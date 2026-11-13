"""A bound row whose action does not move red has its closest approach computed by SGP4 (SPC-120).

In a scenario bound to a red track and a blue asset, each row gets exactly one
closest approach. A row whose action carries a hypothesis is sampled, or
refused and kept a lookup (SPC-112). A row whose action does not move red
(no action, a sensor retask, a posture change) is computed: both bound orbits
propagated by SGP4 from their element sets with no burn, searched through the
shared helper, over the part of the horizon both element sets are within
their limits. A manoeuvre with no hypothesis names no burn, so it stays a
lookup and says why. The computed figure belongs to the pair: one search per
scenario, shared by every computed row and every response, since our response
is not applied to the blue orbit yet.

One figure never mixes propagators: computed is SGP4 on both objects, sampled
is RK45 on both. Where a matrix holds both, the result states the measured
gap between the two propagators for these orbits.

The bound fixtures are the plane-change reference element sets
(tests/unit/_decision_reference.py): SGP4 puts their crossing at 10.4036 km,
1,410.93 s after EPOCH.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from spectre.astro import monte_carlo
from spectre.astro.along_track import ERROR_MODEL_WORDS
from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import (
    ElsetApproach,
    ElsetFailure,
    elset_closest_approach,
    elset_position_error_km,
)
from spectre.astro.monte_carlo import ManoeuvreHypothesis, SeparationWindow
from spectre.domain import decision
from spectre.domain.decision import (
    LOOKUP_BASES,
    BoundElset,
    ComputedPlan,
    MissRule,
    OutcomeMetrics,
    ScenarioBinding,
    ScenarioResult,
    evaluate_scenario,
    outcome_bases,
    plan_computed,
)
from spectre.domain.decision_figures import ELSET_MODEL
from spectre.domain.provenance import Basis, FigureBasis
from tests.unit._decision_reference import EPOCH, GEO_DRIFT_IN, PLANE_CHANGE
from tests.unit.test_decision_figure_basis import _render
from tests.unit.test_decision_sampled import (
    _LOOKUPS,
    _binding,
    _bound,
    _elset,
    _evasive,
    _Fake,
    _never,
    _page,
    _scenario,
    _steady,
)

_MANOEUVRE, _RETASK, _POSTURE, _NO_ACTION = 0, 1, 2, 3
_STILL = (_RETASK, _POSTURE, _NO_ACTION)
_HOUR = SeparationWindow(EPOCH, 3600.0)


def _computed(**kwargs: Any) -> ScenarioResult:
    """The 4 x 4 plane-change scenario, bound on both sides, with no hypothesis: nothing is sampled."""
    return evaluate_scenario(_scenario(binding=kwargs.pop("binding", _binding()), **kwargs), sampler=_never)


def _reference() -> ElsetApproach:
    found = elset_closest_approach(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, _HOUR)
    assert isinstance(found, ElsetApproach)
    return found


def _cells(result: ScenarioResult, row: int) -> list[OutcomeMetrics]:
    return result.outcome_matrix[row]


@pytest.fixture(scope="module")
def computed() -> ScenarioResult:
    return _computed()


# ── D1, D2, D8: which rows are computed, and what a computed cell holds ──

class TestARowThatDoesNotMoveRedIsComputed:
    def test_a_bound_no_action_row_is_computed(self, computed: ScenarioResult) -> None:
        """D1: 10.4 km at 1,410.9 s, where the lookup says 5,000 km."""
        reference = _reference()
        for cell in _cells(computed, _NO_ACTION):
            assert cell.ca_computed == reference
            assert cell.closest_approach_km == 10.4
            assert cell.figure_bases.closest_approach_km.kind is Basis.COMPUTED
            assert cell.figure_bases.time_to_closest_hours.kind is Basis.COMPUTED
            assert cell.ca_refusal is None and cell.ca_percentiles is None
        assert _cells(evaluate_scenario(_scenario()), _NO_ACTION)[_NO_ACTION].closest_approach_km == 5000.0

    def test_every_row_that_does_not_move_red_shares_one_figure_across_responses(
        self, computed: ScenarioResult, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """D2: the lookup differs by type and response cost; the computed figure is the pair's, searched once."""
        calls: list[SeparationWindow] = []
        real = decision.elset_closest_approach

        def counted(red: str, blue: str, window: SeparationWindow) -> ElsetApproach | ElsetFailure:
            calls.append(window)
            return real(red, blue, window)

        monkeypatch.setattr(decision, "elset_closest_approach", counted)
        result = _computed()
        assert calls == [_HOUR]
        cells = [cell for row in _STILL for cell in _cells(result, row)]
        assert len(cells) == 12
        assert {cell.closest_approach_km for cell in cells} == {10.4}
        assert all(cell.ca_computed is cells[0].ca_computed for cell in cells)
        assert {cell.time_to_closest_hours for cell in cells} == {0.39}
        lookup = evaluate_scenario(_scenario())
        assert len({cell.closest_approach_km for row in _STILL for cell in _cells(lookup, row)}) > 1

    def test_the_tca_is_carried_unrounded_with_its_edge_flag(self, computed: ScenarioResult) -> None:
        """D8: 1,410.93 s, which 0.39 h rounds to 1,404 s."""
        cell = _cells(computed, _NO_ACTION)[0]
        assert cell.ca_computed is not None
        assert cell.ca_computed.approach.tca_s == pytest.approx(1410.93, abs=0.01)
        assert cell.ca_computed.approach.miss_km == pytest.approx(10.4036, abs=0.0001)
        assert cell.ca_computed.approach.at_window_edge is False
        assert cell.time_to_closest_hours == 0.39


# ── D3 to D7: what is refused, and the span ──

_NOT_A_BURN = (
    "Not computed: a manoeuvre with no hypothesis names no burn, and propagating the orbit as it stands would show "
    "only where it goes if it does not move. Add a manoeuvre hypothesis to sample this row." + _LOOKUPS
)


class TestWhatIsNotComputed:
    def test_a_manoeuvre_row_without_a_hypothesis_is_refused_with_its_sentence(self, computed: ScenarioResult) -> None:
        """D3: scored on its no-burn miss, a manoeuvre would read 10.4 km where the lookup takes 200 km."""
        for cell in _cells(computed, _MANOEUVRE):
            assert cell.ca_computed is None
            assert cell.ca_refusal == _NOT_A_BURN
            assert cell.figure_bases.closest_approach_km == FigureBasis(
                Basis.LOOKUP, f"{LOOKUP_BASES.closest_approach_km.note}. {_NOT_A_BURN}",
            )
        lookup = evaluate_scenario(_scenario())
        for cell, plain in zip(_cells(computed, _MANOEUVRE), _cells(lookup, _MANOEUVRE), strict=True):
            assert dataclasses.replace(cell, ca_refusal=None, figure_bases=LOOKUP_BASES) == plain

    def test_a_refused_hypothesis_row_stays_a_lookup_and_is_never_computed(self) -> None:
        """D4: a no-action row carrying a 10-sample hypothesis is refused, not given the no-burn figure."""
        result = evaluate_scenario(_bound({_NO_ACTION: _evasive(10)}), sampler=_never)
        for cell in _cells(result, _NO_ACTION):
            assert cell.ca_computed is None
            assert str(cell.ca_refusal).startswith("Not sampled: 10 samples are fewer than the 50")
            assert cell.figure_bases.closest_approach_km.kind is Basis.LOOKUP
        assert all(cell.ca_computed is not None for row in (_RETASK, _POSTURE) for cell in _cells(result, row))

    @pytest.mark.parametrize(
        ("binding", "side"),
        [
            (_binding(red_age=30.0), "red"),
            (_binding(blue_age=30.0), "blue"),
            (_binding(red_age=None), "red"),
            (_binding(blue_age=None), "blue"),
            (_binding(red_age=24.0), "red"),
        ],
        ids=["red out of date", "blue out of date", "red age unknown", "blue age unknown", "red exactly at its limit"],
    )
    def test_an_orbit_out_of_date_or_of_unknown_age_is_refused(self, binding: ScenarioBinding, side: str) -> None:
        """D5: as sampling refuses it. At its limit exactly an orbit is current but has no time left to earn."""
        result = _computed(binding=binding)
        sentence = (
            f"Not computed: the {side} orbit is out of date or its age is unknown, so a miss computed from it would "
            "not be earned." + _LOOKUPS
        )
        for row in _STILL:
            for cell in _cells(result, row):
                assert cell.ca_computed is None
                assert cell.ca_refusal == sentence
                assert cell.figure_bases.closest_approach_km.kind is Basis.LOOKUP

    @pytest.mark.parametrize("reason", ["propagation", "unparsable"])
    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_an_sgp4_failure_is_refused_naming_its_side(
        self, side: str, reason: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """D6."""
        monkeypatch.setattr(decision, "elset_closest_approach", lambda *_: ElsetFailure(side, reason))  # type: ignore[arg-type]
        result = _computed()
        sentence = (
            f"Not computed: SGP4 could not propagate the {side} element set across the horizon, so a miss without "
            "those instants could hide the closest." + _LOOKUPS
        )
        assert {cell.ca_refusal for row in _STILL for cell in _cells(result, row)} == {sentence}
        assert result.n_computed_cells == 0

    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_a_real_failure_names_the_side_whose_element_set_failed(self, side: str) -> None:
        """D6b: through the real search, so the element sets must reach it red first; swapped, the operator would
        be told the wrong orbit failed."""
        bad = dataclasses.replace(_elset(side), tle="not an element set")
        binding = ScenarioBinding(
            red=bad if side == "red" else _elset("red"), blue=bad if side == "blue" else _elset("blue"),
        )
        plan = plan_computed(_scenario(binding=binding))
        assert plan is not None and plan.approach is None
        assert plan.refusal == (
            f"Not computed: SGP4 could not propagate the {side} element set across the horizon, so a miss without "
            "those instants could hide the closest." + _LOOKUPS
        )

    @pytest.mark.parametrize(
        ("red_age", "blue_age", "span_h", "end"),
        [(20.0, 0.0, 4.0, "16:00"), (0.0, 22.0, 2.0, "14:00"), (20.0, 21.5, 2.5, "14:30")],
        ids=["red", "blue", "the shorter of the two"],
    )
    def test_the_span_is_trimmed_to_the_element_set_limits(
        self, red_age: float, blue_age: float, span_h: float, end: str,
    ) -> None:
        """D7: a 20 h old element set with a 24 h limit earns 4 h of a 10 h horizon."""
        result = _computed(binding=_binding(red_age, blue_age), horizon_hours=10.0)
        cell = _cells(result, _NO_ACTION)[0]
        assert cell.ca_computed is not None
        assert cell.ca_computed.window == SeparationWindow(EPOCH, span_h * 3600.0)
        assert result.searched_span_note == (
            f"Closest approaches are searched over the first {span_h:.1f} h of the 10 h horizon, while both element "
            f"sets are within their limits; past 2026-10-17 {end} UTC a miss would rest on an out-of-date orbit."
        )
        assert f"over {span_h:.1f} h of the 10 h horizon" in cell.figure_bases.closest_approach_km.note
        assert result.searched_span_note in _page(result)

    def test_an_untrimmed_span_has_no_note(self, computed: ScenarioResult) -> None:
        assert computed.searched_span_note is None


# ── D9, D10: the edge lines and the notes ──

def _geo(side: str) -> BoundElset:
    tle = GEO_DRIFT_IN.red_tle if side == "red" else GEO_DRIFT_IN.blue_tle
    return BoundElset(
        side=side, name=f"{side.upper()}_GEO", stk_name=f"{side.upper()}_GEO",  # type: ignore[arg-type]
        satno=90002 if side == "red" else 90001, tle=tle, data_mode="REAL", epoch=EPOCH, age_hours=0.0,
        limit_hours=72.0,
    )


class TestTheEdgesAndTheNotes:
    def test_a_minimum_at_the_end_of_the_search_says_still_closing(self) -> None:
        """D9: GEO drift-in closes to 30 km at 31.1 h, so over 24 h the closest is the last instant."""
        result = _computed(binding=ScenarioBinding(red=_geo("red"), blue=_geo("blue")), horizon_hours=24.0)
        cell = _cells(result, _NO_ACTION)[0]
        assert cell.ca_computed is not None
        assert cell.ca_computed.approach.at_window_edge is True
        assert cell.ca_computed.approach.tca_s == 24 * 3600.0
        assert cell.ca_computed_caveat == (
            "Still closing when the search ends, so the closest approach comes after it: this is the separation "
            "then, not an encounter."
        )
        assert cell.ca_computed_caveat in _page(result)

    def test_a_minimum_at_the_start_says_already_opening(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opening = ElsetApproach(ClosestApproach(812.3, 0.0, True), 0.4, _HOUR)
        monkeypatch.setattr(decision, "elset_closest_approach", lambda *_: opening)
        cell = _cells(_computed(), _NO_ACTION)[0]
        assert cell.ca_computed_caveat == (
            "Already opening at the scenario epoch: the closest in the horizon is now, and any closer approach was "
            "before it."
        )

    def test_an_interior_minimum_has_no_edge_line(self, computed: ScenarioResult) -> None:
        assert _cells(computed, _NO_ACTION)[0].ca_computed_caveat is None
        assert _cells(computed, _MANOEUVRE)[0].ca_computed_caveat is None

    def test_the_basis_notes_name_sgp4_both_objects_and_both_epochs(self, computed: ScenarioResult) -> None:
        """D10. Since SPC-202 the note names the element-set band beside the miss in place of "element-set error is not
        in it": both sets 1.0 km plus 2 km a day at 1,410.93 s old, 1.03 km each, 1.46 km in quadrature, 1.5 shown."""
        bases = _cells(computed, _NO_ACTION)[0].figure_bases
        tca = EPOCH + timedelta(seconds=_reference().approach.tca_s)
        each = elset_position_error_km(PLANE_CHANGE.red_tle, EPOCH, tca)
        low = _reference().approach.miss_km - math.hypot(each, each)
        assert bases.closest_approach_km == FigureBasis(
            Basis.COMPUTED,
            "smallest separation of the bound red track RED_PC and blue asset BLUE_PC over 1.0 h of the 1 h horizon "
            "from the scenario epoch, both propagated by SGP4 from their element sets (red epoch 2026-10-17 12:00 "
            "UTC, blue epoch 2026-10-17 12:00 UTC) with no burn, sampled every 60 s and each local minimum refined "
            f"to 0.01 s; element-set error is beside it as a band, not in the figure: {math.hypot(each, each):.1f} km "
            f"(1 sigma) at the closest approach, red's {each:.1f} km (0.4 h old then) and blue's {each:.1f} km (0.4 h "
            f"old) combined in quadrature, by {ELSET_MODEL}; the score reads the band's lower edge, {low:.1f} km, the "
            "miss less 1 sigma, and our response is not applied to the blue orbit",
        )
        assert bases.time_to_closest_hours == FigureBasis(
            Basis.COMPUTED,
            "time of that closest approach from the scenario epoch, SGP4 for both orbits, refined to 0.01 s and "
            "shown to the minute",
        )
        for name in ("custody_maintained", "custody_gap_hours"):
            assert getattr(bases, name) == getattr(LOOKUP_BASES, name), name
        # A manoeuvre response with no target separation keeps the lookup and says how to size it (SPC-121).
        assert bases.delta_v_cost_km_s == FigureBasis(
            Basis.LOOKUP, f"{LOOKUP_BASES.delta_v_cost_km_s.note}. Enter a target separation to size this burn.",
        )
        # A response that does not burn spends 0 m/s against the no-burn blue orbit, not the lookup's rule (SPC-125).
        still = _cells(computed, _NO_ACTION)[1].figure_bases.delta_v_cost_km_s
        assert still.kind is Basis.COMPUTED and still.note.startswith("this response does not burn")
        assert bases.composite_score.kind is Basis.LOOKUP

    def test_the_basis_note_names_each_sides_own_epoch(self) -> None:
        """D10b: a red element set 3 h older than blue's; one epoch printed for both would hide which orbit is old."""
        binding = ScenarioBinding(red=_elset("red", age=3.0, epoch=EPOCH - timedelta(hours=3)), blue=_elset("blue"))
        note = _cells(_computed(binding=binding), _NO_ACTION)[0].figure_bases.closest_approach_km.note
        assert "(red epoch 2026-10-17 09:00 UTC, blue epoch 2026-10-17 12:00 UTC)" in note

    def test_the_cell_line_and_hover(self, computed: ScenarioResult) -> None:
        cell = _cells(computed, _NO_ACTION)[0]
        assert cell.ca_computed_line == (
            "Computed: 10.4 km at 2026-10-17 12:24 UTC ± 4 s, 0.39 h after the scenario epoch; SGP4, no burn."
        )
        assert cell.ca_title == (
            "Computed: 10.404 km at 1,410.93 s after the scenario epoch, passing at 394 m/s; SGP4 for both orbits "
            "with no burn, so one figure, with no distribution."
        )
        assert _cells(computed, _MANOEUVRE)[0].ca_computed_line is None


# ── D11: the invariants ──

def _computed_bases() -> Any:
    return outcome_bases(**{
        name: FigureBasis(Basis.COMPUTED if name in ("closest_approach_km", "time_to_closest_hours") else Basis.LOOKUP, "n")
        for name in ("custody_maintained", "custody_gap_hours", "closest_approach_km", "time_to_closest_hours",
                     "delta_v_cost_km_s")
    })


def _metrics(**changes: Any) -> OutcomeMetrics:
    values: dict[str, Any] = {
        "custody_maintained": True, "custody_gap_hours": 0.0, "closest_approach_km": 10.4,
        "time_to_closest_hours": 0.39, "delta_v_cost_km_s": 0.0, "composite_score": 0.2,
        "figure_bases": _computed_bases(), "ca_computed": _reference(),
    }
    return OutcomeMetrics(**{**values, **changes})


class TestTheInvariantsHold:
    def test_a_well_formed_computed_cell_is_accepted(self) -> None:
        assert _metrics().ca_computed == _reference()

    @pytest.mark.parametrize(
        ("changes", "match"),
        [
            ({"figure_bases": LOOKUP_BASES}, "computed"),
            ({"ca_computed": None}, "computed"),
            ({"closest_approach_km": 10.0}, "10.4"),
            ({"closest_approach_km": 10.4036}, "10.4"),
            ({"time_to_closest_hours": 0.4}, "0.39"),
            ({"ca_refusal": "Not computed: no."}, "refused"),
            (
                {"ca_percentiles": {5: 10.4, 50: 11.0, 95: 12.0}, "ca_std_km": 1.0, "ca_samples": 50,
                 "ca_half_width_km": 0.1, "score_percentiles": {5: 0.2, 50: 0.2, 95: 0.2}, "score_std": 0.0},
                "sampled",
            ),
        ],
        ids=[
            "computed figure with a lookup basis", "computed basis without the figure", "miss not the computed",
            "miss unrounded", "time not the computed", "refused and computed", "a sampled band too",
        ],
    )
    def test_a_cell_that_breaks_an_invariant_is_refused(self, changes: dict[str, Any], match: str) -> None:
        """D11."""
        with pytest.raises(ValueError, match=match):
            _metrics(**changes)


# ── D12, D13: SGP4 only, and the score ──

def _raises(*_: Any, **__: Any) -> NoReturn:
    raise AssertionError("RK45 ran for a computed cell")


class TestOnlySgp4AndTheScore:
    def test_a_computed_cell_never_calls_rk45(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D12."""
        for name in ("run_separation_series", "_dense_arc", "rk45_sgp4_gap_km"):
            monkeypatch.setattr(monte_carlo, name, _raises)
        monkeypatch.setattr(decision, "run_separation_series", _raises)
        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", _raises)
        result = _computed()
        assert result.n_computed_cells == 12
        assert result.propagator_gap_km is None

    def test_a_sampled_only_result_measures_no_gap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D12b: with no computed cell there is nothing to compare, so no RK45 arc runs outside the budget."""
        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", _raises)
        result = evaluate_scenario(_bound({row: _evasive() for row in range(4)}), sampler=_Fake())
        assert result.n_sampled_cells == 16 and result.n_computed_cells == 0
        assert result.propagator_gap_km is None
        assert result.propagator_line is None

    @pytest.mark.parametrize("rule", [MissRule.ELSET_ERROR, MissRule.POINT])
    def test_the_score_follows_the_computed_miss(self, monkeypatch: pytest.MonkeyPatch, rule: MissRule) -> None:
        """D13: with all the weight on closest approach, the score is the closest-approach term at the unrounded miss
        under the rule before SPC-202: 10.4036 km is just outside the default 10 km keep-out, so ln(50,000 / miss) /
        ln 5,000 (SPC-191); the lookup's 5,000 km is ln 10 / ln 5,000 = 0.270346. Under SPC-202's rule it is the term
        at the band's lower edge, the miss less both sets' error at the TCA in quadrature: 10.4036 - 1.4605 = 8.9432
        km, inside the keep-out, so the full penalty, 1."""
        scenario = dataclasses.replace(_scenario(binding=_binding()), miss_rule=rule)
        for name in ("w_custody", "w_dv_cost", "w_time_to_exec", "w_reversibility"):
            setattr(scenario, name, 0.0)
        scenario.w_closest_approach = 1.0
        scored: list[float] = []
        real = decision._score

        def score(scenario: Any, friendly: Any, figures: Any) -> float:
            scored.append(figures.closest_approach_km)
            return real(scenario, friendly, figures)

        monkeypatch.setattr(decision, "_score", score)
        result = evaluate_scenario(scenario, sampler=_never)
        miss = _reference().approach.miss_km
        assert miss != round(miss, 1)
        tca = EPOCH + timedelta(seconds=_reference().approach.tca_s)
        error = math.hypot(*(elset_position_error_km(tle, EPOCH, tca) for tle in (PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle)))
        read = miss if rule is MissRule.POINT else miss - error
        assert scored.count(read) == 12   # every computed cell scores on this, never on the 10.4 shown
        for cell in _cells(result, _NO_ACTION):
            assert cell.closest_approach_km == round(miss, 1)
            expected = 1.0 if read <= 10.0 else math.log(50_000.0 / read) / math.log(5_000.0)
            assert cell.composite_score == round(expected, 6)
        lookup = evaluate_scenario(dataclasses.replace(scenario, binding=None))
        assert _cells(lookup, _NO_ACTION)[_NO_ACTION].composite_score == 0.270346


# ── D14, D15, D17, D19: what the result says ──

_COMPUTED_CAVEAT = (
    "Computed cells propagate both bound orbits with SGP4 as their element sets stand, with no burn: where the "
    "pair goes if the red track does not move, so every row whose action does not move it shares one figure. Our "
    "response is not applied to the blue orbit yet, so every response in a computed row has the same closest "
    "approach, and the ranking within it is decided by lookup figures. Element-set error, by "
    "spectre/astro/along_track.py's model, the threat sweep's rule of thumb, tuned, not sourced: " + ERROR_MODEL_WORDS
    + ", is shown beside each computed miss as a band, "
    "the miss less and plus both sets' error at the closest approach in quadrature (1 sigma), read at each set's age "
    "then (red's set 0.0 h old and blue's 0.0 h old at the scenario epoch, older by the time to the closest "
    "approach), and the score reads the band's lower edge: Claude's choice, since you read the closer case to "
    "answer whether it can reach one of yours."
)


class TestWhatTheResultSays:
    def test_the_computed_caveat_is_on_the_result_and_the_page(self, computed: ScenarioResult) -> None:
        """D14."""
        assert computed.computed_caveat == _COMPUTED_CAVEAT
        assert _COMPUTED_CAVEAT in _page(computed)
        assert evaluate_scenario(_scenario()).computed_caveat is None

    def test_the_basis_lines_count_computed_cells(self, computed: ScenarioResult) -> None:
        assert "Closest approach: lookup in 4 of 16 cells, computed in 12." in computed.basis_lines
        assert "Time to closest approach: lookup in 4 of 16 cells, computed in 12." in computed.basis_lines
        assert "Score: lookup in every cell." in computed.basis_lines

    def test_a_computed_row_says_it_has_no_spread(self, computed: ScenarioResult) -> None:
        """Since SPC-202 each computed row names its first cell's band: plane_change's TCA 0.4 h after both epochs,
        each set 1.03 km by 1 km plus 2 km a day, 1.46 km in quadrature, 1.5 shown."""
        tca = EPOCH + timedelta(seconds=_reference().approach.tca_s)
        each = elset_position_error_km(PLANE_CHANGE.red_tle, EPOCH, tca)
        assert computed.row_uncertainty == (
            "Not computed, so no spread: the cells say why.",
            *(("Computed by SGP4 with no burn: one figure, no spread, with element-set error as a band beside it; "
               f"the score reads its lower edge. The band is {math.hypot(each, each):.1f} km (1 sigma) at the first "
               f"cell's closest approach, red's {each:.1f} km (its set 0.4 h old then) and blue's {each:.1f} km "
               f"(0.4 h old) in quadrature, by {ELSET_MODEL}.",) * 3),
        )

    def test_the_propagator_line_states_the_measured_gap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D15: a computed row and a sampled row in one matrix; the gap is measured once, over the horizon."""
        asked: list[tuple[str, str, SeparationWindow, tuple[ManoeuvreHypothesis, ...]]] = []

        def gap(red: str, blue: str, window: SeparationWindow, hypotheses: tuple[ManoeuvreHypothesis, ...]) -> float:
            asked.append((red, blue, window, tuple(hypotheses)))
            return 2.4

        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", gap)
        result = evaluate_scenario(_bound(), sampler=_Fake())
        sampled = result.scenario.adversary_actions[_MANOEUVRE].hypothesis
        assert sampled is not None
        assert asked == [(PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, _HOUR, (sampled.hypothesis,))]
        assert result.propagator_gap_km == 2.4
        line = (
            "Computed rows use SGP4; sampled rows use RK45 with J2 and drag, from the same element sets. Over this "
            "horizon the two propagators place these orbits up to 2.4 km apart in separation, so a difference "
            "between a computed row and a sampled row smaller than 2.4 km is the propagators, not the burn."
        )
        assert result.propagator_line == line
        assert line in _page(result)

    def test_red_is_measured_from_each_sampled_rows_burn_and_only_those(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A sampled row integrates red from its burn, which may be days before the window; a refused row is not
        sampled, so its burn plays no part in what a sampled figure could differ by."""
        asked: list[tuple[ManoeuvreHypothesis, ...]] = []

        def gap(*args: Any) -> float:
            asked.append(tuple(args[3]))
            return 2.4

        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", gap)
        early = _steady(50, at=EPOCH - timedelta(hours=2))
        # The red element set predates the burn, or the burn could already be in it and sampling is refused.
        binding = ScenarioBinding(red=_elset("red", age=3.0, epoch=EPOCH - timedelta(hours=3)), blue=_elset("blue"))
        scenario = _scenario({_MANOEUVRE: early, _RETASK: _evasive(10)}, binding=binding)
        result = evaluate_scenario(scenario, sampler=_Fake())
        assert result.outcome_matrix[_MANOEUVRE][0].ca_percentiles is not None
        assert result.outcome_matrix[_RETASK][0].ca_refusal is not None
        assert asked == [(result.scenario.adversary_actions[_MANOEUVRE].hypothesis.hypothesis,)]  # type: ignore[union-attr]
        assert asked[0][0].epoch_utc == EPOCH - timedelta(hours=2)

    def test_a_gap_that_could_not_be_measured_says_do_not_compare(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", lambda *_: None)
        result = evaluate_scenario(_bound(), sampler=_Fake())
        assert result.propagator_line == (
            "The two propagators could not be compared for these orbits, so do not compare a computed row with a "
            "sampled row."
        )

    def test_no_propagator_line_without_both_kinds(self, computed: ScenarioResult) -> None:
        assert computed.propagator_line is None
        assert evaluate_scenario(_scenario()).propagator_line is None

    @pytest.mark.parametrize(("binding", "side"), [
        (_binding(blue=False), "a blue asset"), (_binding(red=False), "a red track"),
    ], ids=["red only", "blue only"])
    def test_one_side_bound_says_bind_the_other_to_compute(self, binding: ScenarioBinding, side: str) -> None:
        """D17; SPC-119: only the side still to bind is named."""
        result = evaluate_scenario(_scenario(binding=binding))
        line = f"Closest approach not computed: bind {side} to compute it."
        assert result.computed_binding_note == line
        assert line in _page(result)
        assert result.n_computed_cells == 0
        assert evaluate_scenario(_scenario()).computed_binding_note is None
        assert _computed().computed_binding_note is None

    def test_the_footer_counts_computed_and_sampled_cells(self, computed: ScenarioResult) -> None:
        """D19."""
        assert "Phase 3 · computed closest approach in 12 cells · sampled in 0 cells · What if" in _page(computed)
        both = evaluate_scenario(_bound(), sampler=_Fake())
        assert "Phase 3 · computed closest approach in 12 cells · sampled in 4 cells" in _page(both)
        assert "Phase 1 · What if" in _page(evaluate_scenario(_scenario()))


# ── D18: the page ──

class TestThePage:
    def test_a_computed_cell_prints_tenths_its_mark_and_its_time(self, computed: ScenarioResult) -> None:
        """D18: 10.4 km, not 10 km."""
        text = _page(computed)
        assert text.count("10.4 km (computed)") == 12
        assert text.count(
            "Computed: 10.4 km at 2026-10-17 12:24 UTC ± 4 s, 0.39 h after the scenario epoch; SGP4, no burn."
        ) == 12
        assert text.count(_NOT_A_BURN) == 4
        html = _render(computed)
        assert 'title="Computed: 10.404 km at 1,410.93 s after the scenario epoch, passing at 394 m/s;' in html

    def test_an_older_result_renders_under_strict_undefined(self, computed: ScenarioResult) -> None:
        """A result object from before SPC-120, without its fields, renders and shows no computed line."""
        old_fields = ("custody_maintained", "custody_gap_hours", "closest_approach_km", "time_to_closest_hours",
                      "delta_v_cost_km_s", "composite_score", "ca_percentiles", "ca_refusal", "ca_caveat")
        old = SimpleNamespace(
            scenario=computed.scenario, ranked_per_adversary=computed.ranked_per_adversary,
            robust_best_response=computed.robust_best_response, robust_strategy=computed.robust_strategy,
            computation_time_s=computed.computation_time_s,
            outcome_matrix=[[SimpleNamespace(**{n: getattr(c, n) for n in old_fields}) for c in row]
                            for row in computed.outcome_matrix],
        )
        text = _page(old)  # type: ignore[arg-type]
        assert "Computed:" not in text and "Phase 3" not in text


# ── plan_computed ──

class TestPlanComputed:
    def test_it_is_none_unless_bound_on_both_sides(self) -> None:
        assert plan_computed(_scenario()) is None
        assert plan_computed(_scenario(binding=_binding(blue=False))) is None
        assert plan_computed(_scenario(binding=_binding(red=False))) is None

    def test_it_is_the_pairs_approach_or_its_refusal(self) -> None:
        assert plan_computed(_scenario(binding=_binding())) == ComputedPlan(approach=_reference(), refusal=None)
        refused = plan_computed(_scenario(binding=_binding(red_age=30.0)))
        assert refused is not None and refused.approach is None
        assert str(refused.refusal).startswith("Not computed: the red orbit is out of date")

    def test_the_red_epoch_starts_the_trim_only_while_current(self) -> None:
        """An element set aged past the scenario start by exactly its age trims the span by that age."""
        binding = ScenarioBinding(red=_elset("red", age=23.0), blue=_elset("blue", age=0.0))
        plan = plan_computed(_scenario(binding=binding, horizon_hours=2.0))
        assert plan is not None and plan.approach is not None
        assert plan.approach.window.span_s == pytest.approx(3600.0)
        assert plan.approach.window.start_utc == EPOCH
        assert timedelta(seconds=plan.approach.window.span_s) == timedelta(hours=1)


class TestTheNotesSayWhatIsComputed:
    def test_the_all_lookup_basis_says_how_to_earn_a_computed_closest_approach(self) -> None:
        """Unbound, or bound on one side, the all-lookup basis says what binding would earn: only the side still to
        bind (SPC-119)."""
        assert "Phase 1" not in decision.MODELLED_BASIS
        bind = (
            "Bind a red track and a blue asset to compute the closest approach of a row whose action does not move "
            "the red track, or to sample one that carries a manoeuvre hypothesis."
        )
        for binding, line in ((None, bind), (_binding(blue=False), decision.BIND_BLUE_TO_EARN),
                              (_binding(red=False), decision.BIND_RED_TO_EARN)):
            result = evaluate_scenario(_scenario(binding=binding))
            assert result.basis == f"{decision.MODELLED_BASIS} {line}"
            assert result.basis in _page(result)

    def test_bound_with_every_row_refused_it_does_not_ask_to_bind(self) -> None:
        """Both sides bound and every row refused (a stale orbit): asking to bind would be a wrong instruction."""
        result = evaluate_scenario(_scenario(binding=_binding(red_age=30.0)))
        assert result.n_computed_cells == 0 and result.n_sampled_cells == 0
        assert result.basis == (
            f"{decision.MODELLED_BASIS} Both orbits are bound, but no closest approach could be computed or "
            "sampled: each cell says why."
        )
        assert "Bind a red track" not in result.basis
        assert "Bind a red track" not in _render(result)

    def test_a_cell_hover_never_asks_to_bind(self) -> None:
        """A refused cell sits in a bound scenario; its hover describes the lookup and leaves the advice to the result."""
        result = evaluate_scenario(_scenario(binding=_binding(red_age=30.0)))
        assert {cell.basis for row in result.outcome_matrix for cell in row} == {decision.MODELLED_BASIS}
        assert "Bind" not in decision.MODELLED_BASIS
