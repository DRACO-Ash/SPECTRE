"""Close approaches are found and measured at their closest (audit F-115).

The access search stepped a fixed 60 s against a 500 km threshold. Two
objects closing at 15 km/s with a 300 km miss are inside 500 km for about
53 s, so the step skipped encounters outright, and the minimum it reported
was the nearest sample, not the closest approach. A failed propagation
neither closed nor ended a window, and the horizon was fixed at 24 h.

The reference here is independent of the planner: SGP4 sampled every
0.1 s across each encounter.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
from sgp4.api import Satrec, jday

from spectre.domain.models import BlueAsset, RedTrack, RunConfig
from spectre.domain.scenario import _ACCESS_RANGE_KM, ScenarioPlanner

_EPOCH = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_MU = 398600.4418


def _mean_motion(alt_km: float) -> float:
    a = 6378.137 + alt_km
    return math.sqrt(_MU / a**3) * 86400.0 / (2 * math.pi)


def _tle(satno: int, inc: float, raan: float, anomaly: float, alt_km: float) -> str:
    line1 = f"1 {satno:05d}U 26001A   26290.50000000  .00000000  00000-0  00000-0 0  9990"
    line2 = f"2 {satno:05d} {inc:8.4f} {raan:8.4f} 0001000   0.0000 {anomaly:8.4f} {_mean_motion(alt_km):11.8f}    10"
    return f"{line1}\n{line2}"


# One plane, flown in opposite senses, 300 km apart in altitude.
_BLUE = _tle(90001, 51.6, 200.0, 0.0, 420.0)
_RED = _tle(90002, 128.4, 20.0, 90.0, 720.0)


def _range(a: Satrec, b: Satrec, t: datetime) -> float:
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
    _, ra, _ = a.sgp4(jd, fr)
    _, rb, _ = b.sgp4(jd, fr)
    return float(np.linalg.norm(np.subtract(ra, rb)))


def _reference_encounters(hours: float) -> list[tuple[datetime, float]]:
    """(time, range) of each closest approach under 500 km, sampled at 0.1 s near each."""
    a = Satrec.twoline2rv(*_BLUE.splitlines())
    b = Satrec.twoline2rv(*_RED.splitlines())
    out: list[tuple[datetime, float]] = []
    t, stop = _EPOCH, _EPOCH + timedelta(hours=hours)
    inside: list[datetime] = []
    while t <= stop:
        if _range(a, b, t) < _ACCESS_RANGE_KM:
            inside.append(t)
        elif inside:
            fine = [inside[0] - timedelta(seconds=1) + timedelta(seconds=0.1 * k)
                    for k in range(int((inside[-1] - inside[0]).total_seconds() * 10) + 21)]
            out.append(min(((ft, _range(a, b, ft)) for ft in fine), key=lambda p: p[1]))
            inside = []
        t += timedelta(seconds=1)
    return out


def _plan(hours: float) -> list:  # type: ignore[type-arg]
    config = RunConfig(operator="test", source="MANUAL", timestamp=_EPOCH, horizon_hours=hours)
    return ScenarioPlanner(config).plan([BlueAsset(name="B", tle=_BLUE)], [RedTrack(name="R", tle=_RED)])


def test_every_encounter_is_found_at_its_closest() -> None:
    reference = _reference_encounters(3.0)
    assert len(reference) >= 3, "the geometry gives a fast encounter twice an orbit"
    windows = _plan(3.0)
    assert len(windows) == len(reference)
    for (tca, miss), window in zip(reference, windows, strict=True):
        assert window.start <= tca <= window.end
        assert abs(window.min_range_km - miss) < 1.0


def test_the_horizon_comes_from_the_run_config() -> None:
    assert RunConfig(operator="o", source="s").horizon_hours == 24.0
    short = _plan(1.0)
    assert short
    assert all(w.end <= _EPOCH + timedelta(hours=1) for w in short)
