import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.domain.errors import NotFoundError, ServiceUnavailableError
from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.models import Correspondent, Tag
from paperless_pilot.domain.suggestions import Suggestion
from tests.clock import FakeClock
from tests.factories import answer
from tests.pipeline import Pipeline, build_pipeline

INBOX, OTHER = 1, 7
TODO, STEUER = 40, 31
ALEX, KIM = 20, 21


@pytest.fixture
async def p(engine: AsyncEngine, clock: FakeClock) -> Pipeline:
    pipeline = await build_pipeline(engine, clock)
    pipeline.paperless.tags.append(Tag(id=INBOX, name="INBOX", document_count=0, is_inbox_tag=True))
    await pipeline.registry.refresh()
    return pipeline


async def suggest(p: Pipeline, document_id: int = 1, **overrides: object) -> Suggestion:
    p.paperless.edit(document_id, tag_ids=(INBOX, OTHER, TODO, STEUER))
    p.hosts[0].replies.append(answer(**overrides))
    await p.jobs.enqueue(document_id, JobKind.EXTRACT, p.clock.now())
    await p.scheduler.run_once("Mac")
    [suggestion] = [s for s in await p.review.list_open() if s.document_id == document_id]
    return suggestion


async def accept_with_kim(p: Pipeline, suggestion: Suggestion) -> None:
    corrected = suggestion.proposed.model_copy(update={"person_tag_ids": (ALEX, KIM)})
    await p.review.accept(suggestion.id, corrected)


async def test_correction_is_learned_and_shown_to_the_model_next_time(p: Pipeline) -> None:
    await accept_with_kim(p, await suggest(p, 1))

    [lesson] = await p.lessons.list()
    assert lesson.document_id == 1
    assert lesson.corrected == ("persons",)
    assert lesson.correct.persons == ("Alex", "Kim")
    assert lesson.excerpt.startswith("Muster Möbel GmbH")

    second = await suggest(p, 2)
    assert second.lesson_ids == [lesson.id]
    assert "- Personen: Alex, Kim (nicht: Alex)" in p.hosts[0].prompts[-1]


async def test_accept_without_correction_learns_nothing(p: Pipeline) -> None:
    suggestion = await suggest(p, 1)
    await p.review.accept(suggestion.id, suggestion.proposed)
    assert await p.lessons.list() == []


async def test_new_correspondent_is_no_correction(p: Pipeline) -> None:
    suggestion = await suggest(
        p, 1, correspondent="Neue Firma", correspondent_evidence="Hauptstraße 1"
    )
    await p.review.accept(suggestion.id, suggestion.proposed)
    assert await p.lessons.list() == []


async def test_failing_lookup_does_not_break_accept(p: Pipeline) -> None:
    suggestion = await suggest(p, 1)

    async def broken() -> list[Correspondent]:
        raise ServiceUnavailableError("Paperless", "Zeitüberschreitung")

    p.paperless.list_correspondents = broken  # type: ignore[method-assign]
    await accept_with_kim(p, suggestion)

    assert set(p.paperless.documents[1].tag_ids) >= {ALEX, KIM}
    assert await p.lessons.list() == []


async def test_revert_forgets_the_correction(p: Pipeline) -> None:
    await accept_with_kim(p, await suggest(p, 1))
    [change] = await p.history.list()

    await p.history.revert(change.id)

    assert await p.lessons.list() == []


async def test_forgotten_lesson_is_not_used_nor_relearned(p: Pipeline) -> None:
    await accept_with_kim(p, await suggest(p, 1))
    [lesson] = await p.lessons.list()

    await p.lessons.forget(lesson.id)

    assert await p.lessons.list() == []
    assert await p.lessons.backfill() == 0
    assert (await suggest(p, 2)).lesson_ids == []
    with pytest.raises(NotFoundError):
        await p.lessons.forget(lesson.id)


async def test_backfill_learns_from_earlier_accepts(p: Pipeline) -> None:
    await accept_with_kim(p, await suggest(p, 1))
    plain = await suggest(p, 2)
    await p.review.accept(plain.id, plain.proposed)
    [lesson] = await p.lessons.list()
    await p.lessons.unlearn(lesson.suggestion_id)  # Stand vor dieser Funktion

    assert await p.lessons.backfill() == 1
    [relearned] = await p.lessons.list()
    assert relearned.document_id == 1
    assert relearned.corrected == ("persons",)
    assert await p.lessons.backfill() == 0


async def test_backfill_skips_documents_paperless_cannot_deliver(p: Pipeline) -> None:
    await accept_with_kim(p, await suggest(p, 1))
    [lesson] = await p.lessons.list()
    await p.lessons.unlearn(lesson.suggestion_id)
    del p.paperless.documents[1]

    assert await p.lessons.backfill() == 0
