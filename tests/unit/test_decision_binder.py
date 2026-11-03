"""The binder builds a scenario's binding from the session's held objects (SPC-100).

It reads the red track and blue asset the operator chose, each from its own
side only, and takes each one's own data mode, never the session's or the
target cache's. A name that is no longer held is refused, not dropped, and
red and blue cannot be one object.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain.decision import Freshness, ScenarioBinding
from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.decision_binding import BindOutcome, bind_scenario, bound_elset
from spectre.web.elsets import elset_age
from spectre.web.planning_state import SessionState
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def _state(reds: list[RedTrack] | None = None, blues: list[BlueAsset] | None = None) -> SessionState:
    state = SessionState()
    state.red_tracks = reds or []
    state.blue_assets = blues or []
    return state


def _day_zero(tle: str) -> str:
    """*tle* with its epoch day field set to 000, which the epoch parser refuses."""
    line1, line2 = tle.split("\n")
    return f"{line1[:20]}000{line1[23:]}\n{line2}"


def test_binds_from_the_session() -> None:
    red_tle = _tle(_NOW - timedelta(hours=5), satno=50322)
    blue_tle = _tle(_NOW - timedelta(hours=5), satno=40001)
    state = _state(
        [RedTrack("RX", red_tle, data_mode="SIMULATED")],
        [BlueAsset("BY", blue_tle, data_mode="EXERCISE")],
    )
    state.udl_data_mode = "REAL"
    state.hrr_tle_data_mode = {"50322": "TEST", "40001": "TEST"}
    outcome = bind_scenario(state, "RX", "BY", _NOW)
    assert outcome.problem is None
    assert outcome.binding is not None
    red, blue = outcome.binding.red, outcome.binding.blue
    assert red is not None and blue is not None
    assert (red.side, red.name, red.stk_name, red.satno, red.tle) == ("red", "RX", "RX", 50322, red_tle)
    assert (blue.side, blue.name, blue.stk_name, blue.satno, blue.tle) == ("blue", "BY", "BY", 40001, blue_tle)
    assert red.data_mode == "SIMULATED", "the track's own mode, not the session's or the target cache's"
    assert blue.data_mode == "EXERCISE", "the asset's own mode, not the session's or the target cache's"
    age = elset_age(red_tle, _NOW)
    assert age is not None
    assert red.epoch == age.epoch
    assert red.limit_hours == 72.0
    assert red.freshness is Freshness.CURRENT


@pytest.mark.parametrize(("hours", "leo", "freshness", "limit"), [
    (13 * 24.0, False, Freshness.OUT_OF_DATE, 72.0),
    (30.0, True, Freshness.OUT_OF_DATE, 24.0),
    (10.0, True, Freshness.CURRENT, 24.0),
])
def test_staleness_uses_the_regime_limit(hours: float, leo: bool, freshness: Freshness, limit: float) -> None:
    state = _state([RedTrack("RX", _tle(_NOW - timedelta(hours=hours), leo=leo))])
    outcome = bind_scenario(state, "RX", "", _NOW)
    assert outcome.binding is not None and outcome.binding.red is not None
    assert outcome.binding.red.freshness is freshness
    assert outcome.binding.red.limit_hours == limit


def test_a_future_epoch_binds_at_zero_hours() -> None:
    """elset_age clamps a future epoch to 0 h; the binder must accept it, as it runs outside the try."""
    state = _state([RedTrack("RX", _tle(_NOW + timedelta(hours=2)))])
    outcome = bind_scenario(state, "RX", "", _NOW)
    assert outcome.problem is None
    assert outcome.binding is not None and outcome.binding.red is not None
    assert outcome.binding.red.age_hours == 0.0
    assert outcome.binding.red.age_label == "0.0 h"
    assert outcome.binding.red.freshness is Freshness.CURRENT


@pytest.mark.parametrize("tle", [_day_zero(_tle(_NOW)), "not a tle"])
def test_an_unreadable_epoch_binds_as_unknown(tle: str) -> None:
    elset = bound_elset("red", RedTrack("RX", tle, data_mode="MANUAL"), _NOW)
    assert elset.freshness is Freshness.UNKNOWN
    assert (elset.epoch, elset.age_hours, elset.limit_hours) == (None, None, None)


def test_blank_selections_leave_it_unbound() -> None:
    assert bind_scenario(_state(), "", "", _NOW) == BindOutcome(None, None)


def test_a_name_no_longer_held_is_refused_not_dropped() -> None:
    state = _state([], [BlueAsset("BY", _tle(_NOW, satno=40001))])
    assert bind_scenario(state, "GONE", "", _NOW) == BindOutcome(
        None, "Red track GONE is no longer held in this session. Choose another or leave it unbound.",
    )
    assert bind_scenario(state, "", "LOST", _NOW) == BindOutcome(
        None, "Blue asset LOST is no longer held in this session. Choose another or leave it unbound.",
    )
    refused = bind_scenario(state, "BY", "", _NOW)
    assert refused.binding is None, "a blue asset posted as red_sat is not looked up on the blue side"
    assert refused.problem == "Red track BY is no longer held in this session. Choose another or leave it unbound."


def test_red_and_blue_cannot_be_one_object() -> None:
    state = _state(
        [RedTrack("RX", _tle(_NOW - timedelta(hours=1), satno=50322))],
        [BlueAsset("BY", _tle(_NOW - timedelta(hours=2), satno=50322))],
    )
    assert bind_scenario(state, "RX", "BY", _NOW) == BindOutcome(
        None, "Red and blue are the same object (SATNO 50322). Bind two different objects.",
    )
    same = _state([RedTrack("RX", "not a tle")], [BlueAsset("BY", "  not a tle  ")])
    assert bind_scenario(same, "RX", "BY", _NOW) == BindOutcome(
        None, "Red and blue hold the same element set. Bind two different objects.",
    )


def test_one_side_may_be_bound_alone() -> None:
    state = _state([RedTrack("RX", _tle(_NOW - timedelta(hours=5)), training=True)])
    outcome = bind_scenario(state, "RX", "", _NOW)
    assert outcome.problem is None
    assert outcome.binding is not None and outcome.binding.red is not None
    assert outcome.binding == ScenarioBinding(red=outcome.binding.red)
    assert outcome.binding.red.training is True
    assert outcome.binding.blue is None
