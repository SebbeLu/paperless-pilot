"""Kommandozeile: `paperless-pilot` startet den Dienst, `extract` und `ocr-score` testen."""

import argparse
import asyncio
import json
import logging

import uvicorn

from paperless_pilot.api.container import build_container, real_adapters
from paperless_pilot.config import Settings
from paperless_pilot.domain.ocr_quality import OcrQuality, assess_ocr


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
    score = commands.add_parser(
        "ocr-score", help="Textqualität aller Dokumente bewerten – schreibt nichts"
    )
    score.add_argument("--worst", type=int, default=30, help="so viele schlechteste zeigen")
    score.add_argument(
        "--threshold", type=float, help="Schwelle (Standard: PILOT_OCR_QUALITY_THRESHOLD)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()  # Pflichtwerte kommen aus der Umgebung
    if args.command == "extract":
        asyncio.run(_extract(settings, args.document_ids, args.host, args.model))
        return
    if args.command == "ocr-score":
        threshold = args.threshold or settings.ocr_quality_threshold
        asyncio.run(_ocr_score(settings, args.worst, threshold))
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
        for document_id in document_ids:
            suggestion = await container.extraction.extract(
                document_id, hosts[0], model or settings.extraction_model
            )
            print(json.dumps(suggestion.model_dump(mode="json"), indent=2, ensure_ascii=False))


async def _ocr_score(settings: Settings, worst: int, threshold: float) -> None:
    async with real_adapters(settings) as adapters:
        rated = [
            (assess_ocr(d.content, d.page_count), d.id, d.title)
            async for d in adapters.paperless.iter_documents()
        ]
    rated.sort(key=lambda r: r[0].score)
    print(f"{len(rated)} Dokumente")
    for bucket in range(10):
        low, high = bucket / 10, (bucket + 1) / 10
        count = sum(low <= q.score < high or (bucket == 9 and q.score == 1) for q, _, _ in rated)
        print(f"{low:.1f}–{high:.1f} {count:5d} {'█' * round(60 * count / max(len(rated), 1))}")
    below = sum(q.score < threshold for q, _, _ in rated)
    print(f"unter der Schwelle {threshold}: {below}")
    print()
    for quality, document_id, title in rated[:worst]:
        print(f"{document_id:6d}  {quality.score:.2f}  {_details(quality)}  {title}")


def _details(quality: OcrQuality) -> str:
    return (
        f"{quality.chars_per_page:6.0f} Z/S  Wörter {quality.word_ratio:.2f}  "
        f"bekannt {quality.dictionary_ratio:.2f}  {', '.join(quality.reasons) or '–'}"
    )


if __name__ == "__main__":
    main()
