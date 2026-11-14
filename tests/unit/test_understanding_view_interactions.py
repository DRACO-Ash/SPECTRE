"""What the ledger states about interactions, on every panel (SPC-173, SPC-174).

A refusal is stated, never silently dropped: a close approach refused on an
out-of-date element set or an unreadable miss distance, the probe grade of
UDL conjunctions, and whether a hostile seed list is configured. The
statements sit with the ledger they qualify, escaped, one per line, and pass
I13 like every other sentence there.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.interaction_graph import Burn, MissEdge, MissSource
from spectre.domain.threat_assessment import Band
from spectre.web import understanding_view as uv
from spectre.web.routes import threat
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)
_BURNT = Burn(epoch=_BURN, earliest=_BURN, latest=_BURN, confirmed=True, detection="HIGH", provider="18SDS")
_MISS = MissEdge("41838", "BLUE-1", "40001", True, MissSource.COMPUTED, 140.0, 12.0, _BURN + timedelta(hours=3),
                 (_BURNT,))
_NOTES = ("UDL conjunction with <b>X</b> (40002) not counted: UDL filed no miss distance.",
          "no hostile seed list configured")


def _understanding() -> tu.ThreatUnderstanding:
    situation = tu.Situation(now=_NOW, access=Band.CRITICAL, custody=Custody.HELD, history_truncated=False)
    return tu.assess(tu.interaction_items([_MISS]), situation, with_cues=True)


class TestTheHeldObjectCarriesThem:
    def test_a_close_approach_is_one_of_its_items(self) -> None:
        held = uv.HeldObject("41838", None, None, None, Custody.HELD, interactions=(_MISS,))
        (item,) = held.items(_NOW, "GEO")
        assert item.label == "closest approach to BLUE-1 12.0 km after its burn, 140.0 km before"

    def test_its_notes_reach_the_view_and_none_reads_none(self) -> None:
        held = uv.HeldObject("41838", None, None, None, Custody.HELD, notes=_NOTES)
        view = uv.object_view(held, _NOW, regime="GEO", data_mode="REAL")
        assert view is not None
        assert view["ledger_notes"] == list(_NOTES)
        assert uv.understanding_view(_understanding())["ledger_notes"] == []


def _section(worst: dict[str, Any]) -> str:
    from tests.unit.test_threat_sweep_template import _context, _render

    page = _render(_context(worst_coa=worst))
    start = page.index('<section class="threat-understanding"')
    return page[start:page.index("</section>", start)]


def _shadowed(notes: tuple[str, ...]) -> dict[str, Any]:
    from spectre.domain.threat_assessment import CapabilityEvidence
    from tests.unit.test_threat_understanding_sweep import _sweep_entry

    worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(intel_threat_level="CRITICAL"))
    assert worst is not None
    shadowed = threat._with_understanding(worst, _understanding(), notes)
    assert shadowed is not None
    return shadowed


class TestTheLedgerStatesThem:
    def test_each_note_is_a_line_with_the_ledger_escaped(self) -> None:
        section = _section(_shadowed(_NOTES))
        start = section.index('<details class="tu-ledger"')
        ledger = section[start:section.index("</details>", start)]
        assert "UDL conjunction with &lt;b&gt;X&lt;/b&gt; (40002) not counted" in ledger
        assert "<b>X</b>" not in ledger
        assert re.search(r'<li[^>]*>no hostile seed list configured</li>', ledger)

    def test_with_none_there_is_no_list(self) -> None:
        assert "tu-ledger-notes" not in _section(_shadowed(()))

    def test_the_words_pass_i13(self) -> None:
        for note in _NOTES:
            assert i13_problems(note) == [], note
