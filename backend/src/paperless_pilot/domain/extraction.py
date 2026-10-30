"""Auslesen: Schema und Prompt aus der Taxonomie bauen, Modellantwort prüfen und übersetzen.

Grundsatz: Dem Modell wird nicht geglaubt, sondern nachgeprüft. Erlaubte Werte erzwingt das
JSON-Schema schon bei der Erzeugung; Absender und Datum müssen mit einem wörtlichen Zitat belegt
werden, das hier gegen den Dokumenttext geprüft wird.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.matching import evidence_in_text, match_correspondent, mentioned
from paperless_pilot.domain.models import Correspondent, Document
from paperless_pilot.domain.suggestions import CheckStatus, FieldCheck, MetadataValues
from paperless_pilot.domain.taxonomy import Taxonomy, TaxonomyEntry

TEXT_LIMIT = 6000
SHORT_TEXT_LIMIT = 2500
TITLE_LIMIT = 80
EARLIEST_DATE = date(1950, 1, 1)

SYSTEM_PROMPT = (
    "Du bist ein sorgfältiger Archivar für ein privates deutsches Dokumentenarchiv. "
    "Du ordnest ein einzelnes Dokument ein und antwortest ausschließlich im vorgegebenen "
    "JSON-Format. Erfinde nichts: Zitate müssen wörtlich aus dem Dokumenttext stammen. "
    "Wenn eine Angabe nicht im Dokument steht, lass sie leer."
)


def trim_text(content: str, limit: int = TEXT_LIMIT) -> str:
    """Anfang und Ende behalten – dort stehen Absender, Datum und Betreff."""
    content = content.strip()
    if len(content) <= limit:
        return content
    head = limit * 3 // 4
    return f"{content[:head]}\n[…]\n{content[-(limit - head) :]}"


def build_output_model(taxonomy: Taxonomy) -> type[BaseModel]:
    """Pydantic-Modell der erwarteten Antwort; erlaubte Werte werden zu ``enum``."""
    if not taxonomy.document_types:
        msg = "Die Taxonomie enthält noch keine Dokumenttypen (Regeln → Taxonomie)"
        raise ValidationFailedError(msg)

    fields: dict[str, Any] = {
        "document_type": (
            _literal(taxonomy.document_types),
            Field(description="Dokumenttyp aus der Liste"),
        ),
        "correspondent": (
            str,
            Field(description="Absender, so wie er im Briefkopf steht, ohne Adresse"),
        ),
        "correspondent_evidence": (
            str,
            Field(description="Wörtliches Zitat aus dem Text, in dem der Absender steht"),
        ),
        "document_date": (
            date | None,
            Field(description="Ausstellungsdatum (nicht Leistungs- oder Fälligkeitsdatum)"),
        ),
        "date_evidence": (
            str | None,
            Field(description="Wörtliches Zitat aus dem Text, in dem das Datum steht"),
        ),
        "title": (
            str,
            Field(description="Kurzer Inhalt, 2–6 Wörter, ohne Datum und ohne Absender"),
        ),
    }
    if taxonomy.persons:
        list_of: Any = list  # Typ entsteht erst zur Laufzeit aus der Taxonomie
        fields["persons"] = (
            list_of[_literal(taxonomy.persons)],
            Field(description="Personen, die das Dokument betrifft"),
        )
    if taxonomy.areas:
        fields["area"] = (_literal(taxonomy.areas), Field(description="Genau ein Lebensbereich"))
    return create_model("Extraction", **fields)


def _literal(entries: Sequence[TaxonomyEntry]) -> Any:
    return Literal[tuple(e.name for e in entries)]


def build_prompt(
    document: Document,
    taxonomy: Taxonomy,
    correspondents: list[str],
    text_limit: int = TEXT_LIMIT,
) -> str:
    def listing(entries: list[TaxonomyEntry]) -> str:
        return "\n".join(
            f"- {e.name}" + (f": {e.description}" if e.description else "") for e in entries
        )

    persons = "\n".join(
        f"- {p.name}"
        + (f" (auch: {', '.join(p.aliases)})" if p.aliases else "")
        + (f": {p.description}" if p.description else "")
        for p in taxonomy.persons
    )
    sections = [
        "Ordne das folgende Dokument ein.",
        f"Dokumenttypen:\n{listing(taxonomy.document_types)}",
    ]
    if taxonomy.persons:
        sections.append(
            "Personen im Haushalt (nur wählen, wenn das Dokument sie betrifft, "
            f"z. B. als Empfänger oder Patient):\n{persons}"
        )
    if taxonomy.areas:
        sections.append(f"Lebensbereiche:\n{listing(taxonomy.areas)}")
    if correspondents:
        sections.append(
            "Bekannte Absender (verwende genau diese Schreibweise, wenn einer passt; "
            "sonst den Namen aus dem Briefkopf):\n" + "\n".join(f"- {c}" for c in correspondents)
        )
    sections.append(
        f"Dateiname: {document.original_file_name}\n"
        f"Bisheriger Titel: {document.title}\n\n"
        f"Dokumenttext:\n<<<\n{trim_text(document.content, text_limit)}\n>>>"
    )
    return "\n\n".join(sections)


def candidate_correspondents(
    correspondents: list[Correspondent], taxonomy: Taxonomy
) -> list[Correspondent]:
    return [c for c in correspondents if not taxonomy.is_excluded_correspondent(c.name)]


def current_values(document: Document, taxonomy: Taxonomy) -> MetadataValues:
    person_ids = {p.paperless_id for p in taxonomy.persons}
    area_ids = [a.paperless_id for a in taxonomy.areas if a.paperless_id in document.tag_ids]
    return MetadataValues(
        title=document.title,
        document_type_id=document.document_type_id,
        correspondent_id=document.correspondent_id,
        created=document.created,
        person_tag_ids=tuple(t for t in document.tag_ids if t in person_ids),
        area_tag_id=area_ids[0] if area_ids else None,
    )


class Interpretation(BaseModel):
    proposed: MetadataValues
    checks: dict[str, FieldCheck]


def interpret(
    answer: BaseModel,
    document: Document,
    taxonomy: Taxonomy,
    correspondents: list[Correspondent],
    today: date,
) -> Interpretation:
    """Übersetzt die Modellantwort in Paperless-IDs und prüft jedes Feld nach."""
    raw = answer.model_dump()
    text = document.content
    checks: dict[str, FieldCheck] = {}

    doc_type = _by_name(taxonomy.document_types, raw["document_type"])
    checks["document_type"] = _link_check(doc_type, "vom Modell gewählt")

    correspondent_id, new_correspondent, checks["correspondent"] = _correspondent(
        raw["correspondent"], raw["correspondent_evidence"], text, taxonomy, correspondents
    )

    created, checks["created"] = _date(raw["document_date"], raw.get("date_evidence"), text, today)

    persons = [p for p in taxonomy.persons if p.name in raw.get("persons", [])]
    checks["persons"] = _persons_check(persons, text)

    area = _by_name(taxonomy.areas, raw["area"]) if "area" in raw else None
    checks["area"] = _link_check(area, "vom Modell gewählt")

    title, checks["title"] = _title(raw["title"])

    return Interpretation(
        proposed=MetadataValues(
            title=title,
            document_type_id=doc_type.paperless_id if doc_type else None,
            correspondent_id=correspondent_id,
            new_correspondent=new_correspondent,
            created=created,
            person_tag_ids=tuple(p.paperless_id for p in persons if p.paperless_id is not None),
            area_tag_id=area.paperless_id if area else None,
        ),
        checks=checks,
    )


def _by_name[E: TaxonomyEntry](entries: list[E], name: str | None) -> E | None:
    return next((e for e in entries if e.name == name), None)


def _link_check(entry: TaxonomyEntry | None, ok_message: str) -> FieldCheck:
    if entry is None:
        return FieldCheck(status=CheckStatus.INFO, message="keine Angabe")
    if entry.paperless_id is None:
        return FieldCheck(
            status=CheckStatus.WARN,
            message=f"„{entry.name}“ ist noch nicht mit Paperless verknüpft (Regeln → Abgleich)",
        )
    return FieldCheck(status=CheckStatus.OK, message=ok_message)


def _correspondent(
    name: str,
    evidence: str,
    text: str,
    taxonomy: Taxonomy,
    correspondents: list[Correspondent],
) -> tuple[int | None, str | None, FieldCheck]:
    name = " ".join(name.split())
    if not name:
        return None, None, FieldCheck(status=CheckStatus.WARN, message="kein Absender erkannt")
    belegt = evidence_in_text(evidence, text) or evidence_in_text(name, text)
    match = match_correspondent(name, candidate_correspondents(correspondents, taxonomy))
    if match is not None:
        status = CheckStatus.OK if belegt else CheckStatus.WARN
        message = "vorhanden" if belegt else "vorhanden, aber nicht im Text belegt"
        return (
            match.correspondent.id,
            None,
            FieldCheck(status=status, message=message, evidence=evidence or None),
        )
    if belegt:
        check = FieldCheck(
            status=CheckStatus.INFO,
            message="neu – wird beim Übernehmen angelegt",
            evidence=evidence or None,
        )
    else:
        check = FieldCheck(
            status=CheckStatus.WARN,
            message="neu und nicht im Text belegt",
            evidence=evidence or None,
        )
    return None, name, check


def _date(
    value: date | None, evidence: str | None, text: str, today: date
) -> tuple[date | None, FieldCheck]:
    if value is None:
        return None, FieldCheck(status=CheckStatus.INFO, message="kein Datum erkannt")
    if value > today:
        return value, FieldCheck(status=CheckStatus.WARN, message="liegt in der Zukunft")
    if value < EARLIEST_DATE:
        return value, FieldCheck(status=CheckStatus.WARN, message="ungewöhnlich alt")
    if not evidence_in_text(evidence, text):
        return value, FieldCheck(
            status=CheckStatus.WARN, message="nicht im Text belegt", evidence=evidence
        )
    if str(value.year) not in (evidence or "") and f"{value.year % 100:02d}" not in (
        evidence or ""
    ):
        return value, FieldCheck(
            status=CheckStatus.WARN, message="Jahr passt nicht zum Zitat", evidence=evidence
        )
    return value, FieldCheck(status=CheckStatus.OK, message="belegt", evidence=evidence)


def _persons_check(persons: list[Any], text: str) -> FieldCheck:
    if not persons:
        return FieldCheck(status=CheckStatus.INFO, message="keine Person")
    missing = [p.name for p in persons if not mentioned([p.name, *p.aliases], text)]
    unlinked = [p.name for p in persons if p.paperless_id is None]
    if unlinked:
        return FieldCheck(
            status=CheckStatus.WARN,
            message=f"nicht mit Paperless verknüpft: {', '.join(unlinked)}",
        )
    if missing:
        return FieldCheck(
            status=CheckStatus.WARN, message=f"im Text nicht gefunden: {', '.join(missing)}"
        )
    return FieldCheck(status=CheckStatus.OK, message="im Text genannt")


def _title(value: str) -> tuple[str, FieldCheck]:
    title = " ".join(value.split()).strip(" .-–")
    if not title:
        return "", FieldCheck(status=CheckStatus.WARN, message="kein Titel")
    if len(title) > TITLE_LIMIT:
        cut = title[:TITLE_LIMIT].rsplit(" ", 1)[0]
        return cut, FieldCheck(status=CheckStatus.INFO, message="gekürzt")
    return title, FieldCheck(status=CheckStatus.OK, message="")
