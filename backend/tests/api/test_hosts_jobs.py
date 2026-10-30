import asyncio

from paperless_pilot.api.routes.events import stream
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.models import Tag
from tests.api.conftest import Api
from tests.factories import document, taxonomy


async def configure(api: Api) -> None:
    await api.container.taxonomy_repository.save(taxonomy(), api.clock.now())


async def test_hosts_show_state_and_accept_rules(api: Api) -> None:
    [mac] = (await api.client.get("/api/hosts")).json()
    assert mac["name"] == "Mac"
    assert mac["online"] is True
    assert mac["has_model"] is True
    assert mac["decision"] == {"allowed": True, "reason": "Keine Einschränkung"}

    updated = await api.client.put(
        "/api/hosts/Mac/rules", json={"paused": True, "window": "20:00-07:00"}
    )

    assert updated.json()["decision"]["reason"] == "Pausiert"
    assert updated.json()["rules"]["window"] == "20:00-07:00"
    refreshed = (await api.client.post("/api/hosts/refresh")).json()
    assert refreshed[0]["rules"]["paused"] is True


async def test_invalid_rules_and_unknown_host(api: Api) -> None:
    bad = await api.client.put("/api/hosts/Mac/rules", json={"window": "abends"})
    unknown = await api.client.put("/api/hosts/PC/rules", json={})

    assert bad.status_code == 422
    assert "HH:MM-HH:MM" in bad.text
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Rechner „PC“ ist nicht konfiguriert"


async def test_enqueue_documents_and_list_jobs(api: Api) -> None:
    result = await api.client.post(
        "/api/jobs/enqueue", json={"scope": "documents", "document_ids": [5, 6, 5]}
    )

    assert result.json() == {"enqueued": 2, "already_queued": 1}
    jobs = (await api.client.get("/api/jobs")).json()
    assert [j["document_id"] for j in jobs] == [6, 5]
    assert (await api.client.get("/api/jobs?status=failed")).json() == []


async def test_enqueue_requires_ids_for_documents(api: Api) -> None:
    response = await api.client.post("/api/jobs/enqueue", json={"scope": "documents"})
    assert response.status_code == 422


async def test_enqueue_inbox(api: Api) -> None:
    await configure(api)
    api.paperless.tags.append(Tag(id=1, name="INBOX", document_count=1, is_inbox_tag=True))
    api.paperless.documents[8] = document(8, tag_ids=(1,))

    result = await api.client.post("/api/jobs/enqueue", json={"scope": "inbox"})

    assert result.json() == {"enqueued": 1, "already_queued": 0}
    assert 40 in api.paperless.documents[8].tag_ids


async def test_enqueue_inbox_without_taxonomy_explains(api: Api) -> None:
    response = await api.client.post("/api/jobs/enqueue", json={"scope": "inbox"})
    assert response.status_code == 400
    assert "nicht mit Paperless verknüpft" in response.json()["detail"]


async def test_retry_failed_job(api: Api) -> None:
    job, _ = await api.container.jobs.enqueue(4, "extract", api.clock.now())  # type: ignore[arg-type]
    await api.container.jobs.fail(job.id, api.clock.now(), "kaputt", None)

    retried = await api.client.post(f"/api/jobs/{job.id}/retry")
    again = await api.client.post(f"/api/jobs/{job.id}/retry")

    assert retried.json()["status"] == "queued"
    assert again.status_code == 404


async def test_status_includes_queue(api: Api) -> None:
    await api.container.jobs.enqueue(4, "extract", api.clock.now())  # type: ignore[arg-type]
    body = (await api.client.get("/api/system/status")).json()
    assert body["queue"]["queued"] == 1
    assert body["open_suggestions"] == 0


async def test_event_stream_formats_server_sent_events() -> None:
    bus = EventBus()
    events = stream(bus, keepalive=0.01)

    assert await anext(events) == ": verbunden\n\n"
    assert await anext(events) == ": keepalive\n\n"
    bus.publish("jobs", 3)
    assert await anext(events) == 'event: jobs\ndata: {"topic":"jobs","document_id":3}\n\n'
    await events.aclose()  # type: ignore[attr-defined]
    await asyncio.sleep(0)
    assert bus.subscriber_count == 0
