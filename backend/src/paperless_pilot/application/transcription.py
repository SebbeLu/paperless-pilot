"""Seiten eines Dokuments vom Bild abschreiben lassen (Vision-OCR) – schreibt nichts."""

from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.models import FileKind
from paperless_pilot.domain.ocr_quality import assess_ocr
from paperless_pilot.domain.ports import DocumentRepository, LlmHost, PageRenderer
from paperless_pilot.domain.transcription import (
    TRANSCRIBE_PROMPT,
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
