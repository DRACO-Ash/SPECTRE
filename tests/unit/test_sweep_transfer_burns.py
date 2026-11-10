"""A scenario opened from the sweep carries every burn of the transfer (SPC-184).

Owner ruling of 2026-11-05 (concept section 9, decision 13). The sweep keeps each burn of an entry's transfer at its
own UTC time with its own prograde, normal and radial parts in m/s; the panel opened from that entry fills the
row's first burn in its fields, as before, and carries the later burns with it, listing every burn in words before
Evaluate. A burn at or before the held red element set's epoch is named as not applied, since the set may already
include it. A transfer of one burn fills the panel exactly as before (tests/unit/test_decision_from_sweep.py).

Nothing here reads the wall clock or reaches the network.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.kepler import propagate_two_body
from spectre.astro.maneuvers import Burn, InterceptSolution, lambert_intercept, min_time_intercept_wrapper
from spectre.astro.monte_carlo import _ric_to_eci_rotation
from spectre.astro.propagator import TLEOrbit
from spectre.domain.decision_transfer import TransferBurn
from spectre.domain.models import SweepBurn, ThreatTarget
from spectre.web.elsets import elset_age
from spectre.web.routes.threat import _sol_to_entry
from tests.unit._decision_reference import RE_KM, Circular, element_set
from tests.unit._i13 import i13_problems
from tests.unit.test_decision_from_sweep import (
    _NOW,
    _RED_TLE,
    TestThePanelRendersUnderStrictUndefined,
    _entry,
    _open,
    _state,
)

_EPOCH = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
_DEPART = _NOW + timedelta(hours=1)
_MID = _NOW + timedelta(hours=3)
_ARRIVE = _NOW + timedelta(hours=6)


def _transfer(*times: datetime) -> tuple[SweepBurn, ...]:
    """A three-burn transfer at *times*, its first burn the entry's departure (30, 40, 0) m/s."""
    at = times or (_DEPART, _MID, _ARRIVE)
    return (SweepBurn(at[0], 30.0, 40.0, 0.0), SweepBurn(at[1], -12.5, 0.0, 3.0), SweepBurn(at[2], 0.0, 0.0, -2.0))


class TestTheSweepKeepsEveryBurn:
    def test_an_entry_carries_each_burn_at_its_own_time_in_metres_per_second(self) -> None:
        later = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)
        sol = InterceptSolution(
            method="lambert", total_delta_v=0.07, departure_epoch=_EPOCH, arrival_epoch=later,
            burns=[
                Burn(1, _EPOCH, np.zeros(3), 0.05, dv_prograde=0.03, dv_normal=0.04, dv_radial=0.0),
                Burn(2, later, np.zeros(3), 0.02, dv_prograde=-0.02, dv_normal=0.0, dv_radial=0.001),
            ],
        )
        entry = _sol_to_entry(sol, ThreatTarget("ALPHA", "40001", "hrr", 1), _EPOCH, "now", "lambert", "GEO")
        assert entry.transfer_m_s == (
            SweepBurn(_EPOCH, 30.0, 40.0, 0.0), SweepBurn(later, -20.0, 0.0, pytest.approx(1.0)),
        )
        assert entry.departure_m_s == (30.0, 40.0, 0.0)

    @pytest.mark.parametrize(("method", "solve", "extra"), [
        ("lambert", lambert_intercept, {"tof_s": 21600.0, "coast_s": 0.0}),
        ("min_time", min_time_intercept_wrapper, {"coast_s": 0.0, "max_delta_v": 3.0}),
    ])
    def test_a_later_burn_is_split_in_reds_own_frame_as_the_engine_applies_it(
        self, method: str, solve: Any, extra: dict[str, Any],
    ) -> None:
        # The solver splits a Lambert arrival burn at the target's state; the engine applies the parts in red's own
        # radial, in-track and cross-track frame at its state on the transfer, so that is where they are split.
        start = datetime(2026, 10, 17, 12, 30, tzinfo=UTC)
        blue = element_set(Circular(90001, RE_KM + 550, 97.4, 40.0, 1.4))
        red = element_set(Circular(90002, RE_KM + 550, 97.4, 43.0, 1.7))
        sol = solve(red, blue, start, **extra)
        entry = _sol_to_entry(sol, ThreatTarget("ALPHA", "90001", "hrr", 1), start, "now", method, "LEO")
        burn1, burn2 = sol.burns
        at = TLEOrbit(red).propagate(burn1.epoch)
        r, v = propagate_two_body(at.r, at.v + burn1.delta_v, (burn2.epoch - burn1.epoch).total_seconds(), MU_EARTH)
        later = entry.transfer_m_s[1]
        applied = _ric_to_eci_rotation(r, v) @ (np.array([later.radial, later.prograde, later.normal]) / 1000.0)
        assert later.at_utc == burn2.epoch
        assert np.linalg.norm(applied - burn2.delta_v) * 1000.0 < 1e-6   # m/s
        # Burn 1 is the departure as before.
        assert entry.transfer_m_s[0] == SweepBurn(burn1.epoch, *(1000.0 * np.array(
            [burn1.dv_prograde, burn1.dv_normal, burn1.dv_radial])))

    def test_a_solution_with_no_burn_carries_none(self) -> None:
        sol = InterceptSolution(method="lambert", departure_epoch=_EPOCH, arrival_epoch=_EPOCH)
        entry = _sol_to_entry(sol, ThreatTarget("ALPHA", "40001", "hrr", 1), _EPOCH, "now", "lambert", "GEO")
        assert entry.transfer_m_s == ()


def _listed(**kw: Any) -> Any:
    """An entry carrying a transfer, its cost the sum of its burns, as the sweep's solutions that list each burn are."""
    burns = kw["transfer_m_s"]
    kw.setdefault("delta_v_m_s", sum(math.hypot(b.prograde, b.normal, b.radial) for b in burns))
    return _entry(**kw)


def _hop(**kw: Any) -> Any:
    """A V-bar hop entry: its solution lists the entry and final burns, 3.5 m/s each, of 3 hops costing 20.8 m/s."""
    burns = (SweepBurn(_DEPART, 0.0, 0.0, 3.466), SweepBurn(_ARRIVE, 0.0, 0.0, -3.466))
    fields: dict[str, Any] = {"method": "vbar_hop", "delta_v_m_s": 20.795, "departure_m_s": (0.0, 0.0, 3.466),
                              "transfer_m_s": burns}
    fields.update(kw)
    return _entry(**fields)


class TestATransferWhoseBurnsAreNotAllListed:
    def test_a_hop_whose_burns_do_not_sum_to_its_cost_carries_its_first_burn_alone_and_says_why(self) -> None:
        prefill = _open(_state(_hop()))
        row = prefill.rows[0]
        assert (row.then, row.burn_lines) == ((), ())
        assert (
            "Row 1 carries burn 1 alone: the sweep's VBAR_HOP solution lists 2 burns summing to 6.9 m/s of the "
            "transfer's 20.8 m/s, so not every burn of its transfer, and the engine does not guess the rest."
        ) in prefill.left
        assert not any("burns from the sweep's solution" in f for f in prefill.filled)

    def test_a_transfer_whose_burns_sum_to_its_cost_carries_every_burn(self) -> None:
        listed = _open(_state(_entry(delta_v_m_s=52.0 + math.hypot(12.5, 3.0), transfer_m_s=_transfer())))
        assert len(listed.rows[0].then) == 2


class TestThePanelCarriesEveryBurn:
    def test_the_first_burn_fills_the_fields_and_the_later_burns_are_carried(self) -> None:
        row = _open(_state(_listed(transfer_m_s=_transfer()))).rows[0]
        assert (row.dv_m_s, row.direction, row.burn_at) == ("50", ("0", "0.6", "0.8"), _DEPART)
        assert row.then == (TransferBurn(_MID, -12.5, 0.0, 3.0), TransferBurn(_ARRIVE, 0.0, 0.0, -2.0))
        assert row.then_value == (
            f"{_MID.isoformat()} -12.5 0.0 3.0;{_ARRIVE.isoformat()} 0.0 0.0 -2.0"
        )

    def test_every_burn_is_listed_in_words(self) -> None:
        row = _open(_state(_listed(transfer_m_s=_transfer()))).rows[0]
        assert row.burn_lines == (
            "Burn 1 at 10:00 UTC on 4 Nov, 50.0 m/s (prograde 30.0, normal 40.0 and radial 0.0 m/s), set in the "
            "fields above.",
            "Burn 2 at 12:00 UTC on 4 Nov, 12.9 m/s (prograde -12.5, normal 0.0 and radial 3.0 m/s).",
            "Burn 3 at 15:00 UTC on 4 Nov, 2.0 m/s (prograde 0.0, normal 0.0 and radial -2.0 m/s).",
        )

    def test_the_fill_says_it_carries_every_burn_as_one_action(self) -> None:
        prefill = _open(_state(_listed(transfer_m_s=_transfer())))
        assert (
            "Adversary row 1: the transfer's 3 burns from the sweep's solution, one action with one P, each at its "
            "own time with the Intercept / Approach archetype's dispersions. Burn 1's prograde, normal and radial "
            "parts are read as in-track, cross-track and radial, which match on a near-circular orbit; each later "
            "burn's are split in red's own in-track, cross-track and radial frame at its state on the transfer, "
            "where the engine applies it. Burn 1, 50 m/s at 10:00 UTC on 4 Nov, is in the fields below; the engine "
            "applies every burn in time order."
        ) in prefill.filled

    def test_a_transfer_of_one_burn_fills_as_before(self) -> None:
        single = _open(_state(_entry(transfer_m_s=_transfer()[:1])))
        before = _open(_state(_entry()))
        assert single == before
        assert single.rows[0].then == () and single.rows[0].then_value == "" and single.rows[0].burn_lines == ()

    def test_a_burn_at_or_before_the_held_red_set_is_named_as_not_applied(self) -> None:
        # The held red set dates from 04:00; burn 1 is at 03:00 and burn 2 at the set's own epoch.
        red_epoch = _NOW - timedelta(hours=5)
        times = (_NOW - timedelta(hours=6), red_epoch, _ARRIVE)
        prefill = _open(_state(_listed(burn_epoch=times[0], tof_hours=12.0, transfer_m_s=_transfer(*times))))
        assert (
            "Burns 1 and 2 of row 1, at 03:00 UTC on 4 Nov and 04:00 UTC on 4 Nov, are at or before the red element "
            "set held for RX, dated 04:00 UTC on 4 Nov, which may already include them, so the engine will not apply "
            "them. It applies burn 3."
        ) in prefill.left
        # The fill never says every burn is applied when some are not.
        assert any("is in the fields below; the engine applies burn 3, not burns 1 and 2, as said below." in f
                   for f in prefill.filled)
        assert not any("applies every burn" in f for f in prefill.filled)
        row = prefill.rows[0]
        assert row.sampled is True
        assert row.burn_lines[0].endswith("set in the fields above; not applied, at or before the red element set's "
                                          "epoch.")
        assert row.burn_lines[2] == "Burn 3 at 15:00 UTC on 4 Nov, 2.0 m/s (prograde 0.0, normal 0.0 and radial -2.0 m/s)."

    def test_a_burn_exactly_at_the_held_red_sets_epoch_is_named_as_not_applied(self) -> None:
        held = elset_age(_RED_TLE, _NOW)
        assert held is not None and held.epoch is not None
        times = (held.epoch - timedelta(hours=1), held.epoch, _ARRIVE)
        row = _open(_state(_listed(burn_epoch=times[0], tof_hours=12.0, transfer_m_s=_transfer(*times)))).rows[0]
        assert row.burn_lines[1].endswith("; not applied, at or before the red element set's epoch.")
        assert row.starts_at == _ARRIVE

    def test_a_row_whose_every_burn_is_dropped_is_said_not_to_be_sampled(self) -> None:
        times = (_NOW - timedelta(hours=8), _NOW - timedelta(hours=7), _NOW - timedelta(hours=6))
        prefill = _open(_state(_listed(burn_epoch=times[0], tof_hours=12.0, transfer_m_s=_transfer(*times))))
        assert prefill.rows[0].sampled is False
        assert (
            "The engine will not sample row 1's closest approach: each of its 3 burns is at or before the red element "
            "set held for RX, dated 04:00 UTC on 4 Nov, so that set may already include them."
        ) in prefill.left
        assert any("is in the fields below; the engine applies none of them, as said below." in f
                   for f in prefill.filled)

    def test_a_burn_over_the_limit_is_named_before_evaluate(self) -> None:
        big = (SweepBurn(_DEPART, 30.0, 40.0, 0.0), SweepBurn(_MID, 1200.0, 0.0, 300.0), SweepBurn(_ARRIVE, 0.0, 0.0, 2.0))
        prefill = _open(_state(_listed(transfer_m_s=big)))
        assert (
            "Burn 2 of row 1 is 1,237 m/s, over the 1,000 m/s a burn may be, so Evaluate will refuse the row: set its "
            "archetype to None to keep it a lookup, or open a cheaper entry from the sweep."
        ) in prefill.left

    def test_burns_1_and_2_dropped_leave_burn_3_alone_and_burns_2_and_3_read_in_time_order(self) -> None:
        red_epoch = _NOW - timedelta(hours=5)
        times = (_NOW - timedelta(hours=6), _NOW - timedelta(hours=4), _ARRIVE)
        prefill = _open(_state(_listed(burn_epoch=times[0], tof_hours=12.0, transfer_m_s=_transfer(*times))))
        assert red_epoch < times[1]
        assert any("the engine applies burns 2 and 3 in time order, not burn 1, as said below." in f
                   for f in prefill.filled)

    def test_the_samples_fit_the_budget_from_the_first_burn_applied(self) -> None:
        red_epoch = _NOW - timedelta(hours=5)
        early = (_NOW - timedelta(hours=70), red_epoch + timedelta(hours=1), _ARRIVE)
        prefill = _open(_state(_listed(burn_epoch=early[0], tof_hours=75.0, transfer_m_s=_transfer(*early))))
        from_first = _open(_state(_entry(burn_epoch=early[0], tof_hours=75.0)))
        # Counted from burn 2, at 05:00, not burn 1, 70 h ago: more samples fit.
        assert prefill.rows[0].samples > from_first.rows[0].samples

    def test_every_sentence_keeps_i13_and_the_house_style(self) -> None:
        times = (_NOW - timedelta(hours=6), _NOW - timedelta(hours=5), _ARRIVE)
        prefills = [_open(_state(_listed(transfer_m_s=_transfer()))),
                    _open(_state(_listed(burn_epoch=times[0], tof_hours=12.0, transfer_m_s=_transfer(*times))))]
        sentences = [s for p in prefills for s in (*p.filled, *p.left, *(line for r in p.rows for line in r.burn_lines))]
        assert [(s, i13_problems(s)) for s in sentences if i13_problems(s)] == []
        assert not any("—" in s or "--" in s for s in sentences)


class TestThePanelShowsTheBurnsBeforeEvaluate:
    def test_the_burns_are_listed_and_carried_in_a_hidden_field(self) -> None:
        page = TestThePanelRendersUnderStrictUndefined._render(
            pol=None, prefill=_open(_state(_listed(transfer_m_s=_transfer()))))
        rows = page.split("<script>", 1)[0]
        lead = re.search(r'<p class="hyp-transfer-lead"[^>]*>(.*?)</p>', rows, re.S)
        assert lead is not None
        assert " ".join(lead.group(1).split()) == (
            "This row carries 3 burns of one transfer as one action, listed in time order:")
        listed = re.search(r'<ol class="hyp-transfer"[^>]*>(.*?)</ol>', rows, re.S)
        assert listed is not None
        items = [re.sub(r"\s+", " ", i).strip() for i in re.findall(r"<li>(.*?)</li>", listed.group(1), re.S)]
        assert len(items) == 3 and items[1].startswith("Burn 2 at 12:00 UTC on 4 Nov, 12.9 m/s")
        hidden = re.findall(r'<input type="hidden" name="hyp_then" value="([^"]*)">', rows)
        assert hidden == [f"{_MID.isoformat()} -12.5 0.0 3.0;{_ARRIVE.isoformat()} 0.0 0.0 -2.0"]
        # The row builder's empty row posts the column too, blank, so the columns stay aligned.
        script = page.split("<script>", 1)[1]
        assert '<input type="hidden" name="hyp_then" value="">' in script

    def test_a_single_burn_panel_lists_nothing_and_posts_a_blank(self) -> None:
        page = TestThePanelRendersUnderStrictUndefined._render(pol=None, prefill=_open(_state(_entry())))
        rows = page.split("<script>", 1)[0]
        assert "hyp-transfer" not in rows
        assert re.findall(r'<input type="hidden" name="hyp_then" value="([^"]*)">', rows) == [""]

    def test_the_list_wraps_at_phone_width(self) -> None:
        page = TestThePanelRendersUnderStrictUndefined._render(
            pol=None, prefill=_open(_state(_listed(transfer_m_s=_transfer()))))
        listed = re.search(r'<ol class="hyp-transfer"[^>]*>', page)
        assert listed is not None and "overflow-wrap:anywhere" in listed.group(0)
        assert "white-space:nowrap" not in listed.group(0)
