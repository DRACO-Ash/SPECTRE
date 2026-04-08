"""Shared FastAPI dependencies and lazy-import helpers for SPECTRE web routes.

All route modules import from here rather than duplicating these helpers.
Lazy imports break the circular dependency that arises because ``app.py``
creates ``templates`` and also imports the routers.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def get_templates() -> Jinja2Templates:
    """Return the Jinja2Templates instance from the application factory.

    The lazy import avoids the circular import that would occur if routes
    imported ``templates`` at module load time (``app.py`` imports routers,
    routers need ``templates`` from ``app.py``).  The object is created once
    at app startup so this is effectively a cached lookup after the first call.
    """
    from spectre.web.app import templates  # noqa: PLC0415

    return templates


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a Jinja2 template with the modern TemplateResponse signature.

    Wraps ``Jinja2Templates.TemplateResponse`` using the non-deprecated
    ``(request, name, context)`` argument order.
    """
    tmpl = get_templates()
    ctx = context or {}
    return cast(HTMLResponse, tmpl.TemplateResponse(request, name, ctx, status_code=status_code))
