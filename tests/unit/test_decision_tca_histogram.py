"""A sampled cell's times of closest approach as a histogram (SPC-124).

Each sample's TCA carries the element sets' position error over that sample's closing speed (SPC-118), so a bin
narrower than that would draw a shape the samples cannot earn. The bin width is the smallest of 1, 2, 5, 10, 15
and 30 s, 1, 2, 5, 10, 15 and 30 min, and 1, 2, 3, 6 and 12 h that is at least the wider of a twentieth of the
range and the median sample's sigma. A sample whose smallest separation is at an edge of the search is not an
encounter, so it is counted in the caption, not drawn. The chart's data is numbers only, so nothing the operator
typed reaches the script; the page offers the histogram only for a sampled cell, with a labelled select, a canvas
named for a screen reader and the same figures as a table, and loads no script from a CDN.
"""

from __future__ import annotations

import dataclasses
import html
import json
import re
from itertools import pairwise
from typing import Any

import pytest

from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.monte_carlo import SeparationSeries, SeparationWindow
from spectre.domain.decision import OutcomeMetrics, ScenarioResult, evaluate_scenario
from spectre.domain.decision_figures import HISTOGRAM_CAPTION, TcaHistogram, tca_histogram
from tests.unit.test_decision_computed import _computed, _metrics
from tests.unit.test_decision_figure_basis import _render
from tests.unit.test_decision_sampled import _bound, _Fake

_PLANE_CHANGE_KM_S = 0.394


def _spread(n: int, first_h: float, span_s: float) -> list[float]:
    return [first_h + span_s * k / (n - 1) / 3600.0 for k in range(n)]


class TestTheBins:
    def test_bins_are_no_finer_than_the_tca_sigma(self) -> None:
        """57: TCAs spread over 2 s with a sigma of 3.7 s give 5 s bins, not a twentieth of 2 s."""
        found = tca_histogram(_spread(50, 0.39, 2.0), [3.7] * 50, n_closing=0, n_opening=0)
        assert found is not None
        assert found.bin_width_s == 5.0
        assert found.median_sigma_s == pytest.approx(3.7)
        assert len(found.counts) in (1, 2)

    @pytest.mark.parametrize(
        ("span_s", "sigma_s", "width_s"),
        [
            (1200.0, 1.0, 60.0),          # a twentieth of 20 min is 1 min
            (1200.0, 61.0, 120.0),        # the sigma rules: 2 min
            (108_000.0, 4259.5, 7200.0),  # GEO: 30 h over 20 is 1.5 h, so 2 h
            (60.0, 50_000.0, 86_400.0),   # wider than the ladder: whole 12 h steps
            (0.0, 0.2, 1.0),              # one TCA, a sigma under 1 s
        ],
    )
    def test_the_width_is_the_smallest_on_the_ladder_that_is_wide_enough(
        self, span_s: float, sigma_s: float, width_s: float,
    ) -> None:
        found = tca_histogram(_spread(40, 1.0, span_s), [sigma_s] * 40, n_closing=0, n_opening=0)
        assert found is not None
        assert found.bin_width_s == width_s

    def test_every_shown_sample_is_in_a_bar(self) -> None:
        found = tca_histogram(_spread(47, 0.2, 1500.0), [30.0] * 47, n_closing=2, n_opening=1)
        assert found is not None
        assert sum(found.counts) == found.n_shown == 47
        assert len(found.edges_h) == len(found.counts) + 1
        assert found.edges_h[0] <= 0.2 and found.edges_h[-1] >= 0.2 + 1500.0 / 3600.0
        assert all(b - a == pytest.approx(found.bin_width_s / 3600.0) for a, b in pairwise(found.edges_h))

    def test_no_histogram_without_a_shown_sample_or_a_sigma(self) -> None:
        assert tca_histogram([], [], n_closing=3, n_opening=0) is None
        assert tca_histogram([0.5, 0.6], [None, None], n_closing=0, n_opening=0) is None

    def test_the_floor_is_the_median_sigma_not_the_least_or_the_most(self) -> None:
        """Sigmas of 1, 1, 100, 200 and 5,000 s over 60 s of TCAs: the median, 100 s, gives 2 min bins; the least
        would give 5 s and the most 2 h."""
        found = tca_histogram(_spread(5, 1.0, 60.0), [1.0, 1.0, 100.0, 200.0, 5000.0], n_closing=0, n_opening=0)
        assert found is not None
        assert found.median_sigma_s == 100.0
        assert found.bin_width_s == 120.0

    def test_the_edges_are_whole_multiples_of_the_width(self) -> None:
        """The first TCA is 7 s past a whole 2 min, so the first edge is that whole 2 min, not the TCA."""
        first_h = (3600.0 + 120.0 * 5 + 7.0) / 3600.0
        found = tca_histogram(_spread(30, first_h, 1500.0), [30.0] * 30, n_closing=0, n_opening=0)
        assert found is not None and found.bin_width_s == 120.0
        edges_s = [round(e * 3600.0, 6) for e in found.edges_h]
        assert edges_s[0] == 3600.0 + 120.0 * 5
        assert all(e % 120.0 == 0.0 for e in edges_s)


class TestTheCaption:
    def test_edge_samples_are_counted_in_the_caption_not_the_bars(self) -> None:
        """58."""
        found = tca_histogram(_spread(47, 0.2, 1500.0), [30.0] * 47, n_closing=2, n_opening=1)
        assert found is not None
        assert found.caption == (
            "Times of closest approach of 47 of 50 samples, in bins of 2 min, no narrower than ± 30 s, the median "
            "uncertainty of the drawn samples' TCAs from element-set error; every drawn sample's uncertainty is "
            "within a bin. Not shown: 2 still closing when the search ended and 1 already opening when it began, "
            "whose smallest separation is at an edge, not an encounter, and 0 closing too slowly to fix a time "
            "within the span searched."
        )
        assert HISTOGRAM_CAPTION.startswith("Times of closest approach of {n} of {total} samples")

    def test_a_sample_known_less_well_than_a_bin_is_said_so(self) -> None:
        """The median floors the bins, so up to half the drawn samples are known less well than a bin; the caption
        says how many, and never that each sample is known to the median."""
        found = tca_histogram([1.0, 1.01, 1.02, 5.0], [10.0, 10.0, 10.0, 40_000.0], n_closing=0, n_opening=0)
        assert found is not None
        assert found.bin_width_s == 900.0 and found.n_wider == 1
        assert "no narrower than ± 10 s, the median uncertainty of the drawn samples' TCAs" in found.caption
        assert "1 drawn sample's uncertainty is wider than a bin." in found.caption
        assert "each sample" not in found.caption

    def test_samples_wider_than_a_bin_are_counted_in_the_plural(self) -> None:
        found = tca_histogram([1.0, 1.01, 1.02, 1.03, 5.0], [10.0, 10.0, 10.0, 4000.0, 40_000.0],
                              n_closing=0, n_opening=0)
        assert found is not None
        assert "2 drawn samples' uncertainties are wider than a bin." in found.caption

    def test_a_sample_whose_time_cannot_be_fixed_is_counted_not_drawn(self) -> None:
        """A sample closing too slowly for its sigma to fit the span has no time to draw."""
        found = tca_histogram([1.0, 1.1, 2.0], [30.0, 30.0, None], n_closing=0, n_opening=0)
        assert found is not None
        assert (found.n_shown, found.n_unfixed, sum(found.counts)) == (2, 1, 2)
        assert found.caption.startswith("Times of closest approach of 2 of 3 samples")
        assert found.caption.endswith("and 1 closing too slowly to fix a time within the span searched.")

    @pytest.mark.parametrize(("width_s", "label"), [(5.0, "5 s"), (900.0, "15 min"), (10_800.0, "3 h")])
    def test_the_bin_is_named_at_its_scale(self, width_s: float, label: str) -> None:
        found = TcaHistogram(width_s, (0.0, width_s / 3600.0), (1,), 1, 0, 0, 1.0)
        assert f"in bins of {label}," in found.caption


class TestTheChartData:
    def test_the_chart_data_holds_numbers_only(self) -> None:
        """59, the domain's half: no string reaches the script."""
        found = tca_histogram(_spread(50, 0.39, 2.0), [3.7] * 50, n_closing=0, n_opening=0)
        assert found is not None
        data = found.chart_data

        def numbers(value: Any) -> bool:
            if isinstance(value, (list, tuple)):
                return all(numbers(v) for v in value)
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        assert all(numbers(v) for v in data.values())
        assert data["counts"] == list(found.counts)
        assert data["edges_h"] == list(found.edges_h)
        assert "decimals" not in data, "the chart labels its bars with the table's exact edges, not rounded hours"

    def test_quarter_hour_edges_are_stated_not_rounded(self) -> None:
        """Samples known to 4 s in 15 min bins: the edges read 0:00, 0:15, 0:30 and 0:45, not 0.0, 0.2, 0.5 and 0.8,
        which moved them by up to 3 min."""
        found = tca_histogram([0.1 + 5.0 * k / 39 for k in range(40)], [4.0] * 40, n_closing=0, n_opening=0)
        assert found is not None and found.bin_width_s == 900.0
        assert [(lo, hi) for lo, hi, _n in found.rows[:3]] == [("0:00", "0:15"), ("0:15", "0:30"), ("0:30", "0:45")]
        assert found.clock_unit == "h:mm"

    @pytest.mark.parametrize(
        ("width_s", "unit"),
        [(1.0, "h:mm:ss"), (5.0, "h:mm:ss"), (30.0, "h:mm:ss"), (60.0, "h:mm"), (600.0, "h:mm"), (900.0, "h:mm"),
         (3600.0, "h:mm"), (10_800.0, "h:mm"), (43_200.0, "h:mm"), (86_400.0, "h:mm")],
    )
    def test_every_edge_reads_back_exactly(self, width_s: float, unit: str) -> None:
        """Edges are whole multiples of the width, so in hours, minutes and seconds they are exact: rounding moves
        none of them at all."""
        edges_s = [width_s * (7 + k) for k in range(4)]
        found = TcaHistogram(width_s, tuple(e / 3600.0 for e in edges_s), (1, 2, 3), 6, 0, 0, 1.0)
        assert found.clock_unit == unit
        stated = [lo for lo, _hi, _n in found.rows] + [found.rows[-1][1]]
        assert [_clock_s(text) for text in stated] == edges_s
        assert [n for _lo, _hi, n in found.rows] == [1, 2, 3]


# ── The cell and the page ──

class _WithSpeeds(_Fake):
    """The fake series, each sample closing at the plane change's 394 m/s."""

    def __call__(self, *args: Any, **kwargs: Any) -> SeparationSeries:
        series = super().__call__(*args, **kwargs)
        return dataclasses.replace(series, closing_speeds_km_s=(_PLANE_CHANGE_KM_S,) * len(series.approaches))


@pytest.fixture(scope="module")
def sampled() -> ScenarioResult:
    return evaluate_scenario(_bound(), sampler=_WithSpeeds())


def _sampled_cells(result: ScenarioResult) -> list[tuple[int, int, OutcomeMetrics]]:
    return [
        (i, j, cell) for i, row in enumerate(result.outcome_matrix) for j, cell in enumerate(row)
        if cell.ca_percentiles is not None
    ]


class TestTheCell:
    def test_a_sampled_cell_carries_its_histogram(self, sampled: ScenarioResult) -> None:
        cells = _sampled_cells(sampled)
        assert len(cells) == 4
        for _i, _j, cell in cells:
            found = cell.tca_histogram
            assert found is not None
            assert found.n_shown == 50 and sum(found.counts) == 50
            assert found.median_sigma_s == pytest.approx(cell.tca_uncertainty.sigma_s, rel=0.05)  # type: ignore[union-attr]

    def test_a_computed_or_lookup_cell_has_none(self, sampled: ScenarioResult) -> None:
        others = [c for row in sampled.outcome_matrix for c in row if c.ca_percentiles is None]
        assert others and all(c.tca_histogram is None for c in others)

    def test_a_series_with_no_closing_speeds_draws_none(self) -> None:
        result = evaluate_scenario(_bound(), sampler=_Fake())
        assert all(c.tca_histogram is None for _i, _j, c in _sampled_cells(result))

    def test_edge_samples_are_left_out_of_the_bars(self) -> None:
        fake = _WithSpeeds()

        def sampler(hypothesis: Any, blue: Any, window: SeparationWindow) -> SeparationSeries:
            out = fake(hypothesis, blue, window)
            edges = (
                ClosestApproach(9.0, window.span_s, True), ClosestApproach(9.2, window.span_s, True),
                ClosestApproach(9.5, 0.0, True),
            )
            return dataclasses.replace(out, approaches=(*out.approaches[:-3], *edges))

        result = evaluate_scenario(_bound(), sampler=sampler)
        found = _sampled_cells(result)[0][2].tca_histogram
        assert found is not None
        assert (found.n_shown, found.n_closing_at_end, found.n_opening_at_start) == (47, 2, 1)
        assert "Not shown: 2 still closing when the search ended and 1 already opening when it began" in found.caption

    def test_a_sample_closing_too_slowly_is_counted_not_drawn(self) -> None:
        """Through the cell: one sample closing at 0 km/s has no sigma, so no time to draw."""
        fake = _WithSpeeds()

        def sampler(hypothesis: Any, blue: Any, window: SeparationWindow) -> SeparationSeries:
            out = fake(hypothesis, blue, window)
            return dataclasses.replace(out, closing_speeds_km_s=(0.0, *out.closing_speeds_km_s[1:]))

        result = evaluate_scenario(_bound(), sampler=sampler)
        found = _sampled_cells(result)[0][2].tca_histogram
        assert found is not None
        assert (found.n_shown, found.n_unfixed, sum(found.counts)) == (49, 1, 49)

    def test_a_computed_cell_with_a_histogram_is_refused(self) -> None:
        found = tca_histogram([0.39], [3.7], n_closing=0, n_opening=0)
        with pytest.raises(ValueError, match="tca_histogram"):
            _metrics(tca_histogram=found)


def _histogram_panel(page: str) -> str:
    start = page.index('<section class="tca-histogram"')
    return page[start:page.index("</section>", start)]


class TestThePage:
    def test_the_histogram_is_offered_only_for_sampled_cells(self, sampled: ScenarioResult) -> None:
        """56: one option and one JSON block per sampled cell."""
        page = _render(sampled)
        panel = _histogram_panel(page)
        cells = _sampled_cells(sampled)
        assert panel.count("<option ") == len(cells) == 4
        assert len(re.findall(r'<script type="application/json"', panel)) == len(cells)
        for i, j, cell in cells:
            name = f"{sampled.scenario.adversary_actions[i].name} against {sampled.scenario.friendly_responses[j].name}"
            assert f'value="{i}-{j}"' in panel and name in panel
            block = re.search(rf'<script type="application/json" id="tca-hist-data-{i}-{j}">(.*?)</script>', panel, re.S)
            assert block is not None
            assert json.loads(block.group(1)) == cast_histogram(cell).chart_data
            assert cast_histogram(cell).caption in html.unescape(" ".join(panel.split()))

    def test_the_controls_are_labelled(self, sampled: ScenarioResult) -> None:
        """49, in the results: the select is tied to its label, the canvas named, the figures a table too."""
        panel = _histogram_panel(_render(sampled))
        units = {cast_histogram(cell).clock_unit for _i, _j, cell in _sampled_cells(sampled)}
        assert units == {"h:mm"}
        assert '<label for="tca-hist-cell"' in panel and ">Sampled cell<" in panel
        assert 'id="tca-hist-cell"' in panel
        assert 'aria-label="Histogram of sampled times of closest approach for the selected cell"' in panel
        assert "<summary>Histogram as a table</summary>" in panel
        for heading in ("TCA from (h:mm after the scenario epoch)", "TCA to (h:mm after the scenario epoch)",
                        "Samples"):
            assert f">{heading}</th>" in panel

    def test_the_chart_labels_its_bars_from_the_table(self, sampled: ScenarioResult) -> None:
        """The bars are labelled with the table's exact edges and the axis with its heading: nothing in the script
        rounds a time."""
        panel = _histogram_panel(_render(sampled))
        assert "toFixed" not in panel
        assert "td:first-child" in panel and "thead th" in panel

    def test_no_panel_without_a_sampled_cell(self) -> None:
        assert 'class="tca-histogram"' not in _render(_computed())

    def test_the_results_load_no_script_from_a_cdn(self, sampled: ScenarioResult) -> None:
        """61: Chart.js is vendored and already on the page; the results load nothing."""
        page = _render(sampled)
        assert "<script src" not in page
        assert "cdn" not in page.lower()
        assert "new Chart(" in _histogram_panel(page)

    def test_an_older_result_shape_renders(self, sampled: ScenarioResult) -> None:
        """60: a cell built before SPC-124 has no histogram attribute, and the result no links."""
        from types import SimpleNamespace

        older = dataclasses.replace(sampled, outcome_matrix=[list(row) for row in sampled.outcome_matrix])
        i, j, cell = _sampled_cells(sampled)[0]
        fields = {f.name: getattr(cell, f.name) for f in dataclasses.fields(cell) if f.name != "tca_histogram"}
        older.outcome_matrix[i][j] = SimpleNamespace(**fields)
        page = _render(older)
        assert _histogram_panel(page).count("<option ") == 3


def _clock_s(text: str) -> float:
    """Seconds in an h:mm or h:mm:ss reading."""
    parts = [int(p) for p in text.split(":")]
    hours, minutes, seconds = (*parts, 0)[:3]
    return float(hours * 3600 + minutes * 60 + seconds)


def cast_histogram(cell: OutcomeMetrics) -> TcaHistogram:
    assert cell.tca_histogram is not None
    return cell.tca_histogram
