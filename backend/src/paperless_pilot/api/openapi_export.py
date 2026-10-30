"""Schreibt die OpenAPI-Beschreibung als JSON – Grundlage für den typisierten Frontend-Client.

Aufruf: ``uv run python -m paperless_pilot.api.openapi_export ../frontend/openapi.json``
"""

import json
import sys
from pathlib import Path

from paperless_pilot.api.app import create_app
from paperless_pilot.config import Settings


def export(target: Path) -> None:
    # Die Beschreibung hängt nicht von echten Zugangsdaten ab.
    settings = Settings.model_validate(
        {"paperless_url": "http://paperless.invalid", "paperless_token": "unused"}
    )
    schema = create_app(settings).openapi()
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export(Path(sys.argv[1]))
