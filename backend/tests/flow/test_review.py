from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from paperless_pilot.domain.jobs import JobKind, JobStatus
from paperless_pilot.domain.models import Tag
from paperless_pilot.domain.suggestions import MetadataValues, Suggestion, SuggestionStatus
from tests.clock import FakeClock
from tests.factories import answer
from tests.pipeline import Pipeline, build_pipeline

INBOX, OTHER = 1, 7
TODO, REVIEW, DONE = 40, 41, 42
ALEX, KIM, EINKAUF, STEUER = 20, 21, 30, 31


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


async def test_accept_writes_values_tags_and_change(p: Pipeline) -> None:
    suggestion = await suggest(p)

    change = await p.review.accept(suggestion.id, suggestion.proposed)

    doc = p.paperless.documents[1]
    assert doc.title == "Bürostuhl"
    assert doc.document_type_id == 10
    assert doc.correspondent_id == 91
    assert doc.created == date(2025, 9, 12)
    # verwaltete Tags ersetzt, Posteingang entfernt, fremde Tags behalten, Status „fertig“
    assert set(doc.tag_ids) == {OTHER, ALEX, EINKAUF, DONE}
    assert change.before.title == "SwiftScan 2026-10-07 14.25.56"
    assert change.after.title == "Bürostuhl"
    accepted = await p.suggestions.get(suggestion.id)
    assert accepted is not None
    assert accepted.status == SuggestionStatus.ACCEPTED
    assert accepted.note is None
    assert await p.review.list_open() == []


async def test_accept_with_corrections_records_them(p: Pipeline) -> None:
    suggestion = await suggest(p)
    corrected = suggestion.proposed.model_copy(
        update={"title": "Schreibtischstuhl", "person_tag_ids": (ALEX, KIM), "area_tag_id": None}
    )

    await p.review.accept(suggestion.id, corrected)

    doc = p.paperless.documents[1]
    assert doc.title == "Schreibtischstuhl"
    assert set(doc.tag_ids) == {OTHER, ALEX, KIM, DONE}
    accepted = await p.suggestions.get(suggestion.id)
    assert accepted is not None
    assert accepted.note == "korrigiert: Titel, Personen, Lebensbereich"


async def test_accept_creates_new_correspondent_once(p: Pipeline) -> None:
    first = await suggest(p, 1, correspondent="Neue Firma", correspondent_evidence="Hauptstraße 1")
    second = await suggest(p, 2, correspondent="Neue Firma", correspondent_evidence="Hauptstraße 1")
    assert first.proposed.new_correspondent == "Neue Firma"

    await p.review.accept(first.id, first.proposed)
    await p.review.accept(second.id, second.proposed)

    created = [c for c in p.paperless.correspondents if c.name == "Neue Firma"]
    assert len(created) == 1
    assert p.paperless.documents[1].correspondent_id == p.paperless.documents[2].correspondent_id


async def test_empty_title_and_date_keep_existing_values(p: Pipeline) -> None:
    suggestion = await suggest(p)
    values = suggestion.proposed.model_copy(update={"title": "", "created": None})

    await p.review.accept(suggestion.id, values)

    assert p.paperless.documents[1].title == "SwiftScan 2026-10-07 14.25.56"
    assert p.paperless.documents[1].created == date(2026, 10, 7)


async def test_conflict_when_edited_in_paperless_meanwhile(p: Pipeline) -> None:
    suggestion = await suggest(p)
    p.paperless.edit(1, title="Von Hand geändert")

    detail = await p.review.detail(suggestion.id)
    assert detail.changed_since == ["Titel"]
    with pytest.raises(ConflictError) as exc_info:
        await p.review.accept(suggestion.id, suggestion.proposed)
    assert exc_info.value.fields == ["Titel"]

    await p.review.accept(suggestion.id, suggestion.proposed, force=True)
    assert p.paperless.documents[1].title == "Bürostuhl"


async def test_unrelated_edit_is_reported_generically(p: Pipeline) -> None:
    suggestion = await suggest(p)
    p.paperless.edit(1, page_count=9)

    assert (await p.review.detail(suggestion.id)).changed_since == ["andere Felder"]


async def test_reject_removes_review_tag(p: Pipeline) -> None:
    suggestion = await suggest(p)

    rejected = await p.review.reject(suggestion.id, "falsches Dokument")

    assert rejected.status == SuggestionStatus.REJECTED
    assert rejected.note == "falsches Dokument"
    assert REVIEW not in p.paperless.documents[1].tag_ids
    assert INBOX in p.paperless.documents[1].tag_ids


async def test_reextract_requeues_with_priority(p: Pipeline) -> None:
    suggestion = await suggest(p)

    superseded = await p.review.reextract(suggestion.id)

    assert superseded.status == SuggestionStatus.SUPERSEDED
    assert TODO in p.paperless.documents[1].tag_ids
    [job, _] = await p.jobs.list()
    assert job.status == JobStatus.QUEUED
    assert job.priority == 10


async def test_decided_or_unknown_suggestions_are_rejected(p: Pipeline) -> None:
    suggestion = await suggest(p)
    await p.review.reject(suggestion.id)

    with pytest.raises(ValidationFailedError, match="bereits entschieden"):
        await p.review.accept(suggestion.id, MetadataValues())
    with pytest.raises(NotFoundError):
        await p.review.detail(999)


async def test_list_puts_uncertain_suggestions_first(p: Pipeline) -> None:
    sure = await suggest(p, 1)
    unsure = await suggest(p, 2, correspondent="Phantasie AG", correspondent_evidence="erfunden")

    assert [s.id for s in await p.review.list_open()] == [unsure.id, sure.id]


async def test_accept_many_takes_proposals_and_reports_failures(p: Pipeline) -> None:
    first = await suggest(p, 1, title="Schreibtisch")
    edited = await suggest(p, 2)
    p.paperless.edit(2, title="Von Hand geändert")

    result = await p.review.accept_many([first.id, first.id, edited.id, 999])

    assert [c.document_id for c in result.accepted] == [1]
    assert p.paperless.documents[1].title == "Schreibtisch"
    assert [f.suggestion_id for f in result.failed] == [edited.id, 999]
    assert "geändert (Titel)" in result.failed[0].message
    assert [s.id for s in await p.review.list_open()] == [edited.id]
