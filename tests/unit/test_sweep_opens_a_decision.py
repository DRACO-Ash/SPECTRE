"""The sweep's worst case and each target row offer a decision scenario (SPC-150).

A labelled control on the worst case card, and on each sweep entry that
reaches its target, opens the Decision Engine panel pre-filled from that
entry. The control names the entry by its index in the sweep and the sweep by
its epoch, so the panel is filled from the server's held sweep and a newer
sweep is never mistaken for the one the operator was reading. An entry that
only aligns the planes reaches nothing, so it offers no control. The sweep
keeps each entry's departure burn, the one burn a single-burn hypothesis can
stand for: a transfer's summed parts are not one burn.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from spectre.astro.maneuvers import Burn, InterceptSolution
from spectre.domain.manoeuvre_calibration import DEFAULT_SWEEP_BUDGET_M_S
from spectre.domain.models import ThreatSweepEntry, ThreatTarget
from spectre.web.routes.threat import _compute_worst_coa, _group_entries, _sol_to_entry, worst_entry_index
from tests.unit.test_threat_sweep_template import _context, _render

_EPOCH = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[2]
_CONTROL = re.compile(r'<button[^>]*hx-get="/plan/decision/from-sweep"[^>]*>', re.S)


def _compiles_nothing(control: str) -> bool:
    """The control is marked for the page's delegated listener and carries no hx-on handler to compile."""
    return "hx-on" not in control and "data-opens-decision" in control


def _entry(target: str, tof: float, *, arrives: bool = True, method: str = "lambert") -> ThreatSweepEntry:
    return ThreatSweepEntry(
        target=ThreatTarget(target, "40001", "hrr", 1), burn_epoch=_EPOCH, burn_location="now",
        delta_v_m_s=50.0, tof_hours=tof, dv_prograde=50.0, dv_normal=0.0, dv_radial=0.0, method=method,
        regime="GEO", arrives=arrives,
    )


class TestTheSweepKeepsTheDepartureBurn:
    def test_an_entry_carries_its_first_burn_in_metres_per_second(self) -> None:
        sol = InterceptSolution(
            method="lambert", total_delta_v=0.07, departure_epoch=_EPOCH,
            arrival_epoch=datetime(2026, 9, 13, 17, 0, tzinfo=UTC),
            burns=[
                Burn(1, _EPOCH, np.zeros(3), 0.05, dv_prograde=0.03, dv_normal=0.04, dv_radial=0.0),
                Burn(2, _EPOCH, np.zeros(3), 0.02, dv_prograde=-0.02, dv_normal=0.0, dv_radial=0.0),
            ],
        )
        entry = _sol_to_entry(sol, ThreatTarget("ALPHA", "40001", "hrr", 1), _EPOCH, "now", "lambert", "GEO")
        assert entry.departure_m_s == (30.0, 40.0, 0.0)
        # The summed parts the card shows are unchanged.
        assert (entry.dv_prograde, entry.dv_normal) == pytest.approx((10.0, 40.0))

    def test_a_solution_with_no_burn_carries_no_departure(self) -> None:
        sol = InterceptSolution(method="lambert", departure_epoch=_EPOCH, arrival_epoch=_EPOCH)
        entry = _sol_to_entry(sol, ThreatTarget("ALPHA", "40001", "hrr", 1), _EPOCH, "now", "lambert", "GEO")
        assert entry.departure_m_s is None


class TestTheWorstCaseNamesItsEntry:
    def test_the_index_of_the_worst_entry_is_found_by_the_same_rule_as_the_worst_case(self) -> None:
        entries = [_entry("PLANE", 0.1, arrives=False, method="plane_change"), _entry("SLOW", 9.0),
                   _entry("FAST", 2.0)]
        coa = _compute_worst_coa(entries)
        assert coa is not None
        assert (coa["target_name"], worst_entry_index(entries, DEFAULT_SWEEP_BUDGET_M_S)) == ("FAST", 2)

    def test_the_index_stays_out_of_the_worst_case_dict_so_the_pinned_verdict_is_unchanged(self) -> None:
        # The legacy verdict of the 20 bundled red objects is pinned by a digest of this dict (SPC-175), so
        # where the entry sits travels beside it in the page context, never inside it.
        coa = _compute_worst_coa([_entry("FAST", 2.0)])
        assert coa is not None
        assert "entry_index" not in coa

    def test_a_sweep_with_nothing_that_arrives_has_no_worst_index(self) -> None:
        unflown = [_entry("PLANE", 0.1, arrives=False, method="plane_change")]
        assert worst_entry_index(unflown, DEFAULT_SWEEP_BUDGET_M_S) is None
        assert worst_entry_index([], DEFAULT_SWEEP_BUDGET_M_S) is None


class TestTheControls:
    def test_the_worst_case_card_offers_a_labelled_control_for_its_entry(self) -> None:
        page = _render(_context(worst_entry_index=4))
        controls = _CONTROL.findall(page)
        assert len(controls) == 1
        control = controls[0]
        assert 'aria-label="Open a decision scenario from the worst case: B_SAT_Alpha"' in control
        assert '"entry": 4' in control
        assert "2026-09-13T12:00:00+00:00" in control
        assert 'hx-target="#hero-decision"' in control
        assert _compiles_nothing(control)

    def test_a_worst_case_with_no_index_beside_it_offers_no_control(self) -> None:
        # A page rendered without the index, as every error path is, cannot name an entry, so it offers none.
        assert _CONTROL.findall(_render(_context())) == []

    def test_each_entry_that_reaches_its_target_offers_one_and_a_plane_change_does_not(self) -> None:
        entries = [_entry("ALPHA", 2.0), _entry("ALPHA", 0.1, arrives=False, method="plane_change")]
        context = _context()
        context["assessment"].entries = entries
        grouped = [{**group, "data_mode": "REAL"} for group in _group_entries(entries)]
        page = _render({**context, "grouped": grouped, "worst_coa": None})
        controls = _CONTROL.findall(page)
        assert len(controls) == 1
        assert 'aria-label="Decide from this entry in the Decision Engine: ALPHA, lambert, now"' in controls[0]
        assert _compiles_nothing(controls[0])

    def test_the_refined_row_offers_the_same_control(self) -> None:
        from spectre.web.app import templates as app_templates

        entry = _entry("ALPHA", 2.0)
        row = app_templates.env.get_template("partials/threat_sweep_row.html").render(
            entry=entry, index=3, group_idx=0, red_name="RX", error=None, refine_error=None,
            sweep_at=_EPOCH.isoformat(),
        )
        controls = _CONTROL.findall(row)
        assert len(controls) == 1
        assert "2026-09-13T12:00:00+00:00" in controls[0]
        assert _compiles_nothing(controls[0])

    def test_a_refined_row_that_only_aligns_the_planes_offers_none(self) -> None:
        from spectre.web.app import templates as app_templates

        entry = _entry("ALPHA", 0.1, arrives=False, method="plane_change")
        row = app_templates.env.get_template("partials/threat_sweep_row.html").render(
            entry=entry, index=3, group_idx=0, red_name="RX", error=None, refine_error=None,
            sweep_at=_EPOCH.isoformat(),
        )
        assert "Load</button>" in row
        assert _CONTROL.findall(row) == []

    def test_the_page_switches_to_the_engine_and_never_reloads_the_filled_panel(self) -> None:
        page = (_ROOT / "spectre" / "web" / "templates" / "operator.html").read_text(encoding="utf-8")
        hero = re.search(r'<div class="hero-panel" id="hero-decision"[^>]*>(.*?)</div><!-- end hero-decision -->',
                         page, re.S)
        assert hero is not None
        # The lazy load sits on a slot inside the hero, so a filled panel swapped in replaces it and its trigger.
        assert "hx-get" not in hero.group(0).split(">", 1)[0]
        assert 'hx-get="/plan/decision/panel"' in hero.group(1)
        assert "function openDecisionPanel()" in page
        # One delegated listener opens the engine after a control's request succeeds, so no control needs an
        # hx-on handler, which htmx compiles with new Function under the CSP's 'unsafe-eval' gap.
        listener = re.search(r"addEventListener\('htmx:afterRequest', function \(e\) \{(.*?)\}\);", page, re.S)
        assert listener is not None
        assert "data-opens-decision" in listener.group(1) and "e.detail.successful" in listener.group(1)
        assert "openDecisionPanel()" in listener.group(1)
