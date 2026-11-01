"""Vorschläge des Modells und der Zustand eines Dokuments, wie paperless-pilot ihn verwaltet."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    INFO = "info"


class FieldCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: CheckStatus
    message: str
    evidence: str | None = None


class MetadataValues(BaseModel):
    """Die Felder, die paperless-pilot setzt – aktuell oder vorgeschlagen."""

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    document_type_id: int | None = None
    correspondent_id: int | None = None
    new_correspondent: str | None = (
        None  # nur in Vorschlägen: Korrespondent, den es noch nicht gibt
    )
    created: date | None = None
    person_tag_ids: tuple[int, ...] = ()
    area_tag_id: int | None = None


FIELD_NAMES = ("document_type", "correspondent", "created", "persons", "area", "title")


class SuggestionStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class NewSuggestion(BaseModel):
    document_id: int
    job_id: int | None
    model: str
    host: str
    duration_ms: int
    document_modified: datetime | None
    current: MetadataValues
    proposed: MetadataValues
    checks: dict[str, FieldCheck]
    lesson_ids: list[int] = []  # frühere Korrekturen, die das Modell als Beispiel bekam


class Suggestion(NewSuggestion):
    id: int
    status: SuggestionStatus
    created_at: datetime
    decided_at: datetime | None = None
    note: str | None = None

    def needs_attention(self) -> bool:
        return any(c.status == CheckStatus.WARN for c in self.checks.values())
