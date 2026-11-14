"""Every ingest path refuses an SGP4-XP element set and an uncorrelated track (charming-dirac 7ed9d0b).

The acceptance check (spectre.astro.elset_check) refuses both; these drive the paths through it. A UDL fetch hands
the check the record the set came in, so a type 4 set is refused by its ephemType even where line 1 says 0, and a
UCT by its flag. The history fetch leaves both out and the log says what it skipped, by type and provider, without
the set's text. When the only set a fetch answers with is refused for this, the page says so in a sentence; when an
older set passes, it is taken and the newer one refused is named (SPC-243). The PoL history from UDL leaves both out
as well.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit._decision_reference import PLANE_CHANGE, _checksum
from tests.unit._udl_stub import UdlStub, reply

_GOOD = PLANE_CHANGE.red_tle
_SATNO = 90002
_XP_FAILS = "it is an SGP4-XP set (ephemeris type 4), which SGP4 would propagate to a wrong orbit without an error"
_UCT_FAILS = "it is an uncorrelated track (UCT), not a set correlated to the object"


def _typed(tle: str, column_63: str) -> str:
    line1, line2 = tle.splitlines()
    body = line1[:62] + column_63 + line1[63:68]
    return f"{body}{_checksum(body)}\n{line2}"


#: The same orbit filed as SGP4-XP, by its line 1 alone.
_XP_TEXT = _typed(_GOOD, "4")


def _record(tle: str, **fields: object) -> dict[str, object]:
    line1, line2 = tle.splitlines()
    return {"line1": line1, "line2": line2, "dataMode": "REAL", **fields}


def _no_set_text(text: str) -> None:
    for line in (*_GOOD.splitlines(), *_XP_TEXT.splitlines()):
        for part in (line, line[8:40], line[40:]):
            assert part not in text, "the element set's text reached the log or the page"


def _flat(html: str) -> str:
    return " ".join(html.replace("&#39;", "'").split())


@pytest.fixture()
def operator(client: Any, auth_cookie: str) -> Iterator[Any]:
    """The test operator, holding UDL credentials, their session restored after."""
    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_password, list(state.blue_assets), list(state.red_tracks))
    state.udl_username, state.udl_password = "udl-user", "udl-pass"
    yield SimpleNamespace(client=client, cookie=auth_cookie, state=state)
    state.udl_username, state.udl_password, state.blue_assets, state.red_tracks = saved


class TestTheNewestSet:
    @pytest.mark.parametrize(("record", "fails"), [
        (_record(_GOOD, ephemType=4, source="EXO"), _XP_FAILS),
        (_record(_XP_TEXT, source="EXO"), _XP_FAILS),
        (_record(_GOOD, uct=True, source="EXO"), _UCT_FAILS),
    ], ids=["record-type", "line-1-type", "uct"])
    def test_it_is_refused_and_logged_by_type_without_its_text(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, record: dict[str, object], fails: str,
    ) -> None:
        from spectre.web.elsets import RefusedElset
        from spectre.web.routes.udl import fetch_tle_for_satno

        UdlStub(reply([record])).install(monkeypatch)
        with caplog.at_level(logging.INFO):
            got = asyncio.run(fetch_tle_for_satno(_SATNO, "u", "p"))
        assert isinstance(got, RefusedElset)
        assert got.sentence("SY-12 (90002)") == f"The element set for SY-12 (90002) was refused: {fails}. It was not stored."
        assert "skipped by type" in caplog.text and "from EXO" in caplog.text
        _no_set_text(caplog.text)

    def test_an_older_sgp4_set_is_taken_in_its_place_and_the_refused_one_named(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Until 0.45.0 the refused newest set refused the fetch (SPC-201); the newest set the check accepts is now
        taken, and the newer one refused is named with its provider and why (SPC-243)."""
        from spectre.web.routes.udl import FetchedElset, fetch_tle_for_satno

        line1, line2 = _GOOD.splitlines()
        assert line1[18:32] == "26290.50000000"
        body = f"{line1[:18]}26289.50000000{line1[32:68]}"
        older = f"{body}{_checksum(body)}\n{line2}"
        UdlStub(reply([_record(older, source="PROVIDER-B"), _record(_XP_TEXT, source="PROVIDER-A")])).install(
            monkeypatch,
        )
        got = asyncio.run(fetch_tle_for_satno(_SATNO, "u", "p"))
        assert isinstance(got, FetchedElset)
        assert (got.tle, got.source) == (older, "PROVIDER-B")
        assert got.passed_over_note("SY-12 (90002)") == (
            "A newer element set for SY-12 (90002), from PROVIDER-A with epoch 2026-10-17 12:00:00.000 UTC, was "
            f"refused: {_XP_FAILS}. The set used is PROVIDER-B's, epoch 2026-10-16 12:00:00.000 UTC, 1.0 d older."
        )

    def test_quick_add_says_so_on_the_page(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply([_record(_GOOD, ephemType=4, source="EXO")])).install(monkeypatch)
        before = list(operator.state.red_tracks)
        resp = operator.client.post("/assets/red/quick-add", data={"satno": str(_SATNO), "name": "SY-12"},
                                    cookies={"spectre_session": operator.cookie}, headers=csrf_headers(operator.cookie))
        assert operator.state.red_tracks == before
        page = _flat(resp.text)
        assert f"The element set for SY-12 ({_SATNO}) was refused: {_XP_FAILS}. It was not stored." in page
        _no_set_text(page)

    def test_the_tle_form_is_not_filled(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply([_record(_GOOD, uct=True)])).install(monkeypatch)
        resp = operator.client.get(f"/udl/tle?satno={_SATNO}&name_override=SY-12",
                                   cookies={"spectre_session": operator.cookie})
        page = _flat(resp.text)
        assert f"The element set for SY-12 ({_SATNO}) was refused: {_UCT_FAILS}. It was not stored." in page
        _no_set_text(page)


class TestTheHistory:
    def test_both_are_left_out_and_the_log_names_them_by_type_and_provider(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.web.routes.udl import fetch_tle_history_for_satno

        UdlStub(reply([
            _record(_GOOD, source="18th SPCS"), _record(_GOOD, ephemType=4, source="EXO"),
            _record(_XP_TEXT, source="EXO"), _record(_GOOD, uct=True, source="KBR"),
        ])).install(monkeypatch)
        with caplog.at_level(logging.INFO):
            history = asyncio.run(fetch_tle_history_for_satno(_SATNO, "u", "p"))
        assert history == [_GOOD]
        assert history.refusal("SY-12") == (
            f"3 element sets in the history for SY-12 were refused: {_XP_FAILS}; {_UCT_FAILS}. They were left out."
        )
        assert f"SATNO {_SATNO}: element sets skipped by type: 2 SGP4-XP (type 4) from EXO; 1 UCT from KBR" in caplog.text
        _no_set_text(caplog.text)


class TestThePatternOfLifeHistory:
    def test_both_are_left_out_of_the_udl_history(self, caplog: pytest.LogCaptureFixture) -> None:
        from spectre.web.routes import pol

        answer = httpx.Response(200, json=[
            _record(_GOOD, source="18th SPCS"), _record(_GOOD, ephemType=4, source="EXO"),
            _record(_GOOD, uct=True, source="KBR"),
        ])
        with caplog.at_level(logging.INFO):
            text, metadata, _, _ = pol._parse_udl_elset_response(answer)
        assert text == _GOOD
        assert list(metadata.values()) == [("REAL", "18th SPCS")]
        assert "element sets skipped by type: 1 SGP4-XP (type 4) from EXO; 1 UCT from KBR" in caplog.text


class TestAPaste:
    def test_an_sgp4_xp_paste_is_refused(self, operator: Any) -> None:
        before = list(operator.state.blue_assets)
        resp = operator.client.post("/assets/blue", data={"name": "PASTED", "tle": _XP_TEXT},
                                    cookies={"spectre_session": operator.cookie}, headers=csrf_headers(operator.cookie))
        assert operator.state.blue_assets == before
        assert f"The element set for PASTED was refused: {_XP_FAILS}. It was not stored." in _flat(resp.text)
