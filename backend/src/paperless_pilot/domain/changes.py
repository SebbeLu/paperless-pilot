"""Änderungsprotokoll: jede Schreibaktion in Paperless mit Vorher/Nachher."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from paperless_pilot.domain.models import Document, DocumentPatch


class DocumentState(BaseModel):
    """Die Felder, die paperless-pilot schreibt – Grundlage für Rückgängig."""

    model_config = ConfigDict(frozen=True)

    title: str
    document_type_id: int | None
    correspondent_id: int | None
    created: date
    tag_ids: tuple[int, ...]

    @classmethod
    def of(cls, document: Document) -> "DocumentState":
        return cls(
            title=document.title,
            document_type_id=document.document_type_id,
            correspondent_id=document.correspondent_id,
            created=document.created,
            tag_ids=tuple(sorted(document.tag_ids)),
        )

    def to_patch(self) -> DocumentPatch:
        return DocumentPatch(
            title=self.title,
            document_type_id=self.document_type_id,
            correspondent_id=self.correspondent_id,
            created=self.created,
            tag_ids=self.tag_ids,
        )

    def differs_from(self, other: "DocumentState") -> list[str]:
        return [
            name
            for name in DocumentState.model_fields
            if _normalized(getattr(self, name)) != _normalized(getattr(other, name))
        ]


def _normalized(value: object) -> object:
    return tuple(sorted(value)) if isinstance(value, tuple) else value


class ChangeKind(StrEnum):
    APPLY = "apply"
    REVERT = "revert"


class Actor(StrEnum):
    USER = "user"
    AUTOMATIC = "automatic"


class NewChange(BaseModel):
    document_id: int
    suggestion_id: int | None
    kind: ChangeKind
    actor: Actor
    before: DocumentState
    after: DocumentState


class Change(NewChange):
    id: int
    created_at: datetime
    reverted_by: int | None = None
