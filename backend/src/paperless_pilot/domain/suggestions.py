"""Vorschläge des Modells und der Zustand eines Dokuments, wie paperless-pilot ihn verwaltet."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from paperless_pilot.domain.transcription import StoredTranscription, TranscriptionWarning


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
    content: str | None = None  # nur in Vorschlägen: Abschrift vom Bild (Vision-OCR)


FIELD_NAMES = ("document_type", "correspondent", "created", "persons", "area", "title")


class SuggestionStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TranscriptionSummary(BaseModel):
    """Woher der vorgeschlagene Text stammt und was beim Prüfen auffiel."""

    model_config = ConfigDict(frozen=True)

    transcription_id: int
    pages: int
    rotated_pages: list[int]
    skipped_pages: int
    quality_before: float
    quality_after: float
    warnings: list[TranscriptionWarning]
    model: str
    host: str
    duration_seconds: float

    @classmethod
    def of(cls, stored: StoredTranscription) -> "TranscriptionSummary":
        return cls(
            transcription_id=stored.id,
            pages=stored.pages,
            rotated_pages=stored.rotated_pages,
            skipped_pages=stored.skipped_pages,
            quality_before=stored.quality_before.score,
            quality_after=stored.quality_after.score,
            warnings=stored.warnings,
            model=stored.model,
            host=stored.host,
            duration_seconds=stored.duration_seconds,
        )


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
    transcription: TranscriptionSummary | None = None  # Text kam aus der Vision-OCR


class Suggestion(NewSuggestion):
    id: int
    status: SuggestionStatus
    created_at: datetime
    decided_at: datetime | None = None
    note: str | None = None

    def needs_attention(self) -> bool:
        return any(c.status == CheckStatus.WARN for c in self.checks.values())
