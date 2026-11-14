"""A refused newer element set does not block the UDL fetch: the newest set the check accepts is taken (SPC-243).

From the owner's UDL probe on 41866 (GOES-16), 13 November 2026 (SPC-240): one provider files every set with
ephemType 2, which the acceptance check refuses, and its epochs are often a millisecond or two newer than the matching
sets of two other providers, so none is tied with it. Until 0.45.0 the fetch took only the sets tied at the newest
epoch, found the type 2 set alone and refused, and returned nothing although the other two pass. The fetch now checks
the complete records newest first, takes the first the check accepts, and names each newer set it refused, its
provider, its epoch and why, on the page and in the log. Only when every set is refused is the fetch refused, as
before.

The commercial providers' sets are proprietary, so the three below are synthetic, built from the probe's one
unclassified set with their epochs, ephemeris type and mean anomaly changed and checksums recomputed: they reproduce
the situation, not the providers' data. Every provider is named synthetically, PROVIDER-A to PROVIDER-D.
"""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.web import rate_limit
from spectre.web.elsets import PassedOver, RefusedElset, passed_over_sentence
from spectre.web.routes import udl
from spectre.web.routes.udl import FetchedElset, fetch_tle_for_satno
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit._decision_reference import _checksum
from tests.unit._udl_stub import UdlStub, reply

_SATNO = 41866
_NAME = "GOES-16 (41866)"
#: 13:00 UTC on 13 November 2026, the moment the probe's situation is replayed at.
_REPLAYED_AT = datetime(2026, 11, 13, 13, 0, tzinfo=UTC)

#: The probe's one unclassified set, filed here as PROVIDER-D's, epoch 07:09:01.248 UTC.
_UNCLASSIFIED = ("1 41866U 16071A   26317.29793111 -.00000079 +00000+0 +00000+0 0 99996",
         "2 41866   0.7075  83.5274 0002374 168.4362 163.0396  1.00271604036593")


def _synthetic(epoch_field: str, ephem_type: str, mean_anomaly: str) -> tuple[str, str]:
    """The unclassified set with line 1's epoch (columns 19 to 32) and ephemeris type (column 63) and line 2's mean
    anomaly (columns 44 to 51) replaced, both checksums recomputed."""
    body1 = f"{_UNCLASSIFIED[0][:18]}{epoch_field}{_UNCLASSIFIED[0][32:62]}{ephem_type}{_UNCLASSIFIED[0][63:68]}"
    body2 = f"{_UNCLASSIFIED[1][:43]}{mean_anomaly}{_UNCLASSIFIED[1][51:68]}"
    return f"{body1}{_checksum(body1)}", f"{body2}{_checksum(body2)}"


#: The newest, ephemeris type 2, at 12:28:48.002 UTC.
_TYPE_2_SET = _synthetic("26317.52000002", "2", "243.0300")
#: Type 0, 1.7 milliseconds older, at 12:28:48.000 UTC: not tied with the type 2 set.
_MS_OLDER = _synthetic("26317.52000000", "0", "243.0280")
#: Type 0, about 9 seconds older again, at 12:28:39.360 UTC.
_SECONDS_OLDER = _synthetic("26317.51990000", "0", "242.9900")
_TYPE_2 = "its ephemeris type is 2, not 0, the SGP4 type every propagator here assumes"
_UCT = "it is an uncorrelated track (UCT), not a set correlated to the object"


def _record(lines: tuple[str, str], source: str, **fields: object) -> dict[str, object]:
    return {"line1": lines[0], "line2": lines[1], "source": source, "dataMode": "REAL", **fields}


def _at(lines: tuple[str, str], epoch_field: str) -> tuple[str, str]:
    """*lines* with line 1's epoch field (columns 19 to 32) replaced and its checksum recomputed."""
    body = f"{lines[0][:18]}{epoch_field}{lines[0][32:68]}"
    return f"{body}{_checksum(body)}", lines[1]


def _text(lines: tuple[str, str]) -> str:
    return f"{lines[0]}\n{lines[1]}"


#: The four records, in an order that is not newest first: UDL answers in no order.
_OWNERS = [
    _record(_UNCLASSIFIED, "PROVIDER-D", ephemType=0),
    _record(_SECONDS_OLDER, "PROVIDER-C", ephemType=0, uct=False),
    _record(_MS_OLDER, "PROVIDER-B", ephemType=0),
    _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2, uct=False),
]
#: PROVIDER-A's set about three hours earlier, at 09:36 UTC: refused for the same reason.
_TYPE_2_EARLIER = _at(_TYPE_2_SET, "26317.40000000")

_ONE_REFUSED = (
    f"A newer element set for {_NAME}, from PROVIDER-A with epoch 2026-11-13 12:28:48.002 UTC, was refused: "
    f"{_TYPE_2}. The set used is PROVIDER-B's, epoch 2026-11-13 12:28:48.000 UTC, 0.002 s older."
)


class _At13UTC(datetime):
    """The UDL module's ``datetime`` with ``now`` held at 13:00 UTC on 13 November 2026."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return _REPLAYED_AT.astimezone(tz)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(udl, "datetime", _At13UTC)


def _fetch(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, object]]) -> Any:
    UdlStub(reply(records)).install(monkeypatch)
    return asyncio.run(fetch_tle_for_satno(_SATNO, "u", "p"))


def _no_set_text(text: str) -> None:
    for lines in (_TYPE_2_SET, _MS_OLDER, _SECONDS_OLDER, _UNCLASSIFIED, _TYPE_2_EARLIER):
        for line in lines:
            assert line not in text, "an element set's text reached the log or the page"


def _flat(text: str) -> str:
    return html.unescape(" ".join(text.split()))


class TestTheProbesSituation:
    def test_the_synthetic_lines_pass_their_checksums(self) -> None:
        for lines in (_TYPE_2_SET, _MS_OLDER, _SECONDS_OLDER, _UNCLASSIFIED):
            for line in lines:
                assert line[68] == _checksum(line[:68]), f"{line[:7]} fails its checksum"

    def test_the_ms_older_set_is_taken_and_the_type_2_set_named_as_refused(
        self, clock: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO):
            got = _fetch(monkeypatch, _OWNERS)
        assert isinstance(got, FetchedElset), "the fetch returned no set although two older sets pass"
        assert got.tle == _text(_MS_OLDER)
        assert (got.source, got.data_mode) == ("PROVIDER-B", "REAL")
        assert got.passed_over == (
            PassedOver("PROVIDER-A", datetime(2026, 11, 13, 12, 28, 48, 1728, tzinfo=UTC), (_TYPE_2,)),
        )
        assert got.passed_over_note(_NAME) == _ONE_REFUSED

    def test_the_log_names_the_refused_set_by_type_and_says_which_was_used(
        self, clock: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO):
            _fetch(monkeypatch, _OWNERS)
        assert f"SATNO {_SATNO}: element sets skipped by type: 1 ephemeris type 2 from PROVIDER-A" in caplog.text
        assert _ONE_REFUSED.replace(_NAME, f"SATNO {_SATNO}") in caplog.text
        _no_set_text(caplog.text)


class TestWhichSetIsTaken:
    def test_an_older_accepted_set_is_taken_and_every_newer_refused_one_named(
        self, clock: None, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        got = _fetch(monkeypatch, [
            _record(_UNCLASSIFIED, "PROVIDER-D"),
            _record(_TYPE_2_EARLIER, "PROVIDER-A", ephemType=2),
            _record(_SECONDS_OLDER, "PROVIDER-C", ephemType=0, uct=True),
            _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2),
        ])
        assert isinstance(got, FetchedElset)
        assert (got.tle, got.source) == (_text(_UNCLASSIFIED), "PROVIDER-D")
        assert [p.source for p in got.passed_over] == ["PROVIDER-A", "PROVIDER-C", "PROVIDER-A"], "named newest first"
        assert got.passed_over_note(_NAME) == (
            f"3 newer element sets for {_NAME} were refused. 2 from PROVIDER-A with epochs 2026-11-13 09:36:00.000 UTC "
            f"to 2026-11-13 12:28:48.002 UTC: {_TYPE_2}. 1 from PROVIDER-C with epoch 2026-11-13 12:28:39.360 UTC: "
            f"{_UCT}. The set used is PROVIDER-D's, epoch 2026-11-13 07:09:01.248 UTC, 5.3 h older than the newest "
            "refused."
        )

    def test_several_from_one_provider_are_named_together(self, clock: None, monkeypatch: pytest.MonkeyPatch) -> None:
        got = _fetch(monkeypatch, [
            _record(_UNCLASSIFIED, "PROVIDER-D"), _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2),
            _record(_TYPE_2_EARLIER, "PROVIDER-A", ephemType=2),
        ])
        assert isinstance(got, FetchedElset)
        assert got.passed_over_note(_NAME) == (
            f"2 newer element sets for {_NAME}, from PROVIDER-A with epochs 2026-11-13 09:36:00.000 UTC to "
            f"2026-11-13 12:28:48.002 UTC, were refused: {_TYPE_2}. The set used is PROVIDER-D's, epoch "
            "2026-11-13 07:09:01.248 UTC, 5.3 h older than the newest refused."
        )

    def test_when_every_set_is_refused_the_fetch_is_refused_as_before(
        self, clock: None, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        got = _fetch(monkeypatch, [
            _record(_TYPE_2_EARLIER, "PROVIDER-A", ephemType=2), _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2),
        ])
        assert isinstance(got, RefusedElset)
        assert got.sentence(_NAME) == f"The element set for {_NAME} was refused: {_TYPE_2}. It was not stored."

    @pytest.mark.parametrize("newest_first", [True, False], ids=["newest-listed-first", "newest-listed-last"])
    def test_when_every_set_is_refused_for_different_reasons_the_newest_sets_reason_is_named(
        self, clock: None, monkeypatch: pytest.MonkeyPatch, newest_first: bool,
    ) -> None:
        newest = _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2)
        older = _record(_MS_OLDER, "PROVIDER-B", ephemType=0, uct=True)
        got = _fetch(monkeypatch, [newest, older] if newest_first else [older, newest])
        assert isinstance(got, RefusedElset)
        assert got.check.failures == (_TYPE_2,)

    def test_a_set_whose_epoch_cannot_be_read_is_checked_last(
        self, clock: None, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Day 0 is no date, so the set sorts after every dated one: the refusal names the newest dated set's reason."""
        undated = _at(_MS_OLDER, "26000.50000000")
        got = _fetch(monkeypatch, [_record(undated, "PROVIDER-B"), _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2)])
        assert isinstance(got, RefusedElset)
        assert got.check.failures == (_TYPE_2,)

    @pytest.mark.parametrize("listed", [("PROVIDER-B", "PROVIDER-C"), ("PROVIDER-C", "PROVIDER-B")],
                             ids=["B-listed-first", "C-listed-first"])
    def test_of_two_accepted_sets_tied_at_one_epoch_the_first_by_provider_is_taken(
        self, clock: None, monkeypatch: pytest.MonkeyPatch, listed: tuple[str, str],
    ) -> None:
        """Neither is older, so the order UDL listed them in decides nothing: provider, then set text."""
        tied = _synthetic("26317.52000000", "0", "200.0000")
        sets = {"PROVIDER-B": _MS_OLDER, "PROVIDER-C": tied}
        got = _fetch(monkeypatch, [_record(sets[name], name, ephemType=0) for name in listed])
        assert isinstance(got, FetchedElset)
        assert (got.tle, got.source, got.passed_over) == (_text(_MS_OLDER), "PROVIDER-B", ())

    def test_the_newest_accepted_is_taken_and_nothing_named(self, clock: None, monkeypatch: pytest.MonkeyPatch) -> None:
        got = _fetch(monkeypatch, [_OWNERS[0], _OWNERS[1], _OWNERS[2]])
        assert isinstance(got, FetchedElset)
        assert (got.tle, got.source, got.passed_over) == (_text(_MS_OLDER), "PROVIDER-B", ())
        assert got.passed_over_note(_NAME) == ""

    def test_a_tie_at_the_newest_takes_the_accepted_one_and_names_nothing(
        self, clock: None, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The type 2 set at PROVIDER-B's own epoch is not newer, so it is not passed over: the tie rule stands."""
        tied = _at(_TYPE_2_SET, "26317.52000000")
        got = _fetch(monkeypatch, [
            _record(_MS_OLDER, "PROVIDER-B", ephemType=0), _record(tied, "PROVIDER-A", ephemType=2),
        ])
        assert isinstance(got, FetchedElset)
        assert (got.tle, got.source, got.passed_over) == (_text(_MS_OLDER), "PROVIDER-B", ())

    def test_past_the_cap_older_sets_are_not_checked(
        self, clock: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(udl, "_MAX_SETS_CHECKED", 2)
        with caplog.at_level(logging.WARNING):
            got = _fetch(monkeypatch, [
                _record(_UNCLASSIFIED, "PROVIDER-D"), _record(_TYPE_2_SET, "PROVIDER-A", ephemType=2),
                _record(_TYPE_2_EARLIER, "PROVIDER-A", ephemType=2),
            ])
        assert isinstance(got, RefusedElset)
        assert got.sentence(_NAME) == (
            f"The element set for {_NAME} was refused: {_TYPE_2}. It was not stored. Only the newest 2 element sets "
            "were checked; 1 older one was not."
        )
        assert (f"SATNO {_SATNO}: the newest 2 of 3 element sets were all refused; the 1 older were not checked"
                in caplog.text)

    def test_the_cap_is_500(self) -> None:
        assert udl._MAX_SETS_CHECKED == 500


class TestTheSentence:
    def test_an_unnamed_provider_and_an_unread_epoch_are_said_so(self) -> None:
        epoch = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
        assert passed_over_sentence("SY-12", (PassedOver("", epoch, ("a reason",)),), "", None) == (
            "A newer element set for SY-12, from an unnamed provider with epoch 2026-11-13 12:00:00.000 UTC, was "
            "refused: a reason. The set used is an unnamed provider's."
        )

    @pytest.mark.parametrize(("seconds", "words"), [(90.0, "1.5 min older"), (3 * 86400.0, "3.0 d older")])
    def test_the_gap_reads_in_minutes_or_days(self, seconds: float, words: str) -> None:
        used = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
        sentence = passed_over_sentence("X", (PassedOver("PROVIDER-A", used + timedelta(seconds=seconds), ("r",)),),
                                        "PROVIDER-B", used)
        assert sentence.endswith(f"The set used is PROVIDER-B's, epoch 2026-11-13 12:00:00.000 UTC, {words}.")


@pytest.fixture
def operator(client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch, clock: None) -> Iterator[Any]:
    """The test operator, connected to UDL in REAL with no source chosen, their session restored after."""
    for name in ("_udl_auth_limiter", "_udl_data_limiter", "_udl_sync_limiter"):
        monkeypatch.setattr(rate_limit, name, rate_limit.SlidingWindowLimiter(100, 60))
    state = session_state(auth_cookie)
    names = ("udl_username", "udl_password", "udl_data_mode", "udl_tle_source", "scenario_start", "red_tracks",
             "blue_assets", "elset_refresh", "log_entries")
    saved = {name: getattr(state, name) for name in names}
    state.udl_username, state.udl_password, state.udl_data_mode, state.udl_tle_source = "op", "pw", "REAL", ""
    state.scenario_start, state.red_tracks, state.blue_assets = None, [], []
    yield SimpleNamespace(client=client, cookie=auth_cookie, state=state)
    for name, value in saved.items():
        setattr(state, name, value)


class TestOnScreen:
    def test_the_udl_panel_fills_the_form_with_the_set_taken_and_names_the_refused_one(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        resp = operator.client.get(f"/udl/tle?satno={_SATNO}&name_override=GOES-16",
                                   cookies={"spectre_session": operator.cookie})
        assert resp.status_code == 200
        assert _text(_MS_OLDER) in html.unescape(resp.text), "the form holds the set taken"
        page = _flat(resp.text)
        assert _ONE_REFUSED in page
        assert 'name="elset_source" value="PROVIDER-B"' in page
        assert "was refused" in page and "field-error" not in page, "a set was taken, so nothing is an error"

    def test_the_udl_panel_takes_the_newest_accepted_at_or_before_the_scenario_start(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        operator.state.scenario_start = _REPLAYED_AT
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        resp = operator.client.get(f"/udl/tle?satno={_SATNO}&name_override=GOES-16&mode=epoch",
                                   cookies={"spectre_session": operator.cookie})
        page = _flat(resp.text)
        assert _text(_MS_OLDER) in html.unescape(resp.text)
        assert _ONE_REFUSED in page

    def test_quick_add_adds_the_set_taken_and_says_the_newer_was_refused(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        resp = operator.client.post("/assets/red/quick-add", data={"satno": str(_SATNO), "name": "GOES-16"},
                                    cookies={"spectre_session": operator.cookie},
                                    headers=csrf_headers(operator.cookie))
        assert resp.status_code == 200
        [track] = operator.state.red_tracks
        assert (track.tle, track.elset_source) == (_text(_MS_OLDER), "PROVIDER-B")
        assert _ONE_REFUSED in _flat(resp.text)
        assert f"[UDL] {_ONE_REFUSED}" in operator.state.log_entries

    def test_the_blue_quick_add_says_so_too(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        resp = operator.client.post("/assets/blue/quick-add", data={"satno": str(_SATNO), "name": "GOES-16"},
                                    cookies={"spectre_session": operator.cookie},
                                    headers=csrf_headers(operator.cookie))
        [asset] = operator.state.blue_assets
        assert asset.tle == _text(_MS_OLDER)
        assert _ONE_REFUSED in _flat(resp.text)

    def test_the_connect_refresh_note_names_the_refused_set(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.domain.models import RedTrack
        from spectre.web.elsets import refresh_held_elsets

        operator.state.red_tracks = [RedTrack(name="GOES-16", tle=_text(_UNCLASSIFIED), data_mode="REAL")]
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        asyncio.run(refresh_held_elsets(operator.state, "op", "pw"))
        assert operator.state.red_tracks[0].tle == _text(_MS_OLDER)
        sentence = _ONE_REFUSED.replace(_NAME, "red GOES-16")
        assert operator.state.elset_refresh.passed_over == [sentence]
        note = _flat(operator.client.get("/udl/elset-refresh", cookies={"spectre_session": operator.cookie}).text)
        assert sentence in note
        assert "1 updated, 0 already current" in note


class TestTheAgeShownIsTheSetUsed:
    """The refused type 2 set is 31 minutes old at 13:00 UTC; PROVIDER-D's, the set used, is 5.8 hours old."""

    _RECORDS = [_record(_TYPE_2_SET, "PROVIDER-A", ephemType=2), _record(_UNCLASSIFIED, "PROVIDER-D", ephemType=0)]

    def test_the_udl_panel_states_the_epoch_and_age_of_the_set_used(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        operator.state.scenario_start = _REPLAYED_AT
        UdlStub(reply(self._RECORDS)).install(monkeypatch)
        page = _flat(operator.client.get(f"/udl/tle?satno={_SATNO}&name_override=GOES-16",
                                         cookies={"spectre_session": operator.cookie}).text)
        assert "TLE epoch: <strong>2026-11-13 07:09 UTC</strong>" in page
        assert "0.2d from scenario" in page
        assert "12:28 UTC" not in page.split("A newer element set")[0], "the refused set's epoch is not the one shown"

    def test_the_red_card_ages_the_set_used(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.routes import threat

        UdlStub(reply(self._RECORDS)).install(monkeypatch)
        operator.client.post("/assets/red/quick-add", data={"satno": str(_SATNO), "name": "GOES-16"},
                             cookies={"spectre_session": operator.cookie}, headers=csrf_headers(operator.cookie))
        monkeypatch.setattr(threat, "datetime", _At13UTC)
        card = _flat(operator.client.get("/plan/threat/red-orbit-info?red_sat=GOES-16",
                                         cookies={"spectre_session": operator.cookie}).text)
        assert "5.8 h old" in card
        assert "Provider:</strong> PROVIDER-D" in card


#: What the fetch gives for the four records, for the callers to show.
_B_TAKEN = FetchedElset(_text(_MS_OLDER), "REAL", "PROVIDER-B", (
    PassedOver("PROVIDER-A", datetime(2026, 11, 13, 12, 28, 48, 1728, tzinfo=UTC), (_TYPE_2,)),
))


@pytest.fixture
def connected(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A session connected to UDL whose current fetch answers PROVIDER-B's set for 41866, PROVIDER-A's passed over."""
    from spectre.web.elsets import ElsetHistory
    from spectre.web.planning_state import SessionState

    async def current(*_args: object, **_kwargs: object) -> FetchedElset:
        return _B_TAKEN

    async def history(*_args: object, **_kwargs: object) -> ElsetHistory:
        return ElsetHistory()

    monkeypatch.setattr(udl, "fetch_tle_for_satno", current)
    monkeypatch.setattr(udl, "fetch_tle_history_for_satno", history)
    state = SessionState()
    state.udl_username, state.udl_password = "op", "pw"
    state.hrr_objects = [{"satno": str(_SATNO), "name": "GOES-16"}]
    return state


class TestEveryCallerShowsIt:
    def test_the_sweep_names_it_among_its_notes(self, connected: Any) -> None:
        from spectre.domain.models import ThreatTarget
        from spectre.web.routes.threat import _fetch_missing_target_tles

        errors: list[str] = []
        target = ThreatTarget(target_name="GOES-16", target_satno=str(_SATNO), target_source="hrr", hrr_rank=1)
        asyncio.run(_fetch_missing_target_tles(connected, [target], errors))
        assert connected.hrr_tle_cache[str(_SATNO)] == _text(_MS_OLDER)
        assert errors == [_ONE_REFUSED]

    def test_the_target_prefetch_says_so_in_the_run_log(self, connected: Any) -> None:
        from spectre.web.routes.threat import _prefetch_group_tle

        done = asyncio.run(_prefetch_group_tle(connected, str(_SATNO), asyncio.Semaphore(1), 24.0))
        assert done is True
        assert connected.hrr_tle_cache[str(_SATNO)] == _text(_MS_OLDER)
        assert f"[UDL] {_ONE_REFUSED}" in connected.log_entries

    def test_the_screen_keeps_it_apart_from_the_failed_fetches(self, connected: Any) -> None:
        """A set taken over a refused newer one is live: its note is not a failure's (V0.45 review 1)."""
        from spectre.domain.models import ThreatActor
        from spectre.web.routes.threat import _refresh_outcomes

        got = asyncio.run(_refresh_outcomes(connected, [ThreatActor(actor_name="GOES-16", actor_satno="41866")]))
        assert connected.hrr_tle_cache[str(_SATNO)] == _text(_MS_OLDER)
        assert (got.failed, got.passed_over) == ({}, {str(_SATNO): _ONE_REFUSED})

    def test_the_intercept_badge_stays_real_and_the_note_is_apart(self, connected: Any) -> None:
        from spectre.web.routes.maneuver import _resolve_provenance

        got = asyncio.run(_resolve_provenance(_text(_UNCLASSIFIED), _text(_UNCLASSIFIED), "REAL", connected))
        assert (got.red_tle, got.blue_tle, got.label) == (_text(_MS_OLDER), _text(_MS_OLDER), "REAL")
        named = _ONE_REFUSED.replace(_NAME, f"SATNO {_SATNO}")
        assert got.notes == (named, named)

    def test_the_burn_watch_note_names_it(self, connected: Any) -> None:
        from spectre.web import burn_watch
        from tests.integration.test_burn_watch import _note, _watch

        watch = _watch(connected)
        epoch = asyncio.run(burn_watch._probe(connected, watch))
        assert epoch == datetime(2026, 11, 13, 12, 28, 48, tzinfo=UTC), "the epoch of the set taken"
        named = _ONE_REFUSED.replace(_NAME, "RED-X (90010)")
        assert watch.note == named
        assert named in _flat(_note(burn_watch=watch, burn_alert=None, watch_ends_at=None))


class TestThePanelSaysWhichSetItTook:
    def _get(self, operator: Any, query: str) -> Any:
        resp = operator.client.get(f"/udl/tle?satno={_SATNO}{query}", cookies={"spectre_session": operator.cookie})
        assert resp.status_code == 200
        return resp

    def test_the_name_and_the_logged_epoch_are_the_set_taken(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The name came from the newest record, the refused one, and so did the logged epoch (V0.45 review 2)."""
        UdlStub(reply([
            {**_record(_TYPE_2_SET, "PROVIDER-A", ephemType=2), "objectName": "REFUSED-NAME"},
            {**_record(_MS_OLDER, "PROVIDER-B", ephemType=0), "objectName": "TAKEN-NAME"},
        ])).install(monkeypatch)
        with caplog.at_level(logging.INFO):
            page = _flat(self._get(operator, "").text)
        assert "TLE loaded: <strong>TAKEN-NAME</strong>" in page
        assert "REFUSED-NAME" not in page
        assert "Latest mode selected record with epoch=2026-11-13T12:28:48+00:00" in caplog.text
        assert "selected record with epoch=2026-11-13T12:28:48.001728" not in caplog.text

    def test_the_run_log_holds_the_sentence(self, operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        self._get(operator, "&name_override=GOES-16")
        assert (f"[UDL] Fetched TLE for SATNO {_SATNO} (GOES-16) mode=latest epoch=2026-11-13 12:28 UTC. "
                f"{_ONE_REFUSED}") in operator.state.log_entries

    def test_epoch_mode_is_not_stopped_by_a_closest_record_without_lines(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        operator.state.scenario_start = _REPLAYED_AT
        closest = _at(_SECONDS_OLDER, "26317.53472222")[0]
        stub = UdlStub(reply([{"line1": closest, "source": "PROVIDER-C"}, _record(_MS_OLDER, "PROVIDER-B")]))
        stub.install(monkeypatch)
        resp = self._get(operator, "&name_override=GOES-16&mode=epoch")
        assert _text(_MS_OLDER) in html.unescape(resp.text)
        assert "field-error" not in resp.text
        assert stub.params()["maxResults"] == "100"

    def test_epoch_mode_takes_a_set_dated_exactly_at_the_scenario_start(
        self, operator: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.astro.elset_check import tle_epoch

        operator.state.scenario_start = tle_epoch(_MS_OLDER[0])
        UdlStub(reply(_OWNERS)).install(monkeypatch)
        resp = self._get(operator, "&name_override=GOES-16&mode=epoch")
        assert _text(_MS_OLDER) in html.unescape(resp.text)
        assert "Newer set refused" not in resp.text, "the type 2 set is after the scenario start, so not considered"


class TestTheScreenDoesNotCallALiveSetIllustrative:
    def test_no_provenance_banner_shows_and_the_note_does(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every set is live (the asset pasted, the actor fetched REAL), so the banner has nothing to say (V0.45
        review 1); the set taken over a refused newer one is named in a note of its own."""
        from spectre.astro.elset_check import tle_epoch
        from spectre.web.planning_state import SessionState
        from tests.integration.test_threat_screen_route import _ASSET_TLE, _RED_TLE

        newer = tle_epoch(_RED_TLE.splitlines()[0])
        assert newer is not None
        passed = (PassedOver("PROVIDER-A", newer.replace(microsecond=2000), (_TYPE_2,)),)

        async def current(*_args: object, **_kwargs: object) -> FetchedElset:
            return FetchedElset(_RED_TLE, "REAL", "PROVIDER-B", passed)

        monkeypatch.setattr(udl, "fetch_tle_for_satno", current)
        state: SessionState = session_state(auth_cookie)  # type: ignore[assignment]
        saved = (state.udl_username, state.udl_password, state.hrr_objects)
        state.udl_username, state.udl_password = "u", "p"
        state.hrr_objects = [{"satno": "41838", "name": "SJ-17", "country": "CHN", "rank": 1, "orbit_regime": "GEO"}]
        state.hrr_tle_cache["41838"] = _RED_TLE
        state.hrr_tle_data_mode["41838"] = "SYNTHETIC"
        try:
            resp = client.post("/plan/threat/screen", data={"manual_asset_tle": _ASSET_TLE, "max_dv_m_s": 5000},
                               cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie))
        finally:
            state.udl_username, state.udl_password, state.hrr_objects = saved
            state.hrr_tle_cache.pop("41838", None)
            state.hrr_tle_data_mode.pop("41838", None)
        page = _flat(resp.text)
        assert "Element sets not from live tracking" not in page
        assert FetchedElset(_RED_TLE, "REAL", "PROVIDER-B", passed).passed_over_note("SJ-17 (41838)") in page


class TestTheInterceptBadge:
    @pytest.mark.parametrize("path", ["apply-intercept", "apply-all-intercepts"])
    def test_it_stays_real_and_green_with_the_note_beside_it(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch, path: str,
    ) -> None:
        from spectre.astro.elset_check import tle_epoch
        from spectre.data.intel import satno_from_tle
        from tests.integration.test_web_routes_extended import _ISS_TLE, _ISS_TLE_2, _add_assets

        held = {satno_from_tle(tle): tle for tle in (_ISS_TLE, _ISS_TLE_2)}

        async def current(satno: int, *_args: object, **_kwargs: object) -> FetchedElset:
            tle = held[satno]
            epoch = tle_epoch(tle.splitlines()[0])
            assert epoch is not None
            newer = PassedOver("PROVIDER-A", epoch + timedelta(milliseconds=2), (_TYPE_2,))
            return FetchedElset(tle, "REAL", "PROVIDER-B", (newer,))

        monkeypatch.setattr(udl, "fetch_tle_for_satno", current)
        _add_assets(client, auth_cookie)
        state: Any = session_state(auth_cookie)
        saved = (state.udl_username, state.udl_password)
        state.udl_username, state.udl_password = "u", "p"
        try:
            resp = client.post(
                f"/plan/maneuver/{path}",
                data={"red_sat": "ISS-RED", "blue_sat": "ISS-BLUE", "method": "hohmann", "coast_hours": "0.0",
                      "intercept_hours": "2.0", "intercept_data_mode": "REAL"},
                cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
            )
        finally:
            state.udl_username, state.udl_password = saved
        page = _flat(resp.text)
        assert '<span class="badge-ok" style="font-size:0.68rem">Data Mode: REAL</span>' in page
        assert "Newer set refused" in page and "from PROVIDER-A with epoch" in page
