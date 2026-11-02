"""Adapter für einen Ollama-Server (https://github.com/ollama/ollama/blob/main/docs/api.md)."""

import base64
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, Self

import httpx
from pydantic import BaseModel, ValidationError

from paperless_pilot.domain.errors import (
    InvalidLlmOutputError,
    LlmHostUnavailableError,
    NotFoundError,
    ServiceUnavailableError,
)
from paperless_pilot.domain.models import HostProbe, LlmModel

type JsonObject = dict[str, Any]

# Bild und Abschrift brauchen mehr Kontext als das Auslesen von Text
TEXT_CONTEXT_LENGTH = 16384
_STOP_CHECK_CHARS = 200  # so oft prüft ``stop``, ob abgebrochen werden soll


class OllamaHost:
    def __init__(
        self,
        name: str,
        base_url: str,
        http: httpx.AsyncClient,
        *,
        probe_timeout: float = 5.0,
        generate_timeout: float = 600.0,
        context_length: int = 8192,
    ) -> None:
        self._name = name
        self._base = httpx.URL(base_url.rstrip("/") + "/")
        self._http = http
        self._probe_timeout = probe_timeout
        self._generate_timeout = generate_timeout
        self._context_length = context_length

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

    async def model_capabilities(self, model: str) -> frozenset[str]:
        data = await self._request(
            "POST", "api/show", json={"model": model}, request_timeout=self._probe_timeout
        )
        return frozenset(data.get("capabilities") or ())

    async def generate_text(
        self,
        *,
        model: str,
        prompt: str,
        images: Sequence[bytes] = (),
        max_tokens: int,
        stop: Callable[[str], bool] | None = None,
    ) -> str:
        """Freitext, etwa eine Abschrift.

        Die Antwort kommt gestreamt: Meldet ``stop`` für den bisherigen Text True, etwa weil
        sich das Modell wiederholt, wird abgebrochen. ``max_tokens`` ist die harte Grenze.
        """
        body = self._chat_body(
            model, prompt, images, {"num_predict": max_tokens, "num_ctx": TEXT_CONTEXT_LENGTH}
        )
        body["stream"] = True
        text = ""
        async with (
            self._guard(),
            self._http.stream(
                "POST", self._base.join("api/chat"), json=body, timeout=self._generate_timeout
            ) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                self._raise_for(response)
            checked = 0
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                text += chunk.get("message", {}).get("content", "")
                if stop is not None and len(text) - checked >= _STOP_CHECK_CHARS:
                    checked = len(text)
                    if stop(text):
                        break
                if chunk.get("done"):
                    break
        return text

    async def generate_structured[T: BaseModel](
        self,
        *,
        model: str,
        prompt: str,
        output_type: type[T],
        system: str | None = None,
        images: Sequence[bytes] = (),
    ) -> T:
        data = await self._chat(
            model, prompt, images, {}, system=system, output_format=output_type.model_json_schema()
        )
        raw = data.get("message", {}).get("content", "")
        try:
            return output_type.model_validate_json(raw)
        except ValidationError as exc:
            raise InvalidLlmOutputError(model, raw, str(exc)) from exc

    async def _chat(
        self,
        model: str,
        prompt: str,
        images: Sequence[bytes],
        options: JsonObject,
        *,
        system: str | None = None,
        output_format: JsonObject | None = None,
    ) -> JsonObject:
        body = self._chat_body(model, prompt, images, options, system=system)
        if output_format is not None:
            body["format"] = output_format
        return await self._request(
            "POST", "api/chat", json=body, request_timeout=self._generate_timeout
        )

    def _chat_body(
        self,
        model: str,
        prompt: str,
        images: Sequence[bytes],
        options: JsonObject,
        *,
        system: str | None = None,
    ) -> JsonObject:
        user: JsonObject = {"role": "user", "content": prompt}
        if images:
            user["images"] = [base64.b64encode(img).decode("ascii") for img in images]
        messages = [{"role": "system", "content": system}] if system else []
        messages.append(user)
        return {
            "model": model,
            "messages": messages,
            "stream": False,
            # Denkmodus aus: bei strukturierter Ausgabe und Abschriften kein Qualitätsgewinn,
            # aber um ein Vielfaches langsamer. Modelle ohne Denkmodus ignorieren den Schalter.
            "think": False,
            "options": {"temperature": 0, "num_ctx": self._context_length, **options},
        }

    async def _request(
        self, method: str, path: str, *, request_timeout: float, json: JsonObject | None = None
    ) -> JsonObject:
        async with self._guard():
            response = await self._http.request(
                method, self._base.join(path), json=json, timeout=request_timeout
            )
        self._raise_for(response)
        result: JsonObject = response.json()
        return result

    @asynccontextmanager
    async def _guard(self) -> AsyncIterator[None]:
        """Übersetzt Verbindungsfehler in die Fehler des Kerns."""
        service = f"Ollama ({self._name})"
        try:
            yield
        except httpx.ConnectTimeout as exc:
            raise LlmHostUnavailableError(service, "keine Verbindung (Zeitüberschreitung)") from exc
        except httpx.TimeoutException as exc:
            # Antwort dauert zu lange – zählt als Fehlversuch des Auftrags, nicht des Rechners
            raise ServiceUnavailableError(service, "Zeitüberschreitung") from exc
        except httpx.TransportError as exc:
            raise LlmHostUnavailableError(service, str(exc) or type(exc).__name__) from exc

    def _raise_for(self, response: httpx.Response) -> None:
        if response.status_code == 404:
            raise NotFoundError(_error_text(response))
        if response.status_code >= 400:
            raise ServiceUnavailableError(
                f"Ollama ({self._name})", f"HTTP {response.status_code}: {_error_text(response)}"
            )


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", response.text))[:200]
    except ValueError:
        return response.text[:200]
