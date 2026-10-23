"""Audit-log integrity: an operator name must never be able to forge a record.

The security gate proved this end to end. It created an account whose name was
61 characters long and carried a newline in the middle, which cleared both
guards the create-user form had: str.strip() trims only the ends of a string,
and the 64-character bound only counts characters. One logger.warning about
that account then wrote two lines into the audit log, and the second line was
indistinguishable from a genuine record attributing an action to somebody else.

Two halves close it, and this module tests both.

● The charset check in spectre.web.routes.admin refuses the forged identity at
  the form, so it is never stored and never reaches any sink, including sinks
  added after this change.
● log_safe() flattens the name at the two sinks that still interpolated it raw,
  spectre.web.rate_limit._guard and spectre.web.planning_state.
"""

from __future__ import annotations

import logging

import pytest

from tests.conftest import csrf_headers

# The gate's payload, 61 characters in total. It is deliberately short enough
# to clear the 64-character bound and free of leading and trailing whitespace,
# so neither str.strip() nor the length check has anything to catch. Everything
# after the newline is what appears as the forged second audit line.
_FORGED_TAIL = "2026-10-22 09:00:00 spectre INFO Successful login: root"
_FORGED_USERNAME = "alice\n" + _FORGED_TAIL

# SPECTRE's own file handler formats records with "%(message)s", so a record
# occupies one log line exactly when its formatted output holds no line break.
# Assert on the formatted output rather than on record.msg: the username is
# interpolated at format time, so the forged line does not exist until the
# formatter has run.
_FORMATTER = logging.Formatter("%(message)s")


def _lines_from(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[str]:
    """Return the formatted output of every record emitted by *logger_name*."""
    return [
        _FORMATTER.format(record)
        for record in caplog.records
        if record.name == logger_name
    ]


def _admin_session(client: object) -> dict[str, str]:
    """Return cookies for an authenticated admin session."""
    resp = client.post(  # type: ignore[attr-defined]
        "/login",
        data={"username": "testadmin", "password": "testpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return dict(resp.cookies)


class TestForgedUsernameIsRefused:
    """The decisive case: the forged identity must never be created."""

    def test_the_payload_defeats_the_two_older_guards(self) -> None:
        """State plainly why strip() and the length bound were not enough."""
        assert len(_FORGED_USERNAME) == 61
        assert _FORGED_USERNAME.strip() == _FORGED_USERNAME
        assert "\n" in _FORGED_USERNAME

    def test_newline_in_username_is_refused(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": _FORGED_USERNAME, "password": "hunter2", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        # An operator-facing error on the form, not a 500 and not a stack trace.
        assert resp.status_code == 200
        body = resp.content.decode("utf-8", "replace")
        assert "Username may contain only letters" in body

        # And the account itself must be absent, because a stored forged name
        # is a standing liability for every sink, not only the ones fixed here.
        listing = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        assert listing.status_code == 200
        assert "Successful login: root" not in listing.content.decode("utf-8", "replace")

    @pytest.mark.parametrize("payload", ["bad name", "op\rword", "drop;table", "user x"])
    def test_other_separators_are_refused_too(self, client: object, payload: str) -> None:
        """A newline is one of several characters that must not reach a log."""
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": payload, "password": "hunter2", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert "Username may contain only letters" in resp.content.decode("utf-8", "replace")

    def test_an_ordinary_username_is_still_accepted(self, client: object) -> None:
        """The pattern must not break the form it is guarding."""
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "audit.probe-1", "password": "hunter2", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert "audit.probe-1" in resp.content.decode("utf-8", "replace")

    @pytest.mark.parametrize(
        "bootstrap_name",
        ["admin", "testadmin", "rescue-admin", "smoke_admin", "verify", "sim", "a.user@example.com"],
    )
    def test_bootstrap_style_names_satisfy_the_pattern(self, bootstrap_name: str) -> None:
        """A pattern that refused a bootstrap name would stop SPECTRE starting.

        The first admin account is created from SPECTRE_ADMIN_USER by
        spectre.web.database._bootstrap_admin, which does not route through the
        form. If the form's vocabulary were narrower than the names this
        repository's own deployments use, an administrator could not recreate
        the very account the container boots with.
        """
        from spectre.web.routes.admin import _USERNAME_PATTERN

        assert _USERNAME_PATTERN.fullmatch(bootstrap_name)

    def test_the_configured_bootstrap_username_satisfies_the_pattern(self) -> None:
        from spectre.config.settings import get_settings
        from spectre.web.routes.admin import _USERNAME_PATTERN

        configured = get_settings().spectre_admin_user.strip()
        assert _USERNAME_PATTERN.fullmatch(configured)


class TestRateLimitSink:
    """spectre/web/rate_limit.py: the warning that named the operator raw."""

    async def test_rate_limit_warning_occupies_exactly_one_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # _guard is private, but it is the sink. Reaching it through a route
        # would mean driving sixty requests to trip a limiter, which tests the
        # limiter rather than the log line.
        from fastapi import HTTPException

        from spectre.web.models import User
        from spectre.web.rate_limit import SlidingWindowLimiter, _guard

        # max_calls=0 refuses the very first call, so the warning is reached at
        # once and the test says nothing about the window arithmetic.
        limiter = SlidingWindowLimiter(max_calls=0, window_seconds=60)
        user = User(username=_FORGED_USERNAME, hashed_password="x", role="operator")

        with (
            caplog.at_level(logging.WARNING, logger="spectre.web.rate_limit"),
            pytest.raises(HTTPException),
        ):
            await _guard(limiter, user, "UDL data")

        lines = _lines_from(caplog, "spectre.web.rate_limit")
        assert lines, "the guard must log the refusal"
        assert all(len(line.splitlines()) == 1 for line in lines), lines
        # Flattened, not dropped: the whole payload stays on the one line, so
        # an investigator still sees what was attempted.
        assert "Rate limit hit" in lines[0]
        assert "Successful login: root" in lines[0]


class TestSessionStateSink:
    """spectre/web/planning_state.py: the debug record keyed by username."""

    def test_new_session_record_occupies_exactly_one_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spectre.web.planning_state import clear_session_state, get_session_state

        # The record is only written when the state is created, so clear first.
        clear_session_state(_FORGED_USERNAME)
        try:
            with caplog.at_level(logging.DEBUG, logger="spectre.web.planning_state"):
                get_session_state(_FORGED_USERNAME)

            lines = _lines_from(caplog, "spectre.web.planning_state")
            assert lines, "creating a session state must log it"
            assert all(len(line.splitlines()) == 1 for line in lines), lines
            assert "Created new session state" in lines[0]
            assert "Successful login: root" in lines[0]
        finally:
            clear_session_state(_FORGED_USERNAME)
