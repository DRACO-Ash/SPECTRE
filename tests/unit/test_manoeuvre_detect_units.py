"""Manoeuvre detection must hand classify_manoeuvre angles in degrees, once.

KeplerianElements already stores inclination and RAAN in degrees. Passing them
through ``degrees()`` again multiplied every angle by 57.3, so TLE noise read as
a plane change of hundreds of m/s (audit F-001). A pure 0.1 degree inclination
trim on a circular orbit costs 2 v sin(di/2) (Curtis section 6.10), which this
test pins to within 1 per cent.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import StateVector

_R = 7000.0
_V = math.sqrt(MU_EARTH / _R)


class _StandIn:
    """A TLEOrbit stand-in: one fixed circular state and an epoch."""

    def __init__(self, inc_deg: float) -> None:
        i = math.radians(inc_deg)
        self._r = np.array([_R, 0.0, 0.0])
        self._v = _V * np.array([0.0, math.cos(i), math.sin(i)])
        self._sat = SimpleNamespace(jdsatepoch=2461140.5)

    def propagate(self, epoch: datetime) -> StateVector:
        return StateVector(epoch=epoch, r=self._r, v=self._v)


def test_a_tenth_of_a_degree_trim_is_priced_as_one(monkeypatch: pytest.MonkeyPatch) -> None:
    by_tle = {"BEFORE": _StandIn(51.6), "AFTER": _StandIn(51.7)}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])

    solution = maneuvers.manoeuvre_detect_intercept("BEFORE", "AFTER", datetime(2026, 4, 10, tzinfo=UTC))

    expected_km_s = 2.0 * _V * math.sin(math.radians(0.1) / 2.0)
    assert solution.total_delta_v == pytest.approx(expected_km_s, rel=0.01), (
        f"{solution.total_delta_v * 1000:.1f} m/s for a 0.1 deg trim; "
        f"{expected_km_s * 1000:.1f} m/s expected. About 57x means the angle was converted twice."
    )
