"""Lernen aus Korrekturen: übernommene Korrekturen werden zu Beispielen im Prompt.

Das Modell wird nicht nachtrainiert. Stattdessen bekommt es bei ähnlichen Dokumenten gezeigt,
was es früher falsch vorgeschlagen hat und was richtig war.
"""

import re
from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz

from paperless_pilot.domain.changes import DocumentState
from paperless_pilot.domain.matching import mentioned, normalize_name
from paperless_pilot.domain.models import Correspondent, Document
from paperless_pilot.domain.suggestions import MetadataValues
from paperless_pilot.domain.taxonomy import Taxonomy, TaxonomyEntry

EXCERPT_LENGTH = 400
MAX_LESSONS = 3
SIMILARITY_THRESHOLD = 70
CORRESPONDENT_BONUS = 30
LITTLE_TEXT = 200  # darunter ist der OCR-Text meist Zeichensalat, etwa bei Fotos
# Dateinamen von Kameras und Scannern, die nichts über den Inhalt sagen
_GENERIC_FILE_WORDS = {"img", "dsc", "pxl", "scan", "swiftscan", "image", "photo", "foto", "bild"}
_GENERIC_FILE_WORDS |= {"dokument", "document", "seite", "page", "pdf", "jpg", "jpeg", "png"}

LESSON_FIELDS = ("document_type", "correspondent", "created", "persons", "area", "title")
FIELD_LABELS = {
    "document_type": "Dokumenttyp",
    "correspondent": "Absender",
    "created": "Datum",
    "persons": "Personen",
    "area": "Lebensbereich",
    "title": "Titel",
}


class NamedValues(BaseModel):
    """Werte als Namen statt Paperless-IDs – so versteht sie das Modell."""

    model_config = ConfigDict(frozen=True)

    document_type: str | None = None
    correspondent: str | None = None
    created: date | None = None
    persons: tuple[str, ...] = ()
    area: str | None = None
    title: str | None = None


class NewLesson(BaseModel):
    document_id: int
    suggestion_id: int
    excerpt: str
    file_name: str = ""
    correct: NamedValues
    proposed: NamedValues
    corrected: tuple[str, ...]  # Felder aus LESSON_FIELDS, die korrigiert wurden


class Lesson(NewLesson):
    id: int
    created_at: datetime


def excerpt(content: str) -> str:
    """Textanfang ohne Zeilenumbrüche – dort stehen Briefkopf, Betreff und Anrede."""
    return " ".join(content.split())[:EXCERPT_LENGTH]


def named_values(
    values: MetadataValues, taxonomy: Taxonomy, correspondents: Sequence[Correspondent]
) -> NamedValues:
    correspondent = values.new_correspondent or next(
        (c.name for c in correspondents if c.id == values.correspondent_id), None
    )
    return NamedValues(
        document_type=_name_of(taxonomy.document_types, values.document_type_id),
        correspondent=correspondent,
        created=values.created,
        persons=tuple(p.name for p in taxonomy.persons if p.paperless_id in values.person_tag_ids),
        area=_name_of(taxonomy.areas, values.area_tag_id),
        title=values.title,
    )


def values_of_state(state: DocumentState, taxonomy: Taxonomy) -> MetadataValues:
    """Werte nach einer Übernahme aus dem protokollierten Stand des Dokuments."""
    areas = [a.paperless_id for a in taxonomy.areas if a.paperless_id in state.tag_ids]
    return MetadataValues(
        title=state.title,
        document_type_id=state.document_type_id,
        correspondent_id=state.correspondent_id,
        created=state.created,
        person_tag_ids=tuple(
            p.paperless_id for p in taxonomy.persons if p.paperless_id in state.tag_ids
        ),
        area_tag_id=areas[0] if areas else None,
    )


def _name_of(entries: Sequence[TaxonomyEntry], paperless_id: int | None) -> str | None:
    return next((e.name for e in entries if e.paperless_id == paperless_id), None)


def corrected_fields(
    proposed: NamedValues, final: NamedValues, before: NamedValues
) -> tuple[str, ...]:
    """Felder, die du gegenüber dem Vorschlag geändert hast.

    Ein leerer Vorschlag, bei dem einfach der bisherige Wert stehen blieb, ist keine Korrektur.
    """
    corrected = []
    for field in LESSON_FIELDS:
        wanted, got = _comparable(field, final), _comparable(field, proposed)
        if wanted == got:
            continue
        if not got and wanted == _comparable(field, before):
            continue
        corrected.append(field)
    return tuple(corrected)


def _comparable(field: str, values: NamedValues) -> object:
    value = getattr(values, field)
    if field == "correspondent":
        return normalize_name(value or "")  # „Stadtwerke GmbH“ ist „Stadtwerke“
    if isinstance(value, tuple):
        return tuple(sorted(normalize_name(v) for v in value))
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def select_lessons(
    lessons: Sequence[Lesson], document: Document, limit: int = MAX_LESSONS
) -> list[Lesson]:
    """Die ähnlichsten Korrekturen: ähnlicher Textanfang, gleicher Absender im Text oder – bei
    Dokumenten fast ohne Text – ein ähnlicher Dateiname."""
    head = excerpt(document.content).casefold()
    little_text = len(head) < LITTLE_TEXT
    stem = file_stem(document.original_file_name)
    scored: list[tuple[float, Lesson]] = []
    for lesson in lessons:
        if lesson.document_id == document.id:
            continue  # sonst lernt ein Dokument von sich selbst
        if little_text or len(lesson.excerpt) < LITTLE_TEXT:
            # Zeichensalat passt als Teilmenge zu fast jedem Text – hier zählt nur der Dateiname
            other = file_stem(lesson.file_name)
            score = fuzz.token_set_ratio(stem, other) if little_text and stem and other else 0.0
        else:
            score = fuzz.token_set_ratio(head, lesson.excerpt.casefold())
        if lesson.correct.correspondent and mentioned(
            [lesson.correct.correspondent], document.content
        ):
            score += CORRESPONDENT_BONUS
        if score >= SIMILARITY_THRESHOLD:
            scored.append((score, lesson))
    chosen: list[Lesson] = []
    for _, lesson in sorted(scored, key=lambda s: (-s[0], -s[1].id)):
        if all(lesson.correct != c.correct for c in chosen):  # gleiche Lehre nur einmal
            chosen.append(lesson)
        if len(chosen) == limit:
            break
    return chosen


def file_stem(name: str) -> str:
    """„2021-03-15 Ultraschall (2).jpg“ → „ultraschall“; nichtssagende Namen → „“."""
    words = re.split(r"[^a-zäöüß]+", name.casefold())
    return " ".join(w for w in words if len(w) > 2 and w not in _GENERIC_FILE_WORDS)


def describe(lesson: Lesson) -> list[str]:
    """Zeilen für den Prompt: richtige Werte, bei korrigierten Feldern mit dem Fehler von damals."""
    lines = []
    for field in LESSON_FIELDS:
        value = _text(getattr(lesson.correct, field))
        if field == "created" and field not in lesson.corrected:
            continue  # ein unverändertes Datum lehrt nichts über andere Dokumente
        if field in lesson.corrected:
            wrong = _text(getattr(lesson.proposed, field))
            lines.append(f"- {FIELD_LABELS[field]}: {value} (nicht: {wrong})")
        elif getattr(lesson.correct, field):
            lines.append(f"- {FIELD_LABELS[field]}: {value}")
    return lines


def _text(value: object) -> str:
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, tuple):
        return ", ".join(value) or "keine"
    return str(value) if value else "–"
