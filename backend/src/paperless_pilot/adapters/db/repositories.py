"""Repositories: übersetzen zwischen Tabellen und Domänenmodellen."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Row, and_, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db import schema as t
from paperless_pilot.domain.availability import HostRules
from paperless_pilot.domain.changes import Change, NewChange
from paperless_pilot.domain.jobs import (
    ACTIVE_STATUSES,
    Job,
    JobKind,
    JobStatus,
    QueueStats,
)
from paperless_pilot.domain.lessons import Lesson, NewLesson
from paperless_pilot.domain.suggestions import NewSuggestion, Suggestion, SuggestionStatus
from paperless_pilot.domain.taxonomy import Taxonomy


class JobRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def enqueue(
        self, document_id: int, kind: JobKind, now: datetime, *, priority: int = 0
    ) -> tuple[Job, bool]:
        """Reiht ein, falls kein aktiver Auftrag existiert. Liefert (Auftrag, neu angelegt?)."""
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(t.jobs).where(
                        t.jobs.c.document_id == document_id,
                        t.jobs.c.kind == kind,
                        t.jobs.c.status.in_(ACTIVE_STATUSES),
                    )
                )
            ).first()
            if existing is not None:
                return _job(existing), False
            row = (
                await conn.execute(
                    insert(t.jobs)
                    .values(
                        document_id=document_id,
                        kind=kind,
                        status=JobStatus.QUEUED,
                        attempts=0,
                        priority=priority,
                        not_before=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(t.jobs)
                )
            ).one()
            return _job(row), True

    async def lease_next(self, owner: str, now: datetime, lease_for: timedelta) -> Job | None:
        """Holt atomar den nächsten fälligen Auftrag. Abgelaufene Leases fallen vorher zurück."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(t.jobs)
                .where(t.jobs.c.status == JobStatus.RUNNING, t.jobs.c.lease_expires_at < now)
                .values(
                    status=JobStatus.QUEUED, lease_owner=None, lease_expires_at=None, updated_at=now
                )
            )
            next_id = (
                select(t.jobs.c.id)
                .where(t.jobs.c.status == JobStatus.QUEUED, t.jobs.c.not_before <= now)
                .order_by(t.jobs.c.priority.desc(), t.jobs.c.id)
                .limit(1)
                .scalar_subquery()
            )
            row = (
                await conn.execute(
                    update(t.jobs)
                    .where(t.jobs.c.id == next_id, t.jobs.c.status == JobStatus.QUEUED)
                    .values(
                        status=JobStatus.RUNNING,
                        lease_owner=owner,
                        lease_expires_at=now + lease_for,
                        attempts=t.jobs.c.attempts + 1,
                        updated_at=now,
                    )
                    .returning(t.jobs)
                )
            ).first()
            return _job(row) if row else None

    async def complete(self, job_id: int, now: datetime) -> None:
        await self._set(job_id, now, status=JobStatus.SUCCEEDED, last_error=None)

    async def fail(self, job_id: int, now: datetime, error: str, retry_at: datetime | None) -> Job:
        """Fehlgeschlagen: mit ``retry_at`` erneut einreihen, sonst endgültig."""
        if retry_at is None:
            return await self._set(job_id, now, status=JobStatus.FAILED, last_error=error)
        return await self._set(
            job_id, now, status=JobStatus.QUEUED, last_error=error, not_before=retry_at
        )

    async def release(self, job_id: int, now: datetime, error: str) -> Job:
        """Zurückgeben ohne Versuch zu zählen – der Rechner, nicht der Auftrag, war das Problem."""
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    update(t.jobs)
                    .where(t.jobs.c.id == job_id)
                    .values(
                        status=JobStatus.QUEUED,
                        attempts=func.max(t.jobs.c.attempts - 1, 0),
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error=error,
                        updated_at=now,
                    )
                    .returning(t.jobs)
                )
            ).one()
            return _job(row)

    async def retry(self, job_id: int, now: datetime) -> Job | None:
        """Endgültig fehlgeschlagenen Auftrag erneut einreihen (von Hand)."""
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    update(t.jobs)
                    .where(t.jobs.c.id == job_id, t.jobs.c.status == JobStatus.FAILED)
                    .values(status=JobStatus.QUEUED, attempts=0, not_before=now, updated_at=now)
                    .returning(t.jobs)
                )
            ).first()
            return _job(row) if row else None

    async def get(self, job_id: int) -> Job | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(t.jobs).where(t.jobs.c.id == job_id))).first()
            return _job(row) if row else None

    async def list(self, status: JobStatus | None = None, limit: int = 200) -> list[Job]:
        query = select(t.jobs).order_by(t.jobs.c.id.desc()).limit(limit)
        if status is not None:
            query = query.where(t.jobs.c.status == status)
        async with self._engine.connect() as conn:
            return [_job(r) for r in await conn.execute(query)]

    async def stats(self) -> QueueStats:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(t.jobs.c.status, func.count()).group_by(t.jobs.c.status)
            )
            return QueueStats(**{str(status): int(count) for status, count in rows.all()})

    async def _set(self, job_id: int, now: datetime, **values: Any) -> Job:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    update(t.jobs)
                    .where(t.jobs.c.id == job_id)
                    .values(lease_owner=None, lease_expires_at=None, updated_at=now, **values)
                    .returning(t.jobs)
                )
            ).one()
            return _job(row)


def _job(row: Row[Any]) -> Job:
    return Job.model_validate(row._mapping)


class SuggestionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add(self, new: NewSuggestion, now: datetime) -> Suggestion:
        """Speichert einen Vorschlag; ältere offene Vorschläge zum Dokument werden überholt."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(t.suggestions)
                .where(
                    t.suggestions.c.document_id == new.document_id,
                    t.suggestions.c.status == SuggestionStatus.OPEN,
                )
                .values(status=SuggestionStatus.SUPERSEDED, decided_at=now)
            )
            row = (
                await conn.execute(
                    insert(t.suggestions)
                    .values(
                        **new.model_dump(mode="json", exclude={"document_modified"}),
                        document_modified=new.document_modified,
                        status=SuggestionStatus.OPEN,
                        created_at=now,
                    )
                    .returning(t.suggestions)
                )
            ).one()
            return _suggestion(row)

    async def get(self, suggestion_id: int) -> Suggestion | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(t.suggestions).where(t.suggestions.c.id == suggestion_id))
            ).first()
            return _suggestion(row) if row else None

    async def list(
        self, status: SuggestionStatus | None = SuggestionStatus.OPEN, limit: int = 500
    ) -> list[Suggestion]:
        query = select(t.suggestions).order_by(t.suggestions.c.id).limit(limit)
        if status is not None:
            query = query.where(t.suggestions.c.status == status)
        async with self._engine.connect() as conn:
            return [_suggestion(r) for r in await conn.execute(query)]

    async def count_open(self) -> int:
        async with self._engine.connect() as conn:
            return int(
                (
                    await conn.execute(
                        select(func.count()).where(t.suggestions.c.status == SuggestionStatus.OPEN)
                    )
                ).scalar_one()
            )

    async def set_status(
        self,
        suggestion_id: int,
        status: SuggestionStatus,
        now: datetime | None,
        note: str | None = None,
    ) -> Suggestion:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    update(t.suggestions)
                    .where(t.suggestions.c.id == suggestion_id)
                    .values(status=status, decided_at=now, note=note)
                    .returning(t.suggestions)
                )
            ).one()
            return _suggestion(row)

    async def set_document_modified(self, suggestion_id: int, modified: datetime | None) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(t.suggestions)
                .where(t.suggestions.c.id == suggestion_id)
                .values(document_modified=modified)
            )


def _suggestion(row: Row[Any]) -> Suggestion:
    return Suggestion.model_validate(dict(row._mapping))


class ChangeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add(self, new: NewChange, now: datetime) -> Change:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    insert(t.changes)
                    .values(**new.model_dump(mode="json"), created_at=now)
                    .returning(t.changes)
                )
            ).one()
            return _change(row)

    async def get(self, change_id: int) -> Change | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(t.changes).where(t.changes.c.id == change_id))).first()
            return _change(row) if row else None

    async def list(
        self, document_id: int | None = None, limit: int = 200, before_id: int | None = None
    ) -> list[Change]:
        conditions = []
        if document_id is not None:
            conditions.append(t.changes.c.document_id == document_id)
        if before_id is not None:
            conditions.append(t.changes.c.id < before_id)
        query = select(t.changes).order_by(t.changes.c.id.desc()).limit(limit)
        if conditions:
            query = query.where(and_(*conditions))
        async with self._engine.connect() as conn:
            return [_change(r) for r in await conn.execute(query)]

    async def mark_reverted(self, change_id: int, reverted_by: int) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(t.changes).where(t.changes.c.id == change_id).values(reverted_by=reverted_by)
            )


def _change(row: Row[Any]) -> Change:
    return Change.model_validate(dict(row._mapping))


class LessonRepository:
    """Korrekturen als Beispiele; je Dokument gilt nur die neueste."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, new: NewLesson, now: datetime) -> Lesson:
        async with self._engine.begin() as conn:
            await conn.execute(delete(t.lessons).where(t.lessons.c.document_id == new.document_id))
            row = (
                await conn.execute(
                    insert(t.lessons)
                    .values(**new.model_dump(mode="json"), active=True, created_at=now)
                    .returning(t.lessons)
                )
            ).one()
            return _lesson(row)

    async def list_active(self) -> list[Lesson]:
        query = select(t.lessons).where(t.lessons.c.active).order_by(t.lessons.c.id.desc())
        async with self._engine.connect() as conn:
            return [_lesson(r) for r in await conn.execute(query)]

    async def forget(self, lesson_id: int) -> bool:
        """Abschalten statt löschen, damit das Nachlernen beim Start sie nicht wieder anlegt."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(t.lessons)
                .where(t.lessons.c.id == lesson_id, t.lessons.c.active)
                .values(active=False)
            )
            return bool(result.rowcount)

    async def remove_for_suggestion(self, suggestion_id: int) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(t.lessons).where(t.lessons.c.suggestion_id == suggestion_id))

    async def known_suggestion_ids(self) -> set[int]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(select(t.lessons.c.suggestion_id))
            return {int(r.suggestion_id) for r in rows}


def _lesson(row: Row[Any]) -> Lesson:
    return Lesson.model_validate(dict(row._mapping))


class HostSettingsRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_all(self) -> dict[str, HostRules]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(select(t.host_settings))
            return {r.name: HostRules.model_validate(r.rules) for r in rows}

    async def save(self, name: str, rules: HostRules, now: datetime) -> None:
        async with self._engine.begin() as conn:
            updated = await conn.execute(
                update(t.host_settings)
                .where(t.host_settings.c.name == name)
                .values(rules=rules.model_dump(mode="json"), updated_at=now)
            )
            if updated.rowcount == 0:
                await conn.execute(
                    insert(t.host_settings).values(
                        name=name, rules=rules.model_dump(mode="json"), updated_at=now
                    )
                )


class TaxonomyRepository:
    """Genau eine Taxonomie, gespeichert als JSON-Dokument."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self) -> tuple[Taxonomy, bool]:
        """Liefert (Taxonomie, wurde sie schon einmal gespeichert?)."""
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(t.taxonomy).where(t.taxonomy.c.id == 1))).first()
            if row is None:
                return Taxonomy(), False
            return Taxonomy.model_validate(row.data), bool(row.configured)

    async def save(self, taxonomy: Taxonomy, now: datetime) -> None:
        data = taxonomy.model_dump(mode="json")
        async with self._engine.begin() as conn:
            updated = await conn.execute(
                update(t.taxonomy)
                .where(t.taxonomy.c.id == 1)
                .values(data=data, configured=True, updated_at=now)
            )
            if updated.rowcount == 0:
                await conn.execute(
                    insert(t.taxonomy).values(id=1, data=data, configured=True, updated_at=now)
                )
