from paperless_pilot.domain.jobs import JobKind
from tests.api.conftest import Api
from tests.factories import CORRESPONDENTS, answer, document, taxonomy


async def prepare(api: Api) -> int:
    await api.container.taxonomy_repository.save(taxonomy(), api.clock.now())
    api.paperless.documents[1] = document(1, tag_ids=(40,))
    api.paperless.correspondents.extend(CORRESPONDENTS)
    api.hosts[0].replies.append(answer())
    await api.container.registry.refresh()
    await api.container.jobs.enqueue(1, JobKind.EXTRACT, api.clock.now())
    await api.container.scheduler.run_once("Mac")
    [item] = (await api.client.get("/api/suggestions")).json()
    change = await api.client.post(
        f"/api/suggestions/{item['id']}/accept", json={"values": item["proposed"]}
    )
    return int(change.json()["id"])


async def test_list_and_revert(api: Api) -> None:
    change_id = await prepare(api)

    [change] = (await api.client.get("/api/changes")).json()
    reverted = await api.client.post(f"/api/changes/{change_id}/revert", json={})
    again = await api.client.post(f"/api/changes/{change_id}/revert", json={})

    assert change["before"]["title"].startswith("SwiftScan")
    assert reverted.json()["kind"] == "revert"
    assert again.status_code == 400
    assert len((await api.client.get("/api/changes?document_id=1&limit=5")).json()) == 2
    assert (await api.client.get("/api/changes?limit=0")).status_code == 422


async def test_revert_conflict(api: Api) -> None:
    change_id = await prepare(api)
    api.paperless.edit(1, document_type_id=11)

    response = await api.client.post(f"/api/changes/{change_id}/revert", json={})

    assert response.status_code == 409
    assert response.json()["conflict"] == ["Dokumenttyp"]
