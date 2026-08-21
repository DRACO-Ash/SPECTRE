"""Integration tests for the intercept CSV export route.

This is a data-egress path: it authenticates, reads per-operator session state
and streams it to the browser. It must never serve another operator's history,
and it must remain importable without reshaping.
"""

from __future__ import annotations

import csv
import io

_EXPECTED_COLUMNS = [
    "run_id", "method", "red_name", "blue_name", "total_dv_km_s", "arrival_utc",
    "miss_km", "n_burns", "burn_num", "segment", "burn_epoch_utc", "burn_dv_km_s",
    "dv_prograde", "dv_normal", "dv_radial", "notes",
]


def _rows(body: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body)))


class TestExportAccessControl:
    def test_requires_authentication(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient

        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/plan/export", follow_redirects=False)
            assert resp.status_code == 302
            assert "/login" in resp.headers["location"]


class TestExportShape:
    def test_returns_csv_with_download_headers(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export", cookies={"spectre_session": auth_cookie}
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        assert ".csv" in resp.headers["content-disposition"]

    def test_is_not_cached(self, client: object, auth_cookie: str) -> None:
        """Operational history must not linger in an intermediary cache."""
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export", cookies={"spectre_session": auth_cookie}
        )
        assert resp.headers["cache-control"] == "no-store"

    def test_emits_the_documented_column_header(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export", cookies={"spectre_session": auth_cookie}
        )
        rows = _rows(resp.text)
        assert _EXPECTED_COLUMNS in rows, "the column header must be present and unchanged"

    def test_metadata_header_names_the_operator(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export", cookies={"spectre_session": auth_cookie}
        )
        assert "# SPECTRE Intercept Export" in resp.text
        assert "testadmin" in resp.text

    def test_empty_history_still_returns_a_valid_file(
        self, client: object, auth_cookie: str
    ) -> None:
        """A fresh session exports headers, not an error."""
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export", cookies={"spectre_session": auth_cookie}
        )
        assert resp.status_code == 200
        assert _EXPECTED_COLUMNS in _rows(resp.text)


class TestExportFiltering:
    def test_run_id_filter_is_reflected_in_the_metadata(
        self, client: object, auth_cookie: str
    ) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export",
            params={"run_id": "RUN_DOES_NOT_EXIST"},
            cookies={"spectre_session": auth_cookie},
        )
        assert resp.status_code == 200
        assert "RUN_DOES_NOT_EXIST" in resp.text

    def test_run_id_filter_appears_in_the_filename(
        self, client: object, auth_cookie: str
    ) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export",
            params={"run_id": "RUN_ABC123"},
            cookies={"spectre_session": auth_cookie},
        )
        assert "RUN_ABC123" in resp.headers["content-disposition"]

    def test_unknown_run_id_yields_no_data_rows(
        self, client: object, auth_cookie: str
    ) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export",
            params={"run_id": "RUN_DOES_NOT_EXIST"},
            cookies={"spectre_session": auth_cookie},
        )
        rows = [r for r in _rows(resp.text) if r and not r[0].startswith("#")]
        # Only the column header row survives.
        assert rows == [_EXPECTED_COLUMNS]
