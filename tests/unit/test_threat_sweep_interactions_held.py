"""The sweep judges close approaches and holds every edge per object (SPC-173).

The sweep adds what it learnt to the session's store for the red object and
reads back all that object holds, so an edge flown on an earlier sweep still
counts, and the intel card and the screen read the same edges. Closest
approaches are computed only from what the sweep already holds: the set from
before the burn, the set it flew and each target in reach. Nothing is fetched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.custody import Custody
from spectre.domain.interaction_graph import Edge, Miss, MissSource
from spectre.domain.models import ThreatTarget
from spectre.domain.threat_understanding import Dimension
from spectre.domain.warning_change import Change, TargetWarning, WarningChange
from spectre.domain.warning_change import Status as WarningStatus
from spectre.web import interaction_store
from spectre.web.routes import threat
from tests.unit.test_threat_understanding_sweep import _HELD, _NO_HISTORY, _RAISES, _SATNO, _held_history

_IN_REACH = TargetWarning("BLUE-1", True, None, 3.0, Change.NEWLY_IN_REACH)
_SOONER = TargetWarning("BLUE-2", True, 9.0, 2.0, Change.CUT)
_OUT = TargetWarning("BLUE-3", True, 9.0, None, Change.NO_LONGER_IN_REACH)
_TARGETS = [ThreatTarget("BLUE-1", "40001", "hrr", 1), ThreatTarget("BLUE-2", "", "manual", None),
            ThreatTarget("BLUE-3", "40003", "hrr", 3)]


def _basis(now: datetime) -> Any:
    return threat._SweepBasis(targets=list(_TARGETS), manual_tle_by_name={"BLUE-2": "manual set"},
                              frozen=threat._FrozenTargets({"40001": "frozen set", "40003": "other"}),
                              red_regime="LEO", max_dv_m_s=500.0, blue_satnos=frozenset({"40001"}), now=now)


def _figures(*rows: TargetWarning) -> WarningChange:
    return WarningChange(WarningStatus.FIGURES, "That burn put BLUE-1 in reach with 3h warning.", rows=rows)


def _after_raises() -> tuple[Any, datetime]:
    history = _held_history(_RAISES)
    return history, history.pol.records[-1].epoch + timedelta(hours=1)


def _state() -> Any:
    return SimpleNamespace(interaction_store=None, elset_histories={}, hrr_tle_data_mode={})


def _hold(state: Any, learnt: tuple[WarningChange, Any], history: Any, basis: Any,
          satno: str | None) -> interaction_store.HeldInteractions:
    """What the sweep holds after learning *learnt*, its warning change and its closest approaches."""
    return threat._hold_red_interactions(state, history, basis, satno, threat._Learnt(*learnt))


class TestAWarningEdgeCarriesItsTargetsNumber:
    def test_read_from_the_swept_target_of_that_name(self) -> None:
        history, now = _after_raises()
        edges = threat._interactions(_figures(_IN_REACH, _SOONER), history, _basis(now), _SATNO)
        assert {e.target: e.target_satno for e in edges} == {"BLUE-1": "40001", "BLUE-2": ""}


class TestTheTargetsSearched:
    def test_only_those_in_reach_after_the_burn_soonest_first_each_with_the_set_it_was_flown_with(self) -> None:
        history, now = _after_raises()
        targets = threat._computed_targets(_figures(_IN_REACH, _OUT, _SOONER), _basis(now))
        assert targets == [interaction_store.Target("BLUE-2", "", True, "manual set"),
                           interaction_store.Target("BLUE-1", "40001", True, "frozen set")]

    def test_a_row_naming_no_swept_target_has_no_set(self) -> None:
        history, now = _after_raises()
        stray = TargetWarning("GONE", False, None, 1.0, Change.NEWLY_IN_REACH)
        assert threat._computed_targets(_figures(stray), _basis(now)) == [
            interaction_store.Target("GONE", "", False, None)]


class TestTheComputedApproaches:
    def test_figures_search_from_the_set_before_the_first_burn_to_the_set_flown(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        history, now = _after_raises()
        seen: dict[str, Any] = {}

        def fake(burns: Any, before: str, after: str, targets: Any, at: datetime) -> Any:
            seen.update(burns=burns, before=before, after=after, targets=targets, at=at)
            return (), ("searched.",)

        monkeypatch.setattr(interaction_store, "computed_misses", fake)
        assert threat._red_computed(_figures(_IN_REACH), history, _basis(now), "flown set") == ((), ("searched.",))
        flown = threat._window_burns(history.pol, _basis(now))
        assert (seen["before"], seen["after"], seen["at"]) == (flown[0].tle_before.tle, "flown set", now)
        assert [b.epoch for b in seen["burns"]] == [m.burn_epoch for m in flown]
        assert [t.name for t in seen["targets"]] == ["BLUE-1"]

    @pytest.mark.parametrize("change", [WarningChange(WarningStatus.NO_BURN, "No confirmed burn."),
                                        WarningChange(WarningStatus.NOT_COMPUTED, "Custody is lost.")])
    def test_without_figures_nothing_is_searched(self, change: WarningChange) -> None:
        history, now = _after_raises()
        assert threat._red_computed(change, history, _basis(now), "flown set") is None

    def test_without_a_history_nothing_is_searched(self) -> None:
        _, now = _after_raises()
        assert threat._red_computed(_figures(_IN_REACH), _NO_HISTORY, _basis(now), "flown set") is None

    def test_a_failure_is_logged_and_stated_without_its_detail(
            self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def broken(*_a: Any) -> Any:
            raise RuntimeError("internal detail\nforged line")

        monkeypatch.setattr(interaction_store, "computed_misses", broken)
        history, now = _after_raises()
        with caplog.at_level("WARNING", logger=threat.logger.name):
            found = threat._red_computed(_figures(_IN_REACH), history, _basis(now), "flown set")
        assert found == ((), ("Closest approaches could not be computed on this sweep; the server log has the "
                              "detail.",))
        (record,) = [r for r in caplog.records if "Closest approaches" in r.getMessage()]
        assert "\nforged line" not in record.getMessage()


class TestTheSweepHoldsAndReadsBack:
    def test_the_warning_edges_and_computed_approaches_are_held_for_the_object(self) -> None:
        history, now = _after_raises()
        state = _state()
        flown = threat._window_burns(history.pol, _basis(now))
        miss = Miss("BLUE-1", "40001", True, MissSource.COMPUTED, flown[-1].burn_epoch + timedelta(hours=1), 9.0,
                    120.0, flown[0].burn_window[0] - timedelta(hours=1), 3.0)
        held = _hold(state, (_figures(_IN_REACH), ((miss,), ())), history, _basis(now), _SATNO)
        assert sorted(interaction_store.kind_of(e) for e in held.edges) == ["computed", "warning"]
        assert interaction_store.held_interactions(state, _SATNO, now).edges == held.edges

    def test_an_edge_from_an_earlier_sweep_still_counts_when_this_one_has_no_figures(self) -> None:
        history, now = _after_raises()
        state = _state()
        _hold(state, (_figures(_IN_REACH), ((), ())), history, _basis(now), _SATNO)
        no_burn = WarningChange(WarningStatus.NO_BURN, "No confirmed burn.")
        later = _hold(state, (no_burn, None), history, _basis(now + timedelta(hours=1)), _SATNO)
        assert [e.target for e in later.edges] == ["BLUE-1"]

    def test_without_a_history_what_is_held_is_still_read(self) -> None:
        history, now = _after_raises()
        state = _state()
        _hold(state, (_figures(_IN_REACH), ((), ())), history, _basis(now), _SATNO)
        held = _hold(state, (_figures(_IN_REACH), None), _NO_HISTORY, _basis(now), _SATNO)
        assert [e.target for e in held.edges] == ["BLUE-1"]

    def test_with_no_number_nothing_is_held_or_read(self) -> None:
        history, now = _after_raises()
        state = _state()
        held = _hold(state, (_figures(_IN_REACH), ((), ())), history, _basis(now), None)
        assert held == interaction_store.HeldInteractions()
        assert state.interaction_store is None

    def test_a_failure_holding_them_leaves_the_sweep_standing_and_stays_in_the_log(
            self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def broken(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("internal detail\nforged line")

        monkeypatch.setattr(interaction_store, "sweep_interactions", broken)
        history, now = _after_raises()
        with caplog.at_level("WARNING", logger=threat.logger.name):
            held = _hold(_state(), (_figures(_IN_REACH), None), history, _basis(now), _SATNO)
        assert held == interaction_store.HeldInteractions()
        (record,) = [r for r in caplog.records if "Interactions could not be held" in r.getMessage()]
        assert "\nforged line" not in record.getMessage()


class TestEveryPanelReadsTheHeldEdges:
    def _state_holding_one(self) -> tuple[Any, datetime]:
        history, now = _after_raises()
        state = _state()
        _hold(state, (_figures(_IN_REACH), ((), ())), history, _basis(now), _SATNO)
        return state, now

    def test_the_intel_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        monkeypatch.setattr(threat, "catalogue_entry", lambda _s: None)
        state, now = self._state_holding_one()
        view = threat._red_object_view(state, _SATNO, "", "REAL", now)
        assert view is not None
        assert [row["claim"] for row in view["ledger"] if row["dimension"] == "Interactions"] == [
            "BLUE-1 put in reach by its burn, 3h warning"]

    def test_the_red_model_is_given_the_held_edges_and_notes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        monkeypatch.setattr(threat, "catalogue_entry", lambda _s: None)
        history, now = _after_raises()
        edge = Edge(_SATNO, "BLUE-1", True, Change.NEWLY_IN_REACH, None, 3.0, now,
                    threat._interactions(_figures(_IN_REACH), history, _basis(now), _SATNO)[0].burns)
        context = threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD)
        red = threat._Red(_SATNO, "", "LEO", history, _HELD, context, (edge,), notes=("stated.",))
        worst = {"dv": 120.0, "access_level": "CRITICAL", "threat_level": "CRITICAL", "capability_level": "CRITICAL"}
        understanding = threat._red_understanding(red, worst, now)
        assert understanding is not None
        assert [r.item.dimension for r in understanding.range.ledger].count(Dimension.INTERACTIONS) == 1


class TestWhatTheHistoryConfirms:
    def test_its_confirmed_burns_and_where_it_starts(self) -> None:
        history, _ = _after_raises()
        confirmed = threat._history_burns(history.pol)
        assert confirmed == interaction_store.HistoryBurns(
            frozenset(m.burn_epoch for m in history.pol.manoeuvres), history.pol.records[0].epoch)

    def test_a_history_with_no_element_set_confirms_nothing(self) -> None:
        assert threat._history_burns(SimpleNamespace(records=[], manoeuvres=[])) is None


class TestAConfiguredSeedReachesTheRedModel:
    def test_a_path_to_a_hostile_seed_is_graded_and_the_list_is_stated(
            self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        seeds = tmp_path / "seeds.json"
        seeds.write_text(json.dumps({"seeds": [{"satno": "40001", "disposition": "hostile"}]}), encoding="utf-8")
        monkeypatch.setenv("SPECTRE_HOSTILE_SEEDS", str(seeds))
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        monkeypatch.setattr(threat, "catalogue_entry", lambda _s: None)
        history, now = _after_raises()
        held = _hold(_state(), (_figures(_IN_REACH), ((), ())), history, _basis(now), _SATNO)
        assert [(p.seed, p.hops) for p in held.paths] == [("40001", 1)]
        assert held.notes[-1] == "hostile seed list held: 1 hostile seed; a benign entry propagates nothing"
        context = threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD)
        red = threat._Red(_SATNO, "", "LEO", history, _HELD, context, held.edges, held.notes, held.paths)
        worst = {"dv": 120.0, "access_level": "CRITICAL", "threat_level": "CRITICAL", "capability_level": "CRITICAL"}
        understanding = threat._red_understanding(red, worst, now)
        assert understanding is not None
        assert [r.item.label for r in understanding.range.ledger if r.item.derived_from == f"seed:{_SATNO}"] == [
            "1 hop from hostile seed BLUE-1 (40001)"]

    def test_the_sweep_page_names_the_seed_on_screen_and_in_the_ledger(
            self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        # Concept section 9, decisions 5 and 15 (SPC-180): the seed is named by catalogue number and name.
        from tests.unit.test_threat_understanding_display import _block, _render, _strip, _text

        seeds = tmp_path / "seeds.json"
        seeds.write_text(json.dumps({"seeds": [{"satno": "40001", "disposition": "hostile"}]}), encoding="utf-8")
        monkeypatch.setenv("SPECTRE_HOSTILE_SEEDS", str(seeds))
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        monkeypatch.setattr(threat, "catalogue_entry", lambda _s: None)
        history, now = _after_raises()
        held = _hold(_state(), (_figures(_IN_REACH), ((), ())), history, _basis(now), _SATNO)
        context = threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD)
        red = threat._Red(_SATNO, "", "LEO", history, _HELD, context, held.edges, held.notes, held.paths)
        from tests.unit.test_threat_sweep_template import _context

        worst = _context()["worst_coa"]
        shadowed = threat._with_understanding(worst, threat._red_understanding(red, worst, now), held.notes)
        page = _render("partials/threat_sweep.html", _context(worst_coa=shadowed))
        ledger = _text(_block(page, '<details class="tu-ledger"', "details"))
        assert "1 hop from hostile seed BLUE-1 (40001)" in ledger
        assert "1 hop from hostile seed BLUE-1 (40001)" in _strip(page)


class TestTheSweepsOneCall:
    def test_it_searches_off_the_event_loop_and_holds_what_it_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio
        import threading

        history, now = _after_raises()
        loop_thread: list[str] = []

        def searched(_c: Any, _h: Any, _b: Any, red_tle: str) -> Any:
            loop_thread.append(threading.current_thread().name)
            assert red_tle == "flown set"
            return (), ("searched.",)

        monkeypatch.setattr(threat, "_red_computed", searched)
        state = _state()
        held = asyncio.run(threat._sweep_interactions(state, _figures(_IN_REACH), history, _basis(now),
                                                      (_SATNO, "flown set")))
        assert loop_thread and loop_thread[0] != threading.main_thread().name
        assert "searched." in held.notes
        assert [e.target for e in held.edges] == ["BLUE-1"]
