from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text

from paperless_pilot.adapters.db.database import MIGRATIONS, create_engine, migrate
from paperless_pilot.adapters.db.repositories import SuggestionRepository


def _upgrade_to(revision: str):  # type: ignore[no-untyped-def]
    def run(connection: Connection) -> None:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        config.attributes["connection"] = connection
        command.upgrade(config, revision)

    return run


async def test_existing_suggestions_survive_upgrade(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "pilot.db")
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade_to("0001"))
        await conn.execute(
            text(
                "INSERT INTO suggestions (document_id, status, model, host, duration_ms, current,"
                " proposed, checks, created_at) VALUES (5, 'accepted', 'm', 'Mac', 1, '{}', '{}',"
                " '{}', '2026-10-30T12:00:00.000000+00:00')"
            )
        )

    await migrate(engine)

    [old] = await SuggestionRepository(engine).list(None)
    assert old.document_id == 5
    assert old.lesson_ids == []
    await engine.dispose()
