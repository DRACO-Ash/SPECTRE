"""Shared FastAPI dependencies and lazy-import helpers for SIPC web routes.

All route modules import from here rather than duplicating these helpers.
Lazy imports break the circular dependency that arises because ``app.py``
creates ``templates`` and also imports the routers.
"""

from __future__ import annotations


def get_templates() -> object:
    """Return the Jinja2Templates instance from the application factory.

    The lazy import avoids the circular import that would occur if routes
    imported ``templates`` at module load time (``app.py`` imports routers,
    routers need ``templates`` from ``app.py``).  The object is created once
    at app startup so this is effectively a cached lookup after the first call.
    """
    from sipc.web.app import templates  # noqa: PLC0415

    return templates
