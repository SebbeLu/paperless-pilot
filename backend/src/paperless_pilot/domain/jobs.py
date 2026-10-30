"""Aufträge der Warteschlange und ihre Wiederholungsregeln."""

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class JobKind(StrEnum):
    EXTRACT = "extract"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)

MAX_ATTEMPTS = 5
_RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30))


def retry_delay(attempts: int) -> timedelta:
    """Wartezeit vor dem nächsten Versuch: 1, 5, danach jeweils 30 Minuten."""
    return _RETRY_DELAYS[min(max(attempts, 1), len(_RETRY_DELAYS)) - 1]


def should_retry(attempts: int) -> bool:
    return attempts < MAX_ATTEMPTS


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    document_id: int
    kind: JobKind
    status: JobStatus
    attempts: int
    priority: int
    not_before: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class QueueStats(BaseModel):
    queued: int = 0
    running: int = 0
    failed: int = 0
    succeeded: int = 0
