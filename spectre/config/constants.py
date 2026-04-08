"""SPECTRE scenario naming conventions, units, and configuration constants."""

# ── Asset naming prefixes ─────────────────────────────────────────────────────
BLUE_PREFIX: str = ""
RED_PREFIX: str = ""

# ── Propagation / analysis step sizes ────────────────────────────────────────
PROP_STEP_SEC: int = 10
ANALYSIS_STEP_SEC: int = 10

# ── Physical units (documentation / validation) ───────────────────────────────
DISTANCE_UNIT: str = "km"
SPEED_UNIT: str = "m/s"
ANGLE_UNIT: str = "deg"

# ── Reference frames ─────────────────────────────────────────────────────────
COORD_FRAME: str = "ICRF"
TIME_SYSTEM: str = "UTC"

# ── TLE Clustering Configuration ─────────────────────────────────────────────
# Controls how near-duplicate TLEs from multiple providers are clustered and
# reduced to a single representative per cluster before sweep analysis.
# Adjust tolerances to tune aggressiveness:
#   wider tolerance  →  more TLEs grouped together  →  fewer representatives out
#   tighter tolerance →  fewer TLEs grouped together →  more representatives out
#
# inclination_tolerance_deg:
#   Max allowed difference in inclination (degrees) for two TLEs to be
#   considered equivalent. J2 and provider fitting noise are typically <0.01°.
#   Default: 0.01 deg.
#
# raan_tolerance_deg:
#   Max allowed difference in RAAN (degrees). Wider than inclination because
#   J2 secular drift and provider epoch offsets of minutes can shift RAAN by
#   ~0.05° between providers fitting the same pass.
#   Default: 0.05 deg.
#
# eccentricity_tolerance:
#   Max allowed difference in eccentricity (dimensionless). LEO objects
#   typically have eccentricities < 0.01; inter-provider variation is ~1e-4.
#   Default: 0.0001.
#
# dbscan_min_samples:
#   Minimum number of TLEs required to form a cluster. Setting to 1 would
#   treat every singleton as its own cluster, defeating the purpose.
#   Default: 2.
#
# fetch_window_hours:
#   How many hours back to look when fetching multi-provider TLE history for
#   an object. Longer windows capture more providers but increase UDL load.
#   Default: 24 h (one full day of TLE generation cadence).
TLE_CLUSTERING: dict[str, float | int] = {
    "inclination_tolerance_deg": 0.01,
    "raan_tolerance_deg":        0.05,
    "eccentricity_tolerance":    1e-4,
    "dbscan_min_samples":        2,
    "fetch_window_hours":        24,
}

# ── TLE cadence filter thresholds ────────────────────────────────────────────
TLE_FILTER: dict[str, float | int] = {
    "min_spacing_leo_s": 900,       # 15 min  — LEO / HEO / GTO
    "min_spacing_meo_s": 1800,      # 30 min  — MEO
    "min_spacing_geo_s": 3600,      # 60 min  — GEO / DEEP
    "staleness_warn_leo_h": 24,     # flag gaps > 24 h for LEO
    "staleness_warn_geo_h": 72,     # flag gaps > 72 h for GEO
    "bstar_discontinuity_frac": 0.5,  # fractional B* jump threshold
    "large_cluster_threshold": 10,  # log clusters >= this size
}
