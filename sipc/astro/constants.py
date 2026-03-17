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
