"""Aufbau der echten Anwendungsfälle mit Attrappen – für Ablauf-Tests ohne HTTP."""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    HostSettingsRepository,
    JobRepository,
    LessonRepository,
    SuggestionRepository,
    TaxonomyRepository,
    TranscriptionRepository,
)
from paperless_pilot.application.events import EventBus
from paperless_pilot.application.extraction import ExtractionService
from paperless_pilot.application.history import HistoryService
from paperless_pilot.application.hosts import HostRegistry
from paperless_pilot.application.intake import IntakeService
from paperless_pilot.application.lessons import LessonService
from paperless_pilot.application.processing import JobProcessor, Scheduler
from paperless_pilot.application.review import ReviewService
from paperless_pilot.application.transcription import TranscriptionService, VisionOcr
from tests.clock import FakeClock
from tests.factories import CORRESPONDENTS, document, taxonomy
from tests.fakes import FakeAvailability, FakeDocumentRepository, FakeLlmHost, FakePageRenderer

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
    lessons: LessonService
    transcriptions: TranscriptionRepository
    pages: FakePageRenderer


async def build_pipeline(
    engine: AsyncEngine,
    clock: FakeClock,
    hosts: list[FakeLlmHost] | None = None,
    *,
    vision: bool = False,
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
        hosts,
        "gemma4:26b",
        {},
        host_settings,
        availability,
        clock,
        BERLIN,
        events,
        vision_model="gemma4:26b" if vision else None,
    )
    changes = ChangeRepository(engine)
    lessons = LessonService(
        paperless, LessonRepository(engine), suggestions, changes, tax, clock, events
    )
    extraction = ExtractionService(paperless, tax, lessons, clock, BERLIN)
    transcriptions = TranscriptionRepository(engine)
    pages = FakePageRenderer()
    vision_ocr = VisionOcr(
        TranscriptionService(paperless, pages, clock, max_pages=8, max_tokens=4096),
        transcriptions,
        jobs,
        registry,
        clock,
        model="gemma4:26b",
        threshold=0.68,
        time_per_page=timedelta(minutes=10),
        max_pages=8,
    )
    processor = JobProcessor(
        paperless,
        jobs,
        suggestions,
        tax,
        extraction,
        registry,
        clock,
        events,
        vision=vision_ocr if vision else None,
    )
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
        review=ReviewService(paperless, suggestions, changes, jobs, tax, lessons, clock, events),
        history=HistoryService(paperless, changes, suggestions, lessons, clock, events),
        lessons=lessons,
        transcriptions=transcriptions,
        pages=pages,
    )
