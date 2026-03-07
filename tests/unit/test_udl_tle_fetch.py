"""Unit tests for the dual-mode UDL TLE fetch route.

Uses pytest-asyncio + respx (or unittest.mock) to mock httpx without a live
UDL connection.  All tests run offline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sipc.web.routes.udl import _parse_tle_epoch


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

    def test_two_digit_year_post_2000(self) -> None:
        # Year "99" → 1999 (< 57 threshold)
        line = "1 25544U 98067A   99001.00000000  .00000000  00000-0  00000-0 0  9999 0"
        dt = _parse_tle_epoch(line)
        assert dt is not None
        assert dt.year == 1999

    def test_two_digit_year_pre_2000(self) -> None:
        # Year "57" → 1957
        line = "1 00001U 57001A   57274.33491898  .00000000  00000-0  00000-0 0  9999 0"
        dt = _parse_tle_epoch(line)
        assert dt is not None
        assert dt.year == 1957

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
    """Tests for mode='latest' (GET /udl/elset/current)."""

    @pytest.mark.asyncio
    async def test_latest_calls_elset_current(self, mock_state) -> None:
        """latest mode should hit /elset/current, not /elset."""
        record = _make_udl_record(39034)

        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
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

            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="latest",
                current_user=_make_user(),
            )

            call_args = mock_client.get.call_args
            assert "/elset/current" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_latest_no_udl_creds_returns_error(self, mock_state) -> None:
        mock_state.udl_username = None

        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
        ):
            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="latest",
                current_user=_make_user(),
            )

            ctx = tmpl.TemplateResponse.call_args[0][1]
            assert ctx["error"] is not None
            assert "UDL" in ctx["error"]


class TestFetchTleEpochMode:
    """Tests for mode='epoch' (GET /udl/elset with epoch filter)."""

    @pytest.mark.asyncio
    async def test_epoch_mode_no_scenario_returns_error(self, mock_state) -> None:
        """epoch mode without scenario_start must return a clear error."""
        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
        ):
            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = tmpl.TemplateResponse.call_args[0][1]
            assert ctx["error"] is not None
            assert "scenario time" in ctx["error"].lower()

    @pytest.mark.asyncio
    async def test_epoch_mode_calls_elset_with_epoch_filter(
        self, mock_state_with_scenario
    ) -> None:
        """epoch mode should use /elset with epoch=< filter."""
        record = _make_udl_record(39034, epoch_str="26025.79842163")

        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
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

            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
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
        # scenario_start = 2026-01-25 19:00 UTC
        # day 25 of 2026 = 26025.xxx → closest
        # day 1 of 2026 = 26001.xxx → further away
        near_record = _make_udl_record(39034, epoch_str="26025.00000000")
        far_record = _make_udl_record(39034, epoch_str="26001.00000000")

        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
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

            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = tmpl.TemplateResponse.call_args[0][1]
            assert ctx["error"] is None
            # Near record epoch (day 25) should have been selected → TLE line contains "26025"
            assert "26025" in ctx["tle"]

    @pytest.mark.asyncio
    async def test_epoch_mode_excludes_future_tles(
        self, mock_state_with_scenario
    ) -> None:
        """epoch mode must not select a TLE whose epoch is after scenario_start."""
        # scenario_start = 2026-01-25 19:00 UTC; day 30 is after that
        future_record = _make_udl_record(39034, epoch_str="26030.00000000")

        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
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

            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = tmpl.TemplateResponse.call_args[0][1]
            assert ctx["error"] is not None
            assert "No elset found" in ctx["error"]

    @pytest.mark.asyncio
    async def test_tle_age_days_computed(self, mock_state_with_scenario) -> None:
        """tle_age_days should be the absolute difference in days from scenario_start."""
        # scenario_start = 2026-01-25 19:00 UTC = day 25.79167
        # TLE epoch = day 25.00000 → delta ≈ 0.79167 days ≈ 19 hours
        record = _make_udl_record(39034, epoch_str="26025.00000000")

        with (
            patch("sipc.web.routes.udl.get_session_state", return_value=mock_state_with_scenario),
            patch("sipc.web.routes.udl.get_templates") as tmpl_mock,
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

            tmpl = MagicMock()
            tmpl_mock.return_value = tmpl

            from sipc.web.routes.udl import fetch_tle
            await fetch_tle(
                request=_make_request(),
                satno=39034,
                mode="epoch",
                current_user=_make_user(),
            )

            ctx = tmpl.TemplateResponse.call_args[0][1]
            assert ctx["tle_age_days"] is not None
            assert ctx["tle_age_days"] < 1.0  # less than 1 day apart
