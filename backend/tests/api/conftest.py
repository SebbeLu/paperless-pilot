from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager

from paperless_pilot.api.app import create_app
from paperless_pilot.api.container import Adapters, Container
from paperless_pilot.config import Settings
from tests.clock import FakeClock
from tests.fakes import FakeAvailability, FakeDocumentRepository, FakeLlmHost


@dataclass
class Api:
    client: httpx.AsyncClient
    container: Container
    paperless: FakeDocumentRepository
    hosts: list[FakeLlmHost]
    availability: FakeAvailability
    clock: FakeClock


@pytest.fixture
def paperless() -> FakeDocumentRepository:
    return FakeDocumentRepository()


@pytest.fixture
def hosts() -> list[FakeLlmHost]:
    return [FakeLlmHost("Mac")]


@pytest.fixture
async def api(
    tmp_path: Path,
    paperless: FakeDocumentRepository,
    hosts: list[FakeLlmHost],
    clock: FakeClock,
) -> AsyncIterator[Api]:
    availability = FakeAvailability()
    settings = Settings.model_validate(
        {"paperless_url": "http://paperless.test", "paperless_token": "t", "data_dir": tmp_path}
    )

    @asynccontextmanager
    async def fake_adapters(_settings: Settings) -> AsyncIterator[Adapters]:
        yield Adapters(paperless=paperless, hosts=hosts, availability=availability, clock=clock)

    app = create_app(settings, adapter_factory=fake_adapters)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://pilot.test") as client:
            yield Api(
                client=client,
                container=app.state.container,
                paperless=paperless,
                hosts=hosts,
                availability=availability,
                clock=clock,
            )
