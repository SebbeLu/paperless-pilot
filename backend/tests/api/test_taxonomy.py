from paperless_pilot.domain.models import Correspondent, DocumentType, Tag
from tests.api.conftest import Api

TAXONOMY = {
    "document_types": [{"name": "Rechnung", "description": "Rechnungen, Quittungen"}],
    "persons": [{"name": "Alex", "aliases": ["A. Muster"]}],
    "areas": [{"name": "Steuer"}],
}


async def test_fresh_installation_has_default_status_tags(api: Api) -> None:
    body = (await api.client.get("/api/taxonomy")).json()

    assert body["configured"] is False
    assert [i["name"] for i in body["sync"]] == ["ai:todo", "ai:prüfen", "ai:fertig", "ai:fehler"]
    assert {i["status"] for i in body["sync"]} == {"missing"}


async def test_save_validates_and_plans_sync(api: Api) -> None:
    api.paperless.tags.append(Tag(id=7, name="steuer", document_count=141, is_inbox_tag=False))

    response = await api.client.put("/api/taxonomy", json=TAXONOMY)

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    sync = {i["name"]: i for i in body["sync"]}
    assert sync["Rechnung"]["status"] == "missing"
    assert sync["Steuer"] == {
        "group": "areas",
        "name": "Steuer",
        "status": "link_by_name",
        "paperless_id": 7,
        "paperless_name": "steuer",
    }


async def test_invalid_taxonomy_is_rejected(api: Api) -> None:
    response = await api.client.put(
        "/api/taxonomy", json={"areas": [{"name": "Auto"}, {"name": "auto"}]}
    )

    assert response.status_code == 422
    assert "doppelt" in response.text


async def test_sync_links_existing_and_creates_missing(api: Api) -> None:
    api.paperless.tags.append(Tag(id=7, name="Steuer", document_count=1, is_inbox_tag=False))
    await api.client.put("/api/taxonomy", json=TAXONOMY)

    body = (await api.client.post("/api/taxonomy/sync")).json()

    assert {i["status"] for i in body["sync"]} == {"linked"}
    taxonomy = body["taxonomy"]
    assert taxonomy["areas"][0]["paperless_id"] == 7
    assert taxonomy["document_types"][0]["paperless_id"] in {
        t.id for t in api.paperless.document_types
    }
    assert {t.name for t in api.paperless.tags} >= {"Alex", "ai:todo", "ai:prüfen"}
    # zweiter Abgleich legt nichts doppelt an
    tags_before = len(api.paperless.tags)
    await api.client.post("/api/taxonomy/sync")
    assert len(api.paperless.tags) == tags_before


async def test_deleted_object_is_reported_stale_and_recreated(api: Api) -> None:
    await api.client.put("/api/taxonomy", json=TAXONOMY)
    await api.client.post("/api/taxonomy/sync")
    api.paperless.document_types.clear()

    body = (await api.client.get("/api/taxonomy")).json()
    assert {i["name"]: i["status"] for i in body["sync"]}["Rechnung"] == "stale"

    synced = (await api.client.post("/api/taxonomy/sync")).json()
    assert {i["status"] for i in synced["sync"]} == {"linked"}


async def test_export_is_a_download(api: Api) -> None:
    await api.client.put("/api/taxonomy", json=TAXONOMY)

    response = await api.client.get("/api/taxonomy/export")

    assert "attachment" in response.headers["content-disposition"]
    assert response.json()["persons"][0]["aliases"] == ["A. Muster"]


async def test_lookups_mark_excluded_correspondents(api: Api) -> None:
    api.paperless.correspondents.extend(
        [
            Correspondent(id=1, name="o_Ärzte", document_count=1),
            Correspondent(id=2, name="Muster AG", document_count=1),
        ]
    )
    api.paperless.document_types.append(DocumentType(id=3, name="Rechnung", document_count=0))

    body = (await api.client.get("/api/paperless/lookups")).json()

    assert body["correspondents"] == [
        {"id": 2, "name": "Muster AG", "excluded": False},
        {"id": 1, "name": "o_Ärzte", "excluded": True},
    ]
    assert body["document_types"] == [{"id": 3, "name": "Rechnung"}]
