import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.models import Tag
from paperless_pilot.domain.taxonomy import Taxonomy
from tests.clock import FakeClock
from tests.factories import document
from tests.pipeline import Pipeline, build_pipeline

TODO, REVIEW = 40, 41
INBOX = 1


@pytest.fixture
async def p(engine: AsyncEngine, clock: FakeClock) -> Pipeline:
    pipeline = await build_pipeline(engine, clock)
    pipeline.paperless.tags.append(Tag(id=INBOX, name="INBOX", document_count=0, is_inbox_tag=True))
    return pipeline


async def test_collect_enqueues_todo_documents_once(p: Pipeline) -> None:
    p.paperless.edit(1, tag_ids=(TODO,))
    p.paperless.edit(2, tag_ids=(TODO, 5))

    first = await p.intake.collect()
    second = await p.intake.collect()

    assert (first.enqueued, first.already_queued) == (2, 0)
    assert (second.enqueued, second.already_queued) == (0, 2)


async def test_collect_does_nothing_before_taxonomy_is_configured(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    p = await build_pipeline(engine, clock)
    await p.taxonomy.save(Taxonomy(), clock.now())  # Status-Tags ohne Paperless-ID

    assert (await p.intake.collect()).enqueued == 0


async def test_enqueue_inbox_tags_and_skips_processed(p: Pipeline) -> None:
    p.paperless.documents[4] = document(4, tag_ids=(INBOX, REVIEW))
    p.paperless.edit(1, tag_ids=(INBOX,))
    p.paperless.edit(2, tag_ids=(INBOX, TODO))
    p.paperless.edit(3, tag_ids=())

    result = await p.intake.enqueue_inbox()

    assert result.enqueued == 2
    assert TODO in p.paperless.documents[1].tag_ids
    assert [d for d, _ in p.paperless.patches] == [1]  # Dokument 2 hatte den Tag schon
    assert sorted(j.document_id for j in await p.jobs.list()) == [1, 2]


async def test_enqueue_inbox_needs_linked_todo_tag(p: Pipeline) -> None:
    taxonomy, _ = await p.taxonomy.get()
    taxonomy.status.todo.paperless_id = None
    await p.taxonomy.save(taxonomy, p.clock.now())

    with pytest.raises(ValidationFailedError, match="nicht mit Paperless verknüpft"):
        await p.intake.enqueue_inbox()
