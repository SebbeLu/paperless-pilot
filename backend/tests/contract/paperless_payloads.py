"""Synthetische Antworten im Format der Paperless-ngx-API v10 (Form an 3.2.1 abgeglichen).

Bewusst keine echten Dokumente: Die Daten sind erfunden, nur die Struktur ist echt.
"""

from typing import Any

BASE_URL = "http://paperless.test:8000"


def document(doc_id: int = 1, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": doc_id,
        "correspondent": 3,
        "document_type": 5,
        "storage_path": None,
        "title": f"Rechnung {doc_id}",
        "content": "Musterfirma GmbH\nRechnung Nr. 4711\nBetrag: 42,00 EUR",
        "tags": [1, 7],
        "created": "2026-10-07",
        "created_date": "2026-10-07",
        "modified": "2026-10-08T09:12:00.000000+02:00",
        "added": "2026-10-07T14:25:56.000000+02:00",
        "deleted_at": None,
        "archive_serial_number": None,
        "original_file_name": "SwiftScan 2026-10-07 14.25.56.pdf",
        "archived_file_name": "2026-10-07 Rechnung.pdf",
        "duplicate_documents": [],
        "owner": 3,
        "user_can_change": True,
        "is_shared_by_requester": False,
        "notes": [],
        "custom_fields": [],
        "page_count": 2,
        "mime_type": "application/pdf",
        "root_document": None,
        "versions": [],
    }
    data.update(overrides)
    return data


def page(results: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


def tag(tag_id: int, name: str, *, inbox: bool = False, count: int = 0) -> dict[str, Any]:
    return {
        "id": tag_id,
        "slug": name.lower(),
        "name": name,
        "color": "#a6cee3",
        "text_color": "#000000",
        "match": "",
        "matching_algorithm": 1,
        "is_insensitive": True,
        "is_inbox_tag": inbox,
        "document_count": count,
        "owner": 3,
        "user_can_change": True,
        "parent": None,
        "children": [],
    }


def named(obj_id: int, name: str, count: int = 0) -> dict[str, Any]:
    """Korrespondent bzw. Dokumenttyp."""
    return {
        "id": obj_id,
        "slug": name.lower(),
        "name": name,
        "match": "",
        "matching_algorithm": 6,
        "is_insensitive": True,
        "document_count": count,
        "owner": 3,
        "user_can_change": True,
    }


STATISTICS = {
    "documents_total": 709,
    "documents_inbox": 95,
    "inbox_tag": 1,
    "inbox_tags": [1],
    "document_file_type_counts": [],
    "character_count": 1,
    "tag_count": 106,
    "correspondent_count": 44,
    "document_type_count": 30,
    "storage_path_count": 0,
    "current_asn": 0,
}
