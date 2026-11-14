"""Alpha-5 catalogue numbers are read the same way everywhere (SPC-026).

Numbers from 100,000 up are written in the five columns of line 1 as a letter
and four digits. The letter stands for 10 to 33 in order, with I and O left
out so they cannot be mistaken for 1 and 0: A0001 is 100001, H9999 is 179999,
J0000 is 180000, N9999 is 229999, P0000 is 230000 and Z9999 is 339999.

``satno_from_tle`` read only five digits, so an Alpha-5 object had no number
in the sweep, the intercept intel lookup, the element-set refresh and the
decision binder, while the pattern-of-life parser read it. A letter that is
not an Alpha-5 letter (I, O, lower case) is still unreadable: None, never a
guessed number.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.astro.pattern_of_life import _catalogue_number, parse_tle_history_counted
from spectre.data.intel import satno_from_tle
from spectre.domain.models import BlueAsset, RedTrack, ThreatTarget
from spectre.web.app import templates
from spectre.web.decision_binding import BindOutcome, bind_scenario
from spectre.web.planning_state import SessionState
from spectre.web.routes import threat
from tests.unit.test_elset_freshness import _checksummed, _tle

_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)

_READABLE = [
    ("A0001", 100001),
    ("A0000", 100000),
    ("H9999", 179999),
    ("J0000", 180000),
    ("N9999", 229999),
    ("P0000", 230000),
    ("Z9999", 339999),
    ("25544", 25544),
    ("00005", 5),
]

#: Short letter fields (" A001", "A001 ", "  A01") are here so a weakened width
#: check, which would read each as 100001, cannot pass: Alpha-5 is a letter
#: and exactly 4 digits.
_UNREADABLE = [
    "I0001", "O0001", "a0001", "A-001", "A12X4", "1_234", "-1234", "     ",
    " A001", "A001 ", "  A01",
]


def _numbered(field: str, epoch: datetime = _NOW) -> str:
    """A valid element set at *epoch* with *field* in columns 3 to 7 of both lines, checksums recomputed."""
    return "\n".join(
        _checksummed(f"{line[:2]}{field}{line[7:]}") for line in _tle(epoch, satno=50322).split("\n")
    )


@pytest.mark.parametrize(("field", "number"), _READABLE)
def test_an_alpha5_or_numeric_field_is_read_exactly(field: str, number: int) -> None:
    assert satno_from_tle(_numbered(field)) == number


@pytest.mark.parametrize("field", _UNREADABLE)
def test_a_field_that_is_not_a_catalogue_number_is_unreadable(field: str) -> None:
    assert satno_from_tle(_numbered(field)) is None


def test_a_name_line_that_looks_like_line_1_does_not_hide_the_number() -> None:
    """A three-line set whose name begins "1 " is read past, to line 1 itself."""
    tle = "1 ROCKET BODY\n" + _numbered("A0001")
    assert satno_from_tle(tle) == 100001


@pytest.mark.parametrize(("field", "number"), _READABLE)
def test_the_history_parser_reads_the_same_number(field: str, number: int) -> None:
    line1 = _numbered(field).split("\n")[0]
    assert _catalogue_number(line1) == number


@pytest.mark.parametrize("field", _UNREADABLE)
def test_the_history_parser_refuses_the_same_fields(field: str) -> None:
    line1 = _numbered(field).split("\n")[0]
    with pytest.raises(ValueError, match="catalogue number"):
        _catalogue_number(line1)


def test_an_alpha5_history_is_kept_for_its_own_number() -> None:
    records, counts = parse_tle_history_counted(_numbered("A0001"), satno=100001)
    assert (len(records), counts.other_object, counts.malformed) == (1, 0, 0)


def test_the_binder_catches_two_element_sets_of_one_alpha5_object() -> None:
    state = SessionState()
    state.red_tracks = [RedTrack("RX", _numbered("A0001", _NOW - timedelta(hours=1)))]
    state.blue_assets = [BlueAsset("BY", _numbered("A0001", _NOW - timedelta(hours=3)))]
    assert state.red_tracks[0].tle != state.blue_assets[0].tle, "two different element sets"
    assert bind_scenario(state, "RX", "BY", _NOW) == BindOutcome(
        None, "Red and blue are the same object (SATNO 100001). Bind two different objects.",
    )


def test_the_binder_keeps_two_alpha5_objects_apart() -> None:
    state = SessionState()
    state.red_tracks = [RedTrack("RX", _numbered("A0001", _NOW - timedelta(hours=1)))]
    state.blue_assets = [BlueAsset("BY", _numbered("J0001", _NOW - timedelta(hours=1)))]
    outcome = bind_scenario(state, "RX", "BY", _NOW)
    assert outcome.problem is None
    assert outcome.binding is not None and outcome.binding.red is not None and outcome.binding.blue is not None
    assert (outcome.binding.red.satno, outcome.binding.blue.satno) == (100001, 180001)


def test_a_manual_sweep_target_carries_its_alpha5_number() -> None:
    targets: list[ThreatTarget] = []
    state = SimpleNamespace(manual_sweep_tles=[{"name": "A5", "tle": _numbered("A0001"), "confidence": "HIGH"}])
    threat._append_manual_targets(state, targets)
    assert [t.target_satno for t in targets] == ["100001"]


def test_the_manual_target_list_shows_the_number_the_sweep_uses() -> None:
    manual = [
        {"name": "A5", "tle": _numbered("A0001"), "confidence": "HIGH"},
        {"name": "BAD", "tle": _numbered("I0001"), "confidence": "LOW"},
        {"name": "ISS", "tle": _numbered("25544"), "confidence": "MEDIUM"},
    ]
    out = templates.env.get_template("partials/sweep_manual_tles.html").render(manual_tles=manual, error=None)
    cells = re.findall(r'<td[^>]*font-family:monospace">\s*(.*?)\s*</td>', out, re.DOTALL)
    assert cells == ["100001", "unreadable", "25544"]
