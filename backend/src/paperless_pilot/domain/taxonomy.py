"""Ziel-Taxonomie: erlaubte Dokumenttypen, Personen, Lebensbereiche und Status-Tags."""

import re
from collections.abc import Iterator
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator


class TaxonomyEntry(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    paperless_id: int | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "Name darf nicht leer sein"
            raise ValueError(msg)
        return value


class PersonEntry(TaxonomyEntry):
    aliases: list[str] = []


class StatusTags(BaseModel):
    todo: TaxonomyEntry = TaxonomyEntry(name="ai:todo", description="wartet auf Auslesen")
    review: TaxonomyEntry = TaxonomyEntry(name="ai:prüfen", description="Vorschlag liegt vor")
    done: TaxonomyEntry = TaxonomyEntry(name="ai:fertig", description="geprüft und übernommen")
    error: TaxonomyEntry = TaxonomyEntry(
        name="ai:fehler", description="konnte nicht ausgelesen werden"
    )


class Taxonomy(BaseModel):
    document_types: list[TaxonomyEntry] = []
    persons: list[PersonEntry] = []
    areas: list[TaxonomyEntry] = []
    status: StatusTags = StatusTags()
    correspondent_exclude_pattern: str = "^o_"
    remove_inbox_tag_on_accept: bool = True

    @field_validator("correspondent_exclude_pattern")
    @classmethod
    def _valid_regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            msg = f"Ungültiger regulärer Ausdruck: {exc}"
            raise ValueError(msg) from exc
        return value

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        _require_unique("Dokumenttypen", [e.name for e in self.document_types])
        _require_unique("Tags", [e.name for e in self.tag_entries()])
        return self

    def tag_entries(self) -> Iterator[TaxonomyEntry]:
        """Alle Einträge, die in Paperless Tags sind."""
        yield from self.persons
        yield from self.areas
        yield from (self.status.todo, self.status.review, self.status.done, self.status.error)

    def managed_tag_ids(self) -> set[int]:
        return {e.paperless_id for e in self.tag_entries() if e.paperless_id is not None}

    def is_excluded_correspondent(self, name: str) -> bool:
        return bool(self.correspondent_exclude_pattern) and bool(
            re.search(self.correspondent_exclude_pattern, name)
        )


def _require_unique(label: str, names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        key = name.casefold()
        if key in seen:
            msg = f"{label}: „{name}“ ist doppelt vorhanden"
            raise ValueError(msg)
        seen.add(key)
