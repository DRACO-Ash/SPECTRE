"""Screening a blue asset, through the real endpoint.

The unit tests pin the ranking rule and the panel. These exercise the route:
that it refuses clearly when it cannot proceed, that it never returns an empty
result without a reason, and that the three-click path actually resolves.
"""

from __future__ import annotations

import pytest

from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

pytestmark = pytest.mark.anyio

# A real GEO element set, used as a manual asset so the screen can run without
# a UDL session.
_ASSET_TLE = (
    "1 30793U 07007A   26250.50000000 -.00000100  00000-0  00000-0 0  9995\n"
    "2 30793   0.0400  95.0000 0002000 270.0000 180.0000  1.00271000 46210"
)
_RED_TLE = (
    "1 41838U 16065A   26250.50000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 41838   3.4700  83.3000 0005000 310.0000 124.0000  1.00270000 26260"
)


def _screen(client: object, cookie: str, **data: object) -> object:
    return client.post(  # type: ignore[attr-defined]
        "/plan/threat/screen",
        data=data,
        cookies={"spectre_session": cookie},
        headers=csrf_headers(cookie),
    )


class TestTheScreenRefusesClearly:
    """Every empty answer carries a reason. Silence reads as safety."""

    def test_no_asset_selected_says_so(self, client: object, auth_cookie: str) -> None:
        resp = _screen(client, auth_cookie)
        assert resp.status_code == 200
        assert "Select a blue asset" in resp.text

    def test_an_invalid_manual_tle_says_why(self, client: object, auth_cookie: str) -> None:
        resp = _screen(client, auth_cookie, manual_asset_tle="not a tle at all")
        assert resp.status_code == 200
        assert "Manual asset TLE invalid" in resp.text

    def test_an_uncached_asset_says_what_to_do(self, client: object, auth_cookie: str) -> None:
        resp = _screen(client, auth_cookie, asset_satno="99999")
        assert resp.status_code == 200
        assert "No element set cached" in resp.text
        assert "Fetch the HRR watchlist" in resp.text

    def test_an_empty_watchlist_says_so_rather_than_rendering_blank(
        self, client: object, auth_cookie: str
    ) -> None:
        """A valid asset with no watchlist must not look like safety.

        This is no longer the default state: a bootstrap watchlist ships with
        the package, so a fresh session always has candidates. The empty case
        is reached only by clearing it, which is what this does, because the
        branch still has to say something when an operator wipes the list.
        """

        state = session_state(auth_cookie)
        saved_objects = list(state.hrr_objects)
        state.hrr_objects = []
        try:
            resp = _screen(client, auth_cookie, manual_asset_tle=_ASSET_TLE)
            assert resp.status_code == 200
            assert "No HRR watchlist" in resp.text, (
                "an empty candidate set must be explained, never rendered blank"
            )
        finally:
            state.hrr_objects = saved_objects

    def test_a_fresh_session_can_screen_without_udl(
        self, client: object, auth_cookie: str
    ) -> None:
        """The point of bundling a watchlist: it runs out of the box.

        Before this, a deployed instance had no watchlist and the screen
        stalled at "fetch the HRR list from the UDL panel first", so nobody
        without UDL credentials could see the capability work at all.
        """
        resp = _screen(client, auth_cookie, asset_satno="30793", max_dv_m_s=500)
        assert resp.status_code == 200
        assert "MOST DANGEROUS ACTOR" in resp.text, (
            "a fresh session must be able to rank candidate actors with no "
            "UDL connection"
        )
        assert "candidate actor(s)" in resp.text
        # Audit F-039: the bundled watchlist is SYNTHETIC, and the result
        # built from it has to say so where it is read.
        assert "not from live tracking" in " ".join(resp.text.split())
        assert 'class="provenance-badge"' in resp.text


class TestTheScreenRunsAgainstAWatchlist:
    def test_it_ranks_a_red_object_that_can_reach_the_asset(
        self, client: object, auth_cookie: str
    ) -> None:

        state = session_state(auth_cookie)
        saved_objects, saved_cache = list(state.hrr_objects), dict(state.hrr_tle_cache)
        state.hrr_objects = [
            {"satno": "41838", "name": "SJ-17", "country": "CHN",
             "rank": 1, "orbit_regime": "GEO"},
            {"satno": "30793", "name": "SKYNET-5A", "country": "GBR",
             "rank": 1, "orbit_regime": "GEO"},
        ]
        state.hrr_tle_cache["41838"] = _RED_TLE
        state.hrr_tle_cache["30793"] = _ASSET_TLE
        try:
            resp = _screen(client, auth_cookie, asset_satno="30793", max_dv_m_s=5000)
            assert resp.status_code == 200
            assert "Asset Screening" in resp.text
            assert "SJ-17" in resp.text, "the one candidate actor must be listed"
            assert "km/s" not in resp.text
        finally:
            # Restore rather than clear: the cache is shared, and clearing it
            # wiped the bootstrap element sets for every later test.
            state.hrr_objects = saved_objects
            state.hrr_tle_cache.clear()
            state.hrr_tle_cache.update(saved_cache)

    def test_a_blue_only_watchlist_reports_no_candidates(
        self, client: object, auth_cookie: str
    ) -> None:

        state = session_state(auth_cookie)
        saved_objects, saved_cache = list(state.hrr_objects), dict(state.hrr_tle_cache)
        state.hrr_objects = [
            {"satno": "30793", "name": "SKYNET-5A", "country": "GBR",
             "rank": 1, "orbit_regime": "GEO"},
        ]
        state.hrr_tle_cache["30793"] = _ASSET_TLE
        try:
            resp = _screen(client, auth_cookie, asset_satno="30793")
            assert resp.status_code == 200
            assert "No red HRR objects" in resp.text
            assert "0 red object(s) were considered" in resp.text
        finally:
            # Restore rather than clear: the cache is shared, and clearing it
            # wiped the bootstrap element sets for every later test.
            state.hrr_objects = saved_objects
            state.hrr_tle_cache.clear()
            state.hrr_tle_cache.update(saved_cache)


class TestTheAssetSelector:
    def test_it_lists_only_blue_objects(self, client: object, auth_cookie: str) -> None:

        state = session_state(auth_cookie)
        state.hrr_objects = [
            {"satno": "41838", "name": "SJ-17", "country": "CHN",
             "rank": 1, "orbit_regime": "GEO"},
            {"satno": "30793", "name": "SKYNET-5A", "country": "GBR",
             "rank": 1, "orbit_regime": "GEO"},
        ]
        state.udl_username = "someone"
        try:
            resp = client.get(  # type: ignore[attr-defined]
                "/plan/threat/screen-config",
                cookies={"spectre_session": auth_cookie},
            )
            assert resp.status_code == 200
            assert "SKYNET-5A" in resp.text
            assert "SJ-17" not in resp.text, (
                "a red object is a candidate actor, never an asset to screen"
            )
            assert "1 red object(s) on the watchlist" in resp.text
        finally:
            state.hrr_objects = []
            state.udl_username = None


class TestAFailedRefreshIsShown:
    """Audit F-135: an actor screened after a failed refresh says so on the result."""

    def test_the_note_reaches_the_provenance_banner(self, client: object, auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.routes import udl

        async def _down(*_a: object, **_k: object) -> None:
            return None

        monkeypatch.setattr(udl, "fetch_tle_for_satno", _down)
        state = session_state(auth_cookie)
        saved = (state.udl_username, state.udl_password, state.hrr_objects)
        state.udl_username, state.udl_password = "u", "p"
        state.hrr_objects = [{"satno": "41838", "name": "SJ-17", "country": "CHN", "rank": 1, "orbit_regime": "GEO"}]
        state.hrr_tle_cache["41838"] = _RED_TLE
        state.hrr_tle_data_mode["41838"] = "SYNTHETIC"
        try:
            resp = _screen(client, auth_cookie, manual_asset_tle=_ASSET_TLE, max_dv_m_s=5000)
        finally:
            state.udl_username, state.udl_password, state.hrr_objects = saved
            state.hrr_tle_cache.pop("41838", None)
            state.hrr_tle_data_mode.pop("41838", None)
        flat = " ".join(resp.text.split())  # type: ignore[attr-defined]
        assert "SJ-17 (41838): live element set not fetched; screened on the set already held" in flat
