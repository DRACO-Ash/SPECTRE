"""The method panel shows the miss the solver computed, never a literal.

Audit F-130. Hohmann and bi-elliptic printed "0.0 km (coplanar)" and phasing
"0.0 km" whatever the solver's miss distance, while the stat card on the same
panel printed the computed figure: two miss distances on one screen, and a
coplanarity claim nothing had checked. Since F-011 those solvers fly the arc
and report the real miss.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from spectre.domain.models import InterceptMethod, InterceptResult
from spectre.web.routes.maneuver import _method_insights


@pytest.mark.parametrize("method", [InterceptMethod.HOHMANN, InterceptMethod.BIELLIPTIC, InterceptMethod.PHASING])
def test_the_computed_miss_is_shown(method: InterceptMethod) -> None:
    result = InterceptResult(
        red_name="RED", blue_name="BLUE", method=method,
        arrival_epoch=datetime(2026, 9, 13, tzinfo=UTC), intercept_range_km=37.25,
    )
    rows = {r["label"]: r["value"] for r in _method_insights(result, 120.0, 37.25)}
    assert rows["Miss Distance"] == "37.25 km"
    assert not any("coplanar" in str(v) for v in rows.values())
