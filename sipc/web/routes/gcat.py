"""GCAT — General Catalog of Artificial Space Objects web routes.
=================================================================
Downloads, caches (in-memory, per-process), and serves 28 public TSV
datasets from Jonathan C. McDowell's GCAT
(https://planet4589.org/space/gcat/, CC-BY licence).

Architecture
------------
  GET  /gcat/panel            Returns the panel skeleton INSTANTLY.
                              No network requests to planet4589.org are made here.
  GET  /gcat/table?dataset=X  Downloads dataset X on first call (~2-5s),
                              subsequent calls served from cache in <50ms.
  POST /gcat/refresh          Clears cache, re-downloads all 28 datasets
                              (concurrent thread-pool), returns fresh panel.

Logging
-------
  INFO  — download success (label, rows, cols, timing), every table request
  WARN  — empty or malformed response, unknown column
  ERROR — download failure, parse error

Citation: data from GCAT (J. McDowell, planet4589.org/space/gcat)
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from sipc.web.auth import require_login
from sipc.web.deps import render
from sipc.web.models import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gcat", tags=["gcat"])

BASE_URL = "https://planet4589.org/space/gcat"
PAGE_SIZE = 100
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="gcat-dl")

# ── Dataset registry ──────────────────────────────────────────────────────────
DATASETS: dict[str, dict[str, str]] = {
    # Derived — most operationally valuable first
    "currentcat": {
        "label": "Current Catalog",
        "url": f"{BASE_URL}/tsv/derived/currentcat.tsv",
        "category": "derived",
        "desc": "Current status of every tracked object — the primary operational reference for disposition, type, and state.",
    },
    "launchlog": {
        "label": "Launch Log",
        "url": f"{BASE_URL}/tsv/derived/launchlog.tsv",
        "category": "derived",
        "desc": "Orbital launch log with full payload manifest for every launch since Sputnik.",
    },
    "active": {
        "label": "Active Catalog",
        "url": f"{BASE_URL}/tsv/derived/active.tsv",
        "category": "derived",
        "desc": "Currently operational payloads — confirmed active or presumed active.",
    },
    "geotab": {
        "label": "Geosync Catalog",
        "url": f"{BASE_URL}/tsv/derived/geotab.tsv",
        "category": "derived",
        "desc": "GEO/GSO objects with on-station longitude and drift-rate data.",
    },
    "launch": {
        "label": "Full Launches",
        "url": f"{BASE_URL}/tsv/launch/launch.tsv",
        "category": "derived",
        "desc": "Complete per-launch record for all orbital attempts including vehicle family, site, and outcome.",
    },
    # Object catalogs
    "satcat": {
        "label": "SatCat",
        "url": f"{BASE_URL}/tsv/cat/satcat.tsv",
        "category": "object",
        "desc": "Standard satellite catalog — US Space Force–tracked objects with NORAD designations.",
    },
    "auxcat": {
        "label": "AuxCat",
        "url": f"{BASE_URL}/tsv/cat/auxcat.tsv",
        "category": "object",
        "desc": "Auxiliary catalog of objects not formally tracked by US Space Force.",
    },
    "ftocat": {
        "label": "FtoCat",
        "url": f"{BASE_URL}/tsv/cat/ftocat.tsv",
        "category": "object",
        "desc": "Failed-to-orbit objects — payloads that did not achieve intended orbit.",
    },
    "ecat": {
        "label": "EventCat",
        "url": f"{BASE_URL}/tsv/cat/ecat.tsv",
        "category": "object",
        "desc": "Event catalog — phase changes including dockings, manoeuvres, and reentries.",
    },
    "deepcat": {
        "label": "DeepCat",
        "url": f"{BASE_URL}/tsv/cat/deepcat.tsv",
        "category": "object",
        "desc": "Deep space objects on escape or highly elliptical trajectories.",
    },
    "hcocat": {
        "label": "HelioCat",
        "url": f"{BASE_URL}/tsv/cat/hcocat.tsv",
        "category": "object",
        "desc": "Heliocentric orbit register — objects orbiting the Sun.",
    },
    "lprcat": {
        "label": "LunarPlanetCat",
        "url": f"{BASE_URL}/tsv/cat/lprcat.tsv",
        "category": "object",
        "desc": "Lunar and planetary orbit register.",
    },
    "landercat": {
        "label": "LanderCat",
        "url": f"{BASE_URL}/tsv/cat/landercat.tsv",
        "category": "object",
        "desc": "Lunar and planetary landings and impact events.",
    },
    "tmpcat": {
        "label": "TmpCat",
        "url": f"{BASE_URL}/tsv/cat/tmpcat.tsv",
        "category": "object",
        "desc": "Temporary catalog — objects pending permanent assignment.",
    },
    # Payload catalogs
    "psatcat": {
        "label": "PayloadSatCat",
        "url": f"{BASE_URL}/tsv/cat/psatcat.tsv",
        "category": "payload",
        "desc": "Payload metadata for SatCat: category, civil/military/commercial, end-of-life.",
    },
    "pauxcat": {
        "label": "PayloadAuxCat",
        "url": f"{BASE_URL}/tsv/cat/pauxcat.tsv",
        "category": "payload",
        "desc": "Payload metadata for auxiliary catalog objects.",
    },
    "pftocat": {
        "label": "PayloadFtoCat",
        "url": f"{BASE_URL}/tsv/cat/pftocat.tsv",
        "category": "payload",
        "desc": "Payload metadata for failed-to-orbit objects.",
    },
    "pdeepcat": {
        "label": "PayloadDeepCat",
        "url": f"{BASE_URL}/tsv/cat/pdeepcat.tsv",
        "category": "payload",
        "desc": "Payload metadata for deep space objects.",
    },
    # Supporting reference tables
    "orgs": {
        "label": "Organisations",
        "url": f"{BASE_URL}/tsv/tables/orgs.tsv",
        "category": "supporting",
        "desc": "Countries, agencies, companies, operators, owners, and manufacturers.",
    },
    "sites": {
        "label": "Launch Sites",
        "url": f"{BASE_URL}/tsv/tables/sites.tsv",
        "category": "supporting",
        "desc": "Launch origin sites and cosmodromes with geographic coordinates.",
    },
    "lp": {
        "label": "Launch Points",
        "url": f"{BASE_URL}/tsv/tables/lp.tsv",
        "category": "supporting",
        "desc": "Individual launch pads and positions within each site.",
    },
    "platforms": {
        "label": "Platforms",
        "url": f"{BASE_URL}/tsv/tables/platforms.tsv",
        "category": "supporting",
        "desc": "Mobile launch platforms — ships, aircraft, and mobile erector-launchers.",
    },
    "family": {
        "label": "LV Families",
        "url": f"{BASE_URL}/tsv/tables/family.tsv",
        "category": "supporting",
        "desc": "Launch vehicle family groupings and taxonomic hierarchy.",
    },
    "lv": {
        "label": "Launch Vehicles",
        "url": f"{BASE_URL}/tsv/tables/lv.tsv",
        "category": "supporting",
        "desc": "Launch vehicle type definitions with performance data.",
    },
    "stages": {
        "label": "LV Stages",
        "url": f"{BASE_URL}/tsv/tables/stages.tsv",
        "category": "supporting",
        "desc": "Rocket stage specifications with mass and propellant data.",
    },
    "engines": {
        "label": "Engines",
        "url": f"{BASE_URL}/tsv/tables/engines.tsv",
        "category": "supporting",
        "desc": "Rocket engine catalog with thrust, Isp, and propellant type.",
    },
    "refs": {
        "label": "References",
        "url": f"{BASE_URL}/tsv/tables/refs.tsv",
        "category": "supporting",
        "desc": "Citation sources for launch times and orbital parameters.",
    },
    "worlds": {
        "label": "Worlds",
        "url": f"{BASE_URL}/tsv/worlds/worlds.tsv",
        "category": "supporting",
        "desc": "Solar system bodies used as central bodies for orbital reference frames.",
    },
}

CATEGORIES: dict[str, dict[str, str]] = {
    "derived": {
        "label": "Derived",
        "color": "gold",
        "title": "Derived Catalogs",
        "desc": "Operationally-derived views of the complete tracked-object catalog",
    },
    "object": {
        "label": "Objects",
        "color": "blue",
        "title": "Object Catalogs",
        "desc": "Raw tracked-object records organised by orbital regime",
    },
    "payload": {
        "label": "Payloads",
        "color": "amber",
        "title": "Payload Catalogs",
        "desc": "Mission and payload metadata overlays for object catalog entries",
    },
    "supporting": {
        "label": "Supporting",
        "color": "green",
        "title": "Supporting Tables",
        "desc": "Reference tables for organisations, launch vehicles, and sites",
    },
}

# ── In-memory cache ───────────────────────────────────────────────────────────
_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_FETCH_TIME: datetime | None = None
_FETCHING: bool = False
_FETCH_ERRORS: list[str] = []


# ── TSV fetcher (sync — runs in ThreadPoolExecutor) ───────────────────────────

def _fetch_one(key: str, meta: dict[str, str]) -> tuple[str, pd.DataFrame | None]:
    """Download and parse one GCAT TSV.  Returns (key, df) or (key, None)."""
    url = meta["url"]
    label = meta["label"]
    log.info("[GCAT] ↓  %-24s  %s", label, url)
    t0 = time.perf_counter()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SIPC-GCAT/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — URL from hardcoded GCAT table, not user input
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("[GCAT] ✗  FAILED %-20s: %s", label, exc)
        return key, None

    lines = [ln for ln in raw.split("\n") if ln.strip() and not ln.startswith("# ")]
    if not lines:
        log.warning("[GCAT] ⚠  Empty response for %s", label)
        return key, None

    header = lines[0].lstrip("#").strip()
    tsv_text = header + "\n" + "\n".join(lines[1:])

    try:
        df = pd.read_csv(
            io.StringIO(tsv_text),
            sep="\t",
            dtype=str,
            on_bad_lines="skip",
            low_memory=False,
        )
    except Exception as exc:
        log.error("[GCAT] ✗  Parse error %-20s: %s", label, exc)
        return key, None

    df.columns = [c.strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    df = df.fillna("")

    elapsed = time.perf_counter() - t0
    log.info("[GCAT] ✓  %-24s  %6d rows × %3d cols  (%.2fs)", label, len(df), len(df.columns), elapsed)
    return key, df


# ── Bulk async downloader (used by /refresh only) ─────────────────────────────

async def _load_all() -> None:
    """Concurrently download all 28 GCAT datasets into _CACHE.
    Called only by the manual Refresh endpoint — never blocks panel load.
    """
    global _FETCHING, _CACHE_FETCH_TIME, _FETCH_ERRORS
    if _FETCHING:
        log.info("[GCAT] Refresh already running — skipping duplicate")
        return

    _FETCHING = True
    _FETCH_ERRORS = []
    log.info("[GCAT] ══ Starting full refresh (%d datasets) ══", len(DATASETS))
    t_start = time.perf_counter()

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(_EXECUTOR, _fetch_one, key, meta)
        for key, meta in DATASETS.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    loaded = failed = 0
    for result in results:
        if isinstance(result, Exception):
            log.error("[GCAT] gather exception: %s", result)
            _FETCH_ERRORS.append(str(result))
            failed += 1
            continue
        key, df = result
        if df is not None:
            _CACHE[key] = {
                "df": df,
                "fetched_at": datetime.now(UTC),
                "rows": len(df),
                "cols": len(df.columns),
                "columns": list(df.columns),
            }
            loaded += 1
        else:
            _FETCH_ERRORS.append(f"failed: {DATASETS[key]['label']}")
            failed += 1

    _CACHE_FETCH_TIME = datetime.now(UTC)
    _FETCHING = False
    total_rows = sum(v["rows"] for v in _CACHE.values())
    elapsed = time.perf_counter() - t_start
    log.info(
        "[GCAT] ══ Refresh done: %d loaded / %d failed / %d total rows (%.1fs) ══",
        loaded, failed, total_rows, elapsed,
    )


# ── Shared helpers ────────────────────────────────────────────────────────────

def _panel_context() -> dict[str, Any]:
    """Build common context dict for gcat_panel.html."""
    gcat_total_rows = sum(v["rows"] for v in _CACHE.values())
    return {
        "datasets": DATASETS,
        "categories": CATEGORIES,
        "cache_rows": {k: v["rows"] for k, v in _CACHE.items()},
        "cat_counts": {
            cat: sum(1 for ds in DATASETS.values() if ds["category"] == cat)
            for cat in CATEGORIES
        },
        "gcat_total_rows": gcat_total_rows,
        "loaded_count": len(_CACHE),
        "total_count": len(DATASETS),
        "last_updated": (
            _CACHE_FETCH_TIME.strftime("%Y-%m-%d %H:%M UTC")
            if _CACHE_FETCH_TIME else "—"
        ),
        "fetch_errors": _FETCH_ERRORS,
        "fetching": _FETCHING,
    }


def _page_data(
    key: str,
    page: int = 1,
    q: str = "",
    sort: str = "",
    asc: int = 1,
) -> dict[str, Any] | None:
    """Return paginated table context for one dataset.  Returns None if not cached."""
    cached = _CACHE.get(key)
    if not cached:
        return None

    df: pd.DataFrame = cached["df"].copy()
    total_rows = len(df)

    if q.strip():
        qlo = q.strip().lower()
        mask = (
            df.apply(lambda col: col.astype(str).str.lower().str.contains(qlo, na=False))
            .any(axis=1)
        )
        df = df[mask]
        log.debug("[GCAT] search '%s' on %s: %d → %d rows", q, key, total_rows, len(df))

    filtered_rows = len(df)

    if sort and sort in df.columns:
        try:
            df = df.sort_values(sort, ascending=bool(asc), key=lambda s: s.str.lower())
        except Exception as exc:
            log.warning("[GCAT] sort failed for '%s': %s", sort, exc)
    elif sort:
        log.warning("[GCAT] sort column '%s' not found in %s", sort, key)
        sort = ""

    total_pages = max(1, (filtered_rows + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), total_pages)
    start = (page - 1) * PAGE_SIZE
    page_df = df.iloc[start: start + PAGE_SIZE]

    log.info(
        "[GCAT] table %-14s  q='%s'  sort='%s'  page=%d/%d  rows=%d/%d",
        key, q, sort, page, total_pages, filtered_rows, total_rows,
    )

    return {
        "dataset_key": key,
        "meta": DATASETS.get(key, {}),
        "columns": list(cached["columns"]),
        "rows": [list(row) for _, row in page_df.iterrows()],
        "total_rows": total_rows,
        "filtered_rows": filtered_rows,
        "page": page,
        "total_pages": total_pages,
        "q": q,
        "sort": sort,
        "asc": asc,
        "page_size": PAGE_SIZE,
    }


# ── Route handlers ────────────────────────────────────────────────────────────

@router.get("/panel", response_class=HTMLResponse)
async def gcat_panel(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the GCAT panel skeleton INSTANTLY.

    No network requests to planet4589.org are made here.
    Data loads on demand when the user clicks a dataset in the nav.
    """
    log.info(
        "[GCAT] Panel opened by %s — %d/%d datasets in cache",
        current_user.username, len(_CACHE), len(DATASETS),
    )
    return render(request, "partials/gcat_panel.html", _panel_context())


@router.get("/table", response_class=HTMLResponse)
async def gcat_table(
    request: Request,
    dataset: str = Query("currentcat"),
    page: int = Query(1, ge=1),
    q: str = Query(""),
    sort: str = Query(""),
    asc: int = Query(1),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return a paginated, searchable, sortable table for one dataset.

    Downloads on first access for each dataset key (~2-5s per dataset).
    Subsequent requests for the same key are served from in-memory cache.
    """
    if dataset not in DATASETS:
        log.warning("[GCAT] Unknown dataset key '%s' requested by %s", dataset, current_user.username)
        return HTMLResponse(
            '<div class="gcat-error-state">'
            f'<span class="gcat-error-icon">⚠</span>'
            f'Unknown dataset: <code>{dataset}</code>'
            '</div>',
            status_code=404,
        )

    if dataset not in _CACHE:
        log.info("[GCAT] On-demand download: '%s' for %s", dataset, current_user.username)
        loop = asyncio.get_event_loop()
        _, df_result = await loop.run_in_executor(
            _EXECUTOR, _fetch_one, dataset, DATASETS[dataset]
        )
        if df_result is None:
            label = DATASETS[dataset]["label"]
            return HTMLResponse(
                '<div class="gcat-error-state">'
                f'<span class="gcat-error-icon">✗</span>'
                f'Failed to download <strong>{label}</strong>. '
                'Check your network connection and try again.'
                '</div>'
            )
        _CACHE[dataset] = {
            "df": df_result,
            "fetched_at": datetime.now(UTC),
            "rows": len(df_result),
            "cols": len(df_result.columns),
            "columns": list(df_result.columns),
        }
        log.info("[GCAT] '%s' cached: %d rows", dataset, len(df_result))

    td = _page_data(dataset, page=page, q=q, sort=sort, asc=asc)
    if td is None:
        return HTMLResponse('<div class="gcat-error-state">Dataset unavailable.</div>')

    return render(request, "partials/gcat_table.html", td)


@router.post("/refresh", response_class=HTMLResponse)
async def gcat_refresh(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear the in-memory cache and re-download all 28 GCAT datasets.

    This is the slow path (~10-30s). Use it intentionally via the Refresh button.
    Returns a fresh panel HTML on completion.
    """
    global _CACHE_FETCH_TIME
    log.info(
        "[GCAT] ══ Manual refresh by %s — clearing %d cached datasets ══",
        current_user.username, len(_CACHE),
    )
    _CACHE.clear()
    _CACHE_FETCH_TIME = None
    await _load_all()

    log.info(
        "[GCAT] Refresh complete for %s — %d datasets, %d total rows",
        current_user.username, len(_CACHE), sum(v["rows"] for v in _CACHE.values()),
    )
    return render(request, "partials/gcat_panel.html", _panel_context())
