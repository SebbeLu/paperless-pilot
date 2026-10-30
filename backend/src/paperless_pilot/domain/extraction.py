"""Auslesen: Schema und Prompt aus der Taxonomie bauen, Modellantwort prüfen und übersetzen.

Grundsatz: Dem Modell wird nicht geglaubt, sondern nachgeprüft. Erlaubte Werte erzwingt das
JSON-Schema schon bei der Erzeugung; Absender und Datum müssen mit einem wörtlichen Zitat belegt
werden, das hier gegen den Dokumenttext geprüft wird.
"""

import re
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.matching import (
    evidence_in_text,
    match_correspondent,
    mentioned,
    normalize_name,
)
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
            Field(
                description="Absender (Firma, Behörde, Praxis), der das Dokument ausgestellt hat "
                "– nicht der Empfänger"
            ),
        ),
        "correspondent_evidence": (
            str,
            Field(description="Wörtliches Zitat aus dem Text, in dem der Absender steht"),
        ),
        # Als Text im deutschen Format: Modelle verdrehen ISO-Daten häufig, „TT.MM.JJJJ“ nicht.
        "document_date": (
            str | None,
            Field(description="Ausstellungsdatum im Format TT.MM.JJJJ, z. B. 05.02.2026"),
        ),
        "date_evidence": (
            str | None,
            Field(description="Wörtliches Zitat aus dem Text, in dem das Datum steht"),
        ),
        "title": (
            str,
            Field(
                description="Neu formulierter kurzer Inhalt, 2–6 Wörter, ohne Datum, ohne "
                "Absender, nicht der Dateiname"
            ),
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
        "Ordne das folgende Dokument ein.\n"
        "- Absender ist, wer das Dokument ausgestellt hat (Firma, Behörde, Praxis, Arbeitgeber). "
        "Personen aus dem Haushalt sind Empfänger, nie Absender.\n"
        "- Datum ist das Ausstellungsdatum, nicht ein Leistungs-, Fälligkeits- oder Geburtsdatum.\n"
        "- Der Titel beschreibt den Inhalt in eigenen Worten; der Dateiname ist meist "
        "nichtssagend.",
        f"Dokumenttypen:\n{listing(taxonomy.document_types)}",
    ]
    if taxonomy.persons:
        sections.append(
            "Personen im Haushalt (wählen, wen das Dokument betrifft, z. B. Empfänger, "
            f"Patient, Versicherter):\n{persons}"
        )
    if taxonomy.areas:
        sections.append(f"Lebensbereiche:\n{listing(taxonomy.areas)}")
    if correspondents:
        sections.append(
            "Bekannte Absender (verwende genau diese Schreibweise, wenn einer passt; "
            "sonst den Namen aus dem Briefkopf):\n" + "\n".join(f"- {c}" for c in correspondents)
        )
    sections.append(
        f"Dateiname: {document.original_file_name}\n\n"
        f"Dokumenttext:\n<<<\n{trim_text(document.content, text_limit)}\n>>>"
    )
    return "\n\n".join(sections)


def candidate_correspondents(
    correspondents: list[Correspondent], taxonomy: Taxonomy
) -> list[Correspondent]:
    """Vorschlagbare Absender: ohne Sammel-Korrespondenten und ohne Personen des Haushalts."""
    household = _household_names(taxonomy)
    return [
        c
        for c in correspondents
        if not taxonomy.is_excluded_correspondent(c.name)
        and normalize_name(c.name) not in household
    ]


def _household_names(taxonomy: Taxonomy) -> set[str]:
    names = {normalize_name(n) for p in taxonomy.persons for n in (p.name, *p.aliases)}
    return {n for n in names if n}


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

    created, checks["created"] = _date(
        parse_german_date(raw["document_date"], today),
        raw["document_date"],
        raw.get("date_evidence"),
        text,
        today,
    )

    persons = [p for p in taxonomy.persons if p.name in raw.get("persons", [])]
    checks["persons"] = _persons_check(persons, text)

    area = _by_name(taxonomy.areas, raw["area"]) if "area" in raw else None
    checks["area"] = _link_check(area, "vom Modell gewählt")

    title, checks["title"] = _title(raw["title"], document)

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
    if normalize_name(name) in _household_names(taxonomy) or any(
        normalize_name(name) in n or n in normalize_name(name)
        for n in _household_names(taxonomy)
        if len(n) > 3
    ):
        return (
            None,
            None,
            FieldCheck(
                status=CheckStatus.WARN,
                message=f"„{name}“ gehört zum Haushalt – vermutlich Empfänger, nicht Absender",
                evidence=evidence or None,
            ),
        )
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


_GERMAN_DATE = re.compile(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4}|\d{2})(?!\d)")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_WORD_DATE = re.compile(r"(\d{1,2})\s*\.?\s*([^\W\d_]{3,})\.?\s*(\d{4})(?!\d)")


def parse_german_date(value: str | None, today: date) -> date | None:
    """„05.02.2026“, „5.2.26“, „5. Februar 2026“ oder ISO „2026-02-05“ → Datum; sonst ``None``."""
    if not value:
        return None
    if match := _WORD_DATE.search(value):
        day, year = int(match[1]), int(match[3])
        if (month := _month_number(match[2])) is None:
            return None
    elif match := _GERMAN_DATE.search(value):
        day, month, year = (int(g) for g in match.groups())
        if year < 100:
            year += 2000 if year <= today.year % 100 else 1900
    elif match := _ISO_DATE.fullmatch(value.strip()):
        year, month, day = (int(g) for g in match.groups())
        if year < EARLIEST_DATE.year // 2:  # verdrehtes ISO-Datum wie „0502-10-20“
            return None
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date(
    value: date | None, raw: str | None, evidence: str | None, text: str, today: date
) -> tuple[date | None, FieldCheck]:
    if value is None:
        if raw:
            return None, FieldCheck(status=CheckStatus.WARN, message=f"Datum „{raw}“ nicht lesbar")
        return None, FieldCheck(status=CheckStatus.INFO, message="kein Datum erkannt")
    if problem := _date_problem(value, evidence, text, today):
        return value, FieldCheck(status=CheckStatus.WARN, message=problem, evidence=evidence)
    return value, FieldCheck(status=CheckStatus.OK, message="belegt", evidence=evidence)


def _date_problem(value: date, evidence: str | None, text: str, today: date) -> str | None:
    if value > today:
        return "liegt in der Zukunft"
    if value < EARLIEST_DATE:
        return "ungewöhnlich alt"
    if not evidence_in_text(evidence, text):
        return "nicht im Text belegt"
    quote = (evidence or "").casefold()
    if str(value.year) not in quote and f"{value.year % 100:02d}" not in quote:
        return "Jahr passt nicht zum Zitat"
    if not _month_in(value.month, quote):
        return "Monat passt nicht zum Zitat"
    return None


_MONTHS = (
    "januar", "februar", "märz", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "dezember",
)  # fmt: skip


_MONTH_ALIASES = {"maerz": 3, "marz": 3, "mar": 3, "march": 3, "may": 5, "june": 6, "july": 7}
_MONTH_ALIASES |= {"oct": 10, "october": 10, "dec": 12, "december": 12}


def _month_number(word: str) -> int | None:
    """Ausgeschriebener oder abgekürzter Monatsname (deutsch oder englisch) → 1–12."""
    word = word.casefold()
    if word in _MONTH_ALIASES:
        return _MONTH_ALIASES[word]
    for number, name in enumerate(_MONTHS, start=1):
        if name.startswith(word) or word.startswith(name):
            return number
    return None


def _month_in(month: int, quote: str) -> bool:
    """Monat als Zahl („07.“, „.7.“) oder ausgeschrieben („Juli“, „Jul“) im Zitat?"""
    name = _MONTHS[month - 1]
    if name in quote or name[:3] in quote:
        return True
    return bool(re.search(rf"(?<!\d)0?{month}\s*\.", quote))


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


def _title(value: str, document: Document) -> tuple[str, FieldCheck]:
    title = " ".join(value.split()).strip(" .-–")
    if not title:
        return "", FieldCheck(status=CheckStatus.WARN, message="kein Titel")
    file_stem = document.original_file_name.rsplit(".", 1)[0]
    if normalize_name(title) in {normalize_name(file_stem), normalize_name(document.title)}:
        return title, FieldCheck(
            status=CheckStatus.WARN, message="entspricht dem Dateinamen bzw. bisherigen Titel"
        )
    if len(title) > TITLE_LIMIT:
        cut = title[:TITLE_LIMIT].rsplit(" ", 1)[0]
        return cut, FieldCheck(status=CheckStatus.INFO, message="gekürzt")
    return title, FieldCheck(status=CheckStatus.OK, message="")
