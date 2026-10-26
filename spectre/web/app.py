"""FastAPI application factory for SPECTRE web console."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from spectre import __version__
from spectre.config.settings import (
    get_settings,
    secret_key_is_ephemeral,
    uses_sqlite,
    validate_data_dir,
    validate_secret_key,
    validate_sqlite_support,
)
from spectre.web.csrf import require_csrf
from spectre.web.database import init_db
from spectre.web.format_units import format_m_s, format_tof_label
from spectre.web.health import router as health_router
from spectre.web.log_safety import log_safe
from spectre.web.planning_state import set_default_hrr_objects, set_default_hrr_tles
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
templates.env.filters["m_s"] = format_m_s        # {{ dv | m_s }} → delta-v in m/s, honestly rounded
templates.env.filters["tof"] = format_tof_label  # {{ hours | tof }} → "6h 30m", one definition


def banner_class(marking: str) -> str:
    """The banner colour class for *marking*.

    A marking the theme has no colour for gets the most restrictive one
    rather than the unclassified green (audit F-269).
    """
    word = marking.strip().upper()
    if word.startswith("UNCLASSIFIED"):
        return "unclassified"
    if word.startswith("OFFICIAL"):
        return "official"
    return "secret"


# One source for the version and the marking; the splash said v2.0.0 and both
# templates said UNCLASSIFIED whatever the deployment was (audit F-269).
templates.env.globals["spectre_version"] = __version__
templates.env.globals["classification_marking"] = get_settings().classification_marking
templates.env.globals["classification_class"] = banner_class(get_settings().classification_marking)


logger = logging.getLogger(__name__)
_access_log = logging.getLogger("spectre.access")

_HRR_FILENAME = "HRR_List.json"

#: Bundled bootstrap watchlist, shipped inside the package.
#:
#: The operator's own HRR_List.json is gitignored and dockerignored because it
#: is operational data and belongs on the data volume, not in a source tree or
#: an image. The consequence was that a freshly deployed instance had no
#: watchlist at all and both the threat sweep and the asset screen stalled at
#: "fetch the HRR list from the UDL panel first". This file is the floor under
#: that: real catalogue numbers and names, SYNTHETIC element sets, clearly
#: marked, and outranked by anything the operator supplies.
_HRR_BUNDLED = Path(__file__).parent.parent / "data" / "hrr_default.json"


def _hrr_candidate_paths() -> list[Path]:
    """Return the places an HRR watchlist may live, in priority order.

    The operator-supplied copy on the data volume wins, so a deployed instance
    can be given fresh data without rebuilding the image. The source-tree
    location is kept for local development. The bundled bootstrap list is last
    and always present, so the capability runs out of the box.
    """
    return [
        Path(get_settings().data_dir) / _HRR_FILENAME,
        Path(__file__).parent.parent.parent / _HRR_FILENAME,
        _HRR_BUNDLED,
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
        objects = hrr_blue + hrr_red
        set_default_hrr_objects(objects)

        # Element sets, where the list carried them. A real JCO notification
        # does not, so this is empty for an operator-supplied file and the
        # sweep still needs a UDL fetch, exactly as before.
        tles = {o["satno"]: o["tle"] for o in objects if o.get("tle")}
        modes = {o["satno"]: o.get("tle_data_mode", "REAL") for o in objects if o.get("tle")}
        set_default_hrr_tles(tles, modes)

        logger.info(
            "HRR pre-load: %d Blue + %d Red = %d satellites from %s (%s)",
            len(hrr_blue), len(hrr_red), len(objects),
            newest.get("createdAt", "unknown date"), hrr_path,
        )
        synthetic = [m for m in modes.values() if m != "REAL"]
        if synthetic:
            logger.warning(
                "%d of %d element sets are %s, not live tracking data. Connect "
                "to UDL to replace them before relying on any result.",
                len(synthetic), len(objects), min(synthetic),
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
    #
    # The one exception is the platform's DAST scan, which starts the image with
    # no environment at all. There SECRET_KEY resolves to a throwaway minted for
    # this process. It is announced loudly because a running instance on an
    # ephemeral key loses every session at restart, and because the flag has no
    # business being set anywhere but the scan.
    if secret_key_is_ephemeral():
        logger.warning(
            "APPSTORE_DAST_SCAN is set and SECRET_KEY is not, so this process is "
            "signing sessions with a THROWAWAY key minted at boot. Every session "
            "and CSRF token dies at restart. This is correct for the App Store "
            "security scan and wrong for anything else: if you see this line in a "
            "deployment, unset APPSTORE_DAST_SCAN and set a real SECRET_KEY."
        )
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
        # The database never lives on the injected mount: that volume is object
        # storage and cannot host SQLite. It goes on the container filesystem,
        # which works but does not survive a redeploy.
        sqlite_dir = validate_data_dir(settings.sqlite_dir)
        validate_sqlite_support(sqlite_dir)
        logger.warning(
            "SPECTRE %s storage: SQLite at %s. This is EPHEMERAL and will be lost on "
            "redeploy or restart. Attach the POSTGRESQL add-on for durable storage; "
            "its injected DATABASE_URL is picked up automatically.",
            __version__, sqlite_dir,
        )
    else:
        logger.info(
            "SPECTRE %s storage: external database, durable. Data volume at %s",
            __version__, resolved_data_dir,
        )

    await init_db()
    _load_hrr_from_disk()
    logger.info("SPECTRE %s ready — listening for requests", __version__)
    yield
    logger.info("SPECTRE %s shutting down", __version__)


# ── Security response headers ─────────────────────────────────────────────────
#
# The console shipped with no security headers at all, so this round's two
# cross-site scripting defects had nothing behind the output escaping: an
# injected handler reads the CSRF token out of the DOM and posts to
# /admin/users. These headers are that second line.
#
# The policy is as tight as the shipped templates allow and no tighter, because
# a policy that blanks a panel is worse than no policy. Every loosening below is
# forced by something already in the tree, and each is a KNOWN GAP recorded with
# the work needed to close it:
#
#   script-src 'unsafe-inline'. 17 templates carry inline <script>; base.html
#     holds two of them, the pre-paint theme bootstrap and the shared
#     spectreActivate keyboard handler, and 158 inline onclick and onkeydown
#     attributes drive the panels. A nonce does not cover event handler
#     attributes at all, and hashes would need 'unsafe-hashes' and a hash per
#     handler. To close: move the base.html blocks into /static and convert the
#     handlers to delegated listeners, then drop the token.
#   script-src 'unsafe-eval'. htmx 1.9.12 compiles hx-on::* attributes with
#     new Function (static/htmx.min.js). Seven of them clear forms and open
#     panels in catalog_results, sweep_target_config, admin/users, operator and
#     training_scenario_list. Without the token htmx raises
#     htmx:evalDisallowedError and those seven stop working. To close: replace
#     the seven attributes with listeners in a static file, then drop the token.
#   style-src 'unsafe-inline'. Roughly 1500 inline style attributes and three
#     inline <style> blocks (splash_overlay, intercept_geometry, training).
#     To close: move them into the stylesheet. Counts rechecked for F-270.
#   frame-src and frame-ancestors 'self'. The training Console tab embeds the
#     console itself: templates/training.html sets an iframe src of '/'.
#     'none', or X-Frame-Options: DENY, blanks that tab. 'self' still refuses
#     the cross-origin framing the clickjacking finding describes.
#
# BE PRECISE ABOUT WHAT THIS DOES NOT STOP. With 'unsafe-inline' in script-src,
# an injected inline script or event handler EXECUTES. This policy is therefore
# not a mitigation for the stored-XSS class that the escaping in the templates
# addresses; it is a second perimeter around it. Treating it as the control
# would be exactly the mistake that let one `| safe` reach the DOM.
#
# What it does buy, and these are real: injected script cannot load external
# code, exfiltrate over fetch or XHR to another origin, submit a form off-site,
# load a plugin, or rewrite the document base.
#
# KNOWN GAP, with the work it needs. Dropping 'unsafe-inline' requires the two
# inline <script> blocks in base.html to move to a file under static/ or carry
# a per-response nonce, and the inline onclick/onkeydown attributes across the
# partials to become delegated listeners. That is a large, separately testable
# change; until it lands, script-src is a perimeter and not a shield, and it is
# recorded here rather than implied away.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "base-uri 'none'; "
    "object-src 'none'"
)

#: Sent on every response. Strict-Transport-Security is not here because it is
#: conditional; see :func:`_is_https`.
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
}

#: One year, covering the host's own subdomains.
_HSTS = "max-age=31536000; includeSubDomains"


def _is_https(request: Request) -> bool:
    """Return ``True`` when the browser's leg of *request* was TLS.

    TLS terminates at the platform router, so the scheme inside the container is
    plain http and the forwarded header is the only honest signal. Uvicorn
    trusts that header from loopback only and the router is not on loopback, so
    it is read here rather than relying on the resolved scheme.
    """
    forwarded = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded.split(",")[0].strip() or request.url.scheme
    return scheme == "https"


app = FastAPI(
    title="SPECTRE — Space Planning, Evaluation & Counter-Threat Response Engine",
    version=__version__,
    lifespan=lifespan,
    dependencies=[Depends(require_csrf)],
    # The interactive documentation and the schema are off, not gated. An
    # anonymous GET /openapi.json answered 200 with all 69 routes and their
    # parameter names, which is a complete attack-surface map of an
    # authenticated console sitting on a public ingress. Nothing in the
    # deployment consumes the schema, so there is nothing to gate: only the
    # health probes are public, and they stay public.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# Probes poll every few seconds; logging them would drown the request lines.
_UNLOGGED_PATHS = frozenset({"/healthz", "/livez", "/ping", "/readyz"})


@app.middleware("http")
async def _log_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """One access line per request: method, path, status and duration.

    The path only: the query string can carry operator input, which is why
    uvicorn's own access log is off (audit F-258).
    """
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path not in _UNLOGGED_PATHS:
        _access_log.info(
            "%s %s %d %.0f ms",
            request.method, log_safe(request.url.path), response.status_code,
            (time.perf_counter() - started) * 1000.0,
        )
    return response


@app.middleware("http")
async def _add_security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach the security response headers to every response.

    ``setdefault`` rather than assignment, so a route that has deliberately
    set one of these for itself keeps its own value.
    """
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if _is_https(request):
        response.headers.setdefault("Strict-Transport-Security", _HSTS)
    return response

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
