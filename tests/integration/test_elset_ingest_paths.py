"""Every path an element set enters SPECTRE by runs the one acceptance check (SPC-201, evaluation F-25 and F-34).

Evaluation probe P-14 changed one digit of a UDL element set's inclination, 97.4 to 98.4 degrees, leaving the old
checksum: the set reached BoundElset through quick-add and moved the computed miss from 10.4 to 13.4 km with no flag,
and the background refresh replaced a good held set with it. Here each path is driven with that set, the inverse of
the probe, and with a set whose checksum is good but whose inclination is 597.4 degrees (F-34). On every path the set
is refused, nothing is stored, a set already held is kept, the log names the object and what failed without the
set's text, and the operator is shown a sentence naming the object and what failed.

The UDL paths are driven through httpx's own MockTransport (tests/unit/_udl_stub.py), so the real fetch runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.planning_state import SessionState
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE, _checksum
from tests.unit._udl_stub import UdlStub, reply

_GOOD = PLANE_CHANGE.red_tle
_SATNO = 90002


def _changed(tle: str, column: int, text: str, *, checksum: bool) -> str:
    """Line 2 of *tle* with *text* at *column*, its checksum made good, or left as it was."""
    line1, line2 = tle.splitlines()
    body = line2[:column] + text + line2[column + len(text):68]
    return f"{line1}\n{body}{_checksum(body) if checksum else line2[68]}"


#: P-14's UDL case: one digit of the inclination changed, 97.4 to 98.4 degrees, with the old checksum.
_CORRUPT = _changed(_GOOD, 10, "8", checksum=False)
#: F-34: an inclination of 597.4 degrees, with a good checksum.
_ABSURD = _changed(_GOOD, 8, "5", checksum=True)
_CORRUPT_FAILS = "line 2 fails its checksum"
_ABSURD_FAILS = "the inclination, 597.4 degrees, is outside 0 to 180"


def _record(tle: str, mode: str = "REAL") -> dict[str, str]:
    line1, line2 = tle.splitlines()
    return {"line1": line1, "line2": line2, "dataMode": mode}


def _no_set_text(text: str, tle: str = _CORRUPT) -> None:
    """Neither line of *tle* appears in *text*, nor any run of its fields, nor its epoch as written."""
    for line in tle.splitlines():
        for part in (line, line[8:40], line[:30], line[40:]):
            assert part not in text, "the element set's text reached the log or the page"
    assert tle.splitlines()[0][18:32] not in text, "the element set's epoch columns reached the log"


def _renumbered(tle: str, satno: str) -> str:
    """*tle* for another object: both catalogue numbers changed, both checksums made good."""
    lines = []
    for line in tle.splitlines():
        body = line[:2] + satno + line[7:68]
        lines.append(body + _checksum(body))
    return "\n".join(lines)


#: A sound set for another object, as UDL might answer with in place of the one asked for.
_OTHER = _renumbered(_GOOD, "11111")
_OTHER_FAILS = f"it carries catalogue number 11111, not {_SATNO}, the number asked for"
#: A Unicode digit in place of a 0: '²'.isdigit() is True and int('²') raised out of the checksum.
_UNICODE = _changed(_GOOD, 27, "\N{SUPERSCRIPT TWO}", checksum=False)
_UNICODE_FAILS = "line 2 holds a character that is not plain ASCII"


def _post(client: Any, cookie: str, path: str, data: dict[str, Any]) -> Any:
    return client.post(path, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))


def _get(client: Any, cookie: str, path: str) -> Any:
    return client.get(path, cookies={"spectre_session": cookie})


def _flat(html: str) -> str:
    return " ".join(html.replace("&#39;", "'").split())


_SIDES = {"red": "red_tracks", "blue": "blue_assets"}


@pytest.fixture()
def operator(client: Any, auth_cookie: str) -> Iterator[Any]:
    """The test operator: the client, their cookie and their session, holding UDL credentials, restored after."""
    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_password, list(state.blue_assets), list(state.red_tracks),
             list(state.manual_sweep_tles), dict(state.hrr_tle_cache), list(state.hrr_objects))
    state.udl_username, state.udl_password = "udl-user", "udl-pass"
    yield SimpleNamespace(client=client, cookie=auth_cookie, state=state)
    (state.udl_username, state.udl_password, state.blue_assets, state.red_tracks, state.manual_sweep_tles,
     cache, state.hrr_objects) = saved
    state.hrr_tle_cache.clear()
    state.hrr_tle_cache.update(cache)


# ── The one UDL fetch every UDL path goes through ────────────────────────────

class TestTheUdlFetch:
    def test_the_probe_set_is_refused_and_logged_without_its_text(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.web.elsets import RefusedElset
        from spectre.web.routes.udl import fetch_tle_for_satno

        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        with caplog.at_level(logging.WARNING):
            got = asyncio.run(fetch_tle_for_satno(_SATNO, "u", "p"))
        assert isinstance(got, RefusedElset)
        assert got.sentence("SY-12 (90002)") == (
            f"The element set for SY-12 (90002) was refused: {_CORRUPT_FAILS}. It was not stored."
        )
        logged = caplog.text
        assert "90002" in logged and _CORRUPT_FAILS in logged
        _no_set_text(logged)

    def test_a_good_set_is_returned_as_before(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.routes.udl import fetch_tle_for_satno

        UdlStub(reply([_record(_GOOD, "EXERCISE")])).install(monkeypatch)
        assert asyncio.run(fetch_tle_for_satno(_SATNO, "u", "p")) == (_GOOD, "EXERCISE")

    def test_the_history_fetch_drops_a_refused_set_and_keeps_the_rest(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.web.routes.udl import fetch_tle_history_for_satno

        UdlStub(reply([_record(_GOOD), _record(_CORRUPT), _record(_ABSURD), _record(_OTHER)])).install(monkeypatch)
        with caplog.at_level(logging.WARNING):
            history = asyncio.run(fetch_tle_history_for_satno(_SATNO, "u", "p"))
        assert history == [_GOOD]
        assert history.refusal("SY-12 (90002)") == (
            f"3 element sets in the history for SY-12 (90002) were refused: {_CORRUPT_FAILS}; {_ABSURD_FAILS}; "
            f"{_OTHER_FAILS}. They were left out."
        )
        assert "3 element sets refused" in caplog.text
        _no_set_text(caplog.text)
        _no_set_text(caplog.text, _ABSURD)

    def test_a_history_with_nothing_refused_has_no_refusal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.routes.udl import fetch_tle_history_for_satno

        stub = UdlStub(reply([_record(_GOOD)])).install(monkeypatch)
        assert asyncio.run(fetch_tle_history_for_satno(_SATNO, "u", "p")).refusal("SY-12") is None
        stub.answer = reply(status=500)
        failed = asyncio.run(fetch_tle_history_for_satno(_SATNO, "u", "p"))
        assert failed == [] and failed.refusal("SY-12") is None

    def test_another_objects_set_is_not_the_set_asked_for(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A sound set UDL answers for another number would have replaced the held set (review of SPC-201)."""
        from spectre.web.elsets import RefusedElset
        from spectre.web.routes.udl import fetch_tle_for_satno

        UdlStub(reply([_record(_OTHER)])).install(monkeypatch)
        with caplog.at_level(logging.WARNING):
            got = asyncio.run(fetch_tle_for_satno(_SATNO, "u", "p"))
        assert isinstance(got, RefusedElset)
        assert got.sentence("SY-12 (90002)") == (
            f"The element set for SY-12 (90002) was refused: {_OTHER_FAILS}. It was not stored."
        )
        assert f"The element set for SATNO {_SATNO}, as UDL answered it, was refused: {_OTHER_FAILS}." in caplog.text


# ── The background refresh at UDL connect ───────────────────────────────────

class TestTheRefresh:
    @pytest.mark.parametrize(
        ("bad", "fails"), [(_CORRUPT, _CORRUPT_FAILS), (_ABSURD, _ABSURD_FAILS)], ids=["checksum", "range"],
    )
    def test_a_refused_set_never_replaces_the_held_one(
        self, monkeypatch: pytest.MonkeyPatch, bad: str, fails: str,
    ) -> None:
        """P-14: the refresh replaced a good held set with the corrupted one."""
        from spectre.web.elsets import refresh_held_elsets

        newer = bad.replace(" 26290.50000000", " 26291.00000000", 1)
        newer = f"{newer.splitlines()[0][:68]}{_checksum(newer.splitlines()[0][:68])}\n{newer.splitlines()[1]}"
        UdlStub(reply([_record(newer)])).install(monkeypatch)
        held = SessionState(udl_username="u", udl_password="p")
        held.red_tracks.append(RedTrack(name="HELD_RED", tle=_GOOD, data_mode="REAL"))
        asyncio.run(refresh_held_elsets(held, "u", "p"))
        assert held.red_tracks[0].tle == _GOOD
        assert held.elset_refresh.updated == []
        assert held.elset_refresh.refused == [
            f"The element set for red HELD_RED was refused: {fails}. "
            "It was not stored, and the set already held for that object was kept.",
        ]

    def test_another_objects_set_never_replaces_the_held_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.elsets import refresh_held_elsets

        newer = _renumbered(_GOOD.replace(" 26290.50000000", " 26291.00000000", 1), "11111")
        UdlStub(reply([_record(newer)])).install(monkeypatch)
        held = SessionState(udl_username="u", udl_password="p")
        held.red_tracks.append(RedTrack(name="HELD_RED", tle=_GOOD, data_mode="REAL"))
        asyncio.run(refresh_held_elsets(held, "u", "p"))
        assert held.red_tracks[0].tle == _GOOD
        assert held.elset_refresh.refused == [
            f"The element set for red HELD_RED was refused: {_OTHER_FAILS}. "
            "It was not stored, and the set already held for that object was kept.",
        ]

    def test_the_note_names_each_refusal(self) -> None:
        from datetime import UTC, datetime

        from spectre.web.deps import get_templates
        from spectre.web.planning_state import ElsetRefresh

        refresh = ElsetRefresh(started_at=datetime(2026, 11, 10, tzinfo=UTC), finished_at=datetime(2026, 11, 10,
                               tzinfo=UTC), running=False, refused=["The element set for red X was refused: why."])
        html = get_templates().get_template("partials/elset_refresh_note.html").render(
            {"refresh": refresh, "announce": False},
        )
        assert "1 refused" in html and "The element set for red X was refused: why." in html


# ── The operator's own routes ────────────────────────────────────────────────

class TestQuickAdd:
    @pytest.mark.parametrize("side", _SIDES)
    def test_a_refused_set_is_not_added_and_the_operator_is_told(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch, side: str,
    ) -> None:
        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        before = list(getattr(operator.state, _SIDES[side]))
        resp = _post(operator.client, operator.cookie, f"/assets/{side}/quick-add",
                     {"satno": str(_SATNO), "name": "SY-12"})
        assert resp.status_code == 200
        assert getattr(operator.state, _SIDES[side]) == before
        page = _flat(resp.text)
        assert f"The element set for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored." in page
        _no_set_text(page)

    @pytest.mark.parametrize(("bad", "fails"), [(_UNICODE, _UNICODE_FAILS), (_OTHER, _OTHER_FAILS)],
                             ids=["unicode", "other-object"])
    def test_a_set_the_checksum_cannot_judge_is_refused_not_raised(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch, bad: str, fails: str,
    ) -> None:
        UdlStub(reply([_record(bad)])).install(monkeypatch)
        before = list(operator.state.red_tracks)
        resp = _post(operator.client, operator.cookie, "/assets/red/quick-add", {"satno": str(_SATNO), "name": "SY-12"})
        assert resp.status_code == 200
        assert operator.state.red_tracks == before
        assert f"The element set for SY-12 ({_SATNO}) was refused: {fails}. It was not stored." in _flat(resp.text)

    def test_a_good_set_is_still_added(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply([_record(_GOOD)])).install(monkeypatch)
        _post(operator.client, operator.cookie, "/assets/red/quick-add", {"satno": str(_SATNO), "name": "SY-12 GOOD"})
        assert any(t.name == "SY-12 GOOD" and t.tle == _GOOD for t in operator.state.red_tracks)


class TestTheTleForm:
    def test_a_refused_set_does_not_fill_the_form(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        resp = _get(operator.client, operator.cookie, f"/udl/tle?satno={_SATNO}&name_override=SY-12")
        page = _flat(resp.text)
        assert f"The element set for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored." in page
        _no_set_text(page)

    def test_nothing_of_a_refused_set_reaches_the_log(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The diagnostics logged record['tle1'] and every record's epoch columns, a refused set's included."""
        line1, line2 = _CORRUPT.splitlines()
        record = {"tle1": line1, "tle2": line2, "dataMode": "REAL", "objectName": "SY-12", "epoch": "2026-10-17T12:00"}
        UdlStub(reply([record])).install(monkeypatch)
        with caplog.at_level(logging.DEBUG):
            resp = _get(operator.client, operator.cookie, f"/udl/tle?satno={_SATNO}&name_override=SY-12")
        assert f"was refused: {_CORRUPT_FAILS}" in _flat(resp.text)
        assert "UDL elset record keys" in caplog.text
        assert "record['epoch'] = 2026-10-17T12:00" in caplog.text, "the record's own epoch field is still logged"
        assert "parsed_epoch=2026-10-17T12:00:00+00:00" in caplog.text, "the epoch as read is still logged"
        _no_set_text(caplog.text)

    def test_another_objects_set_does_not_fill_the_form(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply([_record(_OTHER)])).install(monkeypatch)
        resp = _get(operator.client, operator.cookie, f"/udl/tle?satno={_SATNO}&name_override=SY-12")
        assert f"The element set for SY-12 ({_SATNO}) was refused: {_OTHER_FAILS}. It was not stored." in _flat(
            resp.text,
        )


class TestTheManualAdd:
    @pytest.mark.parametrize("side", _SIDES)
    @pytest.mark.parametrize(
        "case", [(_CORRUPT, _CORRUPT_FAILS), (_ABSURD, _ABSURD_FAILS)], ids=["checksum", "range"],
    )
    def test_a_refused_paste_is_not_added(self, operator: Any, side: str, case: tuple[str, str]) -> None:
        bad, fails = case
        before = list(getattr(operator.state, _SIDES[side]))
        resp = _post(operator.client, operator.cookie, f"/assets/{side}", {"name": "PASTED", "tle": bad})
        assert getattr(operator.state, _SIDES[side]) == before
        assert f"The element set for PASTED was refused: {fails}. It was not stored." in _flat(resp.text)

    def test_a_unicode_digit_is_refused_not_raised(self, operator: Any) -> None:
        before = list(operator.state.red_tracks)
        resp = _post(operator.client, operator.cookie, "/assets/red", {"name": "PASTED", "tle": _UNICODE})
        assert resp.status_code == 200
        assert operator.state.red_tracks == before
        assert f"The element set for PASTED was refused: {_UNICODE_FAILS}. It was not stored." in _flat(resp.text)


# ── The sweep's own element sets ─────────────────────────────────────────────

class TestTheSweep:
    def test_a_refused_manual_target_is_not_added(self, operator: Any) -> None:
        resp = _post(operator.client, operator.cookie, "/plan/threat/add-manual-tle",
                     {"manual_name": "PASTED TARGET", "manual_tle": _ABSURD, "manual_confidence": "HIGH"})
        assert all(e["name"] != "PASTED TARGET" for e in operator.state.manual_sweep_tles)
        assert f"The element set for PASTED TARGET was refused: {_ABSURD_FAILS}. It was not stored." in _flat(
            resp.text,
        )

    def test_a_refused_manual_red_set_is_not_flown(self) -> None:
        from spectre.web.routes.threat import _validate_manual_red_tle

        errors: list[str] = []
        assert _validate_manual_red_tle(_CORRUPT, errors) is None
        assert errors == [
            f"The element set for the manual red track was refused: {_CORRUPT_FAILS}. It was not stored; the "
            "registered element set is used instead.",
        ]

    def test_a_refused_manual_asset_is_not_screened(self) -> None:
        from spectre.web.routes.threat import _resolve_asset

        resolved = _resolve_asset(SessionState(), "", _ABSURD)
        assert resolved.error == (
            f"The element set for the manual asset was refused: {_ABSURD_FAILS}. It was not stored."
        )

    def test_a_refused_group_prefetch_stores_nothing_and_says_why(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        operator.state.hrr_objects = [{"satno": str(_SATNO), "name": "SY-12", "side": "red", "rank": 1}]
        operator.state.hrr_tle_cache.pop(str(_SATNO), None)
        resp = _post(operator.client, operator.cookie, "/plan/threat/fetch-targets", {"tgt_group": "all"})
        assert str(_SATNO) not in operator.state.hrr_tle_cache
        page = _flat(resp.text)
        assert "0/1 TLEs ready" in page
        assert f"The element set for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored." in page

    def test_a_refused_target_fetch_stores_nothing_and_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.domain.models import ThreatTarget
        from spectre.web.routes.threat import _fetch_missing_target_tles

        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        state = SessionState(udl_username="u", udl_password="p")
        target = ThreatTarget(target_name="SY-12", target_satno=str(_SATNO), target_source="hrr", hrr_rank=1)
        errors: list[str] = []
        asyncio.run(_fetch_missing_target_tles(state, [target], errors))
        assert str(_SATNO) not in state.hrr_tle_cache
        assert errors == [f"The element set for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored."]

    def test_a_refused_actor_fetch_keeps_the_held_set_and_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.domain.models import ThreatActor
        from spectre.web.routes.threat import _refresh_actor_tles

        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        state = SessionState(udl_username="u", udl_password="p")
        state.hrr_tle_cache[str(_SATNO)] = _GOOD
        state.hrr_tle_data_mode[str(_SATNO)] = "SYNTHETIC"
        actor = ThreatActor(actor_name="SY-12", actor_satno=str(_SATNO))
        notes = asyncio.run(_refresh_actor_tles(state, [actor]))
        assert state.hrr_tle_cache[str(_SATNO)] == _GOOD
        assert notes == [
            f"The element set for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored, and the set "
            "already held for that object was kept.",
        ]


    def test_a_refused_history_set_is_shown_in_the_run_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The group pre-fetch also fetches the history for clustering: a set refused there is said, not only logged."""
        from spectre.web.routes.threat import _prefetch_group_tle

        def by_path(request: Any) -> Any:
            history = request.url.path.endswith("/elset")
            return reply([_record(_GOOD)] + ([_record(_CORRUPT), _record(_GOOD)] if history else []))(request)

        UdlStub(by_path).install(monkeypatch)
        state = SessionState(udl_username="u", udl_password="p")
        state.hrr_objects = [{"satno": str(_SATNO), "name": "SY-12", "side": "red", "rank": 1}]
        assert asyncio.run(_prefetch_group_tle(state, str(_SATNO), asyncio.Semaphore(1), 24.0)) is True
        assert state.hrr_tle_multiset[str(_SATNO)] == [_GOOD, _GOOD]
        assert list(state.log_entries) == [
            f"[UDL] 1 element set in the history for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was left out.",
        ]


# ── The HRR watchlist, fetched live ──────────────────────────────────────────

def _notification(*sets: tuple[int, str, str]) -> dict[str, Any]:
    body = []
    for satno, name, tle in sets:
        line1, line2 = tle.splitlines()
        body.append({"satNo": satno, "commonName": name, "country": "RUS", "rank": 1, "line1": line1, "line2": line2})
    return {"createdAt": "2026-11-10T00:00:00Z", "msgBody": body}


class TestTheHrrList:
    def test_a_refused_set_is_not_carried_and_the_operator_is_told(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The live HRR fetch stored each entry's set in session state with no check (review of SPC-201)."""
        good = _renumbered(_GOOD, "90003")
        UdlStub(reply([_notification((_SATNO, "BAD", _CORRUPT), (90003, "GOOD", good))])).install(monkeypatch)
        operator.state.log_entries.clear()
        with caplog.at_level(logging.INFO):
            resp = _get(operator.client, operator.cookie, "/udl/hrr")
        assert resp.status_code == 200
        held = {o["satno"]: o for o in operator.state.hrr_objects}
        assert "tle" not in held[str(_SATNO)] and held["90003"]["tle"] == good
        sentence = f"The element set for BAD ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored."
        assert f"[HRR] {sentence}" in operator.state.log_entries
        _no_set_text(caplog.text)


# ── Bundled data, training objects and the binder ────────────────────────────

class TestBundledAndTrainingSets:
    def test_every_bundled_set_passes(self) -> None:
        import spectre
        from spectre.astro.elset_check import check_elset
        from spectre.web.routes.udl import parse_hrr_notification

        bundled = Path(spectre.__file__).parent / "data" / "hrr_default.json"
        notifications = json.loads(bundled.read_text(encoding="utf-8"))
        refused = {
            o["satno"]: check_elset(o["tle"]).failures
            for n in notifications for o in sum(parse_hrr_notification(n), []) if o.get("tle")
            if not check_elset(o["tle"]).accepted
        }
        assert refused == {}, f"bundled element sets refused: {refused}"

    def test_a_refused_bundled_set_is_not_preloaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.web import app as app_module
        from spectre.web.models import SessionKey
        from spectre.web.planning_state import (
            get_default_hrr_objects,
            get_default_hrr_tles,
            get_session_state,
            set_default_hrr_tles,
        )

        line1, line2 = _CORRUPT.splitlines()
        good1, good2 = _GOOD.splitlines()
        notification = {"createdAt": "2026-11-10T00:00:00Z", "msgBody": [
            {"satNo": _SATNO, "commonName": "BAD", "country": "RUS", "rank": 1, "line1": line1, "line2": line2},
            {"satNo": 90003, "commonName": "GOOD", "country": "RUS", "rank": 1, "line1": good1, "line2": good2},
        ]}
        path = tmp_path / "hrr_default.json"
        path.write_text(json.dumps([notification]), encoding="utf-8")
        saved, saved_objects = get_default_hrr_tles(), get_default_hrr_objects()
        monkeypatch.setattr(app_module, "_hrr_candidate_paths", lambda: [path])
        try:
            with caplog.at_level(logging.WARNING):
                app_module._load_hrr_from_disk()
            tles, _modes = get_default_hrr_tles()
            assert str(_SATNO) not in tles
            sentence = f"The element set for BAD ({_SATNO}) was refused: {_CORRUPT_FAILS}. It was not stored."
            assert sentence in caplog.text
            _no_set_text(caplog.text)
            assert all("tle" not in o for o in get_default_hrr_objects() if o["satno"] == str(_SATNO))
            # No operator is signed in at start-up: each new session's run log shows it.
            fresh = get_session_state(SessionKey(user_id=987_655, session_id="elset-bundled"))
            assert f"[HRR] {sentence}" in fresh.log_entries
        finally:
            from spectre.web.planning_state import set_default_elset_refusals, set_default_hrr_objects

            set_default_hrr_tles(*saved)
            set_default_hrr_objects(saved_objects)
            set_default_elset_refusals([])

    def test_a_refused_training_set_is_not_loaded(self, caplog: pytest.LogCaptureFixture) -> None:
        from spectre.training.scenarios import ScenarioObject
        from spectre.web.models import SessionKey
        from spectre.web.planning_state import get_session_state
        from spectre.web.routes.training import _preload_training_objects

        line1, line2 = _ABSURD.splitlines()
        bad = ScenarioObject(satno=_SATNO, name="TRAINING RED", side="red", regime="LEO", tle_line1=line1,
                             tle_line2=line2)
        owner = SessionKey(user_id=987_654, session_id="elset-check")
        with caplog.at_level(logging.WARNING):
            _preload_training_objects(SimpleNamespace(objects=[bad]), owner)  # type: ignore[arg-type]
        assert get_session_state(owner).red_tracks == []
        sentence = f"The element set for TRAINING RED was refused: {_ABSURD_FAILS}. It was not stored."
        assert sentence in caplog.text
        assert f"[TRAINING] {sentence}" in get_session_state(owner).log_entries


class TestTheBinder:
    def test_a_held_set_the_check_refuses_is_never_bound(self) -> None:
        from spectre.web.decision_binding import bind_scenario

        state = SessionState()
        state.red_tracks.append(RedTrack(name="HELD_RED", tle=_CORRUPT, data_mode="REAL"))
        state.blue_assets.append(BlueAsset(name="HELD_BLUE", tle=PLANE_CHANGE.blue_tle, data_mode="REAL"))
        bound = bind_scenario(state, state.red_tracks[0].stk_name, state.blue_assets[0].stk_name, EPOCH)
        assert bound.binding is None
        assert bound.problem == (
            f"The element set for red track HELD_RED was refused: {_CORRUPT_FAILS}. Nothing was bound; add a "
            "sound element set for it."
        )


# ── The element-set history Pattern of Life, the sweep and custody read ──────

def _pol_history() -> tuple[str, str]:
    """A coasting LEO history (the Pattern of Life fixture) and its 6th set with one digit changed, the old checksum
    kept, as P-14 changed the inclination."""
    from tests.unit.test_dv_estimation import TestTwoTierReporting

    sets = [r.tle for r in TestTwoTierReporting._catalogue(n=40, burn_at=())]
    sound = sets[5]
    line1, line2 = sound.splitlines()
    assert line2[8:16] == " 53.0000"
    corrupt = f"{line1}\n{line2[:9]}4{line2[10:]}"
    return "\n".join(sets), corrupt


class TestThePatternOfLifeHistory:
    """The history behind custody, the burn-normality verdict, the sweep and the PoL panel was parsed with no check:
    a corrupted set became a phantom plane change (review of SPC-201)."""

    def test_the_parser_refuses_the_set_and_keeps_the_sound_one_at_its_epoch(self) -> None:
        from spectre.astro.pattern_of_life import parse_tle_history_counted

        history, corrupt = _pol_history()
        records, counts = parse_tle_history_counted(f"{corrupt}\n{history}", satno=62902)
        assert len(records) == 40, "the sound set at the corrupted one's epoch was dropped as a duplicate"
        assert {round(r.inc_deg, 4) for r in records} == {53.0}
        assert (counts.refused, counts.refusals, counts.duplicate_epoch) == (1, (_CORRUPT_FAILS,), 0)

    def test_the_panel_says_what_was_refused(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.web.routes import pol

        history, corrupt = _pol_history()

        async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
            text = f"{corrupt}\n{history}"
            return text, text, {}, {}, "SIM"

        monkeypatch.setattr(pol, "_fetch_merged_history", merged)
        state = session_state(auth_cookie)
        saved = (state.udl_username, state.udl_password, getattr(state, "last_pol_analysis", None))
        state.udl_username, state.udl_password = "u", "p"
        try:
            page = _flat(_post(client, auth_cookie, "/pol/analyse", {"satno": "62902", "pol_source": "udl"}).text)
            sentence = f"1 element set in the history for SIM (62902) was refused: {_CORRUPT_FAILS}. It was left out."
            assert sentence in page
            assert f"[POL] {sentence}" in state.log_entries
            assert state.last_pol_analysis.tle_count == 40  # type: ignore[attr-defined]
        finally:
            state.udl_username, state.udl_password, state.last_pol_analysis = saved  # type: ignore[attr-defined]

    def test_the_held_history_custody_reads_leaves_it_out_and_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import UTC, datetime

        from spectre.web.routes import pol

        history, corrupt = _pol_history()

        async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
            text = f"{history}\n{corrupt}"
            return text, text, {}, {}, "SY-RED"

        monkeypatch.setattr(pol, "_fetch_merged_history", merged)
        state = SessionState(udl_username="u", udl_password="p")
        held = asyncio.run(pol.held_history(state, 62902, datetime(2026, 11, 10, tzinfo=UTC)))
        assert held.pol is not None and held.pol.refused_element_sets == 1
        assert {round(r.inc_deg, 4) for r in held.pol.records} == {53.0}
        assert list(state.log_entries) == [
            f"[POL] 1 element set in the history for SY-RED (62902) was refused: {_CORRUPT_FAILS}. It was left out.",
        ]


# ── The burn watch and the intercept engine's re-fetch ───────────────────────

class TestTheOtherUdlCallers:
    def test_the_burn_watch_never_reads_the_epoch_of_a_refused_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import UTC, datetime

        from spectre.web import burn_watch
        from spectre.web.burn_watch import BurnWatch

        UdlStub(reply([_record(_CORRUPT)])).install(monkeypatch)
        state = SessionState(udl_username="u", udl_password="p")
        now = datetime(2026, 11, 10, tzinfo=UTC)
        watch = BurnWatch(red_name="SY-12", red_satno=_SATNO, red_regime="LEO", targets=[], manual_tle_by_name={},
                          max_dv_m_s=100.0, accounted_until=None, started_at=now, next_check_at=now)
        with pytest.raises(burn_watch._StatedError) as raised:
            asyncio.run(burn_watch._probe(state, watch))
        assert str(raised.value) == (
            f"The element set for SY-12 ({_SATNO}) was refused: {_CORRUPT_FAILS}. Its epoch was not read, so this "
            "check could not say whether a newer set has arrived."
        )

    def test_the_intercept_refetch_keeps_the_held_set_and_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.routes.maneuver import _resolve_provenance

        def by_number(request: Any) -> Any:
            """The red set corrupted, the blue set sound, each answered for its own number."""
            asked = request.url.params["satNo"]
            return reply([_record(_CORRUPT if asked == str(_SATNO) else PLANE_CHANGE.blue_tle, "EXERCISE")])(request)

        UdlStub(by_number).install(monkeypatch)
        state = SessionState(udl_username="u", udl_password="p")
        red, blue, label = asyncio.run(_resolve_provenance(_GOOD, PLANE_CHANGE.blue_tle, "EXERCISE", state))
        assert (red, blue) == (_GOOD, PLANE_CHANGE.blue_tle)
        assert label == (
            f"red UNVERIFIED, blue EXERCISE. The element set for SATNO {_SATNO} was refused: {_CORRUPT_FAILS}. It "
            "was not stored, and the set already held for that object was kept."
        )
