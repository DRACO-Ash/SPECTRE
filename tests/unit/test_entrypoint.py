"""Tests for the console entry point.

The entry point is the single place that decides what host and port the
container listens on, so a regression here is a failed deploy rather than a
failed test. It is exercised with uvicorn stubbed out.
"""

from __future__ import annotations

from typing import Any

import pytest

from spectre.web import _entrypoint


@pytest.fixture()
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Run main() with uvicorn stubbed, returning the arguments it was given."""
    recorded: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        recorded["app"] = app
        recorded.update(kwargs)

    monkeypatch.setattr(_entrypoint.uvicorn, "run", fake_run)
    return recorded


class TestEntrypoint:
    def test_serves_the_application_factory(
        self, captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PORT", raising=False)
        _entrypoint.main()
        assert captured["app"] == "spectre.web.app:app"

    def test_binds_all_interfaces_for_the_platform_router(
        self, captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loopback would make the readiness probe unreachable from the pod IP."""
        monkeypatch.delenv("PORT", raising=False)
        _entrypoint.main()
        assert captured["host"] == "0.0.0.0"  # noqa: S104

    def test_defaults_to_port_8080(
        self, captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PORT", raising=False)
        _entrypoint.main()
        assert captured["port"] == 8080

    def test_honours_an_injected_port(
        self, captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PORT", "9090")
        _entrypoint.main()
        assert captured["port"] == 9090

    def test_reload_is_never_enabled(
        self, captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auto-reload in a container would watch files that never change."""
        monkeypatch.delenv("PORT", raising=False)
        _entrypoint.main()
        assert captured["reload"] is False
