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
        # SECURITY HOTSPOT, REVIEWED AND ACCEPTED (Sonar python:S6829, bandit B104).
        # Binding all interfaces is required, not incidental: the process runs in a
        # container whose only route in is the platform ingress, which reaches it on
        # the pod IP. Binding loopback would make the readiness probe unreachable and
        # the deploy fail. Exposure is bounded by the pod network policy and the
        # Keycloak single-sign-on gateway in front of the service, not by this bind.
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=settings.port,
        reload=False,
        access_log=False,  # request logging is handled by the application's own audit path
    )


if __name__ == "__main__":
    main()
