"""A detection from a long gap is flagged as possibly several burns.

Audit F-084. _LONG_GAP_WARN_DAYS was defined, with a comment saying such
detections are "kept but flagged as possibly several burns", and never read:
no detection from a 10 to 30 day gap was flagged.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from spectre.astro.pattern_of_life import _LONG_GAP_WARN_DAYS
from tests.unit.test_pol_status_ladder import _manoeuvre

_TEMPLATE = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / "partials" / "pol_results.html"


@pytest.mark.parametrize(("gap", "flagged"), [(15.0, True), (_LONG_GAP_WARN_DAYS, False), (5.0, False)])
def test_the_flag_follows_the_gap(gap: float, flagged: bool) -> None:
    mnv = dataclasses.replace(_manoeuvre(0.01), gap_days=gap)
    assert mnv.long_gap is flagged


def test_the_detections_table_shows_the_flag() -> None:
    assert "m.long_gap" in _TEMPLATE.read_text(encoding="utf-8")
