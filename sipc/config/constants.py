"""SIPC scenario naming conventions, units, and STK configuration constants."""

# ── Asset naming prefixes ─────────────────────────────────────────────────────
BLUE_PREFIX: str = "B_SAT_"
RED_PREFIX: str = "R_SAT_"
CALC_PREFIX: str = "CALC_"
OUT_PREFIX: str = "OUT_"

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

# ── STK scenario folder structure ────────────────────────────────────────────
STK_FOLDERS: list[str] = [
    "/Blue",
    "/Red",
    "/Sensors",
    "/Constraints",
    "/Outputs",
    "/Scratch",
]
