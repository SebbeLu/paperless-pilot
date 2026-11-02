"""Anwendungsfall Prüfliste: Vorschläge übernehmen, verwerfen oder neu auslesen."""

import logging

from pydantic import BaseModel

from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    JobRepository,
    SuggestionRepository,
    TaxonomyRepository,
    TranscriptionRepository,
)
from paperless_pilot.application.events import EventBus
from paperless_pilot.application.lessons import LessonService
from paperless_pilot.domain.changes import Actor, Change, ChangeKind, DocumentState, NewChange
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import (
    ConflictError,
    NotFoundError,
    PilotError,
    ValidationFailedError,
)
from paperless_pilot.domain.extraction import current_values
from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.matching import normalize_name
from paperless_pilot.domain.models import Document, DocumentPatch
from paperless_pilot.domain.ports import DocumentRepository
from paperless_pilot.domain.suggestions import MetadataValues, Suggestion, SuggestionStatus
from paperless_pilot.domain.taxonomy import Taxonomy

logger = logging.getLogger(__name__)

REEXTRACT_PRIORITY = 10


class SuggestionDetail(BaseModel):
    suggestion: Suggestion
    live: MetadataValues  # aktueller Stand in Paperless
    original_file_name: str
    changed_since: list[str]  # Felder, die seit dem Auslesen in Paperless geändert wurden
    live_content: str | None = None  # Text in Paperless – nur, wenn ein neuer vorgeschlagen ist


class BulkFailure(BaseModel):
    suggestion_id: int
    message: str


class AcceptManyResult(BaseModel):
    accepted: list[Change]
    failed: list[BulkFailure]  # bleiben offen, etwa weil in Paperless inzwischen geändert


class RejectManyResult(BaseModel):
    rejected: list[Suggestion]
    failed: list[BulkFailure]


class ReextractManyResult(BaseModel):
    reextracted: list[Suggestion]
    failed: list[BulkFailure]


class DocumentFailure(BaseModel):
    document_id: int
    message: str


class ReextractDocumentsResult(BaseModel):
    enqueued: list[int]
    failed: list[DocumentFailure]


class ReviewService:
    def __init__(
        self,
        paperless: DocumentRepository,
        suggestions: SuggestionRepository,
        changes: ChangeRepository,
        jobs: JobRepository,
        taxonomy: TaxonomyRepository,
        lessons: LessonService,
        clock: Clock,
        events: EventBus,
        *,
        transcriptions: TranscriptionRepository | None = None,
    ) -> None:
        self._paperless = paperless
        self._transcriptions = transcriptions
        self._suggestions = suggestions
        self._changes = changes
        self._jobs = jobs
        self._taxonomy = taxonomy
        self._lessons = lessons
        self._clock = clock
        self._events = events

    async def list_open(self) -> list[Suggestion]:
        """Offene Vorschläge, unsichere zuerst."""
        open_ = await self._suggestions.list(SuggestionStatus.OPEN)
        return sorted(open_, key=lambda s: (not s.needs_attention(), s.id))

    async def detail(self, suggestion_id: int) -> SuggestionDetail:
        suggestion = await self._get(suggestion_id)
        document = await self._paperless.get_document(suggestion.document_id)
        taxonomy, _ = await self._taxonomy.get()
        return SuggestionDetail(
            suggestion=suggestion,
            live=current_values(document, taxonomy),
            original_file_name=document.original_file_name,
            changed_since=_changed_since(suggestion, document, taxonomy),
            live_content=document.content if suggestion.proposed.content is not None else None,
        )

    async def accept(
        self, suggestion_id: int, values: MetadataValues, *, force: bool = False
    ) -> Change:
        """Schreibt die (ggf. korrigierten) Werte nach Paperless und protokolliert die Änderung.

        Ist ``values.content`` gesetzt, ersetzt es den OCR-Text (Vision-OCR); der bisherige Text
        steht dann im Verlauf und kommt mit „Rückgängig“ zurück.
        """
        suggestion = await self._get_open(suggestion_id)
        document = await self._paperless.get_document(suggestion.document_id)
        taxonomy, _ = await self._taxonomy.get()
        if not force and (changed := _changed_since(suggestion, document, taxonomy)):
            labels = ", ".join(changed)
            msg = f"Das Dokument wurde seit dem Auslesen in Paperless geändert ({labels})"
            raise ConflictError(msg, changed)

        correspondent_id = values.correspondent_id
        if correspondent_id is None and values.new_correspondent:
            correspondent_id = await self._correspondent_for(values.new_correspondent)

        patch = DocumentPatch(
            title=values.title or document.title,
            document_type_id=values.document_type_id,
            correspondent_id=correspondent_id,
            created=values.created or document.created,
            tag_ids=await self._tags_after_accept(document, values, taxonomy),
        )
        with_content = values.content is not None
        if with_content:
            patch = patch.model_copy(update={"content": values.content})
        updated = await self._paperless.update_document(document.id, patch)
        change = await self._changes.add(
            NewChange(
                document_id=document.id,
                suggestion_id=suggestion.id,
                kind=ChangeKind.APPLY,
                actor=Actor.USER,
                before=DocumentState.of(document, with_content=with_content),
                after=DocumentState.of(updated, with_content=with_content),
            ),
            self._clock.now(),
        )
        corrected = _corrected_fields(suggestion.proposed, values)
        await self._suggestions.set_status(
            suggestion.id,
            SuggestionStatus.ACCEPTED,
            self._clock.now(),
            note=f"korrigiert: {', '.join(corrected)}" if corrected else None,
        )
        final = values.model_copy(
            update={
                "title": patch.title,
                "correspondent_id": correspondent_id,
                "new_correspondent": None,
                "created": patch.created,
                "content": None,  # Beispiele fürs Lernen brauchen den Text nicht doppelt
            }
        )
        try:
            await self._lessons.learn(suggestion, final, document)
        except PilotError:  # die Übernahme selbst ist schon geschrieben
            logger.warning("Dokument %d: Korrektur nicht als Beispiel gemerkt", document.id)
        self._events.publish("suggestions", document.id)
        self._events.publish("changes", document.id)
        return change

    async def accept_many(
        self, suggestion_ids: list[int], *, with_content: bool = False
    ) -> AcceptManyResult:
        """Übernimmt mehrere Vorschläge unverändert; ein Fehler hält die übrigen nicht auf.

        Mit ``with_content`` wird eine Abschrift vom Bild mitgeschrieben, aber nur, wenn ihre
        Prüfung nichts gefunden hat – wie das vorausgewählte Kästchen in der Prüfansicht.
        """
        result = AcceptManyResult(accepted=[], failed=[])
        for suggestion_id in dict.fromkeys(suggestion_ids):
            try:
                suggestion = await self._get_open(suggestion_id)
                values = suggestion.proposed
                transcription = suggestion.transcription
                if not with_content or (transcription is not None and transcription.warnings):
                    values = values.model_copy(update={"content": None})
                result.accepted.append(await self.accept(suggestion.id, values))
            except PilotError as error:
                result.failed.append(BulkFailure(suggestion_id=suggestion_id, message=str(error)))
        return result

    async def reject(self, suggestion_id: int, reason: str | None = None) -> Suggestion:
        """Vorschlag verwerfen; der Status-Tag „prüfen“ wird entfernt, sonst bleibt alles."""
        suggestion = await self._get_open(suggestion_id)
        taxonomy, _ = await self._taxonomy.get()
        await self._replace_status(suggestion.document_id, taxonomy, None)
        rejected = await self._suggestions.set_status(
            suggestion.id, SuggestionStatus.REJECTED, self._clock.now(), note=reason
        )
        self._events.publish("suggestions", suggestion.document_id)
        return rejected

    async def reject_many(self, suggestion_ids: list[int]) -> RejectManyResult:
        result = RejectManyResult(rejected=[], failed=[])
        for suggestion_id in dict.fromkeys(suggestion_ids):
            try:
                result.rejected.append(await self.reject(suggestion_id))
            except PilotError as error:
                result.failed.append(BulkFailure(suggestion_id=suggestion_id, message=str(error)))
        return result

    async def reextract(self, suggestion_id: int, kind: JobKind = JobKind.EXTRACT) -> Suggestion:
        """Vorschlag verwerfen und das Dokument mit Vorrang neu auslesen.

        Mit `JobKind.TRANSCRIBE` wird vorher der Text neu vom Bild abgeschrieben."""
        suggestion = await self._get_open(suggestion_id)
        taxonomy, _ = await self._taxonomy.get()
        await self._replace_status(
            suggestion.document_id, taxonomy, taxonomy.status.todo.paperless_id
        )
        superseded = await self._suggestions.set_status(
            suggestion.id,
            SuggestionStatus.SUPERSEDED,
            self._clock.now(),
            note="Text neu erkennen" if kind == JobKind.TRANSCRIBE else "neu auslesen",
        )
        await self._requeue(suggestion.document_id, kind)
        self._events.publish("suggestions", suggestion.document_id)
        self._events.publish("jobs", suggestion.document_id)
        return superseded

    async def reextract_many(self, suggestion_ids: list[int]) -> ReextractManyResult:
        result = ReextractManyResult(reextracted=[], failed=[])
        for suggestion_id in dict.fromkeys(suggestion_ids):
            try:
                result.reextracted.append(await self.reextract(suggestion_id))
            except PilotError as error:
                result.failed.append(BulkFailure(suggestion_id=suggestion_id, message=str(error)))
        return result

    async def reextract_documents(
        self, document_ids: list[int], kind: JobKind = JobKind.EXTRACT
    ) -> ReextractDocumentsResult:
        """Dokumente mit Vorrang neu auslesen, auch bereits übernommene (etwa aus dem Verlauf)."""
        result = ReextractDocumentsResult(enqueued=[], failed=[])
        taxonomy, _ = await self._taxonomy.get()
        open_ = {s.document_id: s for s in await self._suggestions.list(SuggestionStatus.OPEN)}
        for document_id in dict.fromkeys(document_ids):
            try:
                if suggestion := open_.get(document_id):
                    # offener Vorschlag wird dabei verworfen
                    await self.reextract(suggestion.id, kind)
                else:
                    await self._replace_status(
                        document_id, taxonomy, taxonomy.status.todo.paperless_id
                    )
                    await self._requeue(document_id, kind)
            except PilotError as error:
                result.failed.append(DocumentFailure(document_id=document_id, message=str(error)))
                continue
            result.enqueued.append(document_id)
        if result.enqueued:
            self._events.publish("jobs")
        return result

    async def _requeue(self, document_id: int, kind: JobKind) -> None:
        if kind == JobKind.TRANSCRIBE and self._transcriptions is not None:
            # Die alte Abschrift darf das Auslesen nicht mehr beeinflussen
            await self._transcriptions.remove(document_id)
        await self._jobs.enqueue(document_id, kind, self._clock.now(), priority=REEXTRACT_PRIORITY)

    async def _get(self, suggestion_id: int) -> Suggestion:
        suggestion = await self._suggestions.get(suggestion_id)
        if suggestion is None:
            msg = f"Vorschlag {suggestion_id} nicht gefunden"
            raise NotFoundError(msg)
        return suggestion

    async def _get_open(self, suggestion_id: int) -> Suggestion:
        suggestion = await self._get(suggestion_id)
        if suggestion.status != SuggestionStatus.OPEN:
            msg = f"Vorschlag {suggestion_id} ist bereits entschieden ({suggestion.status})"
            raise ValidationFailedError(msg)
        return suggestion

    async def _correspondent_for(self, name: str) -> int:
        """Gleichnamigen Korrespondenten wiederverwenden (z. B. zweiter Brief), sonst anlegen."""
        wanted = normalize_name(name)
        for existing in await self._paperless.list_correspondents():
            if normalize_name(existing.name) == wanted:
                return existing.id
        return (await self._paperless.create_correspondent(name)).id

    async def _tags_after_accept(
        self, document: Document, values: MetadataValues, taxonomy: Taxonomy
    ) -> tuple[int, ...]:
        managed = taxonomy.managed_tag_ids()
        removed = set(managed)
        if taxonomy.remove_inbox_tag_on_accept:
            removed |= {t.id for t in await self._paperless.list_tags() if t.is_inbox_tag}
        tags = [t for t in document.tag_ids if t not in removed]
        tags.extend(values.person_tag_ids)
        if values.area_tag_id is not None:
            tags.append(values.area_tag_id)
        if taxonomy.status.done.paperless_id is not None:
            tags.append(taxonomy.status.done.paperless_id)
        return tuple(dict.fromkeys(tags))

    async def _replace_status(
        self, document_id: int, taxonomy: Taxonomy, status_tag: int | None
    ) -> None:
        status = taxonomy.status
        status_ids = {
            e.paperless_id
            for e in (status.todo, status.review, status.done, status.error)
            if e.paperless_id is not None
        }
        document = await self._paperless.get_document(document_id)
        tags = [t for t in document.tag_ids if t not in status_ids]
        if status_tag is not None:
            tags.append(status_tag)
        if sorted(tags) != sorted(document.tag_ids):
            await self._paperless.update_document(document_id, DocumentPatch(tag_ids=tuple(tags)))


def _changed_since(suggestion: Suggestion, document: Document, taxonomy: Taxonomy) -> list[str]:
    """Welche verwalteten Felder hat jemand seit dem Auslesen in Paperless geändert?"""
    if suggestion.document_modified is None or document.modified == suggestion.document_modified:
        return []
    then, now = suggestion.current, current_values(document, taxonomy)
    labels = {
        "title": "Titel",
        "document_type_id": "Dokumenttyp",
        "correspondent_id": "Absender",
        "created": "Datum",
        "person_tag_ids": "Personen",
        "area_tag_id": "Lebensbereich",
    }
    changed = [
        label
        for field, label in labels.items()
        if _comparable(getattr(then, field)) != _comparable(getattr(now, field))
    ]
    return changed or ["andere Felder"]


def _comparable(value: object) -> object:
    return tuple(sorted(value)) if isinstance(value, tuple) else value


def _corrected_fields(proposed: MetadataValues, final: MetadataValues) -> list[str]:
    fields = {
        "title": "Titel",
        "document_type_id": "Dokumenttyp",
        "correspondent_id": "Absender",
        "new_correspondent": "Absender",
        "created": "Datum",
        "person_tag_ids": "Personen",
        "area_tag_id": "Lebensbereich",
    }
    corrected = [
        label
        for field, label in fields.items()
        if _comparable(getattr(proposed, field)) != _comparable(getattr(final, field))
    ]
    return list(dict.fromkeys(corrected))
