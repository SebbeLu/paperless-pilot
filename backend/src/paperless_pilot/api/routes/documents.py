from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.review import ReextractDocumentsResult
from paperless_pilot.application.transcription import WeakText
from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.models import FileKind

router = APIRouter(prefix="/documents", tags=["documents"])

# Die Originaldatei braucht nur der Dienst selbst (Vision-OCR), der Browser nicht
type ViewKind = Literal["preview", "thumb"]


class DocumentIdsRequest(BaseModel):
    ids: list[int]


@router.post("/reextract")
async def reextract(
    request: DocumentIdsRequest, container: ContainerDep
) -> ReextractDocumentsResult:
    """Dokumente mit Vorrang neu auslesen – offene Vorschläge dazu werden verworfen."""
    result = await container.review.reextract_documents(request.ids)
    container.scheduler.wake()
    return result


@router.post("/transcribe")
async def transcribe(
    request: DocumentIdsRequest, container: ContainerDep
) -> ReextractDocumentsResult:
    """Text mit Vorrang neu vom Bild abschreiben lassen, danach neu auslesen."""
    result = await container.review.reextract_documents(request.ids, JobKind.TRANSCRIBE)
    container.scheduler.wake()
    return result


@router.get("/weak-text")
async def weak_text(container: ContainerDep, refresh: bool = False) -> WeakText:
    """Dokumente mit schwachem OCR-Text ohne Abschrift – liest beim ersten Aufruf alle Dokumente."""
    return await container.weak_text.get(refresh=refresh)


@router.get("/{document_id}/{kind}", response_class=Response)
async def document_file(document_id: int, kind: ViewKind, container: ContainerDep) -> Response:
    """Vorschau (PDF) bzw. Miniaturbild aus Paperless – der Browser hat keinen Paperless-Token."""
    file = await container.adapters.paperless.get_file(document_id, FileKind(kind))
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline"},
    )
