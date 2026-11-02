import pytest

from paperless_pilot.domain.ocr_quality import assess_ocr
from tests.factories import INVOICE_TEXT

THRESHOLD = 0.68


def test_clean_letter_scores_high() -> None:
    quality = assess_ocr(INVOICE_TEXT * 3, page_count=1)

    assert quality.score > 0.9
    assert quality.reasons == ()


def test_empty_text_scores_zero() -> None:
    quality = assess_ocr(" \n\n ", page_count=2)

    assert quality.score == 0
    assert quality.reasons == ("kein Text",)


@pytest.mark.parametrize(
    "content",
    [
        # Zeichensalat aus einem Scan mit Sicherheitsmuster
        "if‚4‘ “V'j'99 =«« ;[ Geburtst39_l0ate ; „ 'Ä\"' ‚ _‚„___„.„_‚_1‚}44| ﬁfa?“ ‘ ;$r " * 20,
        # Schrift ohne Zeichentabelle im PDF: Buchstaben um drei Stellen verschoben
        "OHGLJ 0LW %HLKLOIH ,QIRUPDWLRQHQ ]X ,KUHP $U]W %LWWH JHEHQ 6LH KLHU GHQ 1DPHQ " * 10,
        # gesperrt gesetzte Schrift: jedes Zeichen einzeln
        "R e c h n u n g f ü r H e r r n M u s t e r v o m 1 2 . 0 9 . 2 0 2 5 " * 20,
    ],
    ids=["zeichensalat", "verschoben", "gesperrt"],
)
def test_broken_text_scores_below_threshold(content: str) -> None:
    quality = assess_ocr(content, page_count=1)

    assert quality.score < THRESHOLD
    assert "viele Zeichenfolgen ohne Wortgestalt" in quality.reasons


def test_numbers_and_bullets_are_neutral() -> None:
    words = assess_ocr("Rechnung Datum Betrag", page_count=1)
    with_numbers = assess_ocr("Rechnung 12.09.2025 Datum 249,00 € – Betrag • 14:30", page_count=1)

    assert with_numbers.word_ratio == words.word_ratio == 1


def test_codes_and_words_without_vowels_count_as_garbage() -> None:
    quality = assess_ocr("Rechnung 130t2c26 Datum xkcdq", page_count=1)

    assert quality.word_ratio == 0.5


def test_little_text_per_page_is_reported() -> None:
    quality = assess_ocr("Rechnung für Sie", page_count=4)

    assert "wenig Text je Seite" in quality.reasons
    assert quality.chars_per_page == 3.5


def test_unknown_page_count_counts_as_one_page() -> None:
    assert assess_ocr("Rechnung", page_count=None).chars_per_page == 8
