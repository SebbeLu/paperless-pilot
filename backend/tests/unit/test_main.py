import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from paperless_pilot import __main__ as entrypoint
from paperless_pilot.adapters.db.repositories import TaxonomyRepository
from paperless_pilot.api.container import Adapters, build_container
from paperless_pilot.config import Settings
from tests.clock import FakeClock
from tests.factories import CORRESPONDENTS, answer, document, taxonomy
from tests.fakes import FakeDocumentRepository, FakeLlmHost


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PILOT_PAPERLESS_URL", "http://paperless:8000")
    monkeypatch.setenv("PILOT_PAPERLESS_TOKEN", "t")
    monkeypatch.setenv("PILOT_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)


@pytest.mark.usefixtures("env")
def test_serve_starts_uvicorn_with_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PILOT_PORT", "9000")
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    entrypoint.main([])

    ((args, kwargs),) = calls
    assert args == ("paperless_pilot.api.app:create_app",)
    assert kwargs["factory"] is True
    assert kwargs["port"] == 9000


@pytest.mark.usefixtures("env")
def test_extract_prints_suggestion_without_writing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paperless = FakeDocumentRepository([document(5)])
    paperless.correspondents.extend(CORRESPONDENTS)
    host = FakeLlmHost("Mac", replies=[answer()])

    @asynccontextmanager
    async def fake_adapters(_settings: Settings) -> AsyncIterator[Adapters]:
        yield Adapters(paperless=paperless, hosts=[host], clock=FakeClock())

    async def seed() -> None:
        async with build_container(Settings(), Adapters(paperless=paperless, hosts=[])) as c:
            await TaxonomyRepository(c.engine).save(taxonomy(), FakeClock().now())

    asyncio.run(seed())
    monkeypatch.setattr(entrypoint, "real_adapters", fake_adapters)

    entrypoint.main(["extract", "5", "--host", "Mac", "--model", "klein"])

    printed = json.loads(capsys.readouterr().out)
    assert printed["document_id"] == 5
    assert printed["model"] == "klein"
    assert printed["proposed"]["title"] == "Bürostuhl"
    assert paperless.patches == []


@pytest.mark.usefixtures("env")
def test_extract_with_unknown_host_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_adapters(_settings: Settings) -> AsyncIterator[Adapters]:
        yield Adapters(paperless=FakeDocumentRepository(), hosts=[FakeLlmHost("Mac")])

    monkeypatch.setattr(entrypoint, "real_adapters", fake_adapters)

    with pytest.raises(SystemExit, match="Kein Ollama-Rechner PC"):
        entrypoint.main(["extract", "1", "--host", "PC"])
