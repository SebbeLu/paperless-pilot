from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from paperless_pilot.domain.availability import EntityState, HostRules, decide, in_window

BERLIN = ZoneInfo("Europe/Berlin")
# 30.10.2026 13:00 UTC = 14:00 Ortszeit (MEZ)
NOW = datetime(2026, 10, 30, 13, 0, tzinfo=UTC)
MAC = "binary_sensor.mac_active"
GAME = "binary_sensor.pc_spiel"


def idle_for(minutes: int, state: str = "off") -> EntityState:
    return EntityState(state=state, last_changed=NOW - timedelta(minutes=minutes))


@pytest.mark.parametrize(
    ("window", "hhmm", "inside"),
    [
        ("20:00-07:00", "21:30", True),
        ("20:00-07:00", "06:59", True),
        ("20:00-07:00", "07:00", False),
        ("20:00-07:00", "14:00", False),
        ("09:00-17:00", "09:00", True),
        ("09:00-17:00", "17:00", False),
    ],
)
def test_window_across_midnight(window: str, hhmm: str, inside: bool) -> None:
    hour, minute = map(int, hhmm.split(":"))
    assert in_window(window, datetime(2026, 1, 1, hour, minute).time()) is inside


def test_no_rules_means_always_allowed() -> None:
    decision = decide(HostRules(), NOW, None, BERLIN)
    assert decision.allowed
    assert decision.reason == "Keine Einschränkung"


def test_paused_wins() -> None:
    decision = decide(HostRules(paused=True, window="00:00-23:59"), NOW, {}, BERLIN)
    assert not decision.allowed
    assert decision.reason == "Pausiert"


def test_window_uses_local_time() -> None:
    assert decide(HostRules(window="13:30-15:00"), NOW, None, BERLIN).allowed
    closed = decide(HostRules(window="20:00-07:00"), NOW, None, BERLIN)
    assert not closed.allowed
    assert closed.reason == "Wartet: Zeitfenster ab 20:00"


def test_idle_long_enough_allows() -> None:
    rules = HostRules(idle_entity=MAC, idle_minutes=10)
    decision = decide(rules, NOW, {MAC: idle_for(12)}, BERLIN)
    assert decision.allowed
    assert decision.reason == "Leerlauf seit 12 min"


@pytest.mark.parametrize(
    ("states", "reason"),
    [
        ({MAC: idle_for(4)}, "Leerlauf erst seit 4 min"),
        ({MAC: idle_for(30, state="on")}, "Rechner wird benutzt"),
        ({}, f"{MAC} unbekannt"),
        (None, "Home Assistant nicht erreichbar"),
    ],
)
def test_idle_not_reached(states: dict[str, EntityState] | None, reason: str) -> None:
    rules = HostRules(idle_entity=MAC, window="20:00-07:00")
    decision = decide(rules, NOW, states, BERLIN)
    assert not decision.allowed
    assert decision.reason == f"Wartet: {reason}, Zeitfenster ab 20:00"


def test_block_beats_window_and_idle() -> None:
    rules = HostRules(window="00:00-23:59", idle_entity=MAC, block_entity=GAME)
    decision = decide(rules, NOW, {GAME: idle_for(1, state="on"), MAC: idle_for(60)}, BERLIN)
    assert not decision.allowed
    assert decision.reason == f"Gesperrt: {GAME} ist on"


def test_block_ignored_when_not_active() -> None:
    rules = HostRules(block_entity=GAME)
    assert decide(rules, NOW, {GAME: idle_for(1, state="off")}, BERLIN).allowed


@pytest.mark.parametrize("window", ["20-7", "25:00-07:00", "abends"])
def test_invalid_window_rejected(window: str) -> None:
    with pytest.raises(ValidationError):
        HostRules(window=window)


def test_blank_values_are_normalized() -> None:
    rules = HostRules(window="  ", idle_entity="  ", block_entity="")
    assert rules.window is None
    assert rules.entities() == set()
    assert HostRules(idle_entity=MAC, block_entity=GAME).entities() == {MAC, GAME}
