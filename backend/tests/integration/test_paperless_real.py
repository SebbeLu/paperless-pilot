"""Integrationstest gegen ein echtes Paperless-ngx im Container (braucht Docker, läuft in der CI).

Prüft, dass der Adapter mit der echten API-Version zusammenpasst: Dokument hochladen,
lesen, Taxonomie abfragen und Metadaten zurückschreiben.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from paperless_pilot.adapters.paperless import PaperlessClient
from paperless_pilot.domain.models import DocumentPatch

pytestmark = pytest.mark.integration

PAPERLESS_IMAGE = "ghcr.io/paperless-ngx/paperless-ngx:3.2.1"
ADMIN_USER = "pilot"
ADMIN_PASSWORD = "pilot-integration"  # noqa: S105 - nur im Wegwerf-Container
STARTUP_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class PaperlessServer:
    url: str
    token: str


def _wait_until_ready(url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/api/", timeout=5).status_code in (200, 401, 403):
                return
        except httpx.TransportError:
            pass
        time.sleep(3)
    pytest.fail(f"Paperless unter {url} ist nicht rechtzeitig gestartet")


@pytest.fixture(scope="module")
def paperless_server() -> Iterator[PaperlessServer]:
    with (
        Network() as network,
        DockerContainer("redis:7-alpine").with_network(network).with_network_aliases("redis"),
        DockerContainer(PAPERLESS_IMAGE)
        .with_network(network)
        .with_env("PAPERLESS_REDIS", "redis://redis:6379")
        .with_env("PAPERLESS_ADMIN_USER", ADMIN_USER)
        .with_env("PAPERLESS_ADMIN_PASSWORD", ADMIN_PASSWORD)
        .with_env("PAPERLESS_OCR_LANGUAGE", "deu")
        .with_exposed_ports(8000) as paperless,
    ):
        url = f"http://{paperless.get_container_host_ip()}:{paperless.get_exposed_port(8000)}"
        _wait_until_ready(url)
        response = httpx.post(
            f"{url}/api/token/",
            data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
            timeout=30,
        )
        response.raise_for_status()
        yield PaperlessServer(url=url, token=response.json()["token"])


@pytest.fixture
async def client(paperless_server: PaperlessServer) -> AsyncIterator[PaperlessClient]:
    client = PaperlessClient.create(paperless_server.url, paperless_server.token, timeout=30)
    yield client
    await client.aclose()


async def _upload_text_document(server: PaperlessServer, text: str) -> int:
    headers = {"Authorization": f"Token {server.token}"}
    async with httpx.AsyncClient(base_url=server.url, headers=headers, timeout=30) as http:
        response = await http.post(
            "/api/documents/post_document/",
            files={"document": ("rechnung.txt", text.encode(), "text/plain")},
        )
        response.raise_for_status()
        task_id = response.json()
        for _ in range(120):
            tasks = (await http.get("/api/tasks/", params={"task_id": task_id})).json()
            if tasks and tasks[0]["status"] == "SUCCESS":
                return int(tasks[0]["related_document"])
            if tasks and tasks[0]["status"] == "FAILURE":
                pytest.fail(f"Verarbeitung fehlgeschlagen: {tasks[0].get('result')}")
            await asyncio.sleep(1)
    pytest.fail("Dokument wurde nicht rechtzeitig verarbeitet")


async def test_roundtrip_against_real_paperless(
    client: PaperlessClient, paperless_server: PaperlessServer
) -> None:
    doc_id = await _upload_text_document(
        paperless_server, "Musterfirma GmbH\nRechnung Nr. 4711\nBetrag: 42,00 EUR\n"
    )

    info = await client.server_info()
    assert info.version.startswith("3.")
    assert info.documents_total >= 1

    doc = await client.get_document(doc_id)
    assert "Rechnung Nr. 4711" in doc.content
    assert doc.id in [d.id async for d in client.iter_documents()]

    tags = await client.list_tags()
    assert all(t.name for t in tags)

    updated = await client.update_document(doc_id, DocumentPatch(title="Rechnung 4711"))
    assert updated.title == "Rechnung 4711"
    assert (await client.get_document(doc_id)).title == "Rechnung 4711"
