"""Security response headers on every path out of the console.

The middleware in :mod:`spectre.web.app` that attaches these headers shipped
with no test at all. The reviewer reduced the whole body of
``_add_security_headers`` to ``return await call_next(request)`` and all 1,397
tests stayed green, so the control could have been deleted by an unrelated
refactor and nothing in the repository would have said so. On a console that
faces a Dynamic Application Security Testing (DAST) gate, and whose own branch
comment calls these headers the second line behind the output escaping, that is
the worst shape a control can be in: declared, documented and unheld.

The tests below hold it at three levels, because each catches a different way
of losing it.

● Presence and value, one test per header, taken from a real response produced
  by the real application rather than from a hand-built one.
● The policy pinned character for character. The expected policy is written out
  here rather than imported from ``_CSP``, because a test that imports the
  constant agrees with whatever the constant later says, and would wave through
  the single change that matters most: a quiet loosening of the policy. After
  this, loosening it costs a deliberate edit in two places and a reviewer sees
  both.
● The conditional and error paths, which are where a header policy actually
  evaporates. The HSTS branch is conditional on TLS and was never once
  executed by the suite. A 404 and the redirect an unauthenticated caller gets
  are responses no route handler wrote, so they are the ones a change to the
  middleware is most likely to drop on the floor.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Response

#: The policy as app.py declares it, written out rather than imported.
#:
#: Importing ``_CSP`` would make this test agree with any value the constant
#: ever takes, which is the one thing it must not do. Every token below is
#: forced by something already in the tree and recorded as a known gap in the
#: comment above ``_CSP``; a future edit that drops one of those gaps, or opens
#: a new one, has to come here and say so.
_EXPECTED_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "base-uri 'none'; "
    "object-src 'none'"
)

#: One year, covering the host's own subdomains.
_EXPECTED_HSTS = "max-age=31536000; includeSubDomains"

#: The only two directives whose 'unsafe-inline' is a recorded known gap.
#:
#: Pinned separately from the full policy string because the two assertions
#: fail for different reasons. The string equality above says the policy
#: changed; this says the change widened the set of places an injected inline
#: script or style may run, which is the loosening that costs the most.
_UNSAFE_INLINE_IS_RECORDED_IN = {"script-src", "style-src"}

#: The headers sent on every response, whatever the scheme or the status.
_ALWAYS_ON = {
    "content-security-policy": _EXPECTED_CSP,
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "referrer-policy": "no-referrer",
}

_PRESET_PATH = "/testing/preset-security-header"
_PRESET_VALUE = "DENY"

#: A documentation address (RFC 5737) charged to this module alone.
#:
#: The login route's failed-attempt limiter is a process-wide singleton keyed
#: on the first X-Forwarded-For entry, so a neighbouring test module spending
#: the default budget would turn the 401 below into a 429 and the failure would
#: read as a header defect. Nominating an address buys this module its own
#: budget and keeps the test about the headers.
_OWN_SOURCE = {"x-forwarded-for": "198.51.100.7"}


def _assert_always_on(resp: Any) -> None:
    """Assert the four unconditional headers reached *resp* intact."""
    for name, value in _ALWAYS_ON.items():
        assert resp.headers.get(name) == value, (
            f"{name} missing or altered on HTTP {resp.status_code} {resp.request.url.path}"
        )


def _directives(policy: str) -> dict[str, list[str]]:
    """Split a CSP into ``{directive: [source, ...]}``."""
    parsed: dict[str, list[str]] = {}
    for chunk in policy.split(";"):
        tokens = chunk.split()
        if tokens:
            parsed[tokens[0]] = tokens[1:]
    return parsed


@pytest.fixture(scope="module")
def preset_client(client: Any) -> Iterator[Any]:
    """Yield the integration client with a throwaway route that sets its own header.

    No shipped route sets one of these headers for itself, so the ``setdefault``
    semantics cannot be exercised against the real route table. The route is
    added to the real application rather than to a stand-in, so the request runs
    the same middleware stack the console runs, and it is taken out again on
    teardown so the shared application object is left as it was found.
    """
    from spectre.web.app import app

    async def _preset_endpoint() -> Response:
        return Response(
            content="preset",
            media_type="text/plain",
            headers={"X-Frame-Options": _PRESET_VALUE},
        )

    app.add_api_route(_PRESET_PATH, _preset_endpoint, methods=["GET"], include_in_schema=False)
    try:
        yield client
    finally:
        app.router.routes[:] = [
            route for route in app.router.routes if getattr(route, "path", "") != _PRESET_PATH
        ]


class TestEveryHeaderReachesARealResponse:
    """One test per header, each failing on its own account.

    The status is asserted alongside every header so a response that was never
    rendered cannot satisfy the test by accident.
    """

    def test_content_security_policy_is_sent(self, client: Any) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("content-security-policy") == _EXPECTED_CSP

    def test_x_content_type_options_is_nosniff(self, client: Any) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_is_sameorigin(self, client: Any) -> None:
        """SAMEORIGIN, not DENY: templates/training.html frames the console itself."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("x-frame-options") == "SAMEORIGIN"

    def test_referrer_policy_is_no_referrer(self, client: Any) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("referrer-policy") == "no-referrer"


class TestThePolicyIsPinned:
    def test_the_policy_matches_character_for_character(self, client: Any) -> None:
        """Any edit to the policy, in either direction, has to be made here too."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("content-security-policy") == _EXPECTED_CSP

    def test_unsafe_inline_is_confined_to_the_two_recorded_directives(self, client: Any) -> None:
        """Naming where inline code may run, independently of the pinned string.

        'unsafe-inline' in script-src or style-src is a gap the branch records
        and costs. The same token reached by any other directive is a new gap,
        and this fails whether or not somebody also edited the string above.
        """
        resp = client.get("/")
        policy = resp.headers.get("content-security-policy", "")
        relaxed = {
            name for name, sources in _directives(policy).items() if "'unsafe-inline'" in sources
        }
        assert relaxed == _UNSAFE_INLINE_IS_RECORDED_IN

    def test_no_directive_lists_the_same_source_twice(self, client: Any) -> None:
        """A duplicated source is how a token gets added to a directive unnoticed.

        Appending 'unsafe-inline' to a directive that already carries it leaves
        a policy browsers still honour, so nothing breaks and nothing is seen.
        """
        resp = client.get("/")
        policy = resp.headers.get("content-security-policy", "")
        for name, sources in _directives(policy).items():
            assert len(sources) == len(set(sources)), f"{name} lists a source twice: {sources}"


class TestStrictTransportSecurity:
    """The conditional branch. Line 341 of app.py was never executed."""

    def test_it_is_sent_when_the_router_forwards_https(self, client: Any) -> None:
        resp = client.get("/", headers={"x-forwarded-proto": "https"})
        assert resp.status_code == 200
        assert resp.headers.get("strict-transport-security") == _EXPECTED_HSTS

    def test_it_is_absent_without_a_forwarded_scheme(self, client: Any) -> None:
        """Plain HTTP must not be pinned to TLS the deployment may not have."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "strict-transport-security" not in resp.headers

    def test_it_is_absent_when_the_router_forwards_plain_http(self, client: Any) -> None:
        resp = client.get("/", headers={"x-forwarded-proto": "http"})
        assert resp.status_code == 200
        assert "strict-transport-security" not in resp.headers

    def test_the_leftmost_forwarded_scheme_decides(self, client: Any) -> None:
        """A chained header is read first entry first, which is the browser's leg."""
        secure = client.get("/", headers={"x-forwarded-proto": "https, http"})
        assert secure.headers.get("strict-transport-security") == _EXPECTED_HSTS
        plain = client.get("/", headers={"x-forwarded-proto": "http, https"})
        assert "strict-transport-security" not in plain.headers


class TestARouteKeepsAHeaderItSetItself:
    """``setdefault``, not assignment, so a route can still speak for itself."""

    def test_the_route_value_survives_the_middleware(self, preset_client: Any) -> None:
        resp = preset_client.get(_PRESET_PATH)
        assert resp.status_code == 200
        assert resp.headers.get("x-frame-options") == _PRESET_VALUE

    def test_the_remaining_headers_are_still_added_alongside_it(self, preset_client: Any) -> None:
        """Deferring on one header must not mean skipping the rest."""
        resp = preset_client.get(_PRESET_PATH)
        assert resp.status_code == 200
        assert resp.headers.get("content-security-policy") == _EXPECTED_CSP
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("referrer-policy") == "no-referrer"


class TestTheHeadersSurviveTheErrorPaths:
    """Responses no route handler wrote, which is where a policy quietly stops.

    A header set only on the success path is worth very little: the error path
    is served by the exception handlers, carries operator-visible markup, and is
    reachable without a session, so it is the first thing a scanner walks.
    """

    def test_a_404_carries_them(self, client: Any) -> None:
        resp = client.get("/no-such-page")
        assert resp.status_code == 404
        _assert_always_on(resp)

    def test_the_login_redirect_carries_them(self, client: Any) -> None:
        """An unauthenticated caller is redirected by a dependency, not a handler."""
        resp = client.get("/admin/users", cookies={}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers.get("location") == "/login"
        _assert_always_on(resp)

    def test_a_rejected_sign_in_carries_them(self, client: Any) -> None:
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "wrong-password"},
            headers=_OWN_SOURCE,
            follow_redirects=False,
        )
        assert resp.status_code == 401
        _assert_always_on(resp)

    def test_a_csrf_refusal_carries_them(self, client: Any) -> None:
        """Raised by the global dependency before any route is reached."""
        resp = client.post("/admin/users", data={"username": "x"}, follow_redirects=False)
        assert resp.status_code == 403
        _assert_always_on(resp)
