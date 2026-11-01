"""Erfundene Testdaten – keine echten Dokumente."""

from datetime import UTC, date, datetime
from typing import Any

from paperless_pilot.domain.models import Correspondent, Document
from paperless_pilot.domain.taxonomy import PersonEntry, StatusTags, Taxonomy, TaxonomyEntry

INVOICE_TEXT = """Muster Möbel GmbH · Hauptstraße 1 · 12345 Musterstadt
Frau Alexandra Muster
Rechnung Nr. 4711
Musterstadt, den 12.09.2025
Bürostuhl Ergo, 1 Stück, 249,00 EUR
Gesamtbetrag: 249,00 EUR
Vielen Dank für Ihren Einkauf. Bitte überweisen Sie den Betrag innerhalb von 14 Tagen."""


def document(doc_id: int = 1, **overrides: Any) -> Document:
    values: dict[str, Any] = {
        "id": doc_id,
        "title": "SwiftScan 2026-10-07 14.25.56",
        "content": INVOICE_TEXT,
        "correspondent_id": 90,
        "document_type_id": 91,
        "storage_path_id": None,
        "tag_ids": (1, 50),
        "created": date(2026, 10, 7),
        "page_count": 1,
        "mime_type": "application/pdf",
        "original_file_name": "SwiftScan 2026-10-07 14.25.56.pdf",
        "modified": datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return Document(**values)


def taxonomy(*, linked: bool = True) -> Taxonomy:
    def entry(name: str, pid: int, description: str = "") -> TaxonomyEntry:
        return TaxonomyEntry(
            name=name, description=description, paperless_id=pid if linked else None
        )

    return Taxonomy(
        document_types=[entry("Rechnung", 10, "Rechnungen, Quittungen"), entry("Bescheid", 11)],
        persons=[
            PersonEntry(
                name="Alex", aliases=["Alexandra Muster"], paperless_id=20 if linked else None
            ),
            PersonEntry(name="Kim", paperless_id=21 if linked else None),
        ],
        areas=[entry("Einkauf", 30), entry("Steuer", 31)],
        status=StatusTags(
            todo=entry("ai:todo", 40),
            review=entry("ai:prüfen", 41),
            done=entry("ai:fertig", 42),
            error=entry("ai:fehler", 43),
        ),
    )


CORRESPONDENTS = [
    Correspondent(id=90, name="o_Online-Shops", document_count=99),
    Correspondent(id=91, name="Muster Möbel GmbH", document_count=3),
    Correspondent(id=92, name="Finanzamt Musterstadt", document_count=8),
]


def answer(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "document_type": "Rechnung",
        "correspondent": "Muster Möbel",
        "correspondent_evidence": "Muster Möbel GmbH · Hauptstraße 1",
        "document_date": "12.09.2025",
        "date_evidence": "Musterstadt, den 12.09.2025",
        "persons": ["Alex"],
        "area": "Einkauf",
        "title": "Bürostuhl",
    }
    values.update(overrides)
    return values
