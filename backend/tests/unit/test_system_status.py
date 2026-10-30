from paperless_pilot.application.system_status import SystemStatusService
from paperless_pilot.domain.errors import AuthenticationError, ServiceUnavailableError
from paperless_pilot.domain.models import HostProbe, LlmModel, PaperlessInfo
from tests.fakes import FakeDocumentRepository, FakeLlmHost


async def test_reports_reachable_paperless_and_hosts() -> None:
    paperless = FakeDocumentRepository(
        info=PaperlessInfo(version="3.2.1", api_version=10, documents_total=709, documents_inbox=95)
    )
    mac = FakeLlmHost(
        "Mac",
        probe=HostProbe(
            version="0.24.0",
            models=(LlmModel(name="qwen", size_bytes=1), LlmModel(name="gemma", size_bytes=2)),
        ),
    )

    status = await SystemStatusService(paperless, [mac]).get_status()

    assert status.paperless.reachable
    assert status.paperless.version == "3.2.1"
    assert status.paperless.documents_total == 709
    assert status.paperless.documents_inbox == 95
    assert len(status.hosts) == 1
    assert status.hosts[0].reachable
    assert status.hosts[0].models == ["gemma", "qwen"]
    assert status.hosts[0].url == "http://mac.test:11434"


async def test_failures_become_status_not_exceptions() -> None:
    paperless = FakeDocumentRepository(error=AuthenticationError("Token ungültig"))
    offline = FakeLlmHost("Gaming-PC", error=ServiceUnavailableError("Ollama", "aus"))
    online = FakeLlmHost("Mac")

    status = await SystemStatusService(paperless, [offline, online]).get_status()

    assert not status.paperless.reachable
    assert status.paperless.problem == "auth"
    assert status.paperless.error == "Token ungültig"
    assert [(h.name, h.reachable) for h in status.hosts] == [("Gaming-PC", False), ("Mac", True)]
    assert status.hosts[0].problem == "unreachable"
    assert status.hosts[0].error is not None
    assert "aus" in status.hosts[0].error


async def test_works_without_hosts() -> None:
    status = await SystemStatusService(FakeDocumentRepository(), []).get_status()

    assert status.hosts == []
