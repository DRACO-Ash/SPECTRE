"""POST /udl/notso/sync, pinned before its handler was split.

The handler scored 27 for cognitive complexity and had no test. These pin its
behaviour against a stubbed UDL: no session, a full page then a short one,
an endpoint that does not exist, a non-JSON body, and an error after a good
page. The cache is a temporary file.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from spectre.data import notso_cache
from spectre.web import rate_limit
from tests.conftest import csrf_headers


def _rec(i: int) -> dict[str, Any]:
    return {"id": f"rec-{i:05d}", "createdAt": f"2025-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}.000Z",
            "msgBody": {"SatIds": ["99001"]}}


def _resp(status: int = 200, payload: Any = None, *, bad_json: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("bad", request=MagicMock(), response=MagicMock())
    if bad_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = payload
    return resp


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    from spectre.web.planning_state import get_session_state
    from spectre.web.routes import udl

    monkeypatch.setattr(rate_limit, "_udl_sync_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    cache = notso_cache.NotsoCache(path=tmp_path / "c.json")
    monkeypatch.setattr(notso_cache, "get_notso_cache", lambda: cache)
    state = get_session_state("testadmin")
    saved = (state.udl_username, state.udl_password)
    state.udl_username, state.udl_password = "u", "p"
    responses: list[MagicMock] = []
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(udl.httpx, "AsyncClient", lambda **_k: client)
    yield responses, cache, state
    state.udl_username, state.udl_password = saved


def _sync(client: Any, cookie: str) -> str:
    resp = client.post("/udl/notso/sync", cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def test_no_session_is_refused(client: Any, auth_cookie: str, stub: Any) -> None:
    _responses, _cache, state = stub
    state.udl_username = None
    assert "No active UDL session" in _sync(client, auth_cookie)


def test_pages_until_a_short_one(client: Any, auth_cookie: str, stub: Any) -> None:
    responses, cache, _state = stub
    responses += [_resp(payload=[_rec(i) for i in range(500)]), _resp(payload=[_rec(500 + i) for i in range(3)])]
    page = _sync(client, auth_cookie)
    assert "<strong>+503</strong> new records added" in page
    assert "503 total in cache" in page
    assert cache.total_records() == 503


def test_a_missing_endpoint_is_reported_red(client: Any, auth_cookie: str, stub: Any) -> None:
    responses, _cache, _state = stub
    responses.append(_resp(404))
    page = _sync(client, auth_cookie)
    assert "callout-red" in page and "returned HTTP 404" in page


def test_a_non_json_body_is_reported(client: Any, auth_cookie: str, stub: Any) -> None:
    responses, _cache, _state = stub
    responses.append(_resp(bad_json=True))
    assert "Non-JSON response on page 0" in _sync(client, auth_cookie)


def test_an_error_after_a_good_page_keeps_the_good_page(client: Any, auth_cookie: str, stub: Any) -> None:
    responses, cache, _state = stub
    responses += [_resp(payload=[_rec(i) for i in range(500)]), _resp(500)]
    page = _sync(client, auth_cookie)
    assert "callout-green" in page and "<strong>+500</strong>" in page
    assert "HTTP error on page 1" in page
    assert cache.total_records() == 500
