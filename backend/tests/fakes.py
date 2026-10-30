"""Attrappen für die Ports – für Tests des Kerns ohne Netzwerk."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from paperless_pilot.domain.availability import EntityState
from paperless_pilot.domain.errors import NotFoundError, PilotError, ServiceUnavailableError
from paperless_pilot.domain.models import (
    Correspondent,
    Document,
    DocumentFile,
    DocumentPatch,
    DocumentType,
    FileKind,
    HostProbe,
    LlmModel,
    PaperlessInfo,
    Tag,
)


class FakeDocumentRepository:
    def __init__(
        self,
        documents: Sequence[Document] = (),
        *,
        info: PaperlessInfo | None = None,
        error: PilotError | None = None,
    ) -> None:
        self.documents = {d.id: d for d in documents}
        self.correspondents: list[Correspondent] = []
        self.document_types: list[DocumentType] = []
        self.tags: list[Tag] = []
        self.patches: list[tuple[int, DocumentPatch]] = []
        self._info = info or PaperlessInfo(
            version="3.2.1", api_version=10, documents_total=len(documents), documents_inbox=0
        )
        self._error = error
        self._id_counter = 1000
        self._modified_counter = 0

    def _fail_if_broken(self) -> None:
        if self._error is not None:
            raise self._error

    async def server_info(self) -> PaperlessInfo:
        self._fail_if_broken()
        return self._info

    async def get_document(self, document_id: int) -> Document:
        self._fail_if_broken()
        try:
            return self.documents[document_id]
        except KeyError:
            raise NotFoundError(str(document_id)) from None

    async def iter_documents(self, *, with_all_tags: Sequence[int] = ()) -> AsyncIterator[Document]:
        self._fail_if_broken()
        for doc in self.documents.values():
            if set(with_all_tags) <= set(doc.tag_ids):
                yield doc

    async def list_correspondents(self) -> list[Correspondent]:
        self._fail_if_broken()
        return self.correspondents

    async def list_document_types(self) -> list[DocumentType]:
        self._fail_if_broken()
        return self.document_types

    async def list_tags(self) -> list[Tag]:
        self._fail_if_broken()
        return self.tags

    async def update_document(self, document_id: int, patch: DocumentPatch) -> Document:
        self._fail_if_broken()
        self.patches.append((document_id, patch))
        doc = await self.get_document(document_id)
        changes = patch.model_dump(exclude_unset=True)
        if "tag_ids" in changes:
            changes["tag_ids"] = tuple(changes["tag_ids"] or ())
        self._modified_counter += 1
        changes["modified"] = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
            seconds=self._modified_counter
        )
        updated = doc.model_copy(update=changes)
        self.documents[document_id] = updated
        return updated

    def _next_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    async def create_tag(self, name: str) -> Tag:
        self._fail_if_broken()
        tag = Tag(id=self._next_id(), name=name, document_count=0, is_inbox_tag=False)
        self.tags.append(tag)
        return tag

    async def create_document_type(self, name: str) -> DocumentType:
        self._fail_if_broken()
        doc_type = DocumentType(id=self._next_id(), name=name, document_count=0)
        self.document_types.append(doc_type)
        return doc_type

    async def create_correspondent(self, name: str) -> Correspondent:
        self._fail_if_broken()
        correspondent = Correspondent(id=self._next_id(), name=name, document_count=0)
        self.correspondents.append(correspondent)
        return correspondent

    async def get_file(self, document_id: int, kind: FileKind) -> DocumentFile:
        await self.get_document(document_id)
        media = "application/pdf" if kind == FileKind.PREVIEW else "image/webp"
        return DocumentFile(content=f"{kind}:{document_id}".encode(), media_type=media)

    def edit(self, document_id: int, **changes: object) -> Document:
        """Ändert ein Dokument „von außen“, also wie jemand direkt in Paperless."""
        self._modified_counter += 1
        changes["modified"] = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
            seconds=self._modified_counter
        )
        updated = self.documents[document_id].model_copy(update=changes)
        self.documents[document_id] = updated
        return updated


class FakeAvailability:
    def __init__(
        self, states: dict[str, EntityState] | None = None, *, broken: bool = False
    ) -> None:
        self.states = states or {}
        self.broken = broken

    async def get_states(self, entity_ids: set[str]) -> dict[str, EntityState]:
        if self.broken:
            raise ServiceUnavailableError("Home Assistant", "aus")
        return {e: s for e, s in self.states.items() if e in entity_ids}


class FakeLlmHost:
    def __init__(
        self,
        name: str = "Mac",
        *,
        probe: HostProbe | None = None,
        replies: Sequence[BaseModel | dict[str, Any] | PilotError] = (),
        error: PilotError | None = None,
    ) -> None:
        self._name = name
        self._probe = probe or HostProbe(
            version="0.24.0", models=(LlmModel(name="gemma4:26b", size_bytes=1),)
        )
        self.replies = list(replies)
        self.error = error
        self.prompts: list[str] = []
        self.systems: list[str | None] = []
        self.models: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def base_url(self) -> str:
        return f"http://{self._name.lower()}.test:11434"

    async def probe(self) -> HostProbe:
        if self.error is not None:
            raise self.error
        return self._probe

    async def generate_structured[T: BaseModel](
        self,
        *,
        model: str,
        prompt: str,
        output_type: type[T],
        system: str | None = None,
        images: Sequence[bytes] = (),
    ) -> T:
        if self.error is not None:
            raise self.error
        self.prompts.append(prompt)
        self.systems.append(system)
        self.models.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, PilotError):
            raise reply
        data = reply.model_dump() if isinstance(reply, BaseModel) else reply
        return output_type.model_validate(data)
