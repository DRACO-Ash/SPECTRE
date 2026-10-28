"""Reflected cross-site scripting guards on the raw-HTML error paths.

Most of SPECTRE renders through Jinja, which autoescapes. A handful of error
partials build markup with f-strings instead, which bypasses that entirely, so
escaping at the interpolation point is the only control in the path. SonarQube
flagged seven of these and was right about all seven.

These are behavioural tests: they push a payload through the real endpoint and
assert it comes back inert. They have to be, and the first version was not.
Four of the five posted field names the routes do not declare, so FastAPI
answered 422 before the handler ran and the escaper was never reached; the
suite stayed at five green with ``html.escape`` deleted from geometry.py. Every
request below is therefore checked for the handler's own output, not only for
the absence of the payload, because absence is free in a body that was never
rendered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from spectre.web.routes.udl import FetchedElset
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_PAYLOAD = "<script>alert('xss')</script>"
_ESCAPED = "&lt;script&gt;"
_LIVE = "<script>alert("

# The integration harness logs in as this operator, and the planning state is
# keyed by username, so seeding a session means seeding this one.
_TEST_USER = "testadmin"

# A real element set, used wherever a route insists on a parsable TLE before it
# reaches the markup under test.
_STUB_TLE = (
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
)


def _cookies(auth_cookie: str) -> dict[str, str]:
    """The session cookie dict for an authenticated request."""
    return {"spectre_session": auth_cookie}


def _post(client: Any, auth_cookie: str, path: str, data: dict[str, Any]) -> Any:
    """POST *data* to *path* as the logged-in operator, CSRF token included."""
    return client.post(
        path, data=data, cookies=_cookies(auth_cookie), headers=csrf_headers(auth_cookie),
    )


def _assert_inert(resp: Any, *, status: int = 200, live: str = _LIVE, escaped: str = _ESCAPED) -> None:
    """Assert the handler ran and reflected *escaped* in place of *live*.

    All three checks are load-bearing. The status pins that a handler answered
    at all, so a 422 from a field name the route does not declare can no longer
    pass. The presence check pins that the payload actually reached the markup,
    so a response that never contained it cannot pass either: that is the
    defect that made four of these tests vacuous, and the absence check alone
    is satisfied by an empty body.
    """
    assert resp.status_code == status, (
        f"the handler did not run: HTTP {resp.status_code} {resp.text[:200]!r}"
    )
    text = resp.text
    assert live not in text, "payload reflected as executable markup"
    assert escaped in text, "payload never reached the response, so nothing was escaped"


def _assert_not_reflected(resp: Any, *, marker: str) -> None:
    """Assert the handler ran, said *marker*, and echoed nothing of the input.

    Some paths answer with a fixed operator-facing message rather than escaping
    the input, which is the stronger fix. There is then no escaped form to look
    for, so *marker* carries the proof that the error path was taken: without
    it this would pass on any body that happens not to mention the payload.
    """
    assert resp.status_code == 200, (
        f"the handler did not run: HTTP {resp.status_code} {resp.text[:200]!r}"
    )
    text = resp.text
    assert marker in text, "the handler's own error message is absent, so this path was not exercised"
    assert "alert(" not in text, "operator input reached the response"


@pytest.fixture()
def udl_connected(monkeypatch: pytest.MonkeyPatch, auth_cookie: str) -> Iterator[Any]:
    """A session holding UDL credentials, with the network call stubbed.

    Quick-add returns the 'Not connected to UDL' partial before it ever touches
    btn_id, so without a connected session the escaper under test is
    unreachable and the badge tests assert nothing. Only the outbound fetch is
    stubbed; the route, the template and the escaper are the real ones.
    """

    state = session_state(auth_cookie)
    saved_user, saved_pass = state.udl_username, state.udl_password
    saved_blue, saved_red = list(state.blue_assets), list(state.red_tracks)
    state.udl_username, state.udl_password = "udl-user", "udl-pass"

    async def _stub_fetch(*args: object, **kwargs: object) -> FetchedElset:
        """Stand in for the UDL round trip."""
        return FetchedElset(_STUB_TLE, "REAL", "18th SPCS")

    monkeypatch.setattr("spectre.web.routes.udl.fetch_tle_for_satno", _stub_fetch)
    yield state
    state.udl_username, state.udl_password = saved_user, saved_pass
    state.blue_assets, state.red_tracks = saved_blue, saved_red


class TestGeometryErrors:
    def test_unparseable_epoch_is_escaped(self, client: Any, auth_cookie: str) -> None:
        resp = _post(
            client, auth_cookie, "/plan/geometry/intercept",
            # The field is burn_epoch_str. Posting burn_epoch instead bought a
            # 422 and a test that could not fail.
            {"red_sat": "RED-1", "blue_sat": "BLUE-1", "burn_epoch_str": _PAYLOAD},
        )
        _assert_inert(resp)

    def test_unknown_satellite_name_is_escaped(self, client: Any, auth_cookie: str) -> None:
        resp = _post(
            client, auth_cookie, "/plan/geometry/intercept",
            {
                "red_sat": _PAYLOAD, "blue_sat": "BLUE-1",
                "burn_epoch_str": "2026-01-01T00:00:00",
            },
        )
        _assert_inert(resp)


class TestGcatErrors:
    def test_unknown_dataset_key_is_escaped(self, client: Any, auth_cookie: str) -> None:
        resp = client.get(
            "/gcat/table", params={"dataset": _PAYLOAD}, cookies=_cookies(auth_cookie),
        )
        # The unknown-dataset partial is served with 404, which is the handler
        # answering, not the request being rejected before it.
        _assert_inert(resp, status=404)


class TestScenarioTime:
    def test_invalid_date_echoes_nothing_of_the_input(self, client: Any, auth_cookie: str) -> None:
        """datetime.fromisoformat quotes its input, and this path bypasses Jinja.

        The handler now answers with a fixed message, so the proof is that the
        message is there and the payload is not: reinstating the exception text
        puts the operator's field back in the body and turns this red.
        """
        resp = _post(
            client, auth_cookie, "/scenario/time",
            {"scenario_start": _PAYLOAD, "scenario_stop": "2026-01-02T00:00:00"},
        )
        _assert_not_reflected(resp, marker="Use ISO 8601")


class TestAssetBadges:
    @pytest.mark.parametrize(
        ("endpoint", "name"),
        [("/assets/blue/quick-add", "XSSPROBEBLUE"), ("/assets/red/quick-add", "XSSPROBERED")],
    )
    def test_quick_add_button_id_is_escaped(
        self, client: Any, auth_cookie: str, udl_connected: Any, endpoint: str, name: str,
    ) -> None:
        """btn_id is written into an id attribute straight from a form field."""
        resp = _post(
            client, auth_cookie, endpoint,
            # name is required. Omitting it bought a 422 and a test that could
            # not fail.
            {"satno": "25544", "name": name, "btn_id": _PAYLOAD},
        )
        _assert_inert(resp)


class TestPatternOfLifeElementSets:
    def test_an_element_set_carrying_markup_renders_escaped(
        self, client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markup inside a TLE's own 69 columns reaches the element-set table.

        The table used to render the stored line with ``| safe``, which
        executed it in the analyst's authenticated session the moment they
        expanded 'view'. The reviewer who found it went on to read the CSRF
        token out of the DOM and create an admin account.

        THE CARRIER MATTERS, and an earlier version of this test got it wrong.
        It appended the payload AFTER column 69, which worked until the parser
        began truncating each line to _TLE_LINE_COLUMNS. The payload was then
        stripped before it ever reached the template, and the test failed for a
        reason that had nothing to do with the control it exists to cover: it
        produced the identical failure whether the template was fixed or still
        vulnerable, which is worse than no test.

        So the markup now sits INSIDE the 69 columns, over the classification
        and international-designator fields, where truncation cannot reach it.
        The epoch field is untouched, so sgp4 still parses the line and the
        element set still reaches the table. The parser's truncation bounds a
        payload; it does not sanitise one, so the template escaping remains the
        load-bearing control and this test is what holds it there.
        """
        payload = "<img src=x"
        second = (
            "1 25544U 98067A   24011.50000000  .00016717  00000-0  10270-3 0  9013\n"
            "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
        )
        line1, line2 = _STUB_TLE.split("\n")
        # Same length in, same length out, so column positions downstream hold.
        hot = line1[:7] + payload + line1[7 + len(payload):]
        merged = f"{hot}\n{line2}\n{second}"

        async def _stub_history(
            *args: object, **kwargs: object,
        ) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
            """Stand in for the UDL round trip: archive, merge, metadata, name."""
            return (merged, merged, {}, {}, "PROBE-SAT")


        state = session_state(auth_cookie)
        saved_analysis = getattr(state, "last_pol_analysis", None)
        monkeypatch.setattr("spectre.web.routes.pol._fetch_merged_history", _stub_history)
        try:
            resp = _post(
                client, auth_cookie, "/pol/analyse",
                {
                    "satno": "25544", "pol_source": "udl_direct",
                    "udl_user": "udl-user", "udl_pass": "udl-pass",
                },
            )
            _assert_inert(resp, live="<img src=x", escaped="&lt;img src=x")
        finally:
            state.last_pol_analysis = saved_analysis
