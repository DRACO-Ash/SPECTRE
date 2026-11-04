"""Interactions held per object between sweeps (SPC-173).

An edge is learnt on the sweep that flies it, but the object keeps it: a
later sweep, the intel card and the screen read the edges the session holds
for that object, ageing on Interactions' 30-day half-life. A sweep that
evaluates the same burns again replaces what it re-evaluated, so a figure
superseded by newer element sets does not linger, and an edge older than
four half-lives is dropped. UDL conjunctions are held as the operator looked
them up; the sweep reads them and never fetches.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain import interaction_graph as ig
from spectre.domain.interaction_graph import Burn, Edge, Miss, MissEdge, MissSource
from spectre.domain.warning_change import Change
from spectre.web import interaction_store as store
from spectre.web.udl_conjunction import ConjunctionReading, ConjunctionRow
from tests.unit._decision_reference import EPOCH, GEO_DRIFT_IN
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)
_ACTOR = "41838"


def _burn(epoch: datetime = _BURN) -> Burn:
    return Burn(epoch=epoch, earliest=epoch, latest=epoch, confirmed=True, detection="HIGH", provider="18SDS")


def _warning(target: str = "BLUE-1", burn: Burn | None = None, satno: str = "40001") -> Edge:
    return Edge(_ACTOR, target, True, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (burn or _burn(),), target_satno=satno)


def _miss_edge(source: MissSource = MissSource.COMPUTED, target: str = "BLUE-1") -> MissEdge:
    return MissEdge(_ACTOR, target, "40001", True, source, 140.0, 12.0, _BURN + timedelta(hours=5), (_burn(),))


def _state() -> Any:
    return SimpleNamespace(interaction_store=None)


def _hold(state: Any, edges: tuple[Any, ...], *, burns: tuple[Burn, ...] = (_burn(),),
          kinds: frozenset[str] = store.SWEPT_KINDS, now: datetime = _NOW) -> None:
    store.hold_edges(state, _ACTOR, edges, now, store.Evaluated(tuple(burns), kinds))


class TestEdgesAreHeldPerObject:
    def test_a_sweeps_edges_are_read_back_for_the_same_object_only(self) -> None:
        state = _state()
        _hold(state, (_warning(),))
        assert store.held_interactions(state, _ACTOR, _NOW).edges == (_warning(),)
        assert store.held_interactions(state, "99999", _NOW).edges == ()

    def test_the_object_number_is_read_as_a_number(self) -> None:
        state = _state()
        store.hold_edges(state, "041838", (_warning(),), _NOW, store.Evaluated((_burn(),), store.SWEPT_KINDS))
        assert store.held_interactions(state, " 41838 ", _NOW).edges == (_warning(),)

    def test_a_session_with_none_held_reads_none(self) -> None:
        held = store.held_interactions(SimpleNamespace(), _ACTOR, _NOW)
        assert (held.edges, held.paths) == ((), ())

    def test_edges_on_burns_this_sweep_did_not_evaluate_are_kept(self) -> None:
        state = _state()
        old = _burn(_BURN - timedelta(days=20))
        _hold(state, (_warning("BLUE-OLD", old),), burns=(old,))
        _hold(state, (_warning(),))
        assert {e.target for e in store.held_interactions(state, _ACTOR, _NOW).edges} == {"BLUE-OLD", "BLUE-1"}

    def test_edges_on_the_same_burns_are_replaced_by_the_new_evaluation(self) -> None:
        """A figure superseded by newer element sets does not linger."""
        state = _state()
        _hold(state, (_warning("BLUE-1"), _miss_edge()))
        _hold(state, (_warning("BLUE-2"),))
        assert [e.target for e in store.held_interactions(state, _ACTOR, _NOW).edges] == ["BLUE-2"]

    def test_an_edge_on_two_burns_is_kept_when_a_sweep_re_judges_only_one(self) -> None:
        """Review finding 5: the sweep judged the newer burn, not the pair the edge rests on, so it stands."""
        state = _state()
        older = _burn(_BURN - timedelta(days=2))
        both = Edge(_ACTOR, "BLUE-PAIR", True, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (older, _burn()),
                    target_satno="40003")
        _hold(state, (both,), burns=(older, _burn()))
        _hold(state, (_warning(),))
        assert {e.target for e in store.held_interactions(state, _ACTOR, _NOW).edges} == {"BLUE-PAIR", "BLUE-1"}

    def test_only_the_kinds_evaluated_are_replaced(self) -> None:
        """A sweep with no warning-change figures leaves the warning and computed edges it could not re-judge."""
        state = _state()
        _hold(state, (_warning(), _miss_edge(), _miss_edge(MissSource.UDL)))
        _hold(state, (), kinds=frozenset({store.UDL_KIND}))
        # Held in one order whatever the arrival order: by burn, then source, then target.
        assert store.held_interactions(state, _ACTOR, _NOW).edges == (_miss_edge(), _warning())

    def test_an_edge_older_than_four_half_lives_is_dropped(self) -> None:
        assert timedelta(days=120) == store.EDGE_MAX_AGE
        state = _state()
        _hold(state, (_warning(),))
        assert store.held_interactions(state, _ACTOR, _BURN + timedelta(days=120)).edges == (_warning(),)
        assert store.held_interactions(state, _ACTOR, _BURN + timedelta(days=120, minutes=1)).edges == ()

    def test_at_most_50_are_held_per_object_the_newest_kept(self) -> None:
        state = _state()
        edges = tuple(_warning(f"T-{k:02d}", _burn(_BURN - timedelta(hours=k))) for k in range(store.MAX_EDGES + 5))
        _hold(state, edges, burns=tuple(e.burns[0] for e in edges))
        held = store.held_interactions(state, _ACTOR, _NOW).edges
        assert len(held) == store.MAX_EDGES == 50
        assert {e.target for e in held} == {f"T-{k:02d}" for k in range(50)}


def _row(other: str, tca: datetime, miss_km: float | None, *, problem: str = "", name: str = "") -> ConjunctionRow:
    return ConjunctionRow(other_satno=other, other_name=name, tca=tca, miss_distance="as filed",
                          collision_prob="not given", data_mode="REAL", miss_km=miss_km, miss_problem=problem)


def _filed(row: ConjunctionRow, mode: str) -> ConjunctionRow:
    return dataclasses.replace(row, data_mode=mode)


def _reading(*rows: ConjunctionRow) -> ConjunctionReading:
    return ConjunctionReading(rows=list(rows), usable=len(rows), skipped=0)


class TestConjunctionsAreHeldAsLookedUp:
    def test_a_lookup_is_held_for_its_object(self) -> None:
        state = _state()
        rows = (_row("40001", _BURN, 12.0),)
        store.hold_conjunctions(state, 41838, _reading(*rows), "REAL", _NOW)
        held = store.interaction_store(state).conjunctions[_ACTOR]
        assert (held.rows, held.looked_up_at, held.data_mode) == (rows, _NOW, "REAL")

    def test_each_row_is_judged_against_the_latest_readable_one_for_the_same_object_before_it(self) -> None:
        early = _row("40001", _BURN - timedelta(days=3), 300.0)
        unread = _row("40001", _BURN - timedelta(days=1), None, problem="unreadable")
        other = _row("40002", _BURN - timedelta(days=2), 1.0)
        after = _row("40001", _BURN + timedelta(days=1), 12.0, name="BLUE-COMSAT")
        held = store.HeldConjunctions(_ACTOR, (after, other, unread, early), _NOW, "REAL")
        misses = {m.tca: m for m in store.conjunction_misses(held, frozenset({"40001"}))}
        judged = misses[after.tca]
        assert judged == Miss(target="BLUE-COMSAT (40001)", target_satno="40001", ours=True, source=MissSource.UDL,
                              tca=after.tca, after_km=12.0, before_km=300.0, before_at=early.tca,
                              margin_km=store.UDL_MARGIN_KM)
        assert misses[early.tca].before_km is None
        assert (misses[unread.tca].after_km, misses[unread.tca].problem) == (None, "unreadable")
        assert misses[other.tca].ours is False

    def test_the_latest_earlier_one_is_the_comparison_not_the_earliest(self) -> None:
        """Review finding 5: three with one object; the middle figure is what the newest is closer than, or not."""
        early = _row("40001", _BURN - timedelta(days=3), 300.0)
        middle = _row("40001", _BURN - timedelta(days=1), 15.0)
        after = _row("40001", _BURN + timedelta(days=1), 12.0)
        held = store.HeldConjunctions(_ACTOR, (early, after, middle), _NOW, "REAL")
        misses = {m.tca: m for m in store.conjunction_misses(held, frozenset({"40001"}))}
        assert (misses[after.tca].before_km, misses[after.tca].before_at) == (15.0, middle.tca)
        assert ig.miss_edges(_ACTOR, store.conjunction_misses(held, frozenset({"40001"})), [_burn()]) == ((), ())

    def test_a_change_inside_the_margin_is_not_closer(self) -> None:
        """Review finding 2: two filed figures each carry position error, so a metre is not an approach."""
        assert store.UDL_MARGIN_KM == 8.0
        rows = (_row("40001", _BURN - timedelta(days=2), 20.0), _row("40001", _BURN + timedelta(days=1), 19.999))
        misses = store.conjunction_misses(store.HeldConjunctions(_ACTOR, rows, _NOW, "REAL"), frozenset({"40001"}))
        assert ig.miss_edges(_ACTOR, misses, [_burn()]) == ((), ())
        wide = (rows[0], _row("40001", _BURN + timedelta(days=1), 11.9))
        misses = store.conjunction_misses(store.HeldConjunctions(_ACTOR, wide, _NOW, "REAL"), frozenset({"40001"}))
        (edge,), _ = ig.miss_edges(_ACTOR, misses, [_burn()])
        assert (edge.before_km, edge.after_km) == (20.0, 11.9)

    @pytest.mark.parametrize("mode", ["EXERCISE", "TEST", "SIMULATED", ""])
    def test_one_not_filed_as_real_data_is_refused_and_stated(self, mode: str) -> None:
        """Review finding 2: exercise or test data is not evidence about the real object; the refusal is stated."""
        rows = (_filed(_row("40001", _BURN - timedelta(days=2), 300.0), mode),
                _filed(_row("40001", _BURN + timedelta(days=1), 12.0, name="BLUE-COMSAT"), mode))
        misses = store.conjunction_misses(store.HeldConjunctions(_ACTOR, rows, _NOW, mode), frozenset({"40001"}))
        edges, refused = ig.miss_edges(_ACTOR, misses, [_burn()])
        assert edges == ()
        assert refused == ("UDL conjunction with BLUE-COMSAT (40001) not counted: it was not filed as REAL data, "
                           "so it says nothing about the object itself.",)
        assert i13_problems(refused[0]) == []

    def test_a_real_record_is_compared_only_with_real_ones(self) -> None:
        rows = (_filed(_row("40001", _BURN - timedelta(days=2), 300.0), "EXERCISE"),
                _row("40001", _BURN + timedelta(days=1), 12.0))
        misses = {m.tca: m for m in store.conjunction_misses(store.HeldConjunctions(_ACTOR, rows, _NOW, "REAL"),
                                                              frozenset({"40001"}))}
        assert misses[rows[1].tca].before_km is None

    def test_an_unnamed_or_unnumbered_object_is_still_named(self) -> None:
        held = store.HeldConjunctions(_ACTOR, (_row("", _BURN, 1.0), _row("40009", _BURN, 1.0)), _NOW, "REAL")
        assert sorted(m.target for m in store.conjunction_misses(held, frozenset())) == ["40009",
                                                                                          "an unnumbered object"]


_BEFORE_TLE = GEO_DRIFT_IN.red_tle
_AFTER_TLE = GEO_DRIFT_IN.red_tle
_BLUE_TLE = GEO_DRIFT_IN.blue_tle


class TestComputedApproaches:
    def test_each_target_in_reach_is_searched_from_the_burn_and_judged_by_the_edge_rule(self) -> None:
        burn = _burn(EPOCH - timedelta(hours=1))
        misses, refused = store.computed_misses([burn], _BEFORE_TLE, _AFTER_TLE,
                                                [store.Target("BLUE-1", "40001", True, _BLUE_TLE)],
                                                EPOCH + timedelta(hours=2))
        assert refused == ()
        (miss,) = misses
        assert (miss.target, miss.target_satno, miss.ours, miss.source) == ("BLUE-1", "40001", True,
                                                                            MissSource.COMPUTED)
        # The same set before and after: no closer, so the edge rule finds nothing to count.
        assert miss.before_km == miss.after_km
        assert miss.margin_km > 0.0
        assert ig.miss_edges(_ACTOR, misses, [burn]) == ((), ())

    def test_an_out_of_date_set_is_refused_and_stated(self) -> None:
        burn = _burn(EPOCH - timedelta(hours=1))
        misses, (sentence,) = store.computed_misses([burn], _BEFORE_TLE, _AFTER_TLE,
                                                    [store.Target("BLUE-1", "40001", True, _BLUE_TLE)],
                                                    EPOCH + timedelta(days=30))
        assert misses == ()
        assert sentence.startswith("computed closest approach with BLUE-1 not counted: the red element set is "
                                   "out of date, 30.")
        assert i13_problems(sentence) == []

    def test_a_target_with_no_element_set_is_refused_and_stated(self) -> None:
        burn = _burn(EPOCH - timedelta(hours=1))
        _, (sentence,) = store.computed_misses([burn], _BEFORE_TLE, _AFTER_TLE,
                                               [store.Target("BLUE-1", "40001", True, None)], EPOCH)
        assert sentence == ("computed closest approach with BLUE-1 not counted: the BLUE-1 element set's epoch "
                            "cannot be read, so its age is unknown.")

    def test_a_before_set_with_no_readable_epoch_is_refused_and_stated(self) -> None:
        burn = _burn(EPOCH - timedelta(hours=1))
        _, (sentence,) = store.computed_misses([burn], "not an element set", _AFTER_TLE,
                                               [store.Target("BLUE-1", "40001", True, _BLUE_TLE)], EPOCH)
        assert sentence == ("computed closest approach with BLUE-1 not counted: the red element set from before "
                            "the burn has no readable epoch.")

    def test_a_propagation_failure_is_refused_and_names_the_side(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.astro.elset_approach import ElsetFailure

        monkeypatch.setattr(store, "burn_approach", lambda *_a: ElsetFailure("blue", "propagation"))
        burn = _burn(EPOCH - timedelta(hours=1))
        _, (sentence,) = store.computed_misses([burn], _BEFORE_TLE, _AFTER_TLE,
                                               [store.Target("BLUE-1", "40001", True, _BLUE_TLE)], EPOCH)
        assert sentence == ("computed closest approach with BLUE-1 not counted: SGP4 could not propagate the blue "
                            "element set.")

    def test_at_most_8_targets_are_searched_and_the_rest_are_named_as_not_searched(self) -> None:
        burn = _burn(EPOCH - timedelta(hours=1))
        targets = [store.Target(f"BLUE-{k}", f"4000{k}", True, _BLUE_TLE) for k in range(store.MAX_COMPUTED + 2)]
        misses, refused = store.computed_misses([burn], _BEFORE_TLE, _AFTER_TLE, targets, EPOCH)
        assert len(misses) == store.MAX_COMPUTED == 8
        assert refused == ("Closest approaches were computed for the first 8 targets in reach; 2 more were not "
                           "searched.",)

    def test_no_burn_nothing_is_searched(self) -> None:
        assert store.computed_misses([], _BEFORE_TLE, _AFTER_TLE,
                                     [store.Target("BLUE-1", "40001", True, _BLUE_TLE)], EPOCH) == ((), ())


class TestASweepHoldsWhatItLearnt:
    def test_warning_computed_and_conjunction_edges_are_held_and_refusals_stated(self) -> None:
        state = _state()
        before = _row("40001", _BURN - timedelta(days=2), 300.0, name="BLUE-COMSAT")
        after = _row("40001", _BURN + timedelta(days=1), 12.0, name="BLUE-COMSAT")
        unread = _row("40002", _BURN + timedelta(hours=8), None, problem="UDL filed no miss distance")
        store.hold_conjunctions(state, 41838, _reading(after, unread, before), "REAL", _NOW)
        computed = Miss("BLUE-1", "40001", True, MissSource.COMPUTED, _BURN + timedelta(hours=3), 12.0, 140.0,
                        _BURN - timedelta(days=1), 5.0)
        found = store.SweepFindings((_burn(),), warning=(_warning(),),
                                    computed=((computed,), ("a refusal from the search.",)),
                                    blue_satnos=frozenset({"40001"}))
        held = store.sweep_interactions(state, _ACTOR, found, _NOW)
        kinds = sorted(store.kind_of(e) for e in held.edges)
        assert kinds == [store.COMPUTED_KIND, store.UDL_KIND, store.WARNING_KIND]
        assert "a refusal from the search." in held.notes
        assert ("UDL conjunction with 40002 not counted: UDL filed no miss distance.") in held.notes
        assert ("3 UDL conjunctions are held from the lookup at 2026-11-03 12:00 UTC. Their field names are "
                "inferred and unverified (SPC-033), so each is graded as a probe.") in held.notes
        for note in held.notes:
            assert i13_problems(note) == [], note

    def test_without_figures_only_the_conjunctions_are_re_judged(self) -> None:
        state = _state()
        _hold(state, (_warning(),))
        held = store.sweep_interactions(state, _ACTOR, store.SweepFindings((_burn(),)), _NOW)
        assert held.edges == (_warning(),)

    def test_the_notes_of_the_last_sweep_replace_the_earlier_ones(self) -> None:
        state = _state()
        store.sweep_interactions(state, _ACTOR, store.SweepFindings((_burn(),), computed=((), ("first.",))), _NOW)
        held = store.sweep_interactions(state, _ACTOR, store.SweepFindings((_burn(),), computed=((), ())), _NOW)
        assert "first." not in held.notes


class TestAnEdgeOnABurnTheHistoryNoLongerConfirmsIsDropped:
    """An edge rests on its burns: once the held history covers a burn's time and no longer confirms it, it goes."""

    def test_a_burn_inside_the_history_but_not_confirmed_there_drops_its_edges(self) -> None:
        state = _state()
        gone = _burn(_BURN - timedelta(days=3))
        _hold(state, (_warning("BLUE-GONE", gone),), burns=(gone,))
        history = store.HistoryBurns(confirmed=frozenset({_BURN}), since=_BURN - timedelta(days=30))
        found = store.SweepFindings((_burn(),), warning=(_warning(),), computed=((), ()), history=history)
        held = store.sweep_interactions(state, _ACTOR, found, _NOW)
        assert [e.target for e in held.edges] == ["BLUE-1"]

    def test_a_burn_older_than_the_history_keeps_its_edges(self) -> None:
        state = _state()
        older = _burn(_BURN - timedelta(days=40))
        _hold(state, (_warning("BLUE-OLD", older),), burns=(older,))
        history = store.HistoryBurns(confirmed=frozenset({_BURN}), since=_BURN - timedelta(days=30))
        found = store.SweepFindings((_burn(),), computed=((), ()), history=history)
        held = store.sweep_interactions(state, _ACTOR, found, _NOW)
        assert [e.target for e in held.edges] == ["BLUE-OLD"]
