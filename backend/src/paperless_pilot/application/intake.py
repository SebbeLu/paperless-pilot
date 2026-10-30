"""Eingang: Dokumente mit dem Tag „ai:todo“ (bzw. aus dem Posteingang) einreihen."""

import logging

from pydantic import BaseModel

from paperless_pilot.adapters.db.repositories import JobRepository, TaxonomyRepository
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.models import DocumentPatch
from paperless_pilot.domain.ports import DocumentRepository

logger = logging.getLogger(__name__)


class EnqueueResult(BaseModel):
    enqueued: int
    already_queued: int


class IntakeService:
    def __init__(
        self,
        paperless: DocumentRepository,
        jobs: JobRepository,
        taxonomy: TaxonomyRepository,
        clock: Clock,
        events: EventBus,
    ) -> None:
        self._paperless = paperless
        self._jobs = jobs
        self._taxonomy = taxonomy
        self._clock = clock
        self._events = events

    async def collect(self) -> EnqueueResult:
        """Reiht alle Dokumente mit dem Todo-Tag ein (läuft regelmäßig)."""
        todo = await self._todo_tag()
        if todo is None:
            return EnqueueResult(enqueued=0, already_queued=0)
        ids = [d.id async for d in self._paperless.iter_documents(with_all_tags=[todo])]
        return await self.enqueue(ids)

    async def enqueue(self, document_ids: list[int]) -> EnqueueResult:
        created = 0
        for document_id in document_ids:
            _, new = await self._jobs.enqueue(document_id, JobKind.EXTRACT, self._clock.now())
            created += new
        if created:
            logger.info("%d Dokument(e) eingereiht", created)
            self._events.publish("jobs")
        return EnqueueResult(enqueued=created, already_queued=len(document_ids) - created)

    async def enqueue_inbox(self) -> EnqueueResult:
        """Gibt allen Dokumenten im Posteingang den Todo-Tag und reiht sie ein."""
        todo = await self._todo_tag()
        if todo is None:
            msg = "Der Status-Tag „wartet auf Auslesen“ ist noch nicht mit Paperless verknüpft"
            raise ValidationFailedError(msg)
        taxonomy, _ = await self._taxonomy.get()
        status_ids = {
            e.paperless_id
            for e in (taxonomy.status.review, taxonomy.status.done, taxonomy.status.error)
        }
        inbox_tags = [t.id for t in await self._paperless.list_tags() if t.is_inbox_tag]
        ids: list[int] = []
        for inbox in inbox_tags:
            async for document in self._paperless.iter_documents(with_all_tags=[inbox]):
                if status_ids & set(document.tag_ids) or document.id in ids:
                    continue  # schon bearbeitet oder doppelt über zweiten Posteingangs-Tag
                if todo not in document.tag_ids:
                    await self._paperless.update_document(
                        document.id, DocumentPatch(tag_ids=(*document.tag_ids, todo))
                    )
                ids.append(document.id)
        return await self.enqueue(ids)

    async def _todo_tag(self) -> int | None:
        taxonomy, configured = await self._taxonomy.get()
        return taxonomy.status.todo.paperless_id if configured else None
