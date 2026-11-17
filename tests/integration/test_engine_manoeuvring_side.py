"""The Intercept Engine plans the satellite the operator chose, and its table shows each row's miss (0.47.0).

Audit 4-3 and 2-11: the engine always planned the Red satellite's manoeuvre against the Blue target, so a scenario
in which blue moves (planner_05, cadet_03) could not be planned, and "R-Bar hop: UNKNOWN-RSO comes within 1.3 km of
BLUE-INS" moved the wrong satellite. The form now carries Manoeuvring satellite, Red by default; Blue plans every
method with the roles swapped. Audit 3-5: the ranked table had no miss distance, so up to 23 rows had to be opened.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pytest

from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_ROUTE = "/plan/maneuver/apply-all-intercepts"

#: Two GEO objects one degree apart (as tests/integration/test_all_intercepts_ranking.py).
_RED_GEO = (
    "1 90001U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9993\n"
    "2 90001   0.0500  95.0000 0001000   0.0000  10.0000  1.00270000    14"
)
_BLUE_GEO = (
    "1 90002U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9994\n"
    "2 90002   0.0500  95.0000 0001000   0.0000  11.0000  1.00270000    16"
)


@pytest.fixture()
def seeded(auth_cookie: str) -> Any:
    """RED-GEO and BLUE-GEO, and a second pair holding the same two sets the other way round."""
    from spectre.domain.models import BlueAsset, RedTrack

    state = session_state(auth_cookie)
    saved = list(state.red_tracks), list(state.blue_assets), list(state.intercept_history)
    state.red_tracks = [RedTrack(name="RED-GEO", tle=_RED_GEO), RedTrack(name="RED-SWAP", tle=_BLUE_GEO)]
    state.blue_assets = [BlueAsset(name="BLUE-GEO", tle=_BLUE_GEO), BlueAsset(name="BLUE-SWAP", tle=_RED_GEO)]
    yield state
    state.red_tracks, state.blue_assets, state.intercept_history = saved[0], saved[1], saved[2]


def _post(client: Any, auth_cookie: str, red: str, blue: str, **extra: str) -> Any:
    return client.post(
        _ROUTE,
        data={"red_sat": red, "blue_sat": blue, "manoeuvre_start": "2026-03-01T00:00:00", "coast_hours": "0.0",
              "intercept_hours": "6.0", "targeting_mode": "typed", **extra},
        cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
    )


def _row(html: str, method: str) -> str:
    match = re.search(rf'<tr class="threat-parent[^"]*"[^>]*data-sort-1="{method}".*?</tr>', html, re.S)
    assert match, f"no {method} row"
    return match.group(0)


def _flat(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


class TestManoeuvringSatellite:
    def test_red_is_the_default_and_unchanged(self, client: Any, auth_cookie: str, seeded: Any) -> None:
        html = _post(client, auth_cookie, "RED-GEO", "BLUE-GEO").text
        assert "Manoeuvring: RED-GEO (Red)" in _flat(html)
        assert {r.chaser_side for r in seeded.intercept_history} == {"red"}
        assert "RED-GEO burns" in _flat(_row(html, "lambert"))
        assert "BLUE-GEO burns" in _flat(_row(html, "evasion")), "evasion moves the defended satellite"

    def test_blue_plans_with_the_roles_swapped(self, client: Any, auth_cookie: str, seeded: Any) -> None:
        html = _post(client, auth_cookie, "RED-GEO", "BLUE-GEO", manoeuvring="blue").text
        flat = _flat(html)
        assert "Manoeuvring: BLUE-GEO (Blue)" in flat
        assert {r.chaser_side for r in seeded.intercept_history} == {"blue"}
        assert {(r.red_name, r.blue_name) for r in seeded.intercept_history} == {("RED-GEO", "BLUE-GEO")}
        assert "BLUE-GEO burns" in _flat(_row(html, "lambert"))
        assert "BLUE-GEO burns" in _flat(_row(html, "cola"))
        assert "RED-GEO burns" in _flat(_row(html, "evasion"))
        # A solver's refusal calls its chaser "red"; with blue as the chaser the row says who that is.
        assert "(chaser: BLUE-GEO)" in flat
        swapped = {r.method: r.total_delta_v_m_s for r in seeded.intercept_history}

        # The same plan as red manoeuvring with the two element sets exchanged: blue's set really is the chaser's.
        _post(client, auth_cookie, "RED-SWAP", "BLUE-SWAP")
        exchanged = {r.method: r.total_delta_v_m_s for r in seeded.intercept_history if r.method in swapped}
        assert len(swapped) > 10
        assert swapped == pytest.approx(exchanged)

    def test_blue_reads_as_our_own_plan(self, client: Any, auth_cookie: str, seeded: Any) -> None:
        """0.47.0 review, S2: no worst case, no threat column and no adversary assessments for our own plans."""
        html = _post(client, auth_cookie, "RED-GEO", "BLUE-GEO", manoeuvring="blue").text
        flat = _flat(html)
        assert "Worst-case" not in flat and "Most likely course of action" not in flat
        assert "Cheapest option" in flat
        assert re.search(r">\s*Posture\s*<span", html) and not re.search(r">\s*Threat\s*<span", html)
        assert "OFFENSIVE" not in flat and "OWN APPROACH" in flat
        for left_out in ("fingerprint", "manoeuvre_detect", "intent_predict"):
            assert f'data-sort-1="{left_out}"' not in html
        assert "FINGERPRINT, INTENT_PREDICT, MANOEUVRE_DETECT assessments are left out" in flat
        assert 'data-manoeuvring="blue"' in _row(html, "lambert")

    def test_red_keeps_the_threat_wording(self, client: Any, auth_cookie: str, seeded: Any) -> None:
        html = _post(client, auth_cookie, "RED-GEO", "BLUE-GEO").text
        assert re.search(r">\s*Threat\s*<span", html)
        assert 'data-sort-1="fingerprint"' in html
        assert 'data-manoeuvring="red"' in _row(html, "lambert")


class TestTheOtherViewsNameTheBurner:
    def test_the_trade_space_label_names_the_satellite_that_burns(
        self, client: Any, auth_cookie: str, seeded: Any,
    ) -> None:
        _post(client, auth_cookie, "RED-GEO", "BLUE-GEO")
        points = client.get("/plan/maneuver/trade-space-data", cookies={"spectre_session": auth_cookie}).json()
        labels = {p["method"]: p["label"] for p in points}
        assert labels["evasion"] == "evasion: BLUE-GEO→RED-GEO"
        assert labels["lambert"] == "lambert: RED-GEO→BLUE-GEO"

    @pytest.mark.parametrize("case", [("evasion", "BLUE-GEO", "RED-GEO"), ("lambert", "RED-GEO", "BLUE-GEO")])
    def test_the_geometry_view_flies_the_burn_on_the_satellite_that_burns(
        self, client: Any, auth_cookie: str, seeded: Any, case: tuple[str, str, str],
    ) -> None:
        method, burner, other = case
        resp = client.post(
            "/plan/maneuver/apply-intercept",
            data={"red_sat": "RED-GEO", "blue_sat": "BLUE-GEO", "method": method,
                  "manoeuvre_start": "2026-03-01T00:00:00", "coast_hours": "0.0", "intercept_hours": "6.0"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        form = re.search(r'<form hx-post="/plan/geometry/intercept".*?</form>', resp.text, re.S)
        assert form, "no geometry view offered"
        assert f'name="red_sat"       value="{burner}"' in form.group(0)
        assert f'name="blue_sat"      value="{other}"' in form.group(0)

    def test_anything_else_is_refused(self, client: Any, auth_cookie: str, seeded: Any) -> None:
        assert _post(client, auth_cookie, "RED-GEO", "BLUE-GEO", manoeuvring="green").status_code == 422

    def test_the_form_offers_the_choice_with_red_first(self, client: Any, auth_cookie: str) -> None:
        page = client.get("/", cookies={"spectre_session": auth_cookie}).text
        select = re.search(r'<select name="manoeuvring"[^>]*>(.*?)</select>', page, re.S)
        assert select, "the engine form has no Manoeuvring satellite choice"
        assert re.findall(r'value="(\w+)"', select.group(1)) == ["red", "blue"]
        assert 'value="red" selected' in select.group(1)


class TestTheMissColumn:
    def test_each_row_shows_its_miss_without_opening_it(self, client: Any, auth_cookie: str, seeded: Any) -> None:
        html = _post(client, auth_cookie, "RED-GEO", "BLUE-GEO").text
        assert "Miss Dist (km)" in html
        by_method = {r.method.value: r for r in seeded.intercept_history}
        lambert = by_method["lambert"].intercept_range_km
        cell = re.search(r'<td class="ai-miss"[^>]*>([^<]*)</td>', _row(html, "lambert"))
        assert cell and cell.group(1) == (f"{lambert:.2f}" if lambert < 10 else f"{lambert:.1f}")
        # The GEO pair is co-orbital, 736 km apart: no closest approach near the assumed TCA, so the cell is the
        # window-edge floor, never presented as a closest approach (review S1), and its title says to check the TCA.
        cola = by_method["cola"]
        cola_cell = re.search(r'<td class="ai-miss"[^>]*title="([^"]*)"[^>]*>([^<]*)</td>', _row(html, "cola"))
        assert cola_cell and "assumed TCA" in cola_cell.group(1)
        assert cola.edge_floor_km is not None and math.isnan(cola.intercept_range_km)
        assert cola_cell.group(2) == f"≥{cola.edge_floor_km:.1f}"
        assert "check the TCA" in cola_cell.group(1)
        assert 'data-sort-6=""' in _row(html, "cola"), "a floor sorts with the figures not computed"
        stability = re.search(r'<td class="ai-miss"[^>]*>([^<]*)</td>', _row(html, "stability"))
        assert stability and stability.group(1) == "—", "a score is not a distance"
