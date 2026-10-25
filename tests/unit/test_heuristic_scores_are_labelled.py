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


class TestTheAstroResultsNameThemselvesHonestly:
    """Audit F-018, F-019, F-020: the astro types called scores probabilities."""

    def test_no_heuristic_result_field_is_called_a_probability_or_likelihood(self) -> None:
        import dataclasses

        from spectre.astro import tactical

        types = [tactical.DetectabilityResult, tactical.IntentAssessment, tactical.FingerprintResult]
        names = [f.name for t in types for f in dataclasses.fields(t)]
        assert not [n for n in names if re.search(r"prob|likelihood|confidence", n)], names

    def test_detectability_has_no_edge_at_exactly_geo_altitude(self) -> None:
        """35,785 km was scored with MEO constants and 35,786 km with GEO ones."""
        from spectre.astro.tactical import detectability_metric

        below, above = detectability_metric(0.005, 35780.0), detectability_metric(0.005, 35790.0)
        assert below.detection_score == pytest.approx(above.detection_score)
        assert below.time_to_detection_hours == pytest.approx(above.time_to_detection_hours)

    def test_the_detectability_docstring_claims_no_ssn_basis(self) -> None:
        from spectre.astro.tactical import detectability_metric

        doc = detectability_metric.__doc__ or ""
        assert "heuristic" in doc.lower()
        assert "based on Space Surveillance Network" not in doc

    def test_a_weak_fingerprint_reports_its_real_top_score(self) -> None:
        """Below 0.3 the match score was silently replaced by the constant 0.1."""
        from spectre.astro.tactical import fingerprint_manoeuvre

        r = fingerprint_manoeuvre(0.05, "radial", 8000.0, 10.0, 0.3)
        assert r.primary_classification == "unknown"
        assert r.match_score == pytest.approx(max(r.scores.values()))
        assert r.match_score != pytest.approx(0.1), "the old constant, not the score"


class TestTheAnomalyScoreIsAHeuristicIndex:
    """Audit F-036: the anomaly score read as a measurement under a risk banner."""

    _TEMPLATE = Path("spectre/web/templates/partials/pol_results.html")

    def test_the_panel_names_it_heuristic_and_shows_its_basis(self) -> None:
        text = self._TEMPLATE.read_text(encoding="utf-8")
        assert "heuristic anomaly index (uncalibrated)" in text
        assert "anomaly.basis" in text or "anoms.basis" in text
        assert "modelled.badge(" in text

    def test_the_tooltip_no_longer_cites_a_flat_ceiling(self) -> None:
        assert "200 m/s/yr" not in self._TEMPLATE.read_text(encoding="utf-8")

    def test_the_basis_says_the_weights_are_tuned(self) -> None:
        from spectre.domain.pol_assessment import assess_pattern_of_life
        from tests.unit.test_routine_burns_keep_the_reserve import _pol, _station_keeping

        anomaly = assess_pattern_of_life(_pol(_station_keeping())).anomaly
        assert anomaly is not None
        assert "tuned" in anomaly.basis and "heuristic" in anomaly.basis

    def test_the_module_no_longer_claims_every_threshold_is_cited(self) -> None:
        import spectre.domain.pol_assessment as pa

        assert "anomaly index" in (pa.__doc__ or ""), "the docstring must carve out the tuned anomaly weights"


class TestPhotometryReportsItsStatistics:
    """Audit F-033: a p-value was shown as a "Confidence" percentage."""

    def test_the_assessment_carries_sample_sizes_not_a_confidence(self) -> None:
        import dataclasses

        from spectre.astro.photometry import PhotometryChangeAssessment

        names = {f.name for f in dataclasses.fields(PhotometryChangeAssessment)}
        assert "confidence" not in names
        assert {"n_baseline", "n_recent", "p_value"} <= names

    def test_the_panel_shows_the_p_value_and_sizes(self) -> None:
        text = Path("spectre/web/templates/partials/photometry_results.html").read_text(encoding="utf-8")
        assert "result.confidence" not in text
        assert "Confidence:" not in text
        assert "result.p_value" in text and "result.n_baseline" in text and "result.n_recent" in text

    def test_the_summary_does_not_call_significance_confidence(self) -> None:
        from spectre.astro.photometry import PhotometryChangeAssessment

        a = PhotometryChangeAssessment(
            baseline_mean=12.0, baseline_std=0.02, recent_mean=12.3, recent_std=0.02,
            mean_residual=0.3, t_statistic=9.0, p_value=0.0001, significant_at_95=True,
            significant_at_99=True, magnitude_change=0.3, change_direction="fading",
            estimated_change_epoch=None, n_baseline=20, n_recent=8,
            confounding_factors=[], correlated_manoeuvre_epochs=[],
        )
        assert "confidence" not in a.summary().lower()
        assert "p < 0.01" in a.summary()


class TestTheEvasionPlannerSaysWhatItDoes:
    """Audit F-076 and F-079: dead combined-burn code, and a crash at zero fuel."""

    def test_a_zero_fuel_budget_plans_without_dividing_by_zero(self) -> None:
        from spectre.astro.tactical import optimal_evasion

        plan = optimal_evasion(6878.0, 1.0, 2700.0, fuel_budget_km_s=0.0)
        assert plan.best.delta_v == 0.0
        assert "fuel=100%" in plan.best.notes

    def test_the_docstring_claims_no_combined_burn(self) -> None:
        from spectre.astro.tactical import optimal_evasion

        assert "combined" not in (optimal_evasion.__doc__ or "").lower()
