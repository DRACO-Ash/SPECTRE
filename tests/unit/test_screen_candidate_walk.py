"""The asset screen fetches only the element sets it needs to fill its cap (SPC-239, V0.41 review).

A payload's age is judged on the set it is screened on, so its live set is fetched before the age check. The screen
walks the payloads the first pass did not settle in watchlist order, fetching in batches of the slots still free,
until the cap is filled after the age check, and stops: a watchlist of 200 undated payloads costs 60 fetches, as it
did before the age moved after the fetch, not 200. A note for a failed fetch is kept only for an actor screened, and
the objects left out are named in watchlist order within each kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.web.routes import threat
from spectre.web.routes.udl import FetchedElset

_YEAR = 2026
_CAP = 60


def _tle(satno: int, designator: str) -> str:
    return (
        f"1 {satno:05d}U {designator:<8} 26250.50000000  .00000000  00000-0  00000-0 0  9992\n"
        f"2 {satno:05d}   3.4700  83.3000 0005000 310.0000 124.0000  1.00270000 26266"
    )


def _payload(satno: int) -> dict[str, Any]:
    return {"satno": str(satno), "name": f"PAYLOAD {satno}", "country": "CHN", "rank": 1, "orbit_regime": "GEO"}


def _state(objects: list[dict[str, Any]], **held: Any) -> SimpleNamespace:
    return SimpleNamespace(
        hrr_objects=objects, hrr_tle_cache=dict(held.get("cache", {})), hrr_tle_data_mode=dict(held.get("modes", {})),
        udl_username="u", udl_password="p", udl_data_mode="REAL", udl_tle_source=None,
    )


@dataclass
class _Udl:
    """UDL as the screen meets it: every catalogue number fetched, in order; a number in old returns an old payload's
    set, one in down nothing."""

    calls: list[int] = field(default_factory=list)
    old: set[int] = field(default_factory=set)
    down: set[int] = field(default_factory=set)


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch) -> _Udl:
    from spectre.web.routes import udl as udl_route

    fake = _Udl()

    async def _fetch(satno: int, *_a: object, **_k: object) -> FetchedElset | None:
        fake.calls.append(satno)
        if satno in fake.down:
            return None
        return FetchedElset(_tle(satno, "04042A" if satno in fake.old else "16065A"), "REAL", "18th SPCS")

    monkeypatch.setattr(udl_route, "fetch_tle_for_satno", _fetch)
    monkeypatch.setattr("spectre.web.planning_state.get_onorbit_catalog", list)
    return fake


class TestTheWalkFetchesOnlyWhatTheCapNeeds:
    async def test_two_hundred_undated_payloads_cost_the_caps_fetches_not_two_hundred(self, udl: _Udl) -> None:
        satnos = list(range(70001, 70201))
        chosen = await threat._select_candidates(_state([_payload(n) for n in satnos]), "GEO", _YEAR)
        assert threat._MAX_SCREEN_ACTORS == _CAP
        assert len(udl.calls) == _CAP
        assert sorted(udl.calls) == satnos[:_CAP]
        assert [a.actor_satno for a in chosen.actors] == [str(n) for n in satnos[:_CAP]]
        assert chosen.not_screened == ""

    async def test_old_payloads_among_the_first_sixty_make_the_walk_go_on_past_them(self, udl: _Udl) -> None:
        satnos = list(range(70001, 70201))
        udl.old.update(satnos[:30])
        chosen = await threat._select_candidates(_state([_payload(n) for n in satnos]), "GEO", _YEAR)
        assert sorted(udl.calls) == satnos[:90], "sixty fetched, thirty of them old, then thirty more"
        assert [a.actor_satno for a in chosen.actors] == [str(n) for n in satnos[30:90]]
        assert chosen.not_screened.startswith("Not screened, as not able to act: 30 past working life: PAYLOAD 70001 ")

    async def test_a_payload_the_first_pass_settles_is_never_fetched(
        self, udl: _Udl, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "spectre.web.planning_state.get_onorbit_catalog",
            lambda: [{"satNo": 70002, "objectType": "PAYLOAD", "launchDate": "2001-01-01"}],
        )
        objects = [_payload(70001), _payload(70002), {**_payload(70003), "name": "CZ-3B R/B"}]
        chosen = await threat._select_candidates(_state(objects), "GEO", _YEAR)
        assert udl.calls == [70001]
        assert [a.actor_satno for a in chosen.actors] == ["70001"]

    async def test_a_truncated_list_says_how_many_were_not_reached(
        self, udl: _Udl, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(threat, "_MAX_SCREEN_ACTORS", 2)
        chosen = await threat._select_candidates(_state([_payload(n) for n in (70001, 70002, 70003)]), "GEO", _YEAR)
        assert udl.calls == [70001, 70002]
        assert chosen.notes == [
            "Candidate list truncated to 2 of 3 (compute cap). Ranking covers the truncated set only.",
        ]


class TestOnlyAScreenedActorsFailedFetchIsNoted:
    async def test_a_note_for_an_actor_cut_by_age_is_dropped(self, udl: _Udl) -> None:
        """70001 holds an old TEST set its fetch could not replace, so its age is read from that set and it is cut;
        70002 holds nothing and its fetch failed, so it is screened, and only its note is kept."""
        udl.down.update({70001, 70002})
        state = _state(
            [_payload(70001), _payload(70002)],
            cache={"70001": _tle(70001, "04042A")}, modes={"70001": "TEST"},
        )
        chosen = await threat._select_candidates(state, "GEO", _YEAR)
        assert udl.calls == [70001, 70002]
        assert [a.actor_satno for a in chosen.actors] == ["70002"]
        assert "PAYLOAD 70001 (launched 2004)" in chosen.not_screened
        assert chosen.refresh_notes == [
            "PAYLOAD 70002 (70002): live element set not fetched; screened on the set already held",
        ]


class TestTheLeftOutAreNamedInWatchlistOrder:
    async def test_within_a_kind_the_watchlist_order_holds(
        self, udl: _Udl, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """70001 is dated old by the set it is screened on, 70002 by the catalogue in the first pass; the note names
        70001 first, as the watchlist does."""
        monkeypatch.setattr(
            "spectre.web.planning_state.get_onorbit_catalog",
            lambda: [{"satNo": 70002, "objectType": "PAYLOAD", "launchDate": "2003-01-01"}],
        )
        udl.old.add(70001)
        chosen = await threat._select_candidates(_state([_payload(n) for n in (70001, 70002, 70003)]), "GEO", _YEAR)
        assert "2 past working life: PAYLOAD 70001 (launched 2004), PAYLOAD 70002 (launched 2003)" in (
            chosen.not_screened
        )

    async def test_the_catalogue_is_read_once_per_screen(
        self, udl: _Udl, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reads: list[int] = []

        def _catalogue() -> list[dict[str, Any]]:
            reads.append(1)
            return []

        monkeypatch.setattr("spectre.web.planning_state.get_onorbit_catalog", _catalogue)
        udl.old.update(range(70001, 70061))
        await threat._select_candidates(_state([_payload(n) for n in range(70001, 70121)]), "GEO", _YEAR)
        assert len(udl.calls) == 120
        assert reads == [1]
