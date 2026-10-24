"""UDL-derived data is served only to an operator with a UDL session.

Audit F-142. The on-orbit catalogue and the NOTSO cache are filled with one
operator's UDL credential and were served to any logged-in operator, with no
check of that operator's own UDL session.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import csrf_headers

_CATALOGUE = [{"satNo": 41838, "name": "SJ-17", "objectType": "PAYLOAD", "country": "PRC"}]


@pytest.fixture
def no_udl(monkeypatch: pytest.MonkeyPatch) -> Any:
    from spectre.web.planning_state import get_session_state
    from spectre.web.routes import udl

    monkeypatch.setattr(udl, "get_onorbit_catalog", lambda: _CATALOGUE)
    monkeypatch.setattr(udl, "get_catalog_status", lambda: "ready")
    state = get_session_state("testadmin")
    saved = (state.udl_username, state.udl_password)
    state.udl_username = state.udl_password = None
    yield state
    state.udl_username, state.udl_password = saved


def test_catalogue_search_needs_a_udl_session(client: Any, auth_cookie: str, no_udl: Any) -> None:
    resp = client.get("/udl/catalog/search", params={"q": "sj"}, cookies={"spectre_session": auth_cookie})
    assert resp.status_code == 200
    assert "SJ-17" not in resp.text
    assert "Log in to UDL" in resp.text

    no_udl.udl_username, no_udl.udl_password = "u", "p"
    assert "SJ-17" in client.get(
        "/udl/catalog/search", params={"q": "sj"}, cookies={"spectre_session": auth_cookie},
    ).text


def test_the_notso_cache_needs_a_udl_session(
    client: Any, auth_cookie: str, no_udl: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectre.data import notso_cache

    looked: list[int] = []

    class _Cache:
        def get_for_satno(self, satno: int) -> list[Any]:
            looked.append(satno)
            return []

    monkeypatch.setattr(notso_cache, "get_notso_cache", _Cache)
    saved = getattr(no_udl, "last_pol_analysis", None)
    no_udl.last_pol_analysis = SimpleNamespace(satno=41838)
    try:
        resp = client.post(
            "/pol/notso-correlate", data={"notso_text": ""},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
    finally:
        no_udl.last_pol_analysis = saved
    assert "Log in to UDL" in resp.text
    assert looked == [], "the shared cache was read for an operator with no UDL session"
