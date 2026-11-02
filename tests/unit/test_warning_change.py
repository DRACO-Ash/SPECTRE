"""What a burn changed in the warning an operator has (SPC-007, output 2 of 4).

Each class pins one rule of :mod:`spectre.domain.warning_change`. Figures are
set by hand so every expected sentence can be checked against the input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.domain.warning_change import (
    Change,
    burns_in_window,
    classify,
    compare,
    footer,
    headline,
    is_new_burn,
    least_warning_by_target,
    newest_unconfirmed,
)

_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def _hours(h: float) -> str:
    """A stand-in for format_tof_label: whole hours, or hours and minutes."""
    whole, minutes = int(h), round((h - int(h)) * 60)
    return f"{whole}h" if not minutes else f"{whole}h {minutes:02d}m"


def _entry(name: str, dv: float, tof: float) -> SimpleNamespace:
    return SimpleNamespace(target=SimpleNamespace(target_name=name), delta_v_m_s=dv, tof_hours=tof)


def _burn(start: datetime, end: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(burn_window=(start, end or start))


class TestClassify:
    """U1: one row's change, within a stated 15-minute tolerance."""

    @pytest.mark.parametrize(("before", "after", "expected"), [
        (None, 9.5, Change.NEWLY_IN_REACH),
        (14.0, None, Change.NO_LONGER_IN_REACH),
        (14.0, 3.0, Change.CUT),
        (3.0, 14.0, Change.LENGTHENED),
        (10.0, 9.8, Change.UNCHANGED),
        (10.0, 9.7, Change.CUT),
        (None, None, Change.UNCHANGED),
    ])
    def test_each_change(self, before: float | None, after: float | None, expected: Change) -> None:
        assert classify(before, after) is expected


class TestWarningDefinition:
    """U2: a target's warning is its fastest feasible intercept, as on the worst case card."""

    def test_the_least_flight_time_within_budget(self) -> None:
        entries = [_entry("A", 50.0, 20.0), _entry("A", 400.0, 3.0), _entry("A", 600.0, 1.0), _entry("B", 700.0, 2.0)]
        assert least_warning_by_target(entries, 500.0) == {"A": 3.0}


class TestHeadline:
    """U3 to U5: the main line, in the operator's words."""

    def test_one_burn_cut_and_newly_in_reach(self) -> None:
        rows = compare(
            [("BLUE-1", True), ("BLUE-7", True)],
            {"BLUE-1": 14.0}, {"BLUE-1": 3.0, "BLUE-7": 9.5},
        )
        assert headline(rows, 1, 500.0, _hours) == (
            "That burn cut your warning on BLUE-1 from 14h to 3h, and put BLUE-7 in reach with 9h 30m warning."
        )

    def test_two_burns_and_a_target_that_is_not_ours(self) -> None:
        rows = compare([("MANUAL-X", False)], {"MANUAL-X": 14.0}, {"MANUAL-X": 3.0})
        assert headline(rows, 2, 500.0, _hours) == "Those 2 burns cut the warning on MANUAL-X from 14h to 3h."

    def test_at_most_three_are_named_and_the_rest_counted(self) -> None:
        names = [f"B{i}" for i in range(5)]
        rows = compare([(n, True) for n in names], dict.fromkeys(names, 20.0), {n: float(i + 1) for i, n in enumerate(names)})
        line = headline(rows, 1, 500.0, _hours)
        assert line.count("cut your warning on") == 3
        assert line.endswith(" 2 more changed: see the table.")

    def test_a_lengthening_is_never_called_a_cut(self) -> None:
        """U4."""
        rows = compare([("BLUE-2", True), ("BLUE-3", True)], {"BLUE-2": 3.0, "BLUE-3": 5.0}, {"BLUE-2": 8.0, "BLUE-3": 5.1})
        assert headline(rows, 1, 500.0, _hours) == (
            "That burn did not shorten your warning on any of the 2 targets swept. Largest change: BLUE-2, 3h to 8h."
        )

    def test_nothing_in_reach_either_side(self) -> None:
        rows = compare([("A", True), ("B", True)], {}, {})
        assert headline(rows, 1, 500.0, _hours) == (
            "None of the 2 targets swept is in reach within 500 m/s, before or after that burn."
        )

    def test_the_shortest_warning_after_the_burn_is_named_first(self) -> None:
        """U5: B, cut to 3 h, leads; not A, the larger cut, nor C, unchanged at 1 h."""
        rows = compare([("A", True), ("B", True), ("C", True)], {"A": 20.0, "B": 4.0, "C": 1.0},
                       {"A": 9.0, "B": 3.0, "C": 1.0})
        assert headline(rows, 1, 500.0, _hours).startswith("That burn cut your warning on B from 4h to 3h")


class TestFooter:
    def test_it_counts_what_did_not_change(self) -> None:
        rows = compare([("A", True), ("B", True), ("C", True), ("D", True)], {"A": 14.0, "B": 5.0}, {"A": 3.0, "B": 5.0})
        assert footer(rows) == "1 other target unchanged; 2 out of reach before and after."


class TestWindow:
    """U6: a burn counts when the latest time it can have happened is inside the regime limit."""

    def test_an_undated_burn_whose_bracket_ends_inside_the_window(self) -> None:
        burn = _burn(_NOW - timedelta(hours=30), _NOW - timedelta(hours=20))
        assert burns_in_window([burn], _NOW, 24.0) == [burn]

    def test_a_dated_burn_past_the_limit(self) -> None:
        assert burns_in_window([_burn(_NOW - timedelta(hours=73))], _NOW, 72.0) == []


class TestOneAnnouncementPerBurn:
    """U7: a re-estimate of a burn already accounted for is not new."""

    @pytest.mark.parametrize("shift_minutes", [-2, 0])
    def test_a_redated_burn_inside_the_accounted_window_is_not_new(self, shift_minutes: int) -> None:
        accounted = _NOW - timedelta(hours=5)
        assert not is_new_burn(_burn(accounted + timedelta(minutes=shift_minutes)), accounted)

    def test_a_burn_starting_after_the_accounted_window_is_new(self) -> None:
        accounted = _NOW - timedelta(hours=5)
        assert is_new_burn(_burn(accounted + timedelta(minutes=1)), accounted)

    def test_with_nothing_accounted_every_burn_is_new(self) -> None:
        assert is_new_burn(_burn(_NOW - timedelta(days=30)), None)


class TestUnconfirmed:
    """U8: a candidate newer than the latest confirmed burn is named, not counted."""

    def test_a_newer_candidate_is_returned(self) -> None:
        newer = _burn(_NOW - timedelta(hours=1))
        older = _burn(_NOW - timedelta(hours=9))
        assert newest_unconfirmed([older, newer], _NOW - timedelta(hours=3)) is newer

    def test_an_older_candidate_is_not(self) -> None:
        assert newest_unconfirmed([_burn(_NOW - timedelta(hours=9))], _NOW - timedelta(hours=3)) is None
