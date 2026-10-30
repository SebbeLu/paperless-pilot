from fastapi import APIRouter

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.hosts import HostState
from paperless_pilot.domain.availability import HostRules

router = APIRouter(prefix="/hosts", tags=["hosts"])


@router.get("")
async def list_hosts(container: ContainerDep) -> list[HostState]:
    """Rechner mit Erreichbarkeit, Modellen, Freigabe und laufendem Auftrag."""
    return container.registry.states()


@router.post("/refresh")
async def refresh_hosts(container: ContainerDep) -> list[HostState]:
    """Sofort neu prüfen statt auf den nächsten Takt zu warten."""
    states = await container.registry.refresh()
    container.scheduler.wake()
    return states


@router.put("/{name}/rules")
async def update_rules(name: str, rules: HostRules, container: ContainerDep) -> HostState:
    """Pause, Zeitfenster und Home-Assistant-Regeln eines Rechners."""
    state = await container.registry.update_rules(name, rules)
    container.scheduler.wake()
    return state
