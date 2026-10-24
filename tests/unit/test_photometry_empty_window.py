"""An empty comparison window is reported, not read as "no change".

Audit F-108. An empty baseline or recent window returned p = 1.0 with zero
statistics, which the assessment reported as no significant brightness
change, with no confounding factor to say there was nothing to compare.
"""

from __future__ import annotations

from spectre.astro.photometry import assess_photometry
from tests.unit.test_photometry import _make_obs_sequence


def test_an_empty_baseline_window_is_named_with_its_counts() -> None:
    # Twenty daily observations, all inside a 30-day recent window: the
    # baseline window (30 to 90 days back) holds none.
    result = assess_photometry(_make_obs_sequence(20), recent_window_days=30, baseline_window_days=60)
    window_notes = [c for c in result.confounding_factors if "window" in c]
    assert window_notes, result.confounding_factors
    assert "baseline window holds 0" in window_notes[0]
    assert "recent window holds 20" in window_notes[0]


def test_two_populated_windows_add_no_such_note() -> None:
    result = assess_photometry(_make_obs_sequence(60), recent_window_days=30, baseline_window_days=60)
    assert not [c for c in result.confounding_factors if "window holds" in c]
