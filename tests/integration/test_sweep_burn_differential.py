"""What the burn changed: warning before and after, on the sweep (SPC-006, SPC-007).

The operator's second question, from the handover case: "that burn cut your
warning on asset X from 14 hours to 3". Before is flown from the orbit just
before the burn and after is the sweep's own, against the same targets at the
same moment. Most tests spy on the sweep runner so the figures are set by hand;
the physics test flies the real solvers with no stub.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.astro.pattern_of_life import ParseCounts, analyse_pattern_of_life
from spectre.domain.models import RedTrack, ThreatAssessment, ThreatSweepEntry, ThreatTarget
from spectre.web.routes import pol, threat
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit.test_dv_estimation import _AP0, _E0, _I0, _MA0, _N0, _RA0, _burn, _coast, _Elements, _rec, _tle

_STEP_DAYS = 0.25
_BUDGET = 500.0
# Day 100 of 2026. The dv-estimation base starts at day 300 of 2025, and 80
# days of history then run past day 365, an epoch SGP4 accepts but the
# element-set age reader rightly refuses, which reads as custody lost.
_START_EPOCH = 26100.0


def _base() -> str:
    return _tle(_Elements(_N0, _E0, _I0, _RA0, _AP0, _MA0, _START_EPOCH))


@pytest.fixture(autouse=True)
def _no_live_watch(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The burn watch is tested on its own (test_burn_watch); here it records and does not start."""
    started: list[Any] = []
    monkeypatch.setattr(threat, "start_watch", lambda *a, **_k: started.append(a))
    return started


def _events_history(events: list[tuple[int, float, float | None]], tail_sets: int = 2) -> list[Any]:
    """An object coasting ``n`` element sets, then burning, for each ``(n, d_alt_km, gap_days)``.

    ``gap_days``, when given, is the coast between the last set before the
    burn and the burn itself, so a long gap before a burn can be built.
    """
    recs, tle = [], _base()
    for n_sets, d_alt_km, gap_days in events:
        for k in range(n_sets):
            recs.append(_rec(tle, source="18SDS"))
            last = k == n_sets - 1
            tle = _coast(tle, gap_days if last and gap_days is not None else _STEP_DAYS)
        tle = _burn(tle, d_alt_km=d_alt_km)
    for _ in range(tail_sets):
        recs.append(_rec(tle, source="18SDS"))
        tle = _coast(tle, _STEP_DAYS)
    return recs


_ROUTINE = [(40, 25.0, None)] * 7
_RECENT_RAISE = [*_ROUTINE, (40, 150.0, None)]


def _confirmed(records: list[Any]) -> list[Any]:
    return analyse_pattern_of_life(records, satno=90010, name="RED-LEO", dv_threshold=0.002).manoeuvres


@pytest.fixture
def leo(auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A connected UDL session, a red LEO track and one manual target, restored afterwards."""
    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), list(state.manual_sweep_tles), state.last_threat_assessment,
             state.udl_username, state.udl_password, dict(state.elset_histories))
    state.udl_username, state.udl_password = "operator", "udl-secret"
    state.elset_histories.clear()
    state.last_threat_assessment = None
    yield state
    (state.red_tracks, state.manual_sweep_tles, state.last_threat_assessment,
     state.udl_username, state.udl_password) = saved[:5]
    state.elset_histories.clear()
    state.elset_histories.update(saved[5])


def _arrange(state: Any, monkeypatch: pytest.MonkeyPatch, records: list[Any], *,
             red_tle: str | None = None, now: datetime | None = None) -> datetime:
    """Hold *records* as the red object's UDL history and stand one hour after its newest set."""

    async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return "held", "held", {}, {}, "RED-LEO"

    monkeypatch.setattr(pol, "_fetch_merged_history", merged)
    monkeypatch.setattr(pol, "parse_tle_history_counted", lambda *_a, **_k: (records, ParseCounts()))
    moment = now or records[-1].epoch + timedelta(hours=1)
    monkeypatch.setattr(threat, "_utc_now", lambda: moment)
    state.red_tracks = [RedTrack(name="RED-LEO", tle=red_tle or records[-1].tle)]
    state.manual_sweep_tles = [{"name": "BLUE-LEO", "tle": _target_tle(), "confidence": "HIGH"}]
    return moment


def _target_tle() -> str:
    """A LEO target sharing the red object's starting orbit, 20 degrees further along it."""
    return _tle(_Elements(_N0, _E0, _I0, _RA0, _AP0, (_MA0 + 20.0) % 360.0, _START_EPOCH))


def _spy(monkeypatch: pytest.MonkeyPatch, tof_by_red: dict[str, float]) -> list[dict[str, Any]]:
    """Stand in for the sweep runner: one entry per target, flight time chosen by the red set flown."""
    calls: list[dict[str, Any]] = []

    def run(state: Any, targets: list[ThreatTarget], manual: dict[str, str], red_tle: str, red_regime: str,
            epochs: list[tuple[str, datetime]], max_dv_m_s: float) -> tuple[list[Any], list[str], list[Any]]:
        calls.append({"red_tle": red_tle, "epochs": epochs, "targets": list(targets), "manual": dict(manual),
                      "budget": max_dv_m_s, "state": state})
        tof = tof_by_red.get(red_tle)
        if tof is None:
            return [], [], []
        entries = [ThreatSweepEntry(target=t, burn_epoch=epochs[0][1], burn_location="now", delta_v_m_s=120.0,
                                    tof_hours=tof, dv_prograde=120.0, dv_normal=0.0, dv_radial=0.0,
                                    method="hohmann", regime="LEO") for t in targets]
        return entries, [], []

    monkeypatch.setattr(threat, "_run_target_sweep", run)
    return calls


def _sweep(client: Any, cookie: str) -> str:
    resp = client.post("/plan/threat/sweep", data={"red_sat": "RED-LEO", "tgt_group": "none", "max_dv_m_s": _BUDGET},
                       cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return " ".join(resp.text.split())


class TestTheDifferentialIsOnScreen:
    def test_the_burn_cut_the_warning(self, client: Any, auth_cookie: str, leo: Any,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        """I1."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "What the burn changed" in page
        assert "That burn cut the warning on BLUE-LEO from 14h to 3h." in page
        assert "cut by 11h" in page

    def test_before_is_flown_like_for_like(self, client: Any, auth_cookie: str, leo: Any,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        """I2: same targets, manual map, budget and moment; only the red orbit differs."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        now = _arrange(leo, monkeypatch, records)
        calls = _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        _sweep(client, auth_cookie)
        main, flown = calls[0], calls[1]
        assert flown["red_tle"] == before
        assert flown["epochs"][0][1] == now == main["epochs"][0][1]
        assert flown["targets"] == main["targets"]
        assert flown["manual"] == main["manual"]
        assert flown["budget"] == main["budget"] == _BUDGET

    def test_after_is_the_sweep_itself(self, client: Any, auth_cookie: str, leo: Any,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        """I3: exactly two runs; the after figure is the worst case card's."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(leo, monkeypatch, records)
        calls = _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert len(calls) == 2
        assert calls[0]["red_tle"] == records[-1].tle
        assert page.count("from 14h to 3h") == 1


class TestNoFiguresItCannotStandBehind:
    def test_a_red_set_from_before_the_burn(self, client: Any, auth_cookie: str, leo: Any,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
        """I4."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(leo, monkeypatch, records, red_tle=before)
        calls = _spy(monkeypatch, {before: 14.0})
        page = _sweep(client, auth_cookie)
        assert "from before its burn at" in page
        assert "cut the warning" not in page
        assert len(calls) == 1

    def test_without_udl_it_says_why(self, client: Any, auth_cookie: str, leo: Any,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """I6."""
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        leo.udl_username = leo.udl_password = None
        _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "What the burn changed: cannot say. UDL is not connected" in page
        assert "cut the warning" not in page

    def test_custody_lost_shows_no_figures(self, client: Any, auth_cookie: str, leo: Any,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        """I7."""
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records, now=records[-1].epoch + timedelta(days=4))
        _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "custody is lost, so any figure would rest on an out-of-date orbit" in page
        assert "cut the warning" not in page

    def test_no_burn_in_the_window(self, client: Any, auth_cookie: str, leo: Any,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
        """I8: a burn 10 days old is not diffed."""
        records = _events_history(_RECENT_RAISE, tail_sets=40)
        _arrange(leo, monkeypatch, records)
        calls = _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "No confirmed burn in its element sets from" in page
        assert "There is no burn to compare." in page
        assert "Its last confirmed burn was" in page
        assert len(calls) == 1

    def test_a_before_orbit_too_old_to_fly(self, client: Any, auth_cookie: str, leo: Any,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        """I9: 30 hours between the last set and the burn, against LEO's 24-hour limit."""
        records = _events_history([*_ROUTINE, (40, 150.0, 30 / 24)], tail_sets=1)
        assert _confirmed(records)[-1].tle_before.epoch < records[-1].epoch - timedelta(hours=24)
        _arrange(leo, monkeypatch, records)
        calls = _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "too old to fly to now" in page
        assert len(calls) == 1


class TestEachBurnCarriesItsOwnVerdict:
    def test_two_burns_in_the_window(self, client: Any, auth_cookie: str, leo: Any,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """I10: the 150 km raise reads unlike anything; the small one after it does not."""
        # Six hours apart, so the first burn's pre-burn set is inside LEO's 24 h limit.
        records = _events_history([*_RECENT_RAISE, (1, 25.0, None)])
        burns = _confirmed(records)
        assert len([m for m in burns if (records[-1].epoch - m.burn_window[1]) <= timedelta(hours=23)]) == 2
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {burns[-2].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "Those 2 burns cut the warning on BLUE-LEO" in page
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert section.count("Is this normal?") == 2
        assert "Unlike anything in its last" in section
        assert page.count("Is this normal?") == 2, "the standalone verdict line also rendered"


class TestThePhysics:
    def test_before_is_the_independent_sweep_of_the_pre_burn_orbit(
        self, client: Any, auth_cookie: str, leo: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """I11: no solver stubbed. The before hours match an independent sweep of the pre-burn set."""
        from spectre.domain.warning_change import least_warning_by_target
        from spectre.web.format_units import format_tof_label

        records = _events_history(_RECENT_RAISE)
        before_tle = _confirmed(records)[-1].tle_before.tle
        now = _arrange(leo, monkeypatch, records)
        targets = [ThreatTarget("BLUE-LEO", "", "manual", None)]
        manual = {"BLUE-LEO": _target_tle()}
        entries, _, _ = threat._run_target_sweep(
            threat._FrozenTargets({}), targets, manual, before_tle, "LEO", threat._compute_epochs(before_tle, now), _BUDGET,
        )
        expected = least_warning_by_target(entries, _BUDGET).get("BLUE-LEO")
        assert expected is not None, "the fixture should leave the target in reach before the burn"
        compared: list[Any] = []
        real_compare = threat.compare

        def capture(targets: Any, before: Any, after: Any) -> Any:
            compared.append(before)
            return real_compare(targets, before, after)

        monkeypatch.setattr(threat, "compare", capture)
        page = _sweep(client, auth_cookie)
        assert "What the burn changed" in page
        assert compared and compared[0]["BLUE-LEO"] == pytest.approx(expected, abs=1e-9)
        assert format_tof_label(expected)  # the figure the table would print had it changed


class TestTheOperatorsEarlierSweep:
    def test_no_earlier_sweep_is_needed(self, client: Any, auth_cookie: str, leo: Any,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
        """I12."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "from 14h to 3h" in page
        assert "Last shown before the burn" not in page

    def test_an_earlier_pre_burn_sweep_is_cited_not_used(self, client: Any, auth_cookie: str, leo: Any,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
        """I13: the before figure is flown now, 14h; the 13.8h shown earlier is cited."""
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        before = burn.tle_before.tle
        _arrange(leo, monkeypatch, records)
        target = ThreatTarget("BLUE-LEO", "", "manual", None)
        shown_at = burn.burn_window[0] - timedelta(hours=1)
        leo.last_threat_assessment = ThreatAssessment(
            red_name="RED-LEO", sweep_epoch=shown_at, red_tle=before, target_count=1, elapsed_s=1.0, errors=[],
            entries=[ThreatSweepEntry(target=target, burn_epoch=shown_at, burn_location="now", delta_v_m_s=120.0,
                                      tof_hours=13.8, dv_prograde=120.0, dv_normal=0.0, dv_radial=0.0,
                                      method="hohmann", regime="LEO")],
        )
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "from 14h to 3h" in page
        assert "Last shown before the burn: 13h 48m on BLUE-LEO" in page


    @pytest.mark.parametrize("flown", ["after the burn", "another object"])
    def test_an_earlier_sweep_that_did_not_fly_the_pre_burn_orbit_is_not_cited(
        self, client: Any, auth_cookie: str, leo: Any, monkeypatch: pytest.MonkeyPatch, flown: str,
    ) -> None:
        """I13: only a sweep of this object's orbit from before the burn is cited."""
        from tests.integration.test_all_intercepts_ranking import _RED_GEO

        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        before = burn.tle_before.tle
        _arrange(leo, monkeypatch, records)
        target = ThreatTarget("BLUE-LEO", "", "manual", None)
        red_tle = records[-1].tle if flown == "after the burn" else _RED_GEO
        leo.last_threat_assessment = ThreatAssessment(
            red_name="RED-LEO", sweep_epoch=burn.burn_window[0], red_tle=red_tle, target_count=1, elapsed_s=1.0,
            errors=[], entries=[ThreatSweepEntry(target=target, burn_epoch=burn.burn_window[0], burn_location="now",
                                                 delta_v_m_s=120.0, tof_hours=13.8, dv_prograde=120.0, dv_normal=0.0,
                                                 dv_radial=0.0, method="hohmann", regime="LEO")],
        )
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "from 14h to 3h" in page
        assert "Last shown before the burn" not in page


class TestTheNotsoCue:
    def test_a_newer_manoeuvre_notice_is_named(self, client: Any, auth_cookie: str, leo: Any,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
        """I14: a Verified Maneuver notice after the last confirmed burn is named; a photometric one is not."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        now = _arrange(leo, monkeypatch, records)
        satno = str(int(records[-1].tle.splitlines()[0][2:7]))
        stamp = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        class _Cache:
            def get_for_satno(self, _satno: Any) -> list[dict[str, Any]]:
                return [
                    {"createdAt": stamp, "msgBody": {"Event_Class": "Verified Maneuver / Planned", "SatIds": [satno]}},
                    {"createdAt": stamp, "msgBody": {"Event_Class": "Photometric Change", "SatIds": [satno]}},
                ]

            def last_sync_utc(self) -> str:
                return "2026-11-02T05:00:00Z"

        monkeypatch.setattr("spectre.data.notso_cache.get_notso_cache", lambda: _Cache())
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "reports a Verified Maneuver by RED-LEO" in page
        assert "Photometric Change" not in page


class TestDecideByIsNamedAsMissing:
    @pytest.mark.parametrize("udl", [True, False])
    def test_every_state_says_decide_by_is_not_shown(self, client: Any, auth_cookie: str, leo: Any,
                                                     monkeypatch: pytest.MonkeyPatch, udl: bool) -> None:
        """I15."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(leo, monkeypatch, records)
        if not udl:
            leo.udl_username = leo.udl_password = None
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        assert "Decide-by time is not shown yet" in _sweep(client, auth_cookie)


class TestTheSnapshot:
    """I5: every run of one sweep flies one frozen copy of the targets' element sets."""

    def test_the_basis_holds_a_copy_not_the_live_cache(self) -> None:
        from types import SimpleNamespace

        state = SimpleNamespace(hrr_tle_cache={"1": "set-one"}, hrr_objects=[])
        basis = threat._sweep_basis(state, [ThreatTarget("T", "1", "hrr", 1)], {}, "LEO", _BUDGET,
                                    datetime(2026, 11, 2, tzinfo=UTC))
        state.hrr_tle_cache["1"] = "changed"
        assert basis.frozen.hrr_tle_cache == {"1": "set-one"}

    def test_it_is_taken_after_clustering(self, client: Any, auth_cookie: str, leo: Any,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(leo, monkeypatch, records)
        calls = _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        seen: list[str] = []

        def clustered(state: Any) -> None:
            state.hrr_tle_cache["CLUSTER-MARK"] = "rewritten"
            seen.append("clustered")

        monkeypatch.setattr(threat, "_reduce_tle_clusters", clustered)
        _sweep(client, auth_cookie)
        leo.hrr_tle_cache.pop("CLUSTER-MARK", None)
        assert seen == ["clustered"]
        assert all(isinstance(c["state"], threat._FrozenTargets) for c in calls)
