"""The Assets panel's element cards and the session's Blue assets in Asset Screening.

Training audit 2026-11-16, findings 2-1 and 2-3 (and cross-cutting finding X5). The panel listed names only, and the
screening selector listed HRR objects only, so a training scenario's BLUE-01 could neither be read nor screened.
These drive the real routes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.planning_state import ElsetRefresh
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

pytestmark = pytest.mark.anyio

# A GEO set with a catalogue number no HRR object holds.
_BLUE_GEO = (
    "1 99001U 26001A   26250.50000000 -.00000100  00000-0  00000-0 0  9990\n"
    "2 99001   0.0400  95.0000 0002000 270.0000 180.0000  1.00271000    11"
)
_RED_TLE = (
    "1 41838U 16065A   26250.50000000  .00000000  00000-0  00000-0 0  9992\n"
    "2 41838   3.4700  83.3000 0005000 310.0000 124.0000  1.00270000 26266"
)
_SKYNET = (
    "1 30793U 07007A   26250.50000000 -.00000100  00000-0  00000-0 0  9998\n"
    "2 30793   0.0400  95.0000 0002000 270.0000 180.0000  1.00271000 46216"
)
_HRR = [
    {"satno": "41838", "name": "SJ-17", "country": "CHN", "rank": 1, "orbit_regime": "GEO"},
    {"satno": "30793", "name": "SKYNET-5A", "country": "GBR", "rank": 1, "orbit_regime": "GEO"},
]
_TRIGGER = "HX-Trigger"


@pytest.fixture
def seeded(auth_cookie: str) -> Iterator[object]:
    """The session with a training Blue asset, a Red track whose set does not parse, and a two-object watchlist."""
    state = session_state(auth_cookie)
    saved = (list(state.blue_assets), list(state.red_tracks), list(state.hrr_objects), dict(state.hrr_tle_cache),
             dict(state.hrr_tle_data_mode), state.scenario_start, state.scenario_stop, state.elset_refresh)
    state.blue_assets = [BlueAsset(name="BLUE-01", tle=_BLUE_GEO, training=True, data_mode="SYNTHETIC")]
    state.red_tracks = [RedTrack(name="GARBLED", tle="not\nan element set")]
    state.hrr_objects = list(_HRR)
    state.hrr_tle_cache.update({"41838": _RED_TLE, "30793": _SKYNET})
    state.hrr_tle_data_mode.update({"41838": "REAL", "30793": "REAL"})
    try:
        yield state
    finally:
        (state.blue_assets, state.red_tracks, state.hrr_objects, cache, modes,
         state.scenario_start, state.scenario_stop, state.elset_refresh) = saved
        state.hrr_tle_cache.clear()
        state.hrr_tle_cache.update(cache)
        state.hrr_tle_data_mode.clear()
        state.hrr_tle_data_mode.update(modes)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _post(client: object, cookie: str, path: str, data: dict[str, object]) -> object:
    return client.post(  # type: ignore[attr-defined]
        path, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )


def _get(client: object, cookie: str, path: str, params: dict[str, str] | None = None) -> object:
    return client.get(path, params=params, cookies={"spectre_session": cookie})  # type: ignore[attr-defined]


class TestTheElementCard:
    def test_the_console_shows_each_blue_assets_elements_behind_its_name(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        flat = _flat(_get(client, auth_cookie, "/").text)  # type: ignore[attr-defined]
        assert '<details class="elset-card"> <summary class="asset-name"' in flat
        for shown in ('aria-hidden="true">&#9654;</span> BLUE-01</summary>', "Data mode</dt><dd>SYNTHETIC",
                      "RAAN</dt><dd>95.00&deg;", "Inclination</dt><dd>0.04&deg;", "Arg. of perigee</dt><dd>270.00&deg;",
                      "Mean anomaly</dt><dd>180.00&deg;", "Eccentricity</dt><dd>0.0002000", "Regime</dt><dd>GEO",
                      "Epoch</dt><dd>2026-09-07 12:00:00 UTC"):
            assert shown in flat, shown
        assert "° E at now" in flat or "° W at now" in flat

    def test_a_set_that_does_not_parse_gets_no_card_and_says_so(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        flat = _flat(_get(client, auth_cookie, "/").text)  # type: ignore[attr-defined]
        assert '<span class="asset-name">GARBLED</span>' in flat
        assert "Element set does not parse: no elements to show." in flat

    def test_a_leo_object_says_why_it_has_no_longitude(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        iss = ("1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9999\n"
               "2 25544  51.6420 195.0000 0001207  86.9689 273.1630 15.54320000365490")
        session_state(auth_cookie).red_tracks = [RedTrack(name="ISS", tle=iss)]  # type: ignore[attr-defined]
        flat = _flat(_get(client, auth_cookie, "/").text)  # type: ignore[attr-defined]
        assert "Sub-satellite lon.</dt> <dd>none: not near geostationary, so the point under it circles the Earth" in flat

    def test_an_added_asset_comes_back_with_its_card_and_tells_the_screening_selector(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        resp = _post(client, auth_cookie, "/assets/blue", {"name": "SKY-B", "tle": _SKYNET})
        assert resp.status_code == 200  # type: ignore[attr-defined]
        assert resp.headers[_TRIGGER] == "blueAssetsChanged"  # type: ignore[attr-defined]
        assert "&#9654;</span> SKY-B</summary>" in resp.text  # type: ignore[attr-defined]
        assert "Data mode</dt><dd>MANUAL" in _flat(resp.text)  # type: ignore[attr-defined]

    def test_a_new_scenario_time_redraws_both_lists_at_that_time(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        resp = _post(client, auth_cookie, "/scenario/time",
                     {"scenario_start": "2026-09-07T18:00:00", "scenario_stop": "2026-09-08T18:00:00"})
        flat = _flat(resp.text)  # type: ignore[attr-defined]
        assert '<div id="blue-list" hx-swap-oob="innerHTML">' in flat
        assert '<div id="red-list" hx-swap-oob="innerHTML">' in flat
        assert "6.0 h old at scenario time (2026-09-07 18:00 UTC)" in flat
        assert "at scenario time</dd>" in flat


class TestTheSelectorIsToldOnlyOfARealChange:
    """Review of 0.47.0: every Blue-list answer reloaded the selector, even a refused or duplicate add."""

    def test_a_duplicate_add_does_not(self, client: object, auth_cookie: str, seeded: object) -> None:
        resp = _post(client, auth_cookie, "/assets/blue", {"name": "BLUE-01", "tle": _SKYNET})
        assert "already in the session" in resp.text  # type: ignore[attr-defined]
        assert _TRIGGER not in resp.headers  # type: ignore[attr-defined]

    def test_a_refused_add_does_not(self, client: object, auth_cookie: str, seeded: object) -> None:
        resp = _post(client, auth_cookie, "/assets/blue", {"name": "BAD", "tle": "not an element set"})
        assert _TRIGGER not in resp.headers  # type: ignore[attr-defined]

    def test_removing_an_asset_does_and_removing_none_does_not(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        def delete(name: str) -> object:
            return client.delete(  # type: ignore[attr-defined]
                f"/assets/blue/{name}", cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
            )

        assert _TRIGGER not in delete("NOT-HELD").headers  # type: ignore[attr-defined]
        assert delete("BLUE-01").headers[_TRIGGER] == "blueAssetsChanged"  # type: ignore[attr-defined]

    def test_the_red_list_never_does(self, client: object, auth_cookie: str, seeded: object) -> None:
        resp = _post(client, auth_cookie, "/assets/red", {"name": "RED-NEW", "tle": _RED_TLE})
        assert "RED-NEW" in resp.text  # type: ignore[attr-defined]
        assert _TRIGGER not in resp.headers  # type: ignore[attr-defined]


class TestTheConnectRefreshRedrawsTheCards:
    """Review of 0.47.0: a refresh that replaced held sets left every card showing the old one."""

    def _finished(self, state: object, updated: list[str]) -> None:
        now = datetime(2026, 9, 8, tzinfo=UTC)
        state.elset_refresh = ElsetRefresh(  # type: ignore[attr-defined]
            started_at=now, finished_at=now, running=False, updated=updated,
        )

    def test_an_updated_blue_set_redraws_both_lists_and_tells_the_selector(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        self._finished(seeded, ["blue BLUE-01"])
        resp = _get(client, auth_cookie, "/udl/elset-refresh")
        flat = _flat(resp.text)  # type: ignore[attr-defined]
        assert "1 updated" in flat
        assert '<div id="blue-list" hx-swap-oob="innerHTML">' in flat
        assert '<div id="red-list" hx-swap-oob="innerHTML">' in flat
        assert "BLUE-01</summary>" in flat
        assert resp.headers[_TRIGGER] == "blueAssetsChanged"  # type: ignore[attr-defined]

    def test_an_updated_red_set_redraws_the_lists_without_reloading_the_selector(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        self._finished(seeded, ["red GARBLED"])
        resp = _get(client, auth_cookie, "/udl/elset-refresh")
        assert '<div id="red-list" hx-swap-oob="innerHTML">' in resp.text  # type: ignore[attr-defined]
        assert _TRIGGER not in resp.headers  # type: ignore[attr-defined]

    def test_nothing_updated_redraws_nothing(self, client: object, auth_cookie: str, seeded: object) -> None:
        self._finished(seeded, [])
        resp = _get(client, auth_cookie, "/udl/elset-refresh")
        assert "hx-swap-oob" not in resp.text  # type: ignore[attr-defined]

    def test_it_is_announced_once(self, client: object, auth_cookie: str, seeded: object) -> None:
        self._finished(seeded, ["blue BLUE-01"])
        _get(client, auth_cookie, "/udl/elset-refresh")
        again = _get(client, auth_cookie, "/udl/elset-refresh")
        assert "hx-swap-oob" not in again.text  # type: ignore[attr-defined]


class TestTheScreeningSelector:
    def test_it_lists_the_session_blue_assets_after_the_hrr_objects_with_their_data_mode(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        flat = _flat(_get(client, auth_cookie, "/plan/threat/screen-config").text)  # type: ignore[attr-defined]
        hrr = '<option value="30793">SKYNET-5A [30793] · GEO · R1</option>'
        blue = '<option value="blue:BLUE-01">BLUE-01 [99001] · GEO · SYNTHETIC</option>'
        assert hrr in flat, "the HRR option is unchanged"
        assert blue in flat
        assert flat.index(hrr) < flat.index('<optgroup label="Session Blue Assets">') < flat.index(blue)
        assert "SJ-17" not in flat.split("<select", 1)[1].split("</select>", 1)[0]
        assert 'id="scr-max-dv" value="500"' in flat

    def test_a_reload_keeps_the_asset_chosen_and_the_budget_typed(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        params = {"asset_satno": "blue:BLUE-01", "max_dv_m_s": "1234"}
        flat = _flat(_get(client, auth_cookie, "/plan/threat/screen-config", params).text)  # type: ignore[attr-defined]
        assert '<option value="blue:BLUE-01" selected>' in flat
        assert '<option value="30793">' in flat
        assert 'id="scr-max-dv" value="1234"' in flat
        hrr = _flat(_get(client, auth_cookie, "/plan/threat/screen-config", {"asset_satno": "30793"}).text)  # type: ignore[attr-defined]
        assert '<option value="30793" selected>' in hrr

    @pytest.mark.parametrize("typed", ["", "abc", "-5", "1e9", "nan"])
    def test_a_budget_it_would_refuse_reverts_to_the_default(
        self, client: object, auth_cookie: str, seeded: object, typed: str,
    ) -> None:
        resp = _get(client, auth_cookie, "/plan/threat/screen-config", {"max_dv_m_s": typed})
        assert 'id="scr-max-dv" value="500"' in resp.text  # type: ignore[attr-defined]

    def test_with_no_session_blue_assets_it_is_as_it_was(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        session_state(auth_cookie).blue_assets = []  # type: ignore[attr-defined]
        resp = _get(client, auth_cookie, "/plan/threat/screen-config")
        assert "optgroup" not in resp.text  # type: ignore[attr-defined]
        assert "blue:" not in resp.text  # type: ignore[attr-defined]

    def test_it_offers_a_session_blue_asset_with_no_blue_hrr_object(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        session_state(auth_cookie).hrr_objects = [_HRR[0]]  # type: ignore[attr-defined]
        resp = _get(client, auth_cookie, "/plan/threat/screen-config")
        assert 'value="blue:BLUE-01"' in resp.text  # type: ignore[attr-defined]
        assert "holds no blue objects" not in resp.text  # type: ignore[attr-defined]


class TestScreeningASessionBlueAsset:
    def _screen(self, client: object, cookie: str, **data: object) -> str:
        resp = _post(client, cookie, "/plan/threat/screen", {"max_dv_m_s": 5000, **data})
        assert resp.status_code == 200  # type: ignore[attr-defined]
        return _flat(resp.text)  # type: ignore[attr-defined]

    def test_it_runs_from_the_assets_own_set_and_names_its_data_mode(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        flat = self._screen(client, auth_cookie, asset_satno="blue:BLUE-01")
        assert "Asset Screening: BLUE-01 [99001]" in flat
        assert "SJ-17" in flat, "the one candidate actor must be ranked"
        assert "SYNTHETIC: asset BLUE-01" in flat
        assert "No element set cached" not in flat

    def test_an_asset_removed_since_the_list_loaded_says_so(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        flat = self._screen(client, auth_cookie, asset_satno="blue:GONE")
        assert "Blue asset GONE is no longer in the session." in flat

    def test_an_hrr_asset_still_screens_from_the_cache(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        flat = self._screen(client, auth_cookie, asset_satno="30793")
        assert "Asset Screening: SKYNET-5A [30793]" in flat
        assert "SJ-17" in flat

    @pytest.mark.parametrize(("mode", "line"), [("REAL", None), ("SYNTHETIC", "SYNTHETIC: asset SKYNET-5A")])
    def test_an_hrr_assets_provenance_banner_is_the_caches(
        self, client: object, auth_cookie: str, seeded: object, mode: str, line: str | None,
    ) -> None:
        session_state(auth_cookie).hrr_tle_data_mode["30793"] = mode  # type: ignore[attr-defined]
        flat = self._screen(client, auth_cookie, asset_satno="30793")
        if line is None:
            assert "Element sets not from live tracking" not in flat
        else:
            assert "Element sets not from live tracking" in flat
            assert line in flat


class TestTheAssetIsNeverItsOwnActor:
    """Review of 0.47.0: SJ-17 quick-added to Blue was screened against itself."""

    def test_a_session_blue_copy_of_a_red_hrr_object_is_not_screened_against_itself(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        session_state(auth_cookie).blue_assets = [  # type: ignore[attr-defined]
            BlueAsset(name="SJ-17", tle=_RED_TLE, data_mode="REAL"),
        ]
        flat = TestScreeningASessionBlueAsset()._screen(client, auth_cookie, asset_satno="blue:SJ-17")
        assert "No other red HRR object is in a regime compatible with GEO." in flat
        assert "SJ-17 (41838) is the asset screened, so it is not screened as an actor against itself." in flat
        assert "MOST DANGEROUS ACTOR" not in flat

    def test_nor_is_a_pasted_set(self, client: object, auth_cookie: str, seeded: object) -> None:
        flat = TestScreeningASessionBlueAsset()._screen(client, auth_cookie, manual_asset_tle=_RED_TLE)
        assert "SJ-17 (41838) is the asset screened" in flat
        assert "MOST DANGEROUS ACTOR" not in flat

    def test_other_actors_are_still_screened_and_the_note_says_why_one_is_missing(
        self, client: object, auth_cookie: str, seeded: object,
    ) -> None:
        state = session_state(auth_cookie)
        state.blue_assets = [BlueAsset(name="SJ-17", tle=_RED_TLE, data_mode="REAL")]  # type: ignore[attr-defined]
        state.hrr_objects = [*_HRR, {"satno": "30794", "name": "OTHER-RED", "country": "RUS", "rank": 1,  # type: ignore[attr-defined]
                                     "orbit_regime": "GEO"}]
        state.hrr_tle_cache["30794"] = _RED_TLE.replace("41838", "30794")  # type: ignore[attr-defined]
        try:
            flat = TestScreeningASessionBlueAsset()._screen(client, auth_cookie, asset_satno="blue:SJ-17")
        finally:
            state.hrr_tle_cache.pop("30794", None)  # type: ignore[attr-defined]
        assert "OTHER-RED" in flat
        assert "is the asset screened, so it is not screened as an actor against itself" in flat


def test_the_fixture_epoch_is_what_the_cards_read() -> None:
    """The scenario-time test's 6.0 h rests on this epoch."""
    from spectre.astro.pattern_of_life import _parse_tle_epoch

    assert _parse_tle_epoch(_BLUE_GEO.splitlines()[0]) == datetime(2026, 9, 7, 12, tzinfo=UTC)
