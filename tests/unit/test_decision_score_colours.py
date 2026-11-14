"""A composite score carries no colour band (SPC-208, evaluation F-18).

The results coloured each composite score green below 0.25, amber below 0.50 and red above, in the outcome matrix
and in the ranking cards, with no source for the thresholds: colour implied a safety judgement the score has not
earned. No sourced thresholds exist, so the lead ruled to remove the bands. The number stays, to three places, with
its words: the matrix's heading says lower is better and each score its basis. A response marked not permitted is
still greyed (SPC-195): that says it is no candidate, not how good its score is.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    evaluate_scenario,
)

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_RESULTS = _TEMPLATE_DIR / "partials" / "decision_results.html"
#: The band colours the results used: green, amber and red.
_BANDS = ("#22c55e", "#f59e0b", "#ef4444")
#: One score in each of the old bands, and one on each boundary.
_SCORES = (0.1, 0.25, 0.4, 0.5, 0.9)


def _render(result: ScenarioResult) -> str:
    from spectre.web.app import templates as _app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(_app_templates.env.filters)
    return env.get_template("partials/decision_results.html").render(result=result)


def _response(j: int, *, vetoed: bool) -> FriendlyResponse:
    reason = "Breaks the rules of engagement." if vetoed else ""
    return FriendlyResponse(
        f"F{j}", f"Response {j}", ActionType.NO_ACTION, 0.1 * j, 0.5, 1.0, vetoed=vetoed, veto_reason=reason,
    )


def _result(*, vetoed: bool = False) -> ScenarioResult:
    """One adversary row against five responses whose scores are set to _SCORES, one in each old band; with
    *vetoed*, the last response is marked not permitted."""
    scenario = Scenario(
        name="Bands", epoch_utc=datetime(2026, 4, 10, tzinfo=UTC),
        adversary_actions=[AdversaryAction("A0", "Approach", ActionType.MANOEUVRE, 1.0, 0.7)],
        friendly_responses=[_response(j, vetoed=vetoed and j == len(_SCORES) - 1) for j in range(len(_SCORES))],
    )
    result = evaluate_scenario(scenario)
    cells = zip(result.outcome_matrix[0], _SCORES, strict=True)
    row = [dataclasses.replace(cell, composite_score=score) for cell, score in cells]
    pairs = zip(result.scenario.friendly_responses, _SCORES, strict=True)
    ranked = sorted(pairs, key=lambda pair: (pair[0].vetoed, pair[1]))
    return dataclasses.replace(result, outcome_matrix=[row], ranked_per_adversary=[ranked])


def _styles(html: str, marker: str) -> list[str]:
    """The style attribute of every element carrying *marker*."""
    return re.findall(rf'<div[^>]*{marker}[^>]*style="([^"]*)"', html, flags=re.DOTALL)


def _colour(style: str) -> str:
    found = re.search(r"(?:^|[;\s])color:([^;]+)", style)
    return "" if found is None else found.group(1).strip()


def _scores(html: str, marker: str) -> list[str]:
    """The text of every element carrying *marker*."""
    found = re.findall(rf"<div[^>]*{marker}[^>]*>([^<]*)</div>", html, flags=re.DOTALL)
    return [" ".join(text.split()) for text in found]


class TestNoScoreIsColouredByBand:
    def test_every_score_in_the_matrix_is_the_same_colour_whatever_its_value(self) -> None:
        styles = _styles(_render(_result()), 'data-figure="composite_score"')
        assert len(styles) == len(_SCORES)
        assert {_colour(style) for style in styles} == {"var(--text-primary)"}

    def test_every_score_on_the_ranking_cards_is_the_same_colour_whatever_its_value(self) -> None:
        styles = _styles(_render(_result()), 'class="ranked-score"')
        assert len(styles) == len(_SCORES)
        assert {_colour(style) for style in styles} == {"var(--text-primary)"}

    def test_no_score_element_carries_a_band_colour(self) -> None:
        html = _render(_result())
        styles = (*_styles(html, 'data-figure="composite_score"'), *_styles(html, 'class="ranked-score"'))
        assert len(styles) == 2 * len(_SCORES)
        assert [band for style in styles for band in _BANDS if band in style] == []

    def test_the_template_holds_no_band_threshold(self) -> None:
        text = _RESULTS.read_text(encoding="utf-8")
        assert "green < 0.25" not in text
        assert "composite_score < 0.25" not in text
        assert "score < 0.25" not in text
        assert "score < 0.5" not in text


class TestTheNumberAndItsWordsStay:
    def test_each_score_is_shown_to_three_places_in_the_matrix_and_on_the_cards(self) -> None:
        html = _render(_result())
        shown = [f"{score:.3f}" for score in _SCORES]
        assert _scores(html, 'data-figure="composite_score"') == shown
        assert _scores(html, 'class="ranked-score"') == shown

    def test_the_matrix_still_says_lower_is_better_and_each_score_its_basis(self) -> None:
        html = _render(_result())
        assert "(lower = better for friendly)" in html
        assert html.count('data-figure="composite_score"') == len(_SCORES)
        assert len(re.findall(r'data-figure="composite_score"\s+data-basis="lookup"', html)) == len(_SCORES)

    def test_a_response_not_permitted_is_still_greyed(self) -> None:
        html = _render(_result(vetoed=True))
        matrix = _styles(html, 'data-figure="composite_score"')
        cards = _styles(html, 'class="ranked-score"')
        assert [_colour(style) for style in matrix] == ["var(--text-primary)"] * 4 + ["var(--text-dim)"]
        assert [_colour(style) for style in cards] == ["var(--text-primary)"] * 4 + ["var(--text-dim)"]


class TestTheCardsSayWhatTheScoreIs:
    """Review of 0.38.0 (SPC-208): the ranking cards say, as the matrix does, that lower is better and what the score
    rests on."""

    def test_the_rankings_carry_one_label_with_the_words_and_the_basis(self) -> None:
        html = _render(_result())
        start = html.index("Ranked Responses per Adversary Action")
        labels = re.findall(r'<p class="ranked-score-note"[^>]*>([^<]*)</p>', html[start:])
        assert [" ".join(label.split()) for label in labels] == [
            "Each card's score is the composite score, lower = better for friendly, a lookup, as in the matrix."
        ]
