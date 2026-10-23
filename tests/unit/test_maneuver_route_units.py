"""Unit conversions between the intercept-engine form and the solvers.

The panel's coast field is in hours (``operator.html``, "Coast (hr)") and is
converted to seconds once, at ``maneuver.py``. Some solvers then reuse it for
a quantity in other units. Each conversion is pinned here, because the defects
it has carried were silent: the solver ran and returned a plausible number.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.web.routes import maneuver

_GEO_RED = (
    "1 40258U 14055A   26100.50000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 40258   0.0500  80.0000 0001000 120.0000 200.0000  1.00270000 12345"
)
_GEO_BLUE = (
    "1 41866U 16071A   26100.50000000  .00000000  00000-0  00000-0 0  9991\n"
    "2 41866   0.0500  80.0000 0001000 120.0000 210.0000  1.00270000 12346"
)


class TestGeoDriftDuration:
    """Audit F-007: the coast time in hours reached the solver as days."""

    def test_a_48_hour_coast_is_a_two_day_drift(self) -> None:
        assert maneuver._geo_drift_days(48 * 3600.0) == pytest.approx(2.0)

    def test_a_coast_of_an_hour_or_less_leaves_the_duration_to_the_solver(self) -> None:
        assert maneuver._geo_drift_days(3600.0) is None

    def test_the_drift_arrives_after_the_requested_days(self) -> None:
        start = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        args = maneuver._InterceptArgs(
            red_tle=_GEO_RED, blue_tle=_GEO_BLUE, start=start,
            coast_s=48 * 3600.0, tof_s=3600.0, target_km=0.0, max_dv_m_s=500.0,
        )
        solution = maneuver._SHAPED_SOLVERS[maneuver.InterceptMethod.GEO_DRIFT](args)
        drift = solution.arrival_epoch - solution.departure_epoch
        assert abs(drift - timedelta(days=2)) < timedelta(minutes=1), f"drifted for {drift}"
