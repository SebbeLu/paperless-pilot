from paperless_pilot.domain.models import DocumentPatch


def test_patch_without_fields_is_empty() -> None:
    assert DocumentPatch().is_empty()


def test_explicit_none_counts_as_change() -> None:
    # Korrespondent bewusst entfernen ist eine Änderung, kein leerer Patch.
    assert not DocumentPatch(correspondent_id=None).is_empty()
