"""The sweep says whether the interceptor's latest burn is normal for it (SPC-001, SPC-009).

The sweep held one current element set per object, so it could not answer the
operator's first question. It now fetches the red object's history from UDL
while it computes, holds it for 30 minutes so a repeat sweep does not fetch
again, and says plainly why when it has no answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from spectre.astro.pattern_of_life import ParseCounts
from spectre.web.routes import pol, threat
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO
from tests.integration.test_pol_normality_panel import _history
from tests.integration.test_threat_sweep_routes import _add_manual, _post, sweep_state  # noqa: F401


@pytest.fixture
def udl(sweep_state: Any) -> Iterator[Any]:  # noqa: F811
    """A connected UDL session with no held histories, restored afterwards."""
    saved = (sweep_state.udl_username, sweep_state.udl_password, dict(sweep_state.elset_histories))
    sweep_state.udl_username, sweep_state.udl_password = "operator", "udl-secret"
    sweep_state.elset_histories.clear()
    yield sweep_state
    sweep_state.udl_username, sweep_state.udl_password = saved[0], saved[1]
    sweep_state.elset_histories.clear()
    sweep_state.elset_histories.update(saved[2])


def _sweep(client: Any, cookie: str) -> str:
    _add_manual(client, cookie, "BLUE-GEO", _BLUE_GEO)
    resp = _post(client, cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"})
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _stub_udl(monkeypatch: pytest.MonkeyPatch, sizes_km: list[float], delay_s: float = 0.0) -> list[int]:
    """UDL answering with a history of burns sized *sizes_km*; returns the fetch count."""
    fetches: list[int] = []
    records = _history(sizes_km)

    async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        fetches.append(1)
        if delay_s:
            await asyncio.sleep(delay_s)
        return "held", "held", {}, {}, "RED-GEO"

    monkeypatch.setattr(pol, "_fetch_merged_history", merged)
    monkeypatch.setattr(pol, "parse_tle_history_counted", lambda *_a, **_k: (records, ParseCounts()))
    return fetches


class TestWithoutUdl:
    def test_it_says_why_it_cannot_judge(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:  # noqa: F811
        page = _sweep(client, auth_cookie)
        assert "Is this normal?</strong> Cannot say: UDL is not connected" in page


class TestWithAHistory:
    def test_the_latest_burn_is_judged_against_its_own_history(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_udl(monkeypatch, [25.0] * 7 + [150.0])
        page = _sweep(client, auth_cookie)
        assert "Is this normal?" in page
        assert "Unlike anything in its last 80 days" in page
        assert "element sets over" in page

    def test_a_second_sweep_uses_the_held_history(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fetches = _stub_udl(monkeypatch, [25.0] * 8)
        _sweep(client, auth_cookie)
        page = _sweep(client, auth_cookie)
        assert len(fetches) == 1
        assert "Routine for this object" in page


class TestWhenUdlIsSlowOrFails:
    def test_a_slow_history_is_said_to_be_loading_and_is_held_for_next_time(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(threat, "_HISTORY_WAIT_S", 0.01)
        fetches = _stub_udl(monkeypatch, [25.0] * 8, delay_s=0.5)
        page = _sweep(client, auth_cookie)
        assert "still loading from UDL" in page
        client.portal.call(asyncio.sleep, 1.0)  # type: ignore[attr-defined]
        page = _sweep(client, auth_cookie)
        assert "Routine for this object" in page
        assert len(fetches) == 1

    def test_a_failed_fetch_is_a_stated_problem_not_an_error_page(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def refused(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("401 from UDL with internal detail")

        monkeypatch.setattr(pol, "_fetch_merged_history", refused)
        page = _sweep(client, auth_cookie)
        assert "Cannot say: The element-set history could not be fetched from UDL." in page
        assert "internal detail" not in page
        assert not udl.elset_histories, "a failure was held, so the next sweep would not retry"
