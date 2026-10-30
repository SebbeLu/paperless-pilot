"""Anwendungsfall Verlauf: Änderungen ansehen und rückgängig machen."""

from paperless_pilot.adapters.db.repositories import ChangeRepository, SuggestionRepository
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.changes import Actor, Change, ChangeKind, DocumentState, NewChange
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from paperless_pilot.domain.ports import DocumentRepository
from paperless_pilot.domain.suggestions import SuggestionStatus

FIELD_LABELS = {
    "title": "Titel",
    "document_type_id": "Dokumenttyp",
    "correspondent_id": "Absender",
    "created": "Datum",
    "tag_ids": "Tags",
}


class HistoryService:
    def __init__(
        self,
        paperless: DocumentRepository,
        changes: ChangeRepository,
        suggestions: SuggestionRepository,
        clock: Clock,
        events: EventBus,
    ) -> None:
        self._paperless = paperless
        self._changes = changes
        self._suggestions = suggestions
        self._clock = clock
        self._events = events

    async def list(
        self, document_id: int | None = None, before_id: int | None = None, limit: int = 50
    ) -> list[Change]:
        return await self._changes.list(document_id=document_id, before_id=before_id, limit=limit)

    async def revert(self, change_id: int, *, force: bool = False) -> Change:
        """Stand vor der Übernahme zurückschreiben; der Vorschlag kommt wieder in die Prüfliste."""
        change = await self._changes.get(change_id)
        if change is None:
            msg = f"Änderung {change_id} nicht gefunden"
            raise NotFoundError(msg)
        if change.kind != ChangeKind.APPLY:
            msg = "Nur Übernahmen lassen sich rückgängig machen"
            raise ValidationFailedError(msg)
        if change.reverted_by is not None:
            msg = "Diese Änderung wurde bereits rückgängig gemacht"
            raise ValidationFailedError(msg)

        document = await self._paperless.get_document(change.document_id)
        current = DocumentState.of(document)
        if not force and (differs := current.differs_from(change.after)):
            labels = [FIELD_LABELS[f] for f in differs]
            msg = f"Das Dokument wurde seitdem in Paperless geändert ({', '.join(labels)})"
            raise ConflictError(msg, labels)

        updated = await self._paperless.update_document(document.id, change.before.to_patch())
        revert = await self._changes.add(
            NewChange(
                document_id=document.id,
                suggestion_id=change.suggestion_id,
                kind=ChangeKind.REVERT,
                actor=Actor.USER,
                before=current,
                after=DocumentState.of(updated),
            ),
            self._clock.now(),
        )
        await self._changes.mark_reverted(change.id, revert.id)
        if change.suggestion_id is not None:
            await self._suggestions.set_status(change.suggestion_id, SuggestionStatus.OPEN, None)
            await self._suggestions.set_document_modified(change.suggestion_id, updated.modified)
            self._events.publish("suggestions", document.id)
        self._events.publish("changes", document.id)
        return revert
