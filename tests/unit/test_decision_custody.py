"""Custody in a scenario's outcomes, from the bound red track's SPC-018 status (SPC-123).

Custody is the operator's: timely and actionable information to judge whether
a burn is normal and how the warning time changed. With a red track bound and
its status read, a row's custody is that status carried over the horizon on
the assumption that no newer element set arrives (custody_over_horizon), so
its gap is an upper bound, with basis computed. It describes our information
about red, so it is the same for every response in a row: our response is not
applied to custody yet. A manoeuvre with no hypothesis names no burn time, so
it takes the worst case, a burn at the scenario epoch, with basis lookup.
Unbound, blue only, or with no status read, the rule of thumb stays and the
page says so. Degraded custody cannot judge whether a burn is normal, so in
the operator's terms it is neither held nor lost: the owner ruled on
2026-11-05 (SPC-179) that each hour of it carries 0.25 of the custody penalty
an hour lost carries, and it is shown as degraded in the cell, the cell's
basis and the result's note, never in the gap of lost hours. Custody already
lost at the epoch is lost whatever the burn time, so a manoeuvre with no
hypothesis is computed then, not the worst case; degraded custody is not lost
yet, so such a manoeuvre takes the worst case.

The bound fixtures are the plane-change reference element sets, both at
EPOCH, against a 24 h limit, over a 1 h horizon.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain.custody import BASIS, Custody, CustodyStatus
from spectre.domain.decision import (
    LOOKUP_BASES,
    BoundElset,
    OutcomeMetrics,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    evaluate_scenario,
    outcome_bases,
)
from spectre.domain.provenance import Basis, FigureBasis
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_sampled import _elset, _Fake, _never, _page, _render, _scenario, _steady

_MANOEUVRE, _RETASK, _POSTURE, _NO_ACTION = 0, 1, 2, 3
_HELD = CustodyStatus(Custody.HELD, "Custody held: its orbit is 0.0 h old (limit 24 h) and 40 element sets over 30 days judge its burns.")
_DEGRADED = CustodyStatus(
    Custody.DEGRADED, "Custody degraded: its orbit is current (0.0 h old, limit 24 h), but whether its burns are normal "
    "cannot be judged. UDL is not connected, so no element-set history is held.",
)
_LOST = CustodyStatus(Custody.LOST, "Custody lost: its newest element set is 30.0 h old against a 24 h limit.")

_HELD_THROUGH = (
    "Custody held through the 1 h horizon: its newest element set stays within its 24 h limit until "
    "2026-10-18 12:00 UTC, after the horizon ends."
)
_WORST_CASE = (
    "Custody lost for up to the whole 1 h horizon, taking the worst case: this manoeuvre names no burn time, so the "
    "burn is taken at the scenario epoch. Add a manoeuvre hypothesis with a burn time to compute it."
)
_BURN_AHEAD = (
    "Custody lost from the burn at 2026-10-17 12:15 UTC, 0.2 h into the horizon, for up to 0.8 h: the burn is newer "
    "than the newest element set, so whether it is normal and how it changes your warning time cannot be judged "
    "until a newer element set arrives."
)
_CUSTODY_NOTE = (
    "Custody is the bound red track's as the sweep judges it, held, degraded or lost, carried over the horizon on "
    "the assumption that no newer element set arrives, so each custody gap is an upper bound. Our response is not "
    "applied to custody yet: a sensor retask that would bring a newer element set sooner is not modelled, so every "
    "response in a row has the same custody. Degraded custody can judge the warning time but not whether a burn "
    "is normal, so the hours it is degraded are shown as degraded, neither held nor lost: each carries 0.25 of the "
    "custody penalty an hour lost carries, the owner's ruling of 2026-11-05 rather than a sourced figure, and the "
    "custody gap counts only the hours lost. Like held custody, it is lost once its newest element set passes its "
    "limit or a burn is newer than it, and a manoeuvre that names no burn time takes the worst case. " + BASIS
)
_DEGRADED_THROUGH = (
    "Custody degraded through the 1 h horizon: its newest element set stays within its 24 h limit until "
    "2026-10-18 12:00 UTC, after the horizon ends. Degraded, neither held nor lost: how a burn changes your warning "
    "time can be judged, but whether it is normal cannot."
)
_DEGRADED_NOTE = (
    "the bound red track RED_PC's custody as the sweep judges it at the scenario epoch, degraded, carried over the "
    "1 h horizon on the assumption that no newer element set arrives: lost once its newest element set passes its "
    "limit or a hypothesised burn is newer than it; degraded, neither held nor lost, for 1.0 h of the horizon, each "
    "such hour carrying 0.25 of the custody penalty an hour lost carries (the owner's ruling of 2026-11-05), since "
    "degraded custody can judge the warning time but not whether a burn is normal; our response is not applied"
)
_DEGRADED_GAP_NOTE = (
    "hours of the horizon custody is lost, an upper bound, since a newer element set may arrive sooner; the hours "
    "it is degraded, 1.0 h, are not lost hours and are not in this gap; our response is not applied"
)
_RULE_OF_THUMB = "Custody here is a rule of thumb, not the held, degraded or lost custody shown on the sweep."
_BIND_RED = "Bind a red track to compute it from its element set and history."


def _red(status: CustodyStatus | None = _HELD, **kwargs: Any) -> BoundElset:
    return dataclasses.replace(_elset("red", **kwargs), custody=status)


def _custodied(status: CustodyStatus | None = _HELD, *, blue: bool = True, **kwargs: Any) -> ScenarioBinding:
    return ScenarioBinding(red=_red(status, **kwargs), blue=_elset("blue") if blue else None)


def _burn_at_quarter_hour(scenario: Scenario, hours: float = 0.25) -> Scenario:
    """Row 0 carries a hypothesis burning 0.25 h, or *hours*, into the 1 h horizon, with a rule-of-thumb gap share
    of 0.5."""
    action = dataclasses.replace(
        scenario.adversary_actions[0], custody_gap_fraction=0.5, hypothesis=_steady(50, at=EPOCH + timedelta(hours=hours)),
    )
    return dataclasses.replace(scenario, adversary_actions=[action, *scenario.adversary_actions[1:]])


def _evaluated(binding: ScenarioBinding | None, *, burn: bool = False) -> ScenarioResult:
    scenario = _scenario(binding=binding)
    if burn:
        return evaluate_scenario(_burn_at_quarter_hour(scenario), sampler=_Fake())
    return evaluate_scenario(scenario, sampler=_never)


@pytest.fixture(scope="module")
def held() -> ScenarioResult:
    return _evaluated(_custodied())


@pytest.fixture(scope="module")
def burnt() -> ScenarioResult:
    return _evaluated(_custodied(), burn=True)


def _custody(cell: OutcomeMetrics) -> tuple[bool, float, Custody | None, Basis, Basis]:
    b = cell.figure_bases
    return (
        cell.custody_maintained, cell.custody_gap_hours, cell.custody_state,
        b.custody_maintained.kind, b.custody_gap_hours.kind,
    )


# ── K2 to K5: which custody each row gets ──

class TestABoundRedTracksCustodyIsComputed:
    def test_a_held_no_action_row_is_computed_with_no_gap(self, held: ScenarioResult) -> None:
        """K2."""
        for cell in held.outcome_matrix[_NO_ACTION]:
            assert _custody(cell) == (True, 0.0, Custody.HELD, Basis.COMPUTED, Basis.COMPUTED)
        assert held.row_custody[_NO_ACTION] == _HELD_THROUGH

    def test_a_hypothesised_burn_loses_custody_from_the_burn(self, burnt: ScenarioResult) -> None:
        """K3: 0.75 h of the 1 h horizon, where the rule of thumb gave horizon x gap share, 0.5 h."""
        for cell in burnt.outcome_matrix[_MANOEUVRE]:
            assert cell.ca_percentiles is not None   # sampled, and custody is computed beside it
            assert _custody(cell) == (False, 0.75, Custody.HELD, Basis.COMPUTED, Basis.COMPUTED)
        assert burnt.row_custody[_MANOEUVRE] == _BURN_AHEAD

    def test_a_manoeuvre_without_a_hypothesis_takes_the_worst_case(self, held: ScenarioResult) -> None:
        """K4: lost for the whole horizon, a lookup, where the rule of thumb gave horizon x gap share."""
        for cell in held.outcome_matrix[_MANOEUVRE]:
            assert _custody(cell) == (False, 1.0, None, Basis.LOOKUP, Basis.LOOKUP)
            assert "worst case" in cell.figure_bases.custody_maintained.note
        assert held.row_custody[_MANOEUVRE] == _WORST_CASE

    def test_a_worst_case_cell_does_not_call_custody_a_rule_of_thumb(self, held: ScenarioResult) -> None:
        """Every figure in the cell is a lookup, so its basis is the modelled line, with custody said truly."""
        for cell in held.outcome_matrix[_MANOEUVRE]:
            assert cell.basis == decision.WORST_CASE_CELL_BASIS
            assert "custody takes the worst case, a burn at the scenario epoch, since this manoeuvre names no burn time" in (
                cell.basis
            )

    def test_a_sensor_retask_has_the_same_custody_as_no_action(self, burnt: ScenarioResult) -> None:
        """K5: the rule of thumb kept custody against a retask, with a gap of half its time to execute."""
        row = burnt.outcome_matrix[_MANOEUVRE]
        assert _custody(row[_RETASK]) == _custody(row[_NO_ACTION])
        assert len({_custody(cell) for cell in row}) == 1
        rule = evaluate_scenario(_burn_at_quarter_hour(_scenario()))
        assert rule.outcome_matrix[_MANOEUVRE][_RETASK].custody_maintained is True
        assert rule.outcome_matrix[_MANOEUVRE][_NO_ACTION].custody_gap_hours == 0.5

    def test_red_bound_alone_computes_custody_beside_lookup_closest_approaches(self) -> None:
        result = _evaluated(_custodied(blue=False))
        cell = result.outcome_matrix[_NO_ACTION][_NO_ACTION]
        assert _custody(cell) == (True, 0.0, Custody.HELD, Basis.COMPUTED, Basis.COMPUTED)
        assert cell.figure_bases.closest_approach_km == LOOKUP_BASES.closest_approach_km
        assert cell.ca_refusal is None

    def test_an_out_of_date_red_is_lost_for_the_whole_horizon(self) -> None:
        result = _evaluated(_custodied(_LOST, age=30.0))
        assert _custody(result.outcome_matrix[_NO_ACTION][0]) == (False, 1.0, Custody.LOST, Basis.COMPUTED, Basis.COMPUTED)
        assert str(result.row_custody[_NO_ACTION]).startswith("Custody lost for the whole 1 h horizon: its newest")


    def test_custody_lost_at_the_epoch_is_computed_for_a_manoeuvre_without_a_hypothesis(self) -> None:
        """No burn time can make custody already lost any worse, so it is computed, not the worst case."""
        result = _evaluated(_custodied(_LOST))
        for cell in result.outcome_matrix[_MANOEUVRE]:
            assert _custody(cell) == (False, 1.0, Custody.LOST, Basis.COMPUTED, Basis.COMPUTED)
        assert str(result.row_custody[_MANOEUVRE]).startswith(
            "Custody lost for the whole 1 h horizon: its newest element set is already past its limit",
        )
        assert "Add a manoeuvre hypothesis" not in str(result.row_custody[_MANOEUVRE])

    def test_degraded_custody_takes_the_worst_case_for_a_manoeuvre_without_a_hypothesis(self) -> None:
        """Degraded is not lost yet, so a burn at the epoch, the worst case, would still lose it (SPC-179)."""
        result = _evaluated(_custodied(_DEGRADED))
        for cell in result.outcome_matrix[_MANOEUVRE]:
            assert _custody(cell) == (False, 1.0, None, Basis.LOOKUP, Basis.LOOKUP)
            assert cell.custody_degraded_hours == 0.0
        assert result.row_custody[_MANOEUVRE] == _WORST_CASE


def _custody_only(binding: ScenarioBinding, *, burn: bool = False) -> ScenarioResult:
    """The scenario with all the weight on custody, so each score is the custody penalty alone."""
    scenario = _scenario(binding=binding)
    scenario = _burn_at_quarter_hour(scenario) if burn else scenario
    for name in ("w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility"):
        setattr(scenario, name, 0.0)
    scenario.w_custody = 1.0
    return evaluate_scenario(scenario, sampler=_Fake() if burn else _never)


class TestTheScore:
    def test_the_degraded_weight_is_the_owners_ruling(self) -> None:
        """K11, SPC-179: the owner ruled on 2026-11-05 that degraded scores between held and lost, at a quarter."""
        assert decision.DEGRADED_CUSTODY_WEIGHT == 0.25

    def test_degraded_through_the_horizon_scores_a_quarter_of_lost(self) -> None:
        """K11: an hour degraded carries 0.25 of the penalty an hour lost carries; held carries none. The still
        rows are degraded for the whole 1 h, with no lost hours; held they score 0 and lost 1."""
        held = _custody_only(_custodied())
        degraded = _custody_only(_custodied(_DEGRADED))
        lost = _custody_only(_custodied(_LOST))
        for row in (_RETASK, _POSTURE, _NO_ACTION):
            assert [c.composite_score for c in held.outcome_matrix[row]] == [0.0] * 4
            assert [c.composite_score for c in degraded.outcome_matrix[row]] == [0.25] * 4
            assert [c.composite_score for c in lost.outcome_matrix[row]] == [1.0] * 4
            for cell in degraded.outcome_matrix[row]:
                assert _custody(cell) == (False, 0.0, Custody.DEGRADED, Basis.COMPUTED, Basis.COMPUTED)
                assert cell.custody_degraded_hours == 1.0

    def test_degraded_until_a_burn_scores_its_degraded_and_lost_hours_apart(self) -> None:
        """Degraded for the 0.25 h before the burn and lost for the 0.75 h after it: 0.75 + 0.25 x 0.25 = 0.8125.
        The gap is the 0.75 h lost, never the hour custody was not held."""
        result = _custody_only(_custodied(_DEGRADED), burn=True)
        for cell in result.outcome_matrix[_MANOEUVRE]:
            assert _custody(cell) == (False, 0.75, Custody.DEGRADED, Basis.COMPUTED, Basis.COMPUTED)
            assert cell.custody_degraded_hours == 0.25
            assert cell.composite_score == 0.8125
            # Each sample is scored with the degraded hours too, so the score's spread agrees with the score.
            assert cell.score_percentiles == pytest.approx({5: 0.8125, 50: 0.8125, 95: 0.8125})
        assert str(result.row_custody[_MANOEUVRE]).startswith("Custody degraded for 0.2 h from the start of the horizon.")

    def test_the_score_counts_the_computed_gap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With all the weight on custody, every cell of the burn row scores 0.75, and the no-action row 0."""
        scenario = _burn_at_quarter_hour(_scenario(binding=_custodied()))
        for name in ("w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility"):
            setattr(scenario, name, 0.0)
        scenario.w_custody = 1.0
        scored: list[tuple[bool, float]] = []
        real = decision._score

        def score(scenario: Any, friendly: Any, figures: Any) -> float:
            scored.append((figures.custody_maintained, figures.custody_gap_hours))
            return real(scenario, friendly, figures)

        monkeypatch.setattr(decision, "_score", score)
        result = evaluate_scenario(scenario, sampler=_Fake())
        assert [c.composite_score for c in result.outcome_matrix[_MANOEUVRE]] == [0.75] * 4
        assert [c.composite_score for c in result.outcome_matrix[_NO_ACTION]] == [0.0] * 4
        assert (False, 0.75) in scored


# ── K6, K7, K8: what keeps the rule of thumb, and the refusal suffix ──

class TestTheRuleOfThumbStaysWhereNothingIsComputed:
    @pytest.mark.parametrize("binding", [None, ScenarioBinding(blue=_elset("blue"))], ids=["unbound", "blue only"])
    def test_without_a_red_track_the_rule_of_thumb_stays_and_says_bind_one(
        self, binding: ScenarioBinding | None,
    ) -> None:
        """K6."""
        result = _evaluated(binding)
        assert all(c.figure_bases.custody_maintained == LOOKUP_BASES.custody_maintained for row in result.outcome_matrix for c in row)
        assert result.custody_rule_of_thumb is True
        assert result.custody_bind_note == _BIND_RED
        assert result.custody_note is None
        text = _page(result)
        assert _RULE_OF_THUMB in text and _BIND_RED in text

    def test_a_red_track_with_no_status_read_keeps_the_rule_of_thumb_and_does_not_ask_to_bind(self) -> None:
        result = _evaluated(_custodied(None))
        assert result.custody_rule_of_thumb is True
        assert result.custody_bind_note == decision.CUSTODY_NOT_READ
        text = _page(result)
        assert _RULE_OF_THUMB in text and _BIND_RED not in text

    def test_with_custody_computed_the_rule_of_thumb_line_goes(self, held: ScenarioResult) -> None:
        """The worst-case manoeuvre row is a lookup, but not the rule of thumb, so the line does not return."""
        assert held.custody_rule_of_thumb is False
        assert held.custody_bind_note is None
        text = _page(held)
        assert _RULE_OF_THUMB not in text and _BIND_RED not in text

    def test_custody_on_a_blue_element_set_is_refused(self) -> None:
        """K7: custody describes our information about red."""
        with pytest.raises(ValueError, match="red"):
            dataclasses.replace(_elset("blue"), custody=_HELD)

    def test_a_refused_cell_says_only_its_closest_approach_is_a_lookup(self) -> None:
        """K8: an out-of-date red refuses the computed closest approach, and custody is computed in that cell."""
        result = _evaluated(_custodied(_LOST, age=30.0))
        cell = result.outcome_matrix[_NO_ACTION][0]
        assert str(cell.ca_refusal).endswith(" This cell's closest approach is a lookup.")
        assert "figures are lookups" not in str(cell.ca_refusal)
        assert cell.figure_bases.custody_maintained.kind is Basis.COMPUTED


# ── K12 and the result's notes ──

class TestWhatTheResultSays:
    def test_every_row_computed_reads_computed_in_every_cell(self, burnt: ScenarioResult) -> None:
        """K12."""
        assert "Custody: computed in every cell." in burnt.basis_lines
        assert "Custody gap: computed in every cell." in burnt.basis_lines

    def test_the_custody_note_says_what_custody_is_and_is_not(self, held: ScenarioResult) -> None:
        assert held.custody_note == _CUSTODY_NOTE
        assert _CUSTODY_NOTE in _page(held)

    def test_the_row_sentences_and_the_status_at_evaluation_are_on_the_page(self, held: ScenarioResult) -> None:
        text = _page(held)
        assert text.count(_HELD_THROUGH) == 3   # the retask, posture and no-action rows
        assert _WORST_CASE in text
        assert f"Custody at evaluation: {_HELD.sentence}" in text

    def test_degraded_custody_is_shown_in_the_cell_never_ticked_or_crossed(self) -> None:
        """SPC-179: the three still rows are degraded through the horizon; the manoeuvre row takes the worst case."""
        result = _evaluated(_custodied(_DEGRADED))
        markup = _render(result)
        text = _page(result)
        assert text.count("◐ custody degraded (computed)") == 12
        assert text.count("✗ custody (lookup)") == 4
        assert "✓ custody" not in text and "✗ custody degraded" not in text
        assert '<span style="color:#22c55e">✓</span>' not in markup
        assert text.count(_DEGRADED_THROUGH) == 3

    def test_degraded_then_lost_is_shown_as_both_in_the_cell(self) -> None:
        text = _page(_evaluated(_custodied(_DEGRADED), burn=True))
        assert text.count("◐ custody degraded, then lost (computed)") == 4

    def test_degraded_custody_is_degraded_in_the_cell_basis_and_not_in_the_gap(self) -> None:
        result = _evaluated(_custodied(_DEGRADED))
        cell = result.outcome_matrix[_NO_ACTION][0]
        assert cell.figure_bases.custody_maintained.note == _DEGRADED_NOTE
        assert cell.figure_bases.custody_gap_hours.note == _DEGRADED_GAP_NOTE
        assert "custody: computed, " + _DEGRADED_NOTE in cell.basis
        assert result.custody_note == _CUSTODY_NOTE
        assert _CUSTODY_NOTE in _page(result)

    @pytest.mark.parametrize("burn_h", [0.004, 0.03])
    def test_a_degraded_span_under_a_tenth_of_an_hour_is_never_shown_as_lost_or_as_none(self, burn_h: float) -> None:
        """A burn 14 s or 108 s in: the cell, its basis, its gap and the row sentence all say degraded, then lost,
        and none says the span was 0.0 h."""
        scenario = _burn_at_quarter_hour(_scenario(binding=_custodied(_DEGRADED)), burn_h)
        result = evaluate_scenario(scenario, sampler=_Fake())
        for cell in result.outcome_matrix[_MANOEUVRE]:
            assert cell.custody_reading == "degraded, then lost"
            assert "for under 0.1 h of the horizon" in cell.figure_bases.custody_maintained.note
            assert "the hours it is degraded, under 0.1 h," in cell.figure_bases.custody_gap_hours.note
            assert "0.0 h" not in cell.basis
        sentence = str(result.row_custody[_MANOEUVRE])
        assert sentence.startswith("Custody degraded for under 0.1 h from the start of the horizon.")
        text = _page(result)
        assert text.count("◐ custody degraded, then lost (computed)") == 4
        assert "for 0.0 h" not in text

    def test_a_cell_in_plain_text_marks_degraded_as_neither_held_nor_lost(self) -> None:
        """OutcomeMetrics' text form keeps the cell's mark: ✓ held, ✗ lost, ◐ degraded (SPC-179)."""
        degraded = _evaluated(_custodied(_DEGRADED)).outcome_matrix[_NO_ACTION][0]
        lost = _evaluated(_custodied(_LOST)).outcome_matrix[_NO_ACTION][0]
        held = _evaluated(_custodied()).outcome_matrix[_NO_ACTION][0]
        assert [str(c).split()[0] for c in (held, degraded, lost)] == ["Custody:✓", "Custody:◐", "Custody:✗"]

    def test_held_custody_says_nothing_of_degraded_hours(self, held: ScenarioResult) -> None:
        bases = held.outcome_matrix[_NO_ACTION][0].figure_bases
        assert "degraded, neither held nor lost" not in bases.custody_maintained.note
        assert "degraded" not in bases.custody_gap_hours.note

    def test_an_all_worst_case_result_does_not_call_custody_a_rule_of_thumb(self) -> None:
        """Every row a manoeuvre with no hypothesis: every figure a lookup, custody the worst case, not the rule."""
        scenario = _scenario(binding=_custodied())
        manoeuvre = scenario.adversary_actions[_MANOEUVRE]
        scenario = dataclasses.replace(scenario, adversary_actions=[
            dataclasses.replace(a, action_type=manoeuvre.action_type, hypothesis=None) for a in scenario.adversary_actions
        ])
        result = evaluate_scenario(scenario, sampler=_never)
        assert result.custody_rule_of_thumb is False
        assert "rule of thumb" not in result.basis
        assert result.basis.startswith(decision.WORST_CASE_BASIS)
        assert "custody takes the worst case, a burn at the scenario epoch, since no manoeuvre names a burn time" in (
            result.basis
        )
        assert result.custody_note is None   # no cell's custody is the bound red track's status
        text = _page(result)
        assert "rule of thumb" not in text
        assert text.count(_WORST_CASE) == 4

    def test_the_basis_notes_say_what_the_figure_rests_on(self, held: ScenarioResult) -> None:
        bases = held.outcome_matrix[_NO_ACTION][0].figure_bases
        assert "RED_PC" in bases.custody_maintained.note and "upper bound" in bases.custody_gap_hours.note
        assert "no newer element set arrives" in bases.custody_maintained.note

    def test_an_older_result_renders_under_strict_undefined(self, held: ScenarioResult) -> None:
        """A result and binding from before SPC-123, without its fields, renders with the rule-of-thumb line."""
        red = SimpleNamespace(**{f.name: getattr(held.scenario.binding.red, f.name)  # type: ignore[union-attr]
                                 for f in dataclasses.fields(BoundElset) if f.name != "custody"},
                              freshness=_elset("red").freshness, age_label="0.0 h", limit_label="24 h",
                              sentence=_elset("red").sentence)
        binding = SimpleNamespace(red=red, blue=held.scenario.binding.blue, note="")  # type: ignore[union-attr]
        old_fields = ("custody_maintained", "custody_gap_hours", "closest_approach_km", "time_to_closest_hours",
                      "delta_v_cost_km_s", "composite_score")
        old = SimpleNamespace(
            scenario=SimpleNamespace(**{**vars(held.scenario), "binding": binding}),
            ranked_per_adversary=held.ranked_per_adversary, robust_best_response=held.robust_best_response,
            robust_strategy=held.robust_strategy, computation_time_s=held.computation_time_s,
            outcome_matrix=[[SimpleNamespace(**{n: getattr(c, n) for n in old_fields}) for c in row]
                            for row in held.outcome_matrix],
        )
        text = _page(old)  # type: ignore[arg-type]
        assert _RULE_OF_THUMB in text and "Custody at evaluation" not in text and "through the" not in text


# ── The invariants ──

def _computed_custody() -> tuple[FigureBasis, FigureBasis]:
    return FigureBasis(Basis.COMPUTED, "custody"), FigureBasis(Basis.COMPUTED, "gap")


def _metrics(**changes: Any) -> OutcomeMetrics:
    maintained, gap = _computed_custody()
    args: dict[str, Any] = {
        "custody_maintained": True, "custody_gap_hours": 0.0, "closest_approach_km": 5000.0,
        "time_to_closest_hours": 0.4, "delta_v_cost_km_s": 0.0, "composite_score": 0.1,
        "figure_bases": outcome_bases(
            custody_maintained=maintained, custody_gap_hours=gap,
            closest_approach_km=LOOKUP_BASES.closest_approach_km,
            time_to_closest_hours=LOOKUP_BASES.time_to_closest_hours,
            delta_v_cost_km_s=LOOKUP_BASES.delta_v_cost_km_s,
        ),
        "custody_state": Custody.HELD,
    }
    args.update(changes)
    return OutcomeMetrics(**args)


class TestTheInvariantsHold:
    def test_a_well_formed_cell_is_accepted(self) -> None:
        assert _metrics().custody_state is Custody.HELD

    @pytest.mark.parametrize(
        ("changes", "match"),
        [
            ({"figure_bases": LOOKUP_BASES}, "custody_state"),
            ({"custody_state": None}, "custody_state"),
            ({"custody_gap_hours": 0.5}, "gap"),
            ({"custody_state": Custody.LOST}, "lost"),
            ({"custody_state": Custody.DEGRADED}, "degraded"),
            ({"custody_degraded_hours": 0.5}, "degraded"),
            ({"custody_maintained": False, "custody_gap_hours": 0.5, "custody_state": Custody.LOST,
              "custody_degraded_hours": 0.5}, "degraded"),
            ({"figure_bases": LOOKUP_BASES, "custody_state": None, "custody_degraded_hours": 0.5}, "degraded"),
            (
                {"figure_bases": outcome_bases(
                    custody_maintained=FigureBasis(Basis.COMPUTED, "custody"),
                    custody_gap_hours=LOOKUP_BASES.custody_gap_hours,
                    closest_approach_km=LOOKUP_BASES.closest_approach_km,
                    time_to_closest_hours=LOOKUP_BASES.time_to_closest_hours,
                    delta_v_cost_km_s=LOOKUP_BASES.delta_v_cost_km_s,
                )},
                "share",
            ),
        ],
        ids=[
            "state with a lookup basis", "computed basis without a state", "maintained with a gap",
            "lost yet maintained", "degraded yet maintained", "degraded hours yet maintained",
            "degraded hours when lost at the epoch", "degraded hours on a lookup", "custody and its gap on different bases",
        ],
    )
    def test_a_cell_that_breaks_an_invariant_is_refused(self, changes: dict[str, Any], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            _metrics(**changes)
