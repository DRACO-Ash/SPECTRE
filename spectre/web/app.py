"""FastAPI application factory for SPECTRE web console."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from spectre import __version__
from spectre.config.settings import (
    get_settings,
    uses_sqlite,
    validate_data_dir,
    validate_secret_key,
    validate_sqlite_support,
)
from spectre.web.csrf import require_csrf
from spectre.web.database import init_db
from spectre.web.health import router as health_router
from spectre.web.planning_state import set_default_hrr_objects
from spectre.web.routes.admin import router as admin_router
from spectre.web.routes.decision import router as decision_router
from spectre.web.routes.gcat import router as gcat_router
from spectre.web.routes.geometry import router as geometry_router
from spectre.web.routes.login import router as login_router
from spectre.web.routes.maneuver import router as maneuver_router
from spectre.web.routes.operator import router as operator_router
from spectre.web.routes.plan import router as plan_router
from spectre.web.routes.pol import router as pol_router
from spectre.web.routes.threat import router as threat_router
from spectre.web.routes.training import router as training_router
from spectre.web.routes.udl import _parse_created_at, parse_hrr_notification
from spectre.web.routes.udl import router as udl_router

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.autoescape = True  # Enforce HTML autoescaping (defence-in-depth against XSS).

# Custom Jinja2 filters
templates.env.filters["urlquote"] = quote_plus  # {{ value | urlquote }} → URL-encoded string
templates.env.filters["enumerate"] = enumerate   # {{ list | enumerate }} → (0, item) pairs


logger = logging.getLogger(__name__)

_HRR_FILENAME = "HRR_List.json"


def _hrr_candidate_paths() -> list[Path]:
    """Return the places HRR_List.json may live, in priority order.

    The operator-supplied copy on the data volume wins, so a deployed instance
    can be given fresh data without rebuilding the image. The source-tree
    location is kept for local development; it does not exist once the package
    is installed into a container.
    """
    return [
        Path(get_settings().data_dir) / _HRR_FILENAME,
        Path(__file__).parent.parent.parent / _HRR_FILENAME,
    ]


def _load_hrr_from_disk() -> None:
    """Parse HRR_List.json into the global default store at startup.

    Picks the newest notification in the file (same selection logic as the
    live UDL fetch) so the pre-loaded data is as current as the cached file.
    Absence is not an error: the threat sweep then requires a UDL login.
    """
    hrr_path = next((p for p in _hrr_candidate_paths() if p.exists()), None)
    if hrr_path is None:
        logger.warning(
            "%s not found in %s — threat sweep will require UDL login",
            _HRR_FILENAME,
            " or ".join(str(p.parent) for p in _hrr_candidate_paths()),
        )
        return
    try:
        with hrr_path.open(encoding="utf-8") as fh:
            parsed: Any = json.load(fh)

        # Validate the shape at the boundary. Well-formed JSON of the wrong
        # shape (an object rather than a list of notifications) would otherwise
        # reach the parser as bare strings and fail the boot.
        if not isinstance(parsed, list):
            logger.error(
                "%s contains %s, expected a list of notifications; ignoring",
                _HRR_FILENAME, type(parsed).__name__,
            )
            return
        notifications: list[dict[str, Any]] = [n for n in parsed if isinstance(n, dict)]
        if not notifications:
            return
        newest = max(notifications, key=_parse_created_at)
        hrr_blue, hrr_red = parse_hrr_notification(newest)
        set_default_hrr_objects(hrr_blue + hrr_red)
        logger.info(
            "HRR pre-load: %d Blue + %d Red = %d satellites from %s",
            len(hrr_blue), len(hrr_red), len(hrr_blue) + len(hrr_red),
            newest.get("createdAt", "unknown date"),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Malformed or unreadable cached data must not stop the boot: the threat
        # sweep falls back to requiring a UDL login. json.JSONDecodeError is a
        # ValueError, so a corrupt file lands here too.
        logger.exception("Failed to pre-load %s", _HRR_FILENAME)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration, then initialise logging, storage and the database.

    Fails closed. A missing or placeholder ``SECRET_KEY``, or a data directory
    that will not accept a write, stops the boot with a named error rather than
    letting the process start in a silently broken or insecure state.
    """
    settings = get_settings()
    numeric_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Fail closed on an unusable signing key before anything can issue a token.
    validate_secret_key(settings.secret_key)

    # Prove storage with a real write and record the verdict exactly once, so a
    # pod that is later killed still leaves a diagnosable narrative in its log.
    resolved_data_dir = validate_data_dir(settings.data_dir)

    # A plain write probe is not proof the store works. An object-storage backed
    # volume accepts a small file write and then fails SQLite's locking, which
    # previously surfaced as "WRITABLE" immediately followed by a disk I/O error
    # partway through table creation. So when the database is SQLite, prove
    # SQLite itself before claiming the storage is usable.
    if uses_sqlite(settings.database_url):
        validate_sqlite_support(resolved_data_dir)
        backend = "SQLite"
    else:
        backend = "external database"
    logger.info(
        "SPECTRE %s boot, storage verdict: USABLE at %s (%s)",
        __version__, resolved_data_dir, backend,
    )

    await init_db()
    _load_hrr_from_disk()
    logger.info("SPECTRE %s ready — listening for requests", __version__)
    yield
    logger.info("SPECTRE %s shutting down", __version__)


app = FastAPI(
    title="SPECTRE — Space Planning, Evaluation & Counter-Threat Response Engine",
    version=__version__,
    lifespan=lifespan,
    dependencies=[Depends(require_csrf)],
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Health first: unauthenticated probe paths the platform calls before any session exists.
app.include_router(health_router)
app.include_router(login_router)
app.include_router(plan_router)
app.include_router(admin_router)
app.include_router(operator_router)
app.include_router(udl_router)
app.include_router(maneuver_router)
app.include_router(threat_router)
app.include_router(pol_router)
app.include_router(gcat_router)
app.include_router(decision_router)
app.include_router(geometry_router)
app.include_router(training_router)
