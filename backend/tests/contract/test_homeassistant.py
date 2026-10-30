from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import httpx
import pytest
import respx

from paperless_pilot.adapters.homeassistant import HomeAssistantClient
from paperless_pilot.domain.errors import AuthenticationError, ServiceUnavailableError

BASE = "http://ha.test:8123"


@pytest.fixture
async def client() -> AsyncIterator[HomeAssistantClient]:
    async with httpx.AsyncClient() as http:
        yield HomeAssistantClient(BASE + "/", "ha-token", http)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def state(entity: str, value: str) -> dict[str, object]:
    return {
        "entity_id": entity,
        "state": value,
        "last_changed": "2026-10-30T11:50:00.123456+00:00",
        "attributes": {},
    }


async def test_reads_states_and_skips_unknown(
    client: HomeAssistantClient, api: respx.MockRouter
) -> None:
    route = api.get("/api/states/binary_sensor.mac_active").respond(
        json=state("binary_sensor.mac_active", "off")
    )
    api.get("/api/states/sensor.gibts_nicht").respond(404)

    states = await client.get_states({"binary_sensor.mac_active", "sensor.gibts_nicht"})

    assert list(states) == ["binary_sensor.mac_active"]
    assert states["binary_sensor.mac_active"].state == "off"
    assert states["binary_sensor.mac_active"].last_changed == datetime(
        2026, 10, 30, 11, 50, 0, 123456, tzinfo=UTC
    )
    assert route.calls.last.request.headers["Authorization"] == "Bearer ha-token"


async def test_rejected_token(client: HomeAssistantClient, api: respx.MockRouter) -> None:
    api.get("/api/states/a.b").respond(401)
    with pytest.raises(AuthenticationError):
        await client.get_states({"a.b"})


@pytest.mark.parametrize(
    "outcome", [httpx.Response(500), httpx.ConnectError("weg")], ids=["500", "offline"]
)
async def test_unreachable(
    client: HomeAssistantClient, api: respx.MockRouter, outcome: httpx.Response | Exception
) -> None:
    api.get("/api/states/a.b").mock(side_effect=[outcome])
    with pytest.raises(ServiceUnavailableError):
        await client.get_states({"a.b"})


async def test_create_and_close() -> None:
    client = HomeAssistantClient.create(BASE, "t", timeout=1)
    await client.aclose()
