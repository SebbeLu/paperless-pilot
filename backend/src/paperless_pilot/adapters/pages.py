"""Seiten eines Dokuments als Bilder fürs Vision-Modell: rendern, verkleinern, aufrichten."""

import asyncio
import io
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.models import DocumentFile
from paperless_pilot.domain.transcription import RenderedPage

log = logging.getLogger(__name__)

# Tesseract nennt die Drehung samt Sicherheit; darunter ist die Lage nicht verlässlich erkannt
_MIN_ORIENTATION_CONFIDENCE = 2.0
_OSD = re.compile(r"Rotate: (\d+)\s.*?Orientation confidence: ([\d.]+)", re.DOTALL)


class PageRenderer:
    def __init__(self, *, dpi: int = 200, max_side: int = 2000) -> None:
        self._dpi = dpi
        self._max_side = max_side
        self._tesseract = shutil.which("tesseract")
        if self._tesseract is None:
            log.info("tesseract fehlt – Seiten werden nicht automatisch aufgerichtet")

    async def render(self, file: DocumentFile, max_pages: int) -> list[RenderedPage]:
        return await asyncio.to_thread(self._render, file, max_pages)

    def _render(self, file: DocumentFile, max_pages: int) -> list[RenderedPage]:
        return [self._prepare(image) for image in self._images(file)[:max_pages]]

    def _images(self, file: DocumentFile) -> list[Image.Image]:
        if file.media_type == "application/pdf":
            pdf = pdfium.PdfDocument(file.content)
            try:
                return [page.render(scale=self._dpi / 72).to_pil() for page in pdf]
            finally:
                pdf.close()
        try:
            image = Image.open(io.BytesIO(file.content))
            frames: list[Image.Image] = []
            for index in range(getattr(image, "n_frames", 1)):  # mehrseitige TIFFs
                image.seek(index)
                frames.append(image.convert("RGB"))
        except OSError as exc:
            msg = f"Dateiformat {file.media_type} lässt sich nicht als Bild lesen"
            raise ValidationFailedError(msg) from exc
        return frames

    def _prepare(self, image: Image.Image) -> RenderedPage:
        image = image.convert("RGB")
        image.thumbnail((self._max_side, self._max_side))
        rotation = self._rotation(image)
        if rotation:
            image = image.rotate(-rotation, expand=True)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)
        return RenderedPage(png=buffer.getvalue(), rotated=rotation)

    def _rotation(self, image: Image.Image) -> int:
        """Drehung im Uhrzeigersinn, die die Seite aufrichtet – 0, wenn unsicher.

        Tesseract irrt bei Ausweisen und gefalteten Blättern; deshalb gilt eine Drehung nur,
        wenn die gedrehte Seite danach auch für Tesseract aufrecht steht.
        """
        first = self._detect(image)
        if first is None or first == 0:
            return 0
        check = self._detect(image.rotate(-first, expand=True))
        return first if check == 0 else 0

    def _detect(self, image: Image.Image) -> int | None:
        if self._tesseract is None:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.png"
            image.convert("L").save(path)
            result = subprocess.run(  # noqa: S603 – fester Befehl, Pfad aus shutil.which
                [self._tesseract, str(path), "-", "--psm", "0"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        match = _OSD.search(result.stdout)
        if match is None or float(match.group(2)) < _MIN_ORIENTATION_CONFIDENCE:
            return None
        return int(match.group(1))
