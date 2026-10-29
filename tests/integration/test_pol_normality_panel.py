"""The Pattern of Life panel answers "is this normal?" for the latest burn (SPC-009).

The element histories are built burn by burn from the dv-estimation fixtures,
so pattern of life confirms each one, and the route runs end to end with only
the UDL round trip and the text parse stood in.
"""

from __future__ import annotations

from typing import Any

import pytest

from spectre.astro.pattern_of_life import ParseCounts
from spectre.web import rate_limit
from spectre.web.routes import pol
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit.test_dv_estimation import _base, _burn, _coast, _rec

# Element sets every 6 hours; a burn every 10 days.
_STEP_DAYS = 0.25
_BURN_EVERY = 40


def _history(sizes_km: list[float]) -> list[Any]:
    """An object raising its orbit by each of *sizes_km* in turn, 10 days apart."""
    recs, tle = [], _base()
    for k in range(_BURN_EVERY * (len(sizes_km) + 1)):
        if k and k % _BURN_EVERY == 0:
            tle = _burn(tle, d_alt_km=sizes_km[k // _BURN_EVERY - 1])
        recs.append(_rec(tle, source="18SDS"))
        tle = _coast(tle, _STEP_DAYS)
    return recs


@pytest.fixture
def analysed(monkeypatch: pytest.MonkeyPatch, client: Any, auth_cookie: str) -> Any:
    monkeypatch.setattr(rate_limit, "_udl_auth_limiter", rate_limit.SlidingWindowLimiter(50, 60))
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(50, 60))

    async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return "held", "held", {}, {}, "TEST-SAT"

    monkeypatch.setattr(pol, "_fetch_merged_history", merged)
    state = session_state(auth_cookie)
    saved = getattr(state, "last_pol_analysis", None)

    def run(sizes_km: list[float]) -> str:
        records = _history(sizes_km)
        monkeypatch.setattr(pol, "parse_tle_history_counted", lambda *_a, **_k: (records, ParseCounts()))
        resp = client.post(
            "/pol/analyse",
            data={"satno": "62902", "pol_source": "udl_direct", "udl_user": "u", "udl_pass": "p"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        return " ".join(resp.text.split())

    yield run
    state.last_pol_analysis = saved


def test_a_burn_like_the_ones_before_reads_routine(analysed: Any) -> None:
    page = analysed([25.0] * 8)
    assert "Is this normal? Latest burn" in page
    assert "Routine for this object" in page
    assert "this object&#39;s own history" in page or "this object's own history" in page


def test_a_burn_far_beyond_the_ones_before_reads_unlike_anything(analysed: Any) -> None:
    page = analysed([25.0] * 7 + [150.0])
    assert "Unlike anything in its last" in page
    assert "The largest of its 7 earlier burns" in page


def test_every_row_in_the_catalogue_carries_its_own_verdict(analysed: Any) -> None:
    page = analysed([25.0] * 7 + [150.0])
    assert "Normal?" in page
    assert ">unprecedented<" in page
    assert ">not enough history<" in page


def test_custody_leads_the_panel(analysed: Any) -> None:
    # The fixture history ends months before today, so against the real clock
    # its newest element set is far past the limit.
    page = analysed([25.0] * 8)
    assert "Custody lost: its newest element set is" in page
    assert page.index("Custody lost") < page.index("Is this normal? Latest burn")


class TestPanelCustodyAtAGivenMoment:
    """The same rule as the sweep, read from the analysed history (SPC-018)."""

    @staticmethod
    def _custody(hours_after_last_set: float) -> Any:
        from datetime import timedelta

        from spectre.astro.pattern_of_life import analyse_pattern_of_life
        from spectre.domain.pol_assessment import assess_pattern_of_life

        history = analyse_pattern_of_life(_history([25.0] * 8), satno=1, name="T")
        normality = pol._burn_normality(history, assess_pattern_of_life(history).manoeuvres)
        latest = max(normality, key=lambda n: n.burn.epoch)
        now = history.records[-1].epoch + timedelta(hours=hours_after_last_set)
        return pol._pol_custody(history, latest, now)

    def test_soon_after_the_last_set_it_is_held(self) -> None:
        from spectre.domain.custody import Custody

        assert self._custody(5.0).state is Custody.HELD

    def test_past_the_regime_limit_it_is_lost(self) -> None:
        from spectre.domain.custody import Custody

        # The fixture is LEO, so the limit is 24 hours.
        assert self._custody(30.0).state is Custody.LOST
