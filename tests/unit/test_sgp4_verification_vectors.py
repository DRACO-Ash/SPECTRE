"""SPECTRE's SGP4 wrapper against the published verification vectors (SPC-197, evaluation finding F-06, gate G7).

The sgp4 package ships the verification set of Vallado, Crawford, Hujsak and
Kelso, "Revisiting Spacetrack Report #3" (AIAA 2006-6753): SGP4-VER.TLE holds
33 element sets, each with a start, stop and step in minutes after its column
69, and tcppver.out holds the C++ reference's TEME position (km) and velocity
(km/s) at every time it lists. Every case goes through TLEOrbit, the wrapper
the rest of SPECTRE propagates with, on the gravity model it uses: WGS-72, the
default of Satrec.twoline2rv and the model the vectors were made with. The
wrapper checks no checksum, so it takes every case and none is skipped.

The bound is the wrapper's time quantum: it takes a datetime, which holds whole
microseconds, so an instant it is handed may be rounded by up to 1
microsecond. For an orbit whose position moves at its printed speed, that
costs at most the set's fastest speed, 10.3 km/s, times 1e-6 s: 1.03e-5 km,
and its velocity changes by at most its largest acceleration, about 0.0098
km/s^2 at its lowest point, times 1e-6 s: under 1e-8 km/s. The vectors are
printed to 1e-8 km and 1e-9 km/s. Hence 2e-5 km and 5e-8 km/s, compared as the
size of each difference. On this set the quantum is never spent: every epoch
is written to 1e-8 day, a whole 864 microseconds, and every listed time is a
whole number of microseconds, so the wrapper is handed each instant exactly (a
test checks both). Measured at this commit, the largest differences are
1.2e-7 km and 8.5e-10 km/s. The speed argument does not hold for case 33333
(eccentricity 0.995 and a perigee inside the Earth), where SGP4's position
moves 5e-5 to 1.1e-3 km in a microsecond, far faster than its own printed
velocity: that case is held to the bound by the exact instants alone.

Seven cases end in an SGP4 error: the vectors stop there, and the wrapper must
raise at the same time with the same code. Where the error is at the epoch, the
C++ reference printed the previous case's state in place of one, so that line
is not compared. The library is read only for each case's epoch, its error
times and codes; every state compared is the wrapper's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import sgp4
from sgp4.api import WGS72, Satrec

from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import TLEOrbit

_HERE = Path(sgp4.__file__).parent
_ELEMENTS = _HERE / "SGP4-VER.TLE"
_VECTORS = _HERE / "tcppver.out"

#: The wrapper's time quantum: a datetime holds whole microseconds.
_QUANTUM_S = 1e-6
POSITION_BOUND_KM = 2e-5
VELOCITY_BOUND_KM_S = 5e-8
#: The precision tcppver.out prints position and velocity to.
_PRINTED_KM = 1e-8
_PRINTED_KM_S = 1e-9
#: The cases the verification set ends in an SGP4 error, as the library's own tests list their codes.
_ERROR_CASES = 7
_CASES = 33
_JD_2000 = 2451544.5   # the Julian date of 2000-01-01 00:00 UTC
_TLE_COLUMNS = 69
_SECONDS_PER_DAY = 86400
_MICROSECONDS_PER_S = 1_000_000
#: A TLE's 2-digit year: under 57 is 20xx, else 19xx.
_PIVOT_YEAR = 57


@dataclass
class _Case:
    """One element set, the times its line 2 schedules, and the vectors tcppver.out lists for it."""

    line1: str
    line2: str
    schedule: tuple[float, float, float]
    vectors: list[tuple[float, np.ndarray, np.ndarray]] = field(default_factory=list)

    @property
    def satnum(self) -> int:
        return int(self.line1[2:7])

    @property
    def epoch(self) -> datetime:
        """The element set's epoch as the library reads it, to the microsecond."""
        sat = Satrec.twoline2rv(self.line1, self.line2, WGS72)
        days = (sat.jdsatepoch - _JD_2000) + sat.jdsatepochF
        return datetime(2000, 1, 1, tzinfo=UTC) + timedelta(days=days)

    def scheduled_minutes(self) -> list[float]:
        """The times line 2 schedules, as the C++ reference walks them: start, each step to stop, and stop."""
        start, stop, step = self.schedule
        times = [start + k * step for k in range(int(math.floor((stop - start) / step + 1e-9)) + 1)]
        return times if math.isclose(times[-1], stop) else [*times, stop]


def _cases() -> list[_Case]:
    lines = _ELEMENTS.read_text(encoding="ascii").splitlines()
    cases = []
    for k, line in enumerate(lines):
        if line.startswith("1 "):
            line2 = lines[k + 1]
            start, stop, step = (float(x) for x in line2[_TLE_COLUMNS:].split())
            cases.append(_Case(line[:_TLE_COLUMNS], line2[:_TLE_COLUMNS], (start, stop, step)))
    blocks: list[tuple[int, list[tuple[float, np.ndarray, np.ndarray]]]] = []
    for line in _VECTORS.read_text(encoding="ascii").replace("\r", "").splitlines():
        fields = line.split()
        if fields[1] == "xx":
            blocks.append((int(fields[0]), []))
            continue
        values = [float(x) for x in fields[:7]]
        blocks[-1][1].append((values[0], np.array(values[1:4]), np.array(values[4:7])))
    assert [c.satnum for c in cases] == [satnum for satnum, _ in blocks]
    for case, (_, vectors) in zip(cases, blocks, strict=True):
        case.vectors = vectors
    return cases


def _library_error(case: _Case) -> tuple[float, int] | None:
    """The first scheduled time at which the library reports an SGP4 error, with its code; None when it never does."""
    sat = Satrec.twoline2rv(case.line1, case.line2, WGS72)
    for minutes in case.scheduled_minutes():
        code, _, _ = sat.sgp4_tsince(minutes)
        if code != 0:
            return minutes, code
    return None


pytestmark = pytest.mark.skipif(
    not (_ELEMENTS.is_file() and _VECTORS.is_file()),
    reason="the installed sgp4 package does not ship SGP4-VER.TLE and tcppver.out",
)


def _whole_microseconds(seconds: Fraction) -> bool:
    return (seconds * _MICROSECONDS_PER_S).denominator == 1


def test_the_set_hands_the_wrapper_each_instant_exactly() -> None:
    """Every epoch, written to 1e-8 day, and every listed time is a whole number of microseconds, and the epoch the
    wrapper is handed is the one written: no instant is rounded, so the quantum is never spent on this set."""
    cases = _cases()
    for case in cases:
        written = Fraction(case.line1[18:32].strip()[2:])   # day of year and its fraction, after the 2-digit year
        assert _whole_microseconds((written - int(written)) * _SECONDS_PER_DAY), case.satnum
        year = int(case.line1[18:20])
        start = datetime(year + (2000 if year < _PIVOT_YEAR else 1900), 1, 1, tzinfo=UTC)
        micro = (written - 1) * _SECONDS_PER_DAY * _MICROSECONDS_PER_S
        assert case.epoch == start + timedelta(microseconds=int(micro)), case.satnum
        assert all(_whole_microseconds(Fraction(str(minutes)) * 60) for minutes, _, _ in case.vectors), case.satnum


def test_the_bound_covers_a_microsecond_at_the_fastest_and_most_accelerated_point_in_the_set() -> None:
    """For an orbit moving at its printed speed, the bound covers a microsecond at the set's fastest speed and its
    largest acceleration. Case 33333 is the exception the module docstring names: it rests on exact instants."""
    states = [(r, v) for case in _cases() for _, r, v in case.vectors]
    fastest = max(float(np.linalg.norm(v)) for _, v in states)
    lowest = min(float(np.linalg.norm(r)) for r, _ in states)
    assert fastest * _QUANTUM_S + _PRINTED_KM < POSITION_BOUND_KM
    assert MU_EARTH / lowest**2 * _QUANTUM_S + _PRINTED_KM_S < VELOCITY_BOUND_KM_S


def test_every_listed_state_matches_through_the_wrapper() -> None:
    cases = _cases()
    assert len(cases) == _CASES
    compared = 0
    for case in cases:
        orbit, epoch = TLEOrbit(f"{case.line1}\n{case.line2}"), case.epoch
        error = _library_error(case)
        for minutes, r, v in case.vectors:
            if error is not None and error[0] == 0.0 == minutes:
                continue   # the C++ reference printed the previous case's state here
            state = orbit.propagate(epoch + timedelta(minutes=minutes))
            assert np.linalg.norm(state.r - r) < POSITION_BOUND_KM, (case.satnum, minutes)
            assert np.linalg.norm(state.v - v) < VELOCITY_BOUND_KM_S, (case.satnum, minutes)
            compared += 1
    assert compared > 600


def test_each_case_the_library_ends_in_an_error_raises_in_the_wrapper_at_the_same_time() -> None:
    ended = [(case, error) for case in _cases() if (error := _library_error(case)) is not None]
    assert len(ended) == _ERROR_CASES
    for case, (minutes, code) in ended:
        orbit = TLEOrbit(f"{case.line1}\n{case.line2}")
        with pytest.raises(RuntimeError, match=f"SGP4 error code {code} "):
            orbit.propagate(case.epoch + timedelta(minutes=minutes))
        assert all(listed < minutes or listed == minutes == 0.0 for listed, _, _ in case.vectors), case.satnum
