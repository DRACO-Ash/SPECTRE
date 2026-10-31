"""The intercept engine searches, flies and judges each red approach (0.7.0).

The panel solved each method once with typed values, ranked rows that never
reached the target, ranked blue's own defensive burns as red threats, and
let minimum-time spend the whole 500 m/s budget. Each test here posts the
form as the panel does, at a fixed manoeuvre start, so the geometry does not
move with the hour (CLAUDE.md).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from spectre.domain import realism
from spectre.domain.manoeuvre_evidence import shipped_evidence
from spectre.web.routes import maneuver
from tests.conftest import csrf_headers
from tests.integration.test_all_intercepts_ranking import _ROUTE, seeded_state  # noqa: F401

_START = "2026-10-28T22:00:00"


def _post(client: Any, cookie: str, **form: str) -> str:
    data = {"red_sat": "RED-GEO", "blue_sat": "BLUE-GEO", "manoeuvre_start": _START, **form}
    resp = client.post(_ROUTE, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return resp.text


def _items(state: Any) -> list[Any]:
    return list(state.intercept_history)


def _cost(state: Any, method: maneuver.InterceptMethod) -> float:
    return next(r.total_delta_v_m_s for r in _items(state) if r.method is method)


@pytest.mark.usefixtures("seeded_state")
class TestThePanel:
    def test_the_search_finds_a_cheaper_lambert_than_the_typed_six_hours(
        self, client: Any, auth_cookie: str, seeded_state: Any,  # noqa: F811
    ) -> None:
        _post(client, auth_cookie, targeting_mode="typed")
        typed = _cost(seeded_state, maneuver.InterceptMethod.LAMBERT)
        page = _post(client, auth_cookie, targeting_mode="search")
        assert _cost(seeded_state, maneuver.InterceptMethod.LAMBERT) < typed / 2
        assert "Most likely course of action" in page
        assert "Burn point" in page and "Closest approach" in page

    def test_a_form_that_does_not_say_searches(self, client: Any, auth_cookie: str) -> None:
        assert "was searched for its cheapest plan" in _post(client, auth_cookie)

    def test_typed_mode_says_so(self, client: Any, auth_cookie: str) -> None:
        assert "solved once with the typed values" in _post(client, auth_cookie, targeting_mode="typed")

    def test_minimum_time_spends_a_realistic_budget_not_the_maximum(
        self, client: Any, auth_cookie: str, seeded_state: Any,  # noqa: F811
    ) -> None:
        _post(client, auth_cookie, max_dv_m_s="500")
        budget, _why = realism.realistic_budget_m_s(None, shipped_evidence())
        assert _cost(seeded_state, maneuver.InterceptMethod.MIN_TIME) <= budget + 0.5

    def test_typed_minimum_time_still_spends_what_is_typed(
        self, client: Any, auth_cookie: str, seeded_state: Any,  # noqa: F811
    ) -> None:
        page = _post(client, auth_cookie, targeting_mode="typed", max_dv_m_s="500")
        assert _cost(seeded_state, maneuver.InterceptMethod.MIN_TIME) == pytest.approx(500.0, abs=1.0)
        worst = re.search(r"Worst-case:(.*?)</span>", page, re.S)
        assert worst is not None
        assert "MIN_TIME" not in worst.group(1), "500 m/s is beyond the NOTSO record, so it cannot set the worst case"


class TestTheRows:
    """The route's own helpers, on the same pair and start."""

    def _items(self, search: bool = True, target_km: float = 0.0) -> list[dict[str, Any]]:
        from datetime import UTC, datetime

        from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO

        evidence = shipped_evidence()
        args = maneuver._InterceptArgs(
            _RED_GEO, _BLUE_GEO, datetime(2026, 10, 28, 22, 0, tzinfo=UTC), 3600.0, 21600.0, target_km,
            evidence.fleet.largest_window_m_s, maneuver._Shaping(search=search),
        )
        plan = maneuver._batch_plan(args, None, evidence)
        raw = maneuver._run_all_methods(args, "RED", "BLUE", plan)
        judged = maneuver._Assessing("GEO", args.max_dv_m_s, None, "RED", evidence)
        items = maneuver._items_from_solutions(raw, judged)
        items.sort(key=maneuver._sort_key)
        return items

    def test_defensive_burns_are_never_red_threats(self) -> None:
        items = self._items()
        defence = {maneuver.InterceptMethod.COLA, maneuver.InterceptMethod.EVASION, maneuver.InterceptMethod.FORMATION}
        rows = [i for i in items if i["method"] in defence]
        assert rows and all(i["group"] == maneuver._BLUE_DEFENCE and not i["counts"] for i in rows)

    def test_red_approaches_lead_and_those_that_count_lead_them(self) -> None:
        solved = [i for i in self._items() if i["result"]]
        groups = [maneuver._GROUP_ORDER[i["group"]] for i in solved]
        assert groups == sorted(groups)
        red = [i["counts"] for i in solved if i["group"] == maneuver._RED_APPROACH]
        assert red == sorted(red, reverse=True)

    def test_a_row_that_never_arrives_does_not_count(self) -> None:
        hohmann = next(i for i in self._items() if i["method"] is maneuver.InterceptMethod.HOHMANN)
        assert hohmann["targeting"]["closest_km"] > realism.CLOSE_APPROACH_KM
        assert not hohmann["targeting"]["approach"] and not hohmann["counts"]

    def test_an_unrealistic_row_does_not_count(self) -> None:
        bielliptic = next(i for i in self._items() if i["method"] is maneuver.InterceptMethod.BIELLIPTIC)
        assert bielliptic["realism"].band == realism.UNREALISTIC and not bielliptic["counts"]

    def test_the_standoff_sets_the_approach_radius(self) -> None:
        wide = next(i for i in self._items() if i["method"] is maneuver.InterceptMethod.PHASING)
        tight = next(i for i in self._items(target_km=5.0) if i["method"] is maneuver.InterceptMethod.PHASING)
        # At 50 km the cheapest phasing plan stops well short of 5 km, so a
        # 5 km standoff has to buy a different plan, or none.
        assert wide["targeting"]["approach"] and wide["targeting"]["closest_km"] > 5.0
        assert tight["targeting"]["approach"] == (tight["targeting"]["closest_km"] <= 5.0)
        assert (tight["result"].total_delta_v_m_s, tight["targeting"]["closest_km"]) != (
            wide["result"].total_delta_v_m_s, wide["targeting"]["closest_km"])

    def test_the_most_likely_is_the_cheapest_that_counts(self) -> None:
        items = self._items()
        best = maneuver._most_likely(items)
        assert best is not None and best["counts"]
        assert all(best["result"].total_delta_v_m_s <= i["result"].total_delta_v_m_s
                   for i in items if i["counts"] and i["realism"].band == best["realism"].band)

    def test_typed_mode_compares_one_option(self) -> None:
        lambert = next(i for i in self._items(search=False) if i["method"] is maneuver.InterceptMethod.LAMBERT)
        assert lambert["targeting"]["tried"] == 1 and lambert["targeting"]["burn_point"] == maneuver._TYPED

    def test_hops_are_not_flown(self) -> None:
        vbar = next(i for i in self._items() if i["method"] is maneuver.InterceptMethod.VBAR_HOP)
        assert vbar["targeting"]["flown"] is False and vbar["targeting"]["hops"] in (1, 2, 3, 4, 5)

    def test_the_approach_radius_defaults_to_fifty_km(self) -> None:
        assert maneuver.approach_radius_km(0.0) == realism.CLOSE_APPROACH_KM
        assert maneuver.approach_radius_km(5.0) == pytest.approx(5.0)
