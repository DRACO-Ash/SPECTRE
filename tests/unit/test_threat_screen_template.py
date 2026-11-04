"""The screening panel must show what the route computed.

Same guard shape as the threat sweep's, for the same reason: Jinja's default
undefined is falsy and silent, so a context key the route forgets renders as an
empty string and nothing raises. The refusals panel shipped dead in 0.5.14
exactly that way.

The ranked list is built by calling the real ``rank_actors``, so the fixture
cannot drift from what the route passes.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.models import ThreatActor, ThreatSweepEntry, ThreatTarget
from spectre.domain.threat_assessment import (
    AccessEvidence,
    ActorRange,
    ActorVerdict,
    Band,
    CapabilityEvidence,
    ScreeningResult,
    assess_threat,
    rank_actors,
)
from tests.unit._i13 import i13_problems

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_TEMPLATE = "partials/threat_screen.html"

_BAND_COLOURS = {
    "CRITICAL": ("#ef4444", "rgba(239,68,68,0.06)"),
    "HIGH": ("#f59e0b", "rgba(245,158,11,0.06)"),
    "MEDIUM": ("#3b8beb", "rgba(59,139,235,0.06)"),
    "LOW": ("#22c55e", "rgba(34,197,94,0.06)"),
    "MINIMAL": ("#64748b", "rgba(100,116,139,0.06)"),
}


def _verdict(name: str, satno: str, dv: float, hours: float,
             capability: tuple[str | None, str | None, str]) -> ActorVerdict:
    """*capability* is (threat level, operational status, country)."""
    intel, status, country = capability
    assessment = assess_threat(
        AccessEvidence(best_delta_v_m_s=dv, time_to_arrival_hours=hours,
                       method="vbar_hop", regime="GEO"),
        CapabilityEvidence(intel_threat_level=intel, operational_status=status),
    )
    return ActorVerdict(
        actor_name=name, actor_satno=satno, assessment=assessment,
        warning_hours=hours, delta_v_m_s=dv, method="vbar_hop", country=country,
    )


def _profiles(satno: str, name: str) -> list[ThreatSweepEntry]:
    """Two profiles for one actor, as the route groups them."""
    actor = ThreatActor(actor_name=name, actor_satno=satno, country="CHN", regime="GEO")
    target = ThreatTarget("SKYNET-5A", "30793", "hrr", 1)
    return [
        ThreatSweepEntry(
            target=target,
            burn_epoch=datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
            burn_location=location,
            delta_v_m_s=dv,
            tof_hours=hours,
            dv_prograde=dv * 0.9, dv_normal=dv * 0.3, dv_radial=dv * 0.1,
            method=method,
            regime="GEO",
            posture_label=posture,
            actor=actor,
        )
        for location, dv, hours, method, posture in (
            ("now", 8.0, 6.2, "vbar_hop", "BENIGN"),
            ("apogee", 24.0, 11.0, "lambert", "BENIGN"),
        )
    ]


def _context(**overrides: Any) -> dict[str, Any]:
    """The context key-for-key as ``threat_screen`` renders it on success.

    ``screening`` comes from the real ``rank_actors`` rather than being typed
    out, so a change to the ranking shape fails here rather than rendering a
    blank panel.
    """
    screening = rank_actors([
        _verdict("TJS-3", "43874", 8.0, 6.2, ("CRITICAL", "Operational", "CHN")),
        _verdict("COSMOS 2535", "44797", 9.0, 0.68,
                 ("LOW", "Inactive - Retired / Not Manoeuverable", "RUS")),
        _verdict("SJ-17", "41838", 55.0, 14.0, ("HIGH", "Operational", "CHN")),
    ])
    context: dict[str, Any] = {
        "screening": screening,
        "asset_name": "SKYNET-5A",
        "asset_satno": "30793",
        "asset_regime": "GEO",
        "actors_considered": 22,
        "actors_reachable": 3,
        "red_population": 22,
        "budget_m_s": 500.0,
        "elapsed_s": 1.35,
        "entry_count": 41,
        "method_refusals": [("SJ-17", "bielliptic", "at now: exceeds the 500 m/s budget")],
        "profiles_by_actor": {
            "43874": _profiles("43874", "TJS-3"),
            "44797": _profiles("44797", "COSMOS 2535"),
            "41838": _profiles("41838", "SJ-17"),
        },
        "errors": ["SL-12 R/B (27051): no element set"],
        "error": None,
        "band_colours": _BAND_COLOURS,
        "actor_modes": {},
        "provenance_warnings": [],
    }
    context.update(overrides)
    return context


def _render(context: dict[str, Any]) -> str:
    """Render through the application's OWN filter set, not a fresh one."""
    from spectre.web.app import templates as app_templates

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
    )
    env.filters.update(app_templates.env.filters)
    return env.get_template(_TEMPLATE).render(**context)


class TestEveryNameTheTemplateUsesIsSupplied:
    def test_the_success_context_renders(self) -> None:
        html = _render(_context())
        assert "MOST DANGEROUS ACTOR" in html

    def test_strict_undefined_is_what_catches_a_missing_key(self) -> None:
        context = _context()
        del context["band_colours"]
        with pytest.raises(Exception, match="band_colours"):
            _render(context)


class TestTheTwoHeadlineAnswers:
    """Ranking on either one alone gets it wrong, so both are shown."""

    def test_the_most_dangerous_actor_leads(self) -> None:
        html = _render(_context())
        assert "TJS-3" in html
        assert re.search(r"MOST DANGEROUS ACTOR.*?TJS-3", html, re.S), (
            "the capable object heads the panel, not the fastest one"
        )

    def test_the_earliest_arrival_is_named_separately(self) -> None:
        html = _render(_context())
        assert "EARLIEST ARRIVAL" in html
        assert "COSMOS 2535" in html

    def test_the_disagreement_is_spelled_out(self) -> None:
        html = _render(_context())
        assert "If that assessment is wrong" in html, (
            "when the soonest arrival is not the most capable object, the "
            "analyst has to be told what it costs them to be wrong"
        )

    def test_no_earliest_arrival_block_when_they_agree(self) -> None:
        """One actor cannot disagree with itself."""
        screening = rank_actors([
            _verdict("TJS-3", "43874", 8.0, 1.0, ("CRITICAL", "Operational", "CHN")),
        ])
        html = _render(_context(screening=screening))
        assert "EARLIEST ARRIVAL" not in html
        assert "If that assessment is wrong" not in html


class TestNothingIsHiddenFromTheOperator:
    def test_every_actor_appears_in_the_ranked_table(self) -> None:
        html = _render(_context())
        for name in ("TJS-3", "COSMOS 2535", "SJ-17"):
            assert name in html
        assert "MINIMAL" in html, "the retired object is shown, ranked last"

    def test_an_empty_ranking_still_states_why(self) -> None:
        """"Nothing listed" and "nothing can reach you" must look different."""
        html = _render(_context(screening=rank_actors([]), actors_reachable=0))
        # Collapse whitespace: the template wraps these sentences across lines.
        flat = " ".join(html.split())
        assert "No candidate actor can reach this asset" in flat
        assert "That is a finding, not an absence of data" in flat
        assert "22 red object(s) in a compatible regime were screened" in flat

    def test_candidates_that_could_not_be_assessed_are_listed(self) -> None:
        html = _render(_context())
        assert "1 candidate(s) not assessed" in html
        assert "SL-12 R/B" in html

    def test_refused_methods_are_listed(self) -> None:
        html = _render(_context())
        assert "1 method(s) produced no solution for an actor" in html
        assert "exceeds the 500 m/s budget" in html


class TestTheWorkingBehindEachVerdictIsReachable:
    """A verdict an analyst cannot interrogate gets ignored the first time it
    disagrees with them."""

    def test_each_actor_row_carries_its_profiles(self) -> None:
        html = _render(_context())
        assert "scr-child" in html, "the per-actor profile rows are missing"
        assert "apogee" in html, "the burn locations behind the verdict"
        assert html.count("threat-profile-badge") == 3, (
            "one profile-count badge per ranked actor"
        )

    def test_an_actor_with_no_profiles_still_renders(self) -> None:
        """A verdict can exist without its entries having been kept."""
        html = _render(_context(profiles_by_actor={}))
        assert "TJS-3" in html
        assert "threat-profile-badge" not in html


class TestTheUnitsRuleHoldsHereToo:
    def test_no_km_s_reaches_the_screen(self) -> None:
        html = _render(_context())
        assert "km/s" not in html

    def test_warning_time_leads_the_stat_cards(self) -> None:
        html = _render(_context())
        assert html.index("Warning Time") < html.index("&#916;V Required")


# ── SPC-169: RANGE and UNDERSTANDING beside the unchanged verdict ──

def _spanned() -> ScreeningResult:
    low = ActorRange(floor=Band.MINIMAL, ceiling=Band.CRITICAL, understanding="LOW", history_held=False,
                     at_ceiling=True, statement="Understanding LOW. Governing: information base, Identity not earned.",
                     cue="pull its element-set history: could raise the Threat floor to HIGH, 3 Threat steps, "
                         "about 30 min")
    moderate = ActorRange(floor=Band.HIGH, ceiling=Band.CRITICAL, understanding="MODERATE", history_held=True,
                          at_ceiling=False)
    spans = {"43874": moderate, "44797": low, "41838": low}
    return rank_actors([replace(v, understanding=spans[v.actor_satno]) for v in _context()["screening"].ranked])


_SCREEN_BANDS = re.compile(r"\b(MINIMAL|LOW|MEDIUM|HIGH|CRITICAL|MODERATE)\b")
_DISAGREEMENT = re.compile(r'<div class="screen-understanding-disagreement"[\s\S]*?</div>')


def _plain(fragment: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


class TestTheRangeAndUnderstandingColumns:
    def test_the_table_gains_two_columns_after_the_verdict(self) -> None:
        html = _render(_context(screening=_spanned()))
        headers = re.findall(r'<th scope="col"[^>]*>([^<]*)</th>', html)
        assert headers[4:7] == ["Verdict", "Range", "Understanding"]
        assert "Threat HIGH to CRITICAL" in html and "Threat MINIMAL to CRITICAL" in html
        assert "Understanding LOW: no history held" in html and "Understanding MODERATE" in html

    def test_the_verdict_column_is_unchanged(self) -> None:
        cell = r'<td><span style="color:[^"]*; font-weight:700">[A-Z]+</span></td>'
        before = re.findall(cell, _render(_context()))
        assert before == re.findall(cell, _render(_context(screening=_spanned())))
        assert len(before) == 3

    def test_the_range_takes_the_ceilings_status_token(self) -> None:
        html = _render(_context(screening=_spanned()))
        assert re.search(r'<td class="screen-range" style="color:var\(--spectre-status-critical\)">'
                         r"Threat HIGH to CRITICAL</td>", html)

    def test_the_understanding_cell_explains_itself_and_names_the_cue(self) -> None:
        """Finding 7: the statement and the cue are text a keyboard or screen reader reaches, in a details element."""
        html = _render(_context(screening=_spanned()))
        cell = re.search(r'<td class="screen-understanding[^"]*">\s*<details>\s*<summary>([^<]*)</summary>'
                         r'\s*<div>([^<]*)</div>\s*<div>([^<]*)</div>\s*</details>\s*</td>', html)
        assert cell is not None
        assert cell.groups() == (
            "Understanding LOW: no history held", "Understanding LOW. Governing: information base, Identity not earned.",
            "Raise it by: pull its element-set history: could raise the Threat floor to HIGH, 3 Threat steps, "
            "about 30 min.")
        assert "title=" not in cell.group(0)

    def test_without_a_statement_the_cell_is_its_label(self) -> None:
        assert re.search(r'<td class="screen-understanding col-dim">Understanding MODERATE</td>',
                         _render(_context(screening=_spanned())))

    def test_an_actor_without_a_range_reads_not_assessed(self) -> None:
        html = _render(_context())
        assert html.count('<td class="screen-range col-dim">not assessed</td>') == 3

    def test_the_new_disagreement_renders_in_its_own_block(self) -> None:
        screening = _spanned()
        assert screening.understanding_disagreement
        html = _render(_context(screening=screening))
        block = _DISAGREEMENT.search(html)
        assert block is not None
        assert _plain(block.group(0)) == screening.understanding_disagreement
        assert "If that assessment is wrong" in html, "the existing disagreement stays"

    def test_no_block_without_the_case(self) -> None:
        assert "screen-understanding-disagreement" not in _render(_context())

    def test_the_profile_rows_span_the_wider_table(self) -> None:
        html = _render(_context(screening=_spanned()))
        header = re.search(r"<thead>[\s\S]*?</thead>", html)
        row = re.search(r'<tr class="scr-child[^"]*"[^>]*>([\s\S]*?)</tr>', html)
        assert header is not None and row is not None
        spans = [int(n) for n in re.findall(r'colspan="(\d+)"', row.group(1))]
        assert row.group(1).count("<td") - len(spans) + sum(spans) == header.group(0).count("<th ") == 13

    def test_i13_in_the_new_cells_and_block(self) -> None:
        html = _render(_context(screening=_spanned()))
        block = _DISAGREEMENT.search(html)
        assert block is not None
        found = [*re.findall(r'<td class="screen-range[^"]*"[^>]*>([^<]*)</td>', html),
                 *(_plain(c) for c in re.findall(r'<td class="screen-understanding[^"]*"[^>]*>[\s\S]*?</td>', html)),
                 _plain(block.group(0))]
        assert len(found) >= 7
        for text in found:
            for sentence in re.split(r"(?<=\.)\s+|(?<=held)\s+(?=Understanding)", text):
                assert i13_problems(sentence) == [], sentence
