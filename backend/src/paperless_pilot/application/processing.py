"""Aufträge abarbeiten: abschreiben oder auslesen, Vorschlag speichern, Fehler einordnen."""

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from paperless_pilot.adapters.db.repositories import (
    JobRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.application.events import EventBus
from paperless_pilot.application.extraction import ExtractionService
from paperless_pilot.application.hosts import HostRegistry
from paperless_pilot.application.transcription import VisionOcr
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import (
    InvalidLlmOutputError,
    LlmHostUnavailableError,
    NoTextError,
    NotFoundError,
    PilotError,
    ValidationFailedError,
)
from paperless_pilot.domain.jobs import Job, JobKind, retry_delay, should_retry
from paperless_pilot.domain.models import DocumentPatch
from paperless_pilot.domain.ports import DocumentRepository
from paperless_pilot.domain.taxonomy import Taxonomy

logger = logging.getLogger(__name__)

INVALID_OUTPUT_ATTEMPTS = 2


class JobProcessor:
    def __init__(
        self,
        paperless: DocumentRepository,
        jobs: JobRepository,
        suggestions: SuggestionRepository,
        taxonomy: TaxonomyRepository,
        extraction: ExtractionService,
        registry: HostRegistry,
        clock: Clock,
        events: EventBus,
        vision: VisionOcr | None = None,
    ) -> None:
        self._vision = vision
        self._paperless = paperless
        self._jobs = jobs
        self._suggestions = suggestions
        self._taxonomy = taxonomy
        self._extraction = extraction
        self._registry = registry
        self._clock = clock
        self._events = events

    async def process(self, job: Job, host_name: str) -> None:
        self._registry.set_busy(host_name, job.document_id)
        duration: int | None = None
        try:
            if job.kind == JobKind.TRANSCRIBE:
                duration = await self._transcribe(job, host_name)
            else:
                duration = await self._extract(job, host_name)
        finally:
            self._registry.set_busy(host_name, None, duration)
            self._events.publish("jobs", job.document_id)

    async def _transcribe(self, job: Job, host_name: str) -> int | None:
        if self._vision is None:  # Rechner bekommen solche Aufträge nur mit Vision-OCR
            await self._fail(job, "Vision-OCR ist nicht eingerichtet", final=True, tag=False)
            return None
        try:
            stored = await self._vision.transcribe(job, host_name)
        except LlmHostUnavailableError as exc:
            await self._jobs.release(job.id, self._clock.now(), str(exc))
            self._registry.mark_offline(host_name, str(exc))
            return None
        except NotFoundError as exc:
            await self._fail(job, str(exc), final=True, tag=False)
            return None
        except PilotError as exc:
            final = isinstance(exc, ValidationFailedError) or not should_retry(job.attempts)
            await self._fail(job, str(exc), final=final, tag=False)
            if final:  # dann eben mit dem OCR-Text von Paperless auslesen
                await self._enqueue_extract(job)
            return None
        await self._jobs.complete(job.id, self._clock.now())
        await self._enqueue_extract(job)
        return int(stored.duration_seconds * 1000)

    async def _enqueue_extract(self, job: Job) -> None:
        await self._jobs.enqueue(
            job.document_id, JobKind.EXTRACT, self._clock.now(), priority=job.priority
        )

    async def _extract(self, job: Job, host_name: str) -> int | None:
        state = self._registry.state(host_name)
        duration: int | None = None
        try:
            content = None
            if self._vision is not None:
                document = await self._paperless.get_document(job.document_id)
                if await self._vision.needs_transcription(document):
                    # Erst vom Bild abschreiben; der Auftrag „auslesen“ folgt danach neu
                    await self._jobs.enqueue(
                        job.document_id,
                        JobKind.TRANSCRIBE,
                        self._clock.now(),
                        priority=job.priority,
                    )
                    await self._jobs.complete(job.id, self._clock.now())
                    return None
                content = await self._vision.text_for(job.document_id)
            suggestion = await self._extraction.extract(
                job.document_id,
                self._registry.host(host_name),
                state.model,
                job_id=job.id,
                short=job.attempts > 1,
                content=content,
            )
            duration = suggestion.duration_ms
            saved = await self._suggestions.add(suggestion, self._clock.now())
            taxonomy, _ = await self._taxonomy.get()
            updated = await self._set_status(
                job.document_id, taxonomy, taxonomy.status.review.paperless_id
            )
            if updated is not None:
                await self._suggestions.set_document_modified(saved.id, updated)
            await self._jobs.complete(job.id, self._clock.now())
            self._events.publish("suggestions", job.document_id)
        except LlmHostUnavailableError as exc:
            await self._jobs.release(job.id, self._clock.now(), str(exc))
            self._registry.mark_offline(host_name, str(exc))
        except (NoTextError, NotFoundError) as exc:
            await self._fail(job, str(exc), final=True, tag=isinstance(exc, NoTextError))
        except InvalidLlmOutputError as exc:
            await self._fail(job, str(exc), final=job.attempts >= INVALID_OUTPUT_ATTEMPTS, now=True)
        except PilotError as exc:
            await self._fail(job, str(exc), final=not should_retry(job.attempts))
        return duration

    async def _fail(
        self, job: Job, error: str, *, final: bool, tag: bool = True, now: bool = False
    ) -> None:
        logger.warning("Auftrag %s (Dokument %s): %s", job.id, job.document_id, error)
        if final:
            await self._jobs.fail(job.id, self._clock.now(), error, None)
            if tag:
                taxonomy, _ = await self._taxonomy.get()
                with contextlib.suppress(PilotError):
                    await self._set_status(
                        job.document_id, taxonomy, taxonomy.status.error.paperless_id
                    )
            return
        delay = timedelta(0) if now else retry_delay(job.attempts)
        await self._jobs.fail(job.id, self._clock.now(), error, self._clock.now() + delay)

    async def _set_status(
        self, document_id: int, taxonomy: Taxonomy, tag_id: int | None
    ) -> datetime | None:
        """Ersetzt die Status-Tags von paperless-pilot; liefert den neuen Änderungszeitpunkt."""
        status_ids = {
            e.paperless_id
            for e in (
                taxonomy.status.todo,
                taxonomy.status.review,
                taxonomy.status.done,
                taxonomy.status.error,
            )
            if e.paperless_id is not None
        }
        document = await self._paperless.get_document(document_id)
        tags = [t for t in document.tag_ids if t not in status_ids]
        if tag_id is not None:
            tags.append(tag_id)
        if sorted(tags) == sorted(document.tag_ids):
            return document.modified
        updated = await self._paperless.update_document(
            document_id, DocumentPatch(tag_ids=tuple(tags))
        )
        return updated.modified


class Scheduler:
    """Ein Arbeiter je Rechner; holt Aufträge, solange der Rechner arbeiten darf."""

    def __init__(
        self,
        registry: HostRegistry,
        jobs: JobRepository,
        processor: JobProcessor,
        taxonomy: TaxonomyRepository,
        clock: Clock,
        lease_for: timedelta,
        idle_seconds: float = 10.0,
    ) -> None:
        self._registry = registry
        self._jobs = jobs
        self._processor = processor
        self._taxonomy = taxonomy
        self._clock = clock
        self._lease_for = lease_for
        self._idle_seconds = idle_seconds
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Neue Aufträge oder Freigaben: wartende Arbeiter sofort weitermachen lassen."""
        self._wake.set()

    async def run_once(self, host_name: str) -> bool:
        """Bearbeitet höchstens einen Auftrag. Liefert ``True``, wenn etwas zu tun war."""
        if not self._registry.state(host_name).can_work or not await self._ready():
            return False
        state = self._registry.state(host_name)
        job = await self._jobs.lease_next(
            host_name, self._clock.now(), self._lease_for, state.kinds
        )
        if job is None:
            return False
        await self._processor.process(job, host_name)
        return True

    async def run_forever(self, host_name: str) -> None:
        while True:
            try:
                worked = await self.run_once(host_name)
            except Exception:
                logger.exception("Arbeiter %s: unerwarteter Fehler", host_name)
                worked = False
            if not worked:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._idle_seconds)

    async def _ready(self) -> bool:
        taxonomy, configured = await self._taxonomy.get()
        return configured and bool(taxonomy.document_types)
