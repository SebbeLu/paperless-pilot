from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from paperless_pilot.adapters.db.repositories import TaxonomyRepository
from paperless_pilot.application.extraction import ExtractionService
from paperless_pilot.domain.errors import NoTextError
from paperless_pilot.domain.extraction import SYSTEM_PROMPT
from tests.clock import FakeClock
from tests.factories import CORRESPONDENTS, answer, document, taxonomy
from tests.fakes import FakeDocumentRepository, FakeLlmHost


@pytest.fixture
async def service(
    engine: AsyncEngine, clock: FakeClock
) -> tuple[ExtractionService, FakeDocumentRepository]:
    repo = TaxonomyRepository(engine)
    await repo.save(taxonomy(), clock.now())
    paperless = FakeDocumentRepository([document(1), document(2, content="  ")])
    paperless.correspondents.extend(CORRESPONDENTS)
    return ExtractionService(paperless, repo, clock, ZoneInfo("Europe/Berlin")), paperless


async def test_extract_builds_suggestion_without_writing(
    service: tuple[ExtractionService, FakeDocumentRepository],
) -> None:
    extraction, paperless = service
    host = FakeLlmHost(replies=[answer()])

    suggestion = await extraction.extract(1, host, "gemma4:26b", job_id=7)

    assert suggestion.document_id == 1
    assert suggestion.job_id == 7
    assert suggestion.host == "Mac"
    assert suggestion.model == "gemma4:26b"
    assert suggestion.proposed.correspondent_id == 91
    assert suggestion.current.correspondent_id == 90
    assert suggestion.document_modified == document(1).modified
    assert host.systems == [SYSTEM_PROMPT]
    assert "- Muster Möbel GmbH" in host.prompts[0]
    assert "o_Online-Shops" not in host.prompts[0]
    assert paperless.patches == []


async def test_short_mode_uses_less_text(
    service: tuple[ExtractionService, FakeDocumentRepository],
) -> None:
    extraction, paperless = service
    paperless.documents[1] = document(1, content="X" * 10_000)
    host = FakeLlmHost(replies=[answer(), answer()])

    await extraction.extract(1, host, "m")
    await extraction.extract(1, host, "m", short=True)

    assert len(host.prompts[1]) < len(host.prompts[0]) - 3000


async def test_document_without_text_is_rejected(
    service: tuple[ExtractionService, FakeDocumentRepository],
) -> None:
    extraction, _ = service
    with pytest.raises(NoTextError):
        await extraction.extract(2, FakeLlmHost(), "m")
