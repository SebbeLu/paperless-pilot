"""Vision-OCR: Herkunft und Prüfergebnis der Abschrift am Vorschlag."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("suggestions") as batch:
        batch.add_column(sa.Column("transcription", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("suggestions") as batch:
        batch.drop_column("transcription")
