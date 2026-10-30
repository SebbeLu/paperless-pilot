"""Tabellen für Phase 1: Aufträge, Vorschläge, Verlauf, Rechner, Taxonomie.

Bewusst ausgeschrieben statt ``metadata.create_all``: Eine Migration beschreibt den Stand
zu ihrem Zeitpunkt und darf sich nicht mitändern, wenn ``schema.py`` später wächst.
"""

import sqlalchemy as sa
from alembic import op

from paperless_pilot.adapters.db.schema import UtcDateTime

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("not_before", UtcDateTime, nullable=False),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", UtcDateTime),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", UtcDateTime, nullable=False),
        sa.Column("updated_at", UtcDateTime, nullable=False),
    )
    op.create_index("ix_jobs_pick", "jobs", ["status", "not_before"])
    op.create_index(
        "uq_jobs_active",
        "jobs",
        ["document_id", "kind"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer, nullable=False, index=True),
        sa.Column("job_id", sa.Integer),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("host", sa.String(128), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("document_modified", UtcDateTime),
        sa.Column("current", sa.JSON, nullable=False),
        sa.Column("proposed", sa.JSON, nullable=False),
        sa.Column("checks", sa.JSON, nullable=False),
        sa.Column("created_at", UtcDateTime, nullable=False),
        sa.Column("decided_at", UtcDateTime),
        sa.Column("note", sa.Text),
    )
    op.create_table(
        "changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer, nullable=False, index=True),
        sa.Column("suggestion_id", sa.Integer),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("before", sa.JSON, nullable=False),
        sa.Column("after", sa.JSON, nullable=False),
        sa.Column("created_at", UtcDateTime, nullable=False),
        sa.Column("reverted_by", sa.Integer),
    )
    op.create_table(
        "host_settings",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("rules", sa.JSON, nullable=False),
        sa.Column("updated_at", UtcDateTime, nullable=False),
    )
    op.create_table(
        "taxonomy",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("configured", sa.Boolean, nullable=False),
        sa.Column("updated_at", UtcDateTime, nullable=False),
    )


def downgrade() -> None:
    for table in ("taxonomy", "host_settings", "changes", "suggestions", "jobs"):
        op.drop_table(table)
