"""Adapter für die REST-API von Paperless-ngx (getestet mit 3.2, API-Version 10)."""

from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from typing import Any, Self

import httpx

from paperless_pilot.domain.errors import (
    AuthenticationError,
    NotFoundError,
    ServiceUnavailableError,
)
from paperless_pilot.domain.models import (
    Correspondent,
    CustomFieldValue,
    Document,
    DocumentFile,
    DocumentPatch,
    DocumentType,
    FileKind,
    PaperlessInfo,
    Tag,
)

API_VERSION = 10
PAGE_SIZE = 100
MATCH_NONE = 0
_SERVICE = "Paperless"

type JsonObject = dict[str, Any]


class PaperlessClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient) -> None:
        self._base = httpx.URL(base_url.rstrip("/") + "/")
        self._http = http
        self._headers = {
            "Authorization": f"Token {token}",
            "Accept": f"application/json; version={API_VERSION}",
        }

    @classmethod
    def create(cls, base_url: str, token: str, timeout: float) -> Self:
        return cls(base_url, token, httpx.AsyncClient(timeout=timeout))

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- DocumentRepository ------------------------------------------------

    async def server_info(self) -> PaperlessInfo:
        response = await self._request("GET", self._url("api/statistics/"))
        data = response.json()
        return PaperlessInfo(
            version=response.headers.get("x-version", "unbekannt"),
            api_version=int(response.headers.get("x-api-version", API_VERSION)),
            documents_total=data["documents_total"],
            documents_inbox=data.get("documents_inbox") or 0,
        )

    async def get_document(self, document_id: int) -> Document:
        response = await self._request("GET", self._url(f"api/documents/{document_id}/"))
        return _to_document(response.json())

    async def iter_documents(self, *, with_all_tags: Sequence[int] = ()) -> AsyncIterator[Document]:
        params: dict[str, str | int] = {"page_size": PAGE_SIZE, "ordering": "id"}
        if with_all_tags:
            params["tags__id__all"] = ",".join(str(t) for t in with_all_tags)
        async for item in self._paginate("api/documents/", params):
            yield _to_document(item)

    async def list_correspondents(self) -> list[Correspondent]:
        return [
            Correspondent(id=i["id"], name=i["name"], document_count=i.get("document_count", 0))
            async for i in self._paginate("api/correspondents/")
        ]

    async def list_document_types(self) -> list[DocumentType]:
        return [
            DocumentType(id=i["id"], name=i["name"], document_count=i.get("document_count", 0))
            async for i in self._paginate("api/document_types/")
        ]

    async def list_tags(self) -> list[Tag]:
        return [
            Tag(
                id=i["id"],
                name=i["name"],
                document_count=i.get("document_count", 0),
                is_inbox_tag=i.get("is_inbox_tag", False),
            )
            async for i in self._paginate("api/tags/")
        ]

    async def update_document(self, document_id: int, patch: DocumentPatch) -> Document:
        if patch.is_empty():
            return await self.get_document(document_id)
        response = await self._request(
            "PATCH", self._url(f"api/documents/{document_id}/"), json=_to_api_patch(patch)
        )
        return _to_document(response.json())

    async def create_tag(self, name: str) -> Tag:
        data = await self._create("api/tags/", name)
        return Tag(id=data["id"], name=data["name"], document_count=0, is_inbox_tag=False)

    async def create_document_type(self, name: str) -> DocumentType:
        data = await self._create("api/document_types/", name)
        return DocumentType(id=data["id"], name=data["name"], document_count=0)

    async def create_correspondent(self, name: str) -> Correspondent:
        data = await self._create("api/correspondents/", name)
        return Correspondent(id=data["id"], name=data["name"], document_count=0)

    async def get_file(self, document_id: int, kind: FileKind) -> DocumentFile:
        response = await self._request("GET", self._url(f"api/documents/{document_id}/{kind}/"))
        return DocumentFile(
            content=response.content,
            media_type=response.headers.get("content-type", "application/octet-stream"),
        )

    # --- intern ------------------------------------------------------------

    async def _create(self, path: str, name: str) -> JsonObject:
        # Keine automatische Zuordnung durch Paperless: paperless-pilot entscheidet selbst.
        body = {"name": name, "matching_algorithm": MATCH_NONE}
        response = await self._request("POST", self._url(path), json=body)
        result: JsonObject = response.json()
        return result

    def _url(self, path: str) -> httpx.URL:
        return self._base.join(path)

    def _rebase(self, absolute: str) -> httpx.URL:
        """Übernimmt Pfad und Query eines ``next``-Links, aber Schema/Host aus der Konfiguration.

        Hinter einem Reverse-Proxy kann Paperless sonst auf einen intern falschen Host verweisen.
        """
        link = httpx.URL(absolute)
        return self._base.copy_with(path=link.path, query=link.query or None)

    async def _paginate(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> AsyncIterator[JsonObject]:
        url: httpx.URL | None = self._url(path)
        query: dict[str, str | int] | None = params or {"page_size": PAGE_SIZE}
        while url is not None:
            data = (await self._request("GET", url, params=query)).json()
            for item in data["results"]:
                yield item
            next_link = data.get("next")
            url = self._rebase(next_link) if next_link else None
            query = None  # steckt bereits im next-Link

    async def _request(
        self,
        method: str,
        url: httpx.URL,
        *,
        params: dict[str, str | int] | None = None,
        json: JsonObject | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method, url, params=params, json=json, headers=self._headers
            )
        except httpx.TimeoutException as exc:
            raise ServiceUnavailableError(_SERVICE, "Zeitüberschreitung") from exc
        except httpx.TransportError as exc:
            raise ServiceUnavailableError(_SERVICE, str(exc) or type(exc).__name__) from exc

        if response.status_code in (401, 403):
            raise AuthenticationError(f"Paperless lehnt den API-Token ab ({response.status_code})")
        if response.status_code == 404:
            raise NotFoundError(f"Paperless: {url.path} nicht gefunden")
        if response.status_code >= 400:
            raise ServiceUnavailableError(
                _SERVICE, f"HTTP {response.status_code}: {response.text[:200]}"
            )
        return response


def _to_document(data: JsonObject) -> Document:
    created_raw = data.get("created_date") or data["created"]
    return Document(
        id=data["id"],
        title=data["title"],
        content=data.get("content") or "",
        correspondent_id=data.get("correspondent"),
        document_type_id=data.get("document_type"),
        storage_path_id=data.get("storage_path"),
        tag_ids=tuple(data.get("tags", ())),
        created=date.fromisoformat(created_raw[:10]),
        page_count=data.get("page_count"),
        mime_type=data.get("mime_type", ""),
        original_file_name=data.get("original_file_name") or "",
        custom_fields=tuple(
            CustomFieldValue(field_id=cf["field"], value=cf.get("value"))
            for cf in data.get("custom_fields", ())
        ),
        modified=datetime.fromisoformat(data["modified"]) if data.get("modified") else None,
    )


_PATCH_FIELD_NAMES = {
    "title": "title",
    "correspondent_id": "correspondent",
    "document_type_id": "document_type",
    "storage_path_id": "storage_path",
    "tag_ids": "tags",
    "created": "created",
    "custom_fields": "custom_fields",
}


def _to_api_patch(patch: DocumentPatch) -> JsonObject:
    body: JsonObject = {}
    for field in patch.model_fields_set:
        value = getattr(patch, field)
        match field:
            case "tag_ids":
                value = list(value or ())
            case "created":
                value = value.isoformat() if value is not None else None
            case "custom_fields":
                value = [{"field": cf.field_id, "value": cf.value} for cf in value or ()]
        body[_PATCH_FIELD_NAMES[field]] = value
    return body
