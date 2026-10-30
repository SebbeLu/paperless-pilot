"""Rechner-Verwaltung: Erreichbarkeit, Modelle, Freigaben und was gerade läuft."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from paperless_pilot.adapters.db.repositories import HostSettingsRepository
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.availability import Decision, EntityState, HostRules, decide
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.errors import AuthenticationError, NotFoundError, PilotError
from paperless_pilot.domain.ports import AvailabilitySource, LlmHost

logger = logging.getLogger(__name__)

type Problem = Literal["unreachable", "auth"]


class HostState(BaseModel):
    name: str
    url: str
    model: str
    online: bool = False
    version: str | None = None
    models: list[str] = []
    has_model: bool = False
    problem: Problem | None = None
    error: str | None = None
    checked_at: datetime | None = None
    rules: HostRules = HostRules()
    decision: Decision = Decision(allowed=False, reason="Noch nicht geprüft")
    entity_states: dict[str, EntityState] = {}
    ha_available: bool | None = None
    busy_document_id: int | None = None
    processed: int = 0
    last_duration_ms: int | None = None

    @property
    def can_work(self) -> bool:
        return self.online and self.has_model and self.decision.allowed


class HostRegistry:
    def __init__(
        self,
        hosts: Sequence[LlmHost],
        default_model: str,
        model_overrides: dict[str, str],
        settings: HostSettingsRepository,
        availability: AvailabilitySource | None,
        clock: Clock,
        timezone: ZoneInfo,
        events: EventBus,
    ) -> None:
        self._hosts = {h.name: h for h in hosts}
        self._settings = settings
        self._availability = availability
        self._clock = clock
        self._tz = timezone
        self._events = events
        self._states = {
            h.name: HostState(
                name=h.name, url=h.base_url, model=model_overrides.get(h.name, default_model)
            )
            for h in hosts
        }
        self._lock = asyncio.Lock()

    def host(self, name: str) -> LlmHost:
        return self._hosts[name]

    def names(self) -> list[str]:
        return list(self._hosts)

    def state(self, name: str) -> HostState:
        try:
            return self._states[name]
        except KeyError:
            msg = f"Rechner „{name}“ ist nicht konfiguriert"
            raise NotFoundError(msg) from None

    def states(self) -> list[HostState]:
        return list(self._states.values())

    async def refresh(self) -> list[HostState]:
        """Fragt alle Rechner und Home Assistant ab und entscheidet über die Freigaben."""
        async with self._lock:
            rules = await self._settings.get_all()
            probes = await asyncio.gather(*(self._probe(n) for n in self._hosts))
            entities = set().union(*(r.entities() for r in rules.values()))
            ha_states = await self._entity_states(entities)
            now = self._clock.now()
            for name, probe in zip(self._hosts, probes, strict=True):
                host_rules = rules.get(name, HostRules())
                previous = self._states[name]
                updated = previous.model_copy(
                    update={
                        **probe,
                        "checked_at": now,
                        "rules": host_rules,
                        "decision": decide(host_rules, now, ha_states, self._tz),
                        "entity_states": {
                            e: s for e, s in (ha_states or {}).items() if e in host_rules.entities()
                        },
                        "ha_available": None
                        if not host_rules.entities()
                        else ha_states is not None,
                    }
                )
                updated = updated.model_copy(update={"has_model": updated.model in updated.models})
                self._states[name] = updated
                if _visible(previous) != _visible(updated):
                    logger.info("Rechner %s: %s", name, updated.decision.reason)
            self._events.publish("hosts")
            return self.states()

    async def update_rules(self, name: str, rules: HostRules) -> HostState:
        self.state(name)  # wirft, wenn unbekannt
        await self._settings.save(name, rules, self._clock.now())
        await self.refresh()
        return self.state(name)

    def mark_offline(self, name: str, error: str) -> None:
        self._states[name] = self._states[name].model_copy(
            update={"online": False, "problem": "unreachable", "error": error}
        )
        self._events.publish("hosts")

    def set_busy(self, name: str, document_id: int | None, duration_ms: int | None = None) -> None:
        state = self._states[name]
        update: dict[str, object] = {"busy_document_id": document_id}
        if document_id is None and duration_ms is not None:
            update |= {"processed": state.processed + 1, "last_duration_ms": duration_ms}
        self._states[name] = state.model_copy(update=update)
        self._events.publish("hosts")

    async def _probe(self, name: str) -> dict[str, object]:
        try:
            probe = await self._hosts[name].probe()
        except PilotError as exc:
            problem: Problem = "auth" if isinstance(exc, AuthenticationError) else "unreachable"
            return {"online": False, "problem": problem, "error": str(exc)}
        return {
            "online": True,
            "version": probe.version,
            "models": sorted(m.name for m in probe.models),
            "problem": None,
            "error": None,
        }

    async def _entity_states(self, entities: set[str]) -> dict[str, EntityState] | None:
        if not entities:
            return {}
        if self._availability is None:
            return None
        try:
            return await self._availability.get_states(entities)
        except PilotError as exc:
            logger.warning("Home Assistant nicht erreichbar: %s", exc)
            return None


def _visible(state: HostState) -> tuple[bool, bool, str]:
    return state.online, state.decision.allowed, state.decision.reason
