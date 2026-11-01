"""Anwendungsfall Lernen: Korrekturen festhalten, auswählen, ansehen und vergessen."""

import logging
from collections.abc import Sequence

from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    LessonRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.changes import ChangeKind
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import NotFoundError, PilotError
from paperless_pilot.domain.lessons import (
    Lesson,
    NewLesson,
    corrected_fields,
    excerpt,
    named_values,
    select_lessons,
    values_of_state,
)
from paperless_pilot.domain.models import Correspondent, Document
from paperless_pilot.domain.ports import DocumentRepository
from paperless_pilot.domain.suggestions import MetadataValues, Suggestion, SuggestionStatus
from paperless_pilot.domain.taxonomy import Taxonomy

logger = logging.getLogger(__name__)


class LessonService:
    def __init__(
        self,
        paperless: DocumentRepository,
        lessons: LessonRepository,
        suggestions: SuggestionRepository,
        changes: ChangeRepository,
        taxonomy: TaxonomyRepository,
        clock: Clock,
        events: EventBus,
    ) -> None:
        self._paperless = paperless
        self._lessons = lessons
        self._suggestions = suggestions
        self._changes = changes
        self._taxonomy = taxonomy
        self._clock = clock
        self._events = events

    async def learn(
        self, suggestion: Suggestion, final: MetadataValues, document: Document
    ) -> Lesson | None:
        """Hält fest, was du beim Übernehmen korrigiert hast – ohne Korrektur nichts."""
        taxonomy, _ = await self._taxonomy.get()
        correspondents = await self._paperless.list_correspondents()
        lesson = _lesson_for(suggestion, final, taxonomy, correspondents)
        return await self._save(lesson, document) if lesson else None

    async def backfill(self) -> int:
        """Lernt aus Übernahmen, die vor dieser Funktion entschieden wurden."""
        known = await self._lessons.known_suggestion_ids()
        applied = {
            c.suggestion_id: c
            for c in reversed(await self._changes.list(limit=10_000))
            if c.kind == ChangeKind.APPLY and c.reverted_by is None and c.suggestion_id
        }
        taxonomy, _ = await self._taxonomy.get()
        correspondents = await self._paperless.list_correspondents()
        learned = 0
        for suggestion in await self._suggestions.list(SuggestionStatus.ACCEPTED, limit=10_000):
            change = applied.get(suggestion.id)
            if change is None or suggestion.id in known:
                continue
            final = values_of_state(change.after, taxonomy)
            if (lesson := _lesson_for(suggestion, final, taxonomy, correspondents)) is None:
                continue
            try:
                await self._save(lesson, await self._paperless.get_document(suggestion.document_id))
            except PilotError:
                logger.warning("Dokument %d: Korrektur nicht übernommen", suggestion.document_id)
                continue
            learned += 1
        if learned:
            logger.info("%d frühere Korrektur(en) als Beispiel übernommen", learned)
        return learned

    async def _save(self, lesson: NewLesson, document: Document) -> Lesson:
        saved = await self._lessons.save(
            lesson.model_copy(
                update={
                    "excerpt": excerpt(document.content),
                    "file_name": document.original_file_name,
                }
            ),
            self._clock.now(),
        )
        self._events.publish("lessons", document.id)
        return saved

    async def for_document(self, document: Document) -> list[Lesson]:
        return select_lessons(await self._lessons.list_active(), document)

    async def list(self) -> list[Lesson]:
        return await self._lessons.list_active()

    async def forget(self, lesson_id: int) -> None:
        if not await self._lessons.forget(lesson_id):
            msg = f"Korrektur {lesson_id} nicht gefunden"
            raise NotFoundError(msg)
        self._events.publish("lessons")

    async def unlearn(self, suggestion_id: int) -> None:
        """Nach Rückgängig: die Übernahme gilt nicht mehr, also auch nicht ihre Korrektur."""
        await self._lessons.remove_for_suggestion(suggestion_id)
        self._events.publish("lessons")


def _lesson_for(
    suggestion: Suggestion,
    final: MetadataValues,
    taxonomy: Taxonomy,
    correspondents: Sequence[Correspondent],
) -> NewLesson | None:
    proposed = named_values(suggestion.proposed, taxonomy, correspondents)
    correct = named_values(final, taxonomy, correspondents)
    before = named_values(suggestion.current, taxonomy, correspondents)
    if not (corrected := corrected_fields(proposed, correct, before)):
        return None
    return NewLesson(
        document_id=suggestion.document_id,
        suggestion_id=suggestion.id,
        excerpt="",  # kommt beim Speichern aus dem Dokumenttext
        correct=correct,
        proposed=proposed,
        corrected=corrected,
    )
