"""Konfiguration über Umgebungsvariablen mit dem Präfix ``PILOT_``."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaHostConfig(BaseModel):
    name: str
    url: HttpUrl


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PILOT_", env_file=".env", extra="ignore")

    paperless_url: HttpUrl
    paperless_token: SecretStr | None = None
    paperless_token_file: Path | None = None

    # JSON, z. B. [{"name": "Mac", "url": "http://mac.local:11434"}]
    ollama_hosts: list[OllamaHostConfig] = []

    http_timeout_seconds: float = 10.0
    llm_timeout_seconds: float = 600.0

    # Gebautes Frontend; fehlt es, liefert der Dienst nur die API aus.
    static_dir: Path | None = None

    host: str = "0.0.0.0"  # noqa: S104 - läuft im Container und muss von außen erreichbar sein
    port: int = 8080

    @model_validator(mode="after")
    def _require_token_source(self) -> Self:
        if self.paperless_token is None and self.paperless_token_file is None:
            msg = "PILOT_PAPERLESS_TOKEN oder PILOT_PAPERLESS_TOKEN_FILE muss gesetzt sein"
            raise ValueError(msg)
        return self

    def resolve_paperless_token(self) -> str:
        if self.paperless_token is not None:
            return self.paperless_token.get_secret_value()
        assert self.paperless_token_file is not None  # durch den Validator garantiert  # noqa: S101
        return self.paperless_token_file.read_text(encoding="utf-8").strip()
