import pytest
from pydantic import ValidationError

from paperless_pilot.domain.taxonomy import PersonEntry, Taxonomy, TaxonomyEntry


def test_defaults_contain_status_tags() -> None:
    taxonomy = Taxonomy()
    assert [e.name for e in taxonomy.tag_entries()] == [
        "ai:todo",
        "ai:prüfen",
        "ai:fertig",
        "ai:fehler",
    ]
    assert taxonomy.managed_tag_ids() == set()


def test_managed_tag_ids_cover_persons_areas_and_status() -> None:
    taxonomy = Taxonomy(
        persons=[PersonEntry(name="Alex", paperless_id=1)],
        areas=[TaxonomyEntry(name="Gesundheit", paperless_id=2), TaxonomyEntry(name="Auto")],
    )
    assert taxonomy.managed_tag_ids() == {1, 2}


def test_names_are_trimmed_and_must_not_be_blank() -> None:
    assert TaxonomyEntry(name="  Rechnung ").name == "Rechnung"
    with pytest.raises(ValidationError):
        TaxonomyEntry(name="   ")


@pytest.mark.parametrize(
    "taxonomy",
    [
        {"document_types": [{"name": "Rechnung"}, {"name": "rechnung"}]},
        {"persons": [{"name": "Alex"}], "areas": [{"name": "ALEX"}]},
        {"areas": [{"name": "ai:todo"}]},
    ],
)
def test_duplicate_names_rejected(taxonomy: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="doppelt"):
        Taxonomy.model_validate(taxonomy)


def test_exclude_pattern() -> None:
    taxonomy = Taxonomy()
    assert taxonomy.is_excluded_correspondent("o_Ärzte")
    assert not taxonomy.is_excluded_correspondent("Praxis Dr. Muster")
    assert not Taxonomy(correspondent_exclude_pattern="").is_excluded_correspondent("o_X")
    with pytest.raises(ValidationError, match="regulärer Ausdruck"):
        Taxonomy(correspondent_exclude_pattern="(")
