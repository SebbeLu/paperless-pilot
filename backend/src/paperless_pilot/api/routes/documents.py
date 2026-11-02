from fastapi import APIRouter, Response
from pydantic import BaseModel

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.review import ReextractDocumentsResult
from paperless_pilot.domain.models import FileKind

router = APIRouter(prefix="/documents", tags=["documents"])


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


@router.get("/{document_id}/{kind}", response_class=Response)
async def document_file(document_id: int, kind: FileKind, container: ContainerDep) -> Response:
    """Vorschau (PDF) bzw. Miniaturbild aus Paperless – der Browser hat keinen Paperless-Token."""
    file = await container.adapters.paperless.get_file(document_id, kind)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline"},
    )
