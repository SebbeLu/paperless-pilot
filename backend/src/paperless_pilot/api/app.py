"""FastAPI-Anwendung: Lebenszyklus, Routen und Auslieferung des Frontends."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from paperless_pilot import __version__
from paperless_pilot.api.container import Adapters, build_container, real_adapters
from paperless_pilot.api.errors import register_error_handlers
from paperless_pilot.api.routes import router
from paperless_pilot.api.spa import SpaStaticFiles
from paperless_pilot.config import Settings

logger = logging.getLogger(__name__)

type AdapterFactory = Callable[[Settings], AbstractAsyncContextManager[Adapters]]


def default_adapters(settings: Settings) -> AbstractAsyncContextManager[Adapters]:
    return real_adapters(settings)


def create_app(
    settings: Settings | None = None, adapter_factory: AdapterFactory = default_adapters
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with (
            adapter_factory(settings) as adapters,
            build_container(settings, adapters) as container,
        ):
            app.state.container = container
            logger.info(
                "paperless-pilot %s gestartet%s: %d Ollama-Rechner",
                __version__,
                " im Demo-Modus" if settings.demo else "",
                len(adapters.hosts),
            )
            yield

    app = FastAPI(title="paperless-pilot", version=__version__, lifespan=lifespan)
    register_error_handlers(app)
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
