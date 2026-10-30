"""Attrappen für die Ports – für Tests des Kerns ohne Netzwerk."""

from collections.abc import AsyncIterator, Sequence

from pydantic import BaseModel

from paperless_pilot.domain.errors import NotFoundError, PilotError
from paperless_pilot.domain.models import (
    Correspondent,
    Document,
    DocumentPatch,
    DocumentType,
    HostProbe,
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
        updated = doc.model_copy(update=patch.model_dump(exclude_unset=True))
        self.documents[document_id] = updated
        return updated


class FakeLlmHost:
    def __init__(
        self,
        name: str = "Mac",
        *,
        probe: HostProbe | None = None,
        replies: Sequence[BaseModel] = (),
        error: PilotError | None = None,
    ) -> None:
        self._name = name
        self._probe = probe or HostProbe(version="0.24.0")
        self._replies = list(replies)
        self._error = error
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def base_url(self) -> str:
        return f"http://{self._name.lower()}.test:11434"

    async def probe(self) -> HostProbe:
        if self._error is not None:
            raise self._error
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
        if self._error is not None:
            raise self._error
        self.prompts.append(prompt)
        return output_type.model_validate(self._replies.pop(0).model_dump())
