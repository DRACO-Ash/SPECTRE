"""The domain helpers the hypothesis panel builds from (SPC-114).

The panel starts a hypothesis from the bound red track's state at the burn
time (pre_manoeuvre_state), may enter its delta-V spread (with_spread), and
shows the burn on its own line (burn_line). Its hint names the longest
horizon the cap admits (longest_horizon_h).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro.monte_carlo import elset_state
from spectre.domain.decision import (
    MAX_SAMPLE_HOURS,
    SET_UP_S_PER_SAMPLE,
    AdversaryHypothesis,
    PreManoeuvreState,
    Scenario,
    ScenarioBinding,
    longest_horizon_h,
    needs_a_run,
    pre_manoeuvre_state,
)
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit.test_decision_sampled import _elset, _scenario, _steady

_STATE = (7000.0, 0.0, 0.0, 0.0, 7.546, 0.0)
_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
_AT = PreManoeuvreState(_NOW, _STATE)


class TestTheSpreadMayBeEntered:
    def test_an_entered_spread_replaces_the_archetypes_and_says_so(self) -> None:
        """H8."""
        carried = AdversaryHypothesis.from_archetype("evasive", _AT).with_spread(0.4)
        assert carried.hypothesis.delta_v_magnitude_1sigma_km_s == pytest.approx(0.0004, rel=1e-12)
        assert carried.spread_entered is True
        assert carried.sentence == (
            "Archetype Evasive Manoeuvre: 2.0 m/s; direction (RIC) assumed in-track: an archetype names no "
            "direction; delta-V spread 0.4 m/s (1 sigma) entered; pointing and timing spreads from the Evasive "
            "Manoeuvre archetype."
        )
        assert carried.recorded()["spread_entered"] is True

    def test_without_an_archetype_the_other_spreads_are_the_defaults(self) -> None:
        carried = AdversaryHypothesis.from_entered(5.0, (1.0, 0.0, 0.0), _AT).with_spread(0.5)
        assert carried.sentence.endswith(
            "delta-V spread 0.5 m/s (1 sigma) entered; pointing and timing spreads the defaults, no archetype."
        )

    def test_a_hypothesis_without_an_entered_spread_records_so(self) -> None:
        carried = AdversaryHypothesis.from_archetype("evasive", _AT)
        assert carried.spread_entered is False
        assert carried.recorded()["spread_entered"] is False
        assert carried != carried.with_spread(0.3)

    def test_an_entered_spread_is_checked(self) -> None:
        with pytest.raises(ValueError, match="finite and not negative"):
            AdversaryHypothesis.from_archetype("evasive", _AT).with_spread(-1.0)


class TestAnEnteredDeltaVMayTakeTheArchetypesDirection:
    def test_no_direction_means_in_track_assumed_from_the_archetype(self) -> None:
        carried = AdversaryHypothesis.from_entered(12.5, None, _AT, archetype="orbit_raise")
        assert carried.direction_ric == (0.0, 1.0, 0.0)
        assert carried.direction_basis == "assumed in-track: an archetype names no direction"

    def test_no_direction_and_no_archetype_is_refused(self) -> None:
        with pytest.raises(ValueError, match="needs a direction"):
            AdversaryHypothesis.from_entered(12.5, None, _AT)


class TestTheBurnLine:
    def test_the_burn_line_names_the_time_and_its_offset_from_the_scenario_epoch(self) -> None:
        carried = AdversaryHypothesis.from_archetype("evasive", PreManoeuvreState(_NOW - timedelta(hours=2), _STATE))
        assert carried.burn_line(_NOW) == (
            "Burn at 2026-11-03 07:00 UTC, -2.0 h from the scenario epoch, from the bound red track's state then."
        )

    def test_a_detected_hypothesis_says_where_its_state_came_from(self) -> None:
        detected = AdversaryHypothesis.from_archetype("evasive", _AT)
        detected = AdversaryHypothesis(detected.hypothesis, source=detected.source.__class__("detected"),
                                       archetype_key="evasive")
        assert detected.burn_line(_NOW) == (
            "Burn at 2026-11-03 09:00 UTC, +0.0 h from the scenario epoch, from the detected element set's state then."
        )


class TestThePreManoeuvreState:
    def test_it_is_the_element_set_propagated_to_the_burn(self) -> None:
        at = pre_manoeuvre_state(PLANE_CHANGE.red_tle, EPOCH)
        red = elset_state(PLANE_CHANGE.red_tle, EPOCH)
        assert at is not None and red is not None
        assert at.epoch_utc == EPOCH
        assert np.array_equal(np.asarray(at.state_eci_km), red.state_eci_km)

    def test_an_element_set_that_cannot_be_propagated_gives_none(self) -> None:
        assert pre_manoeuvre_state("not an element set", EPOCH) is None


class TestTheLongestHorizon:
    def test_it_is_what_the_cap_leaves_after_set_up_floored_to_tenths(self) -> None:
        n = 500
        expected = (MAX_SAMPLE_HOURS - n * SET_UP_S_PER_SAMPLE / 3600.0) / (n + 2)
        assert longest_horizon_h(n) == pytest.approx(int(expected * 10) / 10)

    def test_more_rows_share_the_cap(self) -> None:
        assert longest_horizon_h(500, rows=5) < longest_horizon_h(500)

    @pytest.mark.parametrize("rows", [1, 2])
    @pytest.mark.parametrize("n", [100, 500, 1000, 2000])
    def test_the_cap_admits_the_horizon_named_and_refuses_a_tenth_more(self, n: int, rows: int) -> None:
        """Checked against the real cost, not a copy of the formula: a burn at the scenario epoch, as the hint assumes.

        The search stops where an element set passes its limit (SPC-118), so both are given a limit past every
        horizon here, and the horizon is the span searched.
        """
        hours = longest_horizon_h(n, rows=rows)
        assert hours > 0.0
        binding = ScenarioBinding(red=_elset("red", limit=720.0), blue=_elset("blue", limit=720.0))

        def scenario(horizon: float) -> Scenario:
            return _scenario({row: _steady(n) for row in range(rows)}, binding=binding, horizon_hours=horizon)

        assert needs_a_run(scenario(hours)), f"{hours} h at {n} samples over {rows} rows was refused"
        assert not needs_a_run(scenario(round(hours + 0.1, 1))), f"{hours + 0.1} h at {n} samples was admitted"

    def test_none_is_zero_not_negative(self) -> None:
        assert longest_horizon_h(1_000_000) == 0.0
