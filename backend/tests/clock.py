from datetime import UTC, datetime, timedelta


class FakeClock:
    """Steuerbare Uhr für Tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)
