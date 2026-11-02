import io
import subprocess
from typing import Any

import pytest
from PIL import Image

from paperless_pilot.adapters.demo import text_pdf
from paperless_pilot.adapters.pages import PageRenderer
from paperless_pilot.domain.errors import ValidationFailedError
from paperless_pilot.domain.models import DocumentFile


def png(width: int, height: int) -> Image.Image:
    return Image.new("RGB", (width, height), "white")


def file_of(*images: Image.Image, fmt: str = "PNG") -> DocumentFile:
    buffer = io.BytesIO()
    images[0].save(buffer, fmt, save_all=len(images) > 1, append_images=list(images[1:]))
    return DocumentFile(content=buffer.getvalue(), media_type=f"image/{fmt.lower()}")


def size_of(page_png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(page_png)).size


@pytest.fixture
def no_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)


@pytest.mark.usefixtures("no_tesseract")
async def test_pdf_pages_are_rendered_and_downscaled() -> None:
    pdf = DocumentFile(content=text_pdf("Rechnung Nr. 4711"), media_type="application/pdf")

    [page] = await PageRenderer(dpi=300, max_side=1000).render(pdf, max_pages=8)

    assert max(size_of(page.png)) == 1000
    assert page.rotated == 0


@pytest.mark.usefixtures("no_tesseract")
async def test_multipage_tiff_respects_page_limit() -> None:
    tiff = file_of(png(100, 200), png(100, 200), png(100, 200), fmt="TIFF")

    pages = await PageRenderer(max_side=2000).render(tiff, max_pages=2)

    assert [size_of(p.png) for p in pages] == [(100, 200), (100, 200)]


@pytest.mark.usefixtures("no_tesseract")
async def test_unreadable_file_is_rejected() -> None:
    with pytest.raises(ValidationFailedError, match="text/plain"):
        await PageRenderer().render(DocumentFile(content=b"x", media_type="text/plain"), 8)


def osd(rotate: int, confidence: float) -> str:
    return f"Page number: 0\nOrientation in degrees: {rotate}\nRotate: {rotate}\n" + (
        f"Orientation confidence: {confidence}\nScript: Latin\n"
    )


@pytest.mark.parametrize(
    ("answers", "rotated"),
    [
        ([osd(180, 5.2), osd(0, 7.7)], 180),  # auf dem Kopf, danach aufrecht
        ([osd(180, 1.9)], 0),  # zu unsicher
        ([osd(180, 3.0), osd(180, 3.0)], 0),  # gedreht immer noch falsch: gefaltetes Blatt
        ([osd(0, 18.0)], 0),
        (["Too few characters"], 0),
    ],
)
async def test_pages_are_turned_upright_only_when_tesseract_agrees(
    monkeypatch: pytest.MonkeyPatch, answers: list[str], rotated: int
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tesseract")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=answers[len(calls) - 1])

    monkeypatch.setattr("subprocess.run", fake_run)

    [page] = await PageRenderer().render(file_of(png(100, 200)), max_pages=1)

    assert page.rotated == rotated
    assert len(calls) == len(answers)
    assert calls[0][-2:] == ["--psm", "0"]
