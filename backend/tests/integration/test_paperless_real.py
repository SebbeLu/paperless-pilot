"""Integrationstest gegen ein echtes Paperless-ngx im Container (braucht Docker, läuft in der CI).

Prüft, dass der Adapter mit der echten API-Version zusammenpasst: Dokument hochladen,
lesen, Taxonomie abfragen und Metadaten zurückschreiben.
"""

import asyncio
import secrets
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

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
STARTUP_TIMEOUT_SECONDS = 420


@dataclass(frozen=True)
class PaperlessServer:
    url: str
    token: str


def _report_startup_failure(container: DockerContainer, reason: str) -> None:
    """Macht den Fehler samt Container-Log als GitHub-Annotation sichtbar (auch ohne Anmeldung)."""
    stdout, stderr = container.get_logs()
    lines = (stdout + stderr).decode(errors="replace").splitlines()[-40:]
    message = "%0A".join([reason, *lines])  # %0A = Zeilenumbruch in Workflow-Befehlen
    print(f"::error title=Paperless-Start::{message}")
    pytest.fail(reason)


def _wait_until_ready(url: str, container: DockerContainer) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_seen = "keine Antwort"
    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        if wrapped.status in {"exited", "dead"}:
            _report_startup_failure(container, f"Paperless-Container beendet ({wrapped.status})")
        try:
            # Jede HTTP-Antwort von Django heißt: Migrationen und Admin-Anlage sind durch.
            # Ohne Anmeldung leitet /api/ auf den Login um (302), daher kein fester Statuscode.
            status = httpx.get(f"{url}/api/", timeout=5).status_code
            if status < 500:
                return
            last_seen = f"HTTP {status}"
        except httpx.TransportError as exc:
            last_seen = type(exc).__name__
        time.sleep(3)
    _report_startup_failure(
        container, f"Paperless unter {url} nicht rechtzeitig gestartet (zuletzt: {last_seen})"
    )


@pytest.fixture(scope="module")
def paperless_server() -> Iterator[PaperlessServer]:
    with (
        Network() as network,
        DockerContainer("redis:7-alpine").with_network(network).with_network_aliases("redis"),
        DockerContainer(PAPERLESS_IMAGE)
        .with_network(network)
        .with_env("PAPERLESS_REDIS", "redis://redis:6379")
        # Ab 3.2 startet Paperless nicht ohne eigenen Schlüssel
        .with_env("PAPERLESS_SECRET_KEY", secrets.token_urlsafe(64))
        .with_env("PAPERLESS_ADMIN_USER", ADMIN_USER)
        .with_env("PAPERLESS_ADMIN_PASSWORD", ADMIN_PASSWORD)
        .with_env("PAPERLESS_OCR_LANGUAGE", "deu")
        .with_exposed_ports(8000) as paperless,
    ):
        url = f"http://{paperless.get_container_host_ip()}:{paperless.get_exposed_port(8000)}"
        _wait_until_ready(url, paperless)
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


def _document_id_of(task: dict[str, Any]) -> int:
    """Ab 3.2 steht die ID in result_data bzw. related_document_ids, davor in related_document."""
    if document_id := (task.get("result_data") or {}).get("document_id"):
        return int(document_id)
    if ids := task.get("related_document_ids"):
        return int(ids[0])
    if (document_id := task.get("related_document")) is not None:
        return int(document_id)
    pytest.fail(f"Aufgabe ohne Dokument-ID: {task!r}")


async def _upload_text_document(server: PaperlessServer, text: str) -> int:
    headers = {"Authorization": f"Token {server.token}"}
    async with httpx.AsyncClient(base_url=server.url, headers=headers, timeout=30) as http:
        response = await http.post(
            "/api/documents/post_document/",
            files={"document": ("rechnung.txt", text.encode(), "text/plain")},
        )
        response.raise_for_status()
        body = response.json()
        task_id = body["task_id"] if isinstance(body, dict) else body
        last_seen: Any = None
        for _ in range(120):
            last_seen = (await http.get("/api/tasks/", params={"task_id": task_id})).json()
            # Je nach API-Version eine Liste oder eine Seite mit "results"
            tasks = last_seen["results"] if isinstance(last_seen, dict) else last_seen
            task = tasks[0] if tasks else {}
            status = str(task.get("status", "")).upper()  # ab 3.2 kleingeschrieben
            if status == "SUCCESS":
                return _document_id_of(task)
            if status == "FAILURE":
                pytest.fail(f"Verarbeitung fehlgeschlagen: {task!r}")
            await asyncio.sleep(1)
    pytest.fail(f"Dokument wurde nicht rechtzeitig verarbeitet (zuletzt: {last_seen!r})")


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
