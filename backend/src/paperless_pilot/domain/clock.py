"""Uhr als Port – damit Zeitfenster, Leases und Wartezeiten ohne echtes Warten testbar sind."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Aktuelle Zeit, immer mit Zeitzone (UTC)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
