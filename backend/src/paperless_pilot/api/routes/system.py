from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from paperless_pilot import __version__
from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.system_status import SystemStatus

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__


@router.get("/health")
async def health() -> Health:
    """Lebenszeichen für Docker-Healthcheck und Monitoring; prüft keine Abhängigkeiten."""
    return Health()


@router.get("/system/status")
async def system_status(container: ContainerDep) -> SystemStatus:
    """Erreichbarkeit von Paperless und allen Ollama-Rechnern."""
    return await container.system_status.get_status()
