"""The orbital-event search runs off the event loop.

Audit F-040: it ran inline in the async handler over the whole scenario
window, so a long scenario stalled every other request.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


def test_the_route_searches_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, client: object, auth_cookie: str,
) -> None:
    from spectre.web.planning_state import get_session_state
    from spectre.web.routes import maneuver

    seen: list[bool] = []

    def fake(*_a: Any, **_k: Any) -> list[Any]:
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return []

    monkeypatch.setattr(maneuver, "find_orbital_events", fake)
    from spectre.domain.models import BlueAsset
    from tests.unit.test_astro import ISS_TLE

    state = get_session_state("testadmin")
    monkeypatch.setattr(state, "blue_assets", [*state.blue_assets, BlueAsset(name="EVT-PROBE", tle=ISS_TLE)])
    client.get(  # type: ignore[attr-defined]
        "/plan/maneuver/orbital-events", params={"blue_sat": "EVT-PROBE"},
        cookies={"spectre_session": auth_cookie},
    )
    assert seen == [False], "find_orbital_events ran on the event loop"
