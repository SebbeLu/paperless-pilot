"""Kommandozeile: `paperless-pilot` startet den Dienst, `paperless-pilot extract` testet."""

import argparse
import asyncio
import json
import logging
from zoneinfo import ZoneInfo

import uvicorn

from paperless_pilot.api.container import build_container, real_adapters
from paperless_pilot.application.extraction import ExtractionService
from paperless_pilot.config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paperless-pilot")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Dienst starten (Standard)")
    extract = commands.add_parser(
        "extract", help="Dokumente auslesen und Vorschlag anzeigen – schreibt nichts"
    )
    extract.add_argument("document_ids", type=int, nargs="+")
    extract.add_argument("--host", help="Name des Ollama-Rechners (Standard: erster)")
    extract.add_argument("--model", help="Modell (Standard: PILOT_EXTRACTION_MODEL)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()  # Pflichtwerte kommen aus der Umgebung
    if args.command == "extract":
        asyncio.run(_extract(settings, args.document_ids, args.host, args.model))
        return
    uvicorn.run(
        "paperless_pilot.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
    )


async def _extract(
    settings: Settings, document_ids: list[int], host_name: str | None, model: str | None
) -> None:
    async with (
        real_adapters(settings) as adapters,
        build_container(settings, adapters) as container,
    ):
        hosts = [h for h in adapters.hosts if host_name in (None, h.name)]
        if not hosts:
            msg = f"Kein Ollama-Rechner {host_name or ''} konfiguriert"
            raise SystemExit(msg)
        service = ExtractionService(
            adapters.paperless,
            container.taxonomy_repository,
            adapters.clock,
            ZoneInfo(settings.timezone),
        )
        for document_id in document_ids:
            suggestion = await service.extract(
                document_id, hosts[0], model or settings.extraction_model
            )
            print(json.dumps(suggestion.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
