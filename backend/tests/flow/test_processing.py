import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.application.background import run_background
from paperless_pilot.domain.availability import EntityState, HostRules
from paperless_pilot.domain.errors import (
    InvalidLlmOutputError,
    LlmHostUnavailableError,
    ServiceUnavailableError,
)
from paperless_pilot.domain.jobs import JobKind, JobStatus
from paperless_pilot.domain.models import HostProbe
from paperless_pilot.domain.suggestions import SuggestionStatus
from paperless_pilot.domain.taxonomy import Taxonomy
from tests.clock import FakeClock
from tests.factories import answer
from tests.fakes import FakeLlmHost
from tests.pipeline import Pipeline, build_pipeline

TODO, REVIEW, ERROR = 40, 41, 43


@pytest.fixture
async def p(engine: AsyncEngine, clock: FakeClock) -> Pipeline:
    pipeline = await build_pipeline(engine, clock)
    await pipeline.registry.refresh()
    return pipeline


async def enqueue(p: Pipeline, *ids: int) -> None:
    for document_id in ids:
        await p.jobs.enqueue(document_id, JobKind.EXTRACT, p.clock.now())


async def test_success_creates_suggestion_and_swaps_status_tag(p: Pipeline) -> None:
    p.paperless.edit(1, tag_ids=(TODO, 7))
    p.hosts[0].replies.append(answer())
    await enqueue(p, 1)

    assert await p.scheduler.run_once("Mac")

    [suggestion] = await p.suggestions.list()
    assert suggestion.document_id == 1
    assert suggestion.proposed.title == "Bürostuhl"
    doc = p.paperless.documents[1]
    assert set(doc.tag_ids) == {7, REVIEW}
    assert suggestion.document_modified == doc.modified  # nach dem Tag-Wechsel
    assert (await p.jobs.stats()).succeeded == 1
    state = p.registry.state("Mac")
    assert state.busy_document_id is None
    assert state.processed == 1
    assert not await p.scheduler.run_once("Mac")  # nichts mehr zu tun


async def test_document_without_text_fails_and_gets_error_tag(p: Pipeline) -> None:
    await enqueue(p, 3)

    await p.scheduler.run_once("Mac")

    [job] = await p.jobs.list()
    assert job.status == JobStatus.FAILED
    assert job.last_error == "Dokument hat keinen OCR-Text"
    assert ERROR in p.paperless.documents[3].tag_ids


async def test_deleted_document_fails_without_tagging(p: Pipeline) -> None:
    await enqueue(p, 99)

    await p.scheduler.run_once("Mac")

    [job] = await p.jobs.list()
    assert job.status == JobStatus.FAILED


async def test_invalid_answer_is_retried_once_with_shorter_text(p: Pipeline) -> None:
    host = p.hosts[0]
    host.replies.extend([InvalidLlmOutputError("m", "kaputt", "x"), answer()])
    await enqueue(p, 1)

    await p.scheduler.run_once("Mac")
    [job] = await p.jobs.list()
    assert job.status == JobStatus.QUEUED  # sofort wieder fällig

    await p.scheduler.run_once("Mac")
    assert len(await p.suggestions.list()) == 1


async def test_invalid_answer_twice_is_final(p: Pipeline) -> None:
    p.hosts[0].replies.extend(
        [InvalidLlmOutputError("m", "a", "x"), InvalidLlmOutputError("m", "b", "x")]
    )
    await enqueue(p, 1)

    await p.scheduler.run_once("Mac")
    await p.scheduler.run_once("Mac")

    [job] = await p.jobs.list()
    assert job.status == JobStatus.FAILED
    assert ERROR in p.paperless.documents[1].tag_ids


async def test_host_outage_releases_job_and_marks_host_offline(p: Pipeline) -> None:
    p.hosts[0].replies.append(LlmHostUnavailableError("Ollama (Mac)", "weg"))
    await enqueue(p, 1)

    await p.scheduler.run_once("Mac")

    [job] = await p.jobs.list()
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0
    assert not p.registry.state("Mac").online
    assert not await p.scheduler.run_once("Mac")


async def test_temporary_failure_waits_with_backoff(p: Pipeline) -> None:
    p.hosts[0].replies.extend([ServiceUnavailableError("Paperless", "weg"), answer()])
    await enqueue(p, 1)

    await p.scheduler.run_once("Mac")
    assert not await p.scheduler.run_once("Mac")  # noch in der Wartezeit
    p.clock.advance(minutes=1)
    assert await p.scheduler.run_once("Mac")
    assert len(await p.suggestions.list()) == 1


async def test_scheduler_waits_for_configured_taxonomy(p: Pipeline) -> None:
    await p.taxonomy.save(Taxonomy(), p.clock.now())
    await enqueue(p, 1)

    assert not await p.scheduler.run_once("Mac")


async def test_host_without_model_does_not_work(engine: AsyncEngine, clock: FakeClock) -> None:
    host = FakeLlmHost("PC", probe=HostProbe(version="0.24.0"))
    p = await build_pipeline(engine, clock, [host])
    await p.registry.refresh()
    await enqueue(p, 1)

    state = p.registry.state("PC")
    assert state.online
    assert not state.has_model
    assert not await p.scheduler.run_once("PC")


async def test_idle_rule_from_home_assistant(p: Pipeline) -> None:
    entity = "binary_sensor.mac_active"
    p.availability.states[entity] = EntityState(
        state="on", last_changed=p.clock.now() - timedelta(hours=1)
    )
    await p.registry.update_rules("Mac", HostRules(idle_entity=entity, idle_minutes=10))
    await enqueue(p, 1)
    p.hosts[0].replies.append(answer())

    assert not await p.scheduler.run_once("Mac")
    assert p.registry.state("Mac").decision.reason == "Wartet: Rechner wird benutzt"

    p.availability.states[entity] = EntityState(state="off", last_changed=p.clock.now())
    p.clock.advance(minutes=11)
    await p.registry.refresh()
    assert p.registry.state("Mac").entity_states[entity].state == "off"
    assert await p.scheduler.run_once("Mac")


async def test_home_assistant_down_falls_back_to_closed(p: Pipeline) -> None:
    p.availability.broken = True
    await p.registry.update_rules("Mac", HostRules(idle_entity="binary_sensor.x"))

    state = p.registry.state("Mac")
    assert state.ha_available is False
    assert not state.decision.allowed


async def test_background_runner_processes_queue(p: Pipeline) -> None:
    p.hosts[0].replies.append(answer())
    p.paperless.edit(1, tag_ids=(TODO,))

    async with run_background(
        p.registry,
        p.intake,
        p.scheduler,
        p.lessons,
        probe_interval=0.01,
        intake_interval=0.01,
    ):
        for _ in range(200):
            if await p.suggestions.count_open():
                break
            await asyncio.sleep(0.01)

    assert await p.suggestions.count_open() == 1
    assert (await p.suggestions.list())[0].status == SuggestionStatus.OPEN
