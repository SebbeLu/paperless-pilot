import json
from collections.abc import AsyncIterator, Iterator
from datetime import date

import httpx
import pytest
import respx

from paperless_pilot.adapters.paperless import API_VERSION, PaperlessClient
from paperless_pilot.domain.errors import (
    AuthenticationError,
    NotFoundError,
    ServiceUnavailableError,
)
from paperless_pilot.domain.models import CustomFieldValue, DocumentPatch, FileKind
from tests.contract import paperless_payloads as p

TOKEN = "test-token"  # noqa: S105


@pytest.fixture
async def client() -> AsyncIterator[PaperlessClient]:
    async with httpx.AsyncClient() as http:
        yield PaperlessClient(p.BASE_URL, TOKEN, http)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=p.BASE_URL, assert_all_called=False) as router:
        yield router


async def test_sends_token_and_pinned_api_version(
    client: PaperlessClient, api: respx.MockRouter
) -> None:
    route = api.get("/api/documents/1/").respond(json=p.document(1))

    await client.get_document(1)

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Token {TOKEN}"
    assert request.headers["Accept"] == f"application/json; version={API_VERSION}"


async def test_maps_document_to_domain(client: PaperlessClient, api: respx.MockRouter) -> None:
    api.get("/api/documents/1/").respond(
        json=p.document(1, custom_fields=[{"field": 2, "value": "EUR42.00"}])
    )

    doc = await client.get_document(1)

    assert doc.id == 1
    assert doc.title == "Rechnung 1"
    assert doc.correspondent_id == 3
    assert doc.document_type_id == 5
    assert doc.tag_ids == (1, 7)
    assert doc.created == date(2026, 10, 7)
    assert doc.page_count == 2
    assert doc.original_file_name == "SwiftScan 2026-10-07 14.25.56.pdf"
    assert doc.custom_fields == (CustomFieldValue(field_id=2, value="EUR42.00"),)


async def test_document_with_datetime_created_and_missing_optionals(
    client: PaperlessClient, api: respx.MockRouter
) -> None:
    payload = p.document(2, content=None, original_file_name=None, correspondent=None)
    del payload["created_date"]
    payload["created"] = "2021-03-15T00:00:00+01:00"
    api.get("/api/documents/2/").respond(json=payload)

    doc = await client.get_document(2)

    assert doc.created == date(2021, 3, 15)
    assert doc.content == ""
    assert doc.original_file_name == ""
    assert doc.correspondent_id is None


async def test_iterates_all_pages_and_rebases_next_link(
    client: PaperlessClient, api: respx.MockRouter
) -> None:
    # Paperless hinter einem Proxy liefert einen next-Link mit internem Host.
    route = api.get("/api/documents/").mock(
        side_effect=[
            httpx.Response(
                200,
                json=p.page(
                    [p.document(1), p.document(2)],
                    next_url="http://internal-host:8000/api/documents/?ordering=id&page=2&page_size=100",
                ),
            ),
            httpx.Response(200, json=p.page([p.document(3)])),
        ]
    )

    ids = [d.id async for d in client.iter_documents()]

    assert ids == [1, 2, 3]
    first, second = (call.request.url for call in route.calls)
    assert dict(first.params) == {"page_size": "100", "ordering": "id"}
    assert second.host == "paperless.test"
    assert dict(second.params) == {"ordering": "id", "page": "2", "page_size": "100"}


async def test_filters_documents_by_tags(client: PaperlessClient, api: respx.MockRouter) -> None:
    route = api.get("/api/documents/").respond(json=p.page([]))

    _ = [d async for d in client.iter_documents(with_all_tags=[1, 9])]

    assert route.calls.last.request.url.params["tags__id__all"] == "1,9"


async def test_lists_taxonomy(client: PaperlessClient, api: respx.MockRouter) -> None:
    api.get("/api/tags/").respond(
        json=p.page([p.tag(1, "INBOX", inbox=True, count=95), p.tag(2, "Steuer", count=141)])
    )
    api.get("/api/correspondents/").respond(json=p.page([p.named(3, "Finanzamt", 8)]))
    api.get("/api/document_types/").respond(json=p.page([p.named(5, "Rechnung", 178)]))

    tags = await client.list_tags()
    correspondents = await client.list_correspondents()
    types = await client.list_document_types()

    assert [(t.name, t.is_inbox_tag, t.document_count) for t in tags] == [
        ("INBOX", True, 95),
        ("Steuer", False, 141),
    ]
    assert correspondents[0].name == "Finanzamt"
    assert types[0].document_count == 178


async def test_server_info_reads_version_headers(
    client: PaperlessClient, api: respx.MockRouter
) -> None:
    api.get("/api/statistics/").respond(
        json=p.STATISTICS, headers={"x-version": "3.2.1", "x-api-version": "10"}
    )

    info = await client.server_info()

    assert info.version == "3.2.1"
    assert info.api_version == 10
    assert info.documents_total == 709
    assert info.documents_inbox == 95


async def test_update_sends_only_set_fields(client: PaperlessClient, api: respx.MockRouter) -> None:
    route = api.patch("/api/documents/1/").respond(json=p.document(1, title="Neu"))
    patch = DocumentPatch(
        title="Neu",
        correspondent_id=None,
        tag_ids=(1, 2),
        created=date(2026, 1, 2),
        custom_fields=(CustomFieldValue(field_id=4, value="X"),),
    )

    doc = await client.update_document(1, patch)

    assert json.loads(route.calls.last.request.content) == {
        "title": "Neu",
        "correspondent": None,
        "tags": [1, 2],
        "created": "2026-01-02",
        "custom_fields": [{"field": 4, "value": "X"}],
    }
    assert doc.title == "Neu"


async def test_empty_update_does_not_write(client: PaperlessClient, api: respx.MockRouter) -> None:
    patch_route = api.patch("/api/documents/1/")
    api.get("/api/documents/1/").respond(json=p.document(1))

    await client.update_document(1, DocumentPatch())

    assert not patch_route.called


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_token_raises_authentication_error(
    client: PaperlessClient, api: respx.MockRouter, status: int
) -> None:
    api.get("/api/statistics/").respond(status_code=status)

    with pytest.raises(AuthenticationError):
        await client.server_info()


async def test_missing_document_raises_not_found(
    client: PaperlessClient, api: respx.MockRouter
) -> None:
    api.get("/api/documents/99/").respond(status_code=404)

    with pytest.raises(NotFoundError):
        await client.get_document(99)


async def test_server_error_raises_unavailable(
    client: PaperlessClient, api: respx.MockRouter
) -> None:
    api.get("/api/statistics/").respond(status_code=502, text="Bad Gateway")

    with pytest.raises(ServiceUnavailableError, match="HTTP 502"):
        await client.server_info()


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("Connection refused"), httpx.ReadTimeout("timed out")],
)
async def test_network_failure_raises_unavailable(
    client: PaperlessClient, api: respx.MockRouter, error: Exception
) -> None:
    api.get("/api/statistics/").mock(side_effect=error)

    with pytest.raises(ServiceUnavailableError):
        await client.server_info()


async def test_create_and_close() -> None:
    client = PaperlessClient.create(p.BASE_URL + "/", TOKEN, timeout=1.0)
    await client.aclose()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("create_tag", "/api/tags/"),
        ("create_document_type", "/api/document_types/"),
        ("create_correspondent", "/api/correspondents/"),
    ],
)
async def test_create_objects_without_auto_matching(
    client: PaperlessClient, api: respx.MockRouter, method: str, path: str
) -> None:
    route = api.post(path).respond(201, json=p.named(42, "Neu"))

    created = await getattr(client, method)("Neu")

    assert created.id == 42
    assert created.name == "Neu"
    assert json.loads(route.calls.last.request.content) == {
        "name": "Neu",
        "matching_algorithm": 0,
    }


@pytest.mark.parametrize(
    ("kind", "media"), [("preview", "application/pdf"), ("thumb", "image/webp")]
)
async def test_get_file_passes_content_and_type(
    client: PaperlessClient, api: respx.MockRouter, kind: str, media: str
) -> None:
    api.get(f"/api/documents/1/{kind}/").respond(content=b"%PDF", headers={"content-type": media})

    file = await client.get_file(1, FileKind(kind))

    assert file.content == b"%PDF"
    assert file.media_type == media


async def test_document_modified_is_parsed(client: PaperlessClient, api: respx.MockRouter) -> None:
    api.get("/api/documents/1/").respond(json=p.document(1))

    doc = await client.get_document(1)

    assert doc.modified is not None
    assert doc.modified.isoformat() == "2026-10-08T09:12:00+02:00"
