"""A sampled cell shows its band, its distribution on hover and the spread of its score (SPC-115).

Each sampled cell carries the half-width its percentiles are known to, and
the P5, P50, P95 and 1-sigma spread of the composite score across its
samples. The page shows the distribution in the band's title, an
Uncertainty column with one sentence per row, and the score spread on each
ranking card. A lookup cell shows no band and says it is a lookup.

Every test injects the fake sampler of test_decision_sampled, so none runs a
propagator.
"""

from __future__ import annotations

import dataclasses
import html
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from spectre.domain.decision import (
    _ROW_ELSET,
    LOOKUP_CELL_TITLE,
    SCORE_SPREAD_NOTE,
    OutcomeMetrics,
    ScenarioResult,
    evaluate_scenario,
)
from spectre.domain.decision_figures import ElsetErrorAt
from tests.unit.test_decision_figure_basis import _render, _text
from tests.unit.test_decision_sampled import _LOW, _REST, _bound, _evasive, _Fake, _metrics, _scenario

_DISTRIBUTION = (
    "Distribution of 50 sampled misses: P5 3.0 km, P50 8.0 km, P95 20.0 km; spread 5.0 km (1 sigma); each "
    "percentile known to within 0.40 km (95 % bootstrap). Not in this spread: element-set error, which the sweep "
    "takes as 1 km at epoch plus 2 km a day in LEO and 2 km plus 1 km a day at GEO, and the hypothesis being wrong."
)
_MISSES = np.array([miss for miss, _tca in (*_LOW, *_REST)])


def _ca_term(miss_km: float) -> float:
    """The closest-approach term at the default 10 km keep-out (SPC-191): 1 at or inside it, then
    ln(50,000 / miss) / ln 5,000, worked here apart from the engine's own function."""
    return 1.0 if miss_km <= 10.0 else float(np.log(50_000.0 / miss_km) / np.log(5_000.0))


#: The closest-approach term of each fake sample: 9 of the 50 misses are at or inside 10 km and score 1.
_TERMS = np.array([_ca_term(m) for m in _MISSES])


@pytest.fixture(scope="module")
def sampled() -> ScenarioResult:
    return evaluate_scenario(_bound(), sampler=_Fake())


@pytest.fixture(scope="module")
def mixed() -> ScenarioResult:
    """Row 0 sampled, row 1 refused (10 samples are too few), rows 2 and 3 computed (SPC-120; lookups before)."""
    return evaluate_scenario(_bound({0: _evasive(), 1: _evasive(10)}), sampler=_Fake())


def _page(result: Any) -> str:
    return html.unescape(_text(_render(result)))


def _titles(page_html: str) -> list[str]:
    return [html.unescape(t) for t in re.findall(r'title="([^"]*)"', page_html)]


class TestTheCellCarriesItsSpread:
    def test_a_sampled_cell_has_score_percentiles_spread_and_half_width(self, sampled: ScenarioResult) -> None:
        """U1."""
        cell = sampled.outcome_matrix[0][0]
        assert cell.ca_half_width_km == 0.4
        assert cell.score_percentiles is not None
        assert tuple(sorted(cell.score_percentiles)) == (5, 50, 95)
        p = cell.score_percentiles
        assert p[5] <= p[50] <= p[95]
        assert cell.score_std is not None and cell.score_std > 0.0

    def test_the_score_spread_is_the_weight_times_the_spread_of_the_closest_approach_term(
        self, sampled: ScenarioResult,
    ) -> None:
        """U2: only the miss differs between samples, so the score's spread is w times its term's (SPC-191).

        0.25 x the 1-sigma spread of the 50 terms, 9 of them 1 and the rest ln(50,000 / miss) / ln 5,000, is 0.0092.
        """
        w = sampled.scenario.w_closest_approach
        assert w * float(np.std(_TERMS)) == pytest.approx(0.0092, abs=5e-5)
        for cell in sampled.outcome_matrix[0]:
            assert cell.score_std == pytest.approx(w * float(np.std(_TERMS)), rel=1e-12)

    def test_the_score_percentiles_are_the_samples_percentiles(self, sampled: ScenarioResult) -> None:
        """The score is w times the closest-approach term plus figures every sample shares, so score P_k less w x
        the terms' P_k is the same constant for k of 5, 50 and 95: each hover shows that percentile and not another.
        """
        w = sampled.scenario.w_closest_approach
        term = {k: float(np.percentile(_TERMS, k)) for k in (5, 50, 95)}
        assert term[95] - term[5] > 0.1, "the fake's misses must spread for this test to tell percentiles apart"
        for cell in sampled.outcome_matrix[0]:
            p = cell.score_percentiles
            assert p is not None
            base = [p[k] - w * term[k] for k in (5, 50, 95)]
            assert base == pytest.approx([base[1]] * 3, abs=1e-12)

    @pytest.mark.parametrize(
        "changes",
        [{"score_std": 0.1},{"ca_half_width_km": 0.4}, {"score_percentiles": {5: 0.1, 50: 0.2, 95: 0.3}}],
        ids=["score spread", "half-width", "score percentiles"],
    )
    def test_a_lookup_cell_cannot_carry_a_spread(self, changes: dict[str, Any]) -> None:
        """U3."""
        lookup = evaluate_scenario(_scenario()).outcome_matrix[0][0]
        with pytest.raises(ValueError, match="sampled"):
            OutcomeMetrics(**{**{f.name: getattr(lookup, f.name) for f in dataclasses.fields(lookup)}, **changes})

    def test_a_sampled_cell_without_its_score_spread_is_refused(self) -> None:
        with pytest.raises(ValueError, match="sampled"):
            _metrics(score_std=None)


class TestThePageShowsTheSpread:
    def test_the_band_carries_the_distribution_in_its_title(self, sampled: ScenarioResult) -> None:
        """U4."""
        assert sampled.outcome_matrix[0][0].ca_distribution == _DISTRIBUTION
        assert _titles(_render(sampled)).count(_DISTRIBUTION) == 4

    def test_a_lookup_cell_says_lookup_and_shows_no_band(self) -> None:
        """U5."""
        assert LOOKUP_CELL_TITLE == "Lookup: a fixed figure, with no distribution."
        page_html = _render(evaluate_scenario(_scenario()))
        assert _titles(page_html).count(LOOKUP_CELL_TITLE) == 16
        assert "P5" not in page_html

    def test_the_uncertainty_column_has_a_sentence_per_row(self, mixed: ScenarioResult) -> None:
        """U6."""
        page_html = _render(mixed)
        header = re.search(r"<thead>(.*?)</thead>", page_html, re.S)
        assert header is not None
        assert len(re.findall(r"<th\b", header.group(1))) == len(mixed.scenario.friendly_responses) + 2
        assert "Uncertainty" in header.group(1)
        cells = [html.unescape(_text(c)) for c in re.findall(r'<td class="row-uncertainty"[^>]*>(.*?)</td>',
                                                            page_html, re.S)]
        assert cells == [
            "Closest approach spread 5.0 km (1 sigma) over 50 samples; P5, P50 and P95 known to within 0.40 km. "
            "Score spread across samples 0.0092.",
            "Not sampled, so no spread: the cells say why.",
            *(("Computed by SGP4 with no burn: one figure, no spread, with element-set error as a band beside it; "
               "the score reads its lower edge. " + _ROW_ELSET.format(**cast("ElsetErrorAt", row[0].ca_elset_error).words()))
              for row in mixed.outcome_matrix[2:]),
        ]
        assert list(mixed.row_uncertainty) == cells

    def test_each_ranking_card_shows_the_score_spread(self, mixed: ScenarioResult) -> None:
        """U7."""
        text = _page(mixed)
        assert text.count("Score spread 0.0092 (1 sigma, 50 samples)") == 4   # U2's 0.0092
        assert text.count("Score spread: lookup, none computed") == 12
        spread = mixed.outcome_matrix[0][0].score_spread_text
        assert spread == "Score spread 0.0092 (1 sigma, 50 samples)"
        ranked = mixed.ranked_cells[0]
        assert [(r.id, s) for r, s, _cell in ranked] == [(r.id, s) for r, s in mixed.ranked_per_adversary[0]]
        assert all(cell is mixed.outcome_matrix[0][mixed.scenario.friendly_responses.index(r)]
                   for r, _s, cell in ranked)
        p = mixed.outcome_matrix[0][0].score_percentiles
        assert p is not None
        expected = f"Score P5 {p[5]:.4f}, P50 {p[50]:.4f}, P95 {p[95]:.4f} across samples; the score's basis is lookup."
        assert _titles(_render(mixed)).count(expected) == 1

    def test_a_wide_score_spread_is_shown_to_four_places(self) -> None:
        cell = _metrics(score_std=0.01234)
        assert cell.score_spread_text == "Score spread 0.0123 (1 sigma, 50 samples)"

    @pytest.mark.parametrize(
        ("std", "shown"),
        [(0.00004, "under 0.0001"), (0.00006, "0.0001"), (0.0003, "0.0003"), (0.00049, "0.0005")],
    )
    def test_only_a_spread_that_would_print_as_zero_is_shown_as_under_0_0001(self, std: float, shown: str) -> None:
        """The line is where four places round to 0.0000: 0.00004 would; 0.00006 and 0.0003 would not."""
        assert _metrics(score_std=std).score_spread_text == f"Score spread {shown} (1 sigma, 50 samples)"

    def test_the_spread_note_shows_once_when_any_cell_is_sampled(self, sampled: ScenarioResult) -> None:
        """U8."""
        assert SCORE_SPREAD_NOTE == (
            "Score spread is the 1-sigma spread of the composite score across samples, from the closest-approach term "
            "alone. Every miss at or inside the keep-out distance scores the full penalty, so a band inside it shows "
            "no spread however wide it is; a small spread does not mean the outcome is certain. Our response is not "
            "applied to the blue orbit, so within a sampled row the ranking is decided by lookup figures."
        )
        assert _page(sampled).count(SCORE_SPREAD_NOTE) == 1
        assert SCORE_SPREAD_NOTE not in _page(evaluate_scenario(_scenario()))

    def test_the_scenario_epoch_is_on_screen(self) -> None:
        """U9."""
        scenario = _scenario()
        scenario.epoch_utc = datetime(2026, 3, 1, 9, 5, tzinfo=UTC)
        text = _page(evaluate_scenario(scenario))
        assert "Scenario epoch 2026-03-01 09:05 UTC; times to closest approach count from it." in text

    def test_an_older_result_renders_and_says_lookup(self) -> None:
        """U10: a result object from before SPC-115, without its fields, renders under StrictUndefined."""
        result = evaluate_scenario(_scenario())
        old_fields = ("custody_maintained", "custody_gap_hours", "closest_approach_km", "time_to_closest_hours",
                      "delta_v_cost_km_s", "composite_score", "figure_bases", "ca_percentiles", "ca_std_km",
                      "ca_samples", "ca_refusal", "ca_caveat")
        old = SimpleNamespace(
            scenario=result.scenario, ranked_per_adversary=result.ranked_per_adversary,
            robust_best_response=result.robust_best_response, robust_strategy=result.robust_strategy,
            computation_time_s=result.computation_time_s,
            outcome_matrix=[[SimpleNamespace(**{n: getattr(c, n) for n in old_fields}) for c in row]
                            for row in result.outcome_matrix],
        )
        text = _page(old)
        assert text.count("Lookup: no spread computed.") == 4
        assert "Score spread: lookup, none computed" in text


@pytest.mark.parametrize(("horizon", "shown"), [(9.4, "9.4h horizon"), (72.0, "72h horizon"), (0.3, "0.3h horizon")])
def test_the_footer_shows_the_horizon_as_entered(horizon: float, shown: str) -> None:
    """The panel takes tenths of an hour, so the footer must not cut 9.4 h to 9 h."""
    scenario = _scenario(horizon_hours=horizon)
    assert shown in " ".join(_page(evaluate_scenario(scenario)).split())
