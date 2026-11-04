"""Hostile seeds and the paths to them (SPC-174).

Concept section 4.9 and 8: seeds are analyst-adjudicated hostile objects.
Suspicion flows from an object to the seeds it has approached, at most two
hops away: the object approached the seed (one hop), or approached an object
that approached it (two). A third hop adds nothing, and nothing flows from a
benign seed. The list is owner data, possibly classified (section 9,
decision 5): it is read from a configured path, never bundled, validated
strictly, and a malformed list is refused whole with a reason that never
repeats its contents.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.domain import interaction_graph as ig
from spectre.domain.interaction_graph import (
    MAX_HOPS,
    NO_SEED_LIST,
    Burn,
    Edge,
    SeedList,
    SeedPath,
    parse_seed_list,
    seed_paths,
)
from spectre.domain.warning_change import Change
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = Burn(epoch=_NOW, earliest=_NOW, latest=_NOW, confirmed=True, detection="HIGH", provider="18SDS")


def _edge(actor: str, target: str) -> Edge:
    return Edge(actor, f"OBJ-{target}", False, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (_BURN,), target_satno=target)


def _seeds(hostile: tuple[str, ...] = (), benign: tuple[str, ...] = ()) -> SeedList:
    entries = [{"satno": s, "disposition": "hostile"} for s in hostile]
    entries += [{"satno": s, "disposition": "benign"} for s in benign]
    seeds = parse_seed_list(json.dumps({"seeds": entries}))
    assert seeds.refused is False
    return seeds


class TestTheList:
    def test_none_configured_holds_no_seed_and_says_so(self) -> None:
        assert SeedList(frozenset(), frozenset(), "no hostile seed list configured") == NO_SEED_LIST
        assert i13_problems(NO_SEED_LIST.statement) == []

    def test_a_valid_list_holds_its_hostile_and_benign_seeds_as_catalogue_numbers(self) -> None:
        text = json.dumps({"seeds": [
            {"satno": 41838, "disposition": "hostile", "adjudicated_at": "2026-10-01", "note": "analyst cell"},
            {"satno": "044227", "disposition": "hostile"},
            {"satno": "25544", "disposition": "benign"},
        ]})
        seeds = parse_seed_list(text)
        assert (seeds.hostile, seeds.benign, seeds.refused) == (frozenset({"41838", "44227"}), frozenset({"25544"}),
                                                                False)
        assert seeds.statement == ("hostile seed list held: 2 hostile seeds; a benign entry propagates nothing")

    def test_one_hostile_seed_reads_in_the_singular(self) -> None:
        assert _seeds(("41838",)).statement == "hostile seed list held: 1 hostile seed; a benign entry propagates nothing"

    def test_an_empty_list_holds_none(self) -> None:
        seeds = parse_seed_list('{"seeds": []}')
        assert (seeds.hostile, seeds.statement) == (frozenset(), "hostile seed list held: it names no hostile seed")


_REFUSED = "hostile seed list refused, so propagation adds nothing: "


class TestAMalformedListIsRefusedWhole:
    @pytest.mark.parametrize(("text", "reason"), [
        ("not json", "it is not JSON"),
        ('["41838"]', "it must be an object holding only a seeds list"),
        ('{"seeds": [], "extra": 1}', "it must be an object holding only a seeds list"),
        ('{"seeds": {"41838": "hostile"}}', "it must be an object holding only a seeds list"),
        ('{"seeds": ["41838"]}', "entry 1 is not an object"),
        ('{"seeds": [{"satno": 1, "disposition": "hostile", "colour": "red"}]}',
         "entry 1 has a field the list does not take"),
        ('{"seeds": [{"disposition": "hostile"}]}', "entry 1 has no satno"),
        ('{"seeds": [{"satno": 1}]}', "entry 1 has no disposition"),
        ('{"seeds": [{"satno": 1, "disposition": "Hostile"}]}', "entry 1's disposition must be hostile or benign"),
        ('{"seeds": [{"satno": 1, "disposition": "suspect"}]}', "entry 1's disposition must be hostile or benign"),
        ('{"seeds": [{"satno": 1, "disposition": "hostile", "adjudicated_at": "last week"}]}',
         "entry 1's adjudicated_at is not an ISO 8601 date"),
        ('{"seeds": [{"satno": 1, "disposition": "hostile", "adjudicated_at": 2026}]}',
         "entry 1's adjudicated_at is not an ISO 8601 date"),
        ('{"seeds": [{"satno": 1, "disposition": "hostile", "note": 7}]}',
         "entry 1's note must be text of at most 500 characters"),
        ('{"seeds": [{"satno": 1, "disposition": "hostile"}, {"satno": "0001", "disposition": "benign"}]}',
         "entry 2 repeats an earlier entry's satno"),
        # Review finding 3: JSON keeps the last of a repeated key, so a list that says two things is refused.
        ('{"seeds": [{"satno": 900, "disposition": "benign", "disposition": "hostile"}]}',
         "an object in it names one field twice"),
        ('{"seeds": [], "seeds": [{"satno": 900, "disposition": "hostile"}]}', "an object in it names one field twice"),
    ])
    def test_the_reason_names_the_entry_and_the_rule_never_the_contents(self, text: str, reason: str) -> None:
        seeds = parse_seed_list(text)
        assert (seeds.hostile, seeds.benign, seeds.refused) == (frozenset(), frozenset(), True)
        assert seeds.statement == _REFUSED + reason
        assert i13_problems(seeds.statement) == []

    @pytest.mark.parametrize("satno", [True, 0, -5, 1.5, 1e3, "", "12a45", "1234567890", None, [1]])
    def test_a_satno_that_is_not_a_catalogue_number_is_refused(self, satno: Any) -> None:
        seeds = parse_seed_list(json.dumps({"seeds": [{"satno": satno, "disposition": "hostile"}]}))
        assert seeds.statement == _REFUSED + "entry 1's satno is not a catalogue number"

    def test_a_note_over_500_characters_is_refused(self) -> None:
        text = json.dumps({"seeds": [{"satno": 1, "disposition": "hostile", "note": "x" * 501}]})
        assert parse_seed_list(text).statement == _REFUSED + "entry 1's note must be text of at most 500 characters"

    def test_a_refusal_never_repeats_what_the_list_holds(self) -> None:
        seeds = parse_seed_list('{"seeds": [{"satno": "SECRET-<b>", "disposition": "hostile"}]}')
        assert "SECRET" not in seeds.statement

    def test_a_refusal_helper_states_any_reason(self) -> None:
        assert ig.refused_seed_list("the configured file cannot be read").statement == (
            _REFUSED + "the configured file cannot be read")


class TestThePaths:
    def test_one_hop_the_object_approached_a_hostile_seed(self) -> None:
        edge = _edge("100", "900")
        assert seed_paths("100", [edge], _seeds(("900",))) == (SeedPath("900", 1, (edge,)),)

    def test_two_hops_it_approached_an_object_that_approached_one(self) -> None:
        first, second = _edge("100", "200"), _edge("200", "900")
        assert MAX_HOPS == 2
        assert seed_paths("100", [first, second], _seeds(("900",))) == (SeedPath("900", 2, (first, second)),)

    def test_a_third_hop_adds_nothing(self) -> None:
        edges = [_edge("100", "200"), _edge("200", "300"), _edge("300", "900")]
        assert seed_paths("100", edges, _seeds(("900",))) == ()

    def test_a_benign_seed_has_no_effect(self) -> None:
        edges = [_edge("100", "500"), _edge("500", "900")]
        assert seed_paths("100", edges, _seeds(benign=("500", "900"))) == ()
        assert seed_paths("100", edges, _seeds(("900",), benign=("500",))) == (SeedPath("900", 2, tuple(edges)),)

    def test_being_approached_by_a_seed_is_not_a_path_suspicion_flows_from_the_one_that_moved(self) -> None:
        assert seed_paths("100", [_edge("900", "100")], _seeds(("900",))) == ()

    def test_a_target_with_no_number_links_to_nothing(self) -> None:
        unnumbered = Edge("100", "BLUE-1", True, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (_BURN,))
        assert seed_paths("100", [unnumbered], _seeds(("900",))) == ()

    def test_a_path_back_through_the_object_itself_is_not_taken(self) -> None:
        edges = [_edge("100", "200"), _edge("200", "100")]
        assert seed_paths("100", edges, _seeds(("100",))) == ()

    def test_a_path_through_one_seed_to_another_names_both(self) -> None:
        first, second = _edge("100", "900"), _edge("900", "901")
        assert seed_paths("100", [first, second], _seeds(("900", "901"))) == (
            SeedPath("900", 1, (first,)), SeedPath("901", 2, (first, second)))

    def test_numbers_are_read_as_numbers(self) -> None:
        edge = Edge("0100", "OBJ", False, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (_BURN,), target_satno=" 0900 ")
        assert seed_paths("100", [edge], _seeds(("900",))) == (SeedPath("900", 1, (edge,)),)

    def test_none_configured_no_paths(self) -> None:
        assert seed_paths("100", [_edge("100", "900")], NO_SEED_LIST) == ()

    def test_the_paths_come_in_one_order_whatever_the_edge_order(self) -> None:
        edges = [_edge("100", "902"), _edge("100", "901"), _edge("100", "200"), _edge("200", "903")]
        seeds = _seeds(("901", "902", "903"))
        assert seed_paths("100", edges, seeds) == seed_paths("100", list(reversed(edges)), seeds)
        assert [(p.hops, p.seed) for p in seed_paths("100", edges, seeds)] == [(1, "901"), (1, "902"), (2, "903")]
