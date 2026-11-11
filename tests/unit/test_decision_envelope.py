"""The operating envelope, checked at evaluation entry (SPC-200, evaluation F-09, with F-30 and F-31).

docs/decision-engine-envelope.md states the conditions the Decision Engine is fit for. Here each breach the engine
checks is held: a decayed object gives no computed closest approach (F-30, probe P-14's decayed case refused); an
object on SGP4's deep-space branch, SDP4, is flagged, not refused, since the staleness limit and the element-set
error model applied to it are LEO and GEO rules of thumb not validated for it; and expected value with every P at 0
gives no pick and says so (F-31). All-zero weights are refused by the route (tests/integration).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import sgp4

from spectre.astro.elset_approach import ElsetFailure, elset_closest_approach
from spectre.astro.monte_carlo import REENTRY_FLOOR_KM, SeparationWindow
from spectre.astro.propagator import DEEP_SPACE_PERIOD_MIN, SGP4_DECAYED, SGP4Error, TLEOrbit
from spectre.domain.decision import (
    ActionType,
    Basis,
    ProbabilityRule,
    Scenario,
    ScenarioBinding,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from spectre.domain.decision_envelope import DECAYED, DEEP_SPACE, DEEP_SPACE_GEO, envelope_lines
from spectre.domain.models import BlueAsset, RedTrack
from spectre.domain.rule_comparison import compare_rules
from spectre.web.decision_binding import bound_elset
from tests.unit._decision_reference import EPOCH, EPOCH_DAY, GEO_DRIFT_IN, PLANE_CHANGE, _checksum
from tests.unit.test_decision_sampled import _never, _page, _scenario

_VER = Path(sgp4.__file__).parent / "SGP4-VER.TLE"


def _ver(satnum: str) -> str:
    """A verification element set from the SGP4 library's own test file, re-dated to EPOCH, checksums made good."""
    lines = _VER.read_text(encoding="ascii").splitlines()
    k = next(i for i, x in enumerate(lines) if x.startswith(f"1 {satnum}"))
    line1 = lines[k].rstrip().ljust(69)[:18] + EPOCH_DAY + lines[k].rstrip().ljust(69)[32:68]
    line2 = lines[k + 1][:68]
    return f"{line1}{_checksum(line1)}\n{line2}{_checksum(line2)}"


#: SGP4-VER case 28872: SGP4 reports it decayed 52 to 69 minutes after its epoch, and again each perigee after.
_DECAYING = _ver("28872")
#: SGP4-VER case 08195: a Molniya-class orbit, period about 718 minutes, propagated by SDP4.
_MOLNIYA = _ver("08195")
#: Probe P-14's decayed case: the scenario starting 70 minutes after the set's epoch, between two perigee errors.
_LATE = EPOCH + timedelta(minutes=70)


def _binding(red_tle: str, blue_tle: str, now: datetime) -> ScenarioBinding:
    return ScenarioBinding(
        red=bound_elset("red", RedTrack(name="PROBE_RED", tle=red_tle, data_mode="REAL"), now),
        blue=bound_elset("blue", BlueAsset(name="PROBE_BLUE", tle=blue_tle, data_mode="REAL"), now),
    )


def _decayed_scenario(red: str = _DECAYING, blue: str = PLANE_CHANGE.blue_tle) -> Scenario:
    scenario = _scenario(binding=_binding(red, blue, _LATE), horizon_hours=1.0)
    return dataclasses.replace(scenario, epoch_utc=_LATE)


class TestTheSgp4PathHasTheReentryFloor:
    def test_the_object_is_below_the_floor_inside_the_window(self) -> None:
        """The probe's own condition: SGP4 returns states, from 5 to 320 km, so it raises nothing."""
        orbit = TLEOrbit(_DECAYING)
        heights = [orbit.propagate(_LATE + timedelta(minutes=m)).altitude_km for m in range(61)]
        assert min(heights) < REENTRY_FLOOR_KM < max(heights)

    def test_the_search_is_refused_naming_the_side_and_why(self) -> None:
        window = SeparationWindow(start_utc=_LATE, span_s=3600.0)
        assert elset_closest_approach(_DECAYING, PLANE_CHANGE.blue_tle, window) == ElsetFailure("red", "reentered")
        assert elset_closest_approach(PLANE_CHANGE.red_tle, _DECAYING, window) == ElsetFailure("blue", "reentered")

    def test_sgp4s_own_decay_error_is_read_as_decayed(self) -> None:
        """SGP4 raises its error 6 from 52 to 69 minutes after epoch: a search starting at 55 minutes meets it first,
        and was refused as a generic propagation failure with no envelope sentence (review of SPC-200)."""
        early = EPOCH + timedelta(minutes=55)
        with pytest.raises(SGP4Error) as raised:
            TLEOrbit(_DECAYING).propagate(early)
        assert raised.value.code == SGP4_DECAYED
        window = SeparationWindow(start_utc=early, span_s=3600.0)
        assert elset_closest_approach(_DECAYING, PLANE_CHANGE.blue_tle, window) == ElsetFailure("red", "reentered")
        scenario = dataclasses.replace(
            _scenario(binding=_binding(_DECAYING, PLANE_CHANGE.blue_tle, early), horizon_hours=1.0), epoch_utc=early,
        )
        result = evaluate_scenario(scenario, sampler=_never)
        assert result.envelope == (DECAYED.format(side="red", name="PROBE_RED", floor=REENTRY_FLOOR_KM),)

    def test_another_sgp4_error_is_still_a_propagation_failure(self) -> None:
        error = SGP4Error(1, EPOCH)
        assert error.code == 1 and isinstance(error, RuntimeError)
        assert str(error) == f"SGP4 error code 1 at {EPOCH}"

    def test_a_pair_above_the_floor_is_searched_as_before(self) -> None:
        window = SeparationWindow(start_utc=EPOCH, span_s=3600.0)
        assert not isinstance(elset_closest_approach(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, window),
                              ElsetFailure)


class TestTheProbesDecayedCaseIsRefused:
    def test_no_cell_shows_a_computed_closest_approach(self) -> None:
        """P-14 showed "Computed: 643.1 km" in 12 cells, at 5 to 320 km altitude, with no flag."""
        result = evaluate_scenario(_decayed_scenario(), sampler=_never)
        kinds = {c.figure_bases.closest_approach_km.kind for row in result.outcome_matrix for c in row}
        assert Basis.COMPUTED not in kinds
        refusals = {c.ca_refusal for row in result.outcome_matrix for c in row if c.ca_refusal}
        assert any(
            f"the red object is below the {REENTRY_FLOOR_KM:g} km re-entry floor at an instant searched" in r
            for r in refusals
        )

    def test_the_result_says_so_in_a_sentence_and_shows_no_miss(self) -> None:
        result = evaluate_scenario(_decayed_scenario(), sampler=_never)
        assert result.envelope == (DECAYED.format(side="red", name="PROBE_RED", floor=REENTRY_FLOOR_KM),)
        page = _page(result)
        assert result.envelope[0] in page
        assert "643.1" not in page and "(computed)" not in page

    def test_a_decayed_blue_is_named_as_blue(self) -> None:
        result = evaluate_scenario(_decayed_scenario(PLANE_CHANGE.red_tle, _DECAYING), sampler=_never)
        assert result.envelope == (DECAYED.format(side="blue", name="PROBE_BLUE", floor=REENTRY_FLOOR_KM),)


class TestDeepSpaceIsFlaggedNotRefused:
    def test_the_threshold_is_sgp4s_own(self) -> None:
        """225 min is where SGP4 itself switches to SDP4: the flag reads the library's choice, never a guess."""
        assert DEEP_SPACE_PERIOD_MIN == 225.0
        assert TLEOrbit(_MOLNIYA).deep_space and TLEOrbit(GEO_DRIFT_IN.red_tle).deep_space
        assert not TLEOrbit(PLANE_CHANGE.red_tle).deep_space
        assert TLEOrbit(_MOLNIYA).period_minutes > DEEP_SPACE_PERIOD_MIN > TLEOrbit(PLANE_CHANGE.red_tle).period_minutes

    def test_a_molniya_red_is_flagged_with_its_period_and_limit(self) -> None:
        """P-14: a Molniya-class red was evaluated with the 24 h LEO limit and the LEO error model, unflagged."""
        scenario = _scenario(binding=_binding(_MOLNIYA, PLANE_CHANGE.blue_tle, EPOCH), horizon_hours=1.0)
        result = evaluate_scenario(scenario, sampler=_never)
        period = TLEOrbit(_MOLNIYA).period_minutes
        assert result.envelope == (
            DEEP_SPACE.format(side="red", name="PROBE_RED", period=period, limit=24.0),
        )
        assert result.envelope[0] == (
            "The red element set PROBE_RED is propagated with SDP4, SGP4's deep-space branch, which the library "
            f"chooses for a period of about 225 min or more (this set's is about {period:.1f} min): the staleness "
            "limit applied to it, 24 h, and the element-set error model are rules of thumb set for LEO and GEO, not "
            "validated for this orbit, so its age and the uncertainty of its time of closest approach may be "
            "misstated. Its figures stand, flagged."
        )
        assert result.envelope[0] in _page(result)
        computed = {c.figure_bases.closest_approach_km.kind for c in result.outcome_matrix[1]}
        assert computed == {Basis.COMPUTED}, "flagged, not refused: the figure is still computed"

    def test_both_sides_of_a_geo_pair_are_flagged_in_the_geo_sentence(self) -> None:
        """A GEO set is on SDP4 and its limit is the GEO rule of thumb: saying that rule is 'not validated for this
        orbit', as for HEO, contradicted itself (review of SPC-200). It is the GEO rule, tuned rather than sourced."""
        binding = _binding(GEO_DRIFT_IN.red_tle, GEO_DRIFT_IN.blue_tle, EPOCH)
        lines = envelope_lines(_scenario(binding=binding))
        period = TLEOrbit(GEO_DRIFT_IN.red_tle).period_minutes
        assert lines == (
            DEEP_SPACE_GEO.format(side="red", name="PROBE_RED", period=period, limit=72.0),
            DEEP_SPACE_GEO.format(side="blue", name="PROBE_BLUE", period=TLEOrbit(GEO_DRIFT_IN.blue_tle).period_minutes,
                                  limit=72.0),
        )
        assert lines[0] == (
            f"The red element set PROBE_RED is a GEO set, propagated with SDP4, SGP4's deep-space branch (period "
            f"about {period:.1f} min): the staleness limit applied to it, 72 h, and the element-set error model are "
            "the engine's GEO rules of thumb, tuned rather than sourced (SPC-215 will source them), so its age and the "
            "uncertainty of its time of closest approach may be misstated. Its figures stand, flagged."
        )
        assert "not validated for this orbit" not in " ".join(lines)

    def test_the_flag_claims_no_comparison_its_period_cannot_support(self) -> None:
        """SGP4 switches on the un-Kozai'd mean motion; the period shown is the Kozai one, so a set can be on SDP4
        with a period shown as 224.9 min. The sentence says the library chose SDP4, never 'over 225 min'."""
        line2 = PLANE_CHANGE.red_tle.splitlines()[1]
        body = line2[:8] + "  0.0000" + line2[16:26] + "3000000" + line2[33:52] + " 6.40324000" + line2[63:68]
        edge = f"{PLANE_CHANGE.red_tle.splitlines()[0]}\n{body}{_checksum(body)}"
        orbit = TLEOrbit(edge)
        assert orbit.deep_space and orbit.period_minutes < DEEP_SPACE_PERIOD_MIN
        lines = envelope_lines(_scenario(binding=_binding(edge, PLANE_CHANGE.blue_tle, EPOCH)))
        assert lines == (DEEP_SPACE.format(side="red", name="PROBE_RED", period=orbit.period_minutes, limit=24.0),)
        assert f"about {orbit.period_minutes:.1f} min" in lines[0]
        assert "is over" not in lines[0]

    def test_a_leo_pair_and_an_unbound_scenario_carry_no_flag(self) -> None:
        assert envelope_lines(_scenario(binding=_binding(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, EPOCH))) == ()
        assert envelope_lines(_scenario()) == ()
        assert evaluate_scenario(_scenario()).envelope == ()

    def test_a_set_that_does_not_parse_is_left_to_the_checks_that_refuse_it(self) -> None:
        binding = ScenarioBinding(red=bound_elset("red", RedTrack(name="BAD", tle="not a tle"), EPOCH))
        assert envelope_lines(_scenario(binding=binding)) == ()


class TestExpectedValueWithEveryPAt0:
    def _zero(self) -> Scenario:
        """Every row at P 0 under the rule a record 0.28.0 or 0.29.0 wrote, the only way it still arises: under the
        remainder rule the remainder of P carries the whole weight (SPC-203, tests/unit/test_decision_p_remainder.py)."""
        scenario = _scenario()
        return dataclasses.replace(scenario, probability_rule=ProbabilityRule.SHARES, adversary_actions=[
            dataclasses.replace(a, probability=0.0, probability_edited=True) for a in scenario.adversary_actions
        ])

    def test_it_gives_no_pick(self) -> None:
        """F-31: the pick followed row order with no flag."""
        result = evaluate_scenario(self._zero(), SelectorStrategy.EXPECTED_VALUE)
        assert result.robust_best_response is None
        assert find_robust_response(result.scenario, result.outcome_matrix, SelectorStrategy.EXPECTED_VALUE) is None

    def test_nothing_is_starred_and_the_page_says_why(self) -> None:
        result = evaluate_scenario(self._zero(), SelectorStrategy.EXPECTED_VALUE)
        compared = compare_rules(result, SelectorStrategy.MINIMAX)
        assert compared.star_line == (
            "Nothing is starred: expected value, the rule chosen, has no pick, since every row has P 0."
        )
        page = _page(result)
        assert "★" not in page
        assert "No recommendation" in page

    @pytest.mark.parametrize("rule", [SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN])
    def test_the_rules_that_read_no_probability_still_pick(self, rule: SelectorStrategy) -> None:
        """Minimax and minimin read no P, so every row at P 0 picks what the same matrix picks at any P."""
        assert evaluate_scenario(self._zero(), rule).robust_best_response == (
            evaluate_scenario(_scenario(), rule).robust_best_response
        )

    def test_one_row_above_0_is_enough_to_pick(self) -> None:
        scenario = self._zero()
        rows = list(scenario.adversary_actions)
        rows[0] = dataclasses.replace(rows[0], probability=0.1)
        weighted = dataclasses.replace(scenario, adversary_actions=rows)
        picked = evaluate_scenario(weighted, SelectorStrategy.EXPECTED_VALUE)
        # With all the weight on the manoeuvre row, expected value picks what scores least in that row.
        assert rows[0].action_type is ActionType.MANOEUVRE
        row = picked.outcome_matrix[0]
        best = min(range(len(row)), key=lambda j: row[j].composite_score)
        assert picked.robust_best_response == weighted.friendly_responses[best]
