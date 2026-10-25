"""A heuristic score never reaches the operator as a probability or a distance.

Step 4, the "heuristic scores presented as computed physics" cluster: audit
F-072, F-041, F-018, F-020 and F-021. Seven assessment methods (detectability,
intent, envelope, stability, fingerprint, terrain, manoeuvre detection)
carried their 0-100 scores in the miss-distance field, were labelled
"Detection Probability", "Intercept Likelihood" and "Fingerprint
Confidence", and were stamped "Computed via spectre.astro ... solver".
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from spectre.domain.models import BurnResult, InterceptMethod, InterceptResult
from spectre.web.routes.maneuver import _ASSESSMENT_METHODS, _compute_intercept_intel, _result_note

_T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_FORBIDDEN = re.compile(r"probabilit|likelihood|confidence", re.I)
_HEURISTIC_KINDS = {
    InterceptMethod.DETECTABILITY, InterceptMethod.INTENT_PREDICT, InterceptMethod.STABILITY,
    InterceptMethod.FINGERPRINT, InterceptMethod.TERRAIN, InterceptMethod.MANOEUVRE_DETECT,
}


def _assessment(method: InterceptMethod, score: float = 72.0) -> InterceptResult:
    heuristic = method in _HEURISTIC_KINDS
    return InterceptResult(
        red_name="SJ-17", blue_name="B_SAT_Alpha", method=method,
        burns=[BurnResult(burn_number=1, segment_name="Burn 1", burn_epoch=_T0, delta_v_m_s=5.0,
                          dv_prograde=5.0, dv_normal=0.0, dv_radial=0.0)],
        total_delta_v_m_s=5.0, arrival_epoch=_T0 + timedelta(hours=6),
        intercept_range_km=0.0,
        score=score, score_kind="test score", provenance="heuristic" if heuristic else "physics",
    )


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


@pytest.mark.parametrize("method", sorted(_ASSESSMENT_METHODS, key=lambda m: m.value))
def test_no_assessment_figure_is_called_a_probability(method: InterceptMethod) -> None:
    intel = _compute_intercept_intel(_assessment(method), "GEO")
    offenders = [s for s in _strings(intel) if _FORBIDDEN.search(s)]
    assert not offenders, f"{method.value}: {offenders}"


@pytest.mark.parametrize("method", sorted(_HEURISTIC_KINDS, key=lambda m: m.value))
def test_every_heuristic_figure_says_so(method: InterceptMethod) -> None:
    intel = _compute_intercept_intel(_assessment(method), "GEO")
    text = " ".join(_strings(intel["method_insights"]))
    assert "72/100" in text, f"{method.value}: the score is not shown on its 0-100 scale"
    assert "heuristic" in text.lower(), f"{method.value}: the figure is not marked heuristic"


def test_the_score_is_read_from_the_score_field_not_the_miss_distance() -> None:
    result = _assessment(InterceptMethod.INTENT_PREDICT, score=64.0)
    result.intercept_range_km = 999.0
    assert "64/100" in " ".join(_strings(_compute_intercept_intel(result, "GEO")))


def test_a_heuristic_result_is_not_stamped_as_a_solver_output() -> None:
    note = _result_note(InterceptMethod.INTENT_PREDICT, "intent_assessment", "heuristic")
    assert "Computed via" not in note
    assert "heuristic" in note.lower()
    assert "Computed via" in _result_note(InterceptMethod.LAMBERT, "lambert", "physics")


def test_the_observability_line_claims_no_detection_probability() -> None:
    from spectre.web.routes.maneuver import _observability

    assert not [r for dv in (1.0, 50.0, 500.0, 5000.0) if _FORBIDDEN.search(r := _observability(dv)[2])]


def test_no_assessment_solver_writes_its_score_into_the_miss_distance() -> None:
    """The type check F-072 asks for: miss_distance_km is a distance or nothing."""
    tree = ast.parse(Path("spectre/astro/maneuvers.py").read_text(encoding="utf-8"))
    score_names = re.compile(r"score|likelihood|confidence|feasible|raan|gap", re.I)
    offenders = []
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.keyword) and node.arg == "miss_distance_km" or isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == "miss_distance_km" for t in node.targets
        ):
            value = node.value
        if value is not None and score_names.search(ast.unparse(value)):
            offenders.append(f"line {node.lineno}: {ast.unparse(value)}")
    assert not offenders, offenders


def _render_panel(result: InterceptResult) -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    from spectre.web.app import templates as app_templates

    env = Environment(loader=FileSystemLoader("spectre/web/templates"), autoescape=True, undefined=StrictUndefined)
    env.filters.update(app_templates.env.filters)
    env.globals.update(app_templates.env.globals)
    html = env.get_template("partials/intercept_result.html").render(
        result=result, error=None, intercept_history=[result], intel=_compute_intercept_intel(result, "GEO"),
        pair=None, intercept_data_mode="REAL", csrf_token="",
    )
    return " ".join(html.split())


def test_the_panel_badges_a_heuristic_score_and_names_it() -> None:
    html = _render_panel(_assessment(InterceptMethod.INTENT_PREDICT))
    assert "modelled estimate, not a computed solution" in html
    assert "test score" in html and "/100 · heuristic" in html
    assert not _FORBIDDEN.search(re.sub(r"<[^>]+>", " ", html)), "the panel calls a score a probability"


def test_the_panel_shows_a_trajectory_without_the_badge() -> None:
    result = _assessment(InterceptMethod.LAMBERT)
    result.score, result.score_kind, result.provenance, result.intercept_range_km = None, "", "physics", 2.5
    html = _render_panel(result)
    assert "modelled estimate" not in html
    assert "Miss Distance" in html
