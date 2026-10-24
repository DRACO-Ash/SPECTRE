"""The threat sweep routes, driven through the application.

Audit F-042. The sweep, refine, fetch-targets, add-manual-tle and
red-orbit-info routes were never exercised by any test, and
spectre/web/routes/threat.py stood at 48 per cent coverage. These run each
route with a seeded session: real GEO element sets, manual targets, the
regime skip and the error paths.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import csrf_headers
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.unit.test_astro import ISS_TLE

_USER = "testadmin"


@pytest.fixture
def sweep_state() -> Iterator[Any]:
    """One red GEO track and an empty manual target list, restored afterwards."""
    from spectre.domain.models import RedTrack
    from spectre.web.planning_state import get_session_state

    state = get_session_state(_USER)
    saved = (list(state.red_tracks), list(state.manual_sweep_tles), state.last_threat_assessment)
    state.red_tracks = [RedTrack(name="RED-GEO", tle=_RED_GEO)]
    state.manual_sweep_tles = []
    yield state
    state.red_tracks, state.manual_sweep_tles, state.last_threat_assessment = saved


def _post(client: Any, cookie: str, path: str, data: dict[str, Any]) -> Any:
    return client.post(
        f"/plan/threat/{path}", data=data,
        cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )


def _add_manual(client: Any, cookie: str, name: str, tle: str) -> Any:
    return _post(client, cookie, "add-manual-tle", {"manual_name": name, "manual_tle": tle, "manual_confidence": "high"})


class TestManualTargets:
    def test_a_valid_target_is_listed_with_its_confidence(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        assert resp.status_code == 200
        assert sweep_state.manual_sweep_tles == [{"name": "BLUE-GEO", "tle": _BLUE_GEO, "confidence": "HIGH"}]

    @pytest.mark.parametrize(
        ("name", "tle", "message"),
        [("", _BLUE_GEO, "Target name is required"), ("X", "", "TLE is required"), ("X", "not a tle", "Invalid TLE")],
    )
    def test_bad_input_is_refused_with_a_reason(
        self, client: Any, auth_cookie: str, sweep_state: Any, name: str, tle: str, message: str,
    ) -> None:
        resp = _add_manual(client, auth_cookie, name, tle)
        assert message in resp.text
        assert sweep_state.manual_sweep_tles == []

    def test_a_target_can_be_removed(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        _post(client, auth_cookie, "remove-manual-tle", {"manual_name": "BLUE-GEO"})
        assert sweep_state.manual_sweep_tles == []


class TestSweep:
    def test_a_manual_only_sweep_assesses_the_target(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        assert resp.status_code == 200
        assessment = sweep_state.last_threat_assessment
        assert assessment is not None
        assert {e.target.target_name for e in assessment.entries} == {"BLUE-GEO"}
        assert "BLUE-GEO" in resp.text

    def test_a_target_in_an_incompatible_regime_is_not_swept(
        self, client: Any, auth_cookie: str, sweep_state: Any,
    ) -> None:
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        _add_manual(client, auth_cookie, "ISS-LEO", ISS_TLE)
        _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        names = {e.target.target_name for e in sweep_state.last_threat_assessment.entries}
        assert "ISS-LEO" not in names
        assert "BLUE-GEO" in names

    def test_no_targets_is_reported(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        assert "No targets available" in resp.text

    def test_an_unknown_red_satellite_is_reported(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "NOPE", "tgt_group": "none"})
        assert "No TLE found for red satellite" in resp.text

    def test_a_malformed_target_group_is_reported(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "blue:x"})
        assert "Invalid target group rank" in resp.text

    def test_a_bad_manual_red_override_falls_back_with_a_note(
        self, client: Any, auth_cookie: str, sweep_state: Any,
    ) -> None:
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        resp = _post(client, auth_cookie, "sweep", {
            "red_sat": "RED-GEO", "tgt_group": "none", "manual_red_tle": "garbage",
        })
        assert "Manual red TLE invalid" in resp.text
        assert sweep_state.last_threat_assessment is not None


class TestRefine:
    def test_a_swept_entry_refines(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        resp = _post(client, auth_cookie, "refine", {"entry_index": 0, "group_idx": 0})
        assert resp.status_code == 200
        assert "Invalid entry" not in resp.text
        assert "BLUE-GEO" in resp.text

    def test_an_index_past_the_sweep_is_refused(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _post(client, auth_cookie, "refine", {"entry_index": 99, "group_idx": 0})
        assert "Invalid entry" in resp.text


class TestRedOrbitInfo:
    def test_the_card_describes_the_red_orbit(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = client.get(
            "/plan/threat/red-orbit-info", params={"red_sat": "RED-GEO"},
            cookies={"spectre_session": auth_cookie},
        )
        assert resp.status_code == 200
        assert "GEO" in resp.text

    def test_no_selection_returns_nothing(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = client.get("/plan/threat/red-orbit-info", cookies={"spectre_session": auth_cookie})
        assert resp.text == ""


class TestFetchTargets:
    def test_no_group_returns_nothing(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        assert _post(client, auth_cookie, "fetch-targets", {"tgt_group": ""}).text == ""
