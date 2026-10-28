"""The template must actually show what the route computed.

Phase 1 added a refusals panel to ``partials/threat_sweep.html`` and bound it
to ``assessment.method_refusals``. The route supplies ``method_refusals`` at
the top level. Jinja's default undefined is falsy and silent, so the panel
simply never rendered, the page returned HTTP 200, the browser probe passed
with no console error, and every server-side test stayed green.

That is the same failure shape as the silent ``except Exception: pass`` the
panel exists to expose: something that produces nothing looks identical to
something that was never tried. These cases are the guard.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.models import ThreatAssessment, ThreatSweepEntry, ThreatTarget
from spectre.domain.threat_assessment import CapabilityEvidence
from spectre.web.routes.threat import _compute_worst_coa

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_TEMPLATE = "partials/threat_sweep.html"


def _context(**overrides: Any) -> dict[str, Any]:
    """The context key-for-key as ``threat_sweep`` renders it on success.

    ``worst_coa`` is built by calling the real ``_compute_worst_coa`` rather
    than being typed out here, so the fixture cannot drift away from what the
    route actually passes. A hand-written copy would go stale the first time a
    key was added, which is the failure this file exists to prevent.
    """
    target = ThreatTarget("B_SAT_Alpha", "12345", "blue", None)
    entry = ThreatSweepEntry(
        target=target,
        burn_epoch=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        burn_location="now",
        delta_v_m_s=401.2,
        tof_hours=0.5,
        dv_prograde=380.0,
        dv_normal=100.0,
        dv_radial=50.0,
        method="min_time",
        regime="GEO",
    )
    worst_coa = _compute_worst_coa(
        [entry],
        CapabilityEvidence(intel_threat_level="LOW", operational_status="Degraded"),
        3.0,
    )
    context: dict[str, Any] = {
        "assessment": ThreatAssessment(
            red_name="SJ-17",
            sweep_epoch=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
            target_count=3,
            entries=[entry],
            elapsed_s=1.25,
            errors=[],
        ),
        "grouped": [],
        "hrr_count": 0,
        "worst_coa": worst_coa,
        "method_refusals": [
            ("B_SAT_Alpha", "bielliptic", "at now: exceeds the 500 m/s budget"),
            ("B_SAT_Alpha", "lambert", "at now: transfer angle within 0.5 degrees of 180"),
        ],
        "red_satno": "41838",
        "manual_red_confidence": None,
        "clustering_summary": None,
        "provenance_warnings": [],
        "error": None,
    }
    context.update(overrides)
    return context


def _render(context: dict[str, Any]) -> str:
    """Render through the application's OWN filter set, not a fresh one.

    A private Environment here would not have the ``m_s`` filter the templates
    use, so this guard would fail for a reason production never sees, and worse,
    a filter added in production and missed here would go unnoticed. The filters
    are taken from the real app so the two cannot drift.
    """
    from spectre.web.app import templates as _app_templates

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(_app_templates.env.filters)
    return env.get_template(_TEMPLATE).render(**context)


class TestEveryNameTheTemplateUsesIsSupplied:
    """StrictUndefined turns the silent binding error into a failure."""

    def test_the_success_context_renders_without_an_undefined_name(self) -> None:
        html = _render(_context())
        assert "MOST DANGEROUS COURSE OF ACTION" in html

    def test_strict_undefined_is_what_catches_it(self) -> None:
        """Proof the guard has teeth: drop one key and it must fail."""
        context = _context()
        del context["method_refusals"]
        with pytest.raises(Exception, match="method_refusals"):
            _render(context)


class TestTheRefusalsPanelIsVisible:
    def test_each_refused_method_and_its_reason_appear(self) -> None:
        html = _render(_context())
        assert "2 method(s) produced no approach to a target" in html
        assert "BIELLIPTIC" in html
        assert "exceeds the 500 m/s budget" in html
        assert "transfer angle within 0.5 degrees of 180" in html

    def test_no_panel_when_nothing_was_refused(self) -> None:
        html = _render(_context(method_refusals=[]))
        assert "produced no approach" not in html


class TestTheTwoFindingsStaySeparatelyVisible:
    """The contradiction the composite verdict exists to remove."""

    def test_access_and_capability_are_both_on_the_page(self) -> None:
        html = _render(_context())
        assert "GEOMETRIC ACCESS" in html
        assert "ASSESSED CAPABILITY" in html
        # 401 m/s is an AGGRESSIVE profile for GEO; the object is Degraded,
        # so capability is MINIMAL. Shown side by side rather than collapsed
        # into one word that then disagrees with the intel panel beside it.
        assert re.search(r"GEOMETRIC ACCESS.*?MEDIUM", html, re.S)
        assert re.search(r"ASSESSED CAPABILITY.*?MINIMAL", html, re.S)
        assert "MINIMAL THREAT" in html, "the weaker side governs the verdict"

    def test_missing_evidence_is_declared_not_hidden(self) -> None:
        html = _render(_context())
        # Four: the discretionary reserve is listed too since audit F-228.
        assert "4 input(s) unavailable" in html
        assert "propellant budget" in html


class TestThePostureIsOnTheScreen:
    """A delta-v figure on its own tells an operator nothing."""

    def test_the_posture_and_its_reasoning_are_shown(self) -> None:
        html = _render(_context())
        # 401 m/s for a GEO rendezvous is well past the 120 m/s annoyance
        # ceiling drawn from the observed SJ-21 dock-and-tow round trip.
        assert "AGGRESSIVE" in html
        assert "m/s" in html
        assert "station-keeping" in html, (
            "the multiple of routine station-keeping is the figure an operator "
            "can actually weigh"
        )

    def test_a_burn_nothing_could_deliver_in_time_says_so(self) -> None:
        """Reserve is not the same as the ability to spend it in time."""
        from spectre.domain.threat_assessment import AccessEvidence, assess_threat
        from spectre.domain.threat_assessment import CapabilityEvidence as Cap

        verdict = assess_threat(
            AccessEvidence(
                best_delta_v_m_s=450.0, time_to_arrival_hours=0.6,
                method="min_time", regime="GEO",
            ),
            Cap(intel_threat_level="HIGH", operational_status="Operational"),
        )
        assert verdict.undeliverable_reason, (
            "no flown platform can deliver 450 m/s in 36 minutes; the fastest "
            "is a storable-chemical OTV at about 2.5 hours"
        )
        coa = _context()["worst_coa"]
        coa["undeliverable_reason"] = verdict.undeliverable_reason
        html = _render(_context(worst_coa=coa))
        assert "NOT FLYABLE" in html
        assert "continuous thrust" in html


class TestWarningTimeLeads:
    def test_warning_time_is_the_first_stat_after_the_target(self) -> None:
        html = _render(_context())
        warning = html.index("Warning Time")
        cost = html.index("&#916;V Required")
        assert warning < cost, "warning time is the decision; cost is the filter"

    def test_delta_v_is_shown_in_whole_metres_per_second(self) -> None:
        """401 m/s, not 0.4012 km/s. The operator never sees km/s."""
        html = _render(_context())
        assert "401" in html
        assert "0.4012" not in html, "that is km/s with four decimals of noise"
        assert "401." not in html, "a figure this size is shown in whole m/s, with no decimals"
        assert "km/s" not in html, "no operator-facing figure is in km/s"
