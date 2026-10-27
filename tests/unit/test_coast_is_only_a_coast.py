"""The coast field is a coast, and counts have fields of their own.

Audit F-132. "Pre-burn coast duration in hours" was silently reused as the
phasing revolution count, the V-bar and H-bar hop counts and the GEO drift
duration, while those solvers were given no coast at all. Setting a 6 h coast
asked for six revolutions or six hops and applied no coast.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.domain.models import InterceptMethod
from spectre.web.routes import maneuver

_START = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
_SIX_HOURS = 6 * 3600.0

_CASES = [
    (InterceptMethod.PHASING, "phasing_intercept", {"n_revolutions": 2}),
    (InterceptMethod.VBAR_HOP, "vbar_hop_intercept", {"n_hops": 4}),
    (InterceptMethod.HBAR_HOP, "hbar_hop_intercept", {"n_hops": 4}),
    (InterceptMethod.GEO_DRIFT, "geo_drift_intercept", {"drift_time_days": 3.0}),
]


@pytest.mark.parametrize(("method", "solver", "expected"), _CASES)
def test_coast_and_count_reach_the_solver_separately(
    monkeypatch: pytest.MonkeyPatch, method: InterceptMethod, solver: str, expected: dict[str, Any],
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(maneuver, solver, lambda **kw: seen.update(kw))
    args = maneuver._InterceptArgs(
        red_tle="RED", blue_tle="BLUE", start=_START, coast_s=_SIX_HOURS, tof_s=3600.0,
        target_km=0.0, max_dv_m_s=500.0,
        shaping=maneuver._Shaping(revolutions=2, hops=4, drift_days=3.0),
    )
    maneuver._SHAPED_SOLVERS[method](args)
    assert seen["coast_s"] == _SIX_HOURS
    for key, value in expected.items():
        assert seen[key] == value


def test_the_form_offers_the_counts() -> None:
    from pathlib import Path

    page = (Path(maneuver.__file__).parents[1] / "templates" / "operator.html").read_text(encoding="utf-8")
    for name in ("revolutions", "hops", "drift_days"):
        assert f'name="{name}"' in page
