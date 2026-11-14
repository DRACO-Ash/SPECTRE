"""Threat Understanding, SPC-174: suspicion propagated from a hostile seed.

Concept section 4.9: a propagation item for object v takes
q = q_edge x 0.5^hops, for at most 2 hops, and its reading is floor MEDIUM
at most. A third hop adds nothing, a benign seed propagates nothing, and one
edge cannot lift the floor past MEDIUM through propagation. The edge whose
q is used is the weakest on the path: a chain is no stronger than its
weakest link. Every path from one object counts once (one group), so a seed
cluster reached through one edge is not counted once per seed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.interaction_graph import NO_SEED_LIST, Burn, Edge, SeedPath, parse_seed_list, seed_paths
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Dimension, HeldBurn, Situation, Status
from spectre.domain.warning_change import Change
from spectre.web.understanding_view import ledger_view
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)


def _burn(*, detection: str = "HIGH", provider: str = "18SDS", epoch: datetime = _BURN) -> Burn:
    return Burn(epoch=epoch, earliest=epoch, latest=epoch, confirmed=True, detection=detection, provider=provider)


def _edge(actor: str, target: str, burn: Burn | None = None, *, ours: bool = False) -> Edge:
    return Edge(actor, f"OBJ-{target}", ours, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (burn or _burn(),),
                target_satno=target)


def _hostile(*satnos: str, benign: tuple[str, ...] = ()) -> object:
    entries = [{"satno": s, "disposition": "hostile"} for s in satnos]
    entries += [{"satno": s, "disposition": "benign"} for s in benign]
    return parse_seed_list(json.dumps({"seeds": entries}))


def _situation(**kw: object) -> Situation:
    args: dict[str, object] = {"now": _NOW, "access": Band.CRITICAL, "legacy": Band.CRITICAL, "regime": "GEO",
                               "data_mode": "REAL", "custody": Custody.HELD, "history_truncated": False,
                               "burns": (HeldBurn(_BURN, Normality.UNPRECEDENTED),)}
    args.update(kw)
    return Situation(**args)  # type: ignore[arg-type]


def _q(item: tu.EvidenceItem) -> float:
    return tu.reliability(item, _NOW)


def _assess(edges: list[Edge], seeds: object) -> tu.ThreatUnderstanding:
    paths = seed_paths("100", edges, seeds)  # type: ignore[arg-type]
    own = [e for e in edges if e.actor == "100"]
    return tu.assess((*tu.interaction_items(own), *tu.propagation_items(paths, _NOW)), _situation())


class TestTheValues:
    def test_one_hop_is_the_edges_q_halved(self) -> None:
        edge = _edge("100", "900")
        (path,) = seed_paths("100", [edge], _hostile("900"))  # type: ignore[arg-type]
        (item,) = tu.propagation_items([path], _NOW)
        (own,) = tu.interaction_items([edge])
        assert _q(item) == pytest.approx(_q(own) * 0.5)
        assert (item.dimension, item.floor_to, item.basis, item.grade) == (
            Dimension.INTERACTIONS, Band.MEDIUM, Basis.COMPUTED, "B2")
        assert (item.derived_from, item.observed_at) == ("seed:100", _BURN)
        assert item.label == "1 hop from hostile seed OBJ-900 (900)"
        assert item.note == ("an analyst-adjudicated hostile seed it approached; propagation sets the Threat floor "
                             "to MEDIUM at most")

    def test_two_hops_is_the_weakest_edges_q_quartered(self) -> None:
        strong, weak = _edge("100", "200"), _edge("200", "900", _burn(detection="MODERATE"))
        (path,) = seed_paths("100", [strong, weak], _hostile("900"))  # type: ignore[arg-type]
        (item,) = tu.propagation_items([path], _NOW)
        (weakest,) = tu.interaction_items([weak])
        assert _q(item) == pytest.approx(_q(weakest) * 0.25)
        # The seed list never becomes classified (section 9, decisions 5 and 15): the seed is always named.
        assert item.label == "2 hops from hostile seed OBJ-900 (900), through OBJ-200"
        assert item.note == ("an analyst-adjudicated hostile seed an object it approached approached; propagation "
                             "sets the Threat floor to MEDIUM at most")

    def test_a_third_hop_adds_nothing(self) -> None:
        edges = [_edge("100", "200"), _edge("200", "300"), _edge("300", "900")]
        assert _assess(edges, _hostile("900")).range == _assess(edges, NO_SEED_LIST).range


class TestABenignSeedHasNoEffect:
    def test_the_range_and_ledger_are_as_with_no_list(self) -> None:
        edges = [_edge("100", "500"), _edge("500", "600")]
        assert _assess(edges, _hostile(benign=("500", "600"))).range == _assess(edges, NO_SEED_LIST).range

    def test_it_lowers_nothing_beside_a_hostile_one(self) -> None:
        edges = [_edge("100", "900"), _edge("100", "500")]
        assert (_assess(edges, _hostile("900", benign=("500",))).range
                == _assess(edges, _hostile("900")).range)


class TestOneEdgeNeverLiftsTheFloorPastMediumThroughPropagation:
    def test_a_strong_edge_to_a_hostile_seed_sets_medium(self) -> None:
        result = _assess([_edge("100", "900")], _hostile("900"))
        assert tu.depth(result.range.coverage[Dimension.INTERACTIONS]) is tu.Depth.EARNED
        assert result.range.floor is Band.MEDIUM
        (row,) = [r for r in result.range.ledger if r.item.derived_from == "seed:100"]
        assert (row.status, row.applied) == (Status.COUNTED, True)

    def test_without_the_seed_the_same_edge_moves_no_band(self) -> None:
        """The edge to an object not ours is coverage only; the seed is what makes it a reading."""
        assert _assess([_edge("100", "900")], NO_SEED_LIST).range.floor is Band.MINIMAL

    def test_one_edge_into_a_cluster_of_seeds_counts_once(self) -> None:
        edges = [_edge("100", "900"), _edge("900", "901"), _edge("900", "902")]
        result = _assess(edges, _hostile("900", "901", "902"))
        rows = [r for r in result.range.ledger if r.item.derived_from == "seed:100"]
        assert sorted(r.status.value for r in rows) == ["counted", "folded", "folded"]
        assert result.range.floor is Band.MEDIUM

    def test_two_hops_alone_is_below_what_a_reading_needs(self) -> None:
        result = _assess([_edge("100", "200"), _edge("200", "900")], _hostile("900"))
        (row,) = [r for r in result.range.ledger if r.item.derived_from == "seed:100"]
        assert row.status is Status.BELOW_THRESHOLD
        assert result.range.floor is Band.MINIMAL

    def test_a_path_adds_no_coverage_beyond_the_edge_it_rests_on(self) -> None:
        """Review finding 1: the path derives from the same burn as the edge, so it is not a second source.

        One weak warning edge to one of ours, short of earning Interactions on
        its own: a seed at its far end must not earn it, or the edge's own
        floor HIGH would apply through propagation.
        """
        edges = [_edge("100", "900", _burn(detection="MODERATE"), ours=True)]
        alone, seeded = _assess(edges, NO_SEED_LIST).range, _assess(edges, _hostile("900")).range
        assert tu.depth(alone.coverage[Dimension.INTERACTIONS]) is not tu.Depth.EARNED
        assert seeded.coverage[Dimension.INTERACTIONS] == alone.coverage[Dimension.INTERACTIONS]
        assert seeded.floor <= max(alone.floor, Band.MEDIUM)
        (row,) = [r for r in seeded.ledger if r.item.derived_from == "seed:100"]
        assert (row.status, row.counted, row.applied) == (Status.BELOW_THRESHOLD, False, False)

    @pytest.mark.parametrize("ours", [False, True])
    def test_the_propagation_reading_is_never_above_medium(self, ours: bool) -> None:
        (path,) = seed_paths("100", [_edge("100", "900", ours=ours)], _hostile("900"))  # type: ignore[arg-type]
        assert {i.floor_to for i in tu.propagation_items([path], _NOW)} == {Band.MEDIUM}


class TestARoutineFirstEdgeMovesNoBand:
    def test_resting_only_on_routine_burns_it_is_coverage_only(self) -> None:
        (path,) = seed_paths("100", [_edge("100", "900")], _hostile("900"))  # type: ignore[arg-type]
        (item,) = tu.propagation_items([path], _NOW, judged=(HeldBurn(_BURN, Normality.ROUTINE),))
        assert (item.floor_to, item.routine) == (None, True)
        assert item.note == "every burn its own approach rests on was judged routine: coverage only"


    @pytest.mark.parametrize(("routine_at", "coverage_only"), [(0, True), (1, False)])
    def test_over_two_hops_it_is_the_objects_own_first_edge_that_decides(self, routine_at: int,
                                                                         coverage_only: bool) -> None:
        """Review finding 4: a routine burn by the object in between is not suspicion, wherever the seed is."""
        burns = (_burn(), _burn(epoch=_BURN - timedelta(days=2)))
        path = SeedPath("900", 2, (_edge("100", "200", burns[0]), _edge("200", "900", burns[1])))
        judged = [HeldBurn(b.epoch, Normality.ROUTINE if k == routine_at else Normality.UNPRECEDENTED)
                  for k, b in enumerate(burns)]
        (item,) = tu.propagation_items([path], _NOW, judged=judged)
        assert (item.routine, item.floor_to) == (coverage_only, None if coverage_only else Band.MEDIUM)


class TestTheWords:
    @pytest.mark.parametrize("edges", [[_edge("100", "900")], [_edge("100", "200"), _edge("200", "900")]])
    def test_the_ledger_rows_pass_i13(self, edges: list[Edge]) -> None:
        for row in _assess(edges, _hostile("900")).range.ledger:
            for text in ledger_view(row).values():
                assert i13_problems(text) == [], text

    def test_an_aged_path_ages_with_its_weakest_edge(self) -> None:
        old = _burn(epoch=_BURN - timedelta(days=30))
        path = SeedPath("900", 1, (_edge("100", "900", old),))
        (item,) = tu.propagation_items([path], _NOW)
        assert item.observed_at == old.epoch


class TestAPathPastTwoHopsIsNotRead:
    def test_even_one_built_by_hand(self) -> None:
        edges = (_edge("100", "200"), _edge("200", "300"), _edge("300", "900"))
        assert tu.propagation_items([SeedPath("900", 3, edges)], _NOW) == ()
