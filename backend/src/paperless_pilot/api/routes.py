from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from paperless_pilot import __version__
from paperless_pilot.application.system_status import SystemStatus, SystemStatusService

router = APIRouter()


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__


def get_system_status_service(request: Request) -> SystemStatusService:
    service: SystemStatusService = request.app.state.services.system_status
    return service


@router.get("/health", tags=["system"])
async def health() -> Health:
    """Lebenszeichen für Docker-Healthcheck und Monitoring; prüft keine Abhängigkeiten."""
    return Health()


@router.get("/system/status", tags=["system"])
async def system_status(
    service: Annotated[SystemStatusService, Depends(get_system_status_service)],
) -> SystemStatus:
    """Erreichbarkeit von Paperless und allen Ollama-Rechnern."""
    return await service.get_status()
