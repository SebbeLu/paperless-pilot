from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.application.transcription import WeakTextScan
from paperless_pilot.domain.errors import (
    ConflictError,
    LlmHostUnavailableError,
    ValidationFailedError,
)
from paperless_pilot.domain.jobs import JobKind, JobStatus
from paperless_pilot.domain.models import HostProbe, LlmModel
from paperless_pilot.domain.suggestions import Suggestion
from tests.clock import FakeClock
from tests.factories import INVOICE_TEXT, answer
from tests.fakes import FakeLlmHost
from tests.pipeline import Pipeline, build_pipeline

GARBAGE = "‚ _‚„___„.„_‚_‚}| ﬁfa?“ ‘ ;$r ;[ =«« " * 10


@pytest.fixture
async def p(engine: AsyncEngine, clock: FakeClock) -> Pipeline:
    pipeline = await build_pipeline(engine, clock, vision=True)
    pipeline.paperless.edit(1, content=GARBAGE)
    await pipeline.registry.refresh()
    return pipeline


async def jobs_of(p: Pipeline) -> list[tuple[JobKind, JobStatus]]:
    return [(j.kind, j.status) for j in sorted(await p.jobs.list(), key=lambda j: j.id)]


async def test_weak_text_is_transcribed_before_extraction(p: Pipeline) -> None:
    mac = p.hosts[0]
    mac.replies += [INVOICE_TEXT, answer()]
    await p.jobs.enqueue(1, JobKind.EXTRACT, p.clock.now(), priority=10)

    assert await p.scheduler.run_once("Mac")  # auslesen → erst abschreiben
    assert await jobs_of(p) == [
        (JobKind.EXTRACT, JobStatus.SUCCEEDED),
        (JobKind.TRANSCRIBE, JobStatus.QUEUED),
    ]
    assert await p.suggestions.list() == []

    assert await p.scheduler.run_once("Mac")  # abschreiben
    stored = await p.transcriptions.for_document(1)
    assert stored is not None
    assert stored.text == INVOICE_TEXT
    assert stored.quality_after.score > stored.quality_before.score
    assert p.pages.files[0][0].content == b"original:1"

    assert await p.scheduler.run_once("Mac")  # auslesen mit der Abschrift
    [suggestion] = await p.suggestions.list()
    assert suggestion.proposed.title == "Bürostuhl"
    assert INVOICE_TEXT.splitlines()[2] in mac.prompts[-1]
    assert GARBAGE not in mac.prompts[-1]
    assert [j.priority for j in await p.jobs.list()] == [10, 10, 10]
    assert {f for _, patch in p.paperless.patches for f in patch.model_fields_set} == {
        "tag_ids"
    }  # nur Status-Tags, der Inhalt wird erst mit der Übernahme geschrieben


async def test_good_text_is_extracted_directly(p: Pipeline) -> None:
    p.hosts[0].replies.append(answer())
    await p.jobs.enqueue(2, JobKind.EXTRACT, p.clock.now())

    await p.scheduler.run_once("Mac")

    assert await jobs_of(p) == [(JobKind.EXTRACT, JobStatus.SUCCEEDED)]
    assert len(await p.suggestions.list()) == 1


async def test_without_vision_host_weak_text_is_extracted_as_is(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    host = FakeLlmHost("Mac", capabilities={"gemma4:26b": frozenset({"completion"})})
    p = await build_pipeline(engine, clock, [host], vision=True)
    p.paperless.edit(1, content=GARBAGE)
    await p.registry.refresh()
    host.replies.append(answer())
    await p.jobs.enqueue(1, JobKind.EXTRACT, p.clock.now())

    await p.scheduler.run_once("Mac")

    assert not p.registry.state("Mac").has_vision
    assert await jobs_of(p) == [(JobKind.EXTRACT, JobStatus.SUCCEEDED)]
    assert len(await p.suggestions.list()) == 1


async def test_host_without_vision_leaves_transcriptions_to_others(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    mac = FakeLlmHost("Mac")
    pc = FakeLlmHost("PC", capabilities={"gemma4:26b": frozenset({"completion"})})
    p = await build_pipeline(engine, clock, [mac, pc], vision=True)
    await p.registry.refresh()
    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())

    assert not await p.scheduler.run_once("PC")
    assert p.registry.state("PC").kinds == {JobKind.EXTRACT}
    assert p.registry.state("Mac").kinds == {JobKind.EXTRACT, JobKind.TRANSCRIBE}


async def test_unreadable_file_falls_back_to_ocr_text(p: Pipeline) -> None:
    p.pages.error = ValidationFailedError("Dateiformat text/plain lässt sich nicht lesen")
    p.hosts[0].replies.append(answer())
    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())

    await p.scheduler.run_once("Mac")
    assert await jobs_of(p) == [
        (JobKind.TRANSCRIBE, JobStatus.FAILED),
        (JobKind.EXTRACT, JobStatus.QUEUED),
    ]

    await p.scheduler.run_once("Mac")  # kein zweiter Versuch, sondern auslesen
    assert len(await p.suggestions.list()) == 1
    assert len(await p.jobs.list()) == 2


async def test_transcription_retries_and_extends_lease(p: Pipeline) -> None:
    p.hosts[0].replies.append(LlmHostUnavailableError("Ollama (Mac)", "weg"))
    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())

    await p.scheduler.run_once("Mac")

    [job] = await p.jobs.list()
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0  # Rechner war das Problem
    assert not p.registry.state("Mac").online


async def test_lease_covers_all_pages(p: Pipeline) -> None:
    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())
    job = await p.jobs.lease_next("Mac", p.clock.now(), timedelta(minutes=12))
    assert job is not None
    p.hosts[0].replies.append(INVOICE_TEXT)

    await p.registry.refresh()
    assert p.processor._vision is not None
    await p.processor._vision.transcribe(job, "Mac")

    [leased] = await p.jobs.list()
    assert leased.lease_expires_at == p.clock.now() + timedelta(minutes=80)


async def test_worse_transcription_is_not_used(p: Pipeline) -> None:
    p.paperless.edit(1, content=INVOICE_TEXT + "\n" + GARBAGE)
    mac = p.hosts[0]
    mac.replies += [GARBAGE, answer()]
    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())

    await p.scheduler.run_once("Mac")
    await p.scheduler.run_once("Mac")

    assert "Rechnung Nr. 4711" in mac.prompts[-1]  # bisheriger Text, nicht die Abschrift


async def test_vision_capability_is_cached_and_survives_offline(p: Pipeline) -> None:
    mac = p.hosts[0]
    await p.registry.refresh()
    assert mac.capability_calls == 1

    mac.error = LlmHostUnavailableError("Ollama (Mac)", "weg")
    await p.registry.refresh()
    assert p.registry.vision_available()


async def test_missing_vision_model_means_no_vision(engine: AsyncEngine, clock: FakeClock) -> None:
    host = FakeLlmHost(
        "Mac", probe=HostProbe(version="1", models=(LlmModel(name="klein", size_bytes=1),))
    )
    p = await build_pipeline(engine, clock, [host], vision=True)

    await p.registry.refresh()

    assert not p.registry.vision_available()
    assert host.capability_calls == 0


async def transcribed_suggestion(p: Pipeline, transcript: str = INVOICE_TEXT) -> Suggestion:
    p.hosts[0].replies += [transcript, answer()]
    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())
    await p.scheduler.run_once("Mac")
    await p.scheduler.run_once("Mac")
    [suggestion] = await p.suggestions.list()
    return suggestion


async def test_suggestion_carries_transcription(p: Pipeline) -> None:
    suggestion = await transcribed_suggestion(p)

    assert suggestion.proposed.content == INVOICE_TEXT
    assert suggestion.current.content is None
    summary = suggestion.transcription
    assert summary is not None
    stored = await p.transcriptions.for_document(1)
    assert stored is not None
    assert summary.transcription_id == stored.id
    assert summary.quality_after > summary.quality_before
    assert summary.warnings == []
    assert (summary.model, summary.host, summary.pages) == ("gemma4:26b", "Mac", 1)


async def test_detail_shows_paperless_text_for_comparison(p: Pipeline) -> None:
    suggestion = await transcribed_suggestion(p)

    assert (await p.review.detail(suggestion.id)).live_content == GARBAGE


async def test_accept_writes_content_and_revert_restores_it(p: Pipeline) -> None:
    suggestion = await transcribed_suggestion(p)

    corrected = suggestion.proposed.model_copy(update={"title": "Bürostuhl Ergo"})

    change = await p.review.accept(suggestion.id, corrected)

    assert p.paperless.documents[1].content == INVOICE_TEXT
    assert change.before.content == GARBAGE
    assert change.after.content == INVOICE_TEXT
    [lesson] = await p.lessons.list()
    assert "content" not in lesson.model_dump_json()

    await p.history.revert(change.id)

    assert p.paperless.documents[1].content == GARBAGE
    reopened = await p.suggestions.get(suggestion.id)
    assert reopened is not None
    assert reopened.proposed.content == INVOICE_TEXT


async def test_accept_without_content_leaves_text_alone(p: Pipeline) -> None:
    suggestion = await transcribed_suggestion(p)

    change = await p.review.accept(
        suggestion.id, suggestion.proposed.model_copy(update={"content": None})
    )

    assert p.paperless.documents[1].content == GARBAGE
    assert change.before.content is None
    assert "content" not in p.paperless.patches[-1][1].model_fields_set


async def test_revert_detects_text_changed_in_paperless(p: Pipeline) -> None:
    suggestion = await transcribed_suggestion(p)
    change = await p.review.accept(suggestion.id, suggestion.proposed)
    p.paperless.edit(1, content="von Hand korrigiert")

    with pytest.raises(ConflictError, match="Inhalt"):
        await p.history.revert(change.id)


@pytest.mark.parametrize(
    ("transcript", "written"),
    [(INVOICE_TEXT, True), (INVOICE_TEXT + "\nIBAN DE89 3704 0044 0532 0130 01", False)],
    ids=["ohne Warnung", "mit Warnung"],
)
async def test_accept_many_writes_content_only_without_warnings(
    p: Pipeline, transcript: str, written: bool
) -> None:
    suggestion = await transcribed_suggestion(p, transcript)

    result = await p.review.accept_many([suggestion.id], with_content=True)

    assert len(result.accepted) == 1
    assert (p.paperless.documents[1].content == transcript) is written


async def test_accept_many_leaves_text_alone_unless_asked(p: Pipeline) -> None:
    suggestion = await transcribed_suggestion(p)

    await p.review.accept_many([suggestion.id])

    assert p.paperless.documents[1].content == GARBAGE


async def test_retranscribe_replaces_transcription_and_suggestion(p: Pipeline) -> None:
    old = await transcribed_suggestion(p)
    p.hosts[0].replies += ["Neu gelesen: Rechnung Bürostuhl 2024", answer()]

    result = await p.review.reextract_documents([1], JobKind.TRANSCRIBE)

    assert result.enqueued == [1]
    assert await p.transcriptions.for_document(1) is None
    superseded = await p.suggestions.get(old.id)
    assert superseded is not None
    assert superseded.note == "Text neu erkennen"
    assert await p.jobs.active_documents(JobKind.TRANSCRIBE) == {1}

    assert await p.scheduler.run_once("Mac")  # abschreiben
    assert await p.scheduler.run_once("Mac")  # auslesen
    [suggestion] = await p.suggestions.list()
    assert suggestion.proposed.content == "Neu gelesen: Rechnung Bürostuhl 2024"


async def test_retranscribe_works_for_documents_with_good_text(p: Pipeline) -> None:
    p.hosts[0].replies += [INVOICE_TEXT, answer()]

    await p.review.reextract_documents([2], JobKind.TRANSCRIBE)
    assert await p.scheduler.run_once("Mac")
    assert await p.scheduler.run_once("Mac")

    stored = await p.transcriptions.for_document(2)
    assert stored is not None
    assert await jobs_of(p) == [
        (JobKind.TRANSCRIBE, JobStatus.SUCCEEDED),
        (JobKind.EXTRACT, JobStatus.SUCCEEDED),
    ]


async def test_weak_text_scan_lists_documents_without_transcription(p: Pipeline) -> None:
    scan = WeakTextScan(p.paperless, p.transcriptions, p.jobs, p.registry, p.clock, threshold=0.68)

    p.paperless.edit(3, content=INVOICE_TEXT)
    first = await scan.get()
    assert first.document_ids == [1]
    assert first.vision_available

    await p.jobs.enqueue(1, JobKind.TRANSCRIBE, p.clock.now())
    assert (await scan.get()).document_ids == []  # wird gerade abgeschrieben

    p.paperless.edit(2, content=GARBAGE)
    assert (await scan.get()).document_ids == []  # zwischengespeichert
    p.clock.advance(minutes=16)
    assert (await scan.get()).document_ids == [2]
    p.paperless.edit(2, content=INVOICE_TEXT)
    assert (await scan.get(refresh=True)).document_ids == []
