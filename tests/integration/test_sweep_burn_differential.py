"""What the burn changed: warning before and after, on the sweep (SPC-006, SPC-007).

The operator's second question, from the handover case: "that burn cut your
warning on asset X from 14 hours to 3". Before is flown from the orbit just
before the burn and after is the sweep's own, against the same targets at the
same moment. Most tests spy on the sweep runner so the figures are set by hand;
the physics test flies the real solvers with no stub.
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.astro.pattern_of_life import ParseCounts, analyse_pattern_of_life
from spectre.domain.models import BlueAsset, RedTrack, ThreatAssessment, ThreatSweepEntry, ThreatTarget
from spectre.web.burn_watch import CHECK_EVERY
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

    def run(  # noqa: PLR0913, PLR0917 - mirrors _run_target_sweep's signature, which it stands in for
        state: Any, targets: list[ThreatTarget], manual: dict[str, str], red_tle: str, red_regime: str,
        epochs: list[tuple[str, datetime]], max_dv_m_s: float,
    ) -> tuple[list[Any], list[str], list[Any]]:
        calls.append({"red_tle": red_tle, "epochs": epochs, "targets": list(targets), "manual": dict(manual),
                      "budget": max_dv_m_s, "state": state})
        tof = tof_by_red.get(red_tle)
        if tof is None:
            return [], [], []
        # Like the runner, a target with no element set is skipped, not flown.
        flown = [t for t in targets
                 if (manual.get(t.target_name) if t.target_source == "manual" else state.hrr_tle_cache.get(t.target_satno))]
        entries = [ThreatSweepEntry(target=t, burn_epoch=epochs[0][1], burn_location="now", delta_v_m_s=120.0,
                                    tof_hours=tof, dv_prograde=120.0, dv_normal=0.0, dv_radial=0.0,
                                    method="hohmann", regime="LEO") for t in flown]
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


class TestTheSweepTellsTheWatchWhatItShowed:
    """The route hands the watch the set it flew, so a burn it has just shown is not announced again at once."""

    def test_a_burn_shown_with_custody_held_is_accounted_for(self, client: Any, auth_cookie: str, leo: Any,
                                                             monkeypatch: pytest.MonkeyPatch,
                                                             _no_live_watch: list[Any]) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        assert "That burn cut the warning on BLUE-LEO from 14h to 3h." in _sweep(client, auth_cookie)
        (_, _, watch), = _no_live_watch
        assert watch.accounted_until == burn.tle_after.epoch
        assert watch.newest_epoch == records[-1].epoch
        assert watch.next_check_at == now + CHECK_EVERY


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


def _notice(event_class: str, *, created: datetime, event: datetime | None = None,
            legacy: bool = False) -> dict[str, Any]:
    """A cached NOTSO about the red object; *event* is the time its description gives, if any."""
    stamp = created.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if legacy:
        return {"createdAt": stamp, "msgType": event_class, "satNo": 62902,
                "msgText": f"MSGID: X\nSATNO: 62902\nTYPE: {event_class}"}
    body: dict[str, Any] = {"Event_Class": event_class, "SatIds": ["62902"]}
    if event is not None:
        body["Event_Description"] = f"Jday {event.timetuple().tm_yday:03d} {event:%H%M}z\nProviders report it."
    return {"createdAt": stamp, "msgBody": body}


def _notsos(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]) -> None:
    """Hold *records* as the NOTSO cache the operator last synced; nothing is fetched."""

    class _Cache:
        def get_for_satno(self, _satno: Any) -> list[dict[str, Any]]:
            return records

        def last_sync_utc(self) -> str:
            return "2026-11-02T05:00:00Z"

    monkeypatch.setattr("spectre.data.notso_cache.get_notso_cache", _Cache)


class TestTheNotsoCue:
    def test_a_newer_manoeuvre_notice_is_named(self, client: Any, auth_cookie: str, leo: Any,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
        """I14: a Verified Maneuver notice after the last confirmed burn is named; a photometric one is not."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        now = _arrange(leo, monkeypatch, records)
        event = now - timedelta(minutes=10)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event),
                              _notice("Photometric Change", created=event, event=event)])
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "reports a Verified Maneuver by RED-LEO" in page
        assert "Photometric Change" not in page


class TestDecideBy:
    """SPC-008: the soonest credible arrival minus the operator's response time."""

    @staticmethod
    def _sweep_with(client: Any, cookie: str, response: str) -> str:
        resp = client.post("/plan/threat/sweep",
                           data={"red_sat": "RED-LEO", "tgt_group": "none", "max_dv_m_s": _BUDGET,
                                 "response_time_h": response},
                           cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
        assert resp.status_code == 200
        return " ".join(resp.text.split())

    def test_the_default_is_named_as_the_default(self, client: Any, auth_cookie: str, leo: Any,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        leo.response_time_h = None
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        # Arrival 3 h after the burn at now, inside the 12 h default.
        assert "Decide-by has passed for BLUE-LEO" in page
        assert "the default response time of 12 h, which you have not set" in page

    def test_the_operator_sets_their_own(self, client: Any, auth_cookie: str, leo: Any,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        now = _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._sweep_with(client, auth_cookie, "1")
        decide = now + timedelta(hours=2)
        assert f"Decide by {decide:%H:%M} UTC on {decide.day} {decide:%b} for BLUE-LEO" in page
        assert "your response time of 1 h" in page
        assert leo.response_time_h == 1.0
        assert "your response time of 1 h" in _sweep(client, auth_cookie), "a blank field kept the time set"
        leo.response_time_h = None

    def test_a_bad_response_time_is_refused_and_the_set_one_kept(self, client: Any, auth_cookie: str, leo: Any,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        leo.response_time_h = 6.0
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._sweep_with(client, auth_cookie, "500")
        assert "Response time must be more than 0 and at most 168 hours." in page
        assert leo.response_time_h == 6.0
        leo.response_time_h = None

    @staticmethod
    def _sweep_for(client: Any, cookie: str, name: str, hours: str) -> str:
        resp = client.post("/plan/threat/sweep",
                           data={"red_sat": "RED-LEO", "tgt_group": "none", "max_dv_m_s": _BUDGET,
                                 "target_response_name": name, "target_response_h": hours},
                           cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
        assert resp.status_code == 200
        return html.unescape(" ".join(resp.text.split()))

    def test_a_target_takes_its_own_response_time(self, client: Any, auth_cookie: str, leo: Any,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        """SPC-022: set for BLUE-LEO, it is used for BLUE-LEO and said to be its own, and a blank keeps it."""
        records = _events_history(_RECENT_RAISE)
        now = _arrange(leo, monkeypatch, records)
        monkeypatch.setattr(leo, "response_time_h", 8.0)
        monkeypatch.setattr(leo, "response_time_by_target", {})
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._sweep_for(client, auth_cookie, " BLUE-LEO ", "1")
        decide = now + timedelta(hours=2)
        assert f"Decide by {decide:%H:%M} UTC on {decide.day} {decide:%b} for BLUE-LEO" in page
        assert "your response time for BLUE-LEO of 1 h" in page
        assert leo.response_time_by_target == {"BLUE-LEO": 1.0}
        assert leo.response_time_h == 8.0, "the sign-in's time stays the default for other targets"
        assert "your response time for BLUE-LEO of 1 h" in self._sweep_for(client, auth_cookie, "BLUE-LEO", "")

    @pytest.mark.parametrize("case", [
        ("BLUE-LEO", "0", "Response time must be more than 0 and at most 168 hours. The response time for BLUE-LEO "
                          "is unchanged."),
        ("BLUE-LEO", "soon", "Response time must be a number of hours; got 'soon'. The response time for BLUE-LEO "
                             "is unchanged."),
        ("", "3", "A response time for one target needs the target's name; it was not set."),
        ("B" * 81, "3", "A target's name for a response time must be at most 80 characters; it was not set."),
    ])
    def test_a_bad_per_target_time_is_refused_with_a_reason(self, client: Any, auth_cookie: str, leo: Any,
                                                            monkeypatch: pytest.MonkeyPatch,
                                                            case: tuple[str, str, str]) -> None:
        """Checked as the sign-in's time is; nothing held changes, and the time already held is still used."""
        name, hours, said = case
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        monkeypatch.setattr(leo, "response_time_by_target", {"BLUE-LEO": 6.0})
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._sweep_for(client, auth_cookie, name, hours)
        assert said in page
        assert leo.response_time_by_target == {"BLUE-LEO": 6.0}
        assert "your response time for BLUE-LEO of 6 h" in page

    def test_a_name_no_target_in_the_sweep_has_is_said(self, client: Any, auth_cookie: str, leo: Any,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        """A mistyped name would otherwise be held and never used, without a word."""
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        monkeypatch.setattr(leo, "response_time_by_target", {})
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._sweep_for(client, auth_cookie, "BLUE-9", "2")
        assert ("The response time for BLUE-9 is held, but no target in this sweep is called BLUE-9, so decide-by "
                "did not use it.") in page

    @pytest.mark.parametrize("case", [("BLUE-2", "2"), ("BLUE-LEO", "2"), ("", "")])
    def test_a_matched_or_absent_name_is_not_called_unmatched(self, client: Any, auth_cookie: str, leo: Any,
                                                              monkeypatch: pytest.MonkeyPatch,
                                                              case: tuple[str, str]) -> None:
        """Against two targets, a name either of them has is used, and no name at all is not a mistyped one.

        The sign-in's time is 1 h, so the named target's 2 h is the earlier decide-at and the one named.
        """
        name, hours = case
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        leo.manual_sweep_tles.append({"name": "BLUE-2", "tle": _target_tle(), "confidence": "HIGH"})
        monkeypatch.setattr(leo, "response_time_h", 1.0)
        monkeypatch.setattr(leo, "response_time_by_target", {})
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._sweep_for(client, auth_cookie, name, hours)
        assert "Decide by" in page or "Decide-by has passed" in page
        assert "no target in this sweep is called" not in page
        assert (f"your response time for {name} of 2 h" in page) is bool(name)

    def test_custody_lost_withholds_it(self, client: Any, auth_cookie: str, leo: Any,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records, now=records[-1].epoch + timedelta(days=4))
        _spy(monkeypatch, {records[-1].tle: 3.0})
        assert "No decide-by: custody is lost" in _sweep(client, auth_cookie)

    def test_nothing_in_reach(self, client: Any, auth_cookie: str, leo: Any,
                              monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {})
        assert "No decide-by: no target is in reach within 500 m/s." in _sweep(client, auth_cookie)


class TestTheSnapshot:
    """I5: every run of one sweep flies one frozen copy of the targets' element sets."""

    def test_the_basis_holds_a_copy_not_the_live_cache(self) -> None:
        from types import SimpleNamespace

        state = SimpleNamespace(hrr_tle_cache={"1": "set-one"}, hrr_objects=[])
        basis = threat._sweep_basis(state, [ThreatTarget("T", "1", "hrr", 1)], manual={}, red_regime="LEO",
                                    max_dv_m_s=_BUDGET, now=datetime(2026, 11, 2, tzinfo=UTC))
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


class TestTheNotsoCueReadsTheEventTime:
    """V0.9 review 3 and 24: a notice counts as newer by the event time it states, never by when it was written."""

    def test_a_notice_about_the_burn_on_screen_is_not_a_newer_one(self, client: Any, auth_cookie: str, leo: Any,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records)
        assert burn.tle_after.epoch < now - timedelta(minutes=30)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=now - timedelta(minutes=30),
                                      event=burn.burn_epoch)])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "from 14h to 3h" in page
        assert "No element set since shows a confirmed burn yet" not in page

    @pytest.mark.parametrize("legacy", [True, False])
    def test_a_notice_with_no_event_time_is_not_called_newer(self, client: Any, auth_cookie: str, leo: Any,
                                                             monkeypatch: pytest.MonkeyPatch, legacy: bool) -> None:
        """Written after the post-burn set, but about the burn on screen as far as anyone can tell."""
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records)
        created = now - timedelta(minutes=30)
        _notsos(monkeypatch, [_notice("Verified Maneuver", created=created, legacy=legacy)])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "No element set since shows a confirmed burn yet" not in page
        assert (f"NOTSO created at {threat._when(created)} reports a Verified Maneuver by RED-LEO "
                "but gives no event time") in page

    def test_a_notice_from_before_the_confirmed_burn_is_not_named(self, client: Any, auth_cookie: str, leo: Any,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        _arrange(leo, monkeypatch, records)
        earlier = burn.tle_after.epoch - timedelta(hours=2)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=earlier, event=earlier),
                              _notice("Verified Maneuver", created=earlier)])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "from 14h to 3h" in page
        assert "reports a Verified Maneuver" not in page

    def test_a_future_dated_notice_is_not_named(self, client: Any, auth_cookie: str, leo: Any,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records)
        _notsos(monkeypatch, [
            _notice("Verified Maneuver / Planned", created=now - timedelta(minutes=10), event=now + timedelta(hours=1)),
            _notice("Verified Maneuver", created=now + timedelta(hours=1)),
        ])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "from 14h to 3h" in page
        assert "reports a Verified Maneuver" not in page

    def test_the_uk_spelling_counts(self, client: Any, auth_cookie: str, leo: Any,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records)
        event = now - timedelta(minutes=10)
        _notsos(monkeypatch, [_notice("Verified Manoeuvre / Planned", created=event, event=event)])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert f"NOTSO at {threat._when(event)} reports a Verified Manoeuvre by RED-LEO" in page


    def test_a_dated_notice_is_named_before_a_later_undated_one(self, client: Any, auth_cookie: str, leo: Any,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
        """The notice that says when the object moved is the one named, even if an undated one was written later."""
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records)
        event = now - timedelta(minutes=40)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event),
                              _notice("Verified Maneuver", created=now - timedelta(minutes=10))])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert f"NOTSO at {threat._when(event)} reports a Verified Maneuver by RED-LEO" in page
        assert "gives no event time" not in page


class TestNoBurnStillNamesTheNotso:
    def test_a_manoeuvre_notice_is_named_when_no_burn_is_confirmed(self, client: Any, auth_cookie: str, leo: Any,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        """V0.9 review 4: "no burn to compare" never stands alone while a notice says it moved."""
        records = _events_history(_RECENT_RAISE, tail_sets=40)
        now = _arrange(leo, monkeypatch, records)
        event = now - timedelta(hours=2)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event)])
        _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert "There is no burn to compare." in section
        assert f"NOTSO at {threat._when(event)} reports a Verified Maneuver by RED-LEO" in section


    def test_a_notice_about_a_burn_already_confirmed_is_not_named(self, client: Any, auth_cookie: str, leo: Any,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        """A notice about the last confirmed burn, days old, is not a new manoeuvre no element set shows."""
        records = _events_history(_RECENT_RAISE, tail_sets=40)
        burn = _confirmed(records)[-1]
        _arrange(leo, monkeypatch, records)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=burn.tle_after.epoch,
                                      event=burn.burn_epoch)])
        _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert "There is no burn to compare." in section
        assert "reports a Verified Maneuver" not in section


class TestTheSweepsSetIsNewerThanTheHistory:
    """V0.9 review 1 and 10: the red set flown can be newer than the newest held set."""

    def test_no_burn_in_the_history_is_not_no_burn(self, client: Any, auth_cookie: str, leo: Any,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        full = _events_history(_RECENT_RAISE)
        history = full[:-2]
        _arrange(leo, monkeypatch, history, red_tle=full[-1].tle, now=full[-1].epoch + timedelta(hours=1))
        calls = _spy(monkeypatch, {full[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert "There is no burn to compare" not in section
        assert (f"flies its element set of {threat._when(full[-1].epoch)}, newer than the newest in its history "
                f"({threat._when(history[-1].epoch)})") in section
        assert "the change is not computed" in section
        assert len(calls) == 1

    def test_a_burn_found_carries_the_caveat(self, client: Any, auth_cookie: str, leo: Any,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
        full = _events_history([*_RECENT_RAISE, (1, 60.0, None)])
        history = full[:-2]
        before = _confirmed(history)[-1].tle_before.tle
        _arrange(leo, monkeypatch, history, red_tle=full[-1].tle, now=full[-1].epoch + timedelta(hours=1))
        _spy(monkeypatch, {before: 14.0, full[-1].tle: 3.0})
        page = html.unescape(_sweep(client, auth_cookie))
        assert "That burn cut the warning on BLUE-LEO from 14h to 3h." in page
        assert (f"Caveat: the sweep's element set ({threat._when(full[-1].epoch)}) is newer than the newest in its "
                f"history ({threat._when(history[-1].epoch)}); a burn between them would be in the after figures "
                "but not named.") in page


class TestCustodyLostStillSaysWhatUdlHolds:
    def test_a_stale_red_set_with_a_post_burn_set_held(self, client: Any, auth_cookie: str, leo: Any,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        """V0.9 review 13: custody lost, and UDL holds a set from after the burn; say how to get it."""
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        stale = next(r for r in reversed(records) if r.epoch <= records[-1].epoch - timedelta(hours=30))
        _arrange(leo, monkeypatch, records, red_tle=stale.tle)
        _spy(monkeypatch, {stale.tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "custody is lost, so any figure would rest on an out-of-date orbit" in page
        assert (f"UDL holds an element set from after a burn at {threat._when(burn.burn_epoch)}; reconnect to UDL "
                "to refresh held element sets (sets entered by hand are not refreshed), then sweep again.") in page


def _section(page: str) -> str:
    return page.split("What the burn changed", 1)[1].split("</section>", 1)[0]


class TestTheCueStandsBesideARefusal:
    """V0.10 review 1: a refusal to compute never hides a cached notice that says the object moved."""

    def test_a_burn_that_may_be_unseen(self, client: Any, auth_cookie: str, leo: Any,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        full = _events_history(_RECENT_RAISE)
        history = full[:-2]
        now = _arrange(leo, monkeypatch, history, red_tle=full[-1].tle, now=full[-1].epoch + timedelta(hours=1))
        event = now - timedelta(hours=3)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event)])
        _spy(monkeypatch, {full[-1].tle: 3.0})
        section = _section(_sweep(client, auth_cookie))
        assert "cannot be named, so the change is not computed" in section
        assert f"NOTSO at {threat._when(event)} reports a Verified Maneuver by RED-LEO" in section

    def test_custody_lost(self, client: Any, auth_cookie: str, leo: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        stale = next(r for r in reversed(records) if r.epoch <= records[-1].epoch - timedelta(hours=30))
        now = _arrange(leo, monkeypatch, records, red_tle=stale.tle)
        event = now - timedelta(minutes=20)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event)])
        _spy(monkeypatch, {stale.tle: 3.0})
        section = _section(_sweep(client, auth_cookie))
        assert "custody is lost" in section
        assert f"NOTSO at {threat._when(event)} reports a Verified Maneuver by RED-LEO" in section

    def test_a_red_set_from_before_the_burn(self, client: Any, auth_cookie: str, leo: Any,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = _arrange(leo, monkeypatch, records, red_tle=burn.tle_before.tle)
        event = now - timedelta(minutes=10)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event)])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0})
        section = _section(_sweep(client, auth_cookie))
        assert "from before its burn at" in section
        assert f"NOTSO at {threat._when(event)} reports a Verified Maneuver by RED-LEO" in section

    def test_a_notice_about_the_confirmed_burn_is_still_not_named(self, client: Any, auth_cookie: str, leo: Any,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        _arrange(leo, monkeypatch, records, red_tle=burn.tle_before.tle)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=burn.tle_after.epoch,
                                      event=burn.burn_epoch)])
        _spy(monkeypatch, {burn.tle_before.tle: 14.0})
        section = _section(_sweep(client, auth_cookie))
        assert "from before its burn at" in section
        assert "reports a Verified Maneuver" not in section

    def test_without_a_history_nothing_is_claimed_about_element_sets(self, client: Any, auth_cookie: str, leo: Any,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """No history, so "no element set since shows a confirmed burn" would be unearned."""
        records = _events_history(_RECENT_RAISE)
        now = _arrange(leo, monkeypatch, records)
        leo.udl_username, leo.udl_password = None, None
        event = now - timedelta(minutes=10)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event)])
        _spy(monkeypatch, {records[-1].tle: 3.0})
        section = _section(_sweep(client, auth_cookie))
        assert "What the burn changed: cannot say." in section
        assert "No element set since shows a confirmed burn yet" not in section


class TestAnUndatedBurn:
    def test_a_red_set_inside_an_undated_burns_window_is_refused(self, client: Any, auth_cookie: str, leo: Any,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        """V0.9 review 25: the set at the window's start may predate the burn, so it is refused, not diffed."""
        from spectre.astro import pattern_of_life

        records = _events_history(_RECENT_RAISE)
        monkeypatch.setattr(pattern_of_life.Manoeuvre, "burn_epoch", property(lambda self: self.epoch))
        burn = _confirmed(records)[-1]
        assert burn.burn_window == (burn.tle_before.epoch, burn.epoch)
        _arrange(leo, monkeypatch, records, red_tle=burn.tle_before.tle)
        calls = _spy(monkeypatch, {burn.tle_before.tle: 14.0})
        page = _sweep(client, auth_cookie)
        assert (f"from before its burn between {threat._when(burn.burn_window[0])} and "
                f"{threat._when(burn.burn_window[1])}, so its figures") in page
        assert "did not shorten" not in page
        assert "cut the warning" not in page
        assert len(calls) == 1


@pytest.fixture
def hrr(leo: Any) -> Iterator[Any]:
    """The session's HRR objects and their element sets, restored afterwards."""
    saved = (list(leo.hrr_objects), dict(leo.hrr_tle_cache))
    yield leo
    leo.hrr_objects = saved[0]
    leo.hrr_tle_cache.clear()
    leo.hrr_tle_cache.update(saved[1])


def _sweep_group(client: Any, cookie: str, group: str) -> str:
    resp = client.post("/plan/threat/sweep", data={"red_sat": "RED-LEO", "tgt_group": group, "max_dv_m_s": _BUDGET},
                       cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _no_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """UDL answers no element set for any target; nothing reaches the network."""

    async def nothing(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("spectre.web.routes.udl.fetch_tle_for_satno", nothing)


class TestOnlyTheTargetsFlownAreCompared:
    """V0.9 review 8: a target with no element set was never flown, so it is not "out of reach"."""

    def test_an_unflown_target_is_named_not_counted(self, client: Any, auth_cookie: str, hrr: Any,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(hrr, monkeypatch, records)
        hrr.hrr_objects = [{"name": "BLUE-NOSET", "satno": "77777", "country": "GBR", "rank": 1}]
        hrr.hrr_tle_cache.pop("77777", None)
        _no_fetch(monkeypatch)
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep_group(client, auth_cookie, "blue:1")
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert "That burn cut the warning on BLUE-LEO from 14h to 3h." in section
        assert "out of reach before and after" not in section
        assert "Not swept, so its warning change is not computed: BLUE-NOSET (no element set)." in section
        assert "Both against the same 1 target and its same element set," in section

    def test_nothing_flown_is_not_none_in_reach(self, client: Any, auth_cookie: str, hrr: Any,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(hrr, monkeypatch, records)
        hrr.manual_sweep_tles = []
        hrr.hrr_objects = [{"name": "BLUE-NOSET", "satno": "77777", "country": "GBR", "rank": 1}]
        hrr.hrr_tle_cache.pop("77777", None)
        _no_fetch(monkeypatch)
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep_group(client, auth_cookie, "blue:1")
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert "is in reach within" not in section
        assert "did not shorten" not in section
        assert ("What the burn changed is not computed: no target was swept, so no warning was flown before or "
                "after. Not swept: BLUE-NOSET (no element set).") in section

    def test_nothing_flown_still_names_the_notso(self, client: Any, auth_cookie: str, hrr: Any,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        """V0.10 review 1: the not-computed sentence never hides a notice that says the object moved."""
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        now = _arrange(hrr, monkeypatch, records)
        hrr.manual_sweep_tles = []
        hrr.hrr_objects = [{"name": "BLUE-NOSET", "satno": "77777", "country": "GBR", "rank": 1}]
        hrr.hrr_tle_cache.pop("77777", None)
        _no_fetch(monkeypatch)
        event = now - timedelta(minutes=10)
        _notsos(monkeypatch, [_notice("Verified Maneuver / Planned", created=event, event=event)])
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        section = _section(_sweep_group(client, auth_cookie, "blue:1"))
        assert "no target was swept" in section
        assert f"NOTSO at {threat._when(event)} reports a Verified Maneuver by RED-LEO" in section


class TestYourWarning:
    """V0.9 review 14 and 23: "your warning" means a friendly asset, and only that."""

    def test_a_blue_hrr_asset_reads_as_yours(self, client: Any, auth_cookie: str, hrr: Any,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(hrr, monkeypatch, records)
        hrr.hrr_objects = [{"name": "BLUE-1", "satno": "77001", "country": "GBR", "rank": 1},
                           {"name": "RED-2", "satno": "77002", "country": "RUS", "rank": 1}]
        hrr.hrr_tle_cache.update({"77001": _target_tle(), "77002": _target_tle()})
        _no_fetch(monkeypatch)
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep_group(client, auth_cookie, "all")
        section = page.split("What the burn changed", 1)[1].split("</section>", 1)[0]
        assert "cut your warning on BLUE-1 from 14h to 3h" in section
        assert "cut the warning on RED-2 from 14h to 3h" in section
        assert "cut the warning on BLUE-LEO from 14h to 3h" in section

    def test_a_blue_object_with_no_number_makes_nothing_yours(self, client: Any, auth_cookie: str, hrr: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
        from tests.unit.test_dv_estimation import _checksum

        records = _events_history(_RECENT_RAISE)
        before = _confirmed(records)[-1].tle_before.tle
        _arrange(hrr, monkeypatch, records)
        # A pasted set whose number cannot be read (I is not an Alpha-5 letter): its satno is "".
        lines = [line[:2] + "I2902" + line[7:-1] for line in _target_tle().splitlines()]
        unreadable = "\n".join(line + str(_checksum(line)) for line in lines)
        hrr.manual_sweep_tles = [{"name": "PASTED", "tle": unreadable, "confidence": "HIGH"}]
        hrr.hrr_objects = [{"name": "UK-PENDING", "country": "GBR", "rank": 1}]
        _spy(monkeypatch, {before: 14.0, records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        assert "That burn cut the warning on PASTED from 14h to 3h." in page
        assert "your warning" not in page


class TestTheCustodyStatementsAreShown:
    """V0.9 review 26: the unconfirmed-detection note and the long-gap caveat each have a test that needs them."""

    _T0 = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)

    def _burn(self, *, long_gap: bool = False) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(burn_epoch=self._T0, burn_window=(self._T0, self._T0), long_gap=long_gap, gap_days=12.0,
                               tle_after=SimpleNamespace(epoch=self._T0 + timedelta(hours=1)))

    def test_a_newer_unconfirmed_detection_is_named(self) -> None:
        from types import SimpleNamespace

        later = self._T0 + timedelta(hours=3)
        candidate = SimpleNamespace(burn_epoch=later, burn_window=(later, later))
        pol_ = SimpleNamespace(candidate_manoeuvres=[candidate], records=[])
        context = threat._ChangeContext("RED-X", None, None, SimpleNamespace(pol=pol_), None)
        notes = threat._change_notes(context, [self._burn()], None, self._T0 + timedelta(hours=4))
        assert any("An unconfirmed detection at 06:00 UTC on 2 Nov" in n and "is not counted" in n for n in notes)

    @pytest.mark.parametrize(("hours", "said"), [
        (0, "An unconfirmed detection at 06:00 UTC on 2 Nov is newer"),
        (2, "An unconfirmed detection between 06:00 UTC on 2 Nov and 08:00 UTC on 2 Nov is newer"),
    ])
    def test_an_undated_detection_is_named_by_its_bracket(self, hours: int, said: str) -> None:
        """No single time is given for a detection that earned none, as the burn's own line already says."""
        from types import SimpleNamespace

        start = self._T0 + timedelta(hours=3)
        end = start + timedelta(hours=hours)
        candidate = SimpleNamespace(burn_epoch=end, burn_window=(start, end))
        pol_ = SimpleNamespace(candidate_manoeuvres=[candidate], records=[])
        context = threat._ChangeContext("RED-X", None, None, SimpleNamespace(pol=pol_), None)
        notes = threat._change_notes(context, [self._burn()], None, self._T0 + timedelta(hours=6))
        assert any(n.startswith(said) for n in notes), notes

    def test_custody_lost_names_an_undated_burn_by_its_bracket(self) -> None:
        """The custody-lost refusal's "UDL holds a set from after a burn" gives no time the burn did not earn."""
        from types import SimpleNamespace

        start, end = self._T0 - timedelta(hours=4), self._T0
        burn = SimpleNamespace(burn_epoch=end, burn_window=(start, end))
        held_after = threat._held_after([burn], start - timedelta(hours=1))
        assert held_after.startswith(" UDL holds an element set from after a burn between 23:00 UTC on 1 Nov and "
                                     "03:00 UTC on 2 Nov; reconnect")

    def test_a_long_gap_carries_its_caveat(self) -> None:
        line = threat._burn_line(self._burn(long_gap=True), "RED-X", {}, self._T0 + timedelta(hours=4))
        assert "12 days apart" in line.caveat
        assert "may already include other burns" in line.caveat
        assert threat._burn_line(self._burn(), "RED-X", {}, self._T0 + timedelta(hours=4)).caveat == ""


class TestTheSweepsConfidenceReadsItsDataModeAndCustody:
    """SPC-160: the worst case card's confidence is capped by the red set's data mode and the red custody."""

    @staticmethod
    def _post(client: Any, cookie: str, **extra: str) -> str:
        resp = client.post("/plan/threat/sweep",
                           data={"red_sat": "RED-LEO", "tgt_group": "none", "max_dv_m_s": _BUDGET, **extra},
                           cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
        assert resp.status_code == 200
        return html.unescape(" ".join(resp.text.split()))

    def test_a_synthetic_red_set_reads_low(self, client: Any, auth_cookie: str, leo: Any,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        leo.red_tracks[0].data_mode = "SYNTHETIC"
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._post(client, auth_cookie)
        assert "Confidence LOW." in page
        assert "computed from SYNTHETIC element sets: describes the exercise, not the satellite" in page

    def test_custody_lost_reads_low(self, client: Any, auth_cookie: str, leo: Any,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records, now=records[-1].epoch + timedelta(days=4))
        _spy(monkeypatch, {records[-1].tle: 3.0})
        page = self._post(client, auth_cookie)
        assert "Confidence LOW." in page
        assert "custody of the interceptor is lost" in page

    def test_a_hand_entered_track_held_in_custody_names_only_its_entry(self, client: Any, auth_cookie: str,
                                                                       leo: Any,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._post(client, auth_cookie)
        assert "the element set was entered by hand with no stated confidence" in page
        assert "custody of the interceptor" not in page
        assert "custody was not assessed" not in page

    def test_a_manual_override_caps_at_the_operators_stated_confidence(self, client: Any, auth_cookie: str,
                                                                       leo: Any,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._post(client, auth_cookie, manual_red_tle=records[-1].tle, manual_red_confidence="LOW")
        assert "Confidence LOW." in page
        assert "the element set was entered by hand at LOW confidence" in page

    def test_a_red_set_with_no_recorded_mode_is_not_taken_as_live(self, client: Any, auth_cookie: str, leo: Any,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        """Concept 6.2: an unrecorded mode reads UNKNOWN for confidence, not REAL, and caps at MODERATE."""
        records = _events_history(_RECENT_RAISE)
        _arrange(leo, monkeypatch, records)
        leo.red_tracks = []
        monkeypatch.setattr(leo, "blue_assets", [BlueAsset(name="RED-LEO", tle=records[-1].tle)])
        monkeypatch.setattr(leo, "hrr_tle_data_mode", {})
        _spy(monkeypatch, {_confirmed(records)[-1].tle_before.tle: 14.0, records[-1].tle: 3.0})
        page = self._post(client, auth_cookie)
        assert "the element set's data mode is not recorded" in page
        assert "Confidence HIGH." not in page
