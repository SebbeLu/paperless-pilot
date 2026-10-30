from fastapi import APIRouter, Response

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.domain.models import FileKind

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}/{kind}", response_class=Response)
async def document_file(document_id: int, kind: FileKind, container: ContainerDep) -> Response:
    """Vorschau (PDF) bzw. Miniaturbild aus Paperless – der Browser hat keinen Paperless-Token."""
    file = await container.adapters.paperless.get_file(document_id, kind)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline"},
    )
