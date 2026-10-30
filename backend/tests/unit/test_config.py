from pathlib import Path

import pytest
from pydantic import ValidationError

from paperless_pilot.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("PILOT_PAPERLESS_URL", "PILOT_PAPERLESS_TOKEN", "PILOT_PAPERLESS_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # keine lokale .env einlesen


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PILOT_PAPERLESS_URL", "http://paperless:8000")
    monkeypatch.setenv("PILOT_PAPERLESS_TOKEN", "abc")
    monkeypatch.setenv(
        "PILOT_OLLAMA_HOSTS",
        '[{"name": "Mac", "url": "http://mac.local:11434"}]',
    )

    settings = Settings()

    assert str(settings.paperless_url) == "http://paperless:8000/"
    assert settings.resolve_paperless_token() == "abc"
    assert settings.ollama_hosts[0].name == "Mac"
    assert settings.port == 8080


def test_token_from_file(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("geheim\n", encoding="utf-8")

    settings = Settings(paperless_url="http://p", paperless_token_file=token_file)

    assert settings.resolve_paperless_token() == "geheim"


def test_token_is_required() -> None:
    with pytest.raises(ValidationError, match="PILOT_PAPERLESS_TOKEN"):
        Settings(paperless_url="http://p")


def test_token_is_not_leaked_in_repr() -> None:
    settings = Settings(paperless_url="http://p", paperless_token="geheim")

    assert "geheim" not in repr(settings)
