import base64
import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
from pydantic import BaseModel

from paperless_pilot.adapters.ollama import OllamaHost
from paperless_pilot.domain.errors import (
    InvalidLlmOutputError,
    LlmHostUnavailableError,
    NotFoundError,
    ServiceUnavailableError,
)

BASE_URL = "http://ollama.test:11434"


class Invoice(BaseModel):
    correspondent: str
    amount: float


@pytest.fixture
async def host() -> AsyncIterator[OllamaHost]:
    async with httpx.AsyncClient() as http:
        yield OllamaHost("Mac", BASE_URL + "/", http)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


def chat_reply(content: str) -> dict[str, object]:
    return {
        "model": "gemma4:26b",
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


async def test_exposes_name_and_url(host: OllamaHost) -> None:
    assert host.name == "Mac"
    assert host.base_url == BASE_URL


async def test_probe_reports_version_and_models(host: OllamaHost, api: respx.MockRouter) -> None:
    api.get("/api/version").respond(json={"version": "0.24.0"})
    api.get("/api/tags").respond(
        json={"models": [{"name": "gemma4:26b", "size": 18_000_000_000}, {"name": "tiny"}]}
    )

    probe = await host.probe()

    assert probe.version == "0.24.0"
    assert [(m.name, m.size_bytes) for m in probe.models] == [
        ("gemma4:26b", 18_000_000_000),
        ("tiny", 0),
    ]


async def test_generate_structured_sends_schema_and_parses_reply(
    host: OllamaHost, api: respx.MockRouter
) -> None:
    route = api.post("/api/chat").respond(
        json=chat_reply('{"correspondent": "Musterfirma", "amount": 42.0}')
    )

    result = await host.generate_structured(
        model="gemma4:26b",
        prompt="Lies die Rechnung aus.",
        output_type=Invoice,
        system="Du bist ein Archivar.",
        images=[b"\x89PNG"],
    )

    assert result == Invoice(correspondent="Musterfirma", amount=42.0)
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "gemma4:26b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["format"] == Invoice.model_json_schema()
    assert body["options"] == {"temperature": 0, "num_ctx": 8192}
    assert body["messages"] == [
        {"role": "system", "content": "Du bist ein Archivar."},
        {
            "role": "user",
            "content": "Lies die Rechnung aus.",
            "images": [base64.b64encode(b"\x89PNG").decode()],
        },
    ]


async def test_generate_without_system_and_images(host: OllamaHost, api: respx.MockRouter) -> None:
    route = api.post("/api/chat").respond(json=chat_reply('{"correspondent": "X", "amount": 1}'))

    await host.generate_structured(model="m", prompt="p", output_type=Invoice)

    assert json.loads(route.calls.last.request.content)["messages"] == [
        {"role": "user", "content": "p"}
    ]


@pytest.mark.parametrize(
    "content",
    [
        '{"correspondent": "X"}',  # Pflichtfeld fehlt
        "kein JSON",
        '{"correspondent": "X", "amount": "viel"}',  # falscher Typ
    ],
)
async def test_invalid_reply_raises_with_raw_output(
    host: OllamaHost, api: respx.MockRouter, content: str
) -> None:
    api.post("/api/chat").respond(json=chat_reply(content))

    with pytest.raises(InvalidLlmOutputError) as exc_info:
        await host.generate_structured(model="m", prompt="p", output_type=Invoice)

    assert exc_info.value.raw_output == content
    assert exc_info.value.model == "m"


async def test_unknown_model_raises_not_found(host: OllamaHost, api: respx.MockRouter) -> None:
    api.post("/api/chat").respond(status_code=404, json={"error": "model 'x' not found"})

    with pytest.raises(NotFoundError, match="model 'x' not found"):
        await host.generate_structured(model="x", prompt="p", output_type=Invoice)


async def test_server_error_raises_unavailable(host: OllamaHost, api: respx.MockRouter) -> None:
    api.post("/api/chat").respond(status_code=500, text="out of memory")

    with pytest.raises(ServiceUnavailableError, match="HTTP 500: out of memory"):
        await host.generate_structured(model="m", prompt="p", output_type=Invoice)


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("Connection refused"), httpx.ConnectTimeout("timeout")]
)
async def test_offline_host_raises_unavailable(
    host: OllamaHost, api: respx.MockRouter, error: Exception
) -> None:
    api.get("/api/version").mock(side_effect=error)

    with pytest.raises(ServiceUnavailableError, match=r"Ollama \(Mac\)"):
        await host.probe()


async def test_create_and_close() -> None:
    host = OllamaHost.create("PC", BASE_URL, probe_timeout=1, generate_timeout=1)
    await host.aclose()


async def test_slow_generation_counts_against_job_not_host(
    host: OllamaHost, api: respx.MockRouter
) -> None:
    api.post("/api/chat").mock(side_effect=httpx.ReadTimeout("zu langsam"))

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await host.generate_structured(model="m", prompt="p", output_type=Invoice)

    assert not isinstance(exc_info.value, LlmHostUnavailableError)


async def test_unreachable_host_is_reported_as_host_problem(
    host: OllamaHost, api: respx.MockRouter
) -> None:
    api.post("/api/chat").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(LlmHostUnavailableError):
        await host.generate_structured(model="m", prompt="p", output_type=Invoice)
