"""The sweep says whether the interceptor's latest burn is normal for it (SPC-001, SPC-009).

The sweep held one current element set per object, so it could not answer the
operator's first question. It now fetches the red object's history from UDL
while it computes, holds it for 30 minutes so a repeat sweep does not fetch
again, and says plainly why when it has no answer.
"""

from __future__ import annotations

import asyncio
import re
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


def _fresh_orbit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The red element set read as 5 hours old against the GEO limit."""
    from datetime import UTC, datetime

    from spectre.web.elsets import ElsetAge

    monkeypatch.setattr(
        threat, "elset_age",
        lambda *_a, **_k: ElsetAge(epoch=datetime(2026, 10, 29, tzinfo=UTC), hours=5.0, limit_hours=72.0),
    )


class TestCustody:
    """SPC-018: custody is shown first, in the operator's terms."""

    def test_a_stale_orbit_is_custody_lost(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:  # noqa: F811
        # The fixture's red set is from day 60 of 2026, months past the 72 h limit.
        page = _sweep(client, auth_cookie)
        assert "Custody lost: its newest element set is" in page
        assert "a burn since then would not be seen" in page

    def test_a_fresh_orbit_without_udl_is_custody_degraded(
        self, client: Any, auth_cookie: str, sweep_state: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        _fresh_orbit(monkeypatch)
        page = _sweep(client, auth_cookie)
        assert "Custody degraded: its orbit is current (5.0 h old, limit 72 h)" in page
        assert "UDL is not connected" in page

    def test_a_fresh_orbit_with_a_history_is_custody_held(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fresh_orbit(monkeypatch)
        _stub_udl(monkeypatch, [25.0] * 8)
        page = _sweep(client, auth_cookie)
        assert "Custody held: its orbit is 5.0 h old (limit 72 h)" in page
        assert "timely and actionable" in page


class TestBehaviourReplacesTheSolverName:
    """SPC-003: the worst case card no longer calls the winning solver an intent."""

    def test_with_a_history_the_card_names_the_behaviour(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_udl(monkeypatch, [25.0] * 7 + [150.0])
        page = _sweep(client, auth_cookie)
        assert "Behaviour: unprecedented for this object" in page

    def test_without_a_history_it_says_behaviour_is_not_judged(
        self, client: Any, auth_cookie: str, sweep_state: Any,  # noqa: F811
    ) -> None:
        page = _sweep(client, auth_cookie)
        assert "Behaviour not judged: no element-set history" in page
        for solver_prose in ("Close-Proximity Operation", "Orbital Transfer", "Phasing Rendezvous"):
            assert solver_prose not in page


class TestBehaviourFeedsTheVerdict:
    """SPC-002: propellant, anomaly and observed burns reach the capability side."""

    _BEHAVIOUR = ("propellant budget", "behavioural anomaly score", "observed manoeuvre history")

    def test_without_a_history_they_are_listed_as_unavailable(
        self, client: Any, auth_cookie: str, sweep_state: Any,  # noqa: F811
    ) -> None:
        page = _sweep(client, auth_cookie)
        missing = page.split("Evidence not available for this object:", 1)[1].split('"', 1)[0]
        for name in self._BEHAVIOUR:
            assert name in missing

    def test_with_a_history_they_are_used(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_udl(monkeypatch, [25.0] * 8)
        page = _sweep(client, auth_cookie)
        missing = page.split("Evidence not available for this object:", 1)
        listed = missing[1].split('"', 1)[0] if len(missing) > 1 else ""
        for name in self._BEHAVIOUR:
            assert name not in listed


class TestPhaseAngle:
    """SPC-004: the worst case names where the target sits at the burn."""

    def test_the_phase_is_shown_with_its_side(self, client: Any, auth_cookie: str, sweep_state: Any) -> None:  # noqa: F811
        # Red and blue share every element but mean anomaly, 10 and 11 degrees,
        # so blue starts 1.0 degree ahead; the exact figure at their epoch is
        # pinned in test_sweep_epoch_labels. The sweep burns at today's date,
        # months later, where SGP4's GEO resonance terms have moved them apart
        # (0.8 degrees on 29 October 2026), so only the side and size hold here.
        page = _sweep(client, auth_cookie)
        assert "Target Phase at Burn" in page
        found = re.search(r"(\d+\.\d)° ahead of the interceptor", page)
        assert found is not None
        assert 0.5 < float(found.group(1)) < 1.1

    def test_a_geo_sweep_says_its_burn_times_are_samples(
        self, client: Any, auth_cookie: str, sweep_state: Any,  # noqa: F811
    ) -> None:
        page = _sweep(client, auth_cookie)
        assert "Burn times are samples across the next day" in page
