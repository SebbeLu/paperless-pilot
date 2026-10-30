"""Adapter für einen Ollama-Server (https://github.com/ollama/ollama/blob/main/docs/api.md)."""

import base64
from collections.abc import Sequence
from typing import Any, Self

import httpx
from pydantic import BaseModel, ValidationError

from paperless_pilot.domain.errors import (
    InvalidLlmOutputError,
    NotFoundError,
    ServiceUnavailableError,
)
from paperless_pilot.domain.models import HostProbe, LlmModel

type JsonObject = dict[str, Any]


class OllamaHost:
    def __init__(
        self,
        name: str,
        base_url: str,
        http: httpx.AsyncClient,
        *,
        probe_timeout: float = 5.0,
        generate_timeout: float = 600.0,
    ) -> None:
        self._name = name
        self._base = httpx.URL(base_url.rstrip("/") + "/")
        self._http = http
        self._probe_timeout = probe_timeout
        self._generate_timeout = generate_timeout

    @classmethod
    def create(
        cls, name: str, base_url: str, *, probe_timeout: float, generate_timeout: float
    ) -> Self:
        return cls(
            name,
            base_url,
            httpx.AsyncClient(),
            probe_timeout=probe_timeout,
            generate_timeout=generate_timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def name(self) -> str:
        return self._name

    @property
    def base_url(self) -> str:
        return str(self._base).rstrip("/")

    async def probe(self) -> HostProbe:
        version = await self._request("GET", "api/version", request_timeout=self._probe_timeout)
        tags = await self._request("GET", "api/tags", request_timeout=self._probe_timeout)
        return HostProbe(
            version=version["version"],
            models=tuple(
                LlmModel(name=m["name"], size_bytes=m.get("size", 0))
                for m in tags.get("models", ())
            ),
        )

    async def generate_structured[T: BaseModel](
        self,
        *,
        model: str,
        prompt: str,
        output_type: type[T],
        system: str | None = None,
        images: Sequence[bytes] = (),
    ) -> T:
        user: JsonObject = {"role": "user", "content": prompt}
        if images:
            user["images"] = [base64.b64encode(img).decode("ascii") for img in images]
        messages = [{"role": "system", "content": system}] if system else []
        messages.append(user)

        data = await self._request(
            "POST",
            "api/chat",
            json={
                "model": model,
                "messages": messages,
                "format": output_type.model_json_schema(),
                "stream": False,
                "options": {"temperature": 0},
            },
            request_timeout=self._generate_timeout,
        )
        raw = data.get("message", {}).get("content", "")
        try:
            return output_type.model_validate_json(raw)
        except ValidationError as exc:
            raise InvalidLlmOutputError(model, raw, str(exc)) from exc

    async def _request(
        self, method: str, path: str, *, request_timeout: float, json: JsonObject | None = None
    ) -> JsonObject:
        service = f"Ollama ({self._name})"
        try:
            response = await self._http.request(
                method, self._base.join(path), json=json, timeout=request_timeout
            )
        except httpx.TimeoutException as exc:
            raise ServiceUnavailableError(service, "Zeitüberschreitung") from exc
        except httpx.TransportError as exc:
            raise ServiceUnavailableError(service, str(exc) or type(exc).__name__) from exc

        if response.status_code == 404:
            raise NotFoundError(_error_text(response))
        if response.status_code >= 400:
            raise ServiceUnavailableError(
                service, f"HTTP {response.status_code}: {_error_text(response)}"
            )
        result: JsonObject = response.json()
        return result


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", response.text))[:200]
    except ValueError:
        return response.text[:200]
