"""Vision-OCR: Seiten vom Bild abschreiben lassen – und dem Ergebnis nicht blind glauben."""

import calendar
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz

from paperless_pilot.domain.ocr_quality import OcrQuality

TRANSCRIBE_PROMPT = """Schreibe den gesamten Text dieser Dokumentseite wörtlich ab.

Regeln:
- Zeile für Zeile in der Reihenfolge, in der ein Mensch liest; Tabellen zeilenweise, Spalten mit
  „ | “ getrennt.
- Nichts ergänzen, nichts korrigieren, nichts zusammenfassen, keine Erklärungen.
- Umlaute und ß genau so, wie sie gedruckt sind.
- Unleserliches als […], Unterschriften als [Unterschrift], Stempel ohne lesbaren Text als
  [Stempel], Fotos und Logos ohne Text als [Bild]. Handschrift nur, wenn sie eindeutig lesbar ist.
- Ist die Seite leer, antworte nur mit [leer]."""

MAX_SAME_LINES = 3
MAX_SAME_CHARS = 40
# „[Bild] [Bild] [Bild] …“: Wortgruppen bis 4 Wörter, die sich öfter als PHRASE_LOOP-mal
# folgen, gelten als Schleife und werden auf MAX_SAME_PHRASES gekürzt. Leere Tabellenzellen
# („| | | |“) und Nullspalten wiederholen sich auch in echten Dokumenten, daher die hohe Schwelle.
MAX_SAME_PHRASES = 3
PHRASE_LOOP = 8
_LONG_RUN = re.compile(r"(.)\1{%d,}" % MAX_SAME_CHARS)  # noqa: UP031 – Regex-Quantor
_PHRASE_RUN = re.compile(r"((?:\S+[ \t]+){1,4}?)\1{%d,}" % (PHRASE_LOOP - 1))  # noqa: UP031
_FENCE = re.compile(r"^```[a-z]*\n|\n```$")
_TABLE_RULE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*$")  # | :--- | :--- |
_STUCK_TAIL = 600


class RenderedPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    png: bytes
    rotated: int = 0  # Grad im Uhrzeigersinn, um die die Seite aufgerichtet wurde


class TranscriptionWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str


class Transcription(BaseModel):
    """Ergebnis des Abschreibens – noch nichts davon steht in Paperless."""

    document_id: int
    text: str
    pages: int
    rotated_pages: list[int]  # Seitennummern (ab 1), die aufgerichtet wurden
    skipped_pages: int  # über der Höchstzahl, nicht abgeschrieben
    quality_before: OcrQuality
    quality_after: OcrQuality
    warnings: list[TranscriptionWarning]
    model: str
    host: str
    duration_seconds: float


class StoredTranscription(Transcription):
    id: int
    created_at: datetime


def clean_page(raw: str) -> tuple[str, bool]:
    """Codeblock-Hülle entfernen, Endlosschleifen kappen. Zweiter Wert: ob gekappt wurde."""
    text = _FENCE.sub("", raw.strip()).strip()
    capped = False

    def cap_run(match: re.Match[str]) -> str:
        nonlocal capped
        capped = True
        return match.group(1) * MAX_SAME_CHARS

    def cap_phrase(match: re.Match[str]) -> str:
        nonlocal capped
        capped = True
        return match.group(1) * MAX_SAME_PHRASES

    text = _LONG_RUN.sub(cap_run, text)
    text = _PHRASE_RUN.sub(cap_phrase, text + " ").rstrip(" ")
    lines: list[str] = []
    for line in text.splitlines():
        if _TABLE_RULE.match(line):
            continue
        if line.strip() and lines[-MAX_SAME_LINES:] == [line] * MAX_SAME_LINES:
            capped = True
            continue
        lines.append(line)
    return "\n".join(lines).strip(), capped


def looks_stuck(text: str) -> bool:
    """Hängt das Modell in einer Schleife? Für den Abbruch während des Streamings."""
    return clean_page(text[-_STUCK_TAIL:])[1]


def join_pages(pages: list[str]) -> str:
    if len(pages) == 1:
        return pages[0]
    return "\n\n".join(f"--- Seite {n} ---\n{text}" for n, text in enumerate(pages, start=1))


def check_transcription(
    old_text: str, new_text: str, before: OcrQuality, after: OcrQuality
) -> list[TranscriptionWarning]:
    warnings = [*_numbers_only_in_new(old_text, new_text), *_bad_ibans(new_text)]
    warnings += [*_bad_mrz(new_text), *_bad_dates(new_text)]
    if before.word_ratio >= 0.7 and _letters(new_text) < 0.5 * _letters(old_text):
        warnings.append(
            TranscriptionWarning(
                code="shorter",
                message="Deutlich kürzer als der bisherige Text – womöglich fehlt etwas",
            )
        )
    if after.score <= before.score:
        warnings.append(
            TranscriptionWarning(
                code="not_better",
                message=(
                    f"Nicht besser als der bisherige Text "
                    f"(Qualität {before.score:.2f} → {after.score:.2f})"
                ),
            )
        )
    return warnings


# --- Zahlen ---------------------------------------------------------------

_NUMBER_TOKEN = re.compile(r"[\w./:,-]*\d[\w./:,-]*")
_MIN_NUMBER_LENGTH = 4
_MIN_COMPARABLE_DIGITS = 10  # weniger Ziffern im alten Text: kein sinnvoller Vergleich
_NUMBER_MATCH = 85


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def _numbers_only_in_new(old_text: str, new_text: str) -> list[TranscriptionWarning]:
    old = _normalize(old_text)
    if sum(c.isdigit() for c in old) < _MIN_COMPARABLE_DIGITS:
        return []
    missing: list[str] = []
    for token in dict.fromkeys(_NUMBER_TOKEN.findall(new_text)):
        normalized = _normalize(token)
        if sum(c.isdigit() for c in normalized) < _MIN_NUMBER_LENGTH or normalized in old:
            continue
        if fuzz.partial_ratio(normalized, old) < _NUMBER_MATCH:
            missing.append(token.strip(".,:"))
    if not missing:
        return []
    shown = ", ".join(missing[:8]) + (" …" if len(missing) > 8 else "")
    return [
        TranscriptionWarning(
            code="new_numbers",
            message=f"Zahlen, die im bisherigen Text nicht vorkommen: {shown}",
        )
    ]


# --- IBAN (ISO 13616) -----------------------------------------------------

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")


def iban_is_valid(iban: str) -> bool:
    compact = iban.replace(" ", "")
    digits = "".join(str(int(c, 36)) for c in compact[4:] + compact[:4])
    return int(digits) % 97 == 1


def _bad_ibans(text: str) -> list[TranscriptionWarning]:
    return [
        TranscriptionWarning(code="iban", message=f"IBAN-Prüfziffer falsch: {iban}")
        for iban in dict.fromkeys(m.group(0) for m in _IBAN.finditer(text))
        if not iban_is_valid(iban)
    ]


# --- Maschinenlesbare Zone (ICAO 9303) -------------------------------------

_MRZ_LINE = re.compile(r"^[A-Z0-9<]{20,}$")
_MRZ_WEIGHTS = (7, 3, 1)
# Felder mit Prüfziffer: (Zeile, Beginn, Ende, Prüfziffer-Position)
_TD1_FIELDS = ((0, 5, 14, 14), (1, 0, 6, 6), (1, 8, 14, 14))  # Personalausweis, 3 × 30
_TD3_FIELDS = ((1, 0, 9, 9), (1, 13, 19, 19), (1, 21, 27, 27))  # Reisepass, 2 × 44


def mrz_check_digit(field: str) -> int:
    total = 0
    for i, char in enumerate(field):
        value = 0 if char == "<" else int(char, 36)
        total += value * _MRZ_WEIGHTS[i % 3]
    return total % 10


def mrz_is_valid(lines: list[str]) -> bool:
    if len(lines) == 3 and all(len(line) == 30 for line in lines):
        fields = _TD1_FIELDS
    elif len(lines) == 2 and all(len(line) == 44 for line in lines):
        fields = _TD3_FIELDS
    else:
        return False
    for row, start, end, check in fields:
        line = lines[row]
        if not line[check].isdigit() or mrz_check_digit(line[start:end]) != int(line[check]):
            return False
    return True


def _bad_mrz(text: str) -> list[TranscriptionWarning]:
    lines = [line.strip().replace(" ", "") for line in text.splitlines()]
    mrz = [line for line in lines if _MRZ_LINE.match(line) and line.count("<") >= 3]
    if not mrz or mrz_is_valid(mrz):
        return []
    return [
        TranscriptionWarning(
            code="mrz",
            message="Maschinenlesbare Zone unsicher – Prüfziffern stimmen nicht",
        )
    ]


# --- Datum ----------------------------------------------------------------

_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b")


def _bad_dates(text: str) -> list[TranscriptionWarning]:
    bad: list[str] = []
    for match in _DATE.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        year += 2000 if year < 100 else 0
        if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(year, month)[1]:
            bad.append(match.group(0))
    if not bad:
        return []
    return [
        TranscriptionWarning(
            code="date", message=f"Ungültiges Datum: {', '.join(dict.fromkeys(bad))}"
        )
    ]


def _letters(text: str) -> int:
    return sum(c.isalpha() for c in text)
