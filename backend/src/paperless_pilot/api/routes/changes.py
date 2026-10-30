from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.domain.changes import Change

router = APIRouter(prefix="/changes", tags=["changes"])


class RevertRequest(BaseModel):
    force: bool = False


@router.get("")
async def list_changes(
    container: ContainerDep,
    document_id: int | None = None,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Change]:
    """Verlauf, neueste zuerst; mit ``before_id`` blättern."""
    return await container.history.list(document_id, before_id, limit)


@router.post("/{change_id}/revert")
async def revert(change_id: int, request: RevertRequest, container: ContainerDep) -> Change:
    """Übernahme rückgängig machen (Konfliktprüfung wie beim Übernehmen)."""
    return await container.history.revert(change_id, force=request.force)
