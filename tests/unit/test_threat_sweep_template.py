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
        delta_v_km_s=0.4012,
        tof_hours=0.5,
        dv_prograde=0.38,
        dv_normal=0.10,
        dv_radial=0.05,
        method="min_time",
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
            ("bielliptic", "exceeds the 3 km/s budget"),
            ("lambert", "transfer angle within 0.5 degrees of 180"),
        ],
        "red_satno": "41838",
        "manual_red_confidence": None,
        "clustering_summary": None,
        "error": None,
    }
    context.update(overrides)
    return context


def _render(context: dict[str, Any]) -> str:
    env = Environment(  # noqa: S701  autoescape is set below; this is not a default-off env
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
    )
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
        assert "2 method(s) produced no solution" in html
        assert "BIELLIPTIC" in html
        assert "exceeds the 3 km/s budget" in html
        assert "transfer angle within 0.5 degrees of 180" in html

    def test_no_panel_when_nothing_was_refused(self) -> None:
        html = _render(_context(method_refusals=[]))
        assert "produced no solution" not in html


class TestTheTwoFindingsStaySeparatelyVisible:
    """The contradiction the composite verdict exists to remove."""

    def test_access_and_capability_are_both_on_the_page(self) -> None:
        html = _render(_context())
        assert "GEOMETRIC ACCESS" in html
        assert "ASSESSED CAPABILITY" in html
        # 0.401 km/s is HIGH accessibility; the object is recorded Degraded,
        # so capability is MINIMAL. Shown side by side rather than collapsed
        # into one word that then disagrees with the intel panel beside it.
        assert re.search(r"GEOMETRIC ACCESS.*?HIGH", html, re.S)
        assert re.search(r"ASSESSED CAPABILITY.*?MINIMAL", html, re.S)
        assert "MINIMAL THREAT" in html, "the weaker side governs the verdict"

    def test_missing_evidence_is_declared_not_hidden(self) -> None:
        html = _render(_context())
        assert "3 input(s) unavailable" in html
        assert "propellant budget" in html


class TestWarningTimeLeads:
    def test_warning_time_is_the_first_stat_after_the_target(self) -> None:
        html = _render(_context())
        warning = html.index("Warning Time")
        cost = html.index("&#916;V Required")
        assert warning < cost, "warning time is the decision; cost is the filter"

    def test_delta_v_is_shown_to_three_decimals_not_four(self) -> None:
        """The fourth decimal is 0.1 m/s, below TLE-driven uncertainty."""
        html = _render(_context())
        assert "0.401 " in html
        assert "0.4012" not in html
