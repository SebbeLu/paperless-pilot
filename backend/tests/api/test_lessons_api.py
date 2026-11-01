import pytest

from paperless_pilot.domain.jobs import JobKind
from tests.api.conftest import Api
from tests.factories import CORRESPONDENTS, answer, document, taxonomy


@pytest.fixture
async def learned(api: Api) -> Api:
    await api.container.taxonomy_repository.save(taxonomy(), api.clock.now())
    api.paperless.documents[1] = document(1, tag_ids=(40,))
    api.paperless.correspondents.extend(CORRESPONDENTS)
    api.hosts[0].replies.append(answer())
    await api.container.registry.refresh()
    await api.container.jobs.enqueue(1, JobKind.EXTRACT, api.clock.now())
    await api.container.scheduler.run_once("Mac")
    [item] = (await api.client.get("/api/suggestions")).json()
    values = {**item["proposed"], "document_type_id": 11}
    await api.client.post(f"/api/suggestions/{item['id']}/accept", json={"values": values})
    return api


async def test_list_and_forget_lessons(learned: Api) -> None:
    [lesson] = (await learned.client.get("/api/lessons")).json()
    assert lesson["corrected"] == ["document_type"]
    assert lesson["correct"]["document_type"] == "Bescheid"
    assert lesson["proposed"]["document_type"] == "Rechnung"

    response = await learned.client.delete(f"/api/lessons/{lesson['id']}")

    assert response.status_code == 204
    assert (await learned.client.get("/api/lessons")).json() == []
    assert (await learned.client.delete(f"/api/lessons/{lesson['id']}")).status_code == 404
