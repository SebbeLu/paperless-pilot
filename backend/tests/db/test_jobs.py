import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.repositories import JobRepository
from paperless_pilot.domain.jobs import JobKind, JobStatus
from tests.clock import FakeClock

LEASE = timedelta(minutes=10)


@pytest.fixture
def jobs(engine: AsyncEngine) -> JobRepository:
    return JobRepository(engine)


async def test_enqueue_is_idempotent_while_active(jobs: JobRepository, clock: FakeClock) -> None:
    first, created = await jobs.enqueue(7, JobKind.EXTRACT, clock.now())
    again, created_again = await jobs.enqueue(7, JobKind.EXTRACT, clock.now())

    assert created
    assert not created_again
    assert again.id == first.id
    assert first.status == JobStatus.QUEUED


async def test_enqueue_again_after_completion(jobs: JobRepository, clock: FakeClock) -> None:
    first, _ = await jobs.enqueue(7, JobKind.EXTRACT, clock.now())
    await jobs.complete(first.id, clock.now())

    second, created = await jobs.enqueue(7, JobKind.EXTRACT, clock.now())

    assert created
    assert second.id != first.id


async def test_lease_takes_highest_priority_then_oldest(
    jobs: JobRepository, clock: FakeClock
) -> None:
    await jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await jobs.enqueue(2, JobKind.EXTRACT, clock.now(), priority=5)
    await jobs.enqueue(3, JobKind.EXTRACT, clock.now())

    leased = [await jobs.lease_next("w", clock.now(), LEASE) for _ in range(4)]

    assert [j.document_id if j else None for j in leased] == [2, 1, 3, None]
    first = leased[0]
    assert first is not None
    assert first.status == JobStatus.RUNNING
    assert first.attempts == 1
    assert first.lease_owner == "w"
    assert first.lease_expires_at == clock.now() + LEASE


async def test_two_workers_never_get_the_same_job(jobs: JobRepository, clock: FakeClock) -> None:
    for doc in range(10):
        await jobs.enqueue(doc, JobKind.EXTRACT, clock.now())

    results = await asyncio.gather(
        *(jobs.lease_next(f"w{i}", clock.now(), LEASE) for i in range(15))
    )

    leased = [r.document_id for r in results if r is not None]
    assert sorted(leased) == list(range(10))


async def test_expired_lease_falls_back_into_queue(jobs: JobRepository, clock: FakeClock) -> None:
    await jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await jobs.lease_next("abgestürzt", clock.now(), LEASE)

    assert await jobs.lease_next("w2", clock.now(), LEASE) is None
    clock.advance(minutes=11)
    again = await jobs.lease_next("w2", clock.now(), LEASE)

    assert again is not None
    assert again.lease_owner == "w2"
    assert again.attempts == 2


async def test_fail_with_retry_waits_until_not_before(
    jobs: JobRepository, clock: FakeClock
) -> None:
    job, _ = await jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await jobs.lease_next("w", clock.now(), LEASE)

    failed = await jobs.fail(
        job.id, clock.now(), "Paperless weg", clock.now() + timedelta(minutes=5)
    )

    assert failed.status == JobStatus.QUEUED
    assert failed.last_error == "Paperless weg"
    assert await jobs.lease_next("w", clock.now(), LEASE) is None
    clock.advance(minutes=5)
    assert await jobs.lease_next("w", clock.now(), LEASE) is not None


async def test_final_failure_and_manual_retry(jobs: JobRepository, clock: FakeClock) -> None:
    job, _ = await jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await jobs.lease_next("w", clock.now(), LEASE)

    failed = await jobs.fail(job.id, clock.now(), "kein Text", None)
    assert failed.status == JobStatus.FAILED
    assert await jobs.retry(job.id + 99, clock.now()) is None

    retried = await jobs.retry(job.id, clock.now())

    assert retried is not None
    assert retried.status == JobStatus.QUEUED
    assert retried.attempts == 0


async def test_release_does_not_count_attempt(jobs: JobRepository, clock: FakeClock) -> None:
    job, _ = await jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await jobs.lease_next("w", clock.now(), LEASE)

    released = await jobs.release(job.id, clock.now(), "Rechner offline")

    assert released.status == JobStatus.QUEUED
    assert released.attempts == 0
    assert released.lease_owner is None


async def test_stats_list_and_get(jobs: JobRepository, clock: FakeClock) -> None:
    a, _ = await jobs.enqueue(1, JobKind.EXTRACT, clock.now())
    await jobs.enqueue(2, JobKind.EXTRACT, clock.now())
    await jobs.lease_next("w", clock.now(), LEASE)
    await jobs.complete(a.id, clock.now())

    stats = await jobs.stats()

    assert (stats.queued, stats.running, stats.succeeded, stats.failed) == (1, 0, 1, 0)
    assert [j.document_id for j in await jobs.list()] == [2, 1]
    assert [j.document_id for j in await jobs.list(JobStatus.SUCCEEDED)] == [1]
    assert (await jobs.get(a.id)) is not None
    assert await jobs.get(999) is None
