from typing import Any

import pytest
import uvicorn

from paperless_pilot import __main__ as entrypoint


def test_main_starts_uvicorn_with_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PILOT_PAPERLESS_URL", "http://paperless:8000")
    monkeypatch.setenv("PILOT_PAPERLESS_TOKEN", "t")
    monkeypatch.setenv("PILOT_PORT", "9000")
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    entrypoint.main()

    ((args, kwargs),) = calls
    assert args == ("paperless_pilot.api.app:create_app",)
    assert kwargs["factory"] is True
    assert kwargs["port"] == 9000
