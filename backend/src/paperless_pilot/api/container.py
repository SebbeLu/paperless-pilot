"""Verdrahtung: baut aus der Konfiguration Adapter, Repositories und Anwendungsfälle."""

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.database import create_engine, migrate
from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    HostSettingsRepository,
    JobRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.adapters.demo import DEMO_MODEL
from paperless_pilot.adapters.homeassistant import HomeAssistantClient
from paperless_pilot.adapters.ollama import OllamaHost
from paperless_pilot.adapters.paperless import PaperlessClient
from paperless_pilot.application.events import EventBus
from paperless_pilot.application.extraction import ExtractionService
from paperless_pilot.application.history import HistoryService
from paperless_pilot.application.hosts import HostRegistry
from paperless_pilot.application.intake import IntakeService
from paperless_pilot.application.processing import JobProcessor, Scheduler
from paperless_pilot.application.review import ReviewService
from paperless_pilot.application.system_status import SystemStatusService
from paperless_pilot.application.taxonomy import TaxonomyService
from paperless_pilot.config import Settings
from paperless_pilot.domain.clock import Clock, SystemClock
from paperless_pilot.domain.ports import AvailabilitySource, DocumentRepository, LlmHost

HOST_PROBE_TIMEOUT_SECONDS = 3.0


@dataclass
class Adapters:
    """Außenwelt. Tests und der Demo-Modus setzen hier Attrappen ein."""

    paperless: DocumentRepository
    hosts: Sequence[LlmHost]
    availability: AvailabilitySource | None = None
    clock: Clock = field(default_factory=SystemClock)


@dataclass
class Container:
    settings: Settings
    adapters: Adapters
    engine: AsyncEngine
    events: EventBus
    jobs: JobRepository
    suggestions: SuggestionRepository
    changes: ChangeRepository
    host_settings: HostSettingsRepository
    taxonomy_repository: TaxonomyRepository
    system_status: SystemStatusService
    taxonomy: TaxonomyService
    registry: HostRegistry
    extraction: ExtractionService
    intake: IntakeService
    scheduler: Scheduler
    review: ReviewService
    history: HistoryService


@asynccontextmanager
async def real_adapters(settings: Settings) -> AsyncIterator[Adapters]:
    async with AsyncExitStack() as stack:
        paperless = PaperlessClient.create(
            str(settings.paperless_url),
            settings.resolve_paperless_token(),
            timeout=settings.http_timeout_seconds,
        )
        stack.push_async_callback(paperless.aclose)
        hosts = []
        for cfg in settings.ollama_hosts:
            host = OllamaHost.create(
                cfg.name,
                str(cfg.url),
                probe_timeout=HOST_PROBE_TIMEOUT_SECONDS,
                generate_timeout=settings.llm_timeout_seconds,
            )
            stack.push_async_callback(host.aclose)
            hosts.append(host)
        availability = None
        if settings.ha_url is not None and (token := settings.resolve_ha_token()):
            availability = HomeAssistantClient.create(
                str(settings.ha_url), token, timeout=settings.http_timeout_seconds
            )
            stack.push_async_callback(availability.aclose)
        yield Adapters(paperless=paperless, hosts=hosts, availability=availability)


@asynccontextmanager
async def build_container(settings: Settings, adapters: Adapters) -> AsyncIterator[Container]:
    engine = create_engine(settings.database_path)
    try:
        await migrate(engine)
        events = EventBus()
        clock = adapters.clock
        tz = ZoneInfo(settings.timezone)
        paperless = adapters.paperless
        jobs = JobRepository(engine)
        suggestions = SuggestionRepository(engine)
        taxonomy_repository = TaxonomyRepository(engine)
        host_settings = HostSettingsRepository(engine)
        registry = HostRegistry(
            adapters.hosts,
            DEMO_MODEL if settings.demo else settings.extraction_model,
            {h.name: h.model for h in settings.ollama_hosts if h.model},
            host_settings,
            adapters.availability,
            clock,
            tz,
            events,
        )
        extraction = ExtractionService(paperless, taxonomy_repository, clock, tz)
        changes = ChangeRepository(engine)
        processor = JobProcessor(
            paperless, jobs, suggestions, taxonomy_repository, extraction, registry, clock, events
        )
        yield Container(
            settings=settings,
            adapters=adapters,
            engine=engine,
            events=events,
            jobs=jobs,
            suggestions=suggestions,
            changes=changes,
            host_settings=host_settings,
            taxonomy_repository=taxonomy_repository,
            system_status=SystemStatusService(paperless, adapters.hosts, jobs, suggestions),
            taxonomy=TaxonomyService(taxonomy_repository, paperless, clock, events),
            registry=registry,
            extraction=extraction,
            intake=IntakeService(paperless, jobs, taxonomy_repository, clock, events),
            scheduler=Scheduler(
                registry,
                jobs,
                processor,
                taxonomy_repository,
                clock,
                lease_for=timedelta(seconds=settings.llm_timeout_seconds + 120),
            ),
            review=ReviewService(
                paperless, suggestions, changes, jobs, taxonomy_repository, clock, events
            ),
            history=HistoryService(paperless, changes, suggestions, clock, events),
        )
    finally:
        await engine.dispose()
