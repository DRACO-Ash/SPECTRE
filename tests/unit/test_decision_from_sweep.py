"""A decision scenario opened from a threat-sweep entry (SPC-150).

The operator's question is "something moved: can it reach one of mine, how
long have I got, and what do I need to decide, by when?" The sweep answers
the first two; the Decision Engine weighs responses. Opening a scenario from
a sweep entry fills only what the sweep knows: the red track it flew, the
target when it is a held blue asset, the transfer's departure burn as a
hypothesis, and the latest detected burn from the element-set history,
started from the element set before it (SPC-001). It fills no probability and
no confidence (concept 7.5), evaluates nothing, and says what it filled, from
which sweep, and what it could not fill and why.

Nothing here reads the wall clock or reaches the network: every clock is a
fixed moment, and the held history is a stand-in placed in the session.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.astro.pattern_of_life import Manoeuvre, TLERecord
from spectre.domain import decision
from spectre.domain import threat_understanding as tu
from spectre.domain.models import BlueAsset, RedTrack, ThreatAssessment, ThreatSweepEntry, ThreatTarget
from spectre.domain.threat_assessment import Band
from spectre.web import decision_from_sweep as dfs
from tests.unit._i13 import i13_problems
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_SWEPT = _NOW - timedelta(minutes=10)
_RED_TLE = _tle(_NOW - timedelta(hours=5), satno=50322)
_BLUE_TLE = _tle(_NOW - timedelta(hours=5), satno=40001)


def _entry(**kw: Any) -> ThreatSweepEntry:
    fields: dict[str, Any] = {
        "target": ThreatTarget("ALPHA", "40001", "hrr", 1),
        "burn_epoch": _NOW + timedelta(hours=1), "burn_location": "apogee", "delta_v_m_s": 70.0,
        "tof_hours": 5.0, "dv_prograde": 60.0, "dv_normal": 40.0, "dv_radial": 0.0, "method": "lambert",
        "regime": "GEO", "departure_m_s": (30.0, 40.0, 0.0),
    }
    fields.update(kw)
    return ThreatSweepEntry(**fields)


def _state(*entries: ThreatSweepEntry, red_tle: str = _RED_TLE, blue: bool = True, **kw: Any) -> Any:
    assessment = ThreatAssessment(
        red_name="RX", sweep_epoch=_SWEPT, entries=list(entries or [_entry()]), target_count=1, red_tle=red_tle,
    )
    fields: dict[str, Any] = {
        "last_threat_assessment": assessment,
        "red_tracks": [RedTrack("RX", _RED_TLE, data_mode="REAL")],
        "blue_assets": [BlueAsset("Alpha", _BLUE_TLE, data_mode="REAL")] if blue else [],
        "elset_histories": {}, "threat_picture": None,
    }
    fields.update(kw)
    return SimpleNamespace(**fields)


def _open(state: Any, entry: str = "0", sweep: str | None = None, now: datetime = _NOW) -> dfs.SweepPrefill:
    return dfs.open_from_sweep(state, entry, _SWEPT.isoformat() if sweep is None else sweep, now)


def _record(epoch: datetime) -> TLERecord:
    return TLERecord(
        epoch=epoch, tle=_tle(epoch, satno=50322), sma_km=42164.0, ecc=0.0002, inc_deg=0.05, raan_deg=0.0,
        argp_deg=0.0, mean_anomaly_deg=0.0, mean_motion_revday=1.0027, bstar=0.0, alt_km=35786.0,
        period_min=1436.0, regime="GEO",
    )


def _burn(at: datetime, dv_km_s: float = 0.013) -> Manoeuvre:
    before = _record(at - timedelta(hours=12))
    return Manoeuvre(
        epoch=at, gap_days=0.5, delta_v_km_s=dv_km_s, delta_alt_km=0.0, delta_inc_deg=0.0, delta_ecc=0.0,
        delta_raan_corrected_deg=0.0, delta_argp_corrected_deg=0.0, delta_period_s=0.0, delta_drift_deg_day=None,
        dominant_element="altitude", tle_before=before, tle_after=_record(at),
    )


def _history(*burns: Manoeuvre, problem: str = "") -> Any:
    from spectre.web.routes.pol import HeldHistory

    if problem:
        return HeldHistory(50322, _NOW - timedelta(minutes=12), problem=problem)
    pol = SimpleNamespace(regime="GEO", manoeuvres=list(burns), records=[_record(_NOW - timedelta(days=9))],
                          span_days=9.0, satno=50322, name="RX", tle_count=40, history_truncated_at=None)
    return HeldHistory(50322, _NOW - timedelta(minutes=12), pol=pol)


class TestWhatIsPrefilled:
    def test_the_red_track_the_sweep_flew_and_the_target_held_as_a_blue_asset_are_bound(self) -> None:
        prefill = _open(_state())
        assert prefill.problem == ""
        assert (prefill.red, prefill.blue) == ("RX", "Alpha")
        assert "Red track: RX, the object the sweep flew." in prefill.filled
        assert "Blue asset: Alpha, the target ALPHA, held as a blue asset (SATNO 40001)." in prefill.filled

    def test_the_hypothesis_is_the_transfers_departure_burn_read_in_ric(self) -> None:
        row = _open(_state()).rows[0]
        assert row.archetype == "intercept_approach"
        assert row.dv_m_s == "50"
        # (radial, in-track, cross-track) from the solver's (prograde, normal, radial) = (30, 40, 0).
        assert row.direction == ("0", "0.6", "0.8")
        assert row.burn_at == _NOW + timedelta(hours=1)
        assert row.detected is False
        assert row.name == "Least-warning LAMBERT transfer to ALPHA"

    def test_the_horizon_covers_the_arrival_and_the_samples_fit_the_budget(self) -> None:
        prefill = _open(_state())
        # Burn at +1 h, 5 h of flight: arrival 6 h from now, so 7 h.
        assert prefill.horizon_h == "7"
        assert prefill.rows[0].samples == 500
        assert any(s.startswith("Horizon 7 h, to cover the sweep's arrival at 15:00 UTC") for s in prefill.filled)

    def test_the_panel_says_which_sweep_and_entry_it_came_from(self) -> None:
        prefill = _open(_state())
        assert prefill.source == (
            "Opened from the sweep of RX at 08:50 UTC on 4 Nov, 10 min ago: its LAMBERT transfer to ALPHA "
            "[40001], departing at 10:00 UTC on 4 Nov and arriving in 5h."
        )
        assert prefill.scenario_name == "RX on ALPHA, from the sweep at 08:50 UTC"

    def test_probability_and_confidence_are_never_prefilled_and_nothing_is_evaluated(self) -> None:
        prefill = _open(_state())
        names = {f.name for f in dataclasses.fields(prefill)} | {f.name for f in dataclasses.fields(prefill.rows[0])}
        assert not names & {"probability", "confidence", "prob", "conf", "gap"}
        assert (
            "Not pre-filled: P, Conf and Gap keep the engine's defaults, and the friendly responses are yours to "
            "set. Nothing is evaluated until you press Evaluate."
        ) in prefill.left

    def test_a_departure_with_a_negative_zero_part_reads_zero_not_minus_zero(self) -> None:
        row = _open(_state(_entry(departure_m_s=(30.0, 40.0, -0.0)))).rows[0]
        assert row.direction == ("0", "0.6", "0.8")

    @pytest.mark.parametrize(("minutes", "ago"), [(119, "119 min ago"), (120, "2 h ago")])
    def test_the_sweeps_age_reads_in_minutes_below_two_hours_and_in_hours_from_them(self, minutes: int,
                                                                                    ago: str) -> None:
        prefill = _open(_state(), now=_SWEPT + timedelta(minutes=minutes))
        assert prefill.source.startswith(f"Opened from the sweep of RX at 08:50 UTC on 4 Nov, {ago}: ")

    def test_a_departure_already_past_says_the_hypothesis_is_that_it_burned_then(self) -> None:
        prefill = _open(_state(_entry(burn_epoch=_SWEPT, burn_location="now")))
        assert prefill.rows[0].burn_at == _SWEPT
        assert any("Its departure is before now, so the hypothesis is that it burned then." in s
                   for s in prefill.filled)


class TestWhatCannotBeBound:
    def test_a_target_not_held_as_a_blue_asset_is_left_unbound_and_says_why(self) -> None:
        prefill = _open(_state(blue=False))
        assert prefill.blue == ""
        assert (
            "Blue asset not bound: ALPHA [40001] is not held as a blue asset in this session. Add it under Blue "
            "Assets to bind it."
        ) in prefill.left

    def test_a_blue_asset_with_another_catalogue_number_is_not_bound(self) -> None:
        other = BlueAsset("Bravo", _tle(_NOW - timedelta(hours=5), satno=40002), data_mode="REAL")
        prefill = _open(_state(blue_assets=[other]))
        assert prefill.blue == ""
        assert (
            "Blue asset not bound: ALPHA [40001] is not held as a blue asset in this session. Add it under Blue "
            "Assets to bind it."
        ) in prefill.left

    def test_the_blue_asset_carrying_the_targets_number_is_bound_among_others(self) -> None:
        other = BlueAsset("Bravo", _tle(_NOW - timedelta(hours=5), satno=40002), data_mode="REAL")
        alpha = BlueAsset("Alpha", _BLUE_TLE, data_mode="REAL")
        assert _open(_state(blue_assets=[other, alpha])).blue == "Alpha"

    @pytest.mark.parametrize("satno", ["\u00b2", "\u0664\u0660\u0660\u0660\u0661", "4" * 5000],
                             ids=["superscript", "arabic-indic-40001", "5000-digits"])
    def test_a_catalogue_number_int_would_refuse_or_misread_binds_nothing(self, satno: str) -> None:
        prefill = _open(_state(_entry(target=ThreatTarget("ALPHA", satno, "hrr", 1))))
        assert prefill.blue == ""
        assert any(s.startswith("Blue asset not bound: ALPHA [") for s in prefill.left)

    def test_a_target_with_no_catalogue_number_is_not_matched_by_name(self) -> None:
        state = _state(_entry(target=ThreatTarget("Alpha", "", "manual", None)))
        prefill = _open(state)
        assert prefill.blue == ""
        assert "Blue asset not bound: Alpha has no catalogue number to match a held blue asset by." in prefill.left

    def test_a_red_set_other_than_the_one_held_is_not_bound_and_fills_no_hypothesis(self) -> None:
        prefill = _open(_state(red_tle=_tle(_NOW - timedelta(hours=2), satno=50322)))
        assert prefill.red == ""
        assert [row.archetype for row in prefill.rows] == [""]
        assert (
            "Red track not bound: the sweep flew a red element set other than the one now held for RX (a manual "
            "override, or the held set was refreshed since), so no hypothesis is pre-filled. Sweep again to open "
            "from the held set."
        ) in prefill.left

    def test_a_red_object_not_held_as_a_red_track_is_not_bound(self) -> None:
        prefill = _open(_state(red_tracks=[]))
        assert prefill.red == ""
        assert (
            "Red track not bound: RX is not held as a red track in this session, so no hypothesis is pre-filled."
        ) in prefill.left

    def test_a_zero_departure_burn_has_no_direction_so_stays_a_lookup(self) -> None:
        prefill = _open(_state(_entry(departure_m_s=(0.0, 0.0, 0.0))))
        assert [(row.archetype, row.dv_m_s, row.direction) for row in prefill.rows] == [("", "", ("", "", ""))]
        assert (
            "Adversary row 1 stays a lookup: the sweep's departure burn for this entry is zero, so it has no "
            "direction."
        ) in prefill.left

    def test_a_transfer_too_long_for_the_budget_at_the_fewest_samples_says_the_engine_will_refuse_it(self) -> None:
        # Burn at +1 h and 120 h of flight: a 122 h horizon, past what 100 samples on one row fit (117.5 h under
        # the 300 s budget, SPC-178).
        fits = decision.longest_horizon_h(100)
        assert fits < 122
        prefill = _open(_state(_entry(tof_hours=120.0)))
        assert prefill.horizon_h == "122"
        assert prefill.rows[0].samples == 100
        assert (
            f"At 100 samples a row the evaluation's budget covers about {fits} h, short of the 122 h this scenario "
            "needs, so the engine will refuse it as over its budget: remove a row, or shorten the horizon, which "
            "then ends before the arrival."
        ) in prefill.left
        assert not any(s.endswith("that fit the evaluation's budget over that horizon.") for s in prefill.filled)

    def test_an_entry_with_no_departure_burn_stays_a_lookup(self) -> None:
        prefill = _open(_state(_entry(departure_m_s=None)))
        assert prefill.rows[0].archetype == ""
        assert (
            "Adversary row 1 stays a lookup: the sweep's solution for this entry carries no departure burn."
        ) in prefill.left


class TestWhatIsRefused:
    @pytest.mark.parametrize("sweep", ["", "2026-11-04T08:00:00+00:00"])
    def test_a_sweep_that_is_not_the_latest_held_fills_nothing(self, sweep: str) -> None:
        prefill = _open(_state(), sweep=sweep)
        assert prefill.problem == (
            "The sweep this was opened from is no longer the latest held. Open the scenario from the latest sweep."
        )
        assert (prefill.red, prefill.blue, prefill.rows) == ("", "", ())

    def test_no_sweep_held_fills_nothing(self) -> None:
        prefill = _open(_state(last_threat_assessment=None))
        assert prefill.problem == "No threat sweep is held. Run a sweep, then open a scenario from one of its entries."

    @pytest.mark.parametrize("entry", ["1", "-1", "x", "", "\u00b2", "\u0660", "9" * 5000],
                             ids=["past-the-end", "negative", "word", "blank", "superscript", "arabic-indic",
                                  "5000-digits"])
    def test_an_entry_the_sweep_does_not_hold_fills_nothing(self, entry: str) -> None:
        # A superscript or Arabic-Indic digit passes str.isdigit, and 5000 digits pass it too: each is refused
        # as a sentence, never a ValueError from int().
        assert _open(_state(), entry=entry).problem == (
            "That entry is not in the latest sweep. Open the scenario from the latest sweep."
        )

    def test_an_entry_that_only_aligns_the_planes_has_no_transfer_to_hypothesise(self) -> None:
        prefill = _open(_state(_entry(method="plane_change", arrives=False)))
        assert prefill.problem == (
            "This entry only aligns the planes and reaches no target, so it has no transfer to open as a scenario."
        )

    def test_an_arrival_already_past_fills_nothing(self) -> None:
        prefill = _open(_state(), now=_NOW + timedelta(hours=6))
        assert prefill.problem == "This entry's arrival, at 15:00 UTC on 4 Nov, has passed. Sweep again to open a current one."


class TestTheDetectedBurn:
    """For a detected manoeuvre the element-set history is used, through hypothesis_from_tle_record (SPC-001)."""

    def test_the_latest_detected_burn_in_72_h_is_offered_from_the_element_set_before_it(self) -> None:
        at = _NOW - timedelta(hours=6)
        state = _state(elset_histories={50322: _history(_burn(_NOW - timedelta(hours=40)), _burn(at))})
        prefill = _open(state)
        assert [row.detected for row in prefill.rows] == [False, True]
        detected = prefill.rows[1]
        assert detected.burn_at == at
        assert detected.archetype == "repositioning"
        assert detected.name == "Detected burn at 03:00 UTC on 4 Nov"
        assert (detected.dv_m_s, detected.direction) == ("", ("", "", ""))
        assert (
            "Adversary row 2: the burn detected at 03:00 UTC on 4 Nov in RX's element-set history, started from "
            "the element set before it, with the Repositioning archetype's dispersions, as the history classes the "
            "burn."
        ) in prefill.filled

    def test_a_burn_older_than_the_held_red_set_is_said_not_to_be_sampled(self) -> None:
        """The engine refuses to sample a burn the bound red element set may already include (decision._after_burn).

        A detected burn is found from the element set after it, so the held red set is nearly always newer: the
        row is offered for its burn time, which sets when custody is lost, and the panel says it is not sampled.
        """
        state = _state(elset_histories={50322: _history(_burn(_NOW - timedelta(hours=6)))})
        prefill = _open(state)
        assert [row.sampled for row in prefill.rows] == [True, False]
        # The departure row alone counts against the budget.
        assert [row.samples for row in prefill.rows] == [500, 500]
        assert (
            "The engine will not sample row 2's closest approach: the red element set held for RX dates from 04:00 "
            "UTC on 4 Nov, after the burn, so it may already include it. The row's burn time still sets when "
            "custody is lost."
        ) in prefill.left

    def test_a_burn_at_the_held_red_sets_own_epoch_is_sampled(self) -> None:
        # The engine skips only a burn strictly before the red set's epoch (decision._after_burn is epoch > burn).
        from spectre.web.elsets import elset_age

        age = elset_age(_RED_TLE, _NOW)
        assert age is not None
        prefill = _open(_state(elset_histories={50322: _history(_burn(age.epoch))}))
        assert [row.sampled for row in prefill.rows] == [True, True]
        assert not any(s.startswith("The engine will not sample row 2") for s in prefill.left)

    def test_a_held_history_30_min_old_or_more_says_a_later_burn_may_be_missing(self) -> None:
        held = dataclasses.replace(_history(_burn(_NOW - timedelta(hours=6))), fetched_at=_NOW - timedelta(minutes=30))
        prefill = _open(_state(elset_histories={50322: held}))
        assert [row.detected for row in prefill.rows] == [False, True]
        assert (
            "RX's element-set history was fetched 30 min ago, 30 min or more, so a burn since then may not be in "
            "it. Sweep again to refresh it."
        ) in prefill.left

    def test_a_held_history_under_30_min_old_says_nothing_of_its_age(self) -> None:
        held = dataclasses.replace(_history(_burn(_NOW - timedelta(hours=6))), fetched_at=_NOW - timedelta(minutes=29))
        prefill = _open(_state(elset_histories={50322: held}))
        assert not any("element-set history was fetched" in s for s in prefill.left)

    def test_two_sampled_rows_take_fewer_samples_to_fit_the_budget(self) -> None:
        state = _state(_entry(tof_hours=20.0), elset_histories={50322: _history(_burn(_NOW - timedelta(hours=4)))})
        prefill = _open(state)
        # A burn after the held red set's epoch is sampled. Two rows over 22 h of horizon plus the 4 h since the
        # detected burn: 26 h, which 250 samples a row do not fit and 200 do.
        assert decision.longest_horizon_h(250, rows=2) < 26 <= decision.longest_horizon_h(200, rows=2)
        assert [row.sampled for row in prefill.rows] == [True, True]
        assert [row.samples for row in prefill.rows] == [200, 200]

    def test_a_burn_more_than_72_h_old_is_not_offered(self) -> None:
        state = _state(elset_histories={50322: _history(_burn(_NOW - timedelta(hours=73)))})
        prefill = _open(state)
        assert [row.detected for row in prefill.rows] == [False]
        assert (
            "No detected burn is offered: RX's latest confirmed burn, at 08:00 UTC on 1 Nov, is more than 72 h "
            "before now, older than a hypothesis may start."
        ) in prefill.left

    def test_a_burn_exactly_72_h_old_is_still_offered(self) -> None:
        # The window is inclusive at 72 h, the same [low, high] rule a burn hour typed into the panel meets.
        state = _state(elset_histories={50322: _history(_burn(_NOW - timedelta(hours=72)))})
        prefill = _open(state)
        assert [row.detected for row in prefill.rows] == [False, True]
        assert not any("more than 72 h" in s for s in prefill.left)

    @pytest.mark.parametrize(("histories", "why"), [
        ({}, "no element-set history is held for RX."),
        ({50322: None}, "no element-set history is held for RX."),
        ({50322: "problem"}, "UDL returned no element sets for this object."),
        ({50322: "empty"}, "RX's element-set history holds no confirmed burn."),
    ])
    def test_with_no_burn_to_offer_it_says_why(self, histories: dict[int, Any], why: str) -> None:
        held = {
            k: (_history(problem="UDL returned no element sets for this object.") if v == "problem"
                else _history() if v == "empty" else v)
            for k, v in histories.items()
        }
        prefill = _open(_state(elset_histories=held))
        assert f"No detected burn is offered: {why}" in prefill.left

    def test_without_a_bound_red_track_no_detected_burn_is_offered(self) -> None:
        state = _state(red_tracks=[], elset_histories={50322: _history(_burn(_NOW - timedelta(hours=6)))})
        assert [row.detected for row in _open(state).rows] == [False]

    def test_the_held_burn_is_found_again_by_its_burn_time(self) -> None:
        at = _NOW - timedelta(hours=6)
        burn = _burn(at)
        state = _state(elset_histories={50322: _history(burn)})
        assert dfs.detected_burn(state, 50322, at) is burn
        assert dfs.detected_burn(state, 50322, at + timedelta(seconds=1)) is None
        assert dfs.detected_burn(state, None, at) is None
        assert dfs.detected_burn(_state(), 50322, at) is None


class TestThePictureTheEngineWillRead:
    def _picture(self, red: str = "RX") -> decision.ThreatPicture:
        return decision.ThreatPicture(
            red=red, floor=Band.MEDIUM, ceiling=Band.CRITICAL, understanding=tu.Understanding.LOW, cues=(),
            decide_at=None, decide_by="", assessed_at=_SWEPT,
        )

    def test_a_picture_for_the_red_track_is_named_with_its_age(self) -> None:
        prefill = _open(_state(threat_picture=self._picture()))
        assert (
            "The engine reads the sweep's Threat picture for RX, assessed 10 min ago, and shows its age beside every "
            "figure it feeds."
        ) in prefill.left

    def test_a_picture_hours_old_is_read_and_its_age_said(self) -> None:
        """SPC-181: the picture is read at any age; the prefill says how old it is, never that it will not be read."""
        prefill = _open(_state(threat_picture=self._picture()), now=_SWEPT + timedelta(hours=3, minutes=10))
        assert (
            "The engine reads the sweep's Threat picture for RX, assessed 3 h 10 min ago, and shows its age beside "
            "every figure it feeds."
        ) in prefill.left
        assert not any("30 min old" in line for line in prefill.left)

    @pytest.mark.parametrize("picture", [None, "other", "later"])
    def test_with_no_picture_it_reads_for_the_red_track_it_says_none_is_read(self, picture: str | None) -> None:
        """A picture for another red track, or one assessed after now, whose age cannot be said, is not read."""
        held = {None: None, "other": self._picture("OTHER"),
                "later": dataclasses.replace(self._picture(), assessed_at=_NOW + timedelta(minutes=1))}[picture]
        prefill = _open(_state(threat_picture=held))
        assert "The engine reads no Threat picture from the sweep for RX." in prefill.left


class TestTheOperatorText:
    @pytest.mark.parametrize("case", ["detected", "old-history", "over-budget", "zero-departure", "unbound"])
    def test_every_sentence_keeps_i13(self, case: str) -> None:
        old = dataclasses.replace(_history(_burn(_NOW - timedelta(hours=6))), fetched_at=_NOW - timedelta(hours=3))
        state = {
            "detected": _state(elset_histories={50322: _history(_burn(_NOW - timedelta(hours=6)))}),
            "old-history": _state(elset_histories={50322: old}),
            "over-budget": _state(_entry(tof_hours=60.0)),
            "zero-departure": _state(_entry(departure_m_s=(0.0, 0.0, 0.0))),
            "unbound": _state(red_tracks=[], blue=False),
        }[case]
        prefill = _open(state)
        sentences = [prefill.source, *prefill.filled, *prefill.left, *(row.name for row in prefill.rows)]
        assert [(s, i13_problems(s)) for s in sentences if i13_problems(s)] == []
        assert not any("—" in s or "--" in s for s in sentences)


class TestThePanelRendersUnderStrictUndefined:
    """Every name the filled panel reads is supplied, with the app's own filters, and the plain panel still renders."""

    @staticmethod
    def _render(**context: Any) -> str:
        from pathlib import Path

        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        from spectre.web.app import templates as app_templates

        root = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
        env = Environment(loader=FileSystemLoader(str(root)), autoescape=True, undefined=StrictUndefined)
        env.filters.update(app_templates.env.filters)
        return env.get_template("partials/decision_panel.html").render(**context)

    def test_a_filled_panel_with_a_detected_row(self) -> None:
        state = _state(elset_histories={50322: _history(_burn(_NOW - timedelta(hours=6)))})
        page = self._render(pol=None, prefill=_open(state))
        assert page.count('name="hyp_detected" value="1"') == 1
        assert "Fixed at 03:00 UTC on 4 Nov from the sweep" in page
        rows = page.split("<script>", 1)[0]
        blocks = re.findall(r'<details class="adv-hypothesis"[^>]*>.*?</details>', rows, re.S)
        assert len(blocks) == 2
        # Each filled hypothesis opens, so the operator sees what was filled without expanding it.
        assert [re.match(r'<details[^>]*\sopen>', b) is not None for b in blocks] == [True, True]
        # The detected row's delta-V and direction are the detection's: read-only, so nothing typed there is
        # silently ignored. The departure row's stay editable.
        for name in ("hyp_dv", "hyp_dir_r", "hyp_dir_i", "hyp_dir_c"):
            fields = [re.search(rf'<input[^>]*name="{name}"[^>]*>', b) for b in blocks]
            assert [f is not None and " readonly" in f.group(0) for f in fields] == [False, True], name

    def test_a_plain_panel_row_is_closed_and_editable(self) -> None:
        plain = self._render(pol=None).split("<script>", 1)[0]
        assert re.search(r'<details class="adv-hypothesis"[^>]*\sopen>', plain) is None
        assert " readonly" not in plain

    def test_a_refused_and_a_plain_panel(self) -> None:
        refused = self._render(pol=None, prefill=_open(_state(), entry="9"))
        assert "That entry is not in the latest sweep." in refused
        plain = self._render(pol=None)
        assert 'value="Unnamed Scenario"' in plain and "decision-prefill" not in plain
