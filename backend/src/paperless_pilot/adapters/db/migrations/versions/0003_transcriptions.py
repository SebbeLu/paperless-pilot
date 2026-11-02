"""Vision-OCR: Abschriften je Dokument."""

import sqlalchemy as sa
from alembic import op

from paperless_pilot.adapters.db.schema import UtcDateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcriptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer, nullable=False, unique=True),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("created_at", UtcDateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("transcriptions")
