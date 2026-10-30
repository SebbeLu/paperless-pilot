import pytest

from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.models import Correspondent
from tests.api.conftest import Api
from tests.factories import CORRESPONDENTS, answer, document, taxonomy


@pytest.fixture
async def ready(api: Api) -> Api:
    await api.container.taxonomy_repository.save(taxonomy(), api.clock.now())
    api.paperless.documents[1] = document(1, tag_ids=(40,))
    api.paperless.correspondents.extend(CORRESPONDENTS)
    api.hosts[0].replies.append(answer())
    await api.container.registry.refresh()
    await api.container.jobs.enqueue(1, JobKind.EXTRACT, api.clock.now())
    await api.container.scheduler.run_once("Mac")
    return api


async def test_list_detail_accept(ready: Api) -> None:
    [item] = (await ready.client.get("/api/suggestions")).json()
    detail = (await ready.client.get(f"/api/suggestions/{item['id']}")).json()

    assert item["proposed"]["title"] == "Bürostuhl"
    assert item["checks"]["created"]["status"] == "ok"
    assert detail["live"]["correspondent_id"] == 90
    assert detail["original_file_name"].startswith("SwiftScan")
    assert detail["changed_since"] == []

    response = await ready.client.post(
        f"/api/suggestions/{item['id']}/accept", json={"values": item["proposed"]}
    )

    assert response.status_code == 200
    assert response.json()["after"]["title"] == "Bürostuhl"
    assert (await ready.client.get("/api/suggestions")).json() == []
    accepted = (await ready.client.get("/api/suggestions?status=accepted")).json()
    assert [s["id"] for s in accepted] == [item["id"]]


async def test_conflict_is_409_with_fields(ready: Api) -> None:
    [item] = (await ready.client.get("/api/suggestions")).json()
    ready.paperless.edit(1, correspondent_id=92)

    response = await ready.client.post(
        f"/api/suggestions/{item['id']}/accept", json={"values": item["proposed"]}
    )
    forced = await ready.client.post(
        f"/api/suggestions/{item['id']}/accept", json={"values": item["proposed"], "force": True}
    )

    assert response.status_code == 409
    assert response.json()["conflict"] == ["Absender"]
    assert forced.status_code == 200


async def test_reject_and_reextract(ready: Api) -> None:
    [item] = (await ready.client.get("/api/suggestions")).json()

    rejected = await ready.client.post(f"/api/suggestions/{item['id']}/reject", json={})
    again = await ready.client.post(f"/api/suggestions/{item['id']}/reextract")

    assert rejected.json()["status"] == "rejected"
    assert again.status_code == 400
    assert "bereits entschieden" in again.json()["detail"]


async def test_reextract(ready: Api) -> None:
    [item] = (await ready.client.get("/api/suggestions")).json()

    response = await ready.client.post(f"/api/suggestions/{item['id']}/reextract")

    assert response.json()["status"] == "superseded"
    assert (await ready.container.jobs.stats()).queued == 1


async def test_unknown_suggestion_is_404(api: Api) -> None:
    assert (await api.client.get("/api/suggestions/42")).status_code == 404


async def test_document_preview_is_proxied(api: Api) -> None:
    api.paperless.documents[3] = document(3)
    api.paperless.correspondents.append(Correspondent(id=1, name="x", document_count=0))

    preview = await api.client.get("/api/documents/3/preview")
    thumb = await api.client.get("/api/documents/3/thumb")
    missing = await api.client.get("/api/documents/99/preview")
    invalid = await api.client.get("/api/documents/3/original")

    assert preview.headers["content-type"] == "application/pdf"
    assert preview.content == b"preview:3"
    assert thumb.headers["content-type"] == "image/webp"
    assert missing.status_code == 404
    assert invalid.status_code == 422
