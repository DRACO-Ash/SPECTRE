"""What the sign-in and sign-out routes answer at their edges (SPC-071).

The mutation run over spectre/web/routes/login.py left these unpinned: which
entry of X-Forwarded-For is the caller, the address tier's 300 s window, the
sentence a locked-out operator reads, the refusal of the right password once
the budget is spent, where sign-out sends the browser, and that a second
sign-out still ends the session it was asked to end. Each limiter here is the
module's own, with only its record of calls replaced for the test, so its
budget and window are the ones the route uses. The limiter's clock is held.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import update
from starlette.requests import Request

from spectre.web import rate_limit
from spectre.web.auth import session_key_for
from spectre.web.database import AsyncSessionLocal
from spectre.web.models import User
from spectre.web.rate_limit import SlidingWindowLimiter
from spectre.web.routes import login
from tests.conftest import csrf_headers
from tests.integration.test_admin_route_outcomes import remove_accounts
from tests.integration.test_login_hardening import _PANEL, _admin_cookies, _create_operator, _login

_LOCKED = "Too many failed sign-in attempts. Wait a few minutes and try again."


_REFUSED = "Invalid username or password."


def _says(page: str, sentence: str) -> bool:
    """The login page's error paragraph is exactly *sentence*."""
    return re.search(r"<p [^>]*>" + re.escape(sentence) + "</p>", page) is not None


def _says_locked(page: str) -> bool:
    """The login page's error paragraph is exactly the locked-out sentence."""
    return _says(page, _LOCKED)


class _Clock:
    def __init__(self) -> None:
        self.now = 50_000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """The login limiters' clock, held by the test, with their records of calls emptied for it."""
    held = _Clock()
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(monotonic=held.monotonic))
    for limiter in (login._LOGIN_ADDRESS_LIMITER, login._LOGIN_USERNAME_LIMITER):
        monkeypatch.setattr(limiter, "_calls", defaultdict(deque))
        monkeypatch.setattr(limiter, "_last_sweep", held.now)
    return held


def _request(forwarded: str | None, peer: tuple[str, int] | None = ("192.0.2.7", 5000)) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "method": "POST", "path": "/login", "headers": headers,
                    "query_string": b"", "client": peer})


@pytest.fixture(scope="module", autouse=True)
def _leave_no_accounts(client: Any) -> Any:
    yield
    remove_accounts(client, ("logout_", "legacy_nonce"))


class TestWhoIsCalling:
    @pytest.mark.parametrize(("forwarded", "address"), [
        ("203.0.113.9, 10.0.0.1", "203.0.113.9"),
        ("203.0.113.9,10.0.0.1,10.0.0.2", "203.0.113.9"),
        ("  198.51.100.4  ", "198.51.100.4"),
        (None, "192.0.2.7"),
        ("", "192.0.2.7"),
    ])
    def test_the_first_forwarded_entry_is_the_caller(self, forwarded: str | None, address: str) -> None:
        assert login._client_address(_request(forwarded)) == address

    def test_a_request_with_no_peer_and_no_header_is_charged_to_unknown(self) -> None:
        assert login._client_address(_request(None, peer=None)) == "unknown"


class TestTheCookies:
    def test_the_login_page_token_lives_an_hour_and_only_on_the_login_path(self, client: Any) -> None:
        client.cookies.clear()
        header = client.get("/login").headers["set-cookie"].lower()
        assert header.startswith("spectre_login_csrf=")
        for attribute in ("max-age=3600", "path=/login", "httponly", "samesite=strict"):
            assert attribute in header, f"the login token cookie lacks {attribute}"

    def test_each_login_page_gets_a_token_of_its_own(self, client: Any) -> None:
        """A token the same on every page would be one a forging site could fill in (audit F-151)."""
        tokens = set()
        for _ in range(3):
            client.cookies.clear()
            page = client.get("/login")
            cookie = page.cookies["spectre_login_csrf"]
            assert f'value="{cookie}"' in page.text, "the hidden field must carry the cookie's token"
            tokens.add(cookie)
        client.cookies.clear()
        assert len(tokens) == 3
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", token) for token in tokens), "32 random bytes each"

    def test_a_sign_in_id_carries_128_random_bits(self, client: Any) -> None:
        """16 random bytes, 22 URL-safe characters: the id that keeps two sign-ins of one account apart."""
        client.cookies.clear()
        cookie = str(_login(client, "testadmin", "testpass123").cookies["spectre_session"])
        client.cookies.clear()
        key = session_key_for(cookie)
        assert key is not None
        assert re.fullmatch(r"[A-Za-z0-9_-]{22}", key.session_id)

    def test_an_account_from_before_the_nonce_column_still_signs_in(self, client: Any) -> None:
        """Such a row holds an empty nonce, and its sessions carry the same empty nonce (models.User.session_nonce)."""
        cookies = _admin_cookies(client)
        _create_operator(client, cookies, "legacy_nonce", "legacy-nonce-pass")

        async def blank_the_nonce() -> None:
            async with AsyncSessionLocal() as db:
                await db.execute(update(User).where(User.username == "legacy_nonce").values(session_nonce=""))
                await db.commit()

        client.portal.call(blank_the_nonce)
        client.cookies.clear()
        session = {"spectre_session": str(_login(client, "legacy_nonce", "legacy-nonce-pass").cookies["spectre_session"])}
        client.cookies.clear()
        assert client.get(_PANEL, cookies=session, follow_redirects=False).status_code == 200


class TestARefusal:
    def test_a_wrong_password_is_told_so_in_one_sentence(self, client: Any, clock: _Clock) -> None:
        """The same sentence for an unknown name and a wrong password, so neither tells which it was."""
        client.cookies.clear()
        for username in ("testadmin", "no_such_operator_anywhere"):
            refused = _login(client, username, "not-the-password")
            assert refused.status_code == 401
            assert _says(refused.text, _REFUSED)
        client.cookies.clear()


class TestTheWindows:
    @pytest.mark.parametrize("limiter", [login._LOGIN_ADDRESS_LIMITER, login._LOGIN_USERNAME_LIMITER])
    @pytest.mark.anyio
    async def test_ten_failures_lock_for_300_seconds_and_no_longer(
        self, clock: _Clock, limiter: SlidingWindowLimiter,
    ) -> None:
        for _ in range(10):
            assert await limiter.is_allowed("window-probe")
        assert await limiter.is_blocked("window-probe")
        clock.now += 300.0
        assert await limiter.is_blocked("window-probe"), "a failure exactly 300 s old still counts"
        clock.now += 0.5
        assert not await limiter.is_blocked("window-probe"), "a failure over 300 s old must be forgotten"


class TestALockedAccount:
    def test_the_operator_is_told_and_even_the_right_password_is_refused(
        self, client: Any, clock: _Clock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Spread over many addresses, so it is the username tier that locks; then the right password, refused."""
        client.cookies.clear()
        for attempt in range(10):
            resp = _login(client, "testadmin", "wrong-password", address=f"198.51.100.{attempt}")
            assert resp.status_code == 401
        locked = _login(client, "testadmin", "wrong-password", address="198.51.100.200")
        assert locked.status_code == 429
        assert _says_locked(locked.text)

        compared: list[str] = []
        real = login.verify_password

        def spy(password: str, hashed: str) -> bool:
            compared.append(password)
            return real(password, hashed)

        monkeypatch.setattr(login, "verify_password", spy)
        right = _login(client, "testadmin", "testpass123", address="198.51.100.201")
        assert right.status_code == 429
        assert _says_locked(right.text)
        assert "spectre_session" not in right.cookies
        assert compared == [], "the password was compared although the account's budget was spent"


class TestSigningOut:
    def test_sign_out_returns_the_browser_to_the_login_page(self, client: Any) -> None:
        cookies = _admin_cookies(client)
        _create_operator(client, cookies, "logout_once", "logout-once-pass")
        client.cookies.clear()
        session = {"spectre_session": str(_login(client, "logout_once", "logout-once-pass").cookies["spectre_session"])}
        client.cookies.clear()
        resp = client.post("/logout", cookies=session, headers=csrf_headers(session), follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_every_sign_out_ends_the_session_it_was_asked_to_end(self, client: Any) -> None:
        """The generation must rise at every sign-out, not only the first, or the second session outlives its own."""
        cookies = _admin_cookies(client)
        _create_operator(client, cookies, "logout_twice", "logout-twice-pass")
        for round_ in range(3):
            client.cookies.clear()
            session = {"spectre_session": str(
                _login(client, "logout_twice", "logout-twice-pass").cookies["spectre_session"])}
            client.cookies.clear()
            assert client.get(_PANEL, cookies=session).status_code == 200
            client.post("/logout", cookies=session, headers=csrf_headers(session), follow_redirects=False)
            client.cookies.clear()
            after = client.get(_PANEL, cookies=session, follow_redirects=False)
            assert after.status_code == 302, f"sign-out {round_ + 1} left its session alive"
