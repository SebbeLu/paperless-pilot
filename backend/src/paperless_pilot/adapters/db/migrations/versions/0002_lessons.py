"""Lernen aus Korrekturen: Tabelle der Beispiele und welche ein Vorschlag bekam."""

import sqlalchemy as sa
from alembic import op

from paperless_pilot.adapters.db.schema import UtcDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer, nullable=False, unique=True),
        sa.Column("suggestion_id", sa.Integer, nullable=False, index=True),
        sa.Column("excerpt", sa.Text, nullable=False),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("correct", sa.JSON, nullable=False),
        sa.Column("proposed", sa.JSON, nullable=False),
        sa.Column("corrected", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", UtcDateTime, nullable=False),
    )
    with op.batch_alter_table("suggestions") as batch:
        batch.add_column(
            sa.Column("lesson_ids", sa.JSON, nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("suggestions") as batch:
        batch.drop_column("lesson_ids")
    op.drop_table("lessons")
