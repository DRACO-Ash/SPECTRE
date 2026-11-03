"""The intercept panel's data mode is checked before anything reaches UDL (SPC-025).

An unknown value went to UDL as ``dataMode``. Now it is refused: the held
element sets are flown and the result's badge says the requested mode was
refused, so the operator never mistakes them for a fresh fetch in that mode.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from spectre.web.routes import maneuver
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO


def _state() -> SimpleNamespace:
    return SimpleNamespace(udl_username="operator", udl_password="udl-secret", udl_tle_source="",
                           hrr_tle_cache={}, hrr_tle_data_mode={}, red_tracks=[], blue_assets=[])


async def test_an_unknown_mode_is_refused_and_never_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    async def fetch(*_a: Any, data_mode: str = "", **_k: Any) -> None:
        sent.append(data_mode)

    monkeypatch.setattr("spectre.web.routes.udl.fetch_tle_for_satno", fetch)
    red, blue, label = await maneuver._resolve_provenance(_RED_GEO, _BLUE_GEO, "live", _state())
    assert sent == []
    assert (red, blue) == (_RED_GEO, _BLUE_GEO)
    assert label.startswith("refused data mode 'LIVE': it must be REAL, SIMULATED, EXERCISE or TEST; flown with the held sets")


async def test_a_known_mode_is_still_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    async def fetch(*_a: Any, data_mode: str = "", **_k: Any) -> tuple[str, str]:
        sent.append(data_mode)
        return _RED_GEO, data_mode

    monkeypatch.setattr("spectre.web.routes.udl.fetch_tle_for_satno", fetch)
    _, _, label = await maneuver._resolve_provenance(_RED_GEO, _BLUE_GEO, "exercise", _state())
    assert sent == ["EXERCISE", "EXERCISE"]
    assert label == "EXERCISE"
