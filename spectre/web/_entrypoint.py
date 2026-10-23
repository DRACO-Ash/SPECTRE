"""Console script entry point: ``spectre-serve``."""

# Ruff's S104 is exempted for this module as a whole rather than on the bind
# line below. Ruff and bandit each need their own directive for that bind and
# Python allows one comment per line, so the two previously shared a single
# comment; python:S7632 reports that as a malformed suppression, because the
# grammar is the directive, a colon, the codes, and nothing else on the line.
# Split, each tool gets a well-formed directive of its own: ruff's file-level
# exemption here, bandit's marker at the bind. Neither is spelled out in this
# rationale, because both tools scan comment text positionally and read a
# quoted directive as a live one, which is how the first attempt at this fix
# raised RUF100 here and fed seventeen prose words to bandit as test ids. The
# module is nine statements long and binds once, so the exemption covers that
# one bind and nothing else. Why the bind is correct is recorded at the bind.
# ruff: noqa: S104

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
        host="0.0.0.0",  # nosec B104
        port=settings.port,
        reload=False,
        access_log=False,  # request logging is handled by the application's own audit path
    )


if __name__ == "__main__":
    main()
