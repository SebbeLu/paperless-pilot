"""Anwendungsfall: ein Dokument mit einem Modell auslesen und einen Vorschlag bilden."""

import time
from zoneinfo import ZoneInfo

from paperless_pilot.adapters.db.repositories import TaxonomyRepository
from paperless_pilot.application.lessons import LessonService
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import NoTextError
from paperless_pilot.domain.extraction import (
    SHORT_TEXT_LIMIT,
    SYSTEM_PROMPT,
    TEXT_LIMIT,
    build_output_model,
    build_prompt,
    candidate_correspondents,
    current_values,
    interpret,
)
from paperless_pilot.domain.ports import DocumentRepository, LlmHost
from paperless_pilot.domain.suggestions import NewSuggestion


class ExtractionService:
    def __init__(
        self,
        paperless: DocumentRepository,
        taxonomy: TaxonomyRepository,
        lessons: LessonService,
        clock: Clock,
        timezone: ZoneInfo,
    ) -> None:
        self._paperless = paperless
        self._taxonomy = taxonomy
        self._lessons = lessons
        self._clock = clock
        self._tz = timezone

    async def extract(
        self,
        document_id: int,
        host: LlmHost,
        model: str,
        *,
        job_id: int | None = None,
        short: bool = False,
    ) -> NewSuggestion:
        """Liest aus, ohne etwas zu speichern oder in Paperless zu schreiben.

        ``short`` kürzt den Text stärker – für den zweiten Versuch nach einer ungültigen Antwort.
        """
        document = await self._paperless.get_document(document_id)
        if not document.content.strip():
            msg = "Dokument hat keinen OCR-Text"
            raise NoTextError(msg)
        taxonomy, _ = await self._taxonomy.get()
        output_type = build_output_model(taxonomy)
        correspondents = await self._paperless.list_correspondents()
        lessons = await self._lessons.for_document(document)
        prompt = build_prompt(
            document,
            taxonomy,
            [c.name for c in candidate_correspondents(correspondents, taxonomy)],
            text_limit=SHORT_TEXT_LIMIT if short else TEXT_LIMIT,
            lessons=lessons,
        )

        started = time.monotonic()
        answer = await host.generate_structured(
            model=model, prompt=prompt, output_type=output_type, system=SYSTEM_PROMPT
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        today = self._clock.now().astimezone(self._tz).date()
        result = interpret(answer, document, taxonomy, correspondents, today)
        return NewSuggestion(
            document_id=document.id,
            job_id=job_id,
            model=model,
            host=host.name,
            duration_ms=duration_ms,
            document_modified=document.modified,
            current=current_values(document, taxonomy),
            proposed=result.proposed,
            checks=result.checks,
            lesson_ids=[lesson.id for lesson in lessons],
        )
