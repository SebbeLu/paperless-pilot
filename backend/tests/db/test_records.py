from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.database import migrate
from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    HostSettingsRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.adapters.db.schema import UtcDateTime
from paperless_pilot.domain.availability import HostRules
from paperless_pilot.domain.changes import Actor, ChangeKind, DocumentState, NewChange
from paperless_pilot.domain.suggestions import (
    CheckStatus,
    FieldCheck,
    MetadataValues,
    NewSuggestion,
    SuggestionStatus,
)
from paperless_pilot.domain.taxonomy import Taxonomy, TaxonomyEntry
from tests.clock import FakeClock


def new_suggestion(document_id: int = 1) -> NewSuggestion:
    return NewSuggestion(
        document_id=document_id,
        job_id=3,
        model="gemma4:26b",
        host="Mac",
        duration_ms=1234,
        document_modified=None,
        current=MetadataValues(title="Scan 1"),
        proposed=MetadataValues(
            title="Bürostuhl", document_type_id=5, created=date(2025, 9, 12), person_tag_ids=(1, 2)
        ),
        checks={
            "created": FieldCheck(status=CheckStatus.OK, message="belegt", evidence="12.09.2025")
        },
    )


async def test_migration_is_repeatable(engine: AsyncEngine) -> None:
    await migrate(engine)  # zweiter Lauf darf nichts kaputt machen


async def test_suggestions_roundtrip_and_supersede(engine: AsyncEngine, clock: FakeClock) -> None:
    repo = SuggestionRepository(engine)

    first = await repo.add(new_suggestion(), clock.now())
    second = await repo.add(new_suggestion(), clock.now())

    assert first.proposed.person_tag_ids == (1, 2)
    assert first.proposed.created == date(2025, 9, 12)
    assert first.checks["created"].evidence == "12.09.2025"
    assert (await repo.get(first.id)).status == SuggestionStatus.SUPERSEDED  # type: ignore[union-attr]
    assert [s.id for s in await repo.list()] == [second.id]
    assert await repo.count_open() == 1

    modified = clock.now()
    await repo.set_document_modified(second.id, modified)
    accepted = await repo.set_status(second.id, SuggestionStatus.ACCEPTED, clock.now(), "ok")

    assert accepted.status == SuggestionStatus.ACCEPTED
    assert accepted.document_modified == modified
    assert accepted.note == "ok"
    assert await repo.count_open() == 0
    assert len(await repo.list(status=None)) == 2
    assert await repo.get(999) is None


async def test_changes_roundtrip(engine: AsyncEngine, clock: FakeClock) -> None:
    repo = ChangeRepository(engine)
    state = DocumentState(
        title="A",
        document_type_id=None,
        correspondent_id=1,
        created=date(2026, 1, 1),
        tag_ids=(3, 1),
    )
    applied = await repo.add(
        NewChange(
            document_id=4,
            suggestion_id=2,
            kind=ChangeKind.APPLY,
            actor=Actor.USER,
            before=state,
            after=state.model_copy(update={"title": "B"}),
        ),
        clock.now(),
    )
    await repo.add(
        NewChange(
            document_id=5,
            suggestion_id=None,
            kind=ChangeKind.APPLY,
            actor=Actor.USER,
            before=state,
            after=state,
        ),
        clock.now(),
    )

    await repo.mark_reverted(applied.id, 42)

    loaded = await repo.get(applied.id)
    assert loaded is not None
    assert loaded.after.title == "B"
    assert loaded.reverted_by == 42
    assert [c.document_id for c in await repo.list()] == [5, 4]
    assert [c.document_id for c in await repo.list(document_id=4)] == [4]
    assert [c.document_id for c in await repo.list(before_id=applied.id + 1, limit=1)] == [4]
    assert await repo.get(999) is None


async def test_host_settings_upsert(engine: AsyncEngine, clock: FakeClock) -> None:
    repo = HostSettingsRepository(engine)
    assert await repo.get_all() == {}

    await repo.save("Mac", HostRules(window="20:00-07:00"), clock.now())
    await repo.save("Mac", HostRules(paused=True), clock.now())

    assert await repo.get_all() == {"Mac": HostRules(paused=True)}


async def test_taxonomy_defaults_then_saved(engine: AsyncEngine, clock: FakeClock) -> None:
    repo = TaxonomyRepository(engine)
    empty, configured = await repo.get()
    assert not configured
    assert empty.status.todo.name == "ai:todo"

    taxonomy = Taxonomy(document_types=[TaxonomyEntry(name="Rechnung", paperless_id=3)])
    await repo.save(taxonomy, clock.now())
    await repo.save(taxonomy, clock.now())

    loaded, configured = await repo.get()
    assert configured
    assert loaded == taxonomy


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="Zeitzone"):
        UtcDateTime().process_bind_param(datetime(2026, 1, 1), None)  # type: ignore[arg-type]
