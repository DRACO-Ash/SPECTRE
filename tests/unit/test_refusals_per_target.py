"""A refusal names the target it belongs to, and never contradicts a solution.

Audit F-125. One refusal dict was shared across every target, epoch and
actor, keyed by method with setdefault: the first reason won, it named no
target or epoch, and a method that refused once was listed as having
"produced no solution" beside the table showing its solutions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.models import ThreatTarget
from spectre.web.routes import threat
from tests.unit import test_threat_sweep_template as sweep

_EPOCHS = [("now", datetime(2026, 9, 13, tzinfo=UTC)), ("apogee", datetime(2026, 9, 13, 6, tzinfo=UTC))]


def _lambert(*, blue_tle: str, manoeuvre_start: datetime, **_kwargs: Any) -> Any:
    """Refuses EASY at the first epoch only, and HARD at every epoch."""
    if blue_tle == "HARD" or manoeuvre_start == _EPOCHS[0][1]:
        raise ValueError("degenerate Lambert geometry")
    return SimpleNamespace(total_delta_v=0.01)


def _sweep(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    monkeypatch.setattr(threat, "_SWEEP_METHODS", (("lambert", _lambert, {}),))
    monkeypatch.setattr(threat, "_sol_to_entry", lambda *a, **_k: SimpleNamespace(target=a[1], method=a[4]))
    targets = [ThreatTarget("EASY", "1", "hrr", 1), ThreatTarget("HARD", "2", "hrr", 1)]
    state = SimpleNamespace(hrr_tle_cache={"1": "EASY", "2": "HARD"})
    monkeypatch.setattr(threat, "regime_from_tle", lambda _t: "GEO")
    entries, _errors, refusals = threat._run_target_sweep(
        state, targets, {}, "RED", "GEO", _EPOCHS, 500.0,
    )
    assert {e.target.target_name for e in entries} == {"EASY"}
    return refusals


def test_only_the_target_that_refused_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _sweep(monkeypatch) == [("HARD", "lambert", "at now: degenerate Lambert geometry")]


def test_the_panel_names_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    html = sweep._render(sweep._context(method_refusals=_sweep(monkeypatch)))
    flat = " ".join(html.split())
    assert "1 method(s) produced no solution for a target" in flat
    assert "HARD" in flat
    assert "at now: degenerate Lambert geometry" in flat
