from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, model_validator

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.intake import EnqueueResult
from paperless_pilot.domain.errors import NotFoundError
from paperless_pilot.domain.jobs import Job, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


class EnqueueRequest(BaseModel):
    scope: Literal["inbox", "documents"]
    document_ids: list[int] = []

    @model_validator(mode="after")
    def _ids_for_documents(self) -> "EnqueueRequest":
        if self.scope == "documents" and not self.document_ids:
            msg = "document_ids fehlt"
            raise ValueError(msg)
        return self


@router.get("")
async def list_jobs(container: ContainerDep, status: JobStatus | None = None) -> list[Job]:
    return await container.jobs.list(status)


@router.post("/enqueue")
async def enqueue(request: EnqueueRequest, container: ContainerDep) -> EnqueueResult:
    """Posteingang (setzt den Todo-Tag in Paperless) oder einzelne Dokumente einreihen."""
    if request.scope == "inbox":
        result = await container.intake.enqueue_inbox()
    else:
        result = await container.intake.enqueue(request.document_ids)
    container.scheduler.wake()
    return result


@router.post("/{job_id}/retry")
async def retry(job_id: int, container: ContainerDep) -> Job:
    """Endgültig fehlgeschlagenen Auftrag erneut versuchen."""
    job = await container.jobs.retry(job_id, container.adapters.clock.now())
    if job is None:
        msg = f"Kein fehlgeschlagener Auftrag {job_id}"
        raise NotFoundError(msg)
    container.events.publish("jobs", job.document_id)
    container.scheduler.wake()
    return job
