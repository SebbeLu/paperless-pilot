"""Wann darf ein Ollama-Rechner arbeiten? Reine Logik, ohne Netzwerk."""

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator

_WINDOW = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


class EntityState(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: str
    last_changed: datetime


class HostRules(BaseModel):
    """Freigaben eines Rechners. Ohne Zeitfenster und ohne Leerlauf-Entität: immer frei."""

    paused: bool = False
    window: str | None = None  # z. B. "20:00-07:00", Ortszeit
    idle_entity: str | None = None  # z. B. binary_sensor.macbook_active
    idle_state: str = "off"  # Zustand, der „nicht benutzt“ bedeutet
    idle_minutes: int = 10
    block_entity: str | None = None  # z. B. binary_sensor.gaming_pc_spiel
    block_state: str = "on"  # Zustand, der „belegt“ bedeutet

    @field_validator("window")
    @classmethod
    def _valid_window(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parse_window(value)
        return value.strip()

    @field_validator("idle_entity", "block_entity")
    @classmethod
    def _empty_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    def entities(self) -> set[str]:
        return {e for e in (self.idle_entity, self.block_entity) if e}


def parse_window(value: str) -> tuple[time, time]:
    match = _WINDOW.match(value.strip())
    if not match:
        msg = f"Zeitfenster „{value}“ hat nicht das Format HH:MM-HH:MM"
        raise ValueError(msg)
    h1, m1, h2, m2 = (int(g) for g in match.groups())
    try:
        return time(h1, m1), time(h2, m2)
    except ValueError as exc:
        msg = f"Zeitfenster „{value}“ enthält eine ungültige Uhrzeit"
        raise ValueError(msg) from exc


def in_window(window: str, local_now: time) -> bool:
    start, end = parse_window(window)
    if start <= end:
        return start <= local_now < end
    return local_now >= start or local_now < end  # über Mitternacht


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: str


def decide(
    rules: HostRules,
    now: datetime,
    states: dict[str, EntityState] | None,
    tz: ZoneInfo,
) -> Decision:
    """Entscheidet über die Freigabe; ``states`` ist ``None``, wenn Home Assistant schweigt."""
    if rules.paused:
        return Decision(allowed=False, reason="Pausiert")
    if blocked := _block_reason(rules, states):
        return Decision(allowed=False, reason=blocked)
    if rules.window and in_window(rules.window, now.astimezone(tz).time().replace(tzinfo=None)):
        _, end = parse_window(rules.window)
        return Decision(allowed=True, reason=f"Im Zeitfenster bis {end:%H:%M}")
    if rules.idle_entity:
        return _idle_decision(rules, rules.idle_entity, now, states)
    if rules.window:
        return _closed(rules, "")
    return Decision(allowed=True, reason="Keine Einschränkung")


def _block_reason(rules: HostRules, states: dict[str, EntityState] | None) -> str | None:
    if not rules.block_entity:
        return None
    block = (states or {}).get(rules.block_entity)
    if block is not None and block.state == rules.block_state:
        return f"Gesperrt: {rules.block_entity} ist {block.state}"
    return None


def _idle_decision(
    rules: HostRules, entity: str, now: datetime, states: dict[str, EntityState] | None
) -> Decision:
    if states is None:
        return _closed(rules, "Home Assistant nicht erreichbar")
    idle = states.get(entity)
    if idle is None:
        return _closed(rules, f"{entity} unbekannt")
    if idle.state != rules.idle_state:
        return _closed(rules, "Rechner wird benutzt")
    idle_for = now - idle.last_changed
    if idle_for >= timedelta(minutes=rules.idle_minutes):
        return Decision(allowed=True, reason=f"Leerlauf seit {_minutes(idle_for)} min")
    return _closed(rules, f"Leerlauf erst seit {_minutes(idle_for)} min")


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _closed(rules: HostRules, why: str) -> Decision:
    parts = [why] if why else []
    if rules.window:
        start, _ = parse_window(rules.window)
        parts.append(f"Zeitfenster ab {start:%H:%M}")
    return Decision(allowed=False, reason="Wartet: " + ", ".join(parts))
