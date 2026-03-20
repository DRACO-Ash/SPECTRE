"""Physical constants for orbital mechanics."""

from __future__ import annotations

# Standard gravitational parameter (km³/s²)
MU_EARTH: float = 398600.4418

# Earth equatorial radius (km)
R_EARTH: float = 6378.137

# J2 zonal harmonic (oblateness)
J2_EARTH: float = 1.08263e-3

# GEO parameters
GEO_RADIUS: float = 42164.0   # km — geostationary orbit radius
SIDEREAL_DAY: float = 86164.1  # seconds — Earth's sidereal rotation period

# Orbit regime boundaries (altitude km above Earth's surface)
_LEO_MAX_ALT: float = 2000.0
_MEO_MAX_ALT: float = 35386.0   # GEO lower bound − 400 km
_GEO_BAND_ALT: float = 35786.0  # nominal GEO altitude
_GEO_TOL_ALT: float = 400.0     # ± tolerance for GEO band
_GEO_MAX_ALT: float = 36186.0   # GEO upper bound + 400 km

# Mapping of raw UDL orbitRegime strings → canonical family
_REGIME_MAP: dict[str, str] = {
    "VLEO": "LEO", "LEO": "LEO", "SSO": "LEO", "POLAR": "LEO", "SLEO": "LEO",
    "MEO": "MEO",
    "GEO": "GEO", "GSO": "GEO", "NGSO": "GEO",
    "GTO": "GTO",
    "HEO": "HEO", "MOLNIYA": "HEO", "TUNDRA": "HEO",
    "SUPER_SYNC": "DEEP", "GRAVEYARD": "DEEP",
}


def normalise_regime(raw: str) -> str:
    """Map a raw UDL *orbitRegime* string to a canonical regime family.

    Returns one of: ``"LEO"``, ``"MEO"``, ``"GEO"``, ``"GTO"``, ``"HEO"``,
    ``"DEEP"``, or ``"OTHER"`` for unrecognised values.
    """
    return _REGIME_MAP.get(raw.strip().upper(), "OTHER")


def classify_orbit_regime(semi_major_axis_km: float, eccentricity: float = 0.0) -> str:
    """Classify an orbit into a canonical regime family from TLE-derived elements.

    Uses perigee / apogee altitudes and eccentricity to distinguish:
    ``"LEO"``, ``"MEO"``, ``"GEO"``, ``"GTO"``, ``"HEO"``, ``"DEEP"``.
    """
    perigee_alt = semi_major_axis_km * (1.0 - eccentricity) - R_EARTH
    apogee_alt = semi_major_axis_km * (1.0 + eccentricity) - R_EARTH

    if apogee_alt < _LEO_MAX_ALT:
        return "LEO"
    if perigee_alt > _GEO_MAX_ALT:
        return "DEEP"
    if _MEO_MAX_ALT <= perigee_alt and apogee_alt <= _GEO_MAX_ALT:
        return "GEO"
    if perigee_alt < _LEO_MAX_ALT and apogee_alt > _MEO_MAX_ALT:
        # High apogee + low perigee — GTO or HEO depending on eccentricity
        return "GTO" if apogee_alt > _MEO_MAX_ALT and eccentricity > 0.5 else "HEO"
    if eccentricity > 0.3 and apogee_alt > _LEO_MAX_ALT:
        return "HEO"
    if perigee_alt >= _LEO_MAX_ALT:
        return "MEO"
    return "LEO"
