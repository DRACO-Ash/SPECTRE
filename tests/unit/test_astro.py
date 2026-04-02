"""Tests for sipc.astro — transfers, Lambert, propagator, events, maneuvers."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from sipc.astro.constants import MU_EARTH, R_EARTH
from sipc.astro.events import find_orbital_events
from sipc.astro.lambert import solve_lambert
from sipc.astro.maneuvers import hohmann_intercept, lambert_intercept
from sipc.astro.propagator import (
    KeplerianElements,
    TLEOrbit,
    keplerian_to_state,
    state_to_keplerian,
)
from sipc.astro.transfers import bielliptic, hohmann

# ── ISS TLE for propagation tests ──────────────────────────────────────────

ISS_TLE = """\
1 25544U 98067A   24045.51891898  .00016717  00000-0  30143-3 0  9993
2 25544  51.6412  67.2858 0003399 357.5543 175.2785 15.49571089439072
"""


# ── Transfer tests ─────────────────────────────────────────────────────────

class TestHohmann:
    def test_leo_to_geo(self):
        """LEO (300 km) → GEO (35 786 km) — classic textbook case."""
        r1 = R_EARTH + 300.0
        r2 = R_EARTH + 35786.0
        result = hohmann(r1, r2)

        assert result.method == "hohmann"
        # ΔV₁ ≈ 2.46 km/s, ΔV₂ ≈ 1.48 km/s, total ≈ 3.94 km/s
        assert 2.3 < result.delta_v_1 < 2.6
        assert 1.3 < result.delta_v_2 < 1.6
        assert 3.7 < result.total_delta_v < 4.1
        # Transfer time ≈ 5.26 hours
        assert 5.0 < result.transfer_time_s / 3600 < 5.5

    def test_same_orbit_zero_dv(self):
        r = R_EARTH + 500.0
        result = hohmann(r, r)
        assert result.total_delta_v == pytest.approx(0.0, abs=1e-10)


class TestBielliptic:
    def test_basic(self):
        r1 = R_EARTH + 300.0
        r2 = R_EARTH + 35786.0
        rb = R_EARTH + 100000.0
        result = bielliptic(r1, r2, rb)

        assert result.method == "bielliptic"
        assert result.delta_v_3 > 0
        assert result.total_delta_v > 0
        # Bi-elliptic takes longer than Hohmann for this case.
        hoh = hohmann(r1, r2)
        assert result.transfer_time_s > hoh.transfer_time_s


# ── Lambert tests ──────────────────────────────────────────────────────────

class TestLambert:
    def test_coplanar_short_arc(self):
        """Two positions on a circular LEO, 90° apart."""
        r_circ = R_EARTH + 400.0
        r1 = np.array([r_circ, 0, 0])
        r2 = np.array([0, r_circ, 0])

        # Quarter-period for a circular orbit.
        period = 2 * math.pi * math.sqrt(r_circ ** 3 / MU_EARTH)
        tof = period / 4.0

        sol = solve_lambert(r1, r2, tof)

        assert sol.v1.shape == (3,)
        assert sol.v2.shape == (3,)
        # For a circular orbit the speed should be ≈ sqrt(mu/r).
        v_circ = math.sqrt(MU_EARTH / r_circ)
        assert np.linalg.norm(sol.v1) == pytest.approx(v_circ, rel=0.15)

    def test_negative_tof_raises(self):
        with pytest.raises(ValueError, match="positive"):
            solve_lambert(np.array([7000, 0, 0]), np.array([0, 7000, 0]), -100)

    def test_delta_v_with_initial_velocity(self):
        r_circ = R_EARTH + 400.0
        r1 = np.array([r_circ, 0, 0])
        r2 = np.array([0, r_circ, 0])
        period = 2 * math.pi * math.sqrt(r_circ ** 3 / MU_EARTH)
        tof = period / 4.0

        v_init = np.array([0, math.sqrt(MU_EARTH / r_circ), 0])
        sol = solve_lambert(r1, r2, tof, v1_initial=v_init)

        # Quarter-orbit Lambert arc differs from circular — ΔV is moderate.
        assert sol.delta_v1_mag < 3.0  # km/s


# ── Propagator tests ──────────────────────────────────────────────────────

class TestTLEOrbit:
    def test_propagate_returns_state(self):
        orbit = TLEOrbit(ISS_TLE)
        epoch = datetime(2024, 2, 14, 12, 0, 0, tzinfo=UTC)
        sv = orbit.propagate(epoch)

        assert sv.r.shape == (3,)
        assert sv.v.shape == (3,)
        # ISS is in LEO: altitude ~ 400 km.
        assert 200 < sv.altitude_km < 500

    def test_propagate_range(self):
        orbit = TLEOrbit(ISS_TLE)
        start = datetime(2024, 2, 14, 12, 0, 0, tzinfo=UTC)
        stop = start + timedelta(hours=1)
        states = orbit.propagate_range(start, stop, step_s=120)

        assert len(states) > 20
        # All altitudes should be LEO.
        for sv in states:
            assert 150 < sv.altitude_km < 600

    def test_keplerian_roundtrip(self):
        orbit = TLEOrbit(ISS_TLE)
        epoch = datetime(2024, 2, 14, 12, 0, 0, tzinfo=UTC)
        sv = orbit.propagate(epoch)
        kep = state_to_keplerian(sv)

        # ISS: a ≈ 6778 km, inc ≈ 51.6°, ecc near 0.
        assert 6700 < kep.a < 6900
        assert 50 < kep.inc < 53
        assert kep.ecc < 0.01

    def test_bad_tle_raises(self):
        with pytest.raises(ValueError):
            TLEOrbit("not a tle")


class TestKeplerianConversion:
    def test_roundtrip(self):
        """Keplerian → state → Keplerian should be identity."""
        elem = KeplerianElements(
            a=7000.0, ecc=0.01, inc=45.0, raan=90.0, argp=30.0, ta=60.0,
            epoch=datetime(2024, 1, 1, tzinfo=UTC),
        )
        sv = keplerian_to_state(elem)
        recovered = state_to_keplerian(sv)

        assert recovered.a == pytest.approx(elem.a, rel=1e-6)
        assert recovered.ecc == pytest.approx(elem.ecc, abs=1e-6)
        assert recovered.inc == pytest.approx(elem.inc, abs=0.01)
        assert recovered.raan == pytest.approx(elem.raan, abs=0.01)
        assert recovered.argp == pytest.approx(elem.argp, abs=0.1)
        assert recovered.ta == pytest.approx(elem.ta, abs=0.1)


# ── Events tests ──────────────────────────────────────────────────────────

class TestOrbitalEvents:
    def test_finds_events(self):
        start = datetime(2024, 2, 14, 0, 0, 0, tzinfo=UTC)
        stop = start + timedelta(hours=3)
        events = find_orbital_events(ISS_TLE, start, stop)

        assert len(events) > 0
        # ISS orbits ~every 92 min, so 3 hours ≈ 2 orbits → multiple events.
        types_found = {e.event_type for e in events}
        assert len(types_found) >= 2  # Should find at least 2 event types.

    def test_bad_tle_returns_empty(self):
        events = find_orbital_events("garbage", datetime.now(tz=UTC), datetime.now(tz=UTC) + timedelta(hours=1))
        assert events == []


# ── Maneuver integration tests ────────────────────────────────────────────

# Second TLE for intercept tests — a different satellite.
TARGET_TLE = """\
1 36516U 10013A   24045.50000000  .00000072  00000-0  24411-4 0  9993
2 36516  92.0246 175.8413 0006291 289.5072  70.5374 14.88063637744413
"""


class TestLambertIntercept:
    def test_basic_intercept(self):
        t0 = datetime(2024, 2, 14, 12, 0, 0, tzinfo=UTC)
        sol = lambert_intercept(
            red_tle=ISS_TLE,
            blue_tle=TARGET_TLE,
            manoeuvre_start=t0,
            tof_s=3600.0,  # 1-hour transfer
        )

        assert sol.method == "lambert"
        assert len(sol.burns) == 2
        assert sol.total_delta_v > 0
        assert sol.burns[0].epoch == t0
        assert sol.arrival_epoch == t0 + timedelta(seconds=3600)

    def test_with_coast(self):
        t0 = datetime(2024, 2, 14, 12, 0, 0, tzinfo=UTC)
        sol = lambert_intercept(
            red_tle=ISS_TLE,
            blue_tle=TARGET_TLE,
            manoeuvre_start=t0,
            tof_s=3600.0,
            coast_s=600.0,
        )
        # First burn should be at t0 + coast.
        assert sol.burns[0].epoch == t0 + timedelta(seconds=600)


class TestHohmannIntercept:
    def test_basic(self):
        t0 = datetime(2024, 2, 14, 12, 0, 0, tzinfo=UTC)
        sol = hohmann_intercept(
            red_tle=ISS_TLE,
            blue_tle=TARGET_TLE,
            manoeuvre_start=t0,
        )

        assert sol.method == "hohmann"
        assert len(sol.burns) == 2
        assert sol.total_delta_v > 0
