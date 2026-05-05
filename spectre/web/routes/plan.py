"""Session-level planning utilities — export and summary routes.

Handles cross-cutting concerns that span the maneuver, threat, and asset layers
(intercept history export, future: session report generation).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from spectre.web.auth import require_login
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan")


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
    writer.writerow([f"# SPECTRE Intercept Export — {now_utc} — Operator: {current_user.username}"])
    writer.writerow([f"# Runs: {len(results)}  Filter: {run_id or 'all'}"])
    writer.writerow([])

    writer.writerow([
        "run_id",
        "method",
        "red_name",
        "blue_name",
        "total_dv_km_s",
        "arrival_utc",
        "miss_km",
        "n_burns",
        "burn_num",
        "segment",
        "burn_epoch_utc",
        "burn_dv_km_s",
        "dv_prograde",
        "dv_normal",
        "dv_radial",
        "notes",
    ])

    for r in results:
        common = [
            r.option_id,
            r.method.value,
            r.red_name,
            r.blue_name,
            f"{r.total_delta_v_km_s:.6f}",
            r.arrival_epoch.strftime("%Y-%m-%d %H:%M:%S"),
            f"{r.intercept_range_km:.3f}",
            len(r.burns),
        ]
        if r.burns:
            for b in r.burns:
                writer.writerow([
                    *common,
                    b.burn_number,
                    b.segment_name,
                    b.burn_epoch.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{b.delta_v_km_s:.6f}",
                    f"{b.dv_prograde:.6f}",
                    f"{b.dv_normal:.6f}",
                    f"{b.dv_radial:.6f}",
                    r.notes,
                ])
        else:
            writer.writerow([*common, "", "", "", "", "", "", "", r.notes])

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = (
        f"spectre_intercepts_{run_id}_{timestamp}.csv"
        if run_id
        else f"spectre_intercepts_{timestamp}.csv"
    )

    logger.info(
        "Intercept export: operator=%s rows=%d filter=%s filename=%s",
        current_user.username, len(results), run_id or "all", filename,
    )

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
