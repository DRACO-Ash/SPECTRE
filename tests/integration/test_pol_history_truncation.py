"""A PoL history cut short by UDL's record cap says so.

Audit F-144. The archive pull is one request capped at 5,000 records, with no
paging and no check of whether the cap was hit. The current element set is
then appended, so a long-lived object whose archive was truncated got a silent
gap between the last archived set and today.
"""

from __future__ import annotations

from typing import Any

import pytest

from spectre.web import rate_limit
from spectre.web.routes import pol
from tests.conftest import csrf_headers
from tests.unit.tle_clustering.conftest import make_tle_pair

_EPOCHS = ("26010.00000000", "26011.00000000", "26012.00000000")
_ARCHIVE = "\n".join(line for e in _EPOCHS for line in make_tle_pair(25544, 51.6, 100.0, 0.0006, e))
_CURRENT = "\n".join(make_tle_pair(25544, 51.6, 100.0, 0.0006, "26290.00000000"))


@pytest.fixture
def udl_stub(monkeypatch: pytest.MonkeyPatch) -> Any:
    from spectre.web.planning_state import get_session_state

    monkeypatch.setattr(rate_limit, "_udl_auth_limiter", rate_limit.SlidingWindowLimiter(50, 60))
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(50, 60))

    async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return _ARCHIVE, _ARCHIVE + "\n" + _CURRENT, {}, {}, "ISS"

    monkeypatch.setattr(pol, "_fetch_merged_history", merged)
    state = get_session_state("testadmin")
    saved = getattr(state, "last_pol_analysis", None)
    yield
    state.last_pol_analysis = saved


def _analyse(client: Any, cookie: str) -> str:
    resp = client.post(
        "/pol/analyse",
        data={"satno": "25544", "pol_source": "udl_direct", "udl_user": "u", "udl_pass": "p"},
        cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def test_an_archive_at_the_cap_is_flagged(
    client: Any, auth_cookie: str, udl_stub: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pol, "_UDL_MAX_RESULTS", len(_EPOCHS))
    page = _analyse(client, auth_cookie)
    assert "History truncated at 2026-01-12" in page


def test_an_archive_under_the_cap_is_not(client: Any, auth_cookie: str, udl_stub: Any) -> None:
    assert "History truncated" not in _analyse(client, auth_cookie)
