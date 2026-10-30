"""Anwendungsfall Prüfliste: Vorschläge übernehmen, verwerfen oder neu auslesen."""

from pydantic import BaseModel

from paperless_pilot.adapters.db.repositories import (
    ChangeRepository,
    JobRepository,
    SuggestionRepository,
    TaxonomyRepository,
)
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.changes import Actor, Change, ChangeKind, DocumentState, NewChange
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from paperless_pilot.domain.extraction import current_values
from paperless_pilot.domain.jobs import JobKind
from paperless_pilot.domain.matching import normalize_name
from paperless_pilot.domain.models import Document, DocumentPatch
from paperless_pilot.domain.ports import DocumentRepository
from paperless_pilot.domain.suggestions import MetadataValues, Suggestion, SuggestionStatus
from paperless_pilot.domain.taxonomy import Taxonomy

REEXTRACT_PRIORITY = 10


class SuggestionDetail(BaseModel):
    suggestion: Suggestion
    live: MetadataValues  # aktueller Stand in Paperless
    original_file_name: str
    changed_since: list[str]  # Felder, die seit dem Auslesen in Paperless geändert wurden


class ReviewService:
    def __init__(
        self,
        paperless: DocumentRepository,
        suggestions: SuggestionRepository,
        changes: ChangeRepository,
        jobs: JobRepository,
        taxonomy: TaxonomyRepository,
        clock: Clock,
        events: EventBus,
    ) -> None:
        self._paperless = paperless
        self._suggestions = suggestions
        self._changes = changes
        self._jobs = jobs
        self._taxonomy = taxonomy
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
        )

    async def accept(
        self, suggestion_id: int, values: MetadataValues, *, force: bool = False
    ) -> Change:
        """Schreibt die (ggf. korrigierten) Werte nach Paperless und protokolliert die Änderung."""
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
        updated = await self._paperless.update_document(document.id, patch)
        change = await self._changes.add(
            NewChange(
                document_id=document.id,
                suggestion_id=suggestion.id,
                kind=ChangeKind.APPLY,
                actor=Actor.USER,
                before=DocumentState.of(document),
                after=DocumentState.of(updated),
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
        self._events.publish("suggestions", document.id)
        self._events.publish("changes", document.id)
        return change

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

    async def reextract(self, suggestion_id: int) -> Suggestion:
        """Vorschlag verwerfen und das Dokument mit Vorrang neu auslesen."""
        suggestion = await self._get_open(suggestion_id)
        taxonomy, _ = await self._taxonomy.get()
        await self._replace_status(
            suggestion.document_id, taxonomy, taxonomy.status.todo.paperless_id
        )
        superseded = await self._suggestions.set_status(
            suggestion.id, SuggestionStatus.SUPERSEDED, self._clock.now(), note="neu auslesen"
        )
        await self._jobs.enqueue(
            suggestion.document_id, JobKind.EXTRACT, self._clock.now(), priority=REEXTRACT_PRIORITY
        )
        self._events.publish("suggestions", suggestion.document_id)
        self._events.publish("jobs", suggestion.document_id)
        return superseded

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
