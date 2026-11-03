"""Every Decision Engine figure states its own basis (SPC-101).

One "modelled" flag and one basis string covered every figure in a cell, so
a later release could not show a computed closest approach beside a lookup
custody without either hiding the lookup or under-selling the computed
figure. Each figure now carries a typed basis (lookup, sampled or computed).
The score's basis is derived from the figures its formula uses and is never
stronger than lookup, because its weights and normalisations are rules of
thumb. The result's flags are worked out from the cells, so the modelled
badge cannot drop while the ranking is still a weighted heuristic (audit
F-034, F-S05-02).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import ElsetApproach
from spectre.astro.monte_carlo import SeparationWindow
from spectre.domain.custody import Custody
from spectre.domain.decision import (
    _SCORE_INPUTS,
    BIND_TO_EARN,
    FIGURE_LABELS,
    LOOKUP_BASES,
    MIXED_BASIS,
    MODELLED_BASIS,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeBases,
    OutcomeMetrics,
    Scenario,
    ScenarioResult,
    evaluate_scenario,
    outcome_bases,
)
from spectre.domain.provenance import Basis, FigureBasis, weakest

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_FIGURES = ("custody_maintained", "custody_gap_hours", "closest_approach_km", "time_to_closest_hours",
            "delta_v_cost_km_s")


def _bases(**kinds: Basis) -> OutcomeBases:
    """The lookup bases with the named figures set to another kind, built the way later releases build them."""
    return outcome_bases(**{
        name: FigureBasis(kinds.get(name, Basis.LOOKUP), getattr(LOOKUP_BASES, name).note) for name in _FIGURES
    })


def _scenario(n_friendly: int = 2) -> Scenario:
    adversary = [AdversaryAction(id="A1", name="Approach", action_type=ActionType.MANOEUVRE,
                                 probability=0.6, confidence=0.8)]
    friendly = [
        FriendlyResponse(id=f"F{j}", name=f"F{j}", action_type=ActionType.MANOEUVRE, cost=0.3,
                         reversibility=0.5, time_to_execute_hours=6.0)
        for j in range(n_friendly)
    ]
    return Scenario(name="t", epoch_utc=datetime(2026, 4, 10, tzinfo=UTC),
                    adversary_actions=adversary, friendly_responses=friendly)


def _with_bases(cell: OutcomeMetrics, bases: OutcomeBases) -> OutcomeMetrics:
    """*cell* with *bases*; a computed closest approach carries the figure it rests on (SPC-120's invariant).

    The figure is made to match the cell's own, so these tests of the bases see only the change of kind.
    """
    found = None
    if bases.closest_approach_km.kind is Basis.COMPUTED:
        window = SeparationWindow(datetime(2026, 4, 10, tzinfo=UTC), 72 * 3600.0)
        approach = ClosestApproach(cell.closest_approach_km, cell.time_to_closest_hours * 3600.0, False)
        found = ElsetApproach(approach, 7.5, window)
    # A computed custody carries its state at the scenario epoch (SPC-123's invariant); these cells keep custody.
    state = Custody.HELD if bases.custody_maintained.kind is Basis.COMPUTED else None
    return dataclasses.replace(cell, figure_bases=bases, ca_computed=found, custody_state=state)


def _mixed_result() -> ScenarioResult:
    """A 1 x 2 result whose second cell has a computed closest approach."""
    result = evaluate_scenario(_scenario(2))
    cell = result.outcome_matrix[0][1]
    result.outcome_matrix[0][1] = _with_bases(cell, _bases(closest_approach_km=Basis.COMPUTED))
    return result


def _all_computed_result() -> ScenarioResult:
    result = evaluate_scenario(_scenario(2))
    every = _bases(**dict.fromkeys(_FIGURES, Basis.COMPUTED))
    result.outcome_matrix[0] = [_with_bases(c, every) for c in result.outcome_matrix[0]]
    return result


def _unrecorded_result() -> ScenarioResult:
    """A result whose first cell has the 6 figures but no figure bases at all."""
    result = evaluate_scenario(_scenario(2))
    cell = result.outcome_matrix[0][0]
    result.outcome_matrix[0][0] = SimpleNamespace(**{
        name: getattr(cell, name) for name in (*_FIGURES, "composite_score")
    })
    return result


def _render(result: ScenarioResult) -> str:
    from spectre.web.app import templates as _app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(_app_templates.env.filters)
    return env.get_template("partials/decision_results.html").render(result=result)


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", html).split())


def _tags(html: str, figure: str) -> list[str]:
    return [t for t in re.findall(r"<[^>]+>", html) if f'data-figure="{figure}"' in t]


class TestTheBasesAreTyped:
    def test_every_outcome_figure_has_its_own_basis(self) -> None:
        """The sampled band, its spread, half-width, refusal and caveat, and the computed figure (SPC-120) qualify
        closest approach (SPC-112, SPC-115),
        the score's spread across samples qualifies the score (SPC-115), and custody's state at the scenario epoch
        qualifies custody (SPC-123); they are not figures."""
        about_closest_approach = {
            "ca_percentiles", "ca_std_km", "ca_samples", "ca_refusal", "ca_caveat", "ca_half_width_km", "ca_computed",
        }
        about_the_score = {"score_percentiles", "score_std"}
        about_custody = {"custody_state"}   # the status at the scenario epoch qualifies custody (SPC-123)
        qualifiers = about_closest_approach | about_the_score | about_custody
        assert qualifiers <= {f.name for f in fields(OutcomeMetrics)}
        figures = {f.name for f in fields(OutcomeMetrics)} - {"figure_bases"} - qualifiers
        assert figures == {f.name for f in fields(OutcomeBases)}

    def test_every_figure_has_an_operator_label(self) -> None:
        assert set(FIGURE_LABELS) == {f.name for f in fields(OutcomeBases)}

    def test_the_bases_are_exactly_lookup_sampled_computed(self) -> None:
        assert {b.value for b in Basis} == {"lookup", "sampled", "computed"}

    def test_weakest_orders_lookup_sampled_computed(self) -> None:
        assert weakest(Basis.COMPUTED, Basis.LOOKUP) is Basis.LOOKUP
        assert weakest(Basis.COMPUTED, Basis.SAMPLED) is Basis.SAMPLED
        assert weakest(Basis.COMPUTED) is Basis.COMPUTED
        with pytest.raises(ValueError, match="at least one basis"):
            weakest()


class TestTheScoreBasisIsDerived:
    def test_the_score_rests_only_on_the_figures_its_formula_uses(self) -> None:
        assert _SCORE_INPUTS == ("custody_maintained", "custody_gap_hours", "closest_approach_km", "delta_v_cost_km_s")
        computed = dict.fromkeys(_SCORE_INPUTS, Basis.COMPUTED)
        with_time = _bases(**computed, time_to_closest_hours=Basis.COMPUTED)
        without_time = _bases(**computed, time_to_closest_hours=Basis.LOOKUP)
        assert with_time.composite_score.kind is without_time.composite_score.kind

    def test_a_score_cannot_claim_more_than_its_figures(self) -> None:
        def build(**kinds: Basis) -> OutcomeBases:
            values = {name: FigureBasis(kinds.get(name, Basis.LOOKUP), "n") for name in _FIGURES}
            return OutcomeBases(**values, composite_score=FigureBasis(Basis.COMPUTED, "n"))

        with pytest.raises(ValueError, match="score"):
            build(**dict.fromkeys(set(_FIGURES) - {"closest_approach_km"}, Basis.COMPUTED))
        with pytest.raises(ValueError, match="score"):
            build(**dict.fromkeys(_FIGURES, Basis.COMPUTED))

    def test_the_score_stays_a_lookup_when_every_figure_is_computed(self) -> None:
        every = _bases(**dict.fromkeys(_FIGURES, Basis.COMPUTED))
        assert every.composite_score.kind is Basis.LOOKUP
        cell = _with_bases(evaluate_scenario(_scenario(1)).outcome_matrix[0][0], every)
        assert cell.modelled is True


class TestPhaseOneSaysWhichRule:
    def test_phase_one_every_figure_is_a_lookup_and_says_which_rule(self) -> None:
        result = evaluate_scenario(_scenario(2))
        for row in result.outcome_matrix:
            for cell in row:
                assert all(fb.kind is Basis.LOOKUP for _, fb in cell.figure_bases.items())
        bases = result.outcome_matrix[0][0].figure_bases
        assert "per adversary action type" in bases.closest_approach_km.note
        assert "0.4" in bases.time_to_closest_hours.note
        assert "0.05 km/s" in bases.delta_v_cost_km_s.note
        assert "confidence" in bases.custody_gap_hours.note
        assert "50,000 km" in bases.composite_score.note
        assert "0.1 km/s" in bases.composite_score.note
        assert "not the held, degraded or lost custody" in bases.custody_maintained.note

    def test_a_mixed_cell_names_its_computed_figure(self) -> None:
        cell = _mixed_result().outcome_matrix[0][1]
        assert cell.modelled is True
        assert "closest approach: computed" in cell.basis
        assert cell.basis != MODELLED_BASIS


class TestTheResultIsDerivedFromItsCells:
    def test_the_result_basis_is_derived_from_its_cells(self) -> None:
        mixed = _mixed_result()
        assert "Closest approach: lookup in 1 of 2 cells, computed in 1." in mixed.basis_lines
        assert "Custody: lookup in every cell." in mixed.basis_lines
        assert mixed.basis == MIXED_BASIS
        plain = evaluate_scenario(_scenario(2))
        assert plain.basis_lines == ("Every figure in every cell is a lookup.",)
        assert plain.basis == f"{MODELLED_BASIS} {BIND_TO_EARN}"

    def test_an_unrecorded_cell_reads_as_lookup(self) -> None:
        result = _unrecorded_result()
        assert result.modelled is True
        assert result.basis == f"{MODELLED_BASIS} {BIND_TO_EARN}"


class TestEachCellShowsItsOwnBasis:
    def test_each_shown_figure_carries_its_own_mark(self) -> None:
        result = evaluate_scenario(_scenario(2))
        html = _render(result)
        cells = sum(len(row) for row in result.outcome_matrix)
        for figure in ("closest_approach_km", "custody_maintained", "composite_score"):
            assert sum('data-basis="lookup"' in t for t in _tags(html, figure)) == cells, figure
        figure_tags = [t for t in re.findall(r"<[^>]+>", html) if re.search(r'class="figure"', t)]
        assert figure_tags
        assert all("data-basis=" in t for t in figure_tags)

    def test_a_computed_figure_reads_computed_in_its_own_cell_only(self) -> None:
        html = _render(_mixed_result())
        text = _text(html)
        assert text.count("km (computed)") == 1
        assert text.count("km (lookup)") == 1
        assert "Basis: Closest approach: lookup in 1 of 2 cells, computed in 1." in text
        assert 'class="modelled-badge"' in html
        assert "Heuristic ranking" in text
        assert "Custody here is a rule of thumb, not the held, degraded or lost custody shown on the sweep." in text
        assert " ".join(MODELLED_BASIS.split()) not in text

    def test_every_figure_computed_still_keeps_the_badge_and_heuristic_ranking(self) -> None:
        html = _render(_all_computed_result())
        assert 'class="modelled-badge"' in html
        assert "Heuristic ranking" in html
        assert any('data-basis="lookup"' in t for t in _tags(html, "composite_score"))
        assert "deterministic analytic model" not in html

    def test_computed_custody_is_not_called_a_rule_of_thumb(self) -> None:
        """Review finding: the custody sentence follows the custody figure's basis, not a fixed line."""
        text = _text(_render(_all_computed_result()))
        assert "Custody: computed in every cell." in text
        assert "Custody here is a rule of thumb" not in text

    def test_mixed_custody_is_still_called_a_rule_of_thumb(self) -> None:
        """Review finding 28: one lookup custody cell on screen keeps the rule-of-thumb line."""
        result = evaluate_scenario(_scenario(2))
        cell = result.outcome_matrix[0][1]
        # Custody and its gap rest on one basis (SPC-123), so both are computed in the second cell.
        result.outcome_matrix[0][1] = _with_bases(
            cell, _bases(custody_maintained=Basis.COMPUTED, custody_gap_hours=Basis.COMPUTED),
        )
        assert result.custody_rule_of_thumb is True
        assert "Custody: lookup in 1 of 2 cells, computed in 1." in result.basis_lines
        assert "Custody here is a rule of thumb" in _text(_render(result))

    def test_the_score_note_says_the_weights_are_rescaled(self) -> None:
        """Review finding: the route scales the panel weights to sum to one before scoring."""
        from spectre.domain.decision import LOOKUP_BASES

        assert "scaled to sum to one" in LOOKUP_BASES.composite_score.note

    def test_an_unrecorded_basis_reads_as_lookup_never_computed(self) -> None:
        html = _render(_unrecorded_result())
        assert "(lookup)" in html
        assert 'class="modelled-badge"' in html
        assert 'data-basis="computed"' not in html


def test_a_result_without_basis_lines_still_says_so() -> None:
    """The banner falls back to "Basis not recorded" rather than going silent."""
    result: Any = SimpleNamespace(**{f.name: getattr(evaluate_scenario(_scenario(1)), f.name)
                                     for f in fields(ScenarioResult)})
    text = _text(_render(result))
    assert "Basis not recorded; read every figure as a lookup." in text
    assert "modelled estimate, not a computed solution" in text
