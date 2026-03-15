"""SIPC scenario naming conventions, units, and configuration constants."""

# ── Asset naming prefixes ─────────────────────────────────────────────────────
BLUE_PREFIX: str = "B_SAT_"
RED_PREFIX: str = "R_SAT_"

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
