"""The Monte Carlo panel's columns mean what their headers say.

Audit F-104. The period row put the minimum and maximum under columns headed
"5th %ile" and "95th %ile", and the altitude row had no median. The panel
also said nothing about where its dispersions came from beyond the footer
"J2 + exponential drag · RIC perturbation model", so assumed archetype sigmas
read with the weight of measured figures.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.astro.monte_carlo import MonteCarloResult, run_monte_carlo
from tests.unit.test_monte_carlo import _basic_hypothesis

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"


@pytest.fixture(scope="module")
def mc() -> MonteCarloResult:
    hypothesis = _basic_hypothesis(n_samples=200)
    hypothesis.archetype = "Orbit raise"
    return run_monte_carlo(hypothesis, satno=25544, prediction_horizon_hours=6.0, max_workers=1)


def _render(mc: MonteCarloResult) -> str:
    from spectre.web.app import templates as app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(app_templates.env.filters)
    context: dict[str, Any] = {
        "mc": mc,
        "manoeuvre": SimpleNamespace(epoch=datetime(2025, 6, 1, 12, tzinfo=UTC)),
        "manoeuvre_dv_m_s": 10.0,
        "archetypes": [],
    }
    return " ".join(env.get_template("partials/pol_mc_results.html").render(**context).split())


def _row(html: str, label: str) -> list[str]:
    row = re.search(re.escape(label) + r".*?</tr>", html)
    assert row, f"no {label} row"
    return re.findall(r">\s*([-\d.]+)\s*</td>", row.group(0))


def test_the_period_row_is_percentiles_not_extremes(mc: MonteCarloResult) -> None:
    low, high = mc.period_range_minutes
    assert low <= mc.period_min_p5 <= mc.period_min_p50 <= mc.period_min_p95 <= high
    assert (mc.period_min_p5, mc.period_min_p95) != (low, high), "200 samples should not put P5 on the minimum"
    assert _row(_render(mc), "Period (min)") == [
        f"{mc.period_min_p5:.1f}", f"{mc.period_min_p50:.1f}", f"{mc.period_min_p95:.1f}",
    ]


def test_the_altitude_row_has_its_median(mc: MonteCarloResult) -> None:
    assert mc.alt_km_p5 <= mc.alt_km_p50 <= mc.alt_km_p95
    assert _row(_render(mc), "Alt (km)") == [
        f"{mc.alt_km_p5:.1f}", f"{mc.alt_km_p50:.1f}", f"{mc.alt_km_p95:.1f}",
    ]


def test_the_assumptions_are_stated_as_assumptions(mc: MonteCarloResult) -> None:
    html = _render(mc)
    assert "Modelled, not measured" in html
    assert "Orbit raise archetype" in html
    assert "ΔV 1σ 1.0 m/s" in html
    assert "pointing 1σ 2.0°" in html
    assert "timing 1σ 30 s" in html
    assert "ΔV direction: assumed in-track" in html
