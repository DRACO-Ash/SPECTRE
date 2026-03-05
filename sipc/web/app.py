"""FastAPI application factory for SIPC web console."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sipc.web.database import init_db
from sipc.web.routes.login import router as login_router
from sipc.web.routes.operator import router as operator_router
from sipc.web.routes.udl import router as udl_router

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

app = FastAPI(title="SIPC — STK Intercept Planning Console", version="0.2.0")

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(login_router)
app.include_router(operator_router)
app.include_router(udl_router)


@app.on_event("startup")
async def _startup() -> None:
    """Initialise database tables and bootstrap admin user on first run."""
    await init_db()
