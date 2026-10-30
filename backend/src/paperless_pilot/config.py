"""Konfiguration über Umgebungsvariablen mit dem Präfix ``PILOT_``."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaHostConfig(BaseModel):
    name: str
    url: HttpUrl
    model: str | None = None  # weicht vom Standardmodell ab, z. B. kleineres Modell


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PILOT_", env_file=".env", extra="ignore")

    paperless_url: HttpUrl | None = None
    paperless_token: SecretStr | None = None
    paperless_token_file: Path | None = None

    # JSON, z. B. [{"name": "Mac", "url": "http://mac.local:11434"}]
    ollama_hosts: list[OllamaHostConfig] = []

    extraction_model: str = "gemma4:26b"

    # Home Assistant (optional): Leerlauf- und Sperr-Entitäten für die Rechner-Freigabe
    ha_url: HttpUrl | None = None
    ha_token: SecretStr | None = None
    ha_token_file: Path | None = None

    data_dir: Path = Path("/data")
    timezone: str = "Europe/Berlin"

    http_timeout_seconds: float = 10.0
    llm_timeout_seconds: float = 600.0
    intake_interval_seconds: float = 60.0
    host_probe_interval_seconds: float = 30.0

    # Demo-Modus: erfundene Dokumente, Attrappen statt Paperless und Ollama
    demo: bool = False

    # Gebautes Frontend; fehlt es, liefert der Dienst nur die API aus.
    static_dir: Path | None = None

    host: str = "0.0.0.0"  # noqa: S104 - läuft im Container und muss von außen erreichbar sein
    port: int = 8080

    @model_validator(mode="after")
    def _require_paperless(self) -> Self:
        if self.demo:
            return self
        if self.paperless_url is None:
            msg = "PILOT_PAPERLESS_URL muss gesetzt sein"
            raise ValueError(msg)
        if self.paperless_token is None and self.paperless_token_file is None:
            msg = "PILOT_PAPERLESS_TOKEN oder PILOT_PAPERLESS_TOKEN_FILE muss gesetzt sein"
            raise ValueError(msg)
        return self

    def resolve_paperless_token(self) -> str:
        token = _secret(self.paperless_token, self.paperless_token_file)
        if token is None:
            msg = "Kein Paperless-Token konfiguriert"
            raise ValueError(msg)
        return token

    def resolve_ha_token(self) -> str | None:
        return _secret(self.ha_token, self.ha_token_file)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "pilot.db"


def _secret(value: SecretStr | None, file: Path | None) -> str | None:
    if value is not None:
        return value.get_secret_value()
    if file is not None:
        return file.read_text(encoding="utf-8").strip()
    return None
