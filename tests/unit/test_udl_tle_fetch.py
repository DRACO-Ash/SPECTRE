"""Unit tests for the dual-mode UDL TLE fetch route.

Uses pytest-asyncio + unittest.mock to mock httpx without a live
UDL connection.  All tests run offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectre.web.routes.udl import (
    _extract_tle_fields,
    _normalise_elset_records,
    _parse_tle_epoch,
    _select_elset_by_epoch,
    _select_latest_elset,
    _tle_epoch_metadata,
)

# ── _parse_tle_epoch ──────────────────────────────────────────────────────────


class TestParseTleEpoch:
    # Epoch "26025.79842163" = day 25 of 2026 + fraction
    _LINE1 = "1 39034U 12075A   26025.79842163  .00000000  00000+0  10000-2 0  9999 0"

    def test_parses_year_and_day(self) -> None:
        dt = _parse_tle_epoch(self._LINE1)
        assert dt is not None
        assert dt.year == 2026
        # Day 25 of 2026 = 25 Jan
        assert dt.month == 1
        assert dt.day == 25

    def test_returns_utc(self) -> None:
        dt = _parse_tle_epoch(self._LINE1)
        assert dt is not None
        assert dt.tzinfo is UTC

    # The TLE convention: two-digit years 57 to 99 are 1957 to 1999, and 00 to
    # 56 are 2000 to 2056. The cases pin both sides of the pivot and each end.
    @pytest.mark.parametrize(("yy", "year"), [
        ("00", 2000), ("26", 2026), ("56", 2056), ("57", 1957), ("99", 1999),
    ])
    def test_two_digit_year_pivots_at_57(self, yy: str, year: int) -> None:
        line = f"1 25544U 98067A   {yy}001.00000000  .00000000  00000-0  00000-0 0  9999 0"
        dt = _parse_tle_epoch(line)
        assert dt is not None
        assert dt.year == year

    def test_returns_none_for_garbage(self) -> None:
        assert _parse_tle_epoch("not a tle line") is None

    def test_returns_none_for_short_line(self) -> None:
        assert _parse_tle_epoch("1 25544") is None

    def test_fractional_day_precision(self) -> None:
        # Epoch "26001.50000000" = 1 Jan 2026 noon UTC
        line = "1 25544U 98067A   26001.50000000  .00000000  00000-0  00000-0 0  9999 0"
        dt = _parse_tle_epoch(line)
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 1
        assert dt.hour == 12


# ── fetch_tle route (mocked httpx) ────────────────────────────────────────────
#
# These tests call the route function directly with a mock Request, bypassing
# FastAPI's test client so we stay purely unit-level.


def _make_udl_record(satno: int, epoch_str: str = "26025.79842163") -> dict:
    """Build a minimal UDL elset record dict."""
    line1 = f"1 {satno:05d}U 12075A   {epoch_str}  .00000000  00000 0  10000-2 0  9999 0"
    line2 = f"2 {satno:05d}   0.0678 359.1324 0003806 313.0884 153.0596 1.00261563 00000 6"
    return {
        "objectName": f"SAT-{satno}",
        "line1": line1,
        "line2": line2,
    }


@pytest.fixture()
def mock_state():
    """Return a SessionState-like mock with UDL credentials and no scenario time."""
    state = MagicMock()
    state.udl_username = "testuser"
    state.udl_password = "testpass"
    state.scenario_start = None
    state.udl_data_mode = "REAL"
    return state


@pytest.fixture()
def mock_state_with_scenario(mock_state):
    """Return a mock SessionState with scenario_start set to 2026-01-25 19:00 UTC."""
    mock_state.scenario_start = datetime(2026, 1, 25, 19, 0, 0, tzinfo=UTC)
    return mock_state


def _make_request():
    req = MagicMock()
    req.url = MagicMock()
    return req


def _make_user():
    user = MagicMock()
    user.username = "testop"
    return user


class TestFetchTleLatestMode:
    """mode='latest': the archive window first, every provider, then /elset/current.

    UDL's /elset/current answers for one source and, given none, for 18th
    SPCS alone, so asking it first returned a 3-day-old set for an object
    commercial providers had tracked that day.
    """

    @staticmethod
    def _client(*payloads: object) -> AsyncMock:
        responses = []
        for payload in payloads:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = payload
            responses.append(resp)
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=responses)
        return client

    async def _fetch(self, mock_state: Any, client: AsyncMock) -> Any:
        from spectre.web.routes.udl import fetch_tle

        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state),
            patch("spectre.web.routes.udl.render") as render_mock,
            patch("httpx.AsyncClient", return_value=client),
        ):
            render_mock.return_value = MagicMock()
            await fetch_tle(request=_make_request(), satno=39034, mode="latest", current_user=_make_user())
        return render_mock.call_args[0][2]

    @pytest.mark.asyncio
    async def test_latest_asks_the_archive_window_first(self, mock_state) -> None:
        client = self._client([_make_udl_record(39034)])
        ctx = await self._fetch(mock_state, client)
        url, params = client.get.call_args.args[0], client.get.call_args.kwargs["params"]
        assert url.endswith("/elset")
        assert str(params["epoch"]).startswith(">")
        assert client.get.await_count == 1
        assert ctx["error"] is None

    @pytest.mark.asyncio
    async def test_latest_falls_back_to_the_current_catalogue(self, mock_state) -> None:
        client = self._client([], [_make_udl_record(39034)])
        ctx = await self._fetch(mock_state, client)
        url, params = client.get.call_args.args[0], client.get.call_args.kwargs["params"]
        assert url.endswith("/elset/current")
        assert "epoch" not in params
        assert ctx["error"] is None

    @pytest.mark.asyncio
    async def test_an_sgp4_xp_only_answer_is_refused_with_the_reason(self, mock_state) -> None:
        xp = {**_make_udl_record(39034), "ephemType": 4}
        ctx = await self._fetch(mock_state, self._client([xp], [xp]))
        assert "SGP4-XP" in ctx["error"]

    @pytest.mark.asyncio
    async def test_latest_no_udl_creds_returns_error(self, mock_state) -> None:
        mock_state.udl_username = None

        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state),
            patch("spectre.web.routes.udl.render") as render_mock,
        ):
            render_mock.return_value = MagicMock()

            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="latest",
                current_user=_make_user(),
            )

            ctx = render_mock.call_args[0][2]  # render(request, name, context)
            assert ctx["error"] is not None
            assert "UDL" in ctx["error"]


class TestFetchTleEpochMode:
    """Tests for mode='epoch' (GET /udl/elset with epoch filter)."""

    @pytest.mark.asyncio
    async def test_epoch_mode_no_scenario_returns_error(self, mock_state) -> None:
        """epoch mode without scenario_start must return a clear error."""
        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state),
            patch("spectre.web.routes.udl.render") as render_mock,
        ):
            render_mock.return_value = MagicMock()

            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = render_mock.call_args[0][2]
            assert ctx["error"] is not None
            assert "scenario time" in ctx["error"].lower()

    @pytest.mark.asyncio
    async def test_epoch_mode_calls_elset_with_epoch_filter(
        self, mock_state_with_scenario
    ) -> None:
        """epoch mode should use /elset with epoch=< filter."""
        record = _make_udl_record(39034, epoch_str="26025.79842163")

        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("spectre.web.routes.udl.render") as render_mock,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [record]
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            render_mock.return_value = MagicMock()

            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            call_args = mock_client.get.call_args
            assert "/elset" in call_args[0][0]
            assert "/elset/current" not in call_args[0][0]
            params = call_args[1]["params"]
            assert str(params.get("epoch", "")).startswith("<")

    @pytest.mark.asyncio
    async def test_epoch_mode_picks_closest_record(
        self, mock_state_with_scenario
    ) -> None:
        """epoch mode should select the record whose epoch is closest to scenario_start."""
        near_record = _make_udl_record(39034, epoch_str="26025.00000000")
        far_record = _make_udl_record(39034, epoch_str="26001.00000000")

        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("spectre.web.routes.udl.render") as render_mock,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [far_record, near_record]
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            render_mock.return_value = MagicMock()

            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = render_mock.call_args[0][2]
            assert ctx["error"] is None
            assert "26025" in ctx["tle"]

    @pytest.mark.asyncio
    async def test_epoch_mode_excludes_future_tles(
        self, mock_state_with_scenario
    ) -> None:
        """epoch mode must not select a TLE whose epoch is after scenario_start."""
        future_record = _make_udl_record(39034, epoch_str="26030.00000000")

        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("spectre.web.routes.udl.render") as render_mock,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [future_record]
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            render_mock.return_value = MagicMock()

            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = render_mock.call_args[0][2]
            assert ctx["error"] is not None
            assert "No elset found" in ctx["error"]

    @pytest.mark.asyncio
    async def test_tle_age_days_computed(self, mock_state_with_scenario) -> None:
        """tle_age_days should be the absolute difference in days from scenario_start."""
        record = _make_udl_record(39034, epoch_str="26025.00000000")

        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("spectre.web.routes.udl.render") as render_mock,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [record]
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            render_mock.return_value = MagicMock()

            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = render_mock.call_args[0][2]
            assert ctx["tle_age_days"] is not None
            assert ctx["tle_age_days"] < 1.0  # less than 1 day apart


# ── The selection helpers lifted out of fetch_tle in 0.5.24 ───────────────────
#
# fetch_tle scored 67 on SonarQube's cognitive complexity against a cap of 15,
# the worst function in the repository, and was invisible to the gate only
# because nobody had touched its lines. Clearing it moved the selection logic
# into named helpers.
#
# The review of that refactor found the logic those helpers exist for was never
# executed by any test: every latest-mode case fed a SINGLE record, so the loop
# that picks the newest of several never ran. The refactor was textually
# faithful, so nothing broke, but a future edit there would have shipped in
# silence. These cover it.


class TestNormaliseElsetRecords:
    """UDL answers with a bare object for one match and a list for several."""

    def test_a_bare_object_becomes_a_single_record_list(self) -> None:
        record = _make_udl_record(25544)
        assert _normalise_elset_records(record) == [record]

    def test_a_list_passes_through(self) -> None:
        records = [_make_udl_record(25544), _make_udl_record(25545)]
        assert _normalise_elset_records(records) == records

    def test_an_empty_list_stays_empty(self) -> None:
        assert _normalise_elset_records([]) == []

    @pytest.mark.parametrize("payload", [None, "not json", 42, 3.5])
    def test_anything_else_yields_no_records(self, payload: object) -> None:
        """A malformed payload must degrade to "no elsets", never raise."""
        assert _normalise_elset_records(payload) == []


class TestSelectLatestElset:
    """The newest epoch wins, and UDL does not order the records."""

    def test_the_newest_is_chosen_from_an_unordered_payload(self) -> None:
        oldest = _make_udl_record(25544, "26001.50000000")
        newest = _make_udl_record(25544, "26010.50000000")
        middle = _make_udl_record(25544, "26005.50000000")
        assert _select_latest_elset([oldest, newest, middle]) is newest

    def test_the_newest_is_chosen_when_it_arrives_last(self) -> None:
        oldest = _make_udl_record(25544, "26001.50000000")
        newest = _make_udl_record(25544, "26010.50000000")
        assert _select_latest_elset([oldest, newest]) is newest

    def test_a_single_record_is_returned_unchanged(self) -> None:
        only = _make_udl_record(25544)
        assert _select_latest_elset([only]) is only

    def test_an_unparsable_first_record_does_not_block_a_parsable_later_one(self) -> None:
        """Otherwise one malformed elset would pin the selection to itself."""
        broken = {"objectName": "SAT", "line1": "nonsense", "line2": "nonsense"}
        good = _make_udl_record(25544, "26010.50000000")
        assert _select_latest_elset([broken, good]) is good

    def test_upper_case_field_spelling_is_read(self) -> None:
        """UDL spells the fields differently depending on the source."""
        old = {"TLE_LINE1": _make_udl_record(25544, "26001.00000000")["line1"]}
        new = {"TLE_LINE1": _make_udl_record(25544, "26009.00000000")["line1"]}
        assert _select_latest_elset([old, new]) is new

    def test_all_unparsable_falls_back_to_the_first(self) -> None:
        a = {"line1": "nonsense"}
        b = {"line1": "also nonsense"}
        assert _select_latest_elset([a, b]) is a


class TestSelectElsetByEpoch:
    """Closest to the scenario start, and never published after it."""

    _START = datetime(2026, 1, 25, 19, 0, tzinfo=UTC)

    def test_the_closest_earlier_record_wins(self) -> None:
        far = _make_udl_record(25544, "26020.00000000")
        near = _make_udl_record(25544, "26025.50000000")
        assert _select_elset_by_epoch([far, near], self._START) is near

    def test_a_record_published_after_the_start_is_skipped(self) -> None:
        """It answers a question the operator did not ask."""
        before = _make_udl_record(25544, "26025.50000000")
        after = _make_udl_record(25544, "26026.50000000")
        assert _select_elset_by_epoch([before, after], self._START) is before

    def test_none_when_every_record_is_after_the_start(self) -> None:
        after_one = _make_udl_record(25544, "26026.00000000")
        after_two = _make_udl_record(25544, "26027.00000000")
        assert _select_elset_by_epoch([after_one, after_two], self._START) is None

    def test_an_unparsable_record_is_skipped_rather_than_ranked(self) -> None:
        broken = {"line1": "nonsense"}
        good = _make_udl_record(25544, "26025.50000000")
        assert _select_elset_by_epoch([broken, good], self._START) is good

    def test_no_records_yields_none(self) -> None:
        assert _select_elset_by_epoch([], self._START) is None


class TestExtractTleFields:
    def test_camel_case_spelling(self) -> None:
        record = _make_udl_record(25544)
        name, tle, line1 = _extract_tle_fields(record, "", 25544)
        assert name == "SAT-25544"
        assert tle == f"{record['line1']}\n{record['line2']}"
        assert line1 == record["line1"]

    def test_upper_case_spelling(self) -> None:
        source = _make_udl_record(25544)
        record = {
            "OBJECT_NAME": "COSMOS 2558",
            "TLE_LINE1": source["line1"],
            "TLE_LINE2": source["line2"],
        }
        name, tle, line1 = _extract_tle_fields(record, "", 25544)
        assert name == "COSMOS 2558"
        assert tle == f"{source['line1']}\n{source['line2']}"

    def test_an_override_beats_the_record(self) -> None:
        name, _, _ = _extract_tle_fields(_make_udl_record(25544), "  ISS  ", 25544)
        assert name == "ISS"

    def test_the_catalogue_number_is_the_last_resort(self) -> None:
        name, _, _ = _extract_tle_fields({"line1": "", "line2": ""}, "", 25544)
        assert name == "25544"


class TestTleEpochMetadata:
    def test_an_unparsable_line_yields_nothing(self) -> None:
        assert _tle_epoch_metadata("nonsense", None) == (None, None)

    def test_without_a_scenario_time_there_is_no_age(self) -> None:
        line1 = _make_udl_record(25544, "26025.00000000")["line1"]
        epoch, age = _tle_epoch_metadata(line1, None)
        assert epoch == "2026-01-25 00:00 UTC"
        assert age is None

    def test_the_age_is_in_days_and_unsigned(self) -> None:
        line1 = _make_udl_record(25544, "26025.00000000")["line1"]
        _, age = _tle_epoch_metadata(line1, datetime(2026, 1, 27, tzinfo=UTC))
        assert age == pytest.approx(2.0, abs=1e-6)

    def test_an_elset_from_after_the_scenario_still_reports_a_positive_age(self) -> None:
        line1 = _make_udl_record(25544, "26025.00000000")["line1"]
        _, age = _tle_epoch_metadata(line1, datetime(2026, 1, 23, tzinfo=UTC))
        assert age == pytest.approx(2.0, abs=1e-6)


class TestARecordWithoutElementLinesIsAnError:
    """Audit F-140. With no parsable line 1 the latest mode fell back to the
    first record, extraction did not check for empty lines, and the route
    rendered no error with a TLE of "\\n" and a "TLE loaded" line.
    Diagnostics read ``tle1``, which extraction ignored."""

    async def _fetch(self, mock_state: object, record: dict) -> dict:
        with (
            patch("spectre.web.routes.udl.get_session_state", return_value=mock_state),
            patch("spectre.web.routes.udl.render") as render_mock,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [record]
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            from spectre.web.routes.udl import fetch_tle
            await fetch_tle(request=_make_request(), satno=39034, mode="latest", current_user=_make_user())
            return render_mock.call_args[0][2]

    @pytest.mark.asyncio
    async def test_no_lines_is_reported(self, mock_state) -> None:
        context = await self._fetch(mock_state, {"objectName": "EMPTY"})
        assert context["error"] is not None
        assert "39034" in context["error"]

    @pytest.mark.asyncio
    async def test_the_tle1_spelling_diagnostics_read_is_extracted_too(self, mock_state) -> None:
        good = _make_udl_record(39034)
        context = await self._fetch(mock_state, {"objectName": "ALT", "tle1": good["line1"], "tle2": good["line2"]})
        assert context["error"] is None
        assert context["tle"] == f"{good['line1']}\n{good['line2']}"
