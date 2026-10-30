from hypothesis import given
from hypothesis import strategies as st

from paperless_pilot.domain.matching import (
    evidence_in_text,
    match_correspondent,
    mentioned,
    normalize_name,
)
from paperless_pilot.domain.models import Correspondent


def c(cid: int, name: str) -> Correspondent:
    return Correspondent(id=cid, name=name, document_count=0)


def test_normalize_drops_legal_forms_and_punctuation() -> None:
    assert normalize_name("Muster-Werke GmbH & Co. KG") == "muster werke"
    assert normalize_name("Verein für Sport e.V.") == "verein fur sport"
    assert normalize_name("Straßenbau AG") == "strassenbau"


@given(st.text())
def test_normalize_is_idempotent(name: str) -> None:
    once = normalize_name(name)
    assert normalize_name(once) == once


def test_match_prefers_exact_then_fuzzy() -> None:
    candidates = [c(1, "Muster Möbel GmbH"), c(2, "Muster Möbelhaus Nord"), c(3, "Stadtwerke")]

    exact = match_correspondent("Muster Möbel", candidates)
    fuzzy = match_correspondent("Stadtwerke Musterstadt", candidates)

    assert exact is not None
    assert exact.correspondent.id == 1
    assert exact.score == 100
    assert fuzzy is not None
    assert fuzzy.correspondent.id == 3


def test_no_match_for_unrelated_or_empty_names() -> None:
    candidates = [c(1, "Muster Möbel GmbH"), c(2, "GmbH")]
    assert match_correspondent("Finanzamt Musterstadt", candidates) is None
    assert match_correspondent("GmbH", candidates) is None


def test_evidence_tolerates_whitespace_case_and_ocr_noise() -> None:
    text = "Musterstadt,  den 12.09.2025\nRechnung Nr. 4711"
    assert evidence_in_text("musterstadt, den 12.09.2025", text)
    assert evidence_in_text("Rechnunq Nr. 4711", text)  # OCR-Fehler q statt g
    assert not evidence_in_text("Rechnung Nr. 9999 vom 01.01.2020", text)
    assert not evidence_in_text("", text)
    assert not evidence_in_text(None, text)
    assert not evidence_in_text("ab", text)


def test_mentioned_matches_whole_words_only() -> None:
    text = "Patient: Alexandra Muster, geb. 01.01.1990"
    assert mentioned(["Alex", "Alexandra Muster"], text)
    assert not mentioned(["Alex"], text)
    assert not mentioned([""], text)
