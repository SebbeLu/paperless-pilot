from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.domain.errors import LlmHostUnavailableError, ValidationFailedError
from paperless_pilot.domain.jobs import JobKind, JobStatus
from paperless_pilot.domain.models import HostProbe, LlmModel
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
