from datetime import date

import pytest
from pydantic import ValidationError

from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.extraction import (
    build_output_model,
    build_prompt,
    current_values,
    interpret,
    parse_german_date,
    trim_text,
)
from paperless_pilot.domain.suggestions import CheckStatus
from paperless_pilot.domain.taxonomy import Taxonomy
from tests.factories import CORRESPONDENTS, answer, document, taxonomy

TODAY = date(2026, 10, 30)


def run(**overrides: object):  # type: ignore[no-untyped-def]
    tax = overrides.pop("tax", taxonomy())
    doc = overrides.pop("doc", document())
    model = build_output_model(tax)  # type: ignore[arg-type]
    return interpret(model.model_validate(answer(**overrides)), doc, tax, CORRESPONDENTS, TODAY)  # type: ignore[arg-type]


def test_schema_restricts_values_to_taxonomy() -> None:
    model = build_output_model(taxonomy())
    schema = model.model_json_schema()

    assert schema["properties"]["document_type"]["enum"] == ["Rechnung", "Bescheid"]
    assert schema["properties"]["area"]["enum"] == ["Einkauf", "Steuer"]
    with pytest.raises(ValidationError):
        model.model_validate(answer(document_type="{}"))
    with pytest.raises(ValidationError):
        model.model_validate(answer(persons=["Unbekannt"]))


def test_schema_without_persons_and_areas() -> None:
    tax = Taxonomy(document_types=taxonomy().document_types)
    schema = build_output_model(tax).model_json_schema()
    assert "persons" not in schema["properties"]
    assert "area" not in schema["properties"]


def test_schema_needs_document_types() -> None:
    with pytest.raises(ValidationFailedError, match="Dokumenttypen"):
        build_output_model(Taxonomy())


def test_trim_keeps_head_and_tail() -> None:
    text = "A" * 5000 + "MITTE" + "Z" * 5000
    trimmed = trim_text(text, 1000)
    assert trimmed.startswith("A" * 750)
    assert trimmed.endswith("Z" * 250)
    assert "MITTE" not in trimmed
    assert trim_text("  kurz  ") == "kurz"


def test_prompt_contains_taxonomy_hints_and_document() -> None:
    prompt = build_prompt(document(), taxonomy(), ["Muster Möbel GmbH"])

    assert "- Rechnung: Rechnungen, Quittungen" in prompt
    assert "- Alex (auch: Alexandra Muster)" in prompt
    assert "- Einkauf" in prompt
    assert "- Muster Möbel GmbH" in prompt
    assert "Rechnung Nr. 4711" in prompt
    assert "Dateiname: SwiftScan" in prompt
    assert "Bisheriger Titel" not in prompt
    assert "nie Absender" in prompt


def test_happy_path_maps_names_to_paperless_ids() -> None:
    result = run()

    p = result.proposed
    assert (p.document_type_id, p.correspondent_id, p.new_correspondent) == (10, 91, None)
    assert p.created == date(2025, 9, 12)
    assert p.person_tag_ids == (20,)
    assert p.area_tag_id == 30
    assert p.title == "Bürostuhl"
    assert {k: v.status for k, v in result.checks.items()} == {
        "document_type": CheckStatus.OK,
        "correspondent": CheckStatus.OK,
        "created": CheckStatus.OK,
        "persons": CheckStatus.OK,
        "area": CheckStatus.OK,
        "title": CheckStatus.OK,
    }
    assert result.checks["created"].evidence == "Musterstadt, den 12.09.2025"


def test_excluded_collector_is_never_matched() -> None:
    result = run(correspondent="o_Online-Shops", correspondent_evidence="Muster Möbel GmbH")
    assert result.proposed.correspondent_id is None
    assert result.proposed.new_correspondent == "o_Online-Shops"


def test_unknown_correspondent_becomes_new_suggestion() -> None:
    belegt = run(correspondent="Hauptstraße Handel", correspondent_evidence="Hauptstraße 1")
    erfunden = run(correspondent="Phantasie AG", correspondent_evidence="erfunden")
    leer = run(correspondent="  ")

    assert belegt.proposed.new_correspondent == "Hauptstraße Handel"
    assert belegt.checks["correspondent"].status == CheckStatus.INFO
    assert erfunden.checks["correspondent"].status == CheckStatus.WARN
    assert leer.proposed.new_correspondent is None
    assert leer.checks["correspondent"].message == "kein Absender erkannt"


def test_known_correspondent_without_evidence_is_flagged() -> None:
    result = run(correspondent="Finanzamt Musterstadt", correspondent_evidence="erfunden")
    assert result.proposed.correspondent_id == 92
    assert result.checks["correspondent"].status == CheckStatus.WARN


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"document_date": None}, "kein Datum erkannt, bisheriges bleibt"),
        ({"document_date": "01.01.2027"}, "liegt in der Zukunft"),
        ({"document_date": "01.01.1901"}, "ungewöhnlich alt"),
        ({"date_evidence": "am 01.01.2025 erfunden"}, "nicht im Text belegt"),
        ({"document_date": "12.09.2024"}, "Jahr passt nicht zum Zitat"),
        ({"document_date": "0502-10-20"}, "Datum „0502-10-20“ nicht lesbar, bisheriges bleibt"),
        ({"document_date": "12.07.2025"}, "Monat passt nicht zum Zitat"),
    ],
)
def test_date_checks(overrides: dict[str, object], message: str) -> None:
    assert run(**overrides).checks["created"].message == message


@pytest.mark.parametrize("document_date", [None, "0502-10-20"])
def test_unreadable_date_keeps_current(document_date: str | None) -> None:
    doc = document(created=date(2024, 3, 1))
    assert run(doc=doc, document_date=document_date).proposed.created == date(2024, 3, 1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("05.02.2026", date(2026, 2, 5)),
        ("5.2.26", date(2026, 2, 5)),
        ("am 31. 12. 99 ausgestellt", date(1999, 12, 31)),
        ("2026-02-05", date(2026, 2, 5)),
        ("10. September 2025", date(2025, 9, 10)),
        ("10 Sept. 2025", date(2025, 9, 10)),
        ("1. März 2026", date(2026, 3, 1)),
        ("1. Maerz 2026", date(2026, 3, 1)),
        ("1 Mar 2026", date(2026, 3, 1)),
        ("3. Okt. 2025", date(2025, 10, 3)),
        ("24 December 2025", date(2025, 12, 24)),
        ("Musterstadt, den 7. Juli 2025", date(2025, 7, 7)),
        ("10. Foo 2025", None),
        ("31. Februar 2026", None),
        ("31.02.2026", None),
        ("0502-10-20", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_german_date(raw: str | None, expected: date | None) -> None:
    assert parse_german_date(raw, TODAY) == expected


def test_household_member_is_never_the_sender() -> None:
    result = run(correspondent="Alexandra Muster", correspondent_evidence="Frau Alexandra Muster")
    assert result.proposed.correspondent_id is None
    assert result.proposed.new_correspondent is None
    assert "gehört zum Haushalt" in result.checks["correspondent"].message


def test_title_copied_from_filename_is_flagged() -> None:
    result = run(title="SwiftScan 2026-10-07 14.25.56")
    assert result.checks["title"].status == CheckStatus.WARN


@pytest.mark.parametrize(
    "evidence", ["Musterstadt, den 12.09.2025", "im September 2025", "12. Sep. 2025", "12.9.2025"]
)
def test_month_in_words_or_numbers_is_accepted(evidence: str) -> None:
    doc = document(content=f"Rechnung\n{evidence}\nBetrag")
    assert run(doc=doc, date_evidence=evidence).checks["created"].status == CheckStatus.OK


def test_date_only_from_file_name_is_flagged() -> None:
    doc = document(
        content="ueqDsiedojna janss! 31eэ", original_file_name="2021-06-23_Zertifikat.pdf"
    )
    result = run(doc=doc, document_date="23.06.2021", date_evidence="2021-06-23")
    assert result.checks["created"].message == "nur aus dem Dateinamen, nicht im Text belegt"


def test_ocr_garbage_date_is_not_accepted() -> None:
    doc = document(content="Musterstadt, 130t2c26\nBrief")
    result = run(doc=doc, document_date="13.07.26", date_evidence="Musterstadt, 130t2c26")
    assert result.checks["created"].message == "Monat passt nicht zum Zitat"


def test_two_digit_year_in_evidence_is_accepted() -> None:
    doc = document(content="Datum: 12.09.25\nRechnung")
    result = run(doc=doc, date_evidence="Datum: 12.09.25")
    assert result.checks["created"].status == CheckStatus.OK


def test_person_not_in_text_is_flagged() -> None:
    result = run(persons=["Alex", "Kim"])
    assert result.proposed.person_tag_ids == (20, 21)
    assert result.checks["persons"].message == "im Text nicht gefunden: Kim"
    assert run(persons=[]).checks["persons"].message == "keine Person"


def test_unlinked_taxonomy_is_reported() -> None:
    result = run(tax=taxonomy(linked=False))
    assert result.proposed.document_type_id is None
    assert result.proposed.person_tag_ids == ()
    assert result.checks["document_type"].status == CheckStatus.WARN
    assert "nicht mit Paperless verknüpft" in result.checks["persons"].message


@pytest.mark.parametrize(
    ("title", "expected", "status"),
    [
        ("  Bürostuhl  Ergo. ", "Bürostuhl Ergo", CheckStatus.OK),
        ("", "", CheckStatus.WARN),
        ("Wort " * 30, ("Wort " * 16).strip(), CheckStatus.INFO),
    ],
)
def test_title_cleanup(title: str, expected: str, status: CheckStatus) -> None:
    result = run(title=title)
    assert result.proposed.title == expected
    assert result.checks["title"].status == status


def test_current_values_pick_managed_tags() -> None:
    doc = document(tag_ids=(20, 31, 99, 21))
    values = current_values(doc, taxonomy())
    assert values.person_tag_ids == (20, 21)
    assert values.area_tag_id == 31
    assert values.correspondent_id == 90
    assert current_values(document(tag_ids=()), taxonomy()).area_tag_id is None
