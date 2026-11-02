"""The "What the burn changed" section and the burn watch note render in every state (T1, T2).

The template tests render with StrictUndefined, so a value a state does not
supply fails here rather than silently rendering nothing in service. The
colours must come from the band tokens, which swap on the light theme.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.domain.warning_change import BurnLine, Change, Status, TargetWarning, WarningChange
from spectre.web.burn_watch import BurnAlert, BurnWatch
from tests.unit.test_threat_sweep_template import _context, _render

_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
_FIGURES = WarningChange(
    status=Status.FIGURES,
    headline="That burn cut your warning on BLUE-1 from 14h to 3h.",
    rows=(TargetWarning("BLUE-1", True, 14.0, 3.0, Change.CUT),),
    changed=(TargetWarning("BLUE-1", True, 14.0, 3.0, Change.CUT),
             TargetWarning("BLUE-7", True, None, 9.5, Change.NEWLY_IN_REACH)),
    footer="12 other targets unchanged.",
    burns=(BurnLine("RED-X burned at 03:12 UTC on 2 Nov, 6h 48m ago.", "Is this normal? Routine for this object."),),
    notes=("An unconfirmed detection at 08:10 UTC on 2 Nov is newer and is not counted, because it is not confirmed.",),
    basis="Computed at 10:00 UTC.",
    worst=Change.NEWLY_IN_REACH,
)


def _watch(**kw: Any) -> BurnWatch:
    args: dict[str, Any] = {"red_name": "RED-X", "red_satno": 1, "red_regime": "GEO", "targets": [],
                            "manual_tle_by_name": {}, "max_dv_m_s": 500.0, "accounted_until": None,
                            "started_at": _NOW, "next_check_at": _NOW + timedelta(minutes=10)}
    args.update(kw)
    return BurnWatch(**args)


@pytest.mark.parametrize("change", [
    None,
    _FIGURES,
    WarningChange(Status.NOT_COMPUTED, "What the burn changed is not shown: custody is lost."),
    WarningChange(Status.CANNOT_SAY, "What the burn changed: cannot say. UDL is not connected."),
    WarningChange(Status.NO_BURN, "No confirmed burn in its element sets from 10:00 UTC on 30 Oct."),
])
def test_the_section_renders_in_every_state(change: WarningChange | None) -> None:
    html = _render(_context(**({} if change is None else {"warning_change": change})))
    if change is not None:
        assert change.headline in html


def test_the_table_shows_only_what_changed() -> None:
    text = " ".join(re.sub(r"<[^>]+>", " ", _render(_context(warning_change=_FIGURES))).split())
    assert "BLUE-1 14h 3h cut by 11h" in text
    assert "BLUE-7 not in reach 9h 30m newly in reach" in text


@pytest.mark.parametrize("state", ["watching", "problem", "stopped", "alert", "none"])
def test_the_watch_note_renders_in_every_state(state: str) -> None:
    watch = {"watching": _watch(), "problem": _watch(problem="The element set could not be fetched from UDL."),
             "stopped": _watch(stopped="UDL is disconnected"), "alert": _watch(), "none": None}[state]
    alert = BurnAlert("RED-X", "03:12 UTC on 2 Nov", _NOW, _FIGURES) if state == "alert" else None
    html = _render(_context(burn_watch=watch, burn_alert=alert, watch_ends_at=_NOW + timedelta(hours=7)))
    assert 'id="burn-watch-note"' in html
    assert ("hx-trigger=\"every 60s\"" in html) == (state in ("watching", "problem", "alert"))


def test_new_colours_come_from_the_band_tokens() -> None:
    """T2: no raw hex or rgb() in the new section or the note; the light theme swaps tokens only."""
    html = _render(_context(warning_change=_FIGURES, burn_watch=_watch(), burn_alert=None,
                            watch_ends_at=_NOW + timedelta(hours=7)))
    for marker in ("sweep-warning-change", 'id="burn-watch-note"'):
        start = html.index(marker)
        block = html[start:html.index("</section>" if "section" in marker else "</div>\n", start)]
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block), marker
        assert not re.search(r"(?<!var\(--spectre-status-)(?<![-\w])rgba?\((?!var\()", block), marker


@pytest.mark.parametrize(("due", "band"), [("set", "high"), ("passed", "critical"), ("none", "unknown")])
def test_the_decide_by_line_renders_in_every_state(due: str, band: str) -> None:
    from spectre.domain.decide_by import DecideBy, Due

    html = _render(_context(decide_by=DecideBy(Due(due), f"Decide-by sentence for {due}.")))
    assert f"Decide-by sentence for {due}." in html
    section = html[html.index("sweep-decide-by"):html.index("</section>", html.index("sweep-decide-by"))]
    assert f"--spectre-status-{band}" in section
