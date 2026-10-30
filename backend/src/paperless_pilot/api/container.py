"""Verdrahtung: baut aus der Konfiguration Adapter, Repositories und Anwendungsfälle."""

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.database import create_engine, migrate
from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    HostSettingsRepository,
    JobRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.adapters.ollama import OllamaHost
from paperless_pilot.adapters.paperless import PaperlessClient
from paperless_pilot.application.events import EventBus
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
        yield Adapters(paperless=paperless, hosts=hosts)


@asynccontextmanager
async def build_container(settings: Settings, adapters: Adapters) -> AsyncIterator[Container]:
    engine = create_engine(settings.database_path)
    try:
        await migrate(engine)
        events = EventBus()
        clock = adapters.clock
        taxonomy_repository = TaxonomyRepository(engine)
        yield Container(
            settings=settings,
            adapters=adapters,
            engine=engine,
            events=events,
            jobs=JobRepository(engine),
            suggestions=SuggestionRepository(engine),
            changes=ChangeRepository(engine),
            host_settings=HostSettingsRepository(engine),
            taxonomy_repository=taxonomy_repository,
            system_status=SystemStatusService(adapters.paperless, adapters.hosts),
            taxonomy=TaxonomyService(taxonomy_repository, adapters.paperless, clock, events),
        )
    finally:
        await engine.dispose()
