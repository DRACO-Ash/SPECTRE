"""No staleness limit is shown bare: every "N h limit" on the POL, sweep and decision pages says whose figure it is
(SPC-215, V0.40 review).

The 24 h limit is LEO's figure, applied unchanged to MEO, HEO/Molniya and other orbits; the 72 h one GEO's. Since
SPC-215 each set states its regime and whose figure it takes, but the sentences that quote the limit, custody's, the
bound sets', the sweep's, said "against a 24 h limit" with no regime. Each rendered page here is searched for a limit
quoted as hours, and the words that follow it must say whose figure it is.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from tests.integration.test_all_intercepts_ranking import _BLUE_GEO
from tests.integration.test_decision_binding_on_screen import _hold, held  # noqa: F401
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_elset_age_display import red_state  # noqa: F401
from tests.integration.test_pol_normality_panel import analysed  # noqa: F401
from tests.integration.test_threat_sweep_routes import _add_manual, _post
from tests.unit.test_elset_freshness import _tle

#: A limit quoted as hours: "a 24 h limit", "its 72 h limit", "limit 72 h", "the last 24 h, its element-set age limit".
_QUOTED = re.compile(r"\b\d+ h limit\b|\blimit \d+ h\b|\b\d+ h, its element-set age limit")
#: Whose figure it is, in the words that follow the limit.
_WHOSE = re.compile(r"(LEO|GEO) figure")
_FOLLOWING = 120


def _text(page: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", page).split())


def _bare(page: str) -> list[str]:
    """Each limit quoted on *page* with no "<LEO|GEO> figure" in the words after it."""
    text = _text(page)
    return [text[m.start():m.end() + _FOLLOWING] for m in _QUOTED.finditer(text)
            if not _WHOSE.search(text[m.end():m.end() + _FOLLOWING])]


def _quoted(page: str) -> int:
    return len(_QUOTED.findall(_text(page)))


def test_the_decision_page_names_whose_limit_each_is(client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
    for hours in (5.0, 100.0):
        _hold(held, red_hours=hours)
        page = _evaluate(client, auth_cookie, _form(red_sat="RX", blue_sat="BY")).text
        assert _quoted(page) >= 2, "the bound sets' lines quote their limits"
        assert _bare(page) == []


def test_the_sweep_names_whose_limit_each_is(client: Any, auth_cookie: str, red_state: Any) -> None:  # noqa: F811
    from spectre.domain.models import RedTrack

    red_state.red_tracks = [RedTrack(name="RED-GEO", tle=_tle(datetime.now(tz=UTC) - timedelta(hours=2)),
                                     data_mode="REAL")]
    _add_manual(client, auth_cookie, "BLUE-GEO", _BLUE_GEO)
    page = _post(client, auth_cookie, "sweep", {"red_sat": "RED-GEO", "tgt_group": "none"}).text
    assert "1 stale" in _text(page)
    assert "BLUE-GEO (GEO: staleness limit 72 h, GEO figure, set for GEO)" in _text(page)
    assert _bare(page) == []


def test_the_pol_page_names_whose_limit_it_is(analysed: Any) -> None:  # noqa: F811
    page = analysed([25.0] * 8)
    assert "Custody lost: its newest element set is" in page
    assert _quoted(page) >= 1
    assert _bare(page) == []
