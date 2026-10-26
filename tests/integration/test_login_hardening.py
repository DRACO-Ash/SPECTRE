"""Integration tests for the hardened login path.

A security gate attacked a running instance and proved four defects here:
unthrottled credential brute force, bcrypt run on the event loop, a timing
oracle that read out which usernames exist, and a logout that left the session
token valid for its full 8 hours. Each test below states the property the fix
restored, so breaking a guard turns one of them red rather than all of them.

Nothing here measures wall-clock time. The clock is the weather: it says what
the machine was doing, not what the code does. Where the defect was a timing
one, the test counts the work instead.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from tests.conftest import csrf_headers

_ADMIN = "testadmin"
# Fixture credential for an in-memory database created and destroyed inside
# the test process. It authenticates against nothing that outlives the run.
_ADMIN_PASSWORD = "testpass123"

# An authenticated route any operator may reach, so a refusal here is about
# the session rather than the role.
_PANEL = "/plan/decision/panel"


def _login(
    client: TestClient, username: str, password: str, address: str | None = None
) -> object:
    """Post credentials, optionally from a nominated source address."""
    headers = {"X-Forwarded-For": address} if address else {}
    return client.post(
        "/login",
        data={"username": username, "password": password},
        headers=headers,
        follow_redirects=False,
    )


def _admin_cookies(client: TestClient) -> dict[str, str]:
    """Return a fresh authenticated admin session."""
    client.cookies.clear()
    resp = _login(client, _ADMIN, _ADMIN_PASSWORD)
    assert resp.status_code == 302, "the admin fixture credential no longer authenticates"
    return dict(resp.cookies)


def _create_operator(
    client: TestClient, admin: dict[str, str], username: str, password: str
) -> None:
    """Create an operator account through the admin route."""
    resp = client.post(
        "/admin/users",
        data={"username": username, "password": password, "role": "operator"},
        cookies=admin,
        headers=csrf_headers(admin),
    )
    assert resp.status_code == 200
    assert username.encode() in resp.content


def _user_id(client: TestClient, admin: dict[str, str], username: str) -> int:
    """Return the row id the admin table shows for *username*."""
    page = client.get("/admin/users", cookies=admin)
    assert page.status_code == 200
    for row in re.finditer(r'<tr id="user-row-(\d+)".*?</tr>', page.content.decode(), re.S):
        if f">{username}<" in row.group(0):
            return int(row.group(1))
    raise AssertionError(f"{username} is not in the admin user table")


class TestFailedLoginRateLimit:
    """DEFECT 1: 40 consecutive failed logins answered 40 x 401 and never 429."""

    def test_the_eleventh_failure_in_the_window_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The comparison is stubbed so 11 attempts cost milliseconds rather
        # than three seconds. The limiter is what is under test here, not
        # bcrypt's work factor.
        monkeypatch.setattr("spectre.web.routes.login.verify_password", lambda *_: False)
        address = "203.0.113.10"

        for attempt in range(10):
            resp = _login(client, "ghost-operator", "wrong", address=address)
            assert resp.status_code == 401, f"attempt {attempt + 1} was throttled too early"

        refused = _login(client, "ghost-operator", "wrong", address=address)
        assert refused.status_code == 429
        # A browser is what reaches this endpoint, so the refusal has to be the
        # login page carrying the reason, not a bare JSON body.
        assert b"Operator Authentication" in refused.content
        assert b"Too many failed sign-in attempts" in refused.content

    def test_a_locked_account_refuses_even_the_correct_password(
        self, client: TestClient
    ) -> None:
        """Audit F-008: the limiter was consulted only after a failed comparison.

        An exhausted budget then refused only wrong passwords, so the correct
        guess still signed in and 429 was just a renamed 401: the brute force
        was bounded by bcrypt throughput, not by the limiter.
        """
        admin = _admin_cookies(client)
        _create_operator(client, admin, "locked_out_user", "the-right-password")
        client.cookies.clear()
        for attempt in range(10):
            resp = _login(client, "locked_out_user", f"wrong-{attempt}", address=f"198.51.104.{attempt}")
            assert resp.status_code == 401
        resp = _login(client, "locked_out_user", "the-right-password", address="198.51.104.200")
        assert resp.status_code == 429
        assert "spectre_session" not in resp.cookies

    def test_a_different_source_address_keeps_its_own_budget(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("spectre.web.routes.login.verify_password", lambda *_: False)
        exhausted = "203.0.113.20"
        untouched = "203.0.113.21"
        # Its own account name. The username tier is module-level state, so a
        # name shared with the test above arrives already exhausted and this
        # test reports the address tier throttling too early when nothing of
        # the sort has happened.
        victim = "ghost-operator-two"

        for _ in range(10):
            assert _login(client, victim, "wrong", address=exhausted).status_code == 401
        assert _login(client, victim, "wrong", address=exhausted).status_code == 429

        # One address under attack must not sign out everyone else.
        #
        # A DIFFERENT username, deliberately. There is a second tier metering
        # the account, so reusing "ghost-operator" here would be refused by
        # that tier and this test would report the address tier leaking when
        # it was the username tier doing its job. The two budgets are only
        # separable by varying one at a time.
        assert _login(client, "other-ghost", "wrong", address=untouched).status_code == 401


class TestTimingEquivalence:
    """DEFECT 3: an unknown username skipped bcrypt entirely (CWE-204).

    2.6 ms against 270.2 ms told an attacker which operators exist however
    generic the error text was.
    """

    def test_an_absent_and_a_known_username_both_pay_for_one_comparison(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compared: list[str] = []

        def _record(plaintext: str, hashed: str) -> bool:
            compared.append(hashed)
            return False

        monkeypatch.setattr("spectre.web.routes.login.verify_password", _record)

        assert _login(client, "no-such-operator", "wrong", address="203.0.113.30").status_code == 401
        assert _login(client, _ADMIN, "wrong", address="203.0.113.31").status_code == 401

        assert len(compared) == 2, "the absent username skipped the bcrypt comparison"
        absent, known = compared
        # The stand-in has to be a real hash at the same cost factor, or the
        # work is only equivalent on paper.
        assert absent.startswith("$2b$"), "the stand-in is not a bcrypt hash"
        assert known.startswith("$2b$")
        assert absent.split("$")[2] == known.split("$")[2], "different bcrypt cost factors"
        assert absent != known


class TestBcryptOffTheEventLoop:
    """DEFECT 2: 32 concurrent anonymous logins took /healthz to a 833 ms median."""

    def test_the_comparison_is_awaited_in_the_threadpool(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import starlette.concurrency

        from spectre.web.auth import verify_password

        awaited: list[object] = []

        async def _spy(func: object, *args: object, **kwargs: object) -> object:
            awaited.append(func)
            return await starlette.concurrency.run_in_threadpool(func, *args, **kwargs)

        monkeypatch.setattr("spectre.web.routes.login.run_in_threadpool", _spy)

        resp = _login(client, _ADMIN, _ADMIN_PASSWORD, address="203.0.113.40")
        assert resp.status_code == 302
        # Awaited, not called: a synchronous call would never reach the spy.
        assert awaited == [verify_password], "bcrypt still runs on the event loop"


class TestSessionRevocation:
    """DEFECT 4: a cookie captured before POST /logout stayed good for 8 hours."""

    def test_logout_refuses_the_captured_cookie(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "hardening_logout", "shift-handover-one")

        client.cookies.clear()
        session = str(_login(client, "hardening_logout", "shift-handover-one").cookies["spectre_session"])
        captured = {"spectre_session": session}
        assert client.get(_PANEL, cookies=captured).status_code == 200

        client.cookies.clear()
        out = client.post(
            "/logout",
            cookies=captured,
            headers=csrf_headers(session),
            follow_redirects=False,
        )
        assert out.status_code == 302

        client.cookies.clear()
        after = client.get(_PANEL, cookies=captured, follow_redirects=False)
        assert after.status_code == 302, "the token outlived the logout that was meant to end it"
        assert "/login" in after.headers["location"]

    def test_a_password_change_ends_a_live_session(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "hardening_reset", "shift-handover-two")

        client.cookies.clear()
        session = str(_login(client, "hardening_reset", "shift-handover-two").cookies["spectre_session"])
        live = {"spectre_session": session}
        assert client.get(_PANEL, cookies=live).status_code == 200

        client.cookies.clear()
        reset = client.post(
            f"/admin/users/{_user_id(client, admin, 'hardening_reset')}",
            data={"role": "operator", "new_password": "rotated-after-the-incident"},
            cookies=admin,
            headers=csrf_headers(admin),
        )
        assert reset.status_code == 200

        client.cookies.clear()
        after = client.get(_PANEL, cookies=live, follow_redirects=False)
        assert after.status_code == 302, "the reset left the session it was meant to answer alive"
        assert "/login" in after.headers["location"]


class TestGenerationComparison:
    """The two shapes the stored counter arrives in, neither of which is a session."""

    def test_a_row_written_before_the_column_existed_starts_at_zero(self) -> None:
        from spectre.web.auth import _session_revoked
        from spectre.web.models import User

        migrated = User(username="row_from_before", hashed_password="x", role="operator")
        # The migration gives an existing row 0, the same value a fresh
        # account starts at, so a token carrying 0 is not revoked.
        migrated.session_generation = 0
        assert _session_revoked(migrated, 0) is False

    def test_a_token_from_before_the_account_id_claim_is_not_bound(self) -> None:
        """A pre-upgrade token names no account, so it cannot be bound to one.

        It decodes, at generation 0, but carries no account id, and
        ``require_login`` refuses a token that does not name the account it
        was issued to (audit F-048). The cost is one sign-in per operator at
        the upgrade; the alternative was accepting tokens of deleted namesakes.
        """
        from spectre.web.auth import SessionClaims, _bound_to, _decode_session, _serializer
        from spectre.web.models import User

        legacy = str(_serializer().dumps({"sub": "signed_in_before_upgrade"}))
        claims = _decode_session(legacy)
        assert claims == SessionClaims("signed_in_before_upgrade", None, 0)
        account = User(id=7, username="signed_in_before_upgrade", hashed_password="x", role="operator")
        account.session_generation = 0
        account.session_nonce = ""
        assert _bound_to(account, claims) is False

    def test_an_older_generation_is_revoked_and_the_current_one_is_not(self) -> None:
        from spectre.web.auth import _session_revoked
        from spectre.web.models import User

        user = User(username="rotated", hashed_password="x", role="operator")
        user.session_generation = 3
        assert _session_revoked(user, 2) is True
        assert _session_revoked(user, 3) is False
        # A token from the future is not a thing this can produce, but it must
        # not be treated as revoked if it ever were: that would lock an account
        # out rather than let a stale token through.
        assert _session_revoked(user, 4) is False


class TestRevocationDoesNotRefuseTheNextSession:
    """Revocation must never refuse a session minted AFTER it.

    Revocation is a counter, ``User.session_generation``, stamped into every
    token and bumped by logout and by the password-change listener; a token
    whose generation is below the account's is refused (auth._session_revoked).

    It replaced a timestamp epoch that could not be made correct (audit
    F-263 corrected this docstring, which still described that design).
    itsdangerous stamps a token's issue time in whole seconds, so a sign-in in
    the same second as the logout before it produced a token byte-identical to
    the revoked one: signing out and straight back in returned the operator to
    the login page. It also made this suite fail about half the time, which is
    how it surfaced: every test in test_threat_screen_route.py got the login
    page instead of the panel. These tests pin both write sites.
    """

    def test_signing_straight_back_in_after_logout_works(self, client: TestClient) -> None:
        """The whole cycle inside one second, which is where it used to break."""
        admin = _admin_cookies(client)
        _create_operator(client, admin, "same_second_user", "back-in-immediately")

        client.cookies.clear()
        first = str(_login(client, "same_second_user", "back-in-immediately").cookies["spectre_session"])

        client.cookies.clear()
        out = client.post(
            "/logout",
            cookies={"spectre_session": first},
            headers=csrf_headers(first),
            follow_redirects=False,
        )
        assert out.status_code == 302

        # No sleep. The sign-in lands in the same second as the logout before
        # it, which is the case a timestamp epoch could not answer: the two
        # tokens were byte-identical. The generation counter changes the
        # payload, so they differ and the old one is refused exactly.
        client.cookies.clear()
        second = str(_login(client, "same_second_user", "back-in-immediately").cookies["spectre_session"])
        assert second != first, "the second sign-in reused the first token"

        client.cookies.clear()
        resp = client.get(_PANEL, cookies={"spectre_session": second}, follow_redirects=False)
        assert resp.status_code == 200, (
            "the session minted after the logout was refused by the logout's own epoch"
        )

    def test_a_password_change_does_not_refuse_the_session_that_follows_it(
        self, client: TestClient
    ) -> None:
        """Same defect, the other write site."""
        admin = _admin_cookies(client)
        _create_operator(client, admin, "rotated_then_in", "first-credential")

        user_id = _user_id(client, admin, "rotated_then_in")
        client.cookies.clear()
        reset = client.post(
            f"/admin/users/{user_id}",
            data={"role": "operator", "new_password": "second-credential"},
            cookies=admin,
            headers=csrf_headers(admin),
        )
        assert reset.status_code == 200

        client.cookies.clear()
        session = str(_login(client, "rotated_then_in", "second-credential").cookies["spectre_session"])

        client.cookies.clear()
        resp = client.get(_PANEL, cookies={"spectre_session": session}, follow_redirects=False)
        assert resp.status_code == 200, (
            "the session opened with the new password was refused by the epoch "
            "that the password change stamped"
        )

    def test_every_generation_write_only_ever_increments(self) -> None:
        """The guard that stops the timestamp design creeping back.

        A write that SETS the generation rather than incrementing it, or that
        reaches for a clock, is the defect this feature was rewritten to
        remove. It reads as harmless and the suite would only catch it by
        luck, so it is enforced here rather than remembered.
        """
        import ast
        import pathlib as _pathlib

        from spectre.web import models
        from spectre.web.routes import login as login_module

        allowed = {
            "(target.session_generation or 0) + 1",
            "(user.session_generation or 0) + 1",
        }
        offenders: list[str] = []
        for module in (models, login_module):
            name = _pathlib.Path(module.__file__).name
            source = _pathlib.Path(module.__file__).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Assign):
                    continue
                if not any(
                    isinstance(t, ast.Attribute) and t.attr == "session_generation"
                    for t in node.targets
                ):
                    continue
                assigned = ast.unparse(node.value)
                if assigned not in allowed:
                    offenders.append(f"{name}:{node.lineno} -> {assigned}")

        assert not offenders, (
            "session_generation must only ever be incremented, never set from a "
            f"clock or a literal; these do not: {offenders}"
        )


class TestTheLimiterCannotBeOutrunByRotatingTheHeader:
    """The address tier alone was decorative, and measurement is what showed it.

    ``_client_address`` reads the first X-Forwarded-For entry, and the comment
    beside it argued the platform router rewrites that header. That is an
    assumption about an ingress this code cannot see, and if the router
    APPENDS instead, the caller chooses the key the limiter counts.

    Measured against the real application before the username tier existed:
    25 failed sign-ins with the header rotated per request produced 25 x 401
    and not one 429, while 25 from a fixed address produced 10 x 401 then
    15 x 429. The guard was perfect against an attacker who chose not to
    defeat it.

    A brute force is a search over passwords for ONE account, so the account
    is what must be bounded. These tests hold that.
    """

    @staticmethod
    def _fail(client: TestClient, username: str, address: str) -> int:
        return client.post(
            "/login",
            data={"username": username, "password": "not-the-password"},
            headers={"X-Forwarded-For": address},
            follow_redirects=False,
        ).status_code

    def test_a_rotating_source_address_still_hits_the_ceiling(
        self, client: TestClient
    ) -> None:
        """Every request from a fresh address, which defeated the old guard."""
        codes = [
            self._fail(client, "rotating_target", f"198.51.100.{i}")
            for i in range(25)
        ]
        assert 429 in codes, (
            "25 failed sign-ins against one account went unbounded because "
            "each arrived from a different address"
        )

    def test_an_account_that_does_not_exist_is_metered_the_same_way(
        self, client: TestClient
    ) -> None:
        """Otherwise 429 answers the question 401 was made generic to hide.

        The enumeration defect closed on this endpoint was a 103x timing gap.
        Metering only real accounts would reopen it as a status code, which is
        a cleaner read-out than the clock ever was.
        """
        codes = [
            self._fail(client, "no_such_operator_at_all", f"198.51.101.{i}")
            for i in range(14)
        ]
        assert 429 in codes, "an unknown username is not metered, so 429 means 'real'"

    def test_one_account_being_locked_does_not_lock_another(
        self, client: TestClient
    ) -> None:
        """The budget is per account, so a noisy neighbour is not a lockout."""
        for i in range(14):
            self._fail(client, "noisy_neighbour", f"198.51.102.{i}")
        assert self._fail(client, "quiet_neighbour", "198.51.102.200") == 401, (
            "a second account was refused because the first had exhausted its budget"
        )

    def test_a_successful_sign_in_is_never_charged(self, client: TestClient) -> None:
        """A shift change is a dozen legitimate sign-ins through one address.

        Charging those would lock an operations room out of its own console,
        which is a worse outage than the attack being prevented.
        """
        admin = _admin_cookies(client)
        _create_operator(client, admin, "shift_change_user", "handover-credential")
        client.cookies.clear()
        for _ in range(15):
            resp = client.post(
                "/login",
                data={"username": "shift_change_user", "password": "handover-credential"},
                headers={"X-Forwarded-For": "198.51.103.7"},
                follow_redirects=False,
            )
            assert resp.status_code == 302, "a correct sign-in was rate limited"
            client.cookies.clear()
