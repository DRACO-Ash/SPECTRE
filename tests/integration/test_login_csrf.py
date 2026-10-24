"""A cross-site page cannot sign the operator into someone else's account.

Audit F-151. POST /login had no CSRF, Origin or Referer check, so a page on
another site could post an attacker's credentials and leave the victim's
browser signed in as the attacker (login CSRF). SameSite=Lax does not stop a
cookie being set on a top-level cross-site POST response.

A browser's login (one carrying Origin or Referer) must now return the token
the login page set, as both a cookie and a form field. The check does not
read Host, so it holds behind a router that rewrites it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

_CREDS = {"username": "testadmin", "password": "testpass123"}


def _page_token(client: Any, path: str = "/login") -> str:
    client.cookies.clear()
    page = client.get(path)
    match = re.search(r'name="login_csrf" value="([^"]+)"', page.text)
    assert match, f"{path} carries no login token"
    assert client.cookies.get("spectre_login_csrf") == match.group(1)
    return match.group(1)


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Referer": "https://evil.example/phish"},
    {"Origin": "null"},
])
def test_a_cross_site_login_is_refused(client: Any, headers: dict[str, str]) -> None:
    client.cookies.clear()
    resp = client.post("/login", data=_CREDS, headers=headers, follow_redirects=False)
    assert resp.status_code == 403
    assert "spectre_session" not in resp.cookies


def test_a_forged_token_is_refused(client: Any) -> None:
    _page_token(client)
    resp = client.post(
        "/login", data={**_CREDS, "login_csrf": "made-up"},
        headers={"Origin": "https://spectre.example"}, follow_redirects=False,
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("path", ["/login", "/"])
def test_the_page_token_signs_in_whatever_the_host(client: Any, path: str) -> None:
    token = _page_token(client, path)
    # The browser names the public host; the app sees "testserver". The token,
    # not the Host header, is what is checked.
    resp = client.post(
        "/login", data={**_CREDS, "login_csrf": token},
        headers={"Origin": "https://spectre.example"}, follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "spectre_session" in resp.cookies


def test_a_failed_sign_in_page_carries_a_fresh_token(client: Any) -> None:
    token = _page_token(client)
    resp = client.post(
        "/login", data={"username": "testadmin", "password": "wrong", "login_csrf": token},
        headers={"Origin": "https://spectre.example"}, follow_redirects=False,
    )
    assert resp.status_code == 401
    assert 'name="login_csrf"' in resp.text


def test_a_client_that_is_not_a_browser_form_is_unaffected(client: Any) -> None:
    client.cookies.clear()
    resp = client.post("/login", data=_CREDS, follow_redirects=False)
    assert resp.status_code == 302


def test_our_own_form_signs_in_with_a_null_origin(client: Any) -> None:
    """Chromium sends "Origin: null" from our login form, because the app's
    Referrer-Policy is no-referrer. A check comparing Origin with Host would
    have refused every real sign-in; the token does not read either."""
    token = _page_token(client)
    resp = client.post(
        "/login", data={**_CREDS, "login_csrf": token}, headers={"Origin": "null"}, follow_redirects=False,
    )
    assert resp.status_code == 302
