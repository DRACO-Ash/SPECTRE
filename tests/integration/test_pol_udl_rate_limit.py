"""PoL analysis is held to the UDL rate limits.

Audit F-045. POST /pol/analyse accepted UDL credentials in the form and
carried no rate limit, so it was an unthrottled credential oracle that side-
stepped the five-per-minute limit on /udl/login, each call firing two UDL
requests of up to 5,000 element sets.
"""

from __future__ import annotations

from typing import Any

import pytest

from spectre.web import rate_limit
from spectre.web.routes import pol
from tests.conftest import csrf_headers


@pytest.fixture
def fresh_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "_udl_auth_limiter", rate_limit.SlidingWindowLimiter(5, 60))
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(60, 60))

    async def no_udl(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return "", "", {}, {}, "STUB"

    monkeypatch.setattr(pol, "_fetch_merged_history", no_udl)


def _analyse(client: object, auth_cookie: str) -> int:
    resp = client.post(  # type: ignore[attr-defined]
        "/pol/analyse",
        data={"satno": "25544", "pol_source": "udl_direct", "udl_user": "u", "udl_pass": "p"},
        cookies={"spectre_session": auth_cookie},
        headers=csrf_headers(auth_cookie),
    )
    return int(resp.status_code)


def test_direct_credentials_are_held_to_the_udl_login_limit(
    client: object, auth_cookie: str, fresh_limits: None,
) -> None:
    codes = [_analyse(client, auth_cookie) for _ in range(6)]
    assert codes[:5] == [200] * 5
    assert codes[5] == 429
