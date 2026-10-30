"""Tabellen der SQLite-Datenbank (SQLAlchemy Core)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Dialect,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
)

_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


class UtcDateTime(TypeDecorator[datetime]):
    """Speichert Zeitpunkte als UTC-Text fester Breite – damit sind Vergleiche in SQL korrekt."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            msg = "Zeitpunkte müssen eine Zeitzone haben"
            raise ValueError(msg)
        return value.astimezone(UTC).strftime(_FORMAT)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.strptime(str(value), _FORMAT).replace(tzinfo=UTC)


metadata = MetaData()

jobs = Table(
    "jobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_id", Integer, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("priority", Integer, nullable=False, default=0),
    Column("not_before", UtcDateTime, nullable=False),
    Column("lease_owner", String(128)),
    Column("lease_expires_at", UtcDateTime),
    Column("last_error", Text),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Index("ix_jobs_pick", "status", "not_before"),
    Index(
        "uq_jobs_active",
        "document_id",
        "kind",
        unique=True,
        sqlite_where=Column("status").in_(["queued", "running"]),
    ),
)

suggestions = Table(
    "suggestions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_id", Integer, nullable=False, index=True),
    Column("job_id", Integer),
    Column("status", String(16), nullable=False, index=True),
    Column("model", String(128), nullable=False),
    Column("host", String(128), nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("document_modified", UtcDateTime),
    Column("current", JSON, nullable=False),
    Column("proposed", JSON, nullable=False),
    Column("checks", JSON, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("decided_at", UtcDateTime),
    Column("note", Text),
)

changes = Table(
    "changes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_id", Integer, nullable=False, index=True),
    Column("suggestion_id", Integer),
    Column("kind", String(16), nullable=False),
    Column("actor", String(16), nullable=False),
    Column("before", JSON, nullable=False),
    Column("after", JSON, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("reverted_by", Integer),
)

host_settings = Table(
    "host_settings",
    metadata,
    Column("name", String(128), primary_key=True),
    Column("rules", JSON, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
)

taxonomy = Table(
    "taxonomy",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("data", JSON, nullable=False),
    Column("configured", Boolean, nullable=False, default=False),
    Column("updated_at", UtcDateTime, nullable=False),
)
