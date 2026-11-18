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
# module binds once, so the exemption covers that
# one bind and nothing else. Why the bind is correct is recorded at the bind.
# ruff: noqa: S104

from __future__ import annotations

import logging
import sys

import uvicorn

from spectre.config.settings import ConfigurationError, get_settings, validate_secret_key
from spectre.web.json_logging import configure_logging, uvicorn_log_config

logger = logging.getLogger("spectre.boot")

# The process's exit status when it refuses to boot, uvicorn's own for a failed startup.
_REFUSED = 3


def main() -> None:
    """Start the SPECTRE web console with uvicorn.

    Logging is configured first, before anything can fail, so every line the
    process writes is one JSON object on stdout and nothing reaches stderr
    (App Store logging standard, 0.48.4). The signing key is then checked here,
    ahead of uvicorn, so a refusal is one FATAL line naming the setting and the
    process exits; the lifespan keeps its own check for any other server.

    The listen port is resolved from the environment (``PORT``, default 8080)
    rather than hard-coded, because the Bluestaq App Store injects the port and
    probes it. Binding 0.0.0.0 is required for the platform router to reach the
    container.
    """
    # Before the settings are read, so even a failure reading them is a JSON line.
    configure_logging(process_hooks=True)
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        validate_secret_key(settings.secret_key)
    except ConfigurationError as exc:
        # Fail closed, as the lifespan does: the refusal is the security control.
        logger.critical(
            "SPECTRE refused to start: %s", exc,
            extra={"config.setting": "SECRET_KEY", "spectre.boot.outcome": "refused"},
        )
        sys.exit(_REFUSED)
    # python:S8392 kept on purpose: the container must bind all interfaces (reason at host= below).
    uvicorn.run(  # NOSONAR
        "spectre.web.app:app",
        # SECURITY HOTSPOT, REVIEWED AND ACCEPTED (Sonar python:S6829, bandit B104).
        # Binding all interfaces is required, not incidental: the process runs in a
        # container whose only route in is the platform ingress, which reaches it on
        # the pod IP. Binding loopback would make the readiness probe unreachable and
        # the deploy fail. Exposure is bounded by the pod network policy and the
        # platform ingress in front of the service, not by this bind. There is no
        # single-sign-on gateway: SPECTRE authenticates its own users (F-258).
        host="0.0.0.0",  # nosec B104
        port=settings.port,
        reload=False,
        # Off because uvicorn's line carries the query string, which can hold
        # operator input. app._log_request writes one line per request with the
        # path only (audit F-258).
        access_log=False,
        # uvicorn's own lines (startup, shutdown, an unhandled request error)
        # leave through the same JSON stdout handler as the app's.
        log_config=uvicorn_log_config(settings.log_level),
    )


if __name__ == "__main__":
    main()
