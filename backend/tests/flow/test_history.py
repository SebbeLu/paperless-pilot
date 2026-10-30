import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.domain.changes import ChangeKind
from paperless_pilot.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.suggestions import SuggestionStatus
from tests.clock import FakeClock
from tests.factories import answer
from tests.pipeline import Pipeline, build_pipeline

TODO, REVIEW = 40, 41


@pytest.fixture
async def p(engine: AsyncEngine, clock: FakeClock) -> Pipeline:
    pipeline = await build_pipeline(engine, clock)
    await pipeline.registry.refresh()
    pipeline.paperless.edit(1, tag_ids=(TODO, 7))
    pipeline.hosts[0].replies.append(answer())
    await pipeline.jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await pipeline.scheduler.run_once("Mac")
    return pipeline


async def accept(p: Pipeline) -> int:
    [suggestion] = await p.review.list_open()
    change = await p.review.accept(suggestion.id, suggestion.proposed)
    return change.id


async def test_revert_restores_previous_state_and_reopens_suggestion(p: Pipeline) -> None:
    before = p.paperless.documents[1]
    change_id = await accept(p)

    revert = await p.history.revert(change_id)

    restored = p.paperless.documents[1]
    assert restored.title == before.title
    assert restored.correspondent_id == before.correspondent_id
    assert set(restored.tag_ids) == {7, REVIEW}
    assert revert.kind == ChangeKind.REVERT
    original = await p.changes.get(change_id)
    assert original is not None
    assert original.reverted_by == revert.id
    [reopened] = await p.review.list_open()
    assert reopened.status == SuggestionStatus.OPEN
    # Wieder übernehmbar, ohne Konflikt durch die eigene Rücknahme
    await p.review.accept(reopened.id, reopened.proposed)
    assert [c.kind for c in await p.history.list()] == ["apply", "revert", "apply"][::-1]


async def test_revert_detects_later_edits(p: Pipeline) -> None:
    change_id = await accept(p)
    p.paperless.edit(1, title="Danach von Hand geändert")

    with pytest.raises(ConflictError) as exc_info:
        await p.history.revert(change_id)
    assert exc_info.value.fields == ["Titel"]

    await p.history.revert(change_id, force=True)
    assert p.paperless.documents[1].title.startswith("SwiftScan")


async def test_revert_only_once_and_only_applies(p: Pipeline) -> None:
    change_id = await accept(p)
    revert = await p.history.revert(change_id)

    with pytest.raises(ValidationFailedError, match="bereits rückgängig"):
        await p.history.revert(change_id)
    with pytest.raises(ValidationFailedError, match="Nur Übernahmen"):
        await p.history.revert(revert.id)
    with pytest.raises(NotFoundError):
        await p.history.revert(999)


async def test_list_filters_and_pages(p: Pipeline) -> None:
    change_id = await accept(p)
    await p.history.revert(change_id)

    assert len(await p.history.list(document_id=1)) == 2
    assert await p.history.list(document_id=2) == []
    newest = await p.history.list(limit=1)
    older = await p.history.list(before_id=newest[0].id)
    assert [c.id for c in older] == [change_id]
