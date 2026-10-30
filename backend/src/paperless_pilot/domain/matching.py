"""Unscharfer Abgleich: Korrespondenten-Namen und Belegzitate im Dokumenttext."""

import re
import unicodedata
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz

from paperless_pilot.domain.models import Correspondent

CORRESPONDENT_THRESHOLD = 90
EVIDENCE_THRESHOLD = 90
MIN_EVIDENCE_LENGTH = 3

# Rechtsformen und Füllwörter, die beim Vergleich von Firmennamen nicht zählen
_LEGAL_FORMS = {
    "gmbh", "mbh", "ag", "kg", "ohg", "gbr", "ug", "se", "ev", "e", "v", "co", "kgaa",
    "haftungsbeschrankt", "inc", "ltd", "limited", "llc", "plc", "sa", "sarl", "bv", "nv",
}  # fmt: skip
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize_name(name: str) -> str:
    """„Muster-Werke GmbH & Co. KG“ → „muster werke“."""
    folded = _fold(name)
    words = [w for w in _NON_WORD.split(folded) if w and w not in _LEGAL_FORMS]
    return " ".join(words)


def _fold(text: str) -> str:
    """Groß/klein, Akzente und Kompatibilitätszeichen (z. B. „𝐀“) vereinheitlichen."""
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", text).casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


class CorrespondentMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    correspondent: Correspondent
    score: float


def match_correspondent(
    name: str, candidates: Iterable[Correspondent]
) -> CorrespondentMatch | None:
    """Bester vorhandener Korrespondent zum vorgeschlagenen Namen – oder keiner."""
    wanted = normalize_name(name)
    if not wanted:
        return None
    best: CorrespondentMatch | None = None
    for candidate in candidates:
        existing = normalize_name(candidate.name)
        if not existing:
            continue
        score = 100.0 if existing == wanted else fuzz.token_set_ratio(wanted, existing)
        if score >= CORRESPONDENT_THRESHOLD and (best is None or score > best.score):
            best = CorrespondentMatch(correspondent=candidate, score=score)
    return best


def _flatten(text: str) -> str:
    return " ".join(_fold(text).split())


def evidence_in_text(evidence: str | None, text: str) -> bool:
    """Steht das Zitat (abgesehen von OCR-Unschärfe und Leerraum) wirklich im Text?"""
    if not evidence or len(evidence.strip()) < MIN_EVIDENCE_LENGTH:
        return False
    needle = _flatten(evidence)
    haystack = _flatten(text)
    if needle in haystack:
        return True
    return fuzz.partial_ratio(needle, haystack) >= EVIDENCE_THRESHOLD


def mentioned(names: Iterable[str], text: str) -> bool:
    """Kommt einer der Namen als ganzes Wort im Text vor?"""
    haystack = _flatten(text)
    for name in names:
        needle = _flatten(name)
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            return True
    return False
