"""Domänenmodell: Paperless-Objekte so, wie der Kern sie braucht – unabhängig vom API-Format."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class CustomFieldValue(_Frozen):
    field_id: int
    value: Any


class Document(_Frozen):
    id: int
    title: str
    content: str
    correspondent_id: int | None
    document_type_id: int | None
    storage_path_id: int | None
    tag_ids: tuple[int, ...]
    created: date
    page_count: int | None
    mime_type: str
    original_file_name: str
    custom_fields: tuple[CustomFieldValue, ...] = ()
    modified: datetime | None = None


class Correspondent(_Frozen):
    id: int
    name: str
    document_count: int


class DocumentType(_Frozen):
    id: int
    name: str
    document_count: int


class Tag(_Frozen):
    id: int
    name: str
    document_count: int
    is_inbox_tag: bool


class DocumentPatch(_Frozen):
    """Änderungen an einem Dokument. Nur explizit gesetzte Felder werden geschrieben."""

    title: str | None = None
    correspondent_id: int | None = None
    document_type_id: int | None = None
    storage_path_id: int | None = None
    tag_ids: tuple[int, ...] | None = None
    created: date | None = None
    custom_fields: tuple[CustomFieldValue, ...] | None = None

    def is_empty(self) -> bool:
        return not self.model_fields_set


class PaperlessInfo(_Frozen):
    version: str
    api_version: int
    documents_total: int
    documents_inbox: int


class LlmModel(_Frozen):
    name: str
    size_bytes: int


class HostProbe(_Frozen):
    """Ergebnis einer Erreichbarkeitsprüfung eines Ollama-Rechners."""

    version: str
    models: tuple[LlmModel, ...] = Field(default=())


class FileKind(StrEnum):
    PREVIEW = "preview"
    THUMB = "thumb"


class DocumentFile(_Frozen):
    content: bytes
    media_type: str
