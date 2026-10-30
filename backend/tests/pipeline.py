"""Aufbau der echten Anwendungsfälle mit Attrappen – für Ablauf-Tests ohne HTTP."""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    HostSettingsRepository,
    JobRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.application.events import EventBus
from paperless_pilot.application.extraction import ExtractionService
from paperless_pilot.application.history import HistoryService
from paperless_pilot.application.hosts import HostRegistry
from paperless_pilot.application.intake import IntakeService
from paperless_pilot.application.processing import JobProcessor, Scheduler
from paperless_pilot.application.review import ReviewService
from tests.clock import FakeClock
from tests.factories import CORRESPONDENTS, document, taxonomy
from tests.fakes import FakeAvailability, FakeDocumentRepository, FakeLlmHost

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass
class Pipeline:
    paperless: FakeDocumentRepository
    hosts: list[FakeLlmHost]
    availability: FakeAvailability
    clock: FakeClock
    events: EventBus
    jobs: JobRepository
    suggestions: SuggestionRepository
    changes: ChangeRepository
    taxonomy: TaxonomyRepository
    host_settings: HostSettingsRepository
    registry: HostRegistry
    intake: IntakeService
    processor: JobProcessor
    scheduler: Scheduler
    review: ReviewService
    history: HistoryService


async def build_pipeline(
    engine: AsyncEngine, clock: FakeClock, hosts: list[FakeLlmHost] | None = None
) -> Pipeline:
    paperless = FakeDocumentRepository([document(1), document(2), document(3, content="")])
    paperless.correspondents.extend(CORRESPONDENTS)
    hosts = hosts if hosts is not None else [FakeLlmHost("Mac")]
    availability = FakeAvailability()
    events = EventBus()
    jobs = JobRepository(engine)
    suggestions = SuggestionRepository(engine)
    tax = TaxonomyRepository(engine)
    await tax.save(taxonomy(), clock.now())
    host_settings = HostSettingsRepository(engine)
    registry = HostRegistry(
        hosts, "gemma4:26b", {}, host_settings, availability, clock, BERLIN, events
    )
    extraction = ExtractionService(paperless, tax, clock, BERLIN)
    processor = JobProcessor(paperless, jobs, suggestions, tax, extraction, registry, clock, events)
    changes = ChangeRepository(engine)
    return Pipeline(
        paperless=paperless,
        hosts=hosts,
        availability=availability,
        clock=clock,
        events=events,
        jobs=jobs,
        suggestions=suggestions,
        changes=changes,
        taxonomy=tax,
        host_settings=host_settings,
        registry=registry,
        intake=IntakeService(paperless, jobs, tax, clock, events),
        processor=processor,
        scheduler=Scheduler(
            registry,
            jobs,
            processor,
            tax,
            clock,
            lease_for=timedelta(minutes=12),
            idle_seconds=0.01,
        ),
        review=ReviewService(paperless, suggestions, changes, jobs, tax, clock, events),
        history=HistoryService(paperless, changes, suggestions, clock, events),
    )
