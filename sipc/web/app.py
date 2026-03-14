"""FastAPI application factory for SIPC web console."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sipc.config.settings import get_settings
from sipc.web.database import init_db
from sipc.web.routes.login import router as login_router
from sipc.web.routes.maneuver import router as maneuver_router
from sipc.web.routes.operator import router as operator_router
from sipc.web.routes.udl import router as udl_router

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

app = FastAPI(title="SIPC — Space Intercept Planning Console", version="0.3.0")

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(login_router)
app.include_router(operator_router)
app.include_router(udl_router)
app.include_router(maneuver_router)


@app.on_event("startup")
async def _startup() -> None:
    """Initialise database tables and bootstrap admin user on first run."""
    settings = get_settings()
    numeric_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    await init_db()
