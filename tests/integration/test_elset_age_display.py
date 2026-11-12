"""The red card and the sweep say how old their element sets are.

In service a 13-day-old GEO set sat on the red card and fed a sweep with no
sign of its age. Both now state it, flagged STALE past the regime's limit
(72 hours for GEO), and the sweep names the stale ones.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.integration.test_threat_sweep_routes import _add_manual, _post
from tests.unit.test_elset_freshness import _tle


@pytest.fixture
def red_state(auth_cookie: str) -> Iterator[Any]:
    from tests.integration.conftest import session_state

    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), list(state.manual_sweep_tles), state.last_threat_assessment)
    state.manual_sweep_tles = []
    yield state
    state.red_tracks, state.manual_sweep_tles, state.last_threat_assessment = saved


def _card(client: Any, cookie: str, name: str) -> str:
    resp = client.get(f"/plan/threat/red-orbit-info?red_sat={name}", cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return " ".join(resp.text.split())


class TestTheRedCard:
    def test_an_old_set_is_aged_and_flagged(self, client: Any, auth_cookie: str, red_state: Any) -> None:
        from spectre.domain.models import RedTrack

        red_state.red_tracks = [RedTrack(name="OLD", tle=_tle(datetime.now(tz=UTC) - timedelta(days=13)))]
        card = _card(client, auth_cookie, "OLD")
        assert "13.0 d old STALE" in card

    def test_a_fresh_set_is_aged_and_not_flagged(self, client: Any, auth_cookie: str, red_state: Any) -> None:
        from spectre.domain.models import RedTrack

        red_state.red_tracks = [
            RedTrack(name="NEW", tle=_tle(datetime.now(tz=UTC) - timedelta(hours=5)), data_mode="REAL"),
        ]
        card = _card(client, auth_cookie, "NEW")
        assert "5.0 h old" in card
        assert "old STALE" not in card
        assert "REAL" in card, "the card says where the set came from"


class TestTheSweep:
    def test_the_interceptor_and_target_ages_are_stated(self, client: Any, auth_cookie: str, red_state: Any) -> None:
        from spectre.domain.models import RedTrack

        red_state.red_tracks = [
            RedTrack(name="RED-GEO", tle=_tle(datetime.now(tz=UTC) - timedelta(hours=2)), data_mode="REAL"),
        ]
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        assert resp.status_code == 200
        text = " ".join(resp.text.split())
        assert "Element set ages" in text
        assert "2.0 h" in text, "the interceptor's age"
        assert "1 stale" in text and "BLUE-GEO" in text, "the stale target is named"

    def test_ages_are_stated_even_when_nothing_reaches_the_target(
        self, client: Any, auth_cookie: str, red_state: Any,
    ) -> None:
        """charming-dirac 0.6.8 failed the App Store's Test stage at 12:07 UTC on the test above (03b7507).

        Target ages were taken from the targets with a solution, so with none there were none, and a stale target
        set can be why nothing reaches it. A 1 mm/s budget makes "nothing reaches it" hold at any hour.
        """
        from spectre.domain.models import RedTrack

        red_state.red_tracks = [
            RedTrack(name="RED-GEO", tle=_tle(datetime.now(tz=UTC) - timedelta(hours=2)), data_mode="REAL"),
        ]
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none", "max_dv_m_s": "0.001"})
        text = " ".join(resp.text.split())
        assert "No intercept solutions found" in text
        assert "1 stale</span>: BLUE-GEO." in text

    def test_a_target_skipped_for_its_regime_is_not_aged(
        self, client: Any, auth_cookie: str, red_state: Any,
    ) -> None:
        """Only targets actually flown are aged: a LEO set the GEO interceptor never flew against is not one."""
        from spectre.domain.models import RedTrack

        red_state.red_tracks = [
            RedTrack(name="RED-GEO", tle=_tle(datetime.now(tz=UTC) - timedelta(hours=2)), data_mode="REAL"),
        ]
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        _add_manual(client, auth_cookie, "BLUE-LEO", _tle(datetime.now(tz=UTC) - timedelta(days=20), leo=True,
                                                         satno=90003))
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none", "max_dv_m_s": "0.001"})
        text = " ".join(resp.text.split())
        assert "BLUE-LEO: skipped" in text and "(regime mismatch)" in text
        assert "1 stale</span>: BLUE-GEO." in text

    def test_a_set_found_mismatched_after_the_cap_is_not_aged(self) -> None:
        """The cap reads the cache before the last-chance fetch; the runner reads the frozen sets after it. A target
        whose fetched set turns out LEO is skipped by the runner, so it was not flown and is not aged."""
        from spectre.domain.models import ThreatTarget
        from spectre.web.routes.threat import _elset_ages, _FrozenTargets, _SweepBasis

        now = datetime.now(tz=UTC)
        geo = ThreatTarget(target_name="BLUE-GEO", target_satno="90002", target_source="hrr", hrr_rank=1)
        leo = ThreatTarget(target_name="BLUE-LEO", target_satno="90003", target_source="hrr", hrr_rank=1)
        none = ThreatTarget(target_name="NO-SET", target_satno="90004", target_source="hrr", hrr_rank=1)
        basis = _SweepBasis(
            targets=[geo, leo, none], manual_tle_by_name={},
            frozen=_FrozenTargets({"90002": _tle(now - timedelta(days=5), satno=90002),
                                   "90003": _tle(now - timedelta(days=9), leo=True, satno=90003)}),
            red_regime="GEO", max_dv_m_s=500.0, blue_satnos=frozenset(), now=now,
        )
        ages = _elset_ages(_tle(now - timedelta(hours=2)), basis, now)
        assert (ages["count"], ages["stale"]) == (1, ["BLUE-GEO"])
        assert ages["red"].label == "2.0 h"

    def test_a_stale_interceptor_is_flagged(self, client: Any, auth_cookie: str, red_state: Any) -> None:
        from spectre.domain.models import RedTrack

        red_state.red_tracks = [RedTrack(name="RED-GEO", tle=_RED_GEO)]
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        text = " ".join(resp.text.split())
        assert "Element set ages" in text
        assert "Interceptor" in text and "STALE" in text


class TestTheRefreshNote:
    def test_it_is_empty_before_udl_connects(self, client: Any, auth_cookie: str, red_state: Any) -> None:
        red_state.elset_refresh = None
        resp = client.get("/udl/elset-refresh", cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 200
        assert 'id="elset-refresh-note"' in resp.text
        assert "Refreshing" not in resp.text

    def test_it_polls_while_running_and_reports_once_done(
        self, client: Any, auth_cookie: str, red_state: Any,
    ) -> None:
        from spectre.web.planning_state import ElsetRefresh

        started = datetime.now(tz=UTC)
        red_state.elset_refresh = ElsetRefresh(started_at=started)
        running = client.get("/udl/elset-refresh", cookies={"spectre_session": auth_cookie}).text
        assert "Refreshing" in running and 'hx-trigger="load delay:2s"' in running

        red_state.elset_refresh = ElsetRefresh(
            started_at=started, finished_at=started, running=False,
            updated=["red SY-12 02"], current=3, failed=["target 12345"],
        )
        first = client.get("/udl/elset-refresh", cookies={"spectre_session": auth_cookie}).text
        assert "1 updated, 3 already current" in " ".join(first.split())
        assert 'data-init="reread-red-card"' in first, "the first report re-reads the red card"
        assert "hx-get" not in first, "polling stops"
        again = client.get("/udl/elset-refresh", cookies={"spectre_session": auth_cookie}).text
        assert 'data-init="reread-red-card"' not in again, "and it does so once"


class TestProvenanceIsRecorded:
    def _add(self, client: Any, cookie: str, data: dict[str, str]) -> None:
        from tests.conftest import csrf_headers

        resp = client.post("/assets/red", data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
        assert resp.status_code == 200

    def test_a_set_fetched_by_the_tle_panel_keeps_its_udl_mode(
        self, client: Any, auth_cookie: str, red_state: Any,
    ) -> None:
        red_state.red_tracks = []
        self._add(client, auth_cookie, {"name": "FETCHED", "tle": _tle(datetime.now(tz=UTC)), "elset_mode": "real"})
        assert red_state.red_tracks[-1].data_mode == "REAL"

    @pytest.mark.parametrize("claimed", ["", "SYNTHETIC", "made up"])
    def test_anything_else_is_manual(self, client: Any, auth_cookie: str, red_state: Any, claimed: str) -> None:
        red_state.red_tracks = []
        self._add(client, auth_cookie, {"name": "PASTED", "tle": _tle(datetime.now(tz=UTC)), "elset_mode": claimed})
        assert red_state.red_tracks[-1].data_mode == "MANUAL"


class TestConnectStartsTheRefresh:
    def test_a_successful_udl_login_spawns_it(self, client: Any, auth_cookie: str, red_state: Any) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from tests.conftest import csrf_headers

        ok = MagicMock(status_code=200, is_success=True)
        http = AsyncMock()
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        http.get = AsyncMock(return_value=ok)
        spawned: list[str] = []

        def record(coro: Any, _owner: object) -> None:
            spawned.append(coro.__qualname__)
            coro.close()

        with patch("httpx.AsyncClient", return_value=http), patch("spectre.web.routes.udl._spawn", side_effect=record):
            resp = client.post(
                "/udl/login", data={"username": "u", "password": "p"},
                cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
            )
        red_state.udl_username = red_state.udl_password = None
        assert resp.status_code == 200
        assert "refresh_held_elsets" in spawned
        assert 'id="elset-refresh-note" hx-swap-oob="outerHTML"' in resp.text, "the note starts polling"
