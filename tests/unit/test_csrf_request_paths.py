"""The CSRF dependency on every path a request can take through it (SPC-071).

The mutation run over spectre/web/csrf.py found the form-field fallback and the
login token's content-type parsing untested: the suite sends the token in the
X-CSRF-Token header, so a plain HTML form post, the path a browser without
HTMX takes, could have been refused or waved through without a test noticing.
These drive the two dependencies directly with a real Starlette request, so
each case names exactly what reaches the check.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from spectre.web.csrf import LOGIN_COOKIE, LOGIN_FIELD, make_csrf_token, require_csrf

_SESSION = "a-session-cookie-value-for-the-form-path"
_FORM = "application/x-www-form-urlencoded"
_BOUNDARY = "spectre-test-boundary"


def _multipart(field: str, value: str) -> bytes:
    return (f"--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n"
            f"--{_BOUNDARY}--\r\n").encode()


def _request(
    method: str, path: str, *, headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None, body: bytes = b"",
) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": raw, "scheme": "http", "server": ("testserver", 80), "client": ("203.0.113.1", 4000),
        "root_path": "",
    }
    return Request(scope, receive)


def _refused(check: Callable[[Request], Awaitable[None]], request: Request) -> bool:
    try:
        asyncio.run(check(request))
    except HTTPException as exc:
        assert exc.status_code == 403
        return True
    return False


class TestSafeMethods:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "TRACE"])
    def test_a_safe_method_needs_no_token(self, method: str) -> None:
        assert not _refused(require_csrf, _request(method, "/scenario/time"))

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_an_unsafe_method_without_a_token_is_refused(self, method: str) -> None:
        assert _refused(require_csrf, _request(method, "/scenario/time", cookies={"spectre_session": _SESSION}))


class TestThePlainFormField:
    """A form post without HTMX carries the token in the csrf_token field, not the header."""

    @pytest.mark.parametrize("content_type", [_FORM, f"{_FORM}; charset=utf-8", f"{_FORM} ; charset=UTF-8"])
    def test_the_right_token_in_the_field_is_accepted(self, content_type: str) -> None:
        body = urlencode({"csrf_token": make_csrf_token(_SESSION), "start": "x"}).encode()
        request = _request("POST", "/scenario/time", headers={"content-type": content_type},
                           cookies={"spectre_session": _SESSION}, body=body)
        assert not _refused(require_csrf, request)

    def test_the_right_token_in_a_multipart_form_is_accepted(self) -> None:
        """A form with a file input posts multipart/form-data, and its field is read the same way."""
        request = _request("POST", "/scenario/time", headers={"content-type": f"multipart/form-data; boundary={_BOUNDARY}"},
                           cookies={"spectre_session": _SESSION}, body=_multipart("csrf_token", make_csrf_token(_SESSION)))
        assert not _refused(require_csrf, request)

    @pytest.mark.parametrize("guess", ["XXXX", "None", "null", "undefined", "0"])
    def test_no_session_cookie_is_never_matched(self, guess: str) -> None:
        """Without a session cookie no token verifies, including one minted for a constant a default might be."""
        request = _request("POST", "/scenario/time", headers={"X-CSRF-Token": make_csrf_token(guess)})
        assert _refused(require_csrf, request)

    def test_a_token_for_another_session_in_the_field_is_refused(self) -> None:
        body = urlencode({"csrf_token": make_csrf_token("another-session-entirely")}).encode()
        request = _request("POST", "/scenario/time", headers={"content-type": _FORM},
                           cookies={"spectre_session": _SESSION}, body=body)
        assert _refused(require_csrf, request)

    def test_an_empty_field_is_refused(self) -> None:
        request = _request("POST", "/scenario/time", headers={"content-type": _FORM},
                           cookies={"spectre_session": _SESSION}, body=b"csrf_token=")
        assert _refused(require_csrf, request)

    def test_a_body_that_cannot_be_parsed_is_refused_not_an_error(self) -> None:
        """multipart/form-data without a boundary makes the form parser raise: no token, so 403, not 500."""
        request = _request("POST", "/scenario/time", headers={"content-type": "multipart/form-data"},
                           cookies={"spectre_session": _SESSION}, body=b"--x\r\n")
        assert _refused(require_csrf, request)

    def test_a_token_in_a_body_that_is_not_a_form_is_not_read(self) -> None:
        """JSON is not a form: a token inside it is not looked for, so the request is refused."""
        request = _request("POST", "/scenario/time", headers={"content-type": "application/json"},
                           cookies={"spectre_session": _SESSION},
                           body=f'{{"csrf_token": "{make_csrf_token(_SESSION)}"}}'.encode())
        assert _refused(require_csrf, request)


class TestTheLoginPageToken:
    """POST /login from a browser must return the cookie the login page set, in the field, matching."""

    _BROWSER = {"origin": "https://spectre.example"}
    #: A missing cookie or field must never match anything. A constant standing in for either would be
    #: matched by an attacker who submits that constant, so a few likely constants are tried as the forgery.
    _GUESSES = ("XXXX", "None", "null", "undefined", "0")

    def _login(self, *, cookie: str | None, body: dict[str, str], content_type: str = _FORM) -> Request:
        headers = {**self._BROWSER, "content-type": content_type}
        cookies = {LOGIN_COOKIE: cookie} if cookie is not None else None
        return _request("POST", "/login", headers=headers, cookies=cookies, body=urlencode(body).encode())

    @pytest.mark.parametrize("content_type", [_FORM, f"{_FORM}; charset=utf-8"])
    def test_the_matching_cookie_and_field_pass(self, content_type: str) -> None:
        request = self._login(cookie="page-token-1", body={LOGIN_FIELD: "page-token-1"}, content_type=content_type)
        assert not _refused(require_csrf, request)

    def test_the_matching_token_in_a_multipart_form_passes(self) -> None:
        request = _request("POST", "/login", cookies={LOGIN_COOKIE: "page-token-1"},
                           headers={**self._BROWSER, "content-type": f"multipart/form-data; boundary={_BOUNDARY}"},
                           body=_multipart(LOGIN_FIELD, "page-token-1"))
        assert not _refused(require_csrf, request)

    @pytest.mark.parametrize("guess", _GUESSES)
    def test_no_cookie_is_never_matched(self, guess: str) -> None:
        assert _refused(require_csrf, self._login(cookie=None, body={LOGIN_FIELD: guess}))

    @pytest.mark.parametrize("guess", _GUESSES)
    def test_no_field_is_never_matched(self, guess: str) -> None:
        assert _refused(require_csrf, self._login(cookie=guess, body={"username": "u"}))

    @pytest.mark.parametrize("guess", _GUESSES)
    def test_an_empty_field_is_never_matched(self, guess: str) -> None:
        assert _refused(require_csrf, self._login(cookie=guess, body={LOGIN_FIELD: ""}))

    @pytest.mark.parametrize("guess", _GUESSES)
    def test_a_body_that_is_not_a_form_is_never_matched(self, guess: str) -> None:
        request = self._login(cookie=guess, body={LOGIN_FIELD: guess}, content_type="application/json")
        assert _refused(require_csrf, request)

    def test_a_mismatched_field_is_refused(self) -> None:
        assert _refused(require_csrf, self._login(cookie="page-token-1", body={LOGIN_FIELD: "page-token-2"}))

    def test_a_request_that_is_not_from_a_browser_form_is_not_asked_for_one(self) -> None:
        request = _request("POST", "/login", headers={"content-type": _FORM}, body=b"username=u&password=p")
        assert not _refused(require_csrf, request)
