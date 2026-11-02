import pytest

from paperless_pilot.domain.ocr_quality import assess_ocr
from paperless_pilot.domain.transcription import (
    MAX_SAME_CHARS,
    check_transcription,
    clean_page,
    iban_is_valid,
    join_pages,
    looks_stuck,
    mrz_check_digit,
    mrz_is_valid,
)
from tests.factories import INVOICE_TEXT

# Musterdaten aus ICAO 9303 (fiktiver Staat „UTO“)
TD1 = [
    "I<UTOD231458907<<<<<<<<<<<<<<<",
    "7408122F1204159UTO<<<<<<<<<<<6",
    "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
]
TD3 = [
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
]
GARBAGE = "if‚‘ “V'j' =«« ;[ ‚ _‚„___„.„_‚_‚}| ﬁfa?“ ‘ ;$r"


def check(old: str, new: str) -> set[str]:
    warnings = check_transcription(old, new, assess_ocr(old), assess_ocr(new))
    return {w.code for w in warnings}


def test_clean_page_removes_code_fence() -> None:
    assert clean_page("```text\nRechnung\n```") == ("Rechnung", False)


def test_clean_page_caps_character_runs() -> None:
    text, capped = clean_page("ANNA" + "<" * 300)

    assert capped
    assert text == "ANNA" + "<" * MAX_SAME_CHARS


def test_clean_page_drops_repeated_lines() -> None:
    text, capped = clean_page("Kopf\n" + "Summe 10,00\n" * 8 + "Ende")

    assert capped
    assert text == "Kopf\n" + "Summe 10,00\n" * 3 + "Ende"


def test_clean_page_keeps_empty_lines_and_short_repeats() -> None:
    assert clean_page("a\n\n\n\nb\nb\nb") == ("a\n\n\n\nb\nb\nb", False)


def test_clean_page_caps_phrase_loops() -> None:
    text, capped = clean_page("Vielen Dank!\n" + "[Bild] " * 200 + "[Bil")

    assert capped
    assert text == "Vielen Dank!\n[Bild] [Bild] [Bild] [Bil"


def test_clean_page_keeps_empty_table_cells_and_drops_markdown_rules() -> None:
    table = "| Anzahl | Text | Preis |\n| :--- | :--- | ---: |\n| 1 | | | | | | 9,00 |"

    assert clean_page(table) == ("| Anzahl | Text | Preis |\n| 1 | | | | | | 9,00 |", False)


def test_looks_stuck_only_at_loops() -> None:
    assert looks_stuck(INVOICE_TEXT + "\n" + "[Bild] " * 20)
    assert looks_stuck("A" + "<" * 60)
    assert not looks_stuck(INVOICE_TEXT)


def test_join_pages_marks_pages_only_when_several() -> None:
    assert join_pages(["eins"]) == "eins"
    assert join_pages(["eins", "zwei"]) == "--- Seite 1 ---\neins\n\n--- Seite 2 ---\nzwei"


def test_good_transcription_of_garbage_has_no_warnings() -> None:
    assert check(GARBAGE * 5, INVOICE_TEXT) == set()


def test_numbers_missing_in_old_text_are_reported() -> None:
    old = INVOICE_TEXT
    new = INVOICE_TEXT.replace("4711", "4777") + "\nKundennummer 998877"

    [warning] = check_transcription(old, new, assess_ocr(old), assess_ocr(new))

    assert warning.code == "new_numbers"
    assert "4777" in warning.message
    assert "998877" in warning.message


def test_numbers_are_matched_despite_ocr_noise() -> None:
    old = INVOICE_TEXT.replace("12.09.2025", "12 . 09.2O25").replace("249,00", "249, 00")

    assert "new_numbers" not in check(old, INVOICE_TEXT)


def test_numbers_are_not_compared_without_old_digits() -> None:
    assert "new_numbers" not in check(GARBAGE, "Kundennummer 998877 vom 12.09.2025")


def test_iban_check_digits() -> None:
    assert iban_is_valid("DE89 3704 0044 0532 0130 00")
    assert not iban_is_valid("DE89 3704 0044 0532 0130 01")
    assert "iban" in check("", "IBAN DE89 3704 0044 0532 0130 01")
    assert "iban" not in check("", "IBAN DE89 3704 0044 0532 0130 00")


def test_mrz_check_digits() -> None:
    assert mrz_check_digit("740812") == 2
    assert mrz_is_valid(TD1)
    assert mrz_is_valid(TD3)
    assert not mrz_is_valid([TD1[0].replace("7<", "4<"), *TD1[1:]])
    assert not mrz_is_valid(TD1[:2])


def test_broken_mrz_is_reported() -> None:
    assert "mrz" not in check("", "\n".join(TD1))
    assert "mrz" in check("", "\n".join([TD1[0], TD1[1].replace("2F", "3F"), TD1[2]]))
    # erfundene, verstümmelte Zeilen, wie sie das Modell im Probelauf geliefert hat
    assert "mrz" in check("", "IDD<X12AB34C5<2910242D<\nMUSTER<ERIKA<<<<<<<<<<<<<<<")
    assert "mrz" in check("", "X12AB34C54<ERIKA" + "<" * 40)


def test_invalid_dates_are_reported() -> None:
    assert "date" in check("", "Datum: 31.02.2025 und 12.13.24")
    assert "date" not in check("", "Datum: 29.02.2024 und 01.01.30")


def test_much_shorter_than_good_old_text() -> None:
    assert "shorter" in check(INVOICE_TEXT, "Rechnung")


@pytest.mark.parametrize("new", [GARBAGE, ""])
def test_not_better_than_before(new: str) -> None:
    assert "not_better" in check(GARBAGE, new)
