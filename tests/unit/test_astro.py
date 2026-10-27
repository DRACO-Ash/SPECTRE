"""Tests for spectre.astro — transfers, Lambert, propagator, events, maneuvers."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro.constants import MU_EARTH, R_EARTH
from spectre.astro.events import find_orbital_events
from spectre.astro.lambert import solve_lambert
from spectre.astro.maneuvers import hohmann_intercept, lambert_intercept
from spectre.astro.propagator import (
    KeplerianElements,
    TLEOrbit,
    keplerian_to_state,
    state_to_keplerian,
)
from spectre.astro.transfers import bielliptic, hohmann

# ── ISS TLE for propagation tests ──────────────────────────────────────────

ISS_TLE = """\
1 25544U 98067A   24045.51891898  .00016717  00000-0  30143-3 0  9993
2 25544  51.6412  67.2858 0003399 357.5543 175.2785 15.49571089439072
"""


# ── Transfer tests ─────────────────────────────────────────────────────────

class TestHohmann:
    def test_leo_to_geo(self):
        """Vallado, Fundamentals of Astrodynamics and Applications, Example 6-1.

        191.344 km to 35,781.349 km altitude: total 3.935224 km/s in 5.256713 h.
        Bands of about 6 per cent stood here before (audit F-070).
        """
        result = hohmann(R_EARTH + 191.344, R_EARTH + 35781.349)

        assert result.method == "hohmann"
        assert result.total_delta_v == pytest.approx(3.935224, abs=1e-5)
        assert result.transfer_time_s / 3600 == pytest.approx(5.256713, abs=1e-5)

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
        # Vis-viva closed form for the three burns, derived here (audit F-070;
        # the totals above were only asserted positive).
        def vv(r: float, a: float) -> float:
            return math.sqrt(MU_EARTH * (2.0 / r - 1.0 / a))

        a1, a2 = (r1 + rb) / 2.0, (r2 + rb) / 2.0
        expected = (
            abs(vv(r1, a1) - math.sqrt(MU_EARTH / r1))
            + abs(vv(rb, a2) - vv(rb, a1))
            + abs(vv(r2, a2) - math.sqrt(MU_EARTH / r2))
        )
        assert result.total_delta_v == pytest.approx(expected, rel=1e-12)
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
        # A quarter period between points 90 deg apart on the circle is the
        # circular orbit itself, so the departure velocity is the circular
        # velocity, exactly. This was a 15 per cent speed band (audit F-070).
        v_circ = math.sqrt(MU_EARTH / r_circ)
        assert np.allclose(sol.v1, [0.0, v_circ, 0.0], atol=1e-7)  # 0.1 mm/s, above the solver tolerance

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
    def test_sgp4_verification_case_00005_at_epoch(self):
        """Vallado et al. (2006) SGP4-VER, satellite 00005 at t = 0, TEME.

        Pinned to 1 m. The propagator was checked only by an altitude band
        (audit F-070).
        """
        tle = (
            "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753\n"
            "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667"
        )
        epoch = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(days=179.78495062 - 1.0)
        sv = TLEOrbit(tle).propagate(epoch)
        assert np.allclose(sv.r, [7022.46529266, -1400.08296755, 0.03995155], atol=1e-3)
        assert np.allclose(sv.v, [1.893841015, 6.405893759, 4.534807250], atol=1e-6)

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
