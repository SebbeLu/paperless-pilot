"""Vision-OCR: Seiten vom Bild abschreiben lassen, wenn der OCR-Text von Paperless schlecht ist."""

from datetime import timedelta

from paperless_pilot.adapters.db.repositories import JobRepository, TranscriptionRepository
from paperless_pilot.application.hosts import HostRegistry
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.jobs import Job, JobKind, JobStatus
from paperless_pilot.domain.models import Document, FileKind
from paperless_pilot.domain.ocr_quality import assess_ocr
from paperless_pilot.domain.ports import DocumentRepository, LlmHost, PageRenderer
from paperless_pilot.domain.transcription import (
    TRANSCRIBE_PROMPT,
    StoredTranscription,
    Transcription,
    TranscriptionWarning,
    check_transcription,
    clean_page,
    join_pages,
    looks_stuck,
)


class TranscriptionService:
    def __init__(
        self,
        paperless: DocumentRepository,
        pages: PageRenderer,
        clock: Clock,
        *,
        max_pages: int,
        max_tokens: int,
    ) -> None:
        self._paperless = paperless
        self._pages = pages
        self._clock = clock
        self._max_pages = max_pages
        self._max_tokens = max_tokens

    async def transcribe(
        self, document_id: int, host: LlmHost, model: str, *, max_pages: int | None = None
    ) -> Transcription:
        started = self._clock.now()
        document = await self._paperless.get_document(document_id)
        limit = max_pages or self._max_pages
        file = await self._paperless.get_file(document_id, FileKind.ORIGINAL)
        rendered = await self._pages.render(file, limit)
        total = max(document.page_count or len(rendered), len(rendered))

        texts: list[str] = []
        capped = False
        for page in rendered:
            raw = await host.generate_text(
                model=model,
                prompt=TRANSCRIBE_PROMPT,
                images=[page.png],
                max_tokens=self._max_tokens,
                stop=looks_stuck,
            )
            text, page_capped = clean_page(raw)
            texts.append(text)
            capped = capped or page_capped
        text = join_pages(texts)

        before = assess_ocr(document.content, document.page_count)
        after = assess_ocr(text, len(rendered) or None)
        warnings = check_transcription(document.content, text, before, after)
        if capped:
            warnings.insert(
                0,
                TranscriptionWarning(
                    code="repetition",
                    message="Das Modell hat sich wiederholt – Wiederholungen abgeschnitten",
                ),
            )
        skipped = total - len(rendered)
        if skipped > 0:
            warnings.append(
                TranscriptionWarning(
                    code="skipped_pages",
                    message=f"Nur die ersten {len(rendered)} von {total} Seiten abgeschrieben",
                )
            )
        return Transcription(
            document_id=document_id,
            text=text,
            pages=len(rendered),
            rotated_pages=[n for n, page in enumerate(rendered, start=1) if page.rotated],
            skipped_pages=max(skipped, 0),
            quality_before=before,
            quality_after=after,
            warnings=warnings,
            model=model,
            host=host.name,
            duration_seconds=round((self._clock.now() - started).total_seconds(), 1),
        )


class VisionOcr:
    """Entscheidet, wann vom Bild abgeschrieben wird, und hält die Abschriften bereit."""

    def __init__(
        self,
        service: TranscriptionService,
        transcriptions: TranscriptionRepository,
        jobs: JobRepository,
        registry: HostRegistry,
        clock: Clock,
        *,
        model: str,
        threshold: float,
        time_per_page: timedelta,
        max_pages: int,
    ) -> None:
        self._service = service
        self._transcriptions = transcriptions
        self._jobs = jobs
        self._registry = registry
        self._clock = clock
        self._model = model
        self._threshold = threshold
        self._time_per_page = time_per_page
        self._max_pages = max_pages

    async def needs_transcription(self, document: Document) -> bool:
        """Schlechter Text, ein Rechner kann Bilder, und es gab noch keinen Versuch."""
        if not self._registry.vision_available():
            return False
        if assess_ocr(document.content, document.page_count).score >= self._threshold:
            return False
        if await self._transcriptions.for_document(document.id) is not None:
            return False
        return await self._jobs.last_status(document.id, JobKind.TRANSCRIBE) != JobStatus.FAILED

    async def text_for(self, document_id: int) -> str | None:
        """Abschrift fürs Auslesen – nur, wenn sie besser ist als der OCR-Text."""
        stored = await self._transcriptions.for_document(document_id)
        if stored is None or stored.quality_after.score <= stored.quality_before.score:
            return None
        return stored.text

    async def transcribe(self, job: Job, host_name: str) -> StoredTranscription:
        now = self._clock.now()
        await self._jobs.extend_lease(job.id, now + self._time_per_page * self._max_pages, now)
        result = await self._service.transcribe(
            job.document_id, self._registry.host(host_name), self._model
        )
        return await self._transcriptions.save(result, self._clock.now())
