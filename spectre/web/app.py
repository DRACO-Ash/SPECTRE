"""FastAPI application factory for SPECTRE web console."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from spectre.config.settings import get_settings
from spectre.web.database import init_db
from spectre.web.planning_state import set_default_hrr_objects
from spectre.web.routes.admin import router as admin_router
from spectre.web.routes.decision import router as decision_router
from spectre.web.routes.gcat import router as gcat_router
from spectre.web.routes.geometry import router as geometry_router
from spectre.web.routes.login import router as login_router
from spectre.web.routes.maneuver import router as maneuver_router
from spectre.web.routes.operator import router as operator_router
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


_HRR_LIST_PATH = Path(__file__).parent.parent.parent / "HRR_List.json"

logger = logging.getLogger(__name__)


def _load_hrr_from_disk() -> None:
    """Parse HRR_List.json into the global default store at startup.

    Picks the newest notification in the file (same selection logic as the
    live UDL fetch) so the pre-loaded data is as current as the cached file.
    """
    if not _HRR_LIST_PATH.exists():
        logger.warning("HRR_List.json not found at %s — threat sweep will require UDL login", _HRR_LIST_PATH)
        return
    try:
        with open(_HRR_LIST_PATH, encoding="utf-8") as fh:
            notifications: list[dict[str, Any]] = json.load(fh)
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
    except Exception as exc:
        logger.error("Failed to pre-load HRR_List.json: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialise database tables, configure logging, and pre-load HRR data."""
    settings = get_settings()
    numeric_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    await init_db()
    _load_hrr_from_disk()
    yield


app = FastAPI(
    title="SPECTRE — Space Planning, Evaluation & Counter-Threat Response Engine",
    version="0.4.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(login_router)
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
