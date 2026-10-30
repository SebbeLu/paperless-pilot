"""Adapter für die REST-API von Home Assistant: Zustände von Entitäten lesen."""

import asyncio
from datetime import datetime
from typing import Self

import httpx

from paperless_pilot.domain.availability import EntityState
from paperless_pilot.domain.errors import AuthenticationError, ServiceUnavailableError

_SERVICE = "Home Assistant"


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient) -> None:
        self._base = httpx.URL(base_url.rstrip("/") + "/")
        self._http = http
        self._headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def create(cls, base_url: str, token: str, timeout: float) -> Self:
        return cls(base_url, token, httpx.AsyncClient(timeout=timeout))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_states(self, entity_ids: set[str]) -> dict[str, EntityState]:
        """Unbekannte Entitäten fehlen im Ergebnis; ist HA nicht erreichbar, folgt ein Fehler."""
        results = await asyncio.gather(*(self._get(e) for e in sorted(entity_ids)))
        return {e: s for e, s in zip(sorted(entity_ids), results, strict=True) if s is not None}

    async def _get(self, entity_id: str) -> EntityState | None:
        try:
            response = await self._http.get(
                self._base.join(f"api/states/{entity_id}"), headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(_SERVICE, str(exc) or type(exc).__name__) from exc
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            msg = "Home Assistant lehnt den Token ab"
            raise AuthenticationError(msg)
        if response.status_code >= 400:
            raise ServiceUnavailableError(_SERVICE, f"HTTP {response.status_code}")
        data = response.json()
        return EntityState(
            state=data["state"], last_changed=datetime.fromisoformat(data["last_changed"])
        )
