from fastapi import APIRouter
from pydantic import BaseModel

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.review import (
    AcceptManyResult,
    ReextractManyResult,
    RejectManyResult,
    SuggestionDetail,
)
from paperless_pilot.domain.changes import Change
from paperless_pilot.domain.suggestions import MetadataValues, Suggestion, SuggestionStatus

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


class AcceptRequest(BaseModel):
    values: MetadataValues
    force: bool = False


class ManyRequest(BaseModel):
    ids: list[int]


class AcceptManyRequest(ManyRequest):
    with_content: bool = False  # Abschriften vom Bild ohne Warnungen mitschreiben


class RejectRequest(BaseModel):
    reason: str | None = None


@router.get("")
async def list_suggestions(
    container: ContainerDep, status: SuggestionStatus = SuggestionStatus.OPEN
) -> list[Suggestion]:
    """Prüfliste: offene Vorschläge, unsichere zuerst."""
    if status == SuggestionStatus.OPEN:
        return await container.review.list_open()
    return await container.suggestions.list(status)


@router.get("/{suggestion_id}")
async def get_suggestion(suggestion_id: int, container: ContainerDep) -> SuggestionDetail:
    """Vorschlag mit dem aktuellen Stand des Dokuments in Paperless."""
    return await container.review.detail(suggestion_id)


@router.post("/accept")
async def accept_many(request: AcceptManyRequest, container: ContainerDep) -> AcceptManyResult:
    """Markierte Vorschläge unverändert übernehmen – ohne „Trotzdem“ bei Konflikten."""
    return await container.review.accept_many(request.ids, with_content=request.with_content)


@router.post("/{suggestion_id}/accept")
async def accept(suggestion_id: int, request: AcceptRequest, container: ContainerDep) -> Change:
    """Übernehmen – mit den Werten aus der Oberfläche (Vorschlag oder korrigiert)."""
    return await container.review.accept(suggestion_id, request.values, force=request.force)


@router.post("/reject")
async def reject_many(request: ManyRequest, container: ContainerDep) -> RejectManyResult:
    """Markierte Vorschläge verwerfen."""
    return await container.review.reject_many(request.ids)


@router.post("/{suggestion_id}/reject")
async def reject(suggestion_id: int, request: RejectRequest, container: ContainerDep) -> Suggestion:
    return await container.review.reject(suggestion_id, request.reason)


@router.post("/reextract")
async def reextract_many(request: ManyRequest, container: ContainerDep) -> ReextractManyResult:
    """Markierte Vorschläge verwerfen und die Dokumente mit Vorrang neu auslesen."""
    result = await container.review.reextract_many(request.ids)
    container.scheduler.wake()
    return result


@router.post("/{suggestion_id}/reextract")
async def reextract(suggestion_id: int, container: ContainerDep) -> Suggestion:
    """Neu auslesen lassen (mit Vorrang)."""
    result = await container.review.reextract(suggestion_id)
    container.scheduler.wake()
    return result
