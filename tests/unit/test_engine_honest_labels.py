"""The Intercept Engine says which satellite burns and what its burn achieves (0.47.0).

Audit 3-6 and 2-9: the EVASION summary read "places RED-01 11.0 km from threat" when the burn was BLUE's; COLA
reported the miss it was asked for (max(Approach within, 1 km)) and FORMATION its own 5.0 km target, whatever the
other satellite's position; a summary said "0 m/s" beside a row showing 0.15 m/s. Audit 3-18: J2 drift failed with
"date value out of range" when the gap closed over millennia. Audit 2-14: a training object's SYNTHETIC set read
UNVERIFIED on the Data Mode badge.

The achieved-miss checks are independent of the code under test: the burning satellite is moved by its burn under
numerically integrated two-body motion (scipy), and its closest approach to the other within ten minutes of the
assumed TCA is found by scipy's bounded minimiser. The 0.47.0 review (B2) showed the separation at the old TCA
instant overstates the miss in crossing geometry, so the head-on and 90 degree pairs below are the ones that matter:
the co-orbital pair cannot tell the two figures apart.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import StateVector
from spectre.domain.models import BlueAsset, BurnResult, InterceptMethod, InterceptResult, RedTrack
from spectre.web.planning_state import SessionState
from spectre.web.routes import maneuver

_TCA = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


class _Circular:
    """A TLEOrbit stand-in on a circular orbit with its node on the x axis."""

    def __init__(self, radius_km: float, inc_deg: float, phase_deg: float) -> None:
        self._r = radius_km
        self._v = math.sqrt(MU_EARTH / radius_km)
        self._n = self._v / radius_km
        self._u0 = math.radians(phase_deg)
        i = math.radians(inc_deg)
        self._p = np.array([1.0, 0.0, 0.0])
        self._q = np.array([0.0, math.cos(i), math.sin(i)])

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._u0 + self._n * (epoch - _TCA).total_seconds()
        r = self._r * (math.cos(u) * self._p + math.sin(u) * self._q)
        v = self._v * (-math.sin(u) * self._p + math.cos(u) * self._q)
        return StateVector(epoch=epoch, r=r, v=v)


#: Red 6 km ahead of blue on the same circle at TCA: an avoidance burn asked for 1 km does not make a 1 km miss.
_BLUE = _Circular(7000.0, 0.0, 0.0)
_RED = _Circular(7000.0, 0.0, math.degrees(6.0 / 7000.0))


def _with_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    by_tle = {"RED": _RED, "BLUE": _BLUE}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])


def _integrate(r0: np.ndarray, v0: np.ndarray, seconds: float) -> np.ndarray:
    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        return [*s[3:], *(-MU_EARTH * r / np.linalg.norm(r) ** 3)]
    return solve_ivp(f, (0.0, seconds), np.concatenate([r0, v0]), rtol=1e-11, atol=1e-9).y[:3, -1]


def _closest_after(
    sol: maneuvers.InterceptSolution, burner: _Circular, other: _Circular, half_s: float = 600.0,
) -> float:
    """The least separation within *half_s* of the assumed TCA, the burner flying its burn, found independently."""
    burn = sol.burns[0]
    start = burner.propagate(burn.epoch)
    to_tca = (sol.arrival_epoch - burn.epoch).total_seconds()

    def f(_t: float, s: np.ndarray) -> list[float]:
        return [*s[3:], *(-MU_EARTH * s[:3] / np.linalg.norm(s[:3]) ** 3)]

    flown = solve_ivp(f, (0.0, to_tca + half_s + 1.0), np.concatenate([start.r, start.v + burn.delta_v]),
                      dense_output=True, rtol=1e-12, atol=1e-10).sol

    def separation(t: float) -> float:
        return float(np.linalg.norm(flown(t)[:3] - other.propagate(burn.epoch + timedelta(seconds=t)).r))

    grid = np.arange(max(to_tca - half_s, 0.0), to_tca + half_s + 0.5, 1.0)
    k = int(np.argmin([separation(t) for t in grid]))
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    return float(minimize_scalar(separation, bounds=(lo, hi), method="bounded", options={"xatol": 1e-7}).fun)


#: A threat meeting the defended satellite head-on (retrograde in its plane) and one crossing at 90 degrees, both
#: through the same point at TCA: the separation at the old TCA instant reads about the miss asked for, the closest
#: approach far less (0.47.0 review, B2).
_HEAD_ON = _Circular(7000.0, 180.0, 0.0)
_CROSSING = _Circular(7000.0, 90.0, 0.0)


def _with(monkeypatch: pytest.MonkeyPatch, red: _Circular, blue: _Circular) -> None:
    by_tle = {"RED": red, "BLUE": blue}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])


class TestTheDefensiveMissIsMeasured:
    def test_cola_reports_the_miss_its_burn_achieves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_pair(monkeypatch)
        sol = maneuvers.cola_intercept("RED", "BLUE", _TCA, desired_miss_km=1.0, time_before_tca_s=3600.0)
        # Co-orbital and 6 km apart, the pair never meets near the TCA: the review's S1 says so rather than reading
        # the window's edge as a closest approach. The floor is the least separation in the window searched.
        assert math.isnan(sol.miss_distance_km) and sol.edge_floor_km is not None and sol.search_window_s
        assert sol.edge_floor_km == pytest.approx(_closest_after(sol, _RED, _BLUE, sol.search_window_s), abs=1e-2)
        assert sol.edge_floor_km != pytest.approx(1.0, abs=0.5), "the miss asked for, not the one achieved"

    def test_formation_reports_the_miss_its_burn_achieves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_pair(monkeypatch)
        sol = maneuvers.formation_intercept("RED", "BLUE", _TCA, desired_miss_km=5.0, tof_s=3600.0)
        assert math.isnan(sol.miss_distance_km) and sol.edge_floor_km is not None and sol.search_window_s
        assert sol.edge_floor_km == pytest.approx(_closest_after(sol, _BLUE, _RED, sol.search_window_s), abs=1e-2)
        assert sol.edge_floor_km != pytest.approx(5.0, abs=0.5), "its own 5 km target, not the one achieved"

    @pytest.mark.parametrize(("red", "ceiling_km"), [(_HEAD_ON, 0.3), (_CROSSING, 0.8)], ids=["head-on", "90-deg"])
    def test_cola_in_crossing_geometry_reports_the_closest_approach(
        self, monkeypatch: pytest.MonkeyPatch, red: _Circular, ceiling_km: float,
    ) -> None:
        """Asked for 1 km, the burn leaves 0.24 km head-on and 0.75 km at 90 degrees; 1.03 km was reported."""
        _with(monkeypatch, red, _BLUE)
        sol = maneuvers.cola_intercept("RED", "BLUE", _TCA, desired_miss_km=1.0, time_before_tca_s=3600.0)
        assert sol.miss_distance_km == pytest.approx(_closest_after(sol, red, _BLUE), abs=2e-3)
        assert sol.miss_distance_km < ceiling_km

    @pytest.mark.parametrize("red", [_HEAD_ON, _CROSSING], ids=["head-on", "90-deg"])
    def test_formation_in_crossing_geometry_reports_the_closest_approach(
        self, monkeypatch: pytest.MonkeyPatch, red: _Circular,
    ) -> None:
        _with(monkeypatch, red, _BLUE)
        sol = maneuvers.formation_intercept("RED", "BLUE", _TCA, desired_miss_km=5.0, tof_s=3600.0)
        assert sol.miss_distance_km == pytest.approx(_closest_after(sol, _BLUE, red), abs=2e-3)

    @pytest.mark.parametrize("red", [_HEAD_ON, _CROSSING], ids=["head-on", "90-deg"])
    def test_evasion_in_crossing_geometry_reports_the_closest_approach(
        self, monkeypatch: pytest.MonkeyPatch, red: _Circular,
    ) -> None:
        _with(monkeypatch, red, _BLUE)
        sol = maneuvers.evasion_intercept("RED", "BLUE", _TCA, desired_miss_km=10.0, time_before_tca_s=3600.0,
                                          fuel_budget_km_s=0.5)
        assert sol.miss_distance_km == pytest.approx(_closest_after(sol, _BLUE, red), abs=2e-3)


def _result(method: InterceptMethod, dv: float = 0.15, miss: float = 11.0, side: str = "red") -> InterceptResult:
    burns = [BurnResult(burn_number=1, segment_name="Burn 1", burn_epoch=_TCA - timedelta(hours=1), delta_v_m_s=dv)]
    return InterceptResult(red_name="RED-01", blue_name="BLUE-01", method=method, burns=burns,
                           total_delta_v_m_s=dv, arrival_epoch=_TCA, intercept_range_km=miss, chaser_side=side)


def _summary(result: InterceptResult) -> str:
    return maneuver._summary_text(result, result.total_delta_v_m_s, result.intercept_range_km, "intent", "1 h")


class TestTheSatelliteThatBurnsIsNamed:
    def test_evasion_names_blue_when_blue_burns(self) -> None:
        summary = _summary(_result(InterceptMethod.EVASION))
        assert summary.startswith("Evasion burn by BLUE-01")
        assert "closest approach to RED-01" in summary and "places RED-01" not in summary

    @pytest.mark.parametrize(("method", "burner"), [(InterceptMethod.COLA, "RED-01"),
                                                    (InterceptMethod.FORMATION, "BLUE-01"),
                                                    (InterceptMethod.EVASION, "BLUE-01"),
                                                    (InterceptMethod.LAMBERT, "RED-01"),
                                                    (InterceptMethod.RBAR_HOP, "RED-01")])
    def test_red_manoeuvring(self, method: InterceptMethod, burner: str) -> None:
        result = _result(method)
        rows = {r["label"]: r["value"] for r in maneuver._method_insights(result, 0.15, 11.0)}
        assert rows["Burning satellite"] == burner
        assert burner in _summary(result).split(" from ")[0].split(" of ")[0]

    @pytest.mark.parametrize(("method", "burner"), [(InterceptMethod.COLA, "BLUE-01"),
                                                    (InterceptMethod.FORMATION, "RED-01"),
                                                    (InterceptMethod.EVASION, "RED-01"),
                                                    (InterceptMethod.LAMBERT, "BLUE-01")])
    def test_blue_manoeuvring_swaps_every_name(self, method: InterceptMethod, burner: str) -> None:
        result = _result(method, side="blue")
        assert maneuver._burner_and_other(result)[0] == burner
        assert {r["label"]: r["value"] for r in maneuver._method_insights(result, 0.15, 11.0)}[
            "Burning satellite"] == burner

    def test_a_hop_says_blue_comes_within_red_when_blue_manoeuvres(self) -> None:
        assert "BLUE-01 comes within 11.0 km of RED-01" in _summary(_result(InterceptMethod.RBAR_HOP, side="blue"))

    def test_the_defensive_summaries_say_the_miss_is_at_the_assumed_tca(self) -> None:
        for method in (InterceptMethod.COLA, InterceptMethod.FORMATION, InterceptMethod.EVASION):
            assert "11.0 km" in _summary(_result(method)) and "assumed TCA" in _summary(_result(method))


class TestASmallBurnIsNotZero:
    @pytest.mark.parametrize("method", [InterceptMethod.COLA, InterceptMethod.EVASION, InterceptMethod.FORMATION,
                                        InterceptMethod.LAMBERT, InterceptMethod.HOHMANN, InterceptMethod.MIN_TIME,
                                        InterceptMethod.RBAR_HOP, InterceptMethod.NMC])
    def test_the_summary_rounds_as_the_row_does(self, method: InterceptMethod) -> None:
        summary = _summary(_result(method, dv=0.15))
        assert "0.15 m/s" in summary
        assert "0 m/s" not in summary.replace("0.15 m/s", "")


class TestTheMissColumn:
    def test_an_approach_reads_km(self) -> None:
        assert maneuver._miss_cell(_result(InterceptMethod.LAMBERT, miss=736.44))["text"] == "736.4"
        assert maneuver._miss_cell(_result(InterceptMethod.COLA, miss=0.4))["text"] == "0.40"

    def test_a_score_is_not_a_distance(self) -> None:
        result = _result(InterceptMethod.STABILITY)
        result.score, result.score_kind = 64.0, "Stability score"
        cell = maneuver._miss_cell(result)
        assert cell["text"] == "—" and "not a distance" in cell["title"]

    def test_a_miss_not_computed_says_so(self) -> None:
        cell = maneuver._miss_cell(_result(InterceptMethod.LAMBERT, miss=math.nan))
        assert cell["text"] == "not computed" and cell["sort"] == ""


class _Inclined:
    """A TLEOrbit stand-in on a circular orbit of given inclination and RAAN."""

    def __init__(self, radius_km: float, inc_deg: float, raan_deg: float) -> None:
        self._r, self._v = radius_km, math.sqrt(MU_EARTH / radius_km)
        self._n = self._v / radius_km
        i, o = math.radians(inc_deg), math.radians(raan_deg)
        self._p = np.array([math.cos(o), math.sin(o), 0.0])
        self._q = np.array([-math.sin(o) * math.cos(i), math.cos(o) * math.cos(i), math.sin(i)])

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._n * (epoch - _TCA).total_seconds() + 0.3
        r = self._r * (math.cos(u) * self._p + math.sin(u) * self._q)
        v = self._v * (-math.sin(u) * self._p + math.cos(u) * self._q)
        return StateVector(epoch=epoch, r=r, v=v)


class TestJ2DriftFindsAPlanInsideTheCap:
    """0.47.0 review, B1: only halving the natural convergence was tried, so a gap whose half took longer than ten
    years read NOT REACHABLE though a larger altitude change closes it inside them. LEO at 420 km, 51.6 degrees, the
    chaser 4 km above, 170 degrees of RAAN apart: halving asked for -11.1 km and 9,330 days."""

    _A_TARGET = 6378.137 + 420.0

    def test_the_plan_closes_the_gap_within_the_cap(self) -> None:
        from spectre.astro.tactical import j2_drift_plan, j2_raan_rate

        plan = j2_drift_plan(self._A_TARGET + 4.0, 0.0005, 51.6, self._A_TARGET, 0.0005, 51.6, 170.0,
                             cap_days=maneuvers.J2_DRIFT_CAP_DAYS)
        assert plan.convergence_time_days / 2.0 > maneuvers.J2_DRIFT_CAP_DAYS, "precondition: halving is too slow"
        assert plan.accel_altitude_change_km != 0.0
        assert plan.accel_convergence_days <= maneuvers.J2_DRIFT_CAP_DAYS
        # Checked against the nodal rates themselves: the new altitude's differential rate, over the days given,
        # turns the gap one way round or the other.
        diff = (j2_raan_rate(self._A_TARGET + 4.0 + plan.accel_altitude_change_km, 0.0005, 51.6)
                - j2_raan_rate(self._A_TARGET, 0.0005, 51.6))
        turned = abs(diff) * plan.accel_convergence_days
        assert min(abs(turned - 170.0), abs(turned - 190.0)) < 1e-6

    def test_without_a_cap_the_plan_is_unchanged(self) -> None:
        from spectre.astro.tactical import j2_drift_plan

        plan = j2_drift_plan(self._A_TARGET + 4.0, 0.0005, 51.6, self._A_TARGET, 0.0005, 51.6, 170.0)
        assert plan.accel_convergence_days == pytest.approx(plan.convergence_time_days / 2.0)

    def test_the_intercept_engine_plans_it_rather_than_refusing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        by_tle = {"RED": _Inclined(self._A_TARGET + 4.0, 51.6, 170.0), "BLUE": _Inclined(self._A_TARGET, 51.6, 0.0)}
        monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
        sol = maneuvers.j2_drift_intercept("RED", "BLUE", _TCA)
        assert sol.burns, "an altitude change is planned"
        assert (sol.arrival_epoch - _TCA).days <= maneuvers.J2_DRIFT_CAP_DAYS
        assert sol.total_delta_v * 1000.0 < 20.0, "a Hohmann of some 20 km in LEO, not a large burn"


class TestJ2DriftIsCapped:
    def test_a_gap_that_closes_over_millennia_is_not_reachable_not_a_date_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        by_tle = {"RED": _Inclined(7000.0, 51.6, 120.0), "BLUE": _Inclined(7000.0, 51.6, 0.0)}
        monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
        real = maneuvers.j2_drift_plan

        def glacial(*args: object, **kwargs: object) -> object:
            plan = real(*args, **kwargs)  # type: ignore[arg-type]
            return type(plan)(**{**plan.__dict__, "accel_convergence_days": 5.0e6, "accel_altitude_change_km": 0.0})

        monkeypatch.setattr(maneuvers, "j2_drift_plan", glacial)
        with pytest.raises(maneuvers.NotReachableError, match="not reachable within 10 years"):
            maneuvers.j2_drift_intercept("RED", "BLUE", _TCA)

    def test_the_batch_keeps_the_row_as_not_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unreachable(**_: object) -> maneuvers.InterceptSolution:
            raise maneuvers.NotReachableError("not reachable within 10 years: J2 drift closes the 12.00 deg RAAN gap")

        monkeypatch.setitem(maneuver._COAST_ONLY_SOLVERS, InterceptMethod.J2_DRIFT, unreachable)
        monkeypatch.setattr(maneuver, "_ALL_METHODS_SEQUENCE", [InterceptMethod.J2_DRIFT])
        args = maneuver._InterceptArgs("RED", "BLUE", _TCA, 0.0, 3600.0, 0.0, 100.0)
        (outcome,) = maneuver._run_all_methods(args, "RED-01", "BLUE-01", maneuver._Plan([], 0.0, 0.0, 50.0))
        assert outcome.verdict == "NOT REACHABLE" and outcome.result is None
        assert "not reachable within 10 years" in (outcome.error or "")


class TestTheDataModeOfAHeldObject:
    _TLE = (
        "1 25544U 98067A   26060.00000000  .00016717  00000-0  10270-3 0  9005\n"
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
    )

    def test_a_training_object_reads_synthetic(self) -> None:
        state = SessionState(blue_assets=[BlueAsset(name="TRN-BLUE", tle=self._TLE, training=True,
                                                    data_mode="SYNTHETIC")],
                             red_tracks=[RedTrack(name="TRN-RED", tle=self._TLE, training=True,
                                                  data_mode="SYNTHETIC")])
        assert maneuver._held_mode(state, self._TLE, ("blue", "TRN-BLUE")) == "SYNTHETIC"
        label = asyncio.run(maneuver._resolve_provenance(self._TLE, self._TLE, "", state,
                                                         ("TRN-RED", "TRN-BLUE"))).label
        assert label == "SYNTHETIC"

    def test_a_hand_entered_object_reads_manual(self) -> None:
        state = SessionState(red_tracks=[RedTrack(name="HAND-RED", tle=self._TLE)])
        assert maneuver._held_mode(state, self._TLE, ("red", "HAND-RED")) == "MANUAL"

    def test_a_set_no_object_holds_is_still_unverified(self) -> None:
        assert maneuver._held_mode(SessionState(), self._TLE, ("red", "NOBODY")) == "UNVERIFIED"

    def test_the_selected_object_is_read_not_another_holding_the_same_text(self) -> None:
        """0.47.0 review, S3: a blue copy of the same set, fetched REAL, made a hand-entered red track read REAL."""
        state = SessionState(red_tracks=[RedTrack(name="RED-GEO", tle=self._TLE)],
                             blue_assets=[BlueAsset(name="BLUE-COPY", tle=self._TLE, data_mode="REAL")])
        assert maneuver._held_mode(state, self._TLE, ("red", "RED-GEO")) == "MANUAL"
        assert maneuver._held_mode(state, self._TLE, ("blue", "BLUE-COPY")) == "REAL"
        label = asyncio.run(maneuver._resolve_provenance(self._TLE, self._TLE, "", state,
                                                         ("RED-GEO", "BLUE-COPY"))).label
        assert label == "red MANUAL, blue REAL"

    def test_the_hrr_cache_is_read_when_no_selected_object_holds_the_set(self) -> None:
        state = SessionState(hrr_tle_cache={"25544": self._TLE}, hrr_tle_data_mode={"25544": "EXERCISE"})
        assert maneuver._held_mode(state, self._TLE, ("red", "NOT-HELD")) == "EXERCISE"


class TestBlueManoeuvringReadsAsOurOwnPlan:
    """0.47.0 review, S2: Blue's plans are options, not threats."""

    def test_the_badge_reads_posture_and_the_type_our_approach(self) -> None:
        red = maneuver._compute_intercept_intel(_result(InterceptMethod.LAMBERT, dv=60.0), "GEO")
        blue = maneuver._compute_intercept_intel(_result(InterceptMethod.LAMBERT, dv=60.0, side="blue"), "GEO")
        assert red["level_label"] == red["threat_level"] and red["manoeuvre_type"] == "OFFENSIVE"
        assert blue["level_label"] in {"BENIGN", "ANNOYANCE", "AGGRESSIVE", "BEYOND PLATFORM"}
        assert blue["manoeuvre_type"] == "OWN APPROACH"

    def test_the_adversary_assessments_are_left_out(self) -> None:
        assert len(maneuver.methods_for("red")) == 23
        blue = maneuver.methods_for("blue")
        assert len(blue) == 20 and not set(blue) & maneuver.ADVERSARY_ASSESSMENTS

    def test_own_plans_rank_by_cost_not_threat(self) -> None:
        def item(dv: float, level: str) -> dict[str, object]:
            return {"result": _result(InterceptMethod.LAMBERT, dv=dv, side="blue"), "group": maneuver._RED_APPROACH,
                    "counts": True, "intel": {"threat_level": level}}

        cheap, dear = item(5.0, "LOW"), item(50.0, "CRITICAL")
        assert sorted([dear, cheap], key=maneuver._sort_key) == [cheap, dear]

    def test_a_refusal_names_the_chaser_briefly(self) -> None:
        words = maneuver._solver_words(ValueError("red is 6 km radial of the target"), "blue", "BLUE-GEO")
        assert words == "(chaser: BLUE-GEO) red is 6 km radial of the target"
        assert maneuver._solver_words(ValueError("x"), "red", "BLUE-GEO") == "x"


class TestEveryLabelNamesTheSatelliteThatBurns:
    def test_the_csv_column_is_the_burner(self) -> None:
        assert maneuver.burning_satellite(_result(InterceptMethod.FORMATION)) == "BLUE-01"
        assert maneuver.burning_satellite(_result(InterceptMethod.COLA, side="blue")) == "BLUE-01"

    def test_the_defensive_summary_rounds_as_the_table_does(self) -> None:
        assert "0.24 km" in _summary(_result(InterceptMethod.COLA, miss=0.2431))
        assert maneuver._miss_cell(_result(InterceptMethod.COLA, miss=0.2431))["text"] == "0.24"


class TestGeoDriftSaysWhatEachFigureIs:
    def test_the_gap_is_in_degrees_and_the_flown_approach_in_km(self) -> None:
        result = _result(InterceptMethod.GEO_DRIFT, miss=736.4)
        result.score, result.score_kind = 1.0, "longitude gap (deg)"
        rows = {r["label"]: r["value"] for r in maneuver._method_insights(result, 5.7, 1.0)}
        assert rows["Longitude gap at the start"] == "1.00°"
        assert rows["Closest approach (flown)"] == "736.4 km"
        assert maneuver._miss_cell(result)["text"] == "736.4"

    def test_unflown_it_says_not_computed_not_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        geo = 42164.0
        by_tle = {"RED": _Circular(geo, 0.05, 0.0), "BLUE": _Circular(geo, 0.05, 1.0)}
        monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
        sol = maneuvers.geo_drift_intercept("RED", "BLUE", _TCA, drift_time_days=3.0)
        assert math.isnan(sol.miss_distance_km), "an unflown plan read as a 0 km arrival"
