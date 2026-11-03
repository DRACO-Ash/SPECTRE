"""Pattern of Life errors say what failed, never the exception text (SPC-023).

Found by the V0.10 UDL build: three Pattern of Life error paths put the raw
exception into the page, as the UDL routes did before SPC-019.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from spectre.web import rate_limit
from spectre.web.routes import pol
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_MARKER = "secret-internal-detail-4471"


@pytest.fixture(autouse=True)
def _open_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here posts more than once, so the UDL rate limits are opened."""
    monkeypatch.setattr(rate_limit, "_udl_auth_limiter", rate_limit.SlidingWindowLimiter(50, 60))
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(50, 60))


def _analyse(client: Any, cookie: str, source: str) -> Any:
    data = {"satno": "25544", "pol_source": source}
    if source == "udl_direct":
        data.update({"udl_user": "u", "udl_pass": "p"})
    return client.post("/pol/analyse", data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))


@pytest.mark.parametrize("source", ["udl_direct", "udl"])
def test_a_failed_udl_fetch_keeps_its_detail_in_the_log(
    client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, source: str,
) -> None:
    async def refused(*_a: Any, **_k: Any) -> None:
        raise RuntimeError(_MARKER)

    monkeypatch.setattr(pol, "_fetch_merged_history", refused)
    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_password)
    state.udl_username, state.udl_password = "operator", "udl-secret"
    try:
        with caplog.at_level(logging.WARNING, logger="spectre.web.routes.pol"):
            resp = _analyse(client, auth_cookie, source)
    finally:
        state.udl_username, state.udl_password = saved
    assert resp.status_code == 200
    assert _MARKER not in resp.text
    assert "The element-set history could not be fetched from UDL" in resp.text
    assert _MARKER in caplog.text


def test_a_failed_analysis_keeps_its_detail_in_the_log(
    client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return "held", "held", {}, {}, "ISS"

    def broken(*_a: Any, **_k: Any) -> None:
        raise ValueError(_MARKER)

    monkeypatch.setattr(pol, "_fetch_merged_history", merged)
    monkeypatch.setattr(pol, "_analyse_merged", broken)
    with caplog.at_level(logging.ERROR, logger="spectre.web.routes.pol"):
        resp = _analyse(client, auth_cookie, "udl_direct")
    assert resp.status_code == 200
    assert _MARKER not in resp.text
    assert "The element-set history could not be analysed" in resp.text
    assert _MARKER in caplog.text
