"""Regime classification against reference orbits.

Audit F-016: Molniya classified as GTO and Tundra as MEO. regimes_compatible
gates the threat sweep and manoeuvre routes, and MEO is not compatible with
GEO, so a Tundra object was dropped from screening against GEO assets.

Element sets are the commonly quoted nominal ones for each orbit type; the
perigee and apogee altitudes noted beside them follow from a(1 - e) - R and
a(1 + e) - R.
"""

from __future__ import annotations

import pytest

from spectre.astro.constants import classify_orbit_regime, regimes_compatible


@pytest.mark.parametrize(
    ("a_km", "ecc", "regime"),
    [
        (6_778.0, 0.0005, "LEO"),    # ISS-like
        (26_560.0, 0.01, "MEO"),     # GPS
        (42_164.0, 0.0002, "GEO"),
        (24_396.0, 0.7283, "GTO"),   # 250 km by 35,786 km
        (26_562.0, 0.74, "HEO"),     # Molniya, 528 km by 39,840 km
        (42_164.0, 0.27, "HEO"),     # Tundra, 24,402 km by 47,170 km
        (50_000.0, 0.01, "DEEP"),
    ],
    ids=["leo", "gps", "geo", "gto", "molniya", "tundra", "deep"],
)
def test_reference_orbits(a_km: float, ecc: float, regime: str) -> None:
    assert classify_orbit_regime(a_km, ecc) == regime


def test_a_tundra_object_is_screened_against_geo() -> None:
    assert regimes_compatible(classify_orbit_regime(42_164.0, 0.27), "GEO")
