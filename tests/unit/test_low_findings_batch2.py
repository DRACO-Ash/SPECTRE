"""Low findings, audit batch 2 (F-241 to F-268). Each test names its finding."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_WEB = _ROOT / "spectre" / "web"


def _source(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def _render(template: str, **context: object) -> str:
    from spectre.web.app import templates

    return templates.env.get_template(template).render(**context)


def _hx_vals(rendered: str) -> list[dict[str, object]]:
    return [json.loads(raw) for raw in re.findall(r"hx-vals='([^']*)'", rendered)]


class TestF241OneTleLookupAndOneDominantAxis:
    """Three routes kept their own _find_tle, and two their own dominant-axis rule."""

    def test_no_route_keeps_its_own_tle_lookup(self) -> None:
        offenders = [p.name for p in (_WEB / "routes").glob("*.py") if "def _find_tle" in p.read_text("utf-8")]
        assert not offenders, f"private TLE lookups remain in {offenders}"

    def test_the_session_lookup_finds_blue_and_red_and_misses_cleanly(self) -> None:
        from spectre.domain.models import BlueAsset, RedTrack
        from spectre.web.planning_state import SessionState

        state = SessionState()
        state.blue_assets.append(BlueAsset(name="A", tle="blue-tle"))
        state.red_tracks.append(RedTrack(name="B", tle="red-tle"))
        assert state.tle_of(state.blue_assets[0].stk_name) == "blue-tle"
        assert state.tle_of(state.red_tracks[0].stk_name) == "red-tle"
        assert state.tle_of("nobody") is None

    def test_the_dominant_axis_rule_lives_in_one_place(self) -> None:
        for route in ("maneuver.py", "threat.py"):
            text = (_WEB / "routes" / route).read_text("utf-8")
            assert "def _dominant_axis" not in text and "_DOMINANT_AXIS_FRACTION =" not in text, route


class TestF242LoadButtonStagesTheBurnNotTheArrival:
    def test_the_load_button_takes_the_first_burn_epoch(self) -> None:
        text = (_WEB / "templates" / "partials" / "all_intercepts_result.html").read_text("utf-8")
        line = next(ln for ln in text.splitlines() if "data-epoch=" in ln)
        assert "burns[0].burn_epoch" in line, line


class TestF243ExceptionTextIsLogSafe:
    def test_solver_and_clustering_failures_go_through_log_safe(self) -> None:
        assert "log_safe(exc)" in (_WEB / "routes" / "maneuver.py").read_text("utf-8")
        assert "log_safe(_cl_exc)" in (_WEB / "routes" / "threat.py").read_text("utf-8")


class TestF244DeadPartialsAreGone:
    @pytest.mark.parametrize("name", ["maneuver_status.html", "osint_card.html", "trade_space_chart.html"])
    def test_unreferenced_partial_removed(self, name: str) -> None:
        assert not (_WEB / "templates" / "partials" / name).exists()


class TestF245UnknownRegimeIsNotCalledFiltered:
    def test_a_none_regime_says_the_list_is_unfiltered(self) -> None:
        out = _render(
            "partials/sweep_target_config.html",
            has_hrr=True, has_udl=False, blue_hrr={1: 1}, red_hrr={}, interceptor_regime=None,
            interceptor_name="RED_X", manual_tles=[],
        )
        assert "Regime unknown" in out
        assert "Regime: <strong" not in out


class TestF246AndF256HxValsAreJson:
    _NASTY = 'A "quoted" name\'s </p>'

    def test_manual_tle_remove_button(self) -> None:
        out = _render("partials/sweep_manual_tles.html", manual_tles=[{"name": self._NASTY, "tle": "", "confidence": ""}], error=None)
        assert {"manual_name": self._NASTY} in _hx_vals(out)

    def test_hrr_buttons_carry_valid_json(self) -> None:
        sat = {"satno": 25544, "name": self._NASTY, "rank": 1}
        out = _render(
            "partials/hrr_panel.html",
            hrr_blue=[sat], hrr_red=[sat], error=None,
        )
        values = _hx_vals(out)
        assert len(values) == 4, values
        assert all(v["satno"] == 25544 and v["name"] == self._NASTY for v in values)

    def test_catalogue_buttons_carry_valid_json(self) -> None:
        out = _render("partials/catalog_results.html", status="ok", q="x", results=[{"satno": 25544, "name": "X"}])
        assert _hx_vals(out) == [{"satno": 25544}, {"satno": 25544}]


class TestF247GcatHostIsPinned:
    @pytest.mark.parametrize("url", [
        "https://evil.example/space/gcat/x.tsv",
        "https://10.0.0.5/x.tsv",
        "https://127.0.0.1/x.tsv",
        "https://169.254.169.254/latest/meta-data/",
    ])
    def test_off_host_https_is_refused(self, url: str) -> None:
        from spectre.web.routes import gcat

        refusal = gcat._url_refusal(url)
        assert refusal is not None and "allowlist" in refusal

    def test_the_real_host_is_allowed(self) -> None:
        from spectre.web.routes import gcat

        assert gcat._url_refusal(f"{gcat.BASE_URL}/tsv/derived/currentcat.tsv") is None


class TestF248StateVectorIsTheNewest:
    def test_newest_record_wins_and_a_single_object_is_accepted(self) -> None:
        from spectre.web.routes.udl import _newest_state_vector

        old = {"epoch": "2026-10-01T00:00:00.000000Z", "referenceFrame": "J2000"}
        new = {"epoch": "2026-10-25T00:00:00.000000Z", "referenceFrame": "J2000"}
        assert _newest_state_vector([new, old]) is new
        assert _newest_state_vector([old, new]) is new
        assert _newest_state_vector(new) is new
        assert _newest_state_vector([]) is None
        assert _newest_state_vector("junk") is None

    def test_the_query_is_bounded_and_no_frame_is_guessed(self) -> None:
        text = (_WEB / "routes" / "udl.py").read_text("utf-8")
        assert ">2020-01-01" not in text
        assert 'rec.get("referenceFrame", "J2000")' not in text


class TestF249SyncStatusIsEscaped:
    def test_error_and_warning_text_is_escaped(self) -> None:
        from spectre.web.routes.udl import _notso_sync_status

        class _Cache:
            def total_records(self) -> int:
                return 0

            def last_sync_utc(self) -> str:
                return "never"

        for added in (0, 1):
            out = _notso_sync_status(added, ["<script>alert(1)</script>"], _Cache())
            assert "<script>" not in out and "&lt;script&gt;" in out


class TestF250NoUnreachableStatusHandler:
    def test_udl_login_has_no_dead_http_status_branch(self) -> None:
        import inspect

        from spectre.web.routes import udl

        src = inspect.getsource(udl.udl_login)
        assert ".raise_for_status()" not in src and "except httpx.HTTPStatusError" not in src


class TestF251UdlPasswordAsTyped:
    def test_template_and_route(self) -> None:
        tmpl = (_WEB / "templates" / "partials" / "pol_panel.html").read_text("utf-8")
        assert 'name="udl_pass" autocomplete="off"' in tmpl
        assert "udl_pass.strip()" not in (_WEB / "routes" / "pol.py").read_text("utf-8")


class TestF252OneUdlBase:
    def test_the_literal_appears_once(self) -> None:
        hits = [p for p in (_ROOT / "spectre").rglob("*.py") if '"https://unifieddatalibrary.com/udl"' in p.read_text("utf-8")]
        assert [p.name for p in hits] == ["settings.py"]


class TestF253HistoryDocstring:
    def test_names_all_four_returns(self) -> None:
        from spectre.web.routes.pol import _fetch_udl_history

        assert "sat_name" in (_fetch_udl_history.__doc__ or "")


class TestF254GcatDownloadIsCapped:
    def test_a_body_past_the_cap_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        from spectre.web.routes import gcat

        monkeypatch.setattr(gcat, "_MAX_TSV_BYTES", 10)
        assert gcat._read_capped(httpx.Response(200, content=b"x" * 11), "T") is None
        assert gcat._read_capped(httpx.Response(200, content=b"x" * 10), "T") == b"x" * 10

    def test_page_request_does_not_copy_the_table(self) -> None:
        assert '["df"].copy()' not in (_WEB / "routes" / "gcat.py").read_text("utf-8")


class TestF255UdlTimes:
    def test_created_at_is_always_aware(self) -> None:
        from spectre.web.routes.udl import _parse_created_at

        naive = _parse_created_at({"createdAt": "2026-10-01T12:00:00"})
        offset = _parse_created_at({"createdAt": "2026-10-01T13:00:00+01:00"})
        assert naive.tzinfo is not None and naive == offset
        assert max([naive, _parse_created_at({"createdAt": "2026-10-02T00:00:00Z"})]).day == 2

    @pytest.mark.parametrize("day", ["000.5", "367.5"])
    def test_day_of_year_out_of_range_is_refused(self, day: str) -> None:
        from spectre.web.routes.udl import _parse_tle_epoch

        line1 = f"1 25544U 98067A   26{day:>12}  .00016717  00000-0  10270-3 0  9994"
        assert _parse_tle_epoch(line1) is None


class TestF259OneSessionLifetime:
    def test_cookie_age_is_the_token_age(self) -> None:
        from spectre.web import auth
        from spectre.web.routes import login

        assert login._SESSION_COOKIE_MAX_AGE is auth._SESSION_MAX_AGE
        assert "28_800" not in (_WEB / "routes" / "login.py").read_text("utf-8")


class TestF260Docstrings:
    def test_rate_limit_docstring_names_the_login_tiers(self) -> None:
        from spectre.web import rate_limit

        assert "login" in (rate_limit.__doc__ or "").lower()

    def test_admin_docstring_does_not_promise_a_rename(self) -> None:
        assert "renamed" not in (_WEB / "routes" / "admin.py").read_text("utf-8")


class TestF262LogSafeNeverExceedsItsLimit:
    @pytest.mark.parametrize("limit", [0, 1, 2, 3, 4, 10])
    def test_bound(self, limit: int) -> None:
        from spectre.web.log_safety import log_safe

        assert len(log_safe("abcdefghijklmnopqrstuvwxyz", limit=limit)) <= limit


class TestF264TrainingQueries:
    def test_no_equality_against_true(self) -> None:
        text = (_WEB / "routes" / "training.py").read_text("utf-8")
        assert "== True" not in text and "E712" not in text


class TestF266ScenarioWindowConvertsOffsets:
    def test_offset_is_converted_not_relabelled(self) -> None:
        from spectre.web.routes.operator import _as_utc

        assert _as_utc(datetime.fromisoformat("2026-01-01T12:00+01:00")) == datetime(2026, 1, 1, 11, tzinfo=UTC)
        assert _as_utc(datetime.fromisoformat("2026-01-01T12:00")) == datetime(2026, 1, 1, 12, tzinfo=UTC)


class TestF267AssetAddIsValidated:
    _TLE = ("1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9999\n"
            "2 25544  51.6420 195.0000 0001207  86.9689 273.1630 15.54320000365490")

    def test_refusals(self) -> None:
        from spectre.web.routes.operator import _add_refusal

        assert _add_refusal("", self._TLE) is not None
        assert _add_refusal("A", "line1\nline2") is not None
        assert _add_refusal("A", self._TLE) is None

    def test_delete_urls_are_encoded(self) -> None:
        for name in ("blue_list.html", "red_list.html"):
            text = (_WEB / "templates" / "partials" / name).read_text("utf-8")
            assert "| urlencode }}" in text, name


class TestF268StaleThemeFilesAreGone:
    @pytest.mark.parametrize("relative", [
        "static/spectre-theme/css/spectre-theme.css",
        "static/favicon.svg",
        "static/spectre_icon_family.svg",
        "static/spectre_icon_mark.svg",
        "static/spectre_logo_primary.svg",
    ])
    def test_removed(self, relative: str) -> None:
        assert not (_WEB / relative).exists()

    def test_readme_points_at_the_loaded_file(self) -> None:
        text = (_WEB / "static" / "spectre-theme" / "README.md").read_text("utf-8")
        assert 'href="css/spectre-theme.css"' not in text


class TestF258RequestsAreLogged:
    def test_access_line_has_the_path_but_not_the_query(self, caplog: pytest.LogCaptureFixture) -> None:
        from fastapi.testclient import TestClient

        from spectre.web.app import app

        with caplog.at_level(logging.INFO, logger="spectre.access"), TestClient(app) as client:
            client.get("/login?secret=hunter2")
        lines = [r.getMessage() for r in caplog.records if r.name == "spectre.access"]
        assert any("/login" in ln for ln in lines), lines
        assert not any("hunter2" in ln for ln in lines)

    def test_the_entrypoint_no_longer_cites_keycloak(self) -> None:
        assert "Keycloak" not in (_WEB / "_entrypoint.py").read_text("utf-8")
