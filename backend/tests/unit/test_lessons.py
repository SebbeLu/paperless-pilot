from datetime import UTC, date, datetime

from paperless_pilot.domain.extraction import build_prompt
from paperless_pilot.domain.lessons import (
    Lesson,
    NamedValues,
    corrected_fields,
    describe,
    excerpt,
    file_stem,
    named_values,
    select_lessons,
)
from paperless_pilot.domain.suggestions import MetadataValues
from tests.factories import CORRESPONDENTS, INVOICE_TEXT, document, taxonomy

TAX_NOTICE = """Finanzamt Musterstadt · Postfach 9 · 12345 Musterstadt
Bescheid für 2024 über Einkommensteuer
Festgesetzt werden 1.234,00 EUR
Dieser Bescheid ist nach § 165 AO vorläufig. Gegen diesen Bescheid ist der Einspruch zulässig."""


def lesson(lesson_id: int = 1, document_id: int = 50, **overrides: object) -> Lesson:
    values: dict[str, object] = {
        "id": lesson_id,
        "document_id": document_id,
        "suggestion_id": 7,
        "excerpt": excerpt(INVOICE_TEXT),
        "correct": NamedValues(
            document_type="Rechnung",
            correspondent="Muster Möbel GmbH",
            created=date(2025, 9, 12),
            persons=("Alex", "Kim"),
            area="Einkauf",
            title="Bürostuhl",
        ),
        "proposed": NamedValues(
            document_type="Rechnung",
            correspondent="Muster Möbel GmbH",
            created=date(2025, 9, 12),
            persons=("Alex",),
            area="Einkauf",
            title="Bürostuhl",
        ),
        "corrected": ("persons",),
        "created_at": datetime(2026, 10, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return Lesson.model_validate(values)


def test_excerpt_flattens_and_cuts_text() -> None:
    assert excerpt("  Kopf\n\nBetreff  " + "x" * 1000).startswith("Kopf Betreff x")
    assert len(excerpt("x" * 1000)) == 400


def test_named_values_resolve_ids_and_new_correspondent() -> None:
    values = MetadataValues(
        document_type_id=11, correspondent_id=92, person_tag_ids=(21,), area_tag_id=31
    )
    named = named_values(values, taxonomy(), CORRESPONDENTS)
    assert named == NamedValues(
        document_type="Bescheid",
        correspondent="Finanzamt Musterstadt",
        persons=("Kim",),
        area="Steuer",
    )
    new = values.model_copy(update={"correspondent_id": None, "new_correspondent": "Neu GmbH"})
    assert named_values(new, taxonomy(), CORRESPONDENTS).correspondent == "Neu GmbH"


def test_real_changes_count_as_corrections() -> None:
    proposed = NamedValues(document_type="Rechnung", persons=("Alex",), title="Stuhl")
    final = NamedValues(document_type="Bescheid", persons=("Kim", "Alex"), title="stuhl ")
    assert corrected_fields(proposed, final, NamedValues()) == ("document_type", "persons")


def test_keeping_the_previous_value_for_an_empty_proposal_is_no_correction() -> None:
    before = NamedValues(created=date(2020, 9, 4), correspondent="Muster Möbel GmbH")
    proposed = NamedValues()
    assert corrected_fields(proposed, before, before) == ()
    assert corrected_fields(proposed, NamedValues(created=date(2020, 9, 5)), before) == ("created",)


def test_similar_document_gets_lesson_but_not_itself() -> None:
    lessons = [lesson(1, document_id=1), lesson(2, document_id=50)]
    assert [x.id for x in select_lessons(lessons, document(1))] == [2]


def test_unrelated_document_gets_no_lesson() -> None:
    assert select_lessons([lesson()], document(1, content=TAX_NOTICE)) == []


def test_correspondent_in_text_tips_a_moderately_similar_lesson() -> None:
    notice = lesson(
        excerpt="Finanzamt Musterstadt Steuernummer 1 Bescheid über Umsatzsteuer 2023 Nachzahlung "
        "1.000,00 EUR. Die Nachzahlung ist bis zum 15. des Folgemonats fällig, bitte geben Sie "
        "die Steuernummer bei jeder Zahlung und jedem Schreiben an das Amt mit an.",
        correct=NamedValues(document_type="Bescheid", correspondent="Finanzamt Musterstadt"),
    )
    assert select_lessons([notice], document(1, content=TAX_NOTICE)) == [notice]
    unknown = notice.model_copy(update={"correct": NamedValues(correspondent="Bundeszentralamt")})
    assert select_lessons([unknown], document(1, content=TAX_NOTICE)) == []


def test_correspondent_alone_is_not_enough() -> None:
    other_topic = lesson(
        excerpt="Ihr Antrag vom Mai wurde bearbeitet. " * 6,
        correct=NamedValues(correspondent="Finanzamt Musterstadt"),
    )
    assert select_lessons([other_topic], document(1, content=TAX_NOTICE)) == []


def test_selection_prefers_best_match_skips_duplicates_and_limits() -> None:
    duplicates = [lesson(n, document_id=50 + n) for n in range(1, 4)]
    other = lesson(
        9,
        document_id=99,
        correct=NamedValues(document_type="Bescheid", correspondent="Muster Möbel GmbH"),
    )
    chosen = select_lessons([*duplicates, other], document(1), limit=2)
    assert [x.id for x in chosen] == [9, 3]  # gleich ähnlich: neueste zuerst


def test_describe_marks_corrections_and_skips_unchanged_date() -> None:
    lines = describe(lesson())
    assert "- Personen: Alex, Kim (nicht: Alex)" in lines
    assert "- Dokumenttyp: Rechnung" in lines
    assert not any(line.startswith("- Datum") for line in lines)

    dated = lesson(
        corrected=("created",),
        proposed=NamedValues(created=date(2025, 9, 1)),
        correct=NamedValues(created=date(2025, 9, 12)),
    )
    assert describe(dated) == ["- Datum: 12.09.2025 (nicht: 01.09.2025)"]


def test_describe_shows_empty_values_readably() -> None:
    empty = lesson(
        corrected=("persons", "area"),
        proposed=NamedValues(persons=("Alex",)),
        correct=NamedValues(area="Steuer"),
    )
    assert describe(empty) == [
        "- Personen: keine (nicht: Alex)",
        "- Lebensbereich: Steuer (nicht: –)",
    ]


def test_prompt_contains_lessons_before_document() -> None:
    prompt = build_prompt(document(1), taxonomy(), [], lessons=[lesson()])
    examples = prompt.index("Frühere Korrekturen")
    assert examples < prompt.index("Dokumenttext:")
    assert "Beispiel 1 – Datei „“, Textanfang: „Muster Möbel GmbH" in prompt
    assert "- Personen: Alex, Kim (nicht: Alex)" in prompt
    assert "Frühere Korrekturen" not in build_prompt(document(1), taxonomy(), [])


PHOTO_NOISE = "tT S e R O R t e"


def test_noise_text_is_matched_by_file_name_only() -> None:
    photo = lesson(excerpt=PHOTO_NOISE, file_name="2021-03-15 Ultraschall.jpg")
    other_photo = document(
        1, content="e R o S t", original_file_name="2021-03-15 Ultraschall (2).jpg"
    )
    letter = document(1, content=TAX_NOTICE + " " + PHOTO_NOISE)
    camera = document(1, content="e R o S t", original_file_name="IMG_2041.jpg")

    assert select_lessons([photo], other_photo) == [photo]
    assert select_lessons([photo], letter) == []
    assert select_lessons([photo], camera) == []


def test_file_stem_drops_dates_numbers_and_generic_words() -> None:
    assert file_stem("2021-03-15 Ultraschall (2).jpg") == "ultraschall"
    assert file_stem("SwiftScan 2026-10-07 14.25.56.pdf") == ""
