"""The threat routes' refusal and fallback branches, as the operator sees them (SPC-010).

threat.py stood at 91.8 per cent with its whole HRR pre-fetch, the target
panel's regime filter, the cluster reduction and several sweep and screen
refusals never run. Each case here pins a sentence or a count an operator
reads, or what the session holds afterwards, so that a refusal turning into
silence, or a fallback turning into a crash, goes red.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.models import RedTrack, ThreatTarget
from spectre.web.routes import threat, udl
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.integration.test_threat_screen_route import _ASSET_TLE, _RED_TLE

# The element sets above are epoch 2026 day 60; the sweep's clock is held near
# it. One read of the wall clock remains: _interceptor_regime propagates the red
# set to datetime.now directly, not through _utc_now, so the target-panel cases
# depend on today's date. They hold for any date because an unperturbed SGP4
# GEO set stays GEO (checked with the clock set to 2027, 2040, 2100 and 2500).
_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

# _BLUE_GEO half a degree further on: what two providers agree on after the cache was filled.
_BLUE_GEO_AGREED = _BLUE_GEO.replace("  11.0000  1.00270000", "  11.5000  1.00270000")

_HELD = (
    "red_tracks", "manual_sweep_tles", "last_threat_assessment", "hrr_objects", "udl_username",
    "udl_password", "udl_data_mode", "udl_tle_source",
)
_DICTS = ("hrr_tle_cache", "hrr_tle_data_mode", "hrr_tle_multiset")


@pytest.fixture
def state(auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The signed-in session with one red GEO track, no UDL session and no manual targets, restored afterwards."""
    monkeypatch.setattr(threat, "_utc_now", lambda: _NOW)
    held = session_state(auth_cookie)
    saved = {name: getattr(held, name) for name in _HELD}
    saved_dicts = {name: dict(getattr(held, name)) for name in _DICTS}
    held.red_tracks = [RedTrack(name="RED-GEO", tle=_RED_GEO)]
    held.manual_sweep_tles = []
    held.udl_username = held.udl_password = None
    yield held
    for name, value in saved.items():
        setattr(held, name, value)
    for name, value in saved_dicts.items():
        getattr(held, name).clear()
        getattr(held, name).update(value)


def _post(client: Any, cookie: str, path: str, data: dict[str, Any]) -> Any:
    return client.post(f"/plan/threat/{path}", data=data, cookies={"spectre_session": cookie},
                       headers=csrf_headers(cookie))


def _get(client: Any, cookie: str, path: str, **params: str) -> Any:
    return client.get(f"/plan/threat/{path}", params=params, cookies={"spectre_session": cookie})


def _flat(resp: Any) -> str:
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _hrr(satno: str, name: str, *, country: str = "GBR", rank: int = 1, regime: str = "GEO") -> dict[str, Any]:
    return {"satno": satno, "name": name, "country": country, "rank": rank, "orbit_regime": regime}


class TestTheRedOrbitCard:
    def test_a_track_not_in_the_session_returns_nothing(self, client: Any, auth_cookie: str, state: Any) -> None:
        assert _get(client, auth_cookie, "red-orbit-info", red_sat="NOT-HELD").text == ""

    def test_an_orbit_that_will_not_read_says_so_and_keeps_the_reason_in_the_log(
        self, client: Any, auth_cookie: str, state: Any, caplog: pytest.LogCaptureFixture,
    ) -> None:
        state.red_tracks = [RedTrack(name="RED-BAD", tle="<b>not a tle</b>")]
        with caplog.at_level(logging.WARNING, logger=threat.logger.name):
            flat = _flat(_get(client, auth_cookie, "red-orbit-info", red_sat="RED-BAD"))
        assert "Orbit info unavailable for this track." in flat
        # The response bypasses Jinja, so the parser's words never reach the markup.
        assert "<b>" not in flat
        assert "at least 2 lines" not in flat
        assert any("red_orbit_info failed for RED-BAD" in r.getMessage() for r in caplog.records)


class TestTheTargetPanelFiltersByTheInterceptorsRegime:
    """The sweep's target dropdown counts only HRR objects the interceptor's orbit can reach."""

    @pytest.fixture(autouse=True)
    def _watchlist(self, state: Any) -> None:
        state.hrr_objects = [
            _hrr("90002", "BLUE-GEO", rank=1), _hrr("25544", "BLUE-LEO", rank=2, regime="LEO"),
            _hrr("41838", "SJ-17", country="CHN", rank=3),
        ]

    def test_a_geo_interceptor_is_offered_only_geo_groups(self, client: Any, auth_cookie: str) -> None:
        flat = _flat(_get(client, auth_cookie, "target-config", red_sat="RED-GEO"))
        assert "targets filtered to match interceptor orbit" in flat
        assert '<option value="blue:1">Rank 1 (1 object)</option>' in flat
        assert '<option value="red:3">Rank 3 (1 object)</option>' in flat
        assert 'value="blue:2"' not in flat, "a LEO object was offered to a GEO interceptor"
        assert "All HRR (2 objects)" in flat

    def test_an_interceptor_whose_regime_is_unknown_is_offered_every_group_unfiltered(
        self, client: Any, auth_cookie: str, state: Any,
    ) -> None:
        # Found by this test: the F-245 wording sat in its own branch, so the
        # panel said "not filtered" and then offered no target group at all.
        state.red_tracks = [RedTrack(name="RED-BAD", tle="not a tle")]
        flat = _flat(_get(client, auth_cookie, "target-config", red_sat="RED-BAD"))
        assert "Regime unknown for RED-BAD: the target list is not filtered by orbit." in flat
        assert "targets filtered to match" not in flat
        for group in ("blue:1", "blue:2", "red:3"):
            assert f'<option value="{group}">' in flat, f"{group} was not offered"
        assert "All HRR (3 objects)" in flat

    def test_a_name_the_session_does_not_hold_is_unfiltered_too(self, client: Any, auth_cookie: str) -> None:
        flat = _flat(_get(client, auth_cookie, "target-config", red_sat="NOT-HELD"))
        assert "Regime unknown for NOT-HELD" in flat
        assert "All HRR (3 objects)" in flat


class TestTheGroupPrefetchRefuses:
    @pytest.mark.parametrize(("group", "said"), [
        ("blue", ""),
        ("blue:one", "Invalid rank: one"),
        ("blue:4", "No HRR objects found for selected group."),
    ])
    def test_a_group_it_cannot_read_or_that_is_empty(
        self, client: Any, auth_cookie: str, state: Any, group: str, said: str,
    ) -> None:
        state.hrr_objects = [_hrr("90002", "BLUE-GEO")]
        resp = _post(client, auth_cookie, "fetch-targets", {"tgt_group": group})
        assert said in resp.text if said else resp.text == ""

    def test_without_a_udl_session_it_says_so_and_fetches_nothing(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def refused(*_a: object, **_k: object) -> None:
            pytest.fail("fetched without a UDL session")

        monkeypatch.setattr(udl, "fetch_tle_for_satno", refused)
        state.hrr_objects = [_hrr("90002", "BLUE-GEO")]
        assert "Not connected to UDL" in _post(client, auth_cookie, "fetch-targets", {"tgt_group": "all"}).text

    def test_a_credential_dropped_mid_fetch_is_a_failure_not_an_empty_password(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def refused(*_a: object, **_k: object) -> None:
            pytest.fail("fetched with no credential")

        monkeypatch.setattr(udl, "fetch_tle_for_satno", refused)
        held = SimpleNamespace(hrr_tle_cache={}, hrr_tle_data_mode={}, udl_username="u", udl_password="")
        assert asyncio.run(threat._prefetch_group_tle(held, "90004", asyncio.Semaphore(1), 24.0)) is False


class TestTheGroupPrefetchCounts:
    """Each object ends the pre-fetch counted once, as ready or as failed."""

    @pytest.fixture
    def calls(self, state: Any, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, dict[str, Any]]]:
        seen: list[tuple[str, int, dict[str, Any]]] = []
        histories = {90004: [_BLUE_GEO, _RED_GEO], 90006: [_BLUE_GEO]}

        async def current(satno: int, _user: str, _password: str, **kwargs: Any) -> tuple[str, str] | None:
            seen.append(("current", satno, kwargs))
            return None if satno == 90005 else (_BLUE_GEO, "TEST")

        async def history(satno: int, _user: str, _password: str, **kwargs: Any) -> list[str]:
            seen.append(("history", satno, kwargs))
            return histories.get(satno, [])

        monkeypatch.setattr(udl, "fetch_tle_for_satno", current)
        monkeypatch.setattr(udl, "fetch_tle_history_for_satno", history)
        state.udl_username, state.udl_password = "u", "p"
        state.udl_data_mode, state.udl_tle_source = "", "18SDS"
        state.hrr_objects = [
            _hrr("90002", "HELD-REAL"), _hrr("90004", "TWO-SOURCES"), _hrr("90005", "NOT-FOUND"),
            _hrr("90006", "ONE-SOURCE"), _hrr("", "NO-NUMBER"), _hrr("90007", "RED-ONE", country="RUS"),
        ]
        state.hrr_tle_cache["90002"] = _BLUE_GEO
        state.hrr_tle_data_mode["90002"] = "REAL"
        for satno in ("90004", "90005", "90006", "90007"):
            state.hrr_tle_cache.pop(satno, None)
        state.hrr_tle_multiset.clear()
        state.hrr_tle_multiset["11111"] = ["stale", "from another group"]
        return seen

    def test_all_objects(self, client: Any, auth_cookie: str, state: Any, calls: list[Any]) -> None:
        flat = _flat(_post(client, auth_cookie, "fetch-targets", {"tgt_group": "all"}))
        # Five numbered objects: the REAL one counts without a call, one fetch fails.
        assert "4/5 TLEs ready" in flat
        assert "1 failed" in flat
        assert state.log_entries[-1].endswith("Pre-fetched all HRR objects: 4/5 TLEs (1 failed)")
        assert {satno for kind, satno, _ in calls if kind == "current"} == {90004, 90005, 90006, 90007}
        assert all(kw["data_mode"] == "REAL" and kw["source"] == "18SDS" for _, _, kw in calls)
        assert state.hrr_tle_data_mode["90004"] == "TEST"
        assert "90005" not in state.hrr_tle_cache
        # Only an object with two or more histories is clustered, and the last group's sets are gone.
        assert set(state.hrr_tle_multiset) == {"90004"}

    def test_one_side_and_rank(self, client: Any, auth_cookie: str, state: Any, calls: list[Any]) -> None:
        flat = _flat(_post(client, auth_cookie, "fetch-targets", {"tgt_group": "red:1"}))
        assert "1/1 TLEs ready" in flat
        assert "failed" not in flat
        assert state.log_entries[-1].endswith("Pre-fetched Red HRR Rank 1: 1/1 TLEs (0 failed)")
        assert [satno for kind, satno, _ in calls if kind == "current"] == [90007]


class TestTheSweepRefuses:
    def test_a_group_with_no_rank_is_named(self, client: Any, auth_cookie: str, state: Any) -> None:
        flat = _flat(_post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "blue"}))
        assert "Invalid target group: blue" in flat
        assert state.last_threat_assessment is None or state.last_threat_assessment.red_name != "RED-GEO"

    def test_a_red_orbit_that_cannot_be_classified_is_not_swept_on_a_guess(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def decayed(_tle: str) -> str:
            raise ValueError("SGP4 error 6: decayed")

        state.last_threat_assessment = None
        state.manual_sweep_tles = [{"name": "BLUE-GEO", "tle": _BLUE_GEO, "confidence": "HIGH"}]
        monkeypatch.setattr(threat, "regime_from_tle", decayed)
        flat = _flat(_post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"}))
        assert "The red TLE could not be propagated to classify its orbit: SGP4 error 6: decayed" in flat
        assert state.last_threat_assessment is None


class TestAnHrrSweep:
    def test_it_clusters_the_multi_source_sets_and_names_the_target_it_could_not_fly(
        self, client: Any, auth_cookie: str, state: Any,
    ) -> None:
        state.hrr_objects = [_hrr("90002", "BLUE-GEO"), _hrr("90003", "NO-SET")]
        state.hrr_tle_cache["90002"] = _BLUE_GEO
        assert state.hrr_tle_cache["90002"] != _BLUE_GEO_AGREED
        state.hrr_tle_data_mode["90002"] = "REAL"
        state.hrr_tle_cache.pop("90003", None)
        state.hrr_tle_multiset.clear()
        # The providers agree on a later set than the one cached, so the cache
        # can only hold it afterwards if the reduction was written back.
        state.hrr_tle_multiset["90002"] = [_BLUE_GEO_AGREED, _BLUE_GEO_AGREED]
        flat = _flat(_post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "blue:1"}))
        assessment = state.last_threat_assessment
        assert {e.target.target_name for e in assessment.entries} == {"BLUE-GEO"}
        assert "No TLE for NO-SET \u2014 skipped" in assessment.errors
        assert "No TLE for NO-SET \u2014 skipped" in flat
        assert "TLE clustering: <strong" in flat
        assert state.hrr_tle_cache["90002"].split("\n")[-1].strip() == _BLUE_GEO_AGREED.split("\n")[-1].strip()

    def test_a_refine_whose_target_set_has_gone_says_so(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.manual_sweep_tles = [{"name": "BLUE-GEO", "tle": _BLUE_GEO, "confidence": "HIGH"}]
        _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        before = list(state.last_threat_assessment.entries)
        state.manual_sweep_tles = []
        assert "TLE not found" in _post(client, auth_cookie, "refine", {"entry_index": 0}).text
        assert state.last_threat_assessment.entries == before


class TestClusterReduction:
    """Clustering is an optimisation, never a gate."""

    def test_nothing_to_cluster_is_no_summary(self) -> None:
        assert threat._reduce_tle_clusters(SimpleNamespace(hrr_tle_multiset={}, hrr_tle_cache={})) is None

    def test_a_failure_leaves_the_cache_as_it_was_and_is_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.astro import tle_preprocessing

        def broken(*_a: object) -> Any:
            raise RuntimeError("DBSCAN fell over")

        monkeypatch.setattr(tle_preprocessing, "cluster_and_reduce_tle_cache", broken)
        held = SimpleNamespace(hrr_tle_multiset={"90002": [_BLUE_GEO, _RED_GEO]}, hrr_tle_cache={"90002": "kept"})
        with caplog.at_level(logging.WARNING, logger=threat.logger.name):
            assert threat._reduce_tle_clusters(held) is None
        assert held.hrr_tle_cache == {"90002": "kept"}
        assert any("DBSCAN fell over" in r.getMessage() for r in caplog.records)


class TestOnePassOverTheTargets:
    """A target the pass cannot fly is named with the reason, never dropped."""

    def test_each_skip_and_assumption_is_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        flown: list[str] = []

        def unreadable(tle: str) -> str:
            if tle == "UNREADABLE":
                raise ValueError("cannot propagate")
            return "LEO" if tle == "LEO-SET" else "GEO"

        def nothing(request: Any, _epochs: Any, refusals: dict[str, str]) -> list[Any]:
            flown.append(request.target.target_name)
            refusals["lambert"] = "no arrival"
            return []

        monkeypatch.setattr(threat, "regime_from_tle", unreadable)
        monkeypatch.setattr(threat, "_sweep_all_methods", nothing)
        held = SimpleNamespace(hrr_tle_cache={"1": "UNREADABLE", "2": "LEO-SET"})
        targets = [
            ThreatTarget("NO-SET", "9", "hrr", 1), ThreatTarget("ODD", "1", "hrr", 1),
            ThreatTarget("LOW", "2", "hrr", 1), ThreatTarget("PASTED", "", "manual", None),
        ]
        entries, errors, refusals = threat._run_target_sweep(
            held, targets, {"PASTED": "GEO-SET"}, "RED", "GEO", [("now", _NOW)], 250.0,
        )
        assert entries == []
        assert flown == ["ODD", "PASTED"]
        assert errors == [
            "No TLE for NO-SET \u2014 skipped",
            "ODD: its TLE could not be propagated to classify its orbit; swept assuming the same regime as red",
            "ODD: all methods/epochs exceeded 250 m/s or solver failed",
            "LOW: skipped \u2014 GEO red vs LEO target (regime mismatch)",
            "PASTED: all methods/epochs exceeded 250 m/s or solver failed",
        ]
        assert refusals == [("ODD", "lambert", "no arrival"), ("PASTED", "lambert", "no arrival")]


def _screen(client: Any, cookie: str, **data: object) -> str:
    return _flat(client.post("/plan/threat/screen", data=data, cookies={"spectre_session": cookie},
                             headers=csrf_headers(cookie)))


class TestTheScreenNamesWhatItLeftOut:
    """Audit F-135's rule for the screen: a shorter list and a safer asset must not look alike."""

    def test_an_actor_with_no_element_set_is_named(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.hrr_objects = [_hrr("41838", "SJ-17", country="CHN")]
        state.hrr_tle_cache.pop("41838", None)
        assert "SJ-17 (41838): no element set" in _screen(client, auth_cookie, manual_asset_tle=_ASSET_TLE)

    def test_an_actor_with_no_method_inside_the_budget_is_named(
        self, client: Any, auth_cookie: str, state: Any,
    ) -> None:
        state.hrr_objects = [_hrr("41838", "SJ-17", country="CHN")]
        state.hrr_tle_cache["41838"] = _RED_TLE
        flat = _screen(client, auth_cookie, manual_asset_tle=_ASSET_TLE, max_dv_m_s=0)
        assert "SJ-17 (41838): no method within 0 m/s" in flat

    def test_a_truncated_candidate_list_says_how_much_was_left_out(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(threat, "_MAX_SCREEN_ACTORS", 1)
        state.hrr_objects = [_hrr("41838", "SJ-17", country="CHN"), _hrr("41839", "SJ-OTHER", country="CHN")]
        state.hrr_tle_cache["41838"] = _RED_TLE
        flat = _screen(client, auth_cookie, manual_asset_tle=_ASSET_TLE, max_dv_m_s=0)
        assert "Candidate list truncated to 1 of 2 (compute cap). Ranking covers the truncated set only." in flat
        assert "SJ-OTHER" not in flat
