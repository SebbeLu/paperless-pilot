"""Hintergrundaufgaben: Rechner prüfen, Eingang abholen, Arbeiter je Rechner."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from paperless_pilot.application.hosts import HostRegistry
from paperless_pilot.application.intake import IntakeService
from paperless_pilot.application.lessons import LessonService
from paperless_pilot.application.processing import Scheduler

logger = logging.getLogger(__name__)


async def _every(seconds: float, action: Callable[[], Awaitable[object]], label: str) -> None:
    while True:
        try:
            await action()
        except Exception:
            logger.exception("%s fehlgeschlagen", label)
        await asyncio.sleep(seconds)


@contextlib.asynccontextmanager
async def run_background(
    registry: HostRegistry,
    intake: IntakeService,
    scheduler: Scheduler,
    lessons: LessonService,
    *,
    probe_interval: float,
    intake_interval: float,
) -> AsyncIterator[None]:
    async def refresh_and_wake() -> None:
        await registry.refresh()
        scheduler.wake()

    async def collect_and_wake() -> None:
        if (await intake.collect()).enqueued:
            scheduler.wake()

    async def backfill() -> None:
        try:
            await lessons.backfill()
        except Exception:
            logger.exception("Nachlernen früherer Korrekturen fehlgeschlagen")

    tasks = [
        asyncio.create_task(backfill()),
        asyncio.create_task(_every(probe_interval, refresh_and_wake, "Rechner-Prüfung")),
        asyncio.create_task(_every(intake_interval, collect_and_wake, "Eingang")),
        *(asyncio.create_task(scheduler.run_forever(name)) for name in registry.names()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
