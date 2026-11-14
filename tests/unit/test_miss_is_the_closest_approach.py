"""Plane change, phasing and the R-bar, V-bar and H-bar hops report how close they bring red to the target.

charming-dirac d2e6513 found every one of these reporting something else as its miss: a plane change 0.0, hard-coded,
while the target stayed 610 km away along-track; phasing the radial gap alone; the R-bar hop the separation it was
asked for; the V-bar and H-bar hops the distance they travel, so an H-bar sequence read 3 km from a target it left
600 km away. Each now reports its closest approach to the target:

● plane change, phasing and the R-bar hop fly their burn two-body and take the closest approach over the transfer
  (a revolution after a plane change, which arrives the moment it fires), found by spectre.astro.closest_approach;
● the V-bar and H-bar hops carried only their first and last burn, so their figure was the closest the hop path came
  in the sequence's own linear model; since the V0.40 review they list every burn and report the flown miss too.

Only the figures change. The sweep decides arrival by method (threat_assessment.arrives_at_target), never by this
figure, so a plane change stays listed, labelled "aligns planes only" and never ranked (owner ruling, 2026-11-12).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.kepler import propagate_two_body
from spectre.astro.propagator import TLEOrbit
from spectre.domain.models import InterceptMethod, InterceptResult
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE

#: The two GEO objects 1 degree apart in one plane: about 736 km along-track, a few km off it.
_START = datetime(2026, 3, 1, tzinfo=UTC)
#: Dense enough that the closest approach it finds is within a few hundred metres of the true one.
_DENSE_STEP_S = 5.0


def _flown_minimum(sol: maneuvers.InterceptSolution, tles: tuple[str, str], span_s: float) -> float:
    """The least separation, sampled every _DENSE_STEP_S, of red after its first burn against the target."""
    red_tle, blue_tle = tles
    burn = sol.burns[0]
    red = TLEOrbit(red_tle).propagate(burn.epoch)
    target = TLEOrbit(blue_tle)
    least = math.inf
    for k in range(int(span_s / _DENSE_STEP_S) + 1):
        t = k * _DENSE_STEP_S
        r, _ = propagate_two_body(red.r, red.v + burn.delta_v, t, MU_EARTH)
        least = min(least, float(np.linalg.norm(r - target.propagate(burn.epoch + timedelta(seconds=t)).r)))
    return least


def _states() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The separation (blue minus red), red's velocity direction and its orbit normal at the start."""
    red, blue = TLEOrbit(_RED_GEO).propagate(_START), TLEOrbit(_BLUE_GEO).propagate(_START)
    h = np.cross(red.r, red.v)
    return np.array(blue.r) - np.array(red.r), red.v / red.v_mag, h / np.linalg.norm(h)


class TestFlownMethods:
    def test_a_plane_change_reports_the_closest_approach_not_zero(self) -> None:
        tles = (PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle)
        sol = maneuvers.plane_change_intercept(*tles, EPOCH)
        period_s = TLEOrbit(PLANE_CHANGE.red_tle).period_minutes * 60.0
        assert sol.miss_distance_km > 1.0, "aligning the planes leaves the along-track gap"
        assert sol.miss_distance_km == pytest.approx(_flown_minimum(sol, tles, period_s), abs=0.5)

    def test_phasing_reports_the_closest_approach_not_the_radial_gap(self) -> None:
        sol = maneuvers.phasing_intercept(_RED_GEO, _BLUE_GEO, _START)
        span_s = (sol.arrival_epoch - sol.departure_epoch).total_seconds()
        flown = _flown_minimum(sol, (_RED_GEO, _BLUE_GEO), span_s)
        assert sol.miss_distance_km == pytest.approx(flown, abs=0.5)

    def test_the_r_bar_hop_reports_the_closest_approach_not_the_separation_asked_for(self) -> None:
        sol = maneuvers.cw_radial_intercept(_RED_GEO, _BLUE_GEO, _START, desired_separation_km=5.0)
        span_s = (sol.arrival_epoch - sol.departure_epoch).total_seconds()
        assert sol.miss_distance_km > 700.0, "a 5 km radial hop leaves the 736 km along-track gap"
        assert sol.miss_distance_km == pytest.approx(_flown_minimum(sol, (_RED_GEO, _BLUE_GEO), span_s), abs=0.5)


class TestTheFlownSearch:
    def test_a_span_of_zero_is_the_separation_at_the_burn(self) -> None:
        red = TLEOrbit(_RED_GEO).propagate(_START)
        at_burn = float(np.linalg.norm(red.r - TLEOrbit(_BLUE_GEO).propagate(_START).r))
        miss = maneuvers._flown_closest_km(red, np.zeros(3), TLEOrbit(_BLUE_GEO), 0.0, MU_EARTH)
        assert miss == pytest.approx(at_burn)

    def test_an_escape_burn_is_searched_over_its_span(self) -> None:
        """No revolution to sample by: the span is searched in one step and refined, and finds the pass it makes."""
        red = TLEOrbit(_RED_GEO).propagate(_START)
        escape = red.v / red.v_mag * 2.0  # km/s: past escape speed at GEO, so it overtakes the target 1 degree ahead
        target = TLEOrbit(_BLUE_GEO)
        dense = min(
            float(np.linalg.norm(propagate_two_body(red.r, red.v + escape, t, MU_EARTH)[0]
                                 - target.propagate(_START + timedelta(seconds=t)).r))
            for t in np.arange(0.0, 600.0, 0.5)
        )
        assert maneuvers._flown_closest_km(red, escape, target, 600.0, MU_EARTH) == pytest.approx(dense, abs=0.5)
        assert dense < 100.0


class TestHopSequences:
    """Since the V0.40 review the hops list every burn of the sequence, and report the flown miss as the rest do."""

    def test_the_v_bar_hop_reports_what_its_burns_achieve(self) -> None:
        separation, along, _ = _states()
        assert abs(float(np.dot(separation, along))) > 700.0
        sol = maneuvers.vbar_hop_intercept(_RED_GEO, _BLUE_GEO, _START)
        span_s = (sol.arrival_epoch - sol.departure_epoch).total_seconds()
        least = flight_dense(sol, span_s)
        assert sol.miss_distance_km == pytest.approx(least, abs=0.5)
        assert sol.miss_distance_km < 30.0, "the hops cover the along-track gap"

    def test_the_h_bar_hop_reports_the_along_track_gap_it_never_covers(self) -> None:
        separation, _, normal = _states()
        on_axis = abs(float(np.dot(separation, normal)))
        sol = maneuvers.hbar_hop_intercept(_RED_GEO, _BLUE_GEO, _START)
        # Three hops of the 1 km floor each, against a cross-track gap of almost nothing.
        assert on_axis < 3.0
        assert sol.miss_distance_km > 700.0, "it read 3 km, the distance travelled"


def flight_dense(sol: maneuvers.InterceptSolution, span_s: float) -> float:
    """The least separation, every _DENSE_STEP_S, of red flying all of *sol*'s burns two-body against the target."""
    red = TLEOrbit(_RED_GEO).propagate(sol.departure_epoch)
    target = TLEOrbit(_BLUE_GEO)
    burns = sorted(sol.burns, key=lambda b: b.epoch)
    least, r, v, at = math.inf, red.r, red.v, sol.departure_epoch
    for k in range(int(span_s / _DENSE_STEP_S) + 1):
        when = sol.departure_epoch + timedelta(seconds=k * _DENSE_STEP_S)
        for burn in [b for b in burns if at <= b.epoch <= when]:
            r, v = propagate_two_body(r, v, (burn.epoch - at).total_seconds(), MU_EARTH)
            v, at = v + burn.delta_v, burn.epoch
        here, _ = propagate_two_body(r, v, (when - at).total_seconds(), MU_EARTH)
        least = min(least, float(np.linalg.norm(here - target.propagate(when).r)))
        burns = [b for b in burns if b.epoch > when]
    return least


class TestTheSweepDoesNotPayForAFigureItNeverReads:
    """Flying each burn costs a few milliseconds a solve; the sweep makes thousands and decides arrival by method."""

    def test_inside_miss_not_read_no_burn_is_flown_and_the_figure_is_nan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def flown(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a burn was flown for a miss nothing reads")

        monkeypatch.setattr(maneuvers, "closest_approach", flown)
        with maneuvers.miss_not_read():
            sol = maneuvers.phasing_intercept(_RED_GEO, _BLUE_GEO, _START)
        assert math.isnan(sol.miss_distance_km)
        with pytest.raises(AssertionError, match="nothing reads"):
            maneuvers.phasing_intercept(_RED_GEO, _BLUE_GEO, _START)

    def test_the_sweep_solves_every_method_inside_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.domain.models import ThreatTarget
        from spectre.web.routes import threat

        monkeypatch.setattr(maneuvers, "closest_approach", lambda *_a, **_k: pytest.fail("the sweep flew a miss"))
        target = ThreatTarget(target_name="BLUE-GEO", target_satno="90002", target_source="manual", hrr_rank=None)
        request = threat._SweepRequest(red_tle=_RED_GEO, target_tle=_BLUE_GEO, target=target, max_dv_m_s=500.0,
                                       regime="GEO")
        entries = threat._sweep_all_methods(request, [("now", _START)])
        assert {"phasing", "plane_change"} <= {e.method for e in entries}
        assert [e.arrives for e in entries if e.method == "plane_change"] == [False], "still kept and labelled"


class TestTheInterceptEngineSaysWhatTheFigureIs:
    @pytest.mark.parametrize("method", [InterceptMethod.RBAR_HOP, InterceptMethod.VBAR_HOP, InterceptMethod.HBAR_HOP])
    def test_the_hops_name_it_a_closest_approach(self, method: InterceptMethod) -> None:
        from spectre.web.routes.maneuver import _method_insights, _summary_text

        result = InterceptResult(red_name="RED", blue_name="BLUE", method=method,
                                 arrival_epoch=_START, intercept_range_km=736.4)
        rows = {r["label"]: r["value"] for r in _method_insights(result, 12.0, 736.4)}
        assert rows["Closest approach"] == "736.4 km"
        assert "Total Advance" not in rows and "Separation" not in rows
        summary = _summary_text(result, 12.0, 736.4, "intercept", "1.0 h")
        assert "comes within 736.4 km of BLUE" in summary
        assert "advances" not in summary and "radially from" not in summary
