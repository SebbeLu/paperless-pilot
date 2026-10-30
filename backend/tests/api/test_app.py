import json
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from paperless_pilot.api.app import create_app
from paperless_pilot.api.openapi_export import export
from paperless_pilot.config import Settings
from tests.contract import paperless_payloads as p

OLLAMA_URL = "http://mac.test:11434"

type ClientFactory = Callable[[FastAPI], Awaitable[httpx.AsyncClient]]


_TMP = tempfile.TemporaryDirectory()


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "paperless_url": p.BASE_URL,
        "paperless_token": "t",
        "ollama_hosts": [{"name": "Mac", "url": OLLAMA_URL}],
        "data_dir": tempfile.mkdtemp(dir=_TMP.name),
        "background_tasks": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
async def client_for() -> AsyncIterator[ClientFactory]:
    managers: list[LifespanManager] = []

    async def _make(app: FastAPI) -> httpx.AsyncClient:
        manager = LifespanManager(app)
        managers.append(manager)
        await manager.__aenter__()
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://pilot.test"
        )

    yield _make
    for manager in managers:
        await manager.__aexit__(None, None, None)


async def test_health(client_for: ClientFactory) -> None:
    client = await client_for(create_app(make_settings()))

    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_system_status_wires_real_adapters(client_for: ClientFactory) -> None:
    client = await client_for(create_app(make_settings()))
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{p.BASE_URL}/api/statistics/").respond(
            json=p.STATISTICS, headers={"x-version": "3.2.1", "x-api-version": "10"}
        )
        router.get(f"{OLLAMA_URL}/api/version").respond(json={"version": "0.24.0"})
        router.get(f"{OLLAMA_URL}/api/tags").respond(json={"models": [{"name": "gemma4:26b"}]})

        response = await client.get("/api/system/status")

    assert response.status_code == 200
    assert response.json() == {
        "paperless": {
            "reachable": True,
            "version": "3.2.1",
            "documents_total": 709,
            "documents_inbox": 95,
            "problem": None,
            "error": None,
        },
        "hosts": [
            {
                "name": "Mac",
                "url": OLLAMA_URL,
                "reachable": True,
                "version": "0.24.0",
                "models": ["gemma4:26b"],
                "problem": None,
                "error": None,
            }
        ],
        "queue": {"queued": 0, "running": 0, "failed": 0, "succeeded": 0},
        "open_suggestions": 0,
    }


def test_openapi_describes_status_endpoint() -> None:
    schema = create_app(make_settings()).openapi()

    assert "/api/system/status" in schema["paths"]
    assert "SystemStatus" in schema["components"]["schemas"]


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>pilot</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


async def test_serves_frontend_with_spa_fallback(client_for: ClientFactory, frontend: Path) -> None:
    client = await client_for(create_app(make_settings(static_dir=frontend)))

    assert (await client.get("/")).text == "<html>pilot</html>"
    assert (await client.get("/assets/app.js")).text == "console.log(1)"
    assert (await client.get("/pruefen/42")).text == "<html>pilot</html>"
    assert (await client.get("/api/gibt-es-nicht")).status_code == 404


async def test_missing_frontend_build_serves_api_only(
    client_for: ClientFactory, tmp_path: Path
) -> None:
    client = await client_for(create_app(make_settings(static_dir=tmp_path)))

    assert (await client.get("/")).status_code == 404
    assert (await client.get("/api/health")).status_code == 200


def test_openapi_export_writes_schema(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    export(target)

    assert json.loads(target.read_text(encoding="utf-8"))["info"]["title"] == "paperless-pilot"
