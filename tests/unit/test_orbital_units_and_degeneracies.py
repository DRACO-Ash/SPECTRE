"""Guards for two silent classes of orbital-mechanics defect.

Both were found by validating against published answers and physical
invariants, not by any existing test, and both survived a full green pipeline.

1. Angles converted twice. ``KeplerianElements`` stores inc, raan, argp and ta
   in DEGREES, and ten call sites in maneuvers.py passed them through
   ``math.degrees()`` again, multiplying every angle by 57.3. Plane-change
   delta-V came out 14 to 57 times too high, the J2 drift plan ran on a
   meaningless inclination, and the manoeuvre-direction classifier answered
   "normal" for almost any burn.

2. Degenerate element sets. Three orbits have an undefined classical element,
   and the converter returned zero instead of substituting the element that is
   defined. Round-tripping a state through elements and back moved it by up to
   78,460 km, and the worst case is circular equatorial, which is GEO.

Neither could be caught by an assertion on the shape of the answer, which is
all the previous tests made. Both are caught by asking whether the number is
right.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from spectre.astro.constants import MU_EARTH, R_EARTH
from spectre.astro.propagator import (
    KeplerianElements,
    StateVector,
    keplerian_to_state,
    state_to_keplerian,
)
from spectre.astro.tactical import plane_change

_EPOCH = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


class TestElementRoundTrip:
    """A state converted to elements and back must be the same state."""

    CASES = {
        "inclined-elliptical": (12000.0, 0.20, 45.0, 30.0, 60.0, 120.0),
        "leo-sun-synchronous": (7078.0, 0.0012, 98.2, 120.0, 90.0, 45.0),
        "molniya-heo": (26562.0, 0.74, 63.4, 90.0, 270.0, 10.0),
        # The three that were broken. The last is GEO.
        "circular-inclined": (8000.0, 0.0, 51.6, 200.0, 0.0, 300.0),
        "equatorial-elliptical": (26000.0, 0.30, 0.0, 0.0, 40.0, 100.0),
        "circular-equatorial-geo": (42164.0, 0.0, 0.0, 0.0, 0.0, 137.0),
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_the_state_survives_the_round_trip(self, name: str) -> None:
        a, ecc, inc, raan, argp, ta = self.CASES[name]
        original = keplerian_to_state(
            KeplerianElements(a=a, ecc=ecc, inc=inc, raan=raan, argp=argp, ta=ta, epoch=_EPOCH)
        )
        recovered = keplerian_to_state(state_to_keplerian(original))
        position_error_km = float(np.linalg.norm(recovered.r - original.r))
        assert position_error_km < 1e-3, (
            f"{name}: the round trip moved the satellite {position_error_km:,.1f} km. "
            "An undefined element must be replaced by the one that is defined "
            "(argument of latitude, longitude of periapsis, or true longitude), "
            "not by zero."
        )

    def test_a_geo_object_does_not_teleport(self) -> None:
        """The specific failure: 78,460 km, anywhere on the belt."""
        state = keplerian_to_state(
            KeplerianElements(a=42164.0, ecc=0.0, inc=0.0, raan=0.0, argp=0.0,
                              ta=137.0, epoch=_EPOCH)
        )
        elements = state_to_keplerian(state)
        assert elements.ta == pytest.approx(137.0, abs=1e-6), (
            "for a circular equatorial orbit the true longitude carries the position; "
            f"got {elements.ta}"
        )


class TestKeplerianElementsAreDegrees:
    """The unit contract the ten defective call sites broke."""

    def test_the_converter_returns_degrees_not_radians(self) -> None:
        elements = state_to_keplerian(
            keplerian_to_state(
                KeplerianElements(a=7078.0, ecc=0.001, inc=98.2, raan=120.0,
                                  argp=90.0, ta=45.0, epoch=_EPOCH)
            )
        )
        assert elements.inc == pytest.approx(98.2, abs=1e-6), (
            "inclination must come back in degrees. If this ever returns radians, "
            "every consumer that trusts the dataclass comment is silently wrong."
        )
        assert 0.0 <= elements.raan <= 360.0
        assert 0.0 <= elements.ta <= 360.0

    def test_no_call_site_converts_an_element_to_degrees_again(self) -> None:
        """Static guard: the defect was ten identical typos, so scan for it.

        Matched precisely, not by substring. An earlier version of this scan
        flagged ``math.degrees(sat.inclo)`` because ".inc" appears inside
        ".inclo" - but sgp4's Satrec fields really are radians and converting
        them is correct. A guard that fires on correct code gets disabled, and
        then it protects nothing.
        """
        import re
        from pathlib import Path

        # An attribute of KeplerianElements, which the dataclass documents as
        # degrees. Anchored with \b so .inc does not match .inclo, and sgp4's
        # Satrec (sat.*) is excluded because those fields are radians.
        pattern = re.compile(
            r"math\.degrees\(\s*(?!sat\.)(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
            r"(?:inc|raan|argp|ta)\b(?!_)"
        )
        astro = Path(__file__).resolve().parents[2] / "spectre" / "astro"
        offenders: list[str] = []
        for path in sorted(astro.glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "math.degrees(" not in line:
                    continue
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}: {stripped[:88]}")
        assert not offenders, (
            "these convert an angle that is already in degrees:\n  " + "\n  ".join(offenders)
        )

    def test_the_scan_can_actually_see_the_defect(self) -> None:
        """Prove the guard goes red, rather than trusting that it would."""
        import re

        pattern = re.compile(
            r"math\.degrees\(\s*(?!sat\.)(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
            r"(?:inc|raan|argp|ta)\b(?!_)"
        )
        # The exact lines that shipped.
        assert pattern.search("    delta_inc = math.degrees(kep_blue.inc - kep_red.inc)")
        assert pattern.search("        kep_red.a, kep_red.ecc, math.degrees(kep_red.inc),")
        assert pattern.search("    result = orbital_terrain(altitude, math.degrees(kep_red.inc))")
        # And must NOT fire on the correct sgp4 conversions next door.
        assert not pattern.search("    inc_deg    = math.degrees(sat.inclo)")
        assert not pattern.search("    argp_deg   = math.degrees(sat.argpo) % 360.0")
        assert not pattern.search("    return math.degrees(rate) * 86400.0")


class TestPlaneChangeCostIsPhysical:
    """delta-V = 2 v sin(di/2). The defect made this 14x to 57x too large."""

    @pytest.mark.parametrize(
        ("inclination_change_deg", "expected_m_s"),
        [(0.5, 26.8), (2.0, 107.3), (5.0, 268.2)],
    )
    def test_geo_plane_change_matches_the_closed_form(
        self, inclination_change_deg: float, expected_m_s: float
    ) -> None:
        radius = 42164.0
        result = plane_change(radius, inclination_change_deg, 0.0, MU_EARTH)
        speed = math.sqrt(MU_EARTH / radius)
        closed_form = 2.0 * speed * math.sin(math.radians(inclination_change_deg) / 2.0)
        assert result.optimal_delta_v * 1000.0 == pytest.approx(expected_m_s, rel=0.02)
        assert result.optimal_delta_v == pytest.approx(closed_form, rel=0.02), (
            "a pure inclination change costs 2 v sin(di/2); anything far above that "
            "means the angle arrived in the wrong units"
        )

    def test_a_small_plane_change_is_not_reported_as_kilometres_per_second(self) -> None:
        """The shape of the bug: a half-degree turn priced like a launch."""
        result = plane_change(42164.0, 0.5, 0.0, MU_EARTH)
        assert result.optimal_delta_v < 0.1, (
            f"a 0.5 degree plane change in GEO costs about 27 m/s; this reports "
            f"{result.optimal_delta_v * 1000:.0f} m/s"
        )


class TestPhysicalInvariants:
    """Cheap checks that would have caught a wide class of arithmetic error."""

    def test_circular_geo_period_is_a_sidereal_day(self) -> None:
        state = StateVector(
            epoch=_EPOCH,
            r=np.array([42164.0, 0.0, 0.0]),
            v=np.array([0.0, math.sqrt(MU_EARTH / 42164.0), 0.0]),
        )
        elements = state_to_keplerian(state)
        # 86,164.1 s is the sidereal day. The 42,164.0 km constant is rounded,
        # which costs about half a second; anything larger is an error.
        assert elements.period_s == pytest.approx(86164.1, abs=2.0)

    def test_a_circular_orbit_reports_zero_eccentricity(self) -> None:
        state = StateVector(
            epoch=_EPOCH,
            r=np.array([7000.0, 0.0, 0.0]),
            v=np.array([0.0, math.sqrt(MU_EARTH / 7000.0), 0.0]),
        )
        assert state_to_keplerian(state).ecc < 1e-12

    def test_altitude_is_measured_from_the_equatorial_radius(self) -> None:
        state = StateVector(epoch=_EPOCH, r=np.array([R_EARTH + 400.0, 0.0, 0.0]),
                            v=np.array([0.0, 7.67, 0.0]))
        assert state.altitude_km == pytest.approx(400.0, abs=1e-9)
