"""Ports: Schnittstellen, über die der Kern mit der Außenwelt spricht.

Adapter (Paperless, Ollama, …) implementieren diese Protokolle; Tests setzen Attrappen ein.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from pydantic import BaseModel

from paperless_pilot.domain.models import (
    Correspondent,
    Document,
    DocumentPatch,
    DocumentType,
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
