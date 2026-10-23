"""The Decision Engine must say what it is: a modelled estimate.

Its outcome metrics are Phase 1 lookup constants and weights, not propagation
(closest approach of 200, 3,000, 5,000 or 10,000 km scaled by cost; time to
approach of 0.4 x horizon). They were presented under a "Robust
Recommendation" banner with nothing in the data or the page marking them as
modelled (audit F-S05-02, and the July 2026 prior P2). The selector labelled
"Maximin" minimised the best-case cost, which is the optimistic minimin rule,
not the cautious maximin one (audit F-S05-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeMetrics,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"


def _metrics(score: float) -> OutcomeMetrics:
    return OutcomeMetrics(
        custody_maintained=True, custody_gap_hours=0.0, closest_approach_km=1000.0,
        time_to_closest_hours=1.0, delta_v_cost_km_s=0.0, composite_score=score,
    )


def _two_by_two() -> tuple[Scenario, list[list[OutcomeMetrics]]]:
    """Response A risks 0.9 or 0.1; response B scores 0.5 whatever happens."""
    adversary = [
        AdversaryAction(id=f"A{i}", name=f"A{i}", action_type=ActionType.MANOEUVRE, probability=p, confidence=0.8)
        for i, p in ((1, 0.2), (2, 0.8))
    ]
    friendly = [
        FriendlyResponse(id=r, name=r, action_type=ActionType.MANOEUVRE, cost=0.3, reversibility=0.5,
                         time_to_execute_hours=6.0)
        for r in ("A", "B")
    ]
    scenario = Scenario(name="t", epoch_utc=datetime(2026, 4, 10, tzinfo=UTC),
                        adversary_actions=adversary, friendly_responses=friendly)
    matrix = [[_metrics(0.9), _metrics(0.5)], [_metrics(0.1), _metrics(0.5)]]
    return scenario, matrix


class TestTheSelectorsDoWhatTheirNamesSay:
    def test_minimax_takes_the_best_worst_case(self) -> None:
        scenario, matrix = _two_by_two()
        assert find_robust_response(scenario, matrix, SelectorStrategy.MINIMAX).id == "B"

    def test_minimin_takes_the_best_best_case(self) -> None:
        scenario, matrix = _two_by_two()
        assert find_robust_response(scenario, matrix, SelectorStrategy.MINIMIN).id == "A"

    def test_expected_value_weighs_by_probability(self) -> None:
        # A: 0.2*0.9 + 0.8*0.1 = 0.26; B: 0.5.
        scenario, matrix = _two_by_two()
        assert find_robust_response(scenario, matrix, SelectorStrategy.EXPECTED_VALUE).id == "A"

    def test_no_strategy_is_called_maximin(self) -> None:
        assert "maximin" not in {s.value for s in SelectorStrategy}


class TestTheResultSaysItIsModelled:
    def test_every_metric_and_the_result_carry_the_flag(self) -> None:
        scenario, _ = _two_by_two()
        result = evaluate_scenario(scenario)
        assert result.modelled is True
        assert "lookup" in result.basis.lower()
        assert all(cell.modelled for row in result.outcome_matrix for cell in row)


def _render(name: str, context: dict[str, Any]) -> str:
    from spectre.web.app import templates as _app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(_app_templates.env.filters)
    return env.get_template(name).render(**context)


class TestTheOperatorIsTold:
    def test_the_results_banner_names_a_modelled_estimate(self) -> None:
        scenario, _ = _two_by_two()
        html = _render("partials/decision_results.html", {"result": evaluate_scenario(scenario)})
        assert "Modelled estimate, not a computed solution" in html
        assert "Robust Recommendation" not in html
        assert "(model)" in html, "the closest-approach figure in each cell must be marked as modelled"

    def test_the_panel_offers_no_maximin(self) -> None:
        panel = (_TEMPLATE_DIR / "partials" / "decision_panel.html").read_text(encoding="utf-8")
        assert 'value="maximin"' not in panel
        assert "Minimin" in panel
