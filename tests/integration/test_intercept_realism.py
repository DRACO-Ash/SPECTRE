"""The Intercept Engine searches, flies and judges each red approach (SPC-234, charming-dirac d3447e2).

The panel solved each method once with typed values, ranked rows that never reached the target, ranked blue's own
defensive burns as red threats, and let minimum-time spend the whole budget. Each test here posts the form as the
panel does, or runs the route's own helpers, at a fixed manoeuvre start, so the geometry does not move with the
hour. Rows that do not reach the target are kept and labelled, never dropped (owner ruling, 2026-11-12).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.astro import maneuvers
from spectre.domain import realism
from spectre.domain.manoeuvre_evidence import shipped_evidence
from spectre.web.routes import maneuver
from tests.conftest import csrf_headers
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO, _ROUTE, seeded_state  # noqa: F401

_START = "2026-03-01T00:00:00"
_START_DT = datetime(2026, 3, 1, tzinfo=UTC)


def _post(client: Any, cookie: str, route: str = _ROUTE, **form: str) -> str:
    data = {"red_sat": "RED-GEO", "blue_sat": "BLUE-GEO", "manoeuvre_start": _START, **form}
    resp = client.post(route, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return resp.text


def _cost(state: Any, method: maneuver.InterceptMethod) -> float:
    return next(r.total_delta_v_m_s for r in state.intercept_history if r.method is method)


def _cannot_search(*_a: object, **_k: object) -> None:
    raise ValueError("closest_approach: no finite separation in the window")


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

    def test_the_default_budget_is_the_record_s_171_8(self, client: Any, auth_cookie: str) -> None:
        """Owner ruling 2026-11-12, overruling R7 for the engine: a form that sends no Max dV reads 171.8 m/s."""
        page = _post(client, auth_cookie, targeting_mode="typed")
        assert round(maneuver.ENGINE_DEFAULT_BUDGET_M_S, 1) == 171.8
        assert "of 172" in page and "of 500" not in page, "the budget share is taken against 171.8 m/s, shown as 172"

    def test_minimum_time_spends_a_realistic_budget_not_the_maximum(
        self, client: Any, auth_cookie: str, seeded_state: Any,  # noqa: F811
    ) -> None:
        page = _post(client, auth_cookie, max_dv_m_s="500")
        budget, why = realism.realistic_budget_m_s(None, shipped_evidence())
        spent = _cost(seeded_state, maneuver.InterceptMethod.MIN_TIME)
        assert 1.0 < spent <= budget + 0.5, "it spends a realistic budget, and does spend it"
        assert f"Minimum-time was given {budget:.0f} m/s, {why}." in page
        row = re.search(r'data-sort-1="min_time"(.*?)</tr>', page, re.S)
        assert row is not None and "No approach" not in row.group(1) and "Possible" in row.group(1)

    def test_typed_minimum_time_still_spends_what_is_typed_and_cannot_set_the_worst_case(
        self, client: Any, auth_cookie: str, seeded_state: Any,  # noqa: F811
    ) -> None:
        page = _post(client, auth_cookie, targeting_mode="typed", max_dv_m_s="500")
        assert _cost(seeded_state, maneuver.InterceptMethod.MIN_TIME) == pytest.approx(500.0, abs=1.0)
        worst = re.search(r"Worst-case:(.*?)</span>", page, re.S)
        assert worst is not None
        assert "MIN_TIME" not in worst.group(1), "500 m/s is beyond the NOTSO record, so it cannot set the worst case"

    def test_rows_that_do_not_arrive_are_kept_and_labelled(
        self, client: Any, auth_cookie: str, seeded_state: Any,  # noqa: F811
    ) -> None:
        page = _post(client, auth_cookie)
        assert "No approach" in page
        assert "Not an approach: it never comes within 50 km of the target." in page
        assert len(seeded_state.intercept_history) >= 20, "nothing is dropped for not arriving"

    def test_each_flown_miss_carries_its_element_set_error_band(self, client: Any, auth_cookie: str) -> None:
        page = _post(client, auth_cookie)
        assert "element-set error" in page
        assert "(1 sigma)" in page

    def test_a_flown_search_that_cannot_run_reads_not_computed(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SPC-238: no row fails for it, NaN is never printed, and nothing reads as arriving."""
        monkeypatch.setattr(maneuvers, "closest_approach", _cannot_search)
        page = _post(client, auth_cookie)
        assert "not computed" in page
        assert not re.search(r"\bnan\b", page, re.I)
        worst = re.search(r"Worst-case:(.*?)</span>", page, re.S)
        # Only the hops, which keep their own figure in the sequence's linear model, can still arrive.
        assert worst is None or re.search(r"[VH]BAR_HOP", worst.group(1))

    def test_the_single_method_page_shows_not_computed_rather_than_failing(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(maneuvers, "closest_approach", _cannot_search)
        page = _post(client, auth_cookie, route="/plan/maneuver/apply-intercept", method="phasing")
        assert "Intercept calculation failed" not in page
        assert "not computed" in page
        assert not re.search(r"\bnan\b", page, re.I)

    def test_the_trade_space_and_export_say_not_computed(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(maneuvers, "closest_approach", _cannot_search)
        _post(client, auth_cookie, route="/plan/maneuver/apply-intercept", method="phasing")
        cookies = {"spectre_session": auth_cookie}
        points = client.get("/plan/maneuver/trade-space-data", cookies=cookies).json()
        phasing = [p for p in points if p["method"] == "phasing"]
        assert phasing and phasing[-1]["miss_km"] is None
        csv = client.get("/plan/export", cookies=cookies).text
        assert "not computed" in csv and ",nan," not in csv


class TestTheRows:
    """The route's own helpers, on the same pair and start."""

    def _items(self, search: bool = True, target_km: float = 0.0) -> list[dict[str, Any]]:
        evidence = shipped_evidence()
        args = maneuver._InterceptArgs(
            _RED_GEO, _BLUE_GEO, _START_DT, 3600.0, 21600.0, target_km,
            evidence.fleet.largest_window_m_s, maneuver._Shaping(search=search),
        )
        budget, _why = realism.realistic_budget_m_s(None, evidence)
        raw = maneuver._batch(args, "RED", "BLUE", budget)
        judged = maneuver._Assessing("GEO", args.max_dv_m_s, None, "RED", evidence, _RED_GEO, _BLUE_GEO)
        items = maneuver._items_from_solutions(raw, judged)
        items.sort(key=maneuver._sort_key)
        return items

    def _row(self, items: list[dict[str, Any]], method: maneuver.InterceptMethod) -> dict[str, Any]:
        return next(i for i in items if i["method"] is method)

    def test_defensive_burns_are_never_red_threats(self) -> None:
        defence = {maneuver.InterceptMethod.COLA, maneuver.InterceptMethod.EVASION, maneuver.InterceptMethod.FORMATION}
        rows = [i for i in self._items() if i["method"] in defence]
        assert rows and all(i["group"] == maneuver._BLUE_DEFENCE and not i["counts"] for i in rows)

    def test_j2_drift_is_an_assessment(self) -> None:
        assert self._row(self._items(False), maneuver.InterceptMethod.J2_DRIFT)["group"] == maneuver._ASSESSMENT

    def test_red_approaches_lead_and_those_that_count_lead_them(self) -> None:
        solved = [i for i in self._items() if i["result"]]
        groups = [maneuver._GROUP_ORDER[i["group"]] for i in solved]
        assert groups == sorted(groups)
        red = [i["counts"] for i in solved if i["group"] == maneuver._RED_APPROACH]
        assert red == sorted(red, reverse=True)

    def test_a_row_that_never_arrives_is_kept_and_does_not_count(self) -> None:
        cw = self._row(self._items(), maneuver.InterceptMethod.CW_DRIFT)
        assert cw["result"] is not None
        assert cw["targeting"]["closest_km"] > realism.CLOSE_APPROACH_KM
        assert not cw["targeting"]["approach"] and not cw["counts"]

    @pytest.mark.parametrize("method", [maneuver.InterceptMethod.LAMBERT, maneuver.InterceptMethod.CW_DRIFT,
                                        maneuver.InterceptMethod.HOHMANN])
    def test_every_red_approach_reports_its_flown_miss(self, method: maneuver.InterceptMethod) -> None:
        """Lambert reported its aim and CW drift the 10 km asked for; the row reports what the burns achieve, checked
        against an independent flight of the row's own burns sampled every 10 s."""
        from spectre.astro.maneuvers import InterceptSolution
        from tests.unit.test_flight_and_targeting import _dense_least

        result = self._row(self._items(search=False), method)["result"]
        solved = maneuver._run_intercept(method, _RED_GEO, _BLUE_GEO, _START_DT, 3600.0, 21600.0, 0.0, 171.8)
        burns = solved.burns
        sol = InterceptSolution(method="x", burns=burns, departure_epoch=burns[0].epoch,
                                arrival_epoch=result.arrival_epoch)
        span_s = (result.arrival_epoch - burns[0].epoch).total_seconds()
        assert result.intercept_range_km == pytest.approx(_dense_least(sol, _RED_GEO, _BLUE_GEO, span_s), abs=0.5)
        if method is maneuver.InterceptMethod.CW_DRIFT:
            assert result.intercept_range_km > 500.0, "it reported the 10 km it was asked for"

    def test_an_unrealistic_row_does_not_count(self) -> None:
        items = self._items(search=False)
        unrealistic = [i for i in items if i["realism"] and i["realism"].band == realism.UNREALISTIC]
        assert unrealistic and not any(i["counts"] for i in unrealistic)

    def test_the_standoff_sets_the_approach_radius(self) -> None:
        tight = self._row(self._items(target_km=5.0), maneuver.InterceptMethod.PHASING)
        assert tight["targeting"]["approach"] == (tight["targeting"]["closest_km"] <= 5.0)
        assert maneuver.approach_radius_km(0.0) == realism.CLOSE_APPROACH_KM
        assert maneuver.approach_radius_km(5.0) == pytest.approx(5.0)

    def test_the_most_likely_is_the_cheapest_that_counts(self) -> None:
        items = self._items()
        best = maneuver._most_likely(items)
        assert best is not None and best["counts"]
        assert all(best["result"].total_delta_v_m_s <= i["result"].total_delta_v_m_s
                   for i in items if i["counts"] and i["realism"].band == best["realism"].band)

    def test_typed_mode_compares_one_option(self) -> None:
        lambert = self._row(self._items(search=False), maneuver.InterceptMethod.LAMBERT)
        assert lambert["targeting"]["tried"] == 1 and lambert["targeting"]["burn_point"] == maneuver._TYPED

    def test_hops_are_flown_and_searched(self) -> None:
        """Since the V0.40 review the hops list every burn, so they are flown as every red approach is."""
        vbar = self._row(self._items(), maneuver.InterceptMethod.VBAR_HOP)
        assert "flown" not in vbar["targeting"] and vbar["targeting"]["hops"] in (1, 2, 3, 4, 5)
        assert vbar["targeting"]["closest_km"] < realism.CLOSE_APPROACH_KM

    def test_the_band_is_both_sets_error_at_the_closest_approach(self) -> None:
        lambert = self._row(self._items(search=False), maneuver.InterceptMethod.LAMBERT)
        band = lambert["targeting"]["band"]
        # Both test sets are of 1 March 2026, GEO: 2 km at epoch plus 1 km a day, so a little over 2 km each.
        assert band["sigma_km"] == pytest.approx(math.hypot(band["red_km"], band["blue_km"]))
        assert 2.0 < band["red_km"] < 2.5
        assert band["low_km"] == pytest.approx(max(lambert["targeting"]["closest_km"] - band["sigma_km"], 0.0))


class TestTheWordsForAMissNotComputed:
    """SPC-238: every sentence and figure that quotes a miss says "not computed" for NaN, never "nan km"."""

    @pytest.mark.parametrize("method", [maneuver.InterceptMethod.LAMBERT, maneuver.InterceptMethod.RBAR_HOP,
                                        maneuver.InterceptMethod.VBAR_HOP, maneuver.InterceptMethod.HBAR_HOP])
    def test_the_insights_and_the_summary(self, method: maneuver.InterceptMethod) -> None:
        from spectre.domain.models import InterceptResult

        result = InterceptResult(red_name="RED", blue_name="BLUE", method=method, arrival_epoch=_START_DT,
                                 intercept_range_km=math.nan)
        values = [r["value"] for r in maneuver._method_insights(result, 12.0, math.nan)]
        summary = maneuver._summary_text(result, 12.0, math.nan, "intercept", "1.0 h")
        assert "not computed" in values
        assert "not computed" in summary and "nan" not in summary.lower()


class TestArrivalAtAStandoff:
    """Review of SPC-234: a flown Lambert miss lands micrometres either side of a standoff it aims at."""

    def _lambert(self, search: bool, target_km: float) -> dict[str, Any]:
        evidence = shipped_evidence()
        args = maneuver._InterceptArgs(_RED_GEO, _BLUE_GEO, _START_DT, 3600.0, 21600.0, target_km, 171.8,
                                       maneuver._Shaping(search=search))
        raw = [o for o in maneuver._batch(args, "RED", "BLUE", 36.77) if o.method is maneuver.InterceptMethod.LAMBERT]
        judged = maneuver._Assessing("GEO", 171.8, None, "RED", evidence, _RED_GEO, _BLUE_GEO)
        return maneuver._items_from_solutions(raw, judged)[0]

    @pytest.mark.parametrize("target_km", [0.1, 20.0])
    def test_typed_lambert_at_its_standoff_is_an_approach(self, target_km: float) -> None:
        assert self._lambert(False, target_km)["targeting"]["approach"]

    def test_the_search_keeps_the_cheap_plan_at_100_m(self) -> None:
        row = self._lambert(True, 0.1)
        assert row["targeting"]["approach"] and row["result"].total_delta_v_m_s < 15.0


class TestAlreadyWithinIsNotAnArrival:
    """Review of SPC-234: on a LEO pair 18 km apart, plans that burn nothing useful "arrived" and a 0 m/s Hohmann
    became the most likely course of action. The no-burn baseline over each plan's window says the target was
    already within the radius, so such rows are labelled and never count."""

    def _items(self) -> list[dict[str, Any]]:
        from tests.unit._decision_reference import EPOCH, PLANE_CHANGE

        red, blue = PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle
        evidence = shipped_evidence()
        args = maneuver._InterceptArgs(red, blue, EPOCH, 3600.0, 21600.0, 0.0, 171.8, maneuver._Shaping(search=True))
        raw = maneuver._batch(args, "RED", "BLUE", 36.77)
        judged = maneuver._Assessing("LEO", 171.8, None, "RED", evidence, red, blue)
        return maneuver._items_from_solutions(raw, judged)

    def test_no_row_counts_for_a_target_already_within(self) -> None:
        items = self._items()
        already = {i["method"] for i in items if i["targeting"] and i["targeting"]["already_within"]}
        assert {maneuver.InterceptMethod.HOHMANN, maneuver.InterceptMethod.CW_DRIFT,
                maneuver.InterceptMethod.PHASING, maneuver.InterceptMethod.VBAR_HOP} <= already
        assert not any(i["counts"] for i in items if i["method"] in already)
        best = maneuver._most_likely(items)
        assert best is None or best["result"].total_delta_v_m_s > 0.0

    def test_the_page_labels_it(self) -> None:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        html = _render(self._items(), Environment, FileSystemLoader, StrictUndefined)
        assert "Already within" in html


def _render(items: list[dict[str, Any]], environment: Any, loader: Any, strict: Any) -> str:
    """The batch partial rendered under StrictUndefined, with the app's own filters and globals."""
    from spectre.web.app import templates as app_templates

    env = environment(loader=loader("spectre/web/templates"), autoescape=True, undefined=strict)
    env.filters.update(app_templates.env.filters)
    env.globals.update(app_templates.env.globals)
    return env.get_template("partials/all_intercepts_result.html").render(
        items=items, error=None, red_name="RED", blue_name="BLUE", intercept_history=[], intercept_data_mode="REAL",
        most_likely=maneuver._most_likely(items), searched=True, evidence=shipped_evidence().fleet,
        approach_km=50.0, fastest_budget=(36.77, "what nine in ten satellites stay within"), csrf_token="",
    )


class TestNothingCounts:
    def test_the_partial_renders_under_strict_undefined(self) -> None:
        """Review of SPC-234: selectattr | first is undefined when nothing counts, and StrictUndefined raised."""
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        items = TestTheRows()._items(search=False)
        for item in items:
            item["counts"] = False
        html = _render(items, Environment, FileSystemLoader, StrictUndefined)
        assert "No red approach both reaches the target" in html
        assert "Worst-case" not in html


#: Decays within days: 160 km perigee and a large drag term, epoch 1 March 2026.
_DECAYING = (
    "1 90007U 26001A   26060.00000000  .00000000  00000-0  50000-0 0  9990\n"
    "2 90007  51.6400 208.9163 0006703  40.5765 319.5681 16.30000000    10"
)


@pytest.fixture()
def decaying_red(auth_cookie: str) -> Any:
    from spectre.domain.models import BlueAsset, RedTrack
    from tests.integration.conftest import session_state

    state = session_state(auth_cookie)
    saved = list(state.red_tracks), list(state.blue_assets)
    blue = "\n".join(_checksummed(line) for line in (
        "1 90008U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990",
        "2 90008  51.6400 208.9163 0006703  40.5765 321.5681 15.49560532    10"))
    state.red_tracks = [RedTrack(name="RED-DECAY", tle="\n".join(_checksummed(x) for x in _DECAYING.splitlines()))]
    state.blue_assets = [BlueAsset(name="BLUE-LEO", tle=blue)]
    yield state
    state.red_tracks, state.blue_assets = saved


def _checksummed(line: str) -> str:
    total = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68])
    return line[:68] + str(total % 10)


@pytest.mark.usefixtures("decaying_red")
class TestADecayedRedSetIsReportedNotA500:
    """Review of SPC-234: the burn points and revolution ran outside each method's guard, so SGP4's decay error
    (code 6) failed the whole route."""

    @pytest.mark.parametrize("mode", ["search", "typed"])
    def test_each_method_reports_its_own_error(self, client: Any, auth_cookie: str, mode: str) -> None:
        data = {"red_sat": "RED-DECAY", "blue_sat": "BLUE-LEO", "manoeuvre_start": "2026-04-15T00:00:00",
                "targeting_mode": mode}
        resp = client.post(_ROUTE, data=data, cookies={"spectre_session": auth_cookie},
                           headers=csrf_headers(auth_cookie))
        assert resp.status_code == 200
        assert "FAILED" in resp.text and "SGP4" in resp.text


class TestTheFormIsBounded:
    """Review of SPC-234: the approach distance now sets the radius, so a bad figure is a 422, not a 500 or a silent
    change of radius."""

    @pytest.mark.parametrize(("field", "value"), [
        ("target_distance_m", "1e12"), ("target_distance_m", "-5000"), ("target_distance_m", "inf"),
        ("target_distance_m", "nan"), ("coast_hours", "-1"), ("coast_hours", "inf"), ("coast_hours", "1e9"),
        ("intercept_hours", "nan"), ("intercept_hours", "0"), ("intercept_hours", "1e9"), ("max_dv_m_s", "nan"),
    ])
    @pytest.mark.parametrize("route", [_ROUTE, "/plan/maneuver/apply-intercept"])
    def test_a_bad_figure_is_refused(self, client: Any, auth_cookie: str, route: str, field: str, value: str) -> None:
        data = {"red_sat": "RED-GEO", "blue_sat": "BLUE-GEO", "method": "lambert", field: value}
        resp = client.post(route, data=data, cookies={"spectre_session": auth_cookie},
                           headers=csrf_headers(auth_cookie))
        assert resp.status_code == 422


def test_the_max_dv_hover_names_the_record_holder_from_the_data() -> None:
    """The hover hard-coded COSMOS 2589; it reads the holder from the shipped record, as the value does (review)."""
    from pathlib import Path

    from spectre.web.app import templates as app_templates

    page = (Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / "operator.html").read_text(
        encoding="utf-8")
    assert "COSMOS 2589" not in page and "{{ engine_budget_holder }}" in page
    assert app_templates.env.globals["engine_budget_holder"] == "COSMOS 2589"
