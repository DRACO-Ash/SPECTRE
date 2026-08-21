"""Console script entry point: ``spectre-serve``."""

from __future__ import annotations

import uvicorn

from spectre.config.settings import get_settings


def main() -> None:
    """Start the SPECTRE web console with uvicorn.

    The listen port is resolved from the environment (``PORT``, default 8080)
    rather than hard-coded, because the Bluestaq App Store injects the port and
    probes it. Binding 0.0.0.0 is required for the platform router to reach the
    container.
    """
    settings = get_settings()
    uvicorn.run(
        "spectre.web.app:app",
        host="0.0.0.0",  # nosec B104 — required: the container must accept traffic from the platform router
        port=settings.port,
        reload=False,
        access_log=False,  # request logging is handled by the application's own audit path
    )


if __name__ == "__main__":
    main()
