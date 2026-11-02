from collections.abc import Callable, Sequence

import pytest

from paperless_pilot.application.transcription import TranscriptionService
from paperless_pilot.domain.errors import ServiceUnavailableError
from paperless_pilot.domain.models import FileKind
from paperless_pilot.domain.transcription import TRANSCRIBE_PROMPT, RenderedPage
from tests.clock import FakeClock
from tests.factories import INVOICE_TEXT, document
from tests.fakes import FakeDocumentRepository, FakeLlmHost, FakePageRenderer

GARBAGE = "‚ _‚„___„.„_‚_‚}| ﬁfa?“ ‘ ;$r ;[ =«« " * 10


class SlowHost(FakeLlmHost):
    def __init__(self, clock: FakeClock, replies: list[str]) -> None:
        super().__init__("Mac", replies=replies)
        self._clock = clock

    async def generate_text(
        self,
        *,
        model: str,
        prompt: str,
        images: Sequence[bytes] = (),
        max_tokens: int,
        stop: Callable[[str], bool] | None = None,
    ) -> str:
        self._clock.advance(seconds=12)
        return await super().generate_text(
            model=model, prompt=prompt, images=images, max_tokens=max_tokens, stop=stop
        )


def service(
    paperless: FakeDocumentRepository, renderer: FakePageRenderer, clock: FakeClock
) -> TranscriptionService:
    return TranscriptionService(paperless, renderer, clock, max_pages=2, max_tokens=500)


async def test_transcribes_each_page_from_original_without_writing() -> None:
    clock = FakeClock()
    paperless = FakeDocumentRepository([document(7, content=GARBAGE, page_count=2)])
    renderer = FakePageRenderer([RenderedPage(png=b"p1"), RenderedPage(png=b"p2", rotated=180)])
    host = SlowHost(clock, ["```\nMuster Möbel GmbH\nRechnung Nr. 4711\n```", "Gesamtbetrag"])

    result = await service(paperless, renderer, clock).transcribe(7, host, "gemma4:26b")

    assert result.text == (
        "--- Seite 1 ---\nMuster Möbel GmbH\nRechnung Nr. 4711\n\n--- Seite 2 ---\nGesamtbetrag"
    )
    assert result.pages == 2
    assert result.rotated_pages == [2]
    assert result.skipped_pages == 0
    assert result.quality_before.score < result.quality_after.score
    assert result.warnings == []
    assert result.duration_seconds == 24
    assert (result.model, result.host) == ("gemma4:26b", "Mac")
    assert host.prompts == [TRANSCRIBE_PROMPT] * 2
    assert host.images == [1, 1]
    [(file, max_pages)] = renderer.files
    assert file.content == f"{FileKind.ORIGINAL}:7".encode()
    assert max_pages == 2
    assert paperless.patches == []


async def test_reports_repetitions_and_skipped_pages() -> None:
    paperless = FakeDocumentRepository([document(7, content=GARBAGE, page_count=5)])
    renderer = FakePageRenderer([RenderedPage(png=b"p")] * 5)
    host = FakeLlmHost(replies=[INVOICE_TEXT + "\nSumme 10,00" * 9])

    result = await service(paperless, renderer, FakeClock()).transcribe(7, host, "m", max_pages=1)

    assert [w.code for w in result.warnings] == ["repetition", "skipped_pages"]
    assert result.warnings[1].message == "Nur die ersten 1 von 5 Seiten abgeschrieben"
    assert result.skipped_pages == 4


async def test_host_errors_propagate() -> None:
    paperless = FakeDocumentRepository([document(7)])
    host = FakeLlmHost(error=ServiceUnavailableError("Ollama (Mac)", "aus"))

    with pytest.raises(ServiceUnavailableError, match="aus"):
        await service(paperless, FakePageRenderer(), FakeClock()).transcribe(7, host, "m")
