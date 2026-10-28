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
from tests.integration.conftest import session_state
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.unit.test_astro import ISS_TLE

_USER = "testadmin"


@pytest.fixture
def sweep_state(auth_cookie: str) -> Iterator[Any]:
    """One red GEO track and an empty manual target list, restored afterwards."""
    from spectre.domain.models import RedTrack

    state = session_state(auth_cookie)
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
        "case",
        [("", _BLUE_GEO, "Target name is required"), ("X", "", "TLE is required"), ("X", "not a tle", "Invalid TLE")],
    )
    def test_bad_input_is_refused_with_a_reason(
        self, client: Any, auth_cookie: str, sweep_state: Any, case: tuple[str, str, str],
    ) -> None:
        name, tle, message = case
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


class TestProvenance:
    """Audit F-039: a sweep from a generated red element set says so."""

    def test_a_synthetic_red_set_is_flagged_in_the_result(
        self, client: Any, auth_cookie: str, sweep_state: Any,
    ) -> None:
        from spectre.domain.models import RedTrack

        # The red set's provenance is the track's own (0.6.3). It used to be
        # read from the target cache by catalogue number, where a hand-entered
        # red set took whatever mode the same object's target set carried.
        sweep_state.red_tracks = [RedTrack(name="RED-GEO", tle=_RED_GEO, data_mode="SYNTHETIC")]
        _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
        resp = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
        flat = " ".join(resp.text.split())
        assert "not from live tracking" in flat
        assert "SYNTHETIC: red RED-GEO" in flat


class TestRefineTellsTheTruth:
    """Audit F-123, F-127 and F-128: the refine route."""

    def _swept(self, client: Any, cookie: str, **extra: str) -> None:
        _add_manual(client, cookie, "BLUE-GEO", _BLUE_GEO)
        _post(client, cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none", **extra})

    def test_a_failed_refine_says_why_and_logs_no_result(
        self, client: Any, auth_cookie: str, sweep_state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.web.routes import threat

        self._swept(client, auth_cookie)
        before = sweep_state.last_threat_assessment.entries[0]

        def _refuse(**_kwargs: Any) -> Any:
            raise ValueError("degenerate Lambert geometry: transfer angle 179.99 deg. Pick another epoch")

        monkeypatch.setattr(threat, "lambert_intercept", _refuse)
        logged = len(sweep_state.log_entries)
        resp = _post(client, auth_cookie, "refine", {"entry_index": 0, "group_idx": 0})
        assert "degenerate Lambert geometry: transfer angle 179.99 deg" in resp.text
        assert sweep_state.last_threat_assessment.entries[0] is before
        added = list(sweep_state.log_entries)[logged:]
        assert not any("Lambert dV" in line for line in added)
        assert any("refused" in line for line in added)

    def test_refine_flies_the_red_orbit_the_sweep_used(
        self, client: Any, auth_cookie: str, sweep_state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.web.routes import threat

        self._swept(client, auth_cookie, manual_red_tle=_BLUE_GEO.replace("BLUE", "RED"))
        swept_red = sweep_state.last_threat_assessment.red_tle
        assert swept_red is not None
        seen: dict[str, Any] = {}
        real = threat.lambert_intercept

        def _spy(**kwargs: Any) -> Any:
            seen.update(kwargs)
            return real(**kwargs)

        monkeypatch.setattr(threat, "lambert_intercept", _spy)
        _post(client, auth_cookie, "refine", {"entry_index": 0, "group_idx": 0})
        assert seen["red_tle"] == swept_red, "the manual red override must survive into the refine"
        assert sweep_state.last_threat_assessment.entries[0].regime == "GEO"

    def test_a_negative_index_is_refused(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        self._swept(client, auth_cookie)
        before = list(sweep_state.last_threat_assessment.entries)
        resp = _post(client, auth_cookie, "refine", {"entry_index": -1, "group_idx": 0})
        assert resp.status_code == 422
        assert sweep_state.last_threat_assessment.entries == before

    def test_a_sweep_replaced_mid_refine_is_left_alone(
        self, client: Any, auth_cookie: str, sweep_state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.domain.models import ThreatAssessment
        from spectre.web.routes import threat

        self._swept(client, auth_cookie)
        replacement = ThreatAssessment(red_name="OTHER", sweep_epoch=sweep_state.last_threat_assessment.sweep_epoch)
        real = threat.lambert_intercept

        def _another_tab_sweeps(**kwargs: Any) -> Any:
            sweep_state.last_threat_assessment = replacement
            return real(**kwargs)

        monkeypatch.setattr(threat, "lambert_intercept", _another_tab_sweeps)
        resp = _post(client, auth_cookie, "refine", {"entry_index": 0, "group_idx": 0})
        assert resp.status_code == 200
        assert replacement.entries == [], "a foreign entry was spliced into the newer sweep"
        assert "newer sweep" in resp.text


class TestManualTargetsAreBounded:
    """Audit F-134: per-user state lives in a process-global dict and outlives the session."""

    def test_an_oversize_name_is_refused(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _add_manual(client, auth_cookie, "N" * 65, _BLUE_GEO)
        assert "64 characters" in resp.text
        assert sweep_state.manual_sweep_tles == []

    def test_an_oversize_tle_is_refused(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _add_manual(client, auth_cookie, "BIG", _BLUE_GEO + "\n" + "x" * 400)
        assert "too long" in resp.text
        assert sweep_state.manual_sweep_tles == []

    def test_an_unknown_confidence_is_refused(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        resp = _post(client, auth_cookie, "add-manual-tle", {
            "manual_name": "X", "manual_tle": _BLUE_GEO, "manual_confidence": "<b>certain</b>",
        })
        assert "Confidence must be one of" in resp.text
        assert sweep_state.manual_sweep_tles == []

    def test_the_list_is_capped(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:
        from spectre.web.routes.threat import _MAX_MANUAL_TARGETS

        sweep_state.manual_sweep_tles = [
            {"name": f"T{i}", "tle": _BLUE_GEO, "confidence": "HIGH"} for i in range(_MAX_MANUAL_TARGETS)
        ]
        resp = _add_manual(client, auth_cookie, "ONE-MORE", _BLUE_GEO)
        assert f"at most {_MAX_MANUAL_TARGETS}" in resp.text
        assert len(sweep_state.manual_sweep_tles) == _MAX_MANUAL_TARGETS
        # Replacing an existing name is not growth.
        _add_manual(client, auth_cookie, "T0", _BLUE_GEO)
        assert len(sweep_state.manual_sweep_tles) == _MAX_MANUAL_TARGETS


def test_intercept_history_is_bounded() -> None:
    """Audit F-134: one entry per apply-intercept call, never cleared until asked."""
    from types import SimpleNamespace

    from spectre.web.routes.maneuver import _MAX_INTERCEPT_HISTORY, _record_intercept

    state = SimpleNamespace(intercept_history=[], last_intercept_result=None)
    for i in range(_MAX_INTERCEPT_HISTORY + 5):
        _record_intercept(state, i)  # type: ignore[arg-type]
    assert len(state.intercept_history) == _MAX_INTERCEPT_HISTORY
    assert state.intercept_history[-1] == _MAX_INTERCEPT_HISTORY + 4
    assert state.intercept_history[0] == 5
    assert state.last_intercept_result == _MAX_INTERCEPT_HISTORY + 4
