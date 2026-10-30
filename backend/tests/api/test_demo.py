from pathlib import Path

import httpx
from asgi_lifespan import LifespanManager

from paperless_pilot.adapters.demo import DemoLlmHost, DemoPaperless, _answer, text_pdf
from paperless_pilot.api.app import create_app
from paperless_pilot.config import Settings
from paperless_pilot.domain.models import FileKind


async def test_demo_mode_runs_end_to_end(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {"demo": True, "data_dir": tmp_path, "background_tasks": False}
    )
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        container = app.state.container
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as client:
            status = (await client.get("/api/system/status")).json()
            assert status["paperless"]["version"] == "Demo"
            assert status["queue"]["queued"] == 6

            assert await container.scheduler.run_once("Demo-Rechner")
            [suggestion] = (await client.get("/api/suggestions")).json()
            assert suggestion["proposed"]["title"] == "Rechnung Nr. 4711"
            assert suggestion["checks"]["created"]["status"] == "ok"

            change = await client.post(
                f"/api/suggestions/{suggestion['id']}/accept",
                json={"values": suggestion["proposed"]},
            )
            assert change.status_code == 200
            preview = await client.get(f"/api/documents/{suggestion['document_id']}/preview")
            assert preview.content.startswith(b"%PDF-1.4")

    # Neustart: Taxonomie bleibt, wird nicht doppelt angelegt
    app = create_app(settings)
    async with LifespanManager(app):
        taxonomy, configured = await app.state.container.taxonomy_repository.get()
        assert configured
        assert len(taxonomy.document_types) == 5


def test_demo_answer_respects_allowed_values() -> None:
    schema = {
        "properties": {
            "document_type": {"$ref": "#/$defs/T"},
            "persons": {"items": {"enum": ["Kim"]}},
            "area": {"enum": ["Andere"]},
        },
        "$defs": {"T": {"enum": ["Bescheid", "Brief"]}},
    }
    answer = _answer("Amt\nKim Beispiel\nBescheid vom 01.02.2026", schema)
    assert answer["document_type"] == "Bescheid"
    assert answer["persons"] == ["Kim"]
    assert answer["area"] == "Andere"
    assert answer["document_date"] == "01.02.2026"

    plain = _answer("Nur eine Zeile", {"properties": {"document_type": {"enum": []}}})
    assert plain["title"] == "Dokument"
    assert plain["document_date"] is None


async def test_demo_paperless_and_host_basics() -> None:
    paperless = DemoPaperless()
    host = DemoLlmHost(delay_seconds=0)
    assert (await paperless.server_info()).documents_inbox == 6
    assert (await host.probe()).models[0].name == "demo-modell"
    thumb = await paperless.get_file(1, FileKind.THUMB)
    assert thumb.media_type == "image/svg+xml"
    assert len([d async for d in paperless.iter_documents(with_all_tags=[999])]) == 0
    assert (await paperless.create_correspondent("X")).name == "X"
    assert b"(a\\(b\\)) '" in text_pdf("a(b)")
