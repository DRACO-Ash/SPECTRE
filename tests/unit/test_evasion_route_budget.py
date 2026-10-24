"""The evasion solver gets the operator's ΔV budget, not the coast time.

Audit F-037. The route derived the evasion fuel budget in km/s from the
panel's coast time in hours, so a 6 h coast meant a 6 km/s budget, and the
operator's max ΔV never reached EVASION, the same class of defect already
fixed for MIN_TIME.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.web.routes import maneuver


def _captured_budget(monkeypatch: pytest.MonkeyPatch, *, coast_s: float, max_dv_m_s: float) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(maneuver, "evasion_intercept", fake)
    maneuver._run_intercept(
        maneuver.InterceptMethod.EVASION, "RED", "BLUE", datetime(2026, 4, 10, tzinfo=UTC),
        coast_s, 3600.0, 10.0, max_dv_m_s,
    )
    return seen


def test_the_budget_follows_the_operators_max_dv(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _captured_budget(monkeypatch, coast_s=0.0, max_dv_m_s=50.0)["fuel_budget_km_s"] == pytest.approx(0.05)
    assert _captured_budget(monkeypatch, coast_s=0.0, max_dv_m_s=500.0)["fuel_budget_km_s"] == pytest.approx(0.5)


def test_the_coast_time_does_not_set_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _captured_budget(monkeypatch, coast_s=6 * 3600.0, max_dv_m_s=50.0)
    b = _captured_budget(monkeypatch, coast_s=0.0, max_dv_m_s=50.0)
    assert a["fuel_budget_km_s"] == b["fuel_budget_km_s"]
