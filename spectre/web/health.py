"""Unauthenticated health and readiness endpoints for SPECTRE.

Contract
--------
The Bluestaq App Store schedules the pod and probes it. Three rules shape this
module, each learned from a real deploy-stage failure:

1. **Prove storage with a real write.** An existence check passes on a
   read-only or root-owned mount, so the probe writes a byte and removes it.
2. **Race a hard timeout.** A probe that *hangs* on a stalled mount is killed
   silently by kubelet liveness back-off, which is undiagnosable. The timeout
   here is strictly shorter than the platform probe, so a stall becomes a
   loud 503 rather than a silent SIGTERM.
3. **Return the diagnosis in the body.** The 503 carries the resolved data
   directory and the exact errno, so a screenshot of the response is a
   complete diagnosis.

Both paths are exempt from authentication by design: the platform probes them
before any session exists. They are GET, so the global CSRF dependency admits
them as safe methods.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from spectre import __version__
from spectre.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Strictly shorter than the platform's probe timeout so a stalled mount surfaces
# as a 503 we can read, never as a silent liveness kill.
_STORAGE_PROBE_TIMEOUT_SECONDS = 2.0

_PROBE_FILENAME = ".spectre-health-probe"


def _write_probe(data_dir: str) -> None:
    """Write and delete a probe file. Blocking; run in a worker thread."""
    probe = Path(data_dir) / _PROBE_FILENAME
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


async def check_storage(data_dir: str) -> tuple[bool, str | None]:
    """Return ``(healthy, detail)`` for a real write to *data_dir*.

    ``detail`` is ``None`` when the write succeeded, otherwise a human-readable
    reason including the errno where the operating system supplied one.
    """
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_write_probe, data_dir),
            timeout=_STORAGE_PROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return False, (
            f"storage write to {data_dir} did not complete within "
            f"{_STORAGE_PROBE_TIMEOUT_SECONDS}s (mount may be stalled)"
        )
    except OSError as exc:
        return False, f"storage write to {data_dir} failed: [errno {exc.errno}] {exc.strerror}"
    except Exception as exc:  # pragma: no cover — defensive
        return False, f"storage write to {data_dir} failed: {exc.__class__.__name__}: {exc}"
    return True, None


@router.get("/healthz", include_in_schema=False)
async def healthz() -> JSONResponse:
    """Liveness probe. 200 while the process is able to serve.

    Deliberately does not touch storage: a liveness probe that fails on a
    storage fault causes a restart loop that cannot fix the fault.
    """
    return JSONResponse({"status": "ok", "version": __version__})


@router.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    """Readiness probe. 200 only when storage genuinely accepts a write."""
    settings = get_settings()
    healthy, detail = await check_storage(settings.data_dir)

    body: dict[str, Any] = {
        "status": "ok" if healthy else "unavailable",
        "version": __version__,
        "data_dir": settings.data_dir,
    }
    if healthy:
        return JSONResponse(body)

    body["detail"] = detail
    body["remedy"] = (
        "If this is the App Store FILE_STORAGE add-on, the pod needs "
        "securityContext.fsGroup set so the non-root container can write to the volume."
    )
    logger.error("Readiness probe failed — %s", detail)
    return JSONResponse(body, status_code=503)
