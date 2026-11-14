"""Every exit from the Pattern of Life routes says what the operator can do next (SPC-012).

The PoL routes were 70 per cent covered at 74d1105, and the lines no test ran
were the refusals, fallbacks and failure sentences: the screens an operator
lands on when something is missing or broken. Each test here pins one of
those screens by what it says, not by the status code alone, because every
exit answers 200 with an HTML fragment and only the words tell them apart.

Writing them found one defect: /pol/chart-data read ``pol.manoeuvre_types``,
a field PolAnalysis no longer carries, so every request for an analysed
object raised and no PoL chart ever drew.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.astro.pattern_of_life import PolAnalysis, analyse_pattern_of_life
from spectre.data import notso_cache
from spectre.domain.pol_assessment import assess_pattern_of_life
from spectre.web import rate_limit
from spectre.web.routes import pol
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit.test_dv_estimation import TestTwoTierReporting

_SATNO = 62902
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_MARKER = "internal-detail-SPC012-5519"
_LOGGER = "spectre.web.routes.pol"
_NO_ANALYSIS = "No PoL analysis for this SATNO. Run Pattern of Life first."


#: Three burns, so the history has burn statistics as well as burns.
_BURNS = (60, 150, 240)


@pytest.fixture(scope="module")
def history_text() -> str:
    """The element-set history of a coasting LEO object with three clear burns."""
    return "\n".join(r.tle for r in TestTwoTierReporting._catalogue(burn_at=_BURNS))


@pytest.fixture(scope="module")
def analysis() -> PolAnalysis:
    result = analyse_pattern_of_life(TestTwoTierReporting._catalogue(burn_at=_BURNS), satno=_SATNO, name="SIM")
    assert len(result.manoeuvres) == len(_BURNS), "the fixture must hold three confirmed manoeuvres"
    return result


@pytest.fixture
def state(auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The signed-in session with open limits, a fixed clock and no analysis or UDL session."""
    monkeypatch.setattr(rate_limit, "_udl_auth_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rate_limit, "_pol_compute_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(pol, "_utc_now", lambda: _NOW)
    held = session_state(auth_cookie)
    saved = (held.udl_username, held.udl_password, held.udl_data_mode, getattr(held, "last_pol_analysis", None))
    held.udl_username, held.udl_password, held.udl_data_mode = None, None, "REAL"
    held.last_pol_analysis = None  # type: ignore[attr-defined]
    yield held
    held.udl_username, held.udl_password, held.udl_data_mode, held.last_pol_analysis = saved  # type: ignore[attr-defined]


@pytest.fixture
def analysed(state: Any, analysis: PolAnalysis) -> Any:
    """The session holding the fixture's analysis, as after a successful Pattern of Life run."""
    state.last_pol_analysis = analysis
    state.pol_reserve_resets = {}
    return state


def _post(client: Any, cookie: str, path: str, data: dict[str, str]) -> str:
    resp = client.post(path, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return html.unescape(" ".join(resp.text.split()))


def _analyse(client: Any, cookie: str, **fields: str) -> str:
    return _post(client, cookie, "/pol/analyse", {"satno": str(_SATNO), **fields})


def _merged(text: str) -> Any:
    async def fetched(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return text, text, {}, {}, "SIM"
    return fetched


class TestAnalyseRefusals:
    def test_no_udl_session_names_both_ways_forward(self, client: Any, auth_cookie: str, state: Any) -> None:
        page = _analyse(client, auth_cookie, pol_source="udl")
        assert "No active UDL session. Connect UDL first, or choose 'UDL (credentials)'." in page

    @pytest.mark.parametrize(("user", "password"), [("", "p"), ("   ", "p"), ("u", "")])
    def test_direct_credentials_with_a_blank_half_are_refused(
        self, client: Any, auth_cookie: str, state: Any, user: str, password: str,
    ) -> None:
        page = _analyse(client, auth_cookie, pol_source="udl_direct", udl_user=user, udl_pass=password)
        assert "Enter UDL username and password." in page

    def test_direct_credentials_send_the_password_as_typed(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Audit F-251: stripping the password sent a different credential."""
        sent: list[tuple[Any, ...]] = []

        async def capture(*args: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
            sent.append(args)
            return "", "", {}, {}, "SIM"

        monkeypatch.setattr(pol, "_fetch_merged_history", capture)
        _analyse(client, auth_cookie, pol_source="udl_direct", udl_user="  op  ", udl_pass=" pass word ")
        assert sent == [(_SATNO, "op", " pass word ", "REAL")]

    def test_an_empty_history_says_what_to_check(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pol, "_fetch_merged_history", _merged("  \n "))
        page = _analyse(client, auth_cookie, pol_source="udl_direct", udl_user="u", udl_pass="p")
        assert f"No TLE data returned from UDL for SATNO {_SATNO}." in page
        assert "Check the SATNO and credentials" in page

    def test_a_history_with_no_parseable_set_says_so(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pol, "_fetch_merged_history", _merged("not an element set"))
        page = _analyse(client, auth_cookie, pol_source="udl_direct", udl_user="u", udl_pass="p")
        assert f"No valid TLEs parsed from UDL response for SATNO {_SATNO}." in page
        assert getattr(state, "last_pol_analysis", None) is None, "a failed run replaced the held analysis"

    def test_a_failure_keeps_the_session_form_for_a_connected_operator(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The error panel is the whole panel: a connected operator still sees the session choice checked."""
        state.udl_username, state.udl_password = "op", "pw"
        monkeypatch.setattr(pol, "_fetch_merged_history", _merged(""))
        page = _analyse(client, auth_cookie, pol_source="udl")
        assert 'value="udl" checked' in page
        assert f"No TLE data returned from UDL for SATNO {_SATNO}." in page


class TestAnalyseSucceeds:
    def test_a_session_run_with_the_cadence_filter_says_so_in_the_log(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch, history_text: str,
    ) -> None:
        state.udl_username, state.udl_password = "op", "pw"
        monkeypatch.setattr(pol, "_fetch_merged_history", _merged(history_text))
        _analyse(client, auth_cookie, pol_source="udl", cadence_filter="on")
        assert state.last_pol_analysis.satno == _SATNO
        line = state.log_entries[-1]
        assert line.startswith(f"[POL] Analysed {_SATNO}: 300 TLEs, 3 manoeuvres")
        assert line.endswith("[UDL] [cadence-filtered, 0 flags]")

    def test_an_unfiltered_run_says_nothing_about_a_filter(
        self, client: Any, auth_cookie: str, state: Any, monkeypatch: pytest.MonkeyPatch, history_text: str,
    ) -> None:
        """Zero flags from a filter that never ran would read as a clean history."""
        monkeypatch.setattr(pol, "_fetch_merged_history", _merged(history_text))
        _analyse(client, auth_cookie, pol_source="udl_direct", udl_user="u", udl_pass="p")
        assert state.log_entries[-1].endswith("[UDL]")


class TestReserveReset:
    @pytest.mark.parametrize("satno", [_SATNO, 25544])
    def test_without_a_matching_analysis_it_says_run_pol_first(
        self, client: Any, auth_cookie: str, state: Any, analysis: PolAnalysis, satno: int,
    ) -> None:
        state.last_pol_analysis = analysis if satno != _SATNO else None
        page = _post(client, auth_cookie, "/pol/reserve-reset", {"satno": str(satno), "reset_date": "2025-06-01"})
        assert page == f'<p class="error-msg">{_NO_ANALYSIS}</p>'

    def test_an_unreadable_date_is_echoed_escaped(self, client: Any, auth_cookie: str, analysed: Any) -> None:
        resp = client.post(
            "/pol/reserve-reset", data={"satno": str(_SATNO), "reset_date": "<b>soon</b>"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        assert "<b>" not in resp.text
        assert 'Could not read "&lt;b&gt;soon&lt;/b&gt;" as a date. Use YYYY-MM-DD.' in resp.text
        assert analysed.pol_reserve_resets == {}

    def test_a_date_is_recorded_as_utc_midnight_and_logged(self, client: Any, auth_cookie: str, analysed: Any) -> None:
        _post(client, auth_cookie, "/pol/reserve-reset", {"satno": str(_SATNO), "reset_date": "2025-06-01T08:00"})
        assert analysed.pol_reserve_resets == {_SATNO: datetime(2025, 6, 1, tzinfo=UTC)}
        assert analysed.log_entries[-1] == f"[POL] Reserve reset for {_SATNO} set to 2025-06-01"

    def test_a_blank_date_clears_the_reset(self, client: Any, auth_cookie: str, analysed: Any) -> None:
        analysed.pol_reserve_resets = "not a mapping"
        _post(client, auth_cookie, "/pol/reserve-reset", {"satno": str(_SATNO), "reset_date": "2025-06-01"})
        _post(client, auth_cookie, "/pol/reserve-reset", {"satno": str(_SATNO), "reset_date": "  "})
        assert analysed.pol_reserve_resets == {}
        assert analysed.log_entries[-1] == f"[POL] Reserve reset for {_SATNO} cleared"


def _epoch(analysis: PolAnalysis) -> str:
    return analysis.manoeuvres[0].epoch.strftime("%Y-%m-%dT%H:%M:%S")


class TestMonteCarlo:
    @pytest.fixture
    def run(self, client: Any, auth_cookie: str) -> Any:
        """Post one Monte Carlo request for the manoeuvre at *epoch* and return the page."""
        def run(epoch: str, **extra: str) -> str:
            return _post(client, auth_cookie, "/pol/monte-carlo", {"satno": str(_SATNO), "manoeuvre_epoch": epoch, **extra})
        return run

    @pytest.mark.parametrize("satno", [_SATNO, 25544])
    def test_without_a_matching_analysis_it_says_run_pol_first(
        self, client: Any, auth_cookie: str, state: Any, analysis: PolAnalysis, satno: int,
    ) -> None:
        """Another object's analysis is no analysis: the run would model the wrong satellite."""
        state.last_pol_analysis = analysis if satno != _SATNO else None
        page = _post(client, auth_cookie, "/pol/monte-carlo", {"satno": str(satno), "manoeuvre_epoch": _epoch(analysis)})
        assert page == f'<p class="error-msg">{_NO_ANALYSIS}</p>'

    def test_an_unknown_epoch_is_named_escaped(self, client: Any, auth_cookie: str, analysed: Any) -> None:
        resp = client.post(
            "/pol/monte-carlo", data={"satno": str(_SATNO), "manoeuvre_epoch": "<i>1999</i>"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        assert "Manoeuvre at &lt;i&gt;1999&lt;/i&gt; not found in PoL results." in resp.text

    @pytest.mark.parametrize(("asked", "used"), [("5", 50), ("10000", 2000)])
    def test_the_sample_count_is_clamped_and_the_run_rendered(
        self, run: Any, analysed: Any, monkeypatch: pytest.MonkeyPatch, asked: str, used: int,
    ) -> None:
        from spectre.astro import monte_carlo

        real = monte_carlo.hypothesis_from_tle_record
        asked_for: list[tuple[int, str]] = []

        def counted(*args: Any, **kwargs: Any) -> Any:
            asked_for.append((kwargs["n_samples"], kwargs["archetype_override"]))
            return real(*args, **{**kwargs, "n_samples": 50})

        monkeypatch.setattr(monte_carlo, "hypothesis_from_tle_record", counted)
        page = run(_epoch(analysed.last_pol_analysis), n_samples=asked, horizon_h="1", manoeuvre_type="plane_change")
        assert asked_for == [(used, "plane_change")], "the sample count or the operator's archetype was not used"
        assert "Monte Carlo failed" not in page
        assert "1h horizon" in page
        assert f"Manoeuvre: {analysed.last_pol_analysis.manoeuvres[0].epoch:%Y-%m-%d}" in page

    def test_a_failed_run_keeps_its_detail_in_the_log(
        self, run: Any, analysed: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.astro import monte_carlo

        def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError(_MARKER)

        monkeypatch.setattr(monte_carlo, "hypothesis_from_tle_record", broken)
        with caplog.at_level(logging.ERROR, logger=_LOGGER):
            page = run(_epoch(analysed.last_pol_analysis))
        assert page == '<p class="error-msg">Monte Carlo failed; the server log has the detail.</p>'
        assert _MARKER in caplog.text


class TestChartData:
    @pytest.mark.parametrize("satno", [_SATNO, 25544])
    def test_without_a_matching_analysis_it_answers_404(
        self, client: Any, auth_cookie: str, state: Any, analysis: PolAnalysis, satno: int,
    ) -> None:
        """Another object's analysis is no analysis: its chart would carry the wrong satellite's burns."""
        state.last_pol_analysis = analysis if satno != _SATNO else None
        resp = client.get(f"/pol/chart-data/{satno}", cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 404
        assert resp.json() == {"error": "No PoL analysis available"}

    def test_an_analysed_object_has_its_charts(
        self, client: Any, auth_cookie: str, analysed: Any, analysis: PolAnalysis,
    ) -> None:
        resp = client.get(f"/pol/chart-data/{_SATNO}", cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 200
        body = resp.json()
        assert body["elements"]["epochs"] == analysis.chart_epochs
        assert body["manoeuvres"]["epochs"] == analysis.manoeuvre_epochs
        # The assessment labels all three burns "altitude change", which the
        # legend reads as repositioning, drawn red. "unknown" grey on every bar
        # is what a chart reading the wrong list of manoeuvres would show.
        assert [v.classification for v in assess_pattern_of_life(analysis).manoeuvres] == ["altitude change"] * 3
        assert body["manoeuvres"]["types"] == ["repositioning"] * 3
        assert body["manoeuvres"]["colors"] == ["#ef4444"] * 3

    def test_the_statistics_are_metres_per_second(
        self, client: Any, auth_cookie: str, analysed: Any, analysis: PolAnalysis,
    ) -> None:
        stats = client.get(f"/pol/chart-data/{_SATNO}", cookies={"spectre_session": auth_cookie}).json()["stats"]
        assert analysis.dv_stats is not None
        assert stats["dv_mean_m_s"] == pytest.approx(analysis.dv_stats.mean * 1000.0)
        assert stats["dv_mean_m_s"] == pytest.approx(13.6, abs=0.1), "a km/s figure reached the chart"
        assert stats["dv_2sigma_high_m_s"] == pytest.approx(analysis.pol_high_dv * 1000.0)
        assert stats["dv_2sigma_high_m_s"] == pytest.approx(13.8, abs=0.1), "a km/s figure reached the chart"


class TestTheChartTypes:
    """Each bar takes its type from the same assessment the manoeuvre table reads."""

    @pytest.mark.parametrize(("classification", "chart_type"), [
        ("station keeping", "station_keeping"), ("plane change", "plane_change"),
        ("relocation", "repositioning"), ("graveyard disposal", "repositioning"), ("", "unknown"),
    ])
    def test_the_label_maps_to_the_legend(self, classification: str, chart_type: str) -> None:
        assert pol._chart_type(classification) == chart_type


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    held = notso_cache.NotsoCache(path=tmp_path / "notso.json")
    monkeypatch.setattr(notso_cache, "get_notso_cache", lambda: held)
    return held


class TestNotso:
    def test_the_panel_counts_the_cached_records_for_the_object(
        self, client: Any, auth_cookie: str, analysed: Any, cache: Any,
    ) -> None:
        cache.append([{"satNo": _SATNO, "msgText": "one"}, {"satNo": _SATNO, "msgText": "two"}])
        resp = client.get("/pol/notso-panel", cookies={"spectre_session": auth_cookie})
        assert "2 cached NOTSO(s) available" in " ".join(resp.text.split())

    def _correlate(self, client: Any, cookie: str, text: str = "") -> str:
        return _post(client, cookie, "/pol/notso-correlate", {"notso_text": text})

    def test_without_an_analysis_it_says_run_pol_first(self, client: Any, auth_cookie: str, state: Any) -> None:
        page = self._correlate(client, auth_cookie, "anything")
        assert "Run Pattern of Life analysis first before correlating NOTSOs." in page

    def test_pasted_text_that_parses_to_nothing_names_the_required_fields(
        self, client: Any, auth_cookie: str, analysed: Any,
    ) -> None:
        page = self._correlate(client, auth_cookie, "nothing here resembles a notice")
        assert "No NOTSO records could be parsed." in page
        assert "SATNO, effective window, and type fields are required" in page

    def test_an_empty_cache_for_the_object_says_to_sync(
        self, client: Any, auth_cookie: str, analysed: Any, cache: Any,
    ) -> None:
        analysed.udl_username, analysed.udl_password = "op", "pw"
        page = self._correlate(client, auth_cookie)
        assert f"No NOTSOs in local cache for SATNO {_SATNO}. Run a cache sync first" in page

    def test_cached_records_that_parse_to_nothing_are_counted(
        self, client: Any, auth_cookie: str, analysed: Any, cache: Any,
    ) -> None:
        analysed.udl_username, analysed.udl_password = "op", "pw"
        cache.append([{"satNo": _SATNO, "msgText": "garbled"}, {"satNo": _SATNO, "msgText": "also garbled"}])
        page = self._correlate(client, auth_cookie)
        assert f"Cache has 2 record(s) for SATNO {_SATNO} but none could be parsed." in page

    def test_a_failed_correlation_keeps_its_detail_in_the_log(
        self, client: Any, auth_cookie: str, analysed: Any,
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(pol, "_load_notsos", lambda *_a: (["n"], [], "pasted text"))

        def broken(*_a: Any) -> None:
            raise RuntimeError(_MARKER)

        monkeypatch.setattr(pol, "notso_behaviour_profile", broken)
        with caplog.at_level(logging.ERROR, logger=_LOGGER):
            page = self._correlate(client, auth_cookie, "x")
        assert page == '<p class="error-msg">NOTSO correlation failed; the server log has the detail.</p>'
        assert _MARKER in caplog.text


_CSV_HEADER = "epoch_utc,apparent_magnitude"


def _csv(rows: int) -> str:
    return "\n".join([_CSV_HEADER] + [f"2026-01-{day:02d}T00:00:00Z,{8.0 + day * 0.01:.2f}" for day in range(1, rows + 1)])


class TestPhotometry:
    def _analyse(self, client: Any, cookie: str, csv_text: str) -> str:
        return _post(client, cookie, "/pol/photometry-analyse", {"csv_text": csv_text})

    def test_the_panel_names_the_analysed_object(self, client: Any, auth_cookie: str, analysed: Any) -> None:
        resp = client.get("/pol/photometry-panel", cookies={"spectre_session": auth_cookie})
        assert f"SATNO <strong>{_SATNO}</strong>" in " ".join(resp.text.split())

    def test_a_blank_csv_names_the_columns_it_needs(self, client: Any, auth_cookie: str, state: Any) -> None:
        page = self._analyse(client, auth_cookie, "   ")
        assert "Paste a CSV with at least epoch_utc and apparent_magnitude columns." in page

    def test_fewer_than_five_observations_are_counted(self, client: Any, auth_cookie: str, state: Any) -> None:
        assert "Need at least 5 valid observations, got 3." in self._analyse(client, auth_cookie, _csv(3))

    def test_a_run_against_the_analysis_is_corroborated_and_logged_with_its_satno(
        self, client: Any, auth_cookie: str, analysed: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A brightness change beside a detected burn is evidence for it, so the burns go in."""
        from spectre.astro import photometry

        real = photometry.assess_photometry
        given: list[list[Any]] = []

        def corroborated(*args: Any, **kwargs: Any) -> Any:
            given.append(kwargs["manoeuvres"])
            return real(*args, **kwargs)

        monkeypatch.setattr(photometry, "assess_photometry", corroborated)
        self._analyse(client, auth_cookie, _csv(12))
        assert len(given) == 1
        assert all(m in given[0] for m in analysed.last_pol_analysis.manoeuvres), "the detected burns were not offered"
        assert analysed.log_entries[-1].startswith(f"[Photometry] Analysed 12 obs for SATNO {_SATNO}: ")

    def test_a_failed_analysis_keeps_its_detail_in_the_log(
        self, client: Any, auth_cookie: str, state: Any,
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.astro import photometry

        def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError(_MARKER)

        monkeypatch.setattr(photometry, "assess_photometry", broken)
        with caplog.at_level(logging.ERROR, logger=_LOGGER):
            page = self._analyse(client, auth_cookie, _csv(6))
        assert page == '<p class="error-msg">Photometry analysis failed; the server log has the detail.</p>'
        assert _MARKER in caplog.text
