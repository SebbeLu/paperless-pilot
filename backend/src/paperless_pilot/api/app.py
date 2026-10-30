"""FastAPI-Anwendung: verdrahtet Konfiguration, Adapter und Routen."""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from paperless_pilot import __version__
from paperless_pilot.adapters.ollama import OllamaHost
from paperless_pilot.adapters.paperless import PaperlessClient
from paperless_pilot.api.routes import router
from paperless_pilot.api.spa import SpaStaticFiles
from paperless_pilot.application.system_status import SystemStatusService
from paperless_pilot.config import Settings

logger = logging.getLogger(__name__)

HOST_PROBE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class Services:
    system_status: SystemStatusService


@asynccontextmanager
async def build_services(settings: Settings) -> AsyncIterator[Services]:
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
        yield Services(system_status=SystemStatusService(paperless, hosts))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # Pflichtwerte kommen aus der Umgebung

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with build_services(settings) as services:
            app.state.services = services
            logger.info(
                "paperless-pilot %s gestartet: Paperless %s, %d Ollama-Rechner",
                __version__,
                settings.paperless_url,
                len(settings.ollama_hosts),
            )
            yield

    app = FastAPI(title="paperless-pilot", version=__version__, lifespan=lifespan)
    app.include_router(router, prefix="/api")
    _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path | None) -> None:
    if static_dir is None:
        return
    if not (static_dir / "index.html").is_file():
        logger.warning(
            "Kein Frontend unter %s gefunden – nur die API wird ausgeliefert", static_dir
        )
        return
    app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="frontend")
