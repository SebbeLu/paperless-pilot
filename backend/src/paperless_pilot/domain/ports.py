"""Ports: Schnittstellen, über die der Kern mit der Außenwelt spricht.

Adapter (Paperless, Ollama, …) implementieren diese Protokolle; Tests setzen Attrappen ein.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from pydantic import BaseModel

from paperless_pilot.domain.availability import EntityState
from paperless_pilot.domain.models import (
    Correspondent,
    Document,
    DocumentFile,
    DocumentPatch,
    DocumentType,
    FileKind,
    HostProbe,
    PaperlessInfo,
    Tag,
)


class DocumentRepository(Protocol):
    async def server_info(self) -> PaperlessInfo: ...

    async def get_document(self, document_id: int) -> Document: ...

    def iter_documents(self, *, with_all_tags: Sequence[int] = ()) -> AsyncIterator[Document]: ...

    async def list_correspondents(self) -> list[Correspondent]: ...

    async def list_document_types(self) -> list[DocumentType]: ...

    async def list_tags(self) -> list[Tag]: ...

    async def update_document(self, document_id: int, patch: DocumentPatch) -> Document: ...

    async def create_tag(self, name: str) -> Tag: ...

    async def create_document_type(self, name: str) -> DocumentType: ...

    async def create_correspondent(self, name: str) -> Correspondent: ...

    async def get_file(self, document_id: int, kind: FileKind) -> DocumentFile: ...


class LlmHost(Protocol):
    """Ein Rechner, auf dem Sprachmodelle laufen."""

    @property
    def name(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    async def probe(self) -> HostProbe: ...

    async def generate_structured[T: BaseModel](
        self,
        *,
        model: str,
        prompt: str,
        output_type: type[T],
        system: str | None = None,
        images: Sequence[bytes] = (),
    ) -> T: ...


class AvailabilitySource(Protocol):
    """Liefert Zustände von Entitäten (Home Assistant)."""

    async def get_states(self, entity_ids: set[str]) -> dict[str, EntityState]: ...
