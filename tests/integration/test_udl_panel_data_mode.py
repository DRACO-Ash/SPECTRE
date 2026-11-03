"""A UDL fetch can name its own data mode for one request (SPC-030).

The session data mode (POST /udl/data-mode) governs every UDL fetch. An
operator who needs one EXERCISE elset while the session runs REAL, or one REAL
elset in an exercise, had to flip the session and remember to flip it back;
forgetting puts exercise data into live operations, or the reverse. The TLE
and state vector fetches now take a ``data_mode`` for that request only:

● blank means the session mode, and the panel's default option says which;
● REAL, SIMULATED, EXERCISE or TEST applies to that request and never moves
  the session mode;
● anything else is refused with a stated reason, never quietly read as REAL;
● the result carries a badge naming the data mode the fetch used.
"""

from __future__ import annotations

from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from spectre.web import rate_limit
from tests.integration.conftest import session_state

_LINE1 = "1 25544U 98067A   26025.79842163  .00000000  00000-0  10000-2 0  9999"
_LINE2 = "2 25544  51.6400 359.1324 0003806 313.0884 153.0596 15.50000000 00006"
_REFUSED = "Data mode must be REAL, SIMULATED, EXERCISE or TEST"


def _elset(data_mode: str | None) -> dict[str, Any]:
    rec: dict[str, Any] = {"objectName": "ISS", "line1": _LINE1, "line2": _LINE2}
    if data_mode is not None:
        rec["dataMode"] = data_mode
    return rec


def _vector(data_mode: str | None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "objectName": "ISS", "epoch": "2026-10-30T12:00:00.000000Z", "referenceFrame": "J2000",
        "xpos": 1.0, "ypos": 2.0, "zpos": 3.0, "xvel": 0.1, "yvel": 0.2, "zvel": 0.3,
    }
    if data_mode is not None:
        rec["dataMode"] = data_mode
    return rec


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch, auth_cookie: str) -> Iterator[tuple[Any, Any]]:
    """A stubbed UDL client, a connected session in REAL, and that session's state."""
    from spectre.web.routes import udl as udl_routes

    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_password, state.udl_data_mode)
    state.udl_username, state.udl_password, state.udl_data_mode = "u", "p", "REAL"
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(udl_routes.httpx, "AsyncClient", lambda **_k: client)
    yield client, state
    state.udl_username, state.udl_password, state.udl_data_mode = saved


def _answer(client: Any, payload: Any) -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    client.get = AsyncMock(return_value=resp)


def _get(client: Any, cookie: str, path: str, **params: Any) -> str:
    resp = client.get(path, params=params, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _sent_mode(udl_client: Any) -> str | None:
    return udl_client.get.call_args.kwargs["params"].get("dataMode")


class TestTleFetch:
    def test_a_chosen_mode_is_asked_of_udl_for_that_request_only(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        _answer(udl_client, [_elset("EXERCISE")])
        page = _get(client, auth_cookie, "/udl/tle", satno=25544, data_mode="EXERCISE")
        assert _sent_mode(udl_client) == "EXERCISE"
        assert "Data Mode: EXERCISE" in page
        assert 'name="elset_mode" value="EXERCISE"' in page
        assert state.udl_data_mode == "REAL", "a per-request choice moved the session mode"

    def test_blank_uses_the_session_mode(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        state.udl_data_mode = "TEST"
        _answer(udl_client, [_elset(None)])
        page = _get(client, auth_cookie, "/udl/tle", satno=25544, data_mode="")
        assert _sent_mode(udl_client) == "TEST"
        assert "Data Mode: TEST" in page

    def test_a_record_without_a_mode_is_badged_with_the_chosen_one(
        self, client: Any, auth_cookie: str, udl: Any,
    ) -> None:
        """The fallback was the session mode, which misnamed an overridden fetch."""
        udl_client, _state = udl
        _answer(udl_client, [_elset(None)])
        page = _get(client, auth_cookie, "/udl/tle", satno=25544, data_mode="simulated")
        assert _sent_mode(udl_client) == "SIMULATED"
        assert "Data Mode: SIMULATED" in page
        assert 'name="elset_mode" value="SIMULATED"' in page

    def test_an_unknown_mode_is_refused_not_read_as_real(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        state.udl_data_mode = "EXERCISE"
        _answer(udl_client, [_elset("REAL")])
        page = _get(client, auth_cookie, "/udl/tle", satno=25544, data_mode="LIVE")
        assert _REFUSED in page
        assert udl_client.get.await_count == 0, "UDL was asked despite an unknown data mode"
        assert "Data Mode: REAL" not in page
        assert state.udl_data_mode == "EXERCISE"


class TestStateVectorFetch:
    def test_a_chosen_mode_is_asked_of_udl_for_that_request_only(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        _answer(udl_client, [_vector(None)])
        page = _get(client, auth_cookie, "/udl/statevector", satno=25544, data_mode="EXERCISE")
        assert _sent_mode(udl_client) == "EXERCISE"
        assert "Data Mode: EXERCISE" in page
        assert state.udl_data_mode == "REAL"

    def test_blank_uses_the_session_mode(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        state.udl_data_mode = "TEST"
        _answer(udl_client, [_vector(None)])
        page = _get(client, auth_cookie, "/udl/statevector", satno=25544)
        assert _sent_mode(udl_client) == "TEST"
        assert "Data Mode: TEST" in page

    def test_an_unknown_mode_is_refused_not_read_as_real(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        _answer(udl_client, [_vector("REAL")])
        page = _get(client, auth_cookie, "/udl/statevector", satno=25544, data_mode="real; drop")
        assert _REFUSED in page
        assert udl_client.get.await_count == 0
        assert state.udl_data_mode == "REAL"


_ONE_FETCH_HINT = "(this fetch only; session mode unchanged)"


class TestTheOneFetchHint:
    """A fetch that named its own mode says the session mode did not move.

    Without it, an EXERCISE badge in a REAL session reads as if the session had
    been switched.
    """

    @pytest.mark.parametrize("path, payload", [("/udl/tle", _elset("EXERCISE")), ("/udl/statevector", _vector(None))])
    def test_a_named_mode_carries_the_hint(
        self, client: Any, auth_cookie: str, udl: Any, path: str, payload: dict[str, Any],
    ) -> None:
        udl_client, _state = udl
        _answer(udl_client, [payload])
        page = _get(client, auth_cookie, path, satno=25544, data_mode="EXERCISE")
        assert f"Data Mode: EXERCISE</span> <em class=\"hint\">{_ONE_FETCH_HINT}</em>" in page

    @pytest.mark.parametrize("path, payload", [("/udl/tle", _elset(None)), ("/udl/statevector", _vector(None))])
    def test_the_session_mode_carries_none(
        self, client: Any, auth_cookie: str, udl: Any, path: str, payload: dict[str, Any],
    ) -> None:
        udl_client, _state = udl
        _answer(udl_client, [payload])
        page = _get(client, auth_cookie, path, satno=25544, data_mode="")
        assert "Data Mode: REAL" in page
        assert _ONE_FETCH_HINT not in page


class TestTheFetchPanels:
    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_each_fetch_panel_offers_the_session_mode_first(
        self, client: Any, auth_cookie: str, udl: Any, side: str,
    ) -> None:
        _udl_client, state = udl
        state.udl_data_mode = "EXERCISE"
        page = _get(client, auth_cookie, "/")
        start = page.index(f'id="{side}-fetch-controls"')
        controls = page[start:page.index(f'id="{side}-tle-fields"', start)]
        assert f'<select id="{side}-tle-data-mode" name="data_mode"' in controls
        options = controls[controls.index(f'id="{side}-tle-data-mode"'):controls.index("</select>")]
        default = f'<option id="{side}-tle-data-mode-session" value="">Session mode (EXERCISE)</option>'
        assert options.index(default) < options.index('value="REAL"')
        for mode in ("REAL", "SIMULATED", "EXERCISE", "TEST"):
            assert f'<option value="{mode}">{mode}</option>' in options

    def test_setting_the_session_mode_relabels_both_defaults(self, client: Any, auth_cookie: str, udl: Any) -> None:
        """Otherwise the default option would still name the mode the page loaded with."""
        _udl_client, state = udl
        page = _set_session_mode(client, auth_cookie, "EXERCISE")
        assert state.udl_data_mode == "EXERCISE"
        assert "Data Mode: EXERCISE" in page
        for side in ("red", "blue"):
            assert (
                f'<option id="{side}-tle-data-mode-session" value="" hx-swap-oob="innerHTML">'
                "Session mode (EXERCISE)</option>"
            ) in page

    def test_setting_the_session_mode_keeps_a_per_fetch_choice(self, client: Any, auth_cookie: str, udl: Any) -> None:
        """Only the default option's text is swapped, never the select itself.

        Swapping the whole select from the Intel panel reset a per-fetch choice
        the operator had made in the Assets panel to Session mode, and the next
        fetch then asked UDL in the session mode without a word.
        """
        page = _set_session_mode(client, auth_cookie, "REAL")
        assert "<select" not in page, "the session mode swap replaces a per-fetch select and drops its choice"
        assert 'hx-swap-oob="true"' not in page

    @pytest.mark.parametrize("side", ["red", "blue"])
    def test_the_default_option_is_the_swap_target(
        self, client: Any, auth_cookie: str, udl: Any, side: str,
    ) -> None:
        page = _get(client, auth_cookie, "/")
        assert f'<option id="{side}-tle-data-mode-session" value="">Session mode (REAL)</option>' in page


class _FormOwners(HTMLParser):
    """Each named control's owning form: its form attribute, else the form it sits in."""

    _CONTROLS = frozenset({"input", "select", "textarea", "button"})

    def __init__(self) -> None:
        super().__init__()
        self._open_form: str | None = None
        self.owners: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = dict(attrs)
        if tag == "form":
            self._open_form = named.get("id")
        elif tag in self._CONTROLS and named.get("name"):
            self.owners.append((str(named["name"]), named.get("form") or self._open_form))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._open_form = None


@pytest.mark.parametrize("form_id", ["red-track-form", "blue-asset-form"])
def test_the_add_form_never_posts_a_data_mode(client: Any, auth_cookie: str, udl: Any, form_id: str) -> None:
    """The per-fetch choice belongs to the fetch; the add stores the elset's own mode."""
    resp = client.get("/", cookies={"spectre_session": auth_cookie})
    owners = _FormOwners()
    owners.feed(resp.text)
    posted = {name for name, form in owners.owners if form == form_id}
    # The Latest or Epoch radios join the form by attribute, so the parser sees both routes in.
    assert "mode" in posted, f"the parser found no form-attribute controls for {form_id}"
    assert "data_mode" not in posted, f"{form_id} posts the per-fetch data mode"


def _set_session_mode(client: Any, cookie: str, mode: str) -> str:
    from tests.conftest import csrf_headers

    resp = client.post(
        "/udl/data-mode", data={"data_mode": mode},
        cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )
    assert resp.status_code == 200
    return " ".join(resp.text.split())


class TestTheSessionModeRefusesAnUnknownValue:
    """SPC-024: an unknown session mode was silently set to REAL."""

    def test_an_unknown_mode_is_refused_and_the_mode_kept(self, client: Any, auth_cookie: str) -> None:
        from tests.integration.conftest import session_state

        state = session_state(auth_cookie)
        saved = state.udl_data_mode
        try:
            _set_session_mode(client, auth_cookie, "EXERCISE")
            page = _set_session_mode(client, auth_cookie, "LIVE")
            assert state.udl_data_mode == "EXERCISE"
            assert "Data mode must be REAL, SIMULATED, EXERCISE or TEST; the session mode is still EXERCISE." in page
            assert "Data Mode: EXERCISE" in page
        finally:
            state.udl_data_mode = saved
