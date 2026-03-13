"""Shared FastAPI dependencies and lazy-import helpers for SIPC web routes.

All route modules import from here rather than duplicating these helpers.
Lazy imports break the circular dependency that arises because ``app.py``
creates ``templates`` and also imports the routers.
"""

from __future__ import annotations

import concurrent.futures

# Single-thread executor for all STK COM calls.  COM objects live in an STA
# (Single Threaded Apartment) and can only be accessed from the thread that
# created them.  Routing all calls through one dedicated thread avoids the
# "interface marshalled for a different thread" error that occurs when
# FastAPI's default thread-pool dispatches work to arbitrary threads.
_com_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stk-com")


def get_templates() -> object:
    """Return the Jinja2Templates instance from the application factory.

    The lazy import avoids the circular import that would occur if routes
    imported ``templates`` at module load time (``app.py`` imports routers,
    routers need ``templates`` from ``app.py``).  The object is created once
    at app startup so this is effectively a cached lookup after the first call.
    """
    from sipc.web.app import templates  # noqa: PLC0415

    return templates


def get_com_session() -> object:
    """Return a new :class:`~sipc.stk_adapter.com_session.StkComSession`.

    The import is deferred so that the module can be imported on non-Windows
    machines (e.g. in CI) without pulling in ``pywin32`` at module load time.
    """
    from sipc.stk_adapter.com_session import StkComSession  # noqa: PLC0415

    return StkComSession()
