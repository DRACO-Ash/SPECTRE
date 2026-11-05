"""Astro edges the mutation run found unpinned, each one a place a real defect could hide (SPC-071).

docs/MUTATION-REPORT.md lists every surviving mutant in spectre/astro. These
are the ones whose change would reach an operator's figures or flags: the
element set the sweep re-solves with when it shifts an orbit along track, the
closest-approach search's default grid, which encounter it reports and whether
it calls a point the window's edge, and the bounds of the transfer formulas.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spectre.astro.along_track import shift_along_track
from spectre.astro.closest_approach import closest_approach
from spectre.astro.constants import MU_EARTH, R_EARTH, classify_orbit_regime
from spectre.astro.propagator import regime_from_tle
from spectre.astro.tactical import graveyard_transfer
from spectre.astro.transfers import bielliptic, hohmann

# The ISS element set of 2008-09-20, the standard worked example, checksums valid on both lines.
_LINE1 = "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927"
_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"


def _checksum(line: str) -> int:
    """The TLE checksum, written out independently: digits at face value, each minus sign as 1, modulo 10."""
    return sum(int(c) if c.isdigit() else int(c == "-") for c in line[:68]) % 10


def _sma_km(line2: str) -> float:
    mean_motion = float(line2[52:63]) * 2.0 * math.pi / 86_400.0
    return float((MU_EARTH / mean_motion**2) ** (1.0 / 3.0))


class TestShiftingAlongTrack:
    def test_the_worked_example_is_valid_to_start_with(self) -> None:
        assert (_checksum(_LINE1), _checksum(_LINE2)) == (int(_LINE1[68]), int(_LINE2[68]))

    def test_no_shift_returns_the_element_set_unchanged_checksum_included(self) -> None:
        assert shift_along_track(f"{_LINE1}\n{_LINE2}", 0.0) == f"{_LINE1}\n{_LINE2}"

    def test_a_named_three_line_set_keeps_its_name_and_first_line(self) -> None:
        shifted = shift_along_track(f"ISS (ZARYA)\n{_LINE1}\n{_LINE2}", 100.0).splitlines()
        assert shifted[:2] == ["ISS (ZARYA)", _LINE1]
        assert len(shifted) == 3
        assert shifted[2][:43] == _LINE2[:43] and shifted[2][51:68] == _LINE2[51:68]

    @pytest.mark.parametrize("km", [25.0, -40.0, 500.0])
    def test_the_shifted_line_carries_a_valid_checksum(self, km: float) -> None:
        line2 = shift_along_track(f"{_LINE1}\n{_LINE2}", km).splitlines()[-1]
        assert len(line2) == 69
        assert int(line2[68]) == _checksum(line2)

    def test_an_anomaly_carried_past_360_degrees_wraps(self) -> None:
        km = _sma_km(_LINE2) * math.radians(40.0)
        line2 = shift_along_track(f"{_LINE1}\n{_LINE2}", km).splitlines()[-1]
        assert float(line2[43:51]) == pytest.approx((325.0288 + 40.0) % 360.0, abs=1e-3)


def _dip(centre_s: float, half_width_s: float) -> object:
    """1000 km everywhere but a V of the given half-width, reaching 0 km at *centre_s*."""
    def separation(t: float) -> float:
        inside = half_width_s - abs(t - centre_s)
        return 1000.0 - 1000.0 * inside / half_width_s if inside > 0 else 1000.0
    return separation


class TestTheClosestApproachSearch:
    def test_the_default_grid_samples_every_minute(self) -> None:
        """An encounter 50 s wide, centred on a whole minute, is caught; a 90 s grid steps over it."""
        found = closest_approach(_dip(240.0, 25.0), 600.0)  # type: ignore[arg-type]
        assert found.miss_km < 1.0
        assert found.tca_s == pytest.approx(240.0, abs=0.05)

    def test_the_deeper_of_two_encounters_is_reported_when_the_window_ends_where_it_began(self) -> None:
        grid = [0.0, 60.0, 120.0, 180.0, 240.0]
        values = [5.0, 0.5, 5.0, 1.0, 5.0]
        found = closest_approach(lambda t: float(np.interp(t, grid, values)), 240.0)
        assert found.miss_km == pytest.approx(0.5, abs=1e-6)
        assert found.tca_s == pytest.approx(60.0, abs=0.05)

    def test_a_refined_point_inside_a_one_step_window_is_not_its_edge(self) -> None:
        found = closest_approach(lambda t: abs(t - 30.0) + 1.0, 60.0)
        assert found.miss_km == pytest.approx(1.0, abs=0.01)
        assert found.tca_s == pytest.approx(30.0, abs=0.01)
        assert found.at_window_edge is False


class TestTransferBounds:
    def test_a_hohmann_transfer_has_no_third_burn(self) -> None:
        result = hohmann(7000.0, 42164.0)
        assert result.delta_v_3 == 0.0
        assert result.total_delta_v == pytest.approx(result.delta_v_1 + result.delta_v_2)

    def test_a_radius_on_the_surface_is_refused(self) -> None:
        with pytest.raises(ValueError, match="above the Earth"):
            bielliptic(R_EARTH, 42164.0, 100_000.0)

    def test_an_intermediate_radius_equal_to_the_outer_orbit_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must exceed both orbit radii"):
            bielliptic(7000.0, 42164.0, 42164.0)


class TestRegimeClassification:
    """The regime gates which targets a sweep will fly against a red object (regimes_compatible)."""

    @pytest.mark.parametrize(("sma_km", "ecc", "regime"), [
        (6778.0, 0.0005, "LEO"),      # ISS
        (8000.0, 0.10, "LEO"),        # low perigee, apogee just above LEO, not eccentric enough for HEO
        (8800.0, 0.0, "MEO"),         # 2,422 km circular: above the 2,000 km LEO ceiling
        (26560.0, 0.01, "MEO"),       # GPS
        (41700.0, 0.0, "MEO"),        # 35,322 km: under the GEO band's 35,386 km floor
        (42164.0, 0.0002, "GEO"),     # geostationary
        (42700.0, 0.0005, "DEEP"),    # graveyard, perigee above the band's 36,186 km ceiling
        (24400.0, 0.73, "GTO"),       # transfer orbit, apogee at GEO
        (26600.0, 0.74, "HEO"),       # Molniya, apogee well above GEO
        (42164.0, 0.27, "HEO"),       # Tundra
        (12000.0, 0.40, "HEO"),       # eccentric, apogee short of GEO
        (12000.0, 0.32, "HEO"),       # just over the 0.3 eccentricity bound
        (40000.0, 0.15, "MEO"),       # apogee above GEO, but too round for HEO by the 0.25 rule
    ])
    def test_a_representative_orbit_is_classified(self, sma_km: float, ecc: float, regime: str) -> None:
        assert classify_orbit_regime(sma_km, ecc) == regime

    @pytest.mark.parametrize(("eccentricity", "mean_motion", "regime"), [
        ("3000000", " 5.00000000", "MEO"),  # e exactly 0.3, apogee short of GEO: HEO needs e over 0.3
        ("2500000", " 1.30000000", "MEO"),  # e exactly 0.25, apogee above GEO: HEO needs e over 0.25
        ("3000001", " 5.00000000", "HEO"),
        ("2500001", " 1.30000000", "HEO"),
    ])
    def test_an_element_set_exactly_at_an_eccentricity_bound_is_not_heo(
        self, eccentricity: str, mean_motion: str, regime: str,
    ) -> None:
        """A TLE's seven-digit eccentricity field gives exactly 0.3 or 0.25, so the bounds are met in practice.

        Both bounds are strict: an orbit at the bound is classified by its
        altitudes, as MEO here, and only one beyond it is HEO.
        """
        line2 = f"{_LINE2[:26]}{eccentricity}{_LINE2[33:52]}{mean_motion}{_LINE2[63:68]}"
        line2 += str(_checksum(line2))
        assert regime_from_tle(f"{_LINE1}\n{line2}") == regime

    def test_an_eccentric_orbit_with_its_apogee_exactly_on_the_geo_floor_is_not_heo(self) -> None:
        """The 0.25 rule needs an apogee above the GEO band's floor, not on it.

        With e between 0.25 and 0.3 only that rule can call the orbit HEO, so
        an apogee exactly on the floor (35,386 km) leaves it to its perigee,
        17,114 km here: MEO. The semi-major axis is chosen so the apogee lands
        on the floor to the bit, as a caller passing a Keplerian semi-major
        axis (the threat route, the Monte Carlo sampler) can.
        """
        sma_km, ecc = 32628.23203125, 0.28
        assert sma_km * (1.0 + ecc) - R_EARTH == 35386.0
        assert classify_orbit_regime(sma_km, ecc) == "MEO"

    def test_an_orbit_given_no_eccentricity_is_taken_as_circular(self) -> None:
        assert classify_orbit_regime(42164.0) == "GEO"

    def test_the_geostationary_radius_drives_the_graveyard_raise(self) -> None:
        """A 300 km raise from GEO costs about 10.9 m/s, the figure disposal planning quotes."""
        result = graveyard_transfer(300.0)
        assert result.r_geo == 42164.0
        assert result.total_delta_v == pytest.approx(0.01088, rel=2e-3)
