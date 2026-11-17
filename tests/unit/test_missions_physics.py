"""The figures a mission computes, the exercise inject, and the condition checks (SPC-248).

Each figure is checked against a computation made here with the sgp4 package and a sidereal time written out in this
file, not with the repository code the engine uses, so a figure the engine gets wrong fails here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from sgp4.api import Satrec, jday

from spectre.data.intel import get_intel
from spectre.domain.models import BlueAsset, RedTrack
from spectre.training import exercise_inject, mission_checks, missions, quantities
from spectre.training.quantities import Bound, Context
from spectre.web.planning_state import ScreeningRecord

_SKYNET = ("1 30793U 20001A   26274.50000000  .00000000  00000-0  00000-0 0  9991\n"
           "2 30793   0.0400  95.0000 0002000 270.0000 265.0000  1.00273791 10007")
_SJ21 = ("1 49330U 20001A   26274.50000000  .00000000  00000-0  00000-0 0  9998\n"
         "2 49330   0.3000 102.0000 0002000 270.0000 258.0000  1.00273791 10004")
_CLOCK = datetime(2026, 10, 1, 12, tzinfo=UTC)
_WATCHLIST = missions.watchlist().values()


class _Watchlist:
    """The bundled watchlist, as a training state holds it."""

    def __init__(self) -> None:
        self.hrr_objects = [{"satno": o["satNo"], "name": o["commonName"], "country": o["country"]}
                            for o in _WATCHLIST]
        self.hrr_tle_cache = {o["satNo"]: f"{o['line1']}\n{o['line2']}" for o in _WATCHLIST}


def _r(tle: str, at: datetime) -> np.ndarray:
    line1, line2 = tle.splitlines()
    jd, fr = jday(at.year, at.month, at.day, at.hour, at.minute, at.second)
    err, r, _ = Satrec.twoline2rv(line1, line2).sgp4(jd, fr)
    assert err == 0
    return np.array(r)


def _gmst_deg(at: datetime) -> float:
    jd, fr = jday(at.year, at.month, at.day, at.hour, at.minute, at.second)
    t = (jd + fr - 2451545.0) / 36525.0
    return ((67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * t + 0.093104 * t * t) / 240.0) % 360.0


def _ctx(**tles: str) -> Context:
    roles = {name: Bound(name, tle.splitlines()[0][2:7], name.upper(), "blue", tle, "SYNTHETIC")
             for name, tle in tles.items()}
    return Context(roles, _CLOCK, state=None, now=_CLOCK)


class TestFigures:
    def test_the_longitude_is_the_one_under_the_object_at_the_clock(self) -> None:
        r = _r(_SKYNET, _CLOCK)
        expected = (math.degrees(math.atan2(r[1], r[0])) - _gmst_deg(_CLOCK) + 180) % 360 - 180
        assert quantities.subsat_longitude(_ctx(asset=_SKYNET), "asset") == pytest.approx(expected, abs=1e-4)

    def test_the_range_and_its_trend(self) -> None:
        ctx = _ctx(a=_SJ21, b=_SKYNET)
        now = float(np.linalg.norm(_r(_SJ21, _CLOCK) - _r(_SKYNET, _CLOCK)))
        later = float(np.linalg.norm(_r(_SJ21, _CLOCK + timedelta(hours=24)) - _r(_SKYNET, _CLOCK + timedelta(hours=24))))
        assert quantities.range_km(ctx, "a", "b") == pytest.approx(now, abs=1e-6)
        assert quantities.range_trend(ctx, "a", "b", 24) == ("closing" if later < now else "opening")

    def test_the_closest_approach_is_the_least_range_in_the_window(self) -> None:
        ctx = _ctx(a=_SJ21, b=_SKYNET)
        scan = min(float(np.linalg.norm(_r(_SJ21, _CLOCK + timedelta(seconds=s)) - _r(_SKYNET, _CLOCK + timedelta(
            seconds=s)))) for s in range(0, 24 * 3600, 30))
        assert quantities.closest_approach_km(ctx, "a", "b", 24) <= scan + 1e-6
        assert quantities.closest_approach_km(ctx, "a", "b", 24) == pytest.approx(scan, abs=0.05)
        assert 0.0 <= quantities.closest_approach_hours(ctx, "a", "b", 24) <= 24.0

    def test_regime_options_mark_the_element_card_regime_once(self) -> None:
        options = quantities.regime_options(_ctx(asset=_SKYNET), "asset")
        assert [o["label"] for o in options if o["correct"]] == ["GEO"]

    def test_a_set_at_the_sidereal_mean_motion_still_drifts_by_its_longitude(self) -> None:
        """N8: the mean motion alone said "holds station"; SGP4's longitude a sidereal day on moves a hundredth east."""
        assert 0.005 < quantities.drift_deg_day(_SKYNET, _CLOCK) < 0.02
        assert quantities.drift_word(_SKYNET, _CLOCK) == "east"

    def test_drift_is_the_longitude_change_over_a_sidereal_day(self) -> None:
        """N8: read from SGP4's longitude a sidereal day on, checked here with this file's own sidereal time."""
        later = _CLOCK + timedelta(minutes=quantities.SIDEREAL_DAY_MIN)

        def lon(tle: str, at: datetime) -> float:
            r = _r(tle, at)
            return math.degrees(math.atan2(r[1], r[0])) - _gmst_deg(at)

        for burn in ((0.0, 1.0, 0.0), (0.0, -1.0, 0.0)):
            tle = exercise_inject.inject(_SKYNET, _CLOCK, burn).tle
            moved = (lon(tle, later) - lon(tle, _CLOCK) + 180) % 360 - 180
            assert quantities.drift_deg_day(tle, _CLOCK) == pytest.approx(moved, abs=1e-3)
            assert quantities.drift_word(tle, _CLOCK) == ("east" if moved > 0 else "west")

    def test_the_intelligence_options_quote_the_record_among_its_neighbours(self) -> None:
        """N14: the other options are what the red objects nearest it are assessed as, not an alphabetical run."""
        ctx = _ctx(red=_SJ21)
        ctx.state = _Watchlist()
        threat = quantities.intel_threat_options(ctx, "red")
        level = quantities.intel_level_options(ctx, "red")
        assert [o["label"] for o in threat if o["correct"]] == ["ASAT / Tug"]
        assert [o["label"] for o in level if o["correct"]] == ["CRITICAL"]
        labels = [o["label"] for o in threat]
        assert len(set(labels)) == 4 and labels != sorted(labels)
        neighbours = {get_intel(o["satNo"])["assessed_threat"] for o in _WATCHLIST if get_intel(o["satNo"])}
        assert set(labels) <= neighbours

    def test_an_object_with_no_record_cannot_start_an_intelligence_question(self) -> None:
        with pytest.raises(quantities.QuantityError):
            quantities.intel_level_options(_ctx(asset=_SKYNET), "asset")


class TestTheExerciseInject:
    def test_the_fitted_set_reproduces_the_burned_state(self) -> None:
        done = exercise_inject.inject(_SKYNET, _CLOCK, (0.0, -0.1, 2.0))
        sv_r = _r(_SKYNET, _CLOCK)
        assert exercise_inject.FIT_LIMIT_KM == 0.05
        assert done.residual_km < exercise_inject.FIT_LIMIT_KM   # the rounding of the set's own columns
        assert float(np.linalg.norm(_r(done.tle, _CLOCK) - sv_r)) < 0.05   # the position does not jump at the burn

    def test_the_inspector_inject_fits_within_the_limit(self) -> None:
        """S6: the mission's own inject, on the bundled SY-12 01 set."""
        sy12 = next(o for o in _WATCHLIST if o["satNo"] == "50321")
        done = exercise_inject.inject(f"{sy12['line1']}\n{sy12['line2']}", _CLOCK, (0.0, -0.1, 2.0))
        assert done.residual_km < 0.05

    def test_an_along_track_burn_lengthens_the_period_and_drifts_west(self) -> None:
        done = exercise_inject.inject(_SKYNET, _CLOCK, (0.0, 1.0, 0.0))
        assert quantities.drift_word(done.tle, _CLOCK) == "west"
        assert quantities.drift_word(exercise_inject.inject(_SKYNET, _CLOCK, (0.0, -1.0, 0.0)).tle, _CLOCK) == "east"

    def test_the_fitted_set_passes_the_acceptance_check(self) -> None:
        from spectre.web.elsets import refused

        done = exercise_inject.inject(_SKYNET, _CLOCK, (0.3, 0.0, 0.0))
        assert refused("SKYNET 5A", done.tle, now=_CLOCK + timedelta(hours=1)) is None
        assert exercise_inject.satrec_ok(done.tle)

    def test_the_burn_is_at_the_clock_only(self) -> None:
        assert exercise_inject.inject_time(_CLOCK, "start") == _CLOCK
        assert not exercise_inject.valid_at("start+30m")
        with pytest.raises(exercise_inject.InjectError):
            exercise_inject.inject_time(_CLOCK, "start+30m")


@dataclass
class _State:
    blue_assets: list[Any] = field(default_factory=list)
    red_tracks: list[Any] = field(default_factory=list)
    last_screening: Any = None
    last_threat_assessment: Any = None
    intercept_history: list[Any] = field(default_factory=list)


@dataclass
class _Sweep:
    red_name: str
    sweep_epoch: datetime
    red_tle: str | None = None


@dataclass
class _Run:
    red_name: str
    blue_name: str
    chaser_side: str


class TestScreenedQuantities:
    """B2: a screening question is graded on the operator's own screening, whatever the engine would rank now."""

    _RUN = quantities.Screened("2026-11-17T00:00:00+00:00", 14, (
        ("62188", "TJS-13", "HIGH"), ("64467", "Cosmos 2589", "HIGH"), ("55841", "Luch / Olymp-2", "MINIMAL"),
        ("49330", "SJ-21", "MINIMAL"), ("43874", "TJS-3", "MINIMAL")))

    def test_the_first_ranked_is_the_operators_first(self) -> None:
        options = quantities.screening_top_options(self._RUN, _ROLES)
        assert [o["label"] for o in options if o["correct"]] == ["TJS-13"]
        assert {o["label"] for o in options} == {"TJS-13", "Cosmos 2589", "Luch / Olymp-2", "SJ-21"}

    def test_a_verdict_and_a_rank_are_the_operators(self) -> None:
        verdicts = quantities.screening_verdict_options(self._RUN, _ROLES, actor="tug")
        assert [o["label"] for o in verdicts if o["correct"]] == ["MINIMAL"]
        assert quantities.screening_rank(self._RUN, _ROLES, actor="tug") == 4
        assert quantities.screening_candidates(self._RUN, _ROLES) == 14

    def test_an_actor_it_did_not_rank(self) -> None:
        empty = quantities.Screened("2026-11-17T00:00:00+00:00", 0, ())
        assert [o["label"] for o in quantities.screening_verdict_options(empty, _ROLES, actor="tug")
                if o["correct"]] == [quantities.NOT_RANKED]
        assert quantities.screening_rank(empty, _ROLES, actor="tug") == 0

    def test_a_mission_reads_them_once_its_asset_is_screened(self) -> None:
        mission = next(m for m in missions.load_campaign().missions if m.id == "who_is_near")
        roles = {"asset": _ROLES["asset"]}
        held = missions.resolve_screened(mission, {"candidates": None, "top": None}, roles, {})
        assert held == {"candidates": None, "top": None}
        read = missions.resolve_screened(mission, held, roles, {"30793": self._RUN.as_json()})
        assert read["candidates"] == 14 and [o["label"] for o in read["top"] if o["correct"]] == ["TJS-13"]


_ROLES = {"asset": Bound("asset", "30793", "SKYNET 5A", "blue", _SKYNET, "SYNTHETIC"),
          "tug": Bound("tug", "49330", "SJ-21", "red", _SJ21, "SYNTHETIC")}
_SINCE = _CLOCK


class TestConditionChecks:
    def test_object_loaded_reads_the_lists(self) -> None:
        state = _State(blue_assets=[BlueAsset(name="SKYNET 5A", tle=_SKYNET)])
        assert mission_checks.object_loaded(state, _ROLES, _SINCE, role="asset", side="blue")
        assert not mission_checks.object_loaded(state, _ROLES, _SINCE, role="asset", side="red")
        assert not mission_checks.object_loaded(_State(red_tracks=[RedTrack(name="X", tle=_SKYNET)]), _ROLES, _SINCE,
                                                role="tug", side="red")

    def test_screening_run_needs_that_asset_screened_since_the_start(self) -> None:
        budget = mission_checks.default_budget()
        after = ScreeningRecord("30793", "SKYNET 5A", _SINCE + timedelta(seconds=5), budget_m_s=budget)
        assert mission_checks.screening_run(_State(last_screening=after), _ROLES, _SINCE, asset="asset")
        before = ScreeningRecord("30793", "SKYNET 5A", _SINCE - timedelta(seconds=5), budget_m_s=budget)
        assert not mission_checks.screening_run(_State(last_screening=before), _ROLES, _SINCE, asset="asset")
        other = ScreeningRecord("33055", "SKYNET 5B", _SINCE + timedelta(seconds=5), budget_m_s=budget)
        assert not mission_checks.screening_run(_State(last_screening=other), _ROLES, _SINCE, asset="asset")
        assert not mission_checks.screening_run(_State(), _ROLES, _SINCE, asset="asset")

    def test_screening_run_refuses_another_budget_and_a_pasted_set(self) -> None:
        """N12: the figures are graded at the default budget, and a pasted set merely carrying the number is not it."""
        at = _SINCE + timedelta(seconds=5)
        cheaper = ScreeningRecord("30793", "SKYNET 5A", at, budget_m_s=50.0)
        pasted = ScreeningRecord("30793", "SKYNET 5A", at, budget_m_s=mission_checks.default_budget(), manual=True)
        for record in (cheaper, pasted):
            assert not mission_checks.screening_run(_State(last_screening=record), _ROLES, _SINCE, asset="asset")

    def test_sweep_run_needs_a_sweep_since_the_start_flown_from_the_bound_set(self) -> None:
        state = _State(last_threat_assessment=_Sweep("SJ-21", _SINCE + timedelta(seconds=1), _SJ21))
        assert mission_checks.sweep_run(state, _ROLES, _SINCE, red="tug")
        assert mission_checks.sweep_run(state, _ROLES, _SINCE)
        renamed = _State(last_threat_assessment=_Sweep("Not SJ-21", _SINCE + timedelta(seconds=1), _SJ21))
        assert mission_checks.sweep_run(renamed, _ROLES, _SINCE, red="tug")   # by number and set, not by name
        assert not mission_checks.sweep_run(_State(last_threat_assessment=_Sweep("SJ-21", _SINCE + timedelta(
            seconds=1), _SKYNET)), _ROLES, _SINCE, red="tug")
        assert not mission_checks.sweep_run(_State(last_threat_assessment=_Sweep("SJ-21", _SINCE - timedelta(
            seconds=1), _SJ21)), _ROLES, _SINCE, red="tug")

    def test_intercept_run_needs_the_pair_by_number_and_the_side_that_burns(self) -> None:
        tracks = {"red_tracks": [RedTrack(name="SJ-21", tle=_SJ21)],
                  "blue_assets": [BlueAsset(name="SKYNET 5A", tle=_SKYNET)]}
        state = _State(intercept_history=[_Run("SJ-21", "SKYNET 5A", "red")], **tracks)
        assert mission_checks.intercept_run(state, _ROLES, _SINCE, red="tug", blue="asset", manoeuvring="red")
        assert not mission_checks.intercept_run(state, _ROLES, _SINCE, red="tug", blue="asset", manoeuvring="blue")
        impostor = _State(intercept_history=[_Run("SJ-21", "SKYNET 5A", "red")],
                          red_tracks=[RedTrack(name="SJ-21", tle=_SKYNET)], blue_assets=tracks["blue_assets"])
        assert not mission_checks.intercept_run(impostor, _ROLES, _SINCE, red="tug", blue="asset", manoeuvring="red")

    def test_a_check_spec_is_validated(self) -> None:
        roles = {"tug", "asset"}
        assert mission_checks.check_problems({"type": "intercept_run", "red": "tug", "blue": "asset",
                                              "manoeuvring": "red"}, roles) == []
        assert mission_checks.check_problems({"type": "intercept_run", "red": "tug", "blue": "asset",
                                              "manoeuvring": "green"}, roles)
        assert mission_checks.check_problems({"type": "screening_run", "asset": "nobody"}, roles)
        assert mission_checks.check_problems({"type": "sweep_run"}, roles) == []
        assert mission_checks.check_problems({"type": "sweep_run", "colour": "red"}, roles)
