"""Monte Carlo simulation for manoeuvre outcome prediction.

Given a ManoeuvreHypothesis (baseline ΔV with uncertainty envelopes),
this module:

- Generates N perturbed ΔV samples (magnitude, pointing cone, timing, Bstar).
- Propagates each sample forward using a J2 + exponential drag numerical
  integrator (RK45 via scipy.integrate.solve_ivp).
- Aggregates the ensemble into a MonteCarloResult with regime probabilities,
  orbital element percentiles, and the 99.7th percentile distance of the
  position cloud from its centroid.
- Separately, builds a separation series against a blue track
  (run_separation_series, SPC-110): each sample's closest approach to the
  blue object over a window, with P5, P50 and P95 of the misses. Blue is
  propagated with the same RK45 model as red, from its SGP4 state at the
  window start; with blue left on SGP4 the GEO reference case missed its TCA
  by 1,951 s.

Design notes
------------
- Perturbations are applied in the Radial-In track-Cross track (RIC) frame and
  then rotated to ECI before integration — physically meaningful for pointing
  errors.
- Propagation uses J2 + simplified exponential atmosphere drag.  At 48 h, the
  MC uncertainty envelope from ΔV variation dominates over force-model error,
  so high-fidelity ephemeris is unnecessary.
- Concurrency: ThreadPoolExecutor. The equations of motion are a Python
  function, so the integrator holds the GIL for most of each step and threads
  give little speed-up; they were described as releasing it (audit F-221).
  A process pool or a vectorised ensemble would be the way to go faster.
  The separation series runs serially for that reason.
"""

from __future__ import annotations

import functools
import logging
import math
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, NamedTuple, cast

import numpy as np
from scipy.integrate import solve_ivp

from spectre.astro.closest_approach import MAX_SAMPLES, ClosestApproach, _grid, closest_approach
from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH, classify_orbit_regime

logger = logging.getLogger(__name__)


# ── Physical constants ────────────────────────────────────────────────────────

_MU   = MU_EARTH   # km³/s²
_R_E  = R_EARTH    # km
_J2   = J2_EARTH   # dimensionless


# ── Atmospheric density model ─────────────────────────────────────────────────

# Vallado, Fundamentals of Astrodynamics and Applications, Table 8-4
# (exponential atmosphere): base altitude km, base density kg/m^3, scale
# height km. Each scale height is fitted so adjacent bands meet. The previous
# uncited table had its scale heights shifted one band against base densities
# that matched no published row, so density jumped at most band edges (x24.9
# at 150 km, x10.1 at 1,000 km) (audit F-105).
_EXPONENTIAL_ATMOSPHERE: tuple[tuple[float, float, float], ...] = (
    (0.0,    1.225,     7.249),
    (25.0,   3.899e-2,  6.349),
    (30.0,   1.774e-2,  6.682),
    (40.0,   3.972e-3,  7.554),
    (50.0,   1.057e-3,  8.382),
    (60.0,   3.206e-4,  7.714),
    (70.0,   8.770e-5,  6.549),
    (80.0,   1.905e-5,  5.799),
    (90.0,   3.396e-6,  5.382),
    (100.0,  5.297e-7,  5.877),
    (110.0,  9.661e-8,  7.263),
    (120.0,  2.438e-8,  9.473),
    (130.0,  8.484e-9,  12.636),
    (140.0,  3.845e-9,  16.149),
    (150.0,  2.070e-9,  22.523),
    (180.0,  5.464e-10, 29.740),
    (200.0,  2.789e-10, 37.105),
    (250.0,  7.248e-11, 45.546),
    (300.0,  2.418e-11, 53.628),
    (350.0,  9.518e-12, 53.298),
    (400.0,  3.725e-12, 58.515),
    (450.0,  1.585e-12, 60.828),
    (500.0,  6.967e-13, 63.822),
    (600.0,  1.454e-13, 71.835),
    (700.0,  3.614e-14, 88.667),
    (800.0,  1.170e-14, 124.64),
    (900.0,  5.245e-15, 181.05),
    (1000.0, 3.019e-15, 268.00),
)


def _atmo_density_kg_m3(h_km: float) -> float:
    """Atmospheric density (kg/m^3) at altitude *h_km*, exponential atmosphere.

    Vallado's Table 8-4, piecewise exponential from the band at or below the
    altitude. Above 1,000 km the top band is extended.
    """
    h = max(0.0, h_km)
    for h_base, rho0, scale_height in reversed(_EXPONENTIAL_ATMOSPHERE):
        if h >= h_base:
            return rho0 * math.exp(-(h - h_base) / scale_height)
    return _EXPONENTIAL_ATMOSPHERE[0][1]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ManoeuvreType:
    """Pre-configured manoeuvre archetype with characteristic uncertainties."""

    name: str
    description: str
    typical_delta_v_km_s: float
    delta_v_1sigma_fraction: float   # Fraction of nominal ΔV
    pointing_1sigma_deg: float
    timing_1sigma_seconds: float


# Archetype magnitudes, checked against "Satellite Manoeuvre Delta-v:
# Feasibility Above 0.5 km/s and Budgets by Regime" (Bluestaq Limited Space
# Watch, v1.0, 13 October 2026). Values are km/s because this module is part of
# the astro package, which works in km and km/s throughout; the operator-facing
# calibration in spectre/domain/manoeuvre_calibration.py is in m/s.
#
# Six of the seven already matched the published figures. The one that did not
# is noted at its entry.
MANOEUVRE_ARCHETYPES: dict[str, ManoeuvreType] = {
    "station_keeping": ManoeuvreType(
        name="Station Keeping",
        # Table 3: GEO north-south is 43-50 m/s per year and east-west 1-5,
        # spread across routine burns, so a single burn is 1-2 m/s.
        description="GEO east-west or north-south station keeping",
        typical_delta_v_km_s=0.002,
        delta_v_1sigma_fraction=0.10,
        pointing_1sigma_deg=1.0,
        timing_1sigma_seconds=10.0,
    ),
    "orbit_raise": ManoeuvreType(
        name="Orbit Raise",
        # Table 4: 500 to 600 km costs about 55 m/s.
        description="LEO/MEO altitude change manoeuvre",
        typical_delta_v_km_s=0.050,
        delta_v_1sigma_fraction=0.05,
        pointing_1sigma_deg=2.0,
        timing_1sigma_seconds=30.0,
    ),
    "plane_change": ManoeuvreType(
        name="Plane Change",
        # Table 4: 54 m/s per degree at GEO, 133 m/s per degree at LEO, so
        # 100 m/s is about 1.9 degrees at GEO or 0.75 at LEO.
        description="Inclination or RAAN adjustment",
        typical_delta_v_km_s=0.100,
        delta_v_1sigma_fraction=0.05,
        pointing_1sigma_deg=3.0,
        timing_1sigma_seconds=60.0,
    ),
    "phasing": ManoeuvreType(
        name="Phasing Manoeuvre",
        # Table 4: a 62 degree GEO relocation over 30 days costs about 11 m/s,
        # matching the observed Luch/Olymp-K 2 move.
        description="Along-track repositioning within same orbit",
        typical_delta_v_km_s=0.010,
        delta_v_1sigma_fraction=0.08,
        pointing_1sigma_deg=2.0,
        timing_1sigma_seconds=20.0,
    ),
    "intercept_approach": ManoeuvreType(
        name="Intercept / Approach",
        # Table 4 worked example: a 90 degree GEO relocation in 3 days costs
        # about 170 m/s (computed, not observed). 200 m/s sits just above it.
        description="Co-orbital approach towards a target",
        typical_delta_v_km_s=0.200,
        delta_v_1sigma_fraction=0.03,
        pointing_1sigma_deg=1.5,
        timing_1sigma_seconds=15.0,
    ),
    "evasive": ManoeuvreType(
        name="Evasive Manoeuvre",
        # CORRECTED. This was 30 m/s, which does not match any published
        # figure. Table 4 puts a collision avoidance manoeuvre at centimetres
        # per second to about 1 m/s, and notes that the screening threshold
        # drives how OFTEN one is flown, not how large it is: Starlink flew
        # 207,152 of them in six months. A threat-evasion burn is larger than a
        # debris CAM but still small, so 2 m/s with a wide dispersion spans
        # both rather than modelling a manoeuvre thirty times too big.
        description="Rapid unplanned manoeuvre to avoid threat or conjunction",
        typical_delta_v_km_s=0.002,
        delta_v_1sigma_fraction=0.15,
        pointing_1sigma_deg=5.0,
        timing_1sigma_seconds=120.0,
    ),
    "repositioning": ManoeuvreType(
        name="Repositioning",
        # Table 4: 34 m/s for 180 degrees over 30 days, 170 m/s for 90 degrees
        # in 3 days. 80 m/s sits between the patient and the hurried case.
        description="Large orbital repositioning / transfer",
        typical_delta_v_km_s=0.080,
        delta_v_1sigma_fraction=0.05,
        pointing_1sigma_deg=2.0,
        timing_1sigma_seconds=30.0,
    ),
}


@dataclass
class ManoeuvreHypothesis:
    """Defines a baseline manoeuvre and its uncertainty envelope.

    Parameters
    ----------
    epoch_utc:
        Nominal manoeuvre epoch.
    delta_v_magnitude_km_s:
        Nominal ΔV magnitude (km/s).
    delta_v_radial, delta_v_in_track, delta_v_cross_track:
        Nominal ΔV components in RIC frame (km/s).  The direction vector
        is normalised internally; *delta_v_magnitude_km_s* sets the scale.
    pre_manoeuvre_state_eci_km:
        Pre-manoeuvre ECI state [x, y, z, vx, vy, vz] (km, km/s).
    n_samples:
        Number of Monte Carlo samples.
    random_seed:
        RNG seed for reproducibility.
    """

    epoch_utc: datetime
    delta_v_magnitude_km_s: float
    delta_v_radial: float         # RIC R-component (km/s)
    delta_v_in_track: float       # RIC I-component (km/s)
    delta_v_cross_track: float    # RIC C-component (km/s)
    pre_manoeuvre_state_eci_km: np.ndarray   # shape (6,)

    # Uncertainty envelope
    delta_v_magnitude_1sigma_km_s: float = 0.001
    delta_v_pointing_1sigma_deg: float   = 2.0
    epoch_1sigma_seconds: float          = 30.0
    bstar_post: float                    = 1.0e-4   # B* for drag in propagation
    bstar_1sigma: float                  = 1.0e-5

    # Sampling configuration
    distribution_type: str = "gaussian"   # "gaussian" | "uniform"
    n_samples: int         = 500
    random_seed: int       = 42
    # Where the RIC split of the ΔV came from, shown on the panel.
    direction_basis: str   = "assumed in-track"
    # The archetype whose sigmas these are, shown on the panel (audit F-104).
    archetype: str         = ""


@dataclass(frozen=True)
class MonteCarloAssumptions:
    """What the run assumed rather than measured, for the panel to state.

    The dispersions come from an archetype table, not from the object's own
    history, and the ΔV direction may be assumed. Carried with the result so
    the panel cannot show the cloud without saying so (audit F-104).
    """

    archetype: str
    dv_1sigma_m_s: float
    pointing_1sigma_deg: float
    timing_1sigma_s: float
    bstar_1sigma: float
    direction_basis: str

    @classmethod
    def of(cls, hypothesis: ManoeuvreHypothesis) -> MonteCarloAssumptions:
        return cls(
            archetype=hypothesis.archetype or "unnamed",
            dv_1sigma_m_s=hypothesis.delta_v_magnitude_1sigma_km_s * 1000.0,
            pointing_1sigma_deg=hypothesis.delta_v_pointing_1sigma_deg,
            timing_1sigma_s=hypothesis.epoch_1sigma_seconds,
            bstar_1sigma=hypothesis.bstar_1sigma,
            direction_basis=hypothesis.direction_basis,
        )


@dataclass
class MonteCarloResult:
    """Aggregated Monte Carlo output for a single manoeuvre hypothesis."""

    hypothesis_satno: int
    prediction_horizon_hours: float
    n_samples_run: int
    n_samples_converged: int
    converged: bool

    # Orbital element statistics at prediction horizon
    sma_km_mean: float
    sma_km_std: float
    sma_km_p5: float
    sma_km_p50: float
    sma_km_p95: float

    ecc_mean: float
    ecc_std: float
    inc_deg_mean: float
    inc_deg_std: float

    # Regime probability breakdown
    regime_probabilities: dict[str, float]

    # Position uncertainty
    # 99.7th percentile distance from the cloud's centroid; not a 3-sigma of
    # any fitted distribution (audit F-219). The name is kept for callers.
    position_3sigma_km: float
    alt_km_p5: float               # 5th percentile altitude
    alt_km_p95: float              # 95th percentile altitude

    # Derived operational metrics
    altitude_range_km: tuple[float, float]
    period_range_minutes: tuple[float, float]

    # Timing
    wall_time_seconds: float
    random_seed: int

    # Where the hypothesis's ΔV direction came from (see ManoeuvreHypothesis).
    direction_basis: str = ""

    # Percentiles for the rows the panel heads "5th %ile / Median / 95th %ile".
    # The period row used to show the minimum and maximum there (audit F-104).
    alt_km_p50: float = 0.0
    period_min_p5: float = 0.0
    period_min_p50: float = 0.0
    period_min_p95: float = 0.0
    assumptions: MonteCarloAssumptions | None = None
    # Widest 95 % bootstrap half-width of SMA P5, P50 and P95; ``converged``
    # means it is within CONVERGENCE_TOLERANCE_KM (audit F-103).
    percentile_half_width_km: float = math.inf


# ── Core physics ──────────────────────────────────────────────────────────────

def _ric_to_eci_rotation(r_eci: np.ndarray, v_eci: np.ndarray) -> np.ndarray:
    """Compute the 3×3 rotation matrix from RIC to ECI at the given state.

    Columns: [R_hat, I_hat, C_hat] in ECI.
    """
    r_hat = r_eci / np.linalg.norm(r_eci)
    h = np.cross(r_eci, v_eci)
    c_hat = h / np.linalg.norm(h)
    i_hat = np.cross(c_hat, r_hat)
    return np.column_stack([r_hat, i_hat, c_hat])  # (3, 3)


def _j2_drag_ode(
    t: float,
    state: np.ndarray,
    bc_m2_kg: float,
) -> np.ndarray:
    """EOM: two-body + J2 + exponential drag (ECI frame, km, s).

    Parameters
    ----------
    state : (6,) — [x, y, z, vx, vy, vz]
    bc_m2_kg : ballistic coefficient m / (Cd*A), in kg/m² despite the name
    """
    x, y, z, vx, vy, vz = state
    r_vec = np.array([x, y, z])
    v_vec = np.array([vx, vy, vz])
    r = float(np.linalg.norm(r_vec))

    # Two-body
    a_2b = -(_MU / r ** 3) * r_vec

    # J2
    zr2 = (z / r) ** 2
    fac = -1.5 * _J2 * _MU * _R_E ** 2 / r ** 5
    a_j2 = fac * np.array([
        x * (1.0 - 5.0 * zr2),
        y * (1.0 - 5.0 * zr2),
        z * (3.0 - 5.0 * zr2),
    ])

    # Drag — significant only below ~800 km
    h_km = r - _R_E
    a_drag = np.zeros(3)
    if h_km < 800.0 and bc_m2_kg > 0.0:
        rho_kg_m3 = _atmo_density_kg_m3(h_km)
        v_mag = float(np.linalg.norm(v_vec))
        if v_mag > 0.01:
            # a_drag [km/s²] = -(1/(2*BC)) * rho [kg/m³] * v² [km²/s²] * 1e6 * 1e-3 * v_hat
            #                = -(500/BC) * rho * v² * v_hat
            a_drag = -(500.0 / bc_m2_kg) * rho_kg_m3 * v_mag ** 2 * (v_vec / v_mag)

    a_total = a_2b + a_j2 + a_drag
    return np.concatenate([v_vec, a_total])


def _state_to_keplerian(r_vec: np.ndarray, v_vec: np.ndarray) -> tuple[float, ...]:
    """Return (sma_km, ecc, inc_deg) from a state: enough for MC classification."""
    r = float(np.linalg.norm(r_vec))
    v = float(np.linalg.norm(v_vec))
    h_vec = np.cross(r_vec, v_vec)
    h = float(np.linalg.norm(h_vec))

    energy = v ** 2 / 2.0 - _MU / r
    sma = -_MU / (2.0 * energy) if abs(energy) > 1e-12 else 1e6

    e_vec = np.cross(v_vec, h_vec) / _MU - r_vec / r
    ecc = float(np.linalg.norm(e_vec))

    inc_deg = math.degrees(math.acos(max(-1.0, min(1.0, h_vec[2] / h))))

    return sma, ecc, inc_deg


# ── Sample generation ─────────────────────────────────────────────────────────

def generate_samples(hypothesis: ManoeuvreHypothesis) -> np.ndarray:
    """Generate N perturbed ΔV vectors in RIC frame.

    Returns
    -------
    np.ndarray, shape (N, 5):
        [dv_R, dv_I, dv_C, epoch_offset_s, bstar_perturbation]
    """
    rng = np.random.default_rng(hypothesis.random_seed)
    n = hypothesis.n_samples

    # 1. Perturb ΔV magnitude
    if hypothesis.distribution_type == "gaussian":
        dv_mags = rng.normal(
            hypothesis.delta_v_magnitude_km_s,
            hypothesis.delta_v_magnitude_1sigma_km_s,
            size=n,
        )
    else:
        # A uniform distribution of half-width sqrt(3) sigma has standard
        # deviation sigma. Three sigma, as it was, made the "uniform" option
        # sqrt(3) times wider than the stated 1-sigma (audit F-220).
        half = math.sqrt(3.0) * hypothesis.delta_v_magnitude_1sigma_km_s
        dv_mags = rng.uniform(
            hypothesis.delta_v_magnitude_km_s - half,
            hypothesis.delta_v_magnitude_km_s + half,
            size=n,
        )
    dv_mags = np.abs(dv_mags)

    # 2. Nominal direction unit vector in RIC
    ric = np.array([
        hypothesis.delta_v_radial,
        hypothesis.delta_v_in_track,
        hypothesis.delta_v_cross_track,
    ])
    ric_norm = float(np.linalg.norm(ric))
    if ric_norm < 1e-15:
        # Default to in-track if zero direction given
        ric_unit = np.array([0.0, 1.0, 0.0])
    else:
        ric_unit = ric / ric_norm

    # 3. Pointing perturbation — Rayleigh cone model
    sigma_rad = math.radians(hypothesis.delta_v_pointing_1sigma_deg)
    cone_angles = rng.rayleigh(sigma_rad, size=n)
    clock_angles = rng.uniform(0.0, 2.0 * math.pi, size=n)

    # Build perturbed unit vectors: rotate ric_unit by cone_angle around random clock angle
    # Create a local frame: find two vectors perpendicular to ric_unit
    if abs(ric_unit[0]) < 0.9:
        perp1 = np.cross(ric_unit, [1.0, 0.0, 0.0])
    else:
        perp1 = np.cross(ric_unit, [0.0, 1.0, 0.0])
    perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(ric_unit, perp1)

    # Rotate: perturbed = cos(cone)*ric_unit + sin(cone)*(cos(clock)*perp1 + sin(clock)*perp2)
    cos_c = np.cos(cone_angles)
    sin_c = np.sin(cone_angles)
    cos_cl = np.cos(clock_angles)
    sin_cl = np.sin(clock_angles)

    perturbed_dirs = (
        cos_c[:, None] * ric_unit
        + sin_c[:, None] * (cos_cl[:, None] * perp1 + sin_cl[:, None] * perp2)
    )  # (N, 3)

    # Scale by perturbed magnitude
    dv_ric = dv_mags[:, None] * perturbed_dirs  # (N, 3)

    # 4. Timing perturbation
    epoch_offsets = rng.normal(0.0, hypothesis.epoch_1sigma_seconds, size=n)

    # 5. B* perturbation (post-manoeuvre drag)
    bstar_perturbations = rng.normal(0.0, hypothesis.bstar_1sigma, size=n)

    return np.column_stack([dv_ric, epoch_offsets[:, None], bstar_perturbations[:, None]])


# ── Single-sample propagation ─────────────────────────────────────────────────

# SGP4 defines B* = rho0 Cd A / (2 m) with rho0 = 0.15696615 kg/m^2 per Earth
# radius, so Cd A / m = 2 B* / rho0 = 12.741621 B* in m^2/kg (Vallado,
# Fundamentals of Astrodynamics and Applications, SGP4 drag term).
_BSTAR_TO_CDA_OVER_M = 12.741621
# Floor on m / (Cd A), kg/m^2, and the smallest |B*| taken at face value.
_MIN_BALLISTIC_KG_M2 = 5.0
_MIN_BSTAR = 1e-8
# A span shorter than this, in seconds, leaves the state where it is.
_ZERO_SPAN_S = 1e-9
# A ΔV breakdown smaller than this, km/s (1 nm/s), carries no direction.
_ZERO_DV_KM_S = 1e-12
#: The RK45 tolerances every propagation in this module uses, the horizon
#: samples and the separation series alike (relative, and absolute in km and km/s).
RK45_RTOL = 1e-8
RK45_ATOL = 1e-10


def _ballistic_coefficient_kg_m2(bstar: float) -> float:
    """m / (Cd A), kg/m^2, from the SGP4 drag term B* (1/Earth radii).

    The previous conversion used an unsourced constant on the Earth radius in
    metres and gave 31.9 kg/m^2 for B* = 1e-4 where SGP4's relation gives
    784.8: drag about 24.6 times too strong (audit F-031).
    """
    return max(_MIN_BALLISTIC_KG_M2, 1.0 / (_BSTAR_TO_CDA_OVER_M * max(abs(bstar), _MIN_BSTAR)))


def propagate_single_sample(
    sample: np.ndarray,
    pre_state: np.ndarray,
    bstar_base: float,
    horizon_hours: float,
) -> dict[str, Any] | None:
    """Propagate one MC sample and return key orbital elements at horizon.

    Time zero is the nominal burn epoch, at which *pre_state* holds. The
    sample's timing offset moves the burn: the pre-burn state is propagated
    (forward or back) to the shifted instant, the ΔV is applied in the RIC
    frame there, and every sample is then integrated to the same horizon. The
    offset used to lengthen or shorten the whole span instead, so the cloud
    mixed states read at different times (audit F-029).

    Returns None on numerical failure.
    """
    dv_ric = sample[:3]
    t_burn = float(sample[3])
    bstar_eff = bstar_base + float(sample[4])
    horizon_s = horizon_hours * 3600.0
    if t_burn >= horizon_s:
        return None

    try:
        burn_state = _integrate(pre_state, t_burn, bstar_base)
        if burn_state is None:
            return None
        burn_state[3:] += _ric_to_eci_rotation(burn_state[:3], burn_state[3:]) @ dv_ric
        final = _integrate(burn_state, horizon_s - t_burn, bstar_eff)
        if final is None:
            return None

        r_final, v_final = final[:3], final[3:]
        sma, ecc, inc_deg = _state_to_keplerian(r_final, v_final)
        alt_km = float(np.linalg.norm(r_final)) - _R_E
        period_min = 2.0 * math.pi * math.sqrt(max(sma, 1.0) ** 3 / _MU) / 60.0

        return {
            "r_final": r_final.tolist(),
            "sma_km": sma,
            "ecc": ecc,
            "inc_deg": inc_deg,
            "alt_km": alt_km,
            "period_min": period_min,
            "regime": classify_orbit_regime(sma, ecc),
        }
    except (ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return None


def _integrate(state: np.ndarray, span_s: float, bstar: float) -> np.ndarray | None:
    """Integrate *state* for *span_s* seconds (negative runs backwards)."""
    if abs(span_s) < _ZERO_SPAN_S:
        return state.copy()
    sol = solve_ivp(
        _j2_drag_ode,
        (0.0, span_s),
        state,
        method="RK45",
        rtol=RK45_RTOL,
        atol=RK45_ATOL,
        args=(_ballistic_coefficient_kg_m2(bstar),),
        dense_output=False,
    )
    return np.array(sol.y[:, -1]) if sol.success else None


# ── Convergence check ─────────────────────────────────────────────────────────

# The panel shows SMA-derived P5, P50 and P95. A run has converged when each
# is known to within this, as a 95 % bootstrap half-width (audit F-103).
CONVERGENCE_TOLERANCE_KM = 1.0
_MIN_CONVERGENCE_SAMPLES = 50
_BOOTSTRAP_RESAMPLES = 200
_SHOWN_PERCENTILES = (5.0, 50.0, 95.0)


#: A separation series' misses converge to within this fraction of P5 where that is wider than
#: CONVERGENCE_TOLERANCE_KM (SPC-117). The operator reads P5 to answer whether red can reach a blue asset, a question
#: of magnitude: a few km at several hundred km changes no answer, while below 20 km the 1 km floor governs, so a
#: close approach is held exactly as tightly as before. Measured at seed 42, the cases it admits have half-widths of
#: 0.5 to 3.4 % of P5 (worst across seeds about 3 %); the GEO Intercept case, P5 7 to 8 km known to 1.8 to 3.9 km,
#: stays refused. run_monte_carlo's SMA check keeps the 1 km absolute tolerance.
MISS_TOLERANCE_FRACTION: float = 0.05


def miss_tolerance_km(p5_km: float) -> float:
    """How closely a series' P5, P50 and P95 must be known: 1 km, or MISS_TOLERANCE_FRACTION of P5 where wider.

    A P5 that is not finite gives the floor, so no tolerance is widened by a series with no misses.
    """
    if not math.isfinite(p5_km):
        return CONVERGENCE_TOLERANCE_KM
    return max(CONVERGENCE_TOLERANCE_KM, MISS_TOLERANCE_FRACTION * p5_km)


def percentile_half_width_km(sma_values: list[float], seed: int = 0) -> float:
    """The widest 95 % bootstrap half-width of SMA P5, P50 and P95, in km.

    Infinite below 50 samples, where the bootstrap itself is not trusted.
    """
    arr = np.asarray(sma_values, dtype=float)
    if arr.size < _MIN_CONVERGENCE_SAMPLES:
        return math.inf
    rng = np.random.default_rng(seed)
    resamples = arr[rng.integers(0, arr.size, size=(_BOOTSTRAP_RESAMPLES, arr.size))]
    shown = np.percentile(resamples, _SHOWN_PERCENTILES, axis=1)
    lo, hi = np.percentile(shown, [2.5, 97.5], axis=1)
    return float(np.max((hi - lo) / 2.0))


def check_convergence(
    sma_values: list[float], tolerance_km: float = CONVERGENCE_TOLERANCE_KM, seed: int = 0,
) -> bool:
    """Whether the SMA percentiles shown are known to within *tolerance_km*.

    It compared the last 200 results with the whole, to 1 % of the SMA for
    the mean (always passing) and of the std (almost never), in thread
    completion order (audit F-103).
    """
    return percentile_half_width_km(sma_values, seed) <= tolerance_km


# ── Main entry point ──────────────────────────────────────────────────────────

def run_monte_carlo(
    hypothesis: ManoeuvreHypothesis,
    satno: int = 0,
    prediction_horizon_hours: float = 48.0,
    max_workers: int = 4,
) -> MonteCarloResult:
    """Run the full Monte Carlo simulation.

    Parameters
    ----------
    hypothesis:
        Manoeuvre hypothesis with uncertainty envelope.
    satno:
        NORAD catalogue number (for logging / result identification).
    prediction_horizon_hours:
        Propagation horizon in hours.
    max_workers:
        Number of threads for parallel propagation.

    Returns
    -------
    MonteCarloResult
    """
    t_start = time.monotonic()
    pre_state = hypothesis.pre_manoeuvre_state_eci_km.copy()

    # Generate all samples
    samples = generate_samples(hypothesis)  # (N, 5)

    # Filled by sample index, not completion order, so a seed always gives
    # the same aggregate whatever the thread count (audit F-103).
    by_index: list[dict[str, Any] | None] = [None] * len(samples)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                propagate_single_sample,
                samples[i],
                pre_state,
                hypothesis.bstar_post,
                prediction_horizon_hours,
            ): i
            for i in range(len(samples))
        }
        for future in as_completed(futures):
            by_index[futures[future]] = future.result()
    results = [r for r in by_index if r is not None]

    n_converged = len(results)
    logger.info(
        "MC for %d: %d/%d converged in %.1fs",
        satno, n_converged, hypothesis.n_samples, time.monotonic() - t_start,
    )

    if not results:
        # Degenerate fallback — all samples diverged
        sma0, ecc0, inc0 = _state_to_keplerian(pre_state[:3], pre_state[3:])
        return MonteCarloResult(
            hypothesis_satno=satno,
            prediction_horizon_hours=prediction_horizon_hours,
            n_samples_run=hypothesis.n_samples,
            n_samples_converged=0,
            converged=False,
            sma_km_mean=sma0, sma_km_std=0.0,
            sma_km_p5=sma0, sma_km_p50=sma0, sma_km_p95=sma0,
            ecc_mean=ecc0, ecc_std=0.0,
            inc_deg_mean=inc0, inc_deg_std=0.0,
            regime_probabilities={classify_orbit_regime(sma0, ecc0): 1.0},
            position_3sigma_km=0.0,
            alt_km_p5=sma0 - _R_E, alt_km_p95=sma0 - _R_E,
            altitude_range_km=(sma0 - _R_E, sma0 - _R_E),
            period_range_minutes=(0.0, 0.0),
            wall_time_seconds=time.monotonic() - t_start,
            random_seed=hypothesis.random_seed,
            direction_basis=hypothesis.direction_basis,
            alt_km_p50=sma0 - _R_E,
            assumptions=MonteCarloAssumptions.of(hypothesis),
        )

    # ── Aggregate results ─────────────────────────────────────────────────────
    sma_arr   = np.array([r["sma_km"]   for r in results])
    ecc_arr   = np.array([r["ecc"]      for r in results])
    inc_arr   = np.array([r["inc_deg"]  for r in results])
    alt_arr   = np.array([r["alt_km"]   for r in results])
    per_arr   = np.array([r["period_min"] for r in results])

    # Position cloud 3-sigma radius
    pos_cloud = np.array([r["r_final"] for r in results])  # (M, 3)
    centroid  = pos_cloud.mean(axis=0)
    dists     = np.linalg.norm(pos_cloud - centroid, axis=1)
    pos_3s    = float(np.percentile(dists, 99.7))

    # Regime probabilities
    regime_counts: dict[str, int] = {}
    for r in results:
        reg = r["regime"]
        regime_counts[reg] = regime_counts.get(reg, 0) + 1
    regime_probs = {k: v / n_converged for k, v in regime_counts.items()}

    half_width = percentile_half_width_km(sma_arr.tolist(), seed=hypothesis.random_seed or 0)

    return MonteCarloResult(
        hypothesis_satno=satno,
        prediction_horizon_hours=prediction_horizon_hours,
        n_samples_run=hypothesis.n_samples,
        n_samples_converged=n_converged,
        converged=half_width <= CONVERGENCE_TOLERANCE_KM,
        percentile_half_width_km=half_width,
        sma_km_mean=float(np.mean(sma_arr)),
        sma_km_std=float(np.std(sma_arr)),
        sma_km_p5=float(np.percentile(sma_arr, 5)),
        sma_km_p50=float(np.percentile(sma_arr, 50)),
        sma_km_p95=float(np.percentile(sma_arr, 95)),
        ecc_mean=float(np.mean(ecc_arr)),
        ecc_std=float(np.std(ecc_arr)),
        inc_deg_mean=float(np.mean(inc_arr)),
        inc_deg_std=float(np.std(inc_arr)),
        regime_probabilities=regime_probs,
        position_3sigma_km=pos_3s,
        alt_km_p5=float(np.percentile(alt_arr, 5)),
        alt_km_p95=float(np.percentile(alt_arr, 95)),
        altitude_range_km=(float(np.min(alt_arr)), float(np.max(alt_arr))),
        period_range_minutes=(float(np.min(per_arr)), float(np.max(per_arr))),
        wall_time_seconds=time.monotonic() - t_start,
        random_seed=hypothesis.random_seed,
        direction_basis=hypothesis.direction_basis,
        alt_km_p50=float(np.percentile(alt_arr, 50)),
        period_min_p5=float(np.percentile(per_arr, 5)),
        period_min_p50=float(np.percentile(per_arr, 50)),
        period_min_p95=float(np.percentile(per_arr, 95)),
        assumptions=MonteCarloAssumptions.of(hypothesis),
    )


# ── Convenience factory ───────────────────────────────────────────────────────

def hypothesis_from_tle_record(
    tle_record: Any,  # TLERecord from pattern_of_life
    manoeuvre: Any,   # Manoeuvre from pattern_of_life
    n_samples: int = 500,
    archetype_override: str | None = None,
) -> ManoeuvreHypothesis:
    """Build a ManoeuvreHypothesis from a detected PoL manoeuvre.

    The pre-manoeuvre state is *tle_record* propagated to the manoeuvre's burn
    epoch (its measured burn time where there is one). The ΔV is split across
    radial, in-track and cross-track in the proportions of the detection's
    element breakdown, in-track signed by the change in semi-major axis; the
    breakdown does not resolve the sense of the radial and cross-track parts.
    Without a breakdown the whole ΔV is assumed in-track, and the hypothesis
    says so. Every hypothesis used to be in-track, so a detected plane change
    was simulated as an orbit raise (audit F-030).
    """
    from spectre.astro.propagator import TLEOrbit

    burn_epoch = getattr(manoeuvre, "burn_epoch", manoeuvre.epoch)
    sv = TLEOrbit(tle_record.tle).propagate(burn_epoch)
    pre_state = np.concatenate([sv.r, sv.v])

    # Pick archetype based on detected manoeuvre type
    archetype_key = archetype_override or manoeuvre.manoeuvre_type
    archetype = MANOEUVRE_ARCHETYPES.get(archetype_key) or MANOEUVRE_ARCHETYPES["orbit_raise"]

    dv = manoeuvre.delta_v_km_s
    dv_1sig = max(dv * archetype.delta_v_1sigma_fraction, 0.0005)
    ric, basis = _ric_split(getattr(manoeuvre, "breakdown", None))

    return ManoeuvreHypothesis(
        epoch_utc=burn_epoch,
        delta_v_magnitude_km_s=dv,
        delta_v_radial=dv * ric[0],
        delta_v_in_track=dv * ric[1],
        delta_v_cross_track=dv * ric[2],
        pre_manoeuvre_state_eci_km=pre_state,
        delta_v_magnitude_1sigma_km_s=dv_1sig,
        delta_v_pointing_1sigma_deg=archetype.pointing_1sigma_deg,
        epoch_1sigma_seconds=archetype.timing_1sigma_seconds,
        bstar_post=getattr(manoeuvre.tle_before, "bstar", 1e-4),
        n_samples=n_samples,
        direction_basis=basis,
        archetype=archetype.name,
    )


def _ric_split(breakdown: Any) -> tuple[np.ndarray, str]:
    """Unit RIC direction from a detection's element breakdown, and its basis."""
    channels = {c.channel: c for c in getattr(breakdown, "components", ())}
    along = channels.get("along_track")
    sense = -1.0 if along is not None and along.inputs.get("delta_a_km", 0.0) < 0.0 else 1.0
    ric = np.array([
        channels["radial"].dv_km_s if "radial" in channels else 0.0,
        sense * along.dv_km_s if along is not None else 0.0,
        channels["cross_track"].dv_km_s if "cross_track" in channels else 0.0,
    ])
    norm = float(np.linalg.norm(ric))
    if norm < _ZERO_DV_KM_S:
        return np.array([0.0, 1.0, 0.0]), "assumed in-track: no element breakdown"
    return ric / norm, (
        "split from the detection's element breakdown; "
        "sense of radial and cross-track parts not resolved"
    )


# ── Separation series against a blue track (SPC-110) ─────────────────────────


class BlueTrack(NamedTuple):
    """An object's state from its element set, the instant it holds at, and the element set's drag term.

    ``state_eci_km`` is SGP4's TEME state [x, y, z, vx, vy, vz] (km, km/s) at
    ``epoch_utc``; ``bstar`` is the element set's B*, for the drag in the
    RK45 propagation. A separation series refuses a track whose epoch is not
    its window start.
    """

    state_eci_km: np.ndarray
    bstar: float
    epoch_utc: datetime


def elset_state(tle: str, at: datetime) -> BlueTrack | None:
    """The SGP4 TEME state of *tle* at *at*, with its B*; None when it cannot be had.

    None covers an element set that does not parse and one SGP4 cannot
    propagate to *at* (TLE_ERRORS). It lives here so the Decision Engine never
    names the propagator.
    """
    from spectre.astro.propagator import TLE_ERRORS, TLEOrbit

    try:
        orbit = TLEOrbit(tle)
        sv = orbit.propagate(at)
    except TLE_ERRORS:
        return None
    return BlueTrack(state_eci_km=np.concatenate([sv.r, sv.v]), bstar=orbit.bstar, epoch_utc=at)


class ElsetError(NamedTuple):
    """Each object's element-set position error along its orbit at the window start, 1 sigma, km (SPC-202).

    A separation series given one draws, for every sample, an offset of each object along its orbit from a normal
    distribution of this sigma, and flies that object from where the offset puts it: its whole trajectory a moment
    earlier or later, by the offset over its speed then, which is the same orbit moved along itself. The Decision
    Engine reads the sigmas from spectre/astro/along_track.py's model at each element set's age.
    """

    red_km: float
    blue_km: float


#: The element-set draws' own stream, so they never share a seed with the burn draws generate_samples makes from the
#: hypothesis's seed alone (SPC-202). The SPC number; any constant apart from the burn's would serve.
ELSET_ERROR_STREAM = 202
#: The two sides' indices in an element-set draw: red, then blue.
_RED, _BLUE = 0, 1


def elset_offsets_km(error: ElsetError, seed: int, n: int) -> np.ndarray:
    """Each of *n* samples' along-track offsets, red then blue, km: shape (n, 2) (SPC-202).

    Sample k's draw for side s is one standard normal from its own generator, seeded (seed, ELSET_ERROR_STREAM, k,
    s), times that side's sigma: the same whatever the sample count, and one side's sigma never moves the other's.
    Positive is ahead along the orbit.
    """
    sigmas = (error.red_km, error.blue_km)
    draws = [
        [float(np.random.default_rng((seed, ELSET_ERROR_STREAM, k, side)).standard_normal()) for side in (_RED, _BLUE)]
        for k in range(n)
    ]
    offsets: np.ndarray = np.asarray(draws, dtype=float).reshape(n, 2) * np.asarray(sigmas, dtype=float)
    return offsets


#: Added to every arc's padding, s, so a shifted arc never reads its integrator's own end.
_PAD_MARGIN_S = 1.0


def _slowest_km_s(state: np.ndarray) -> float:
    """The slowest the object at *state* goes on its orbit, km/s: at apogee, by vis-viva; its speed now if the orbit
    is not closed."""
    speed = float(np.linalg.norm(state[3:]))
    sma, ecc, _ = _state_to_keplerian(np.asarray(state[:3]), np.asarray(state[3:]))
    if not (sma > 0.0 and ecc < 1.0):
        return speed
    return min(speed, math.sqrt(_MU / sma * (1.0 - ecc) / (1.0 + ecc)))


def _pad_s(offsets_km: np.ndarray, state: np.ndarray) -> float:
    """How far past each end an arc must run for every one of *offsets_km* to be read from it, s; 0 with none."""
    largest = float(np.max(np.abs(offsets_km), initial=0.0))
    return 0.0 if not largest else largest / _slowest_km_s(state) + _PAD_MARGIN_S


def _shifted(arc: _Trajectory, dt_s: float) -> _Trajectory:
    """*arc* *dt_s* later along itself: the object where the arc puts it dt_s on (SPC-202). *arc* itself for 0."""
    if not dt_s:
        return arc
    return lambda t: arc(t + dt_s)


def _shift_s(offset_km: float, state: np.ndarray) -> float:
    """The time an object at *state* takes to cover *offset_km* along its orbit, s: the shift that moves it so far."""
    return 0.0 if not offset_km else offset_km / float(np.linalg.norm(state[3:]))


#: What every separation series propagates with, stated on the series.
SEPARATION_PROPAGATOR = "RK45 with J2 and exponential drag, red and blue alike"

#: The altitude, km, below which a separation series stops an arc: the
#: conventional edge of space (the Karman line). Below it the object is
#: minutes from re-entry, and the exponential atmosphere is no guide to
#: where it goes; a miss computed past it would be one the series has not earned.
REENTRY_FLOOR_KM = 100.0

#: A trajectory: the state [x, y, z, vx, vy, vz] at t seconds after the window start.
_Trajectory = Callable[[float], np.ndarray]
#: Called after each sample of a separation series with (samples done, samples in all); it may raise to stop it.
Tick = Callable[[int, int], None]


class SeparationWindow(NamedTuple):
    """The window a separation series searches: its start, its span and the helper's grid step, in seconds."""

    start_utc: datetime
    span_s: float
    step_s: float = 60.0


class BlueBurn(NamedTuple):
    """Our impulsive burn on the blue asset (SPC-121): when, s after the window start, and its RIC delta-V, km/s."""

    at_s: float
    delta_v_ric_km_s: tuple[float, float, float]


class MissStats(NamedTuple):
    """P5, P50 and P95 of a set of misses, their spread, and how closely the percentiles are known, km."""

    p5: float
    p50: float
    p95: float
    std: float
    half_width_km: float
    tolerance_km: float
    converged: bool


class BurnSeries(NamedTuple):
    """One of our burns across a series' samples (SPC-121): each sample's closest approach to the burnt blue asset.

    ``approaches`` and ``closing_speeds_km_s`` run in sample order over the samples that propagated both red and
    the burnt blue; ``n_failed`` counts the rest. Paired with the series' own approaches by sample.
    """

    burn: BlueBurn
    approaches: tuple[ClosestApproach, ...]
    closing_speeds_km_s: tuple[float, ...]
    n_failed: int
    stats: MissStats


class Kept(NamedTuple):
    """Each sample's red state and B* at a game tree's turn boundaries, in sample order, and its smallest separation
    from each blue between the window start and the first boundary (SPC-140). NaN where a sample failed.

    ``red`` is (samples, boundaries, 6), km and km/s; ``bstar`` the B* each sample flies at the first boundary;
    ``slice_min_km`` is (blues, samples), the blues in the order the series searched them; ``pending`` holds, per
    sample, the burns its draw puts after the first boundary, timed from it, for the turn after to make.
    """

    at_s: tuple[float, ...]
    red: np.ndarray
    bstar: np.ndarray
    slice_min_km: np.ndarray
    pending: tuple[tuple[RedBurn, ...], ...]
    # Each sample's blue, that many seconds on along its own orbit: its element-set draw (SPC-202), for the next turn
    # to search against blue moved as this one did. None when the series drew none.
    blue_shift_s: np.ndarray | None = None


class RedBurn(NamedTuple):
    """One of a red sample's burns: *at_s* seconds after its window start, its RIC delta-V and the B* after it."""

    at_s: float
    delta_v_ric_km_s: np.ndarray
    bstar_after: float


@dataclass(frozen=True)
class SeparationSeries:
    """Each sample's closest approach to the blue track in one window, and their statistics.

    ``approaches`` holds one ClosestApproach per sample that propagated, in
    sample order; ``n_failed`` counts the rest, and ``n_reentered`` those of
    them whose red arc went below REENTRY_FLOOR_KM. The percentiles and
    standard deviation are numpy's over the approaches' misses, NaN when there
    are none. ``converged`` is the engine's own check: percentile_half_width_km
    within ``tolerance_km``, which is miss_tolerance_km of P5 (1 km, or 5 % of
    P5 where that is wider, SPC-117), never true below 50 samples. ``integration_s`` is what the series cost: the seconds of
    trajectory it integrated (separation_integration_s).
    """

    window: SeparationWindow
    approaches: tuple[ClosestApproach, ...]
    n_samples_run: int
    n_failed: int
    n_reentered: int
    miss_km_p5: float
    miss_km_p50: float
    miss_km_p95: float
    miss_km_std: float
    percentile_half_width_km: float
    converged: bool
    random_seed: int
    integration_s: float
    wall_time_seconds: float
    tolerance_km: float = CONVERGENCE_TOLERANCE_KM
    propagator: str = SEPARATION_PROPAGATOR
    # Each sample's relative speed at its TCA, km/s, parallel to approaches (SPC-118); empty when not recorded.
    closing_speeds_km_s: tuple[float, ...] = ()
    # Each of our burns on the blue asset, against the same samples (SPC-121); empty when none was asked for.
    after_burns: tuple[BurnSeries, ...] = ()
    # Each sample's red state and B* at a game tree's turn boundary, and its smallest separation from each blue
    # within the turn (SPC-140); None unless a boundary was asked for. Arrays, so never compared.
    kept: Kept | None = field(default=None, compare=False)
    # The element-set error each sample drew, red's and blue's 1 sigma (SPC-202); None when none was drawn.
    elset_error: ElsetError | None = None

    def __post_init__(self) -> None:
        if self.closing_speeds_km_s and len(self.closing_speeds_km_s) != len(self.approaches):
            raise ValueError(
                f"a series holds one closing speed per approach or none; got {len(self.closing_speeds_km_s)} "
                f"for {len(self.approaches)} approaches"
            )

    @property
    def percentiles(self) -> dict[int, float]:
        """P5, P50 and P95 of the misses, in km, keyed 5, 50 and 95."""
        return {5: self.miss_km_p5, 50: self.miss_km_p50, 95: self.miss_km_p95}

    @property
    def closest_sample_km(self) -> float:
        """The smallest miss of any sample, in km; NaN with no samples."""
        return min((a.miss_km for a in self.approaches), default=math.nan)

    @property
    def n_at_window_edge(self) -> int:
        """Samples whose smallest separation is at the window's start or end, not an encounter."""
        return sum(a.at_window_edge for a in self.approaches)

    @property
    def earliest_tca_at_or_below_p5_s(self) -> float:
        """The earliest TCA, in seconds after the window start, of the samples whose miss is at or below P5."""
        return min((a.tca_s for a in self.approaches if a.miss_km <= self.miss_km_p5), default=math.nan)

    @property
    def earliest_at_or_below_p5_index(self) -> int | None:
        """Which approach sets earliest_tca_at_or_below_p5_s, the first on a tie; None with no sample at or below P5."""
        at_or_below = [(a.tca_s, k) for k, a in enumerate(self.approaches) if a.miss_km <= self.miss_km_p5]
        return min(at_or_below)[1] if at_or_below else None


class _Arcs(NamedTuple):
    """What every sample shares: the blue arc, red's unburnt arc and its nominal burn time (s after the start)."""

    blue: _Trajectory
    unburnt: _Trajectory
    burn_s: float


class ReenteredError(Exception):
    """An arc went below REENTRY_FLOOR_KM."""


class Sampled(NamedTuple):
    """One closest approach and the two objects' relative speed at it, km/s."""

    approach: ClosestApproach
    closing_speed_km_s: float


#: What a sample gives when it has no closest approach.
_FAILED = "failed"
_REENTERED = "re-entered"


# PLR0913: three positional inputs, then one keyword per thing a caller may ask of the series, each optional.
def run_separation_series(  # noqa: PLR0913
    hypothesis: ManoeuvreHypothesis, blue: BlueTrack, window: SeparationWindow, *, tick: Tick | None = None,
    blue_burns: Sequence[BlueBurn] = (), keep_at_s: Sequence[float] = (),
    red_then: Sequence[ManoeuvreHypothesis] = (), elset_error: ElsetError | None = None,
) -> SeparationSeries:
    """Each sample's closest approach to *blue* in *window*, with P5, P50 and P95 of the misses.

    *blue* must hold at the window start; the hypothesis's pre-manoeuvre state
    holds at its epoch. Red's unburnt arc is integrated once, back and forward
    from that epoch, at ``bstar_post``; blue's is integrated once over the
    window at its own B*. Each sample burns at the epoch plus its timing
    offset: its delta-V is applied in the RIC frame to the unburnt state there,
    and the burnt arc is integrated to the window end at ``bstar_post`` plus
    its B* offset. Red is the unburnt arc before the burn and the burnt arc
    after it, so a burn before the window is applied and a burn at or after
    its end leaves the unburnt approach; neither is dropped. Each sample's
    closest approach comes from the shared helper, closest_approach.

    Every arc stops at REENTRY_FLOOR_KM. A sample whose burnt arc crosses it
    is counted failed and re-entered; a shared arc that crosses it (blue's, or
    red's before any burn) fails every sample, since no sample's approach can
    then be had.

    Runs serially: threads were measured about four times slower than one
    here, because the equations of motion hold the GIL. Raises ValueError,
    before anything is integrated, when the window is one the helper would
    refuse or *blue* holds at another instant.

    *tick*, when given, is called after each sample with (samples done,
    samples in all), outside the sample's own excepts. It may raise to stop
    the series: the exception propagates and no series is returned (SPC-113's
    budget and cancellation).

    Each of *blue_burns* (SPC-121) is applied to blue's RK45 arc at its time,
    the burnt arc integrated once with the same model, and every sample's red
    searched against it too, so each burn's figure is paired with the no-burn
    one by sample and one model sits on both sides of the difference. A burnt
    arc that fails, or a search against it that fails, fails that sample for
    that burn alone.

    With *keep_at_s* (SPC-140), passed only when not empty, the series also keeps each sample's red state and B* at
    those times, seconds after the window start, and its smallest separation from each blue between the window
    start and the first of them, so a game tree's next turn can start where this one left each sample. Keeping
    changes no figure.

    Each of *red_then* (SPC-184) is a later burn of the same transfer, one action with the first: each sample makes
    it after the first, in time order, at its own time plus its own drawn timing offset, with its own drawn delta-V
    and B* after it, in the RIC frame of the sample's own state then, from the burn's own seed. Its epoch, delta-V,
    direction, spreads and seed are read; its pre-manoeuvre state is not. A later burn whose drawn time falls before
    the sample's first burn is made at the first. The series integrates red from its first burn on, as with one
    burn, so its cost does not grow with the burns.

    With *elset_error* (SPC-202), every sample also draws each object's element-set error along its orbit
    (elset_offsets_km, from the hypothesis's seed) and flies that object from where the draw puts it: red's unburnt
    arc and blue's arc, each read that many seconds on, so the shared arcs are still integrated once, a little past
    each end. A sample's burn is made from its moved red; our burns on blue keep their time on blue's moved arc, so
    each is made at the same point of blue's orbit. The misses, and so the band, P5, convergence and score, are then
    of the moved objects. With none, or both sigmas 0, nothing changes.
    """
    _check_window(window, blue)
    _check_burns(blue_burns)
    t_start = time.monotonic()
    samples = generate_samples(hypothesis)
    burn_s = (hypothesis.epoch_utc - window.start_utc).total_seconds()
    keeper = _Keeper(keep_at_s, len(samples), 1 + len(blue_burns), window) if keep_at_s else None
    later = _later_draws(red_then, len(samples), window)
    seed = hypothesis.random_seed or 0
    offsets = _offsets(elset_error, seed, len(samples))
    outcomes = _approaches(hypothesis, samples, blue, window, _Hooks(tick, blue_burns, keeper, later, offsets))
    series = _series_of(
        window, [outcome[0] for outcome in outcomes], _Ran(hypothesis.random_seed, t_start, keeper),
        integration_s=_integration_s(burn_s + samples[:, 3], burn_s, window.span_s),
        after_burns=tuple(
            _burn_series(burn, [outcome[k + 1] for outcome in outcomes], seed) for k, burn in enumerate(blue_burns)
        ),
        elset_error=None if offsets is None else elset_error,
    )
    logger.info(
        "Separation series: %d/%d samples in %.1fs over %.0f s",
        len(series.approaches), hypothesis.n_samples, series.wall_time_seconds, window.span_s,
    )
    return series


def _offsets(error: ElsetError | None, seed: int, n: int) -> np.ndarray | None:
    """Each sample's along-track offsets, or None when there is no error to draw."""
    if error is None or not (error.red_km or error.blue_km):
        return None
    return elset_offsets_km(error, seed, n)


class _Ran(NamedTuple):
    """What a series records of how it ran: its seed, when it started, and what it kept, if anything."""

    seed: int
    started: float
    keeper: _Keeper | None = None


def _series_of(
    window: SeparationWindow, outcomes: Sequence[Sampled | str], ran: _Ran, **extra: Any,
) -> SeparationSeries:
    """A series from each sample's outcome against one blue, in sample order, with its statistics."""
    sampled = [a for a in outcomes if isinstance(a, Sampled)]
    stats = _miss_stats([a.approach.miss_km for a in sampled], ran.seed or 0)
    return SeparationSeries(
        window=window,
        approaches=tuple(a.approach for a in sampled),
        n_samples_run=len(outcomes),
        n_failed=len(outcomes) - len(sampled),
        n_reentered=list(outcomes).count(_REENTERED),
        miss_km_p5=stats.p5,
        miss_km_p50=stats.p50,
        miss_km_p95=stats.p95,
        miss_km_std=stats.std,
        percentile_half_width_km=stats.half_width_km,
        converged=stats.converged,
        random_seed=ran.seed,
        wall_time_seconds=time.monotonic() - ran.started,
        tolerance_km=stats.tolerance_km,
        closing_speeds_km_s=tuple(a.closing_speed_km_s for a in sampled),
        kept=None if ran.keeper is None else ran.keeper.kept,
        **extra,
    )


def _miss_stats(misses: Sequence[float], seed: int) -> MissStats:
    """P5, P50 and P95 of *misses*, their spread, half-width and tolerance; NaN percentiles with no misses."""
    values = np.asarray(misses, dtype=float)
    half_width = percentile_half_width_km(values.tolist(), seed=seed)
    p5, p50, p95 = (
        (float(p) for p in np.percentile(values, _SHOWN_PERCENTILES)) if values.size else (math.nan,) * 3
    )
    tolerance = miss_tolerance_km(p5)
    std = float(np.std(values)) if values.size else math.nan
    return MissStats(p5, p50, p95, std, half_width, tolerance, half_width <= tolerance)


def _burn_series(burn: BlueBurn, outcomes: Sequence[Sampled | str], seed: int) -> BurnSeries:
    """One burn's approaches across the samples, in sample order, with their statistics."""
    sampled = [a for a in outcomes if isinstance(a, Sampled)]
    return BurnSeries(
        burn=burn,
        approaches=tuple(a.approach for a in sampled),
        closing_speeds_km_s=tuple(a.closing_speed_km_s for a in sampled),
        n_failed=len(outcomes) - len(sampled),
        stats=_miss_stats([a.approach.miss_km for a in sampled], seed),
    )


def _check_burns(burns: Sequence[BlueBurn]) -> None:
    """Raise ValueError for one of our burns before the window or at no finite time."""
    for burn in burns:
        if not (math.isfinite(burn.at_s) and burn.at_s >= 0.0):
            raise ValueError(f"our burn must be at or after the window start; got {burn.at_s!r} s")


def burnt_arc(arc: _Trajectory, burn: BlueBurn, end_s: float, bstar: float) -> _Trajectory | None:
    """*arc* with *burn* applied at its time and the rest integrated by RK45 to *end_s* (SPC-121).

    The arc itself before the burn, so the same model holds on both sides of it; *arc* unchanged when the burn is
    at or after *end_s*. None when the solve fails; raises ReenteredError when the burnt arc goes below the floor.
    """
    if burn.at_s >= end_s:
        return arc
    state = arc(burn.at_s).copy()
    state[3:] += _ric_to_eci_rotation(state[:3], state[3:]) @ np.asarray(burn.delta_v_ric_km_s, dtype=float)
    after = _dense_arc(state, burn.at_s, end_s, bstar)
    return None if after is None else _spliced(arc, after, burn.at_s)


def nominal_red_arc(
    hypothesis: ManoeuvreHypothesis, window: SeparationWindow, then: Sequence[ManoeuvreHypothesis] = (),
) -> _Trajectory | None:
    """Red with the hypothesis's nominal burn, undispersed, over *window*; None when it cannot be integrated.

    What our burn is sized against in a sampled row (SPC-121): the burn of the hypothesis as stated, before any
    spread is drawn. *then* holds the later burns of the same transfer (SPC-184), each made as stated after it.
    """
    nominal = _nominal_draw(hypothesis)
    burn_s = (hypothesis.epoch_utc - window.start_utc).total_seconds()
    try:
        unburnt = _unburnt_arc(hypothesis, min(0.0, burn_s), window.span_s, burn_s)
        if unburnt is None:
            return None
        if then:
            burns = [RedBurn(burn_s, nominal[:3], hypothesis.bstar_post)] + [
                RedBurn((h.epoch_utc - window.start_utc).total_seconds(), _nominal_draw(h)[:3], h.bstar_post)
                for h in then
            ]
            return _chained_red(unburnt, burns, hypothesis.bstar_post, window)
        return _sample_red(nominal, unburnt, burn_s, hypothesis.bstar_post, window)
    except (ReenteredError, ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return None


def rk45_arc(state: np.ndarray, span_s: float, bstar: float, pad_s: float = 0.0) -> _Trajectory | None:
    """*state* at the window start integrated by this engine's RK45 to *span_s*, and *pad_s* past each end for a
    sample's element-set shift to read (SPC-202); None when the solve fails.

    Raises ReenteredError when the arc goes below REENTRY_FLOOR_KM.
    """
    return _padded_arc(state, span_s, bstar, pad_s)


def shift_pad_s(shifts_s: np.ndarray | None) -> float:
    """How far past each end an arc must run for every one of *shifts_s* to be read from it, s; 0 with none."""
    largest = 0.0 if shifts_s is None else float(np.max(np.abs(shifts_s), initial=0.0))
    return 0.0 if not largest else largest + _PAD_MARGIN_S


def along_track_shifts_s(offsets_km: np.ndarray, state: np.ndarray) -> np.ndarray:
    """Each of *offsets_km* as the seconds an object at *state* takes to cover it along its orbit (SPC-202)."""
    return np.array([_shift_s(float(x), state) for x in offsets_km])


def moved_states(state: np.ndarray, bstar: float, offsets_km: np.ndarray) -> np.ndarray | None:
    """*state* moved along its own orbit by each of *offsets_km*, km: the states (n, 6) an RK45 arc from it puts
    the object at that many seconds on (SPC-202). None when the arc cannot be had."""
    shifts = np.array([_shift_s(float(x), state) for x in offsets_km])
    try:
        arc = _padded_arc(state, 0.0, bstar, _pad_s(np.asarray(offsets_km, dtype=float), state))
    except ReenteredError:
        return None
    if arc is None:
        return None
    return np.array([arc(float(dt)) for dt in shifts])


def separation_integration_s(hypothesis: ManoeuvreHypothesis, window: SeparationWindow) -> float:
    """The seconds of trajectory run_separation_series would integrate, known before it runs.

    Blue over the window, red's unburnt arc from the earliest of the window
    start and the sample burns to the later of the window end and the nominal
    burn, and each sample from its burn to the window end. A series costs in
    proportion to this, not to the window alone: a burn a day before a 1 h
    window integrates 25 h per sample.
    """
    burn_s = (hypothesis.epoch_utc - window.start_utc).total_seconds()
    return _integration_s(burn_s + generate_samples(hypothesis)[:, 3], burn_s, window.span_s)


def _integration_s(burns_s: np.ndarray, burn_s: float, span_s: float) -> float:
    """Seconds integrated for sample burns *burns_s* and nominal burn *burn_s* (s after the start) over *span_s*."""
    unburnt = max(span_s, burn_s) - min(_earliest_s(burns_s), burn_s)
    burnt = float(np.sum(np.clip(span_s - burns_s, 0.0, None)))
    return span_s + unburnt + burnt


def _earliest_s(burns_s: np.ndarray) -> float:
    """Where red's unburnt arc must start: the window start or the earliest sample burn before it."""
    return min(0.0, float(np.min(burns_s, initial=math.inf)))


def _check_window(window: SeparationWindow, blue: BlueTrack) -> None:
    """Raise ValueError for a window closest_approach would refuse, or a blue track from another instant."""
    _check_span(window)
    if blue.epoch_utc != window.start_utc:
        raise ValueError(
            f"separation window: the blue track holds at {blue.epoch_utc.isoformat()}, "
            f"not at the window start {window.start_utc.isoformat()}"
        )


def _check_span(window: SeparationWindow) -> None:
    """Raise ValueError for a window closest_approach would refuse."""
    span, step = window.span_s, window.step_s
    if not (math.isfinite(span) and span > 0.0 and math.isfinite(step) and step > 0.0):
        raise ValueError(f"separation window: span {span!r} s and step {step!r} s must be finite and > 0")
    if span / step > MAX_SAMPLES - 1:
        raise ValueError(
            f"separation window: {span:,.0f} s at {step:g} s steps needs more than the "
            f"{MAX_SAMPLES:,} samples the closest-approach helper takes"
        )


class _Hooks(NamedTuple):
    """What a series is asked for besides its samples: the tick after each, and our burns on blue (SPC-121)."""

    tick: Tick | None = None
    blue_burns: Sequence[BlueBurn] = ()
    # Keeps each sample's state at a game tree's turn boundary (SPC-140); None when none was asked for.
    keeper: _Keeper | None = None
    # Per sample, the later burns of its transfer as drawn (SPC-184); empty for a single burn.
    later: tuple[tuple[RedBurn, ...], ...] = ()
    # Per sample, red's and blue's along-track offsets, km (SPC-202); None for none.
    offsets_km: np.ndarray | None = None


def _approaches(
    hypothesis: ManoeuvreHypothesis, samples: np.ndarray, blue: BlueTrack, window: SeparationWindow,
    hooks: _Hooks = _Hooks(),
) -> list[tuple[Sampled | str, ...]]:
    """Per sample, in sample order: its closest approach to blue, then to blue after each of our burns.

    _FAILED or _REENTERED stands where there is none. The tick is called after each sample, outside _try_sample,
    so its excepts never swallow what a tick raises; the exception propagates and no result is returned. When the
    shared arcs fail, no sample runs and no tick is called.
    """
    tick, blue_burns, keeper, later, offsets = hooks
    burn_s = (hypothesis.epoch_utc - window.start_utc).total_seconds()
    earliest = _earliest_s(burn_s + samples[:, 3])
    pads = _Pads.of(offsets, hypothesis, blue)
    try:
        blue_arc = _padded_arc(blue.state_eci_km, window.span_s, blue.bstar, pads.blue)
        unburnt = _unburnt_arc(hypothesis, earliest - pads.red, window.span_s + pads.red, burn_s)
    except (ArithmeticError, ValueError, ReenteredError):   # numpy's LinAlgError is a ValueError
        blue_arc = unburnt = None
    if blue_arc is None or unburnt is None:
        return [(_FAILED,) * (1 + len(blue_burns))] * len(samples)
    arcs = _Arcs(blue=blue_arc, unburnt=unburnt, burn_s=burn_s)
    padded = window._replace(span_s=window.span_s + pads.blue)
    blues = (blue_arc, *(_burnt_blue(blue_arc, burn, padded, blue.bstar) for burn in blue_burns))
    shifts = _shifts(offsets, unburnt(0.0), blue.state_eci_km, len(samples))
    outcomes: list[tuple[Sampled | str, ...]] = []
    for k, sample in enumerate(samples):
        red_dt, blue_dt = shifts[k]
        moved = tuple(b if isinstance(b, str) else _shifted(b, blue_dt) for b in blues)
        keep = _hearing(keeper, k, moved, blue_dt)
        outcomes.append(_try_sample(sample, arcs._replace(unburnt=_shifted(unburnt, red_dt)), hypothesis.bstar_post,
                                    window, moved, keep, later[k] if later else ()))
        if tick is not None:
            tick(len(outcomes), len(samples))
    return outcomes


class _Pads(NamedTuple):
    """How far past each end red's unburnt arc and blue's arc run, s, so every sample's shift reads inside them."""

    red: float
    blue: float

    @classmethod
    def of(cls, offsets: np.ndarray | None, hypothesis: ManoeuvreHypothesis, blue: BlueTrack) -> _Pads:
        if offsets is None:
            return cls(0.0, 0.0)
        red_state = np.asarray(hypothesis.pre_manoeuvre_state_eci_km, dtype=float)
        return cls(_pad_s(offsets[:, _RED], red_state), _pad_s(offsets[:, _BLUE], blue.state_eci_km))


def _shifts(
    offsets: np.ndarray | None, red_start: np.ndarray, blue_start: np.ndarray, n: int,
) -> list[tuple[float, float]]:
    """Each sample's red and blue shifts, s: its offsets over each object's speed at the window start; 0 for none."""
    if offsets is None:
        return [(0.0, 0.0)] * n
    return [(_shift_s(float(r), red_start), _shift_s(float(b), blue_start)) for r, b in offsets]


def _padded_arc(state: np.ndarray, span_s: float, bstar: float, pad_s: float) -> _Trajectory | None:
    """*state* at the window start integrated over the window and *pad_s* past each end; the window alone for 0."""
    ahead = _dense_arc(state, 0.0, span_s + pad_s, bstar)
    if not pad_s or ahead is None:
        return ahead
    back = _dense_arc(state, 0.0, -pad_s, bstar)
    return None if back is None else _spliced(back, ahead, 0.0)


def _burnt_blue(arc: _Trajectory, burn: BlueBurn, window: SeparationWindow, bstar: float) -> _Trajectory | str:
    """Blue after *burn*, integrated once for every sample, or why it cannot be had."""
    try:
        burnt = burnt_arc(arc, burn, window.span_s, bstar)
    except ReenteredError:
        return _REENTERED
    except (ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return _FAILED
    return _FAILED if burnt is None else burnt


def _altitude_km(_t: float, state: np.ndarray, *_: float) -> float:
    """Height above REENTRY_FLOOR_KM, km: solve_ivp's event, zero at the floor."""
    return float(np.linalg.norm(state[:3])) - _R_E - REENTRY_FLOOR_KM


_altitude_km.terminal = True   # type: ignore[attr-defined]  # solve_ivp reads these off the event


def _dense_arc(state: np.ndarray, t0_s: float, t1_s: float, bstar: float) -> _Trajectory | None:
    """*state* at *t0_s* integrated densely to *t1_s*, either way; None when the solve fails.

    Raises ReenteredError when the arc starts or goes below REENTRY_FLOOR_KM.
    """
    if _altitude_km(t0_s, state) < 0.0:
        raise ReenteredError(f"the arc starts {-_altitude_km(t0_s, state):.1f} km below the floor")
    if abs(t1_s - t0_s) < _ZERO_SPAN_S:
        return lambda _t: state.copy()
    sol = solve_ivp(
        _j2_drag_ode,
        (t0_s, t1_s),
        state,
        method="RK45",
        rtol=RK45_RTOL,
        atol=RK45_ATOL,
        args=(_ballistic_coefficient_kg_m2(bstar),),
        dense_output=True,
        events=_altitude_km,
    )
    if sol.status == 1:
        raise ReenteredError(f"the arc reaches the floor at {float(sol.t_events[0][0]):.0f} s")
    return sol.sol if sol.success else None


def _unburnt_arc(
    hypothesis: ManoeuvreHypothesis, earliest_s: float, end_s: float, burn_s: float,
) -> _Trajectory | None:
    """Red without the burn over [*earliest_s*, *end_s*], integrated back and forward from *burn_s*."""
    pre = hypothesis.pre_manoeuvre_state_eci_km
    back = _dense_arc(pre, burn_s, min(earliest_s, burn_s), hypothesis.bstar_post)
    ahead = _dense_arc(pre, burn_s, max(end_s, burn_s), hypothesis.bstar_post)
    if back is None or ahead is None:
        return None
    return _spliced(back, ahead, burn_s)


def _spliced(before: _Trajectory, after: _Trajectory, at_s: float) -> _Trajectory:
    """*before* up to *at_s* seconds and *after* from it."""
    return lambda t: before(t) if t < at_s else after(t)


# PLR0913, PLR0917: one sample's draw, its shared arcs and what it is searched against.
def _try_sample(  # noqa: PLR0913, PLR0917
    sample: np.ndarray, arcs: _Arcs, bstar_post: float, window: SeparationWindow,
    blues: Sequence[_Trajectory | str], keep: Callable[[_RedArc], None] | None = None,
    later: tuple[RedBurn, ...] = (),
) -> tuple[Sampled | str, ...]:
    """One sample's red, built once, searched against each of *blues*: its approach to each, or why there is none.

    A red that cannot be had fails the sample against every blue; a blue that cannot be had, or a search against
    it that fails, fails the sample against that blue alone. *keep*, when given, hears the sample's red (SPC-140).
    *later* holds the sample's later burns of the same transfer, as drawn (SPC-184).
    """
    first = RedBurn(arcs.burn_s + float(sample[3]), sample[:3].copy(), bstar_post + float(sample[4]))
    try:
        if later:
            red = _chained_red(arcs.unburnt, (first, *later), bstar_post, window)
        else:
            red = _sample_red(sample, arcs.unburnt, arcs.burn_s, bstar_post, window)
    except ReenteredError:
        return (_REENTERED,) * len(blues)
    except (ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return (_FAILED,) * len(blues)
    if red is None:
        return (_FAILED,) * len(blues)
    if keep is not None:
        keep(_RedArc(red, bstar_post, (first, *later)))
    return tuple(_search_or_fail(red, blue, window) for blue in blues)


def _search_or_fail(red: _Trajectory, blue: _Trajectory | str, window: SeparationWindow) -> Sampled | str:
    """The approach of *red* to *blue*, or _FAILED when blue could not be had or the search fails."""
    if isinstance(blue, str):
        return _FAILED
    try:
        return searched_approach(red, blue, window)
    except (ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return _FAILED


def _sample_red(
    sample: np.ndarray, unburnt: _Trajectory, nominal_burn_s: float, bstar_post: float, window: SeparationWindow,
) -> _Trajectory | None:
    """Red burnt as *sample* says over *window*; None when the burnt arc's solve fails."""
    burn_s = nominal_burn_s + float(sample[3])
    if burn_s >= window.span_s:
        return unburnt
    state = unburnt(burn_s).copy()
    state[3:] += _ric_to_eci_rotation(state[:3], state[3:]) @ sample[:3]
    burnt = _dense_arc(state, burn_s, window.span_s, bstar_post + float(sample[4]))
    return None if burnt is None else _spliced(unburnt, burnt, burn_s)


def _later_draws(
    later: Sequence[ManoeuvreHypothesis], n: int, window: SeparationWindow,
) -> tuple[tuple[RedBurn, ...], ...]:
    """Per sample, each later burn of the transfer as drawn from its own spreads and seed (SPC-184); empty for none.

    Each burn's draws come from generate_samples at the series' sample count, so sample k's draw of burn j is the
    same whichever other burns the row carries.
    """
    if not later:
        return ()
    timed = [
        ((h.epoch_utc - window.start_utc).total_seconds(), h.bstar_post, generate_samples(replace(h, n_samples=n)))
        for h in later
    ]
    return tuple(
        tuple(RedBurn(at_s + float(draws[k, 3]), draws[k, :3].copy(), bstar + float(draws[k, 4]))
              for at_s, bstar, draws in timed)
        for k in range(n)
    )


def _chained_red(
    unburnt: _Trajectory, burns: Sequence[RedBurn], bstar: float, window: SeparationWindow,
) -> _Trajectory | None:
    """Red unburnt until the first of *burns*, then making each in time order to the window end (SPC-184).

    A later burn drawn before the first is made at the first, so red never burns before its transfer starts. None
    when a solve fails; ReenteredError below the floor.
    """
    first, *rest = burns
    start = first.at_s
    if start >= window.span_s:
        return unburnt
    # _continued_red makes them in time order; the first stays first, since none is made before it.
    clamped = (first, *(b._replace(at_s=max(b.at_s, start)) for b in rest))
    red = _continued_red(unburnt(start).copy(), bstar, clamped, window.span_s, start_s=start)
    return None if red is None else _spliced(unburnt, red.arc, start)


def searched_approach(red: _Trajectory, blue: _Trajectory, window: SeparationWindow) -> Sampled:
    """The closest approach of *red* to *blue* in *window*, and their relative speed at it, km/s."""

    def separation(t: float) -> float:
        return float(np.linalg.norm(blue(t)[:3] - red(t)[:3]))

    approach = closest_approach(separation, window.span_s, step_s=window.step_s)
    speed = float(np.linalg.norm(red(approach.tca_s)[3:] - blue(approach.tca_s)[3:]))
    return Sampled(approach, speed)


def rk45_sgp4_gap_km(
    red_tle: str, blue_tle: str, window: SeparationWindow, hypotheses: Sequence[ManoeuvreHypothesis] = (),
) -> float | None:
    """How far apart RK45 and SGP4 place these two orbits over *window*, red's gap plus blue's, km (SPC-120).

    Each object's RK45 arc is integrated as a separation series integrates it and compared with SGP4 at every
    instant of the helper's grid; the largest difference is that object's gap. Blue is integrated from its SGP4
    state at the window start, at its own B*. Red is integrated as each of *hypotheses* (the sampled rows') has
    it before its burn: from the pre-manoeuvre state at the burn, at ``bstar_post``, back and forward, so a burn
    days before the window is measured over the days it is integrated; red's gap is the largest of them. With no
    hypotheses, red is integrated from its SGP4 state at the window start, as blue is. By the triangle
    inequality the sum bounds how far the two propagators' separations, and so their minima, can differ on the
    grid: a computed row (SGP4, SPC-120) and a sampled row (RK45) that differ by less than this differ by the
    propagators, not the burn. None when any arc cannot be had or integrated across the window.
    """
    grid = _grid(window.span_s, window.step_s)
    red_arcs: list[Callable[[], _Trajectory | None]] = [
        functools.partial(_unburnt_arc, h, 0.0, window.span_s, (h.epoch_utc - window.start_utc).total_seconds())
        for h in hypotheses
    ] or [functools.partial(_elset_arc, red_tle, window)]
    reds = [_propagator_gap_km(red_tle, arc, window, grid) for arc in red_arcs]
    blue = _propagator_gap_km(blue_tle, functools.partial(_elset_arc, blue_tle, window), window, grid)
    if blue is None or None in reds:
        return None
    return max(cast("list[float]", reds)) + blue


def _elset_arc(tle: str, window: SeparationWindow) -> _Trajectory | None:
    """This engine's RK45 arc of *tle* over *window*, from its SGP4 state at the window start; None if none."""
    start = elset_state(tle, window.start_utc)
    return None if start is None else _dense_arc(start.state_eci_km, 0.0, window.span_s, start.bstar)


def _propagator_gap_km(
    tle: str, arc_of: Callable[[], _Trajectory | None], window: SeparationWindow, grid: list[float],
) -> float | None:
    """The largest distance between the RK45 arc *arc_of* gives and SGP4 for one element set over *grid*, km."""
    from spectre.astro.propagator import TLE_ERRORS, TLEOrbit

    try:
        arc = arc_of()
        if arc is None:
            return None
        orbit = TLEOrbit(tle)
        return max(
            float(np.linalg.norm(arc(t)[:3] - orbit.propagate(window.start_utc + timedelta(seconds=t)).r))
            for t in grid
        )
    except ReenteredError:
        return None
    except TLE_ERRORS:   # a failed SGP4 instant, or a failed solve (numpy's LinAlgError is a ValueError)
        return None


# ── A separation series carried from turn to turn (SPC-140) ──────────────────

class _RedArc(NamedTuple):
    """One sample's red over a window: the B* it starts on and its burns in time order, made or still to come."""

    arc: _Trajectory
    bstar: float
    burns: tuple[RedBurn, ...]

    def bstar_at(self, t_s: float) -> float:
        """The B* red flies at *t_s*: after its latest burn by then, as the spliced arc is from the burn on."""
        made = [burn.bstar_after for burn in self.burns if burn.at_s <= t_s]
        return made[-1] if made else self.bstar

    def pending(self, t_s: float) -> tuple[RedBurn, ...]:
        """The burns after *t_s*, timed from it: what the turn starting at *t_s* still has to make."""
        return tuple(burn._replace(at_s=burn.at_s - t_s) for burn in self.burns if burn.at_s > t_s)


class _Keeper:
    """Collects each sample's red state and B* at the turn boundaries, and its smallest separation from each blue
    from the window start to the first boundary, for a game tree's next turn (SPC-140)."""

    def __init__(self, at_s: Sequence[float], samples: int, blues: int, window: SeparationWindow) -> None:
        self.at_s = tuple(float(t) for t in at_s)
        self.red = np.full((samples, len(self.at_s), 6), np.nan)
        self.bstar = np.full(samples, np.nan)
        self.slice_min_km = np.full((blues, samples), np.nan)
        self.pending: list[tuple[RedBurn, ...]] = [()] * samples
        self.blue_shift_s = np.zeros(samples)
        self.slice_window = SeparationWindow(window.start_utc, self.at_s[0], window.step_s)

    def keep(self, k: int, blues: Sequence[_Trajectory | str], red: _RedArc) -> None:
        self.red[k] = [red.arc(t) for t in self.at_s]
        self.bstar[k] = red.bstar_at(self.at_s[0])
        self.pending[k] = red.pending(self.at_s[0])
        for b, blue in enumerate(blues):
            found = _search_or_fail(red.arc, blue, self.slice_window)
            if isinstance(found, Sampled):
                self.slice_min_km[b, k] = found.approach.miss_km

    def hearing(self, k: int, blues: Sequence[_Trajectory | str], shift_s: float) -> Callable[[_RedArc], None]:
        """What sample *k*'s red is handed to: kept against *blues*, each moved by its draw, whose shift, s, is kept
        for the next turn (SPC-202)."""
        self.blue_shift_s[k] = shift_s
        return functools.partial(self.keep, k, blues)

    @property
    def kept(self) -> Kept:
        return Kept(self.at_s, self.red, self.bstar, self.slice_min_km, tuple(self.pending), self.blue_shift_s)


def _hearing(
    keeper: _Keeper | None, k: int, blues: Sequence[_Trajectory | str], shift_s: float,
) -> Callable[[_RedArc], None] | None:
    """Sample *k*'s keep, or None when nothing is kept."""
    return None if keeper is None else keeper.hearing(k, blues, shift_s)


class TurnBurn(NamedTuple):
    """Red's burn again in a later turn of a game tree (SPC-140), *at_s* after the turn's start.

    The hypothesis gives the nominal delta-V and its RIC direction, the spreads, the B* after the burn and the seed;
    its own epoch and pre-manoeuvre state are not read, since each sample burns from where its last turn left it.
    *then* holds a transfer's later burns (SPC-187), each with its own hypothesis and seed and its time after this
    turn's start, made in time order after this one; one past the turn's end is kept for the turn after to make.
    """

    hypothesis: ManoeuvreHypothesis
    at_s: float
    then: tuple[tuple[ManoeuvreHypothesis, float], ...] = ()


class ContinuedRed(NamedTuple):
    """Red where each sample's last turn left it: its states (samples, 6) and B*s at the window start, the burn it
    makes again in this turn, if any, and per sample the burns its last turn drew past its end, timed from this
    turn's start (Kept.pending), empty for none."""

    states: np.ndarray
    bstars: np.ndarray
    burn: TurnBurn | None = None
    pending: tuple[tuple[RedBurn, ...], ...] = ()
    # Per sample, the seconds each blue is read on along its own orbit: the sample's element-set draw for blue, carried
    # from the turn that drew it (SPC-202). None for none.
    blue_shift_s: np.ndarray | None = None


class ContinuedSeries(NamedTuple):
    """One series per blue, over the same samples in the same order, and what was kept at the next boundary."""

    series: tuple[SeparationSeries, ...]
    kept: Kept | None


def _nominal_draw(hypothesis: ManoeuvreHypothesis) -> np.ndarray:
    """The hypothesis's burn as stated, undispersed, as a sample row: its RIC delta-V, no timing or B* offset."""
    parts = np.array([hypothesis.delta_v_radial, hypothesis.delta_v_in_track, hypothesis.delta_v_cross_track])
    norm = float(np.linalg.norm(parts))
    unit = parts / norm if norm >= _ZERO_DV_KM_S else np.array([0.0, 1.0, 0.0])
    return np.array([*(hypothesis.delta_v_magnitude_km_s * unit), 0.0, 0.0])


def _drawn_burns(burn: TurnBurn | None, draw: np.ndarray | None,
                 later: Sequence[np.ndarray] = ()) -> tuple[RedBurn, ...]:
    """This turn's burn as *draw* says, at its time plus the draw's timing offset, clamped to the window start:
    before it, red was in the turn before, whose figures are already taken. *later* holds the sample's draw of each
    of the transfer's later burns (SPC-187), each made no earlier than the first, as a transfer is in turn 1."""
    if burn is None or draw is None:
        return ()
    at_s = max(burn.at_s + float(draw[3]), 0.0)
    first = RedBurn(at_s, draw[:3].copy(), burn.hypothesis.bstar_post + float(draw[4]))
    return (first, *(
        RedBurn(max(t_s + float(d[3]), at_s), d[:3].copy(), h.bstar_post + float(d[4]))
        for (h, t_s), d in zip(burn.then, later, strict=True)
    ))


def nominal_turn_burns(burn: TurnBurn | None) -> tuple[RedBurn, ...]:
    """A turn's burns as stated, undispersed, timed from the turn's start: what our burn is sized against (SPC-187)."""
    if burn is None:
        return ()
    return tuple(
        RedBurn(t_s, _nominal_draw(h)[:3], h.bstar_post) for h, t_s in ((burn.hypothesis, burn.at_s), *burn.then)
    )


def _continued_red(
    state: np.ndarray, bstar: float, burns: Sequence[RedBurn], span_s: float, *, start_s: float = 0.0,
) -> _RedArc | None:
    """Red from *state* at *start_s* (the window start unless given) to *span_s*, making each of *burns* that falls
    before *span_s*, in time order, in the RIC frame of its state then. None when a solve fails; ReenteredError
    below the floor."""
    ordered = tuple(sorted(burns, key=lambda burn: burn.at_s))
    arc: _Trajectory | None = None
    t_s, at, flying = start_s, state, bstar
    for burn in (b for b in ordered if b.at_s < span_s):
        leg = _dense_arc(at, t_s, burn.at_s, flying)
        if leg is None:
            return None
        arc = leg if arc is None else _spliced(arc, leg, t_s)
        at = leg(burn.at_s).copy()
        at[3:] += _ric_to_eci_rotation(at[:3], at[3:]) @ burn.delta_v_ric_km_s
        t_s, flying = burn.at_s, burn.bstar_after
    last = _dense_arc(at, t_s, span_s, flying)
    if last is None:
        return None
    return _RedArc(last if arc is None else _spliced(arc, last, t_s), bstar, ordered)


def nominal_continued_arc(
    state: np.ndarray, bstar: float, burn: TurnBurn | None, span_s: float, pending: Sequence[RedBurn] = (),
) -> tuple[_Trajectory, float] | None:
    """Red from *state* with the burn as stated, undispersed, and the B* it ends on; what our burn is sized
    against in a later turn (SPC-140), as nominal_red_arc is in the first. *pending* holds a transfer's burns the
    turns before left to this one, as stated (SPC-187). None when a solve fails."""
    try:
        red = _continued_red(state, bstar, (*pending, *nominal_turn_burns(burn)), span_s)
    except (ReenteredError, ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return None
    return None if red is None else (red.arc, red.bstar_at(span_s))


def _continue_sample(
    start: tuple[np.ndarray, float], burns: Sequence[RedBurn], window: SeparationWindow,
    blues: Sequence[_Trajectory], keep: Callable[[_RedArc], None] | None,
) -> tuple[Sampled | str, ...]:
    """One sample carried on from its state and B*, making *burns*, and searched against each blue, or why it has
    no approach."""
    state, bstar = start
    try:
        red = _continued_red(state, bstar, burns, window.span_s)
    except ReenteredError:
        return (_REENTERED,) * len(blues)
    except (ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return (_FAILED,) * len(blues)
    if red is None:
        return (_FAILED,) * len(blues)
    if keep is not None:
        keep(red)
    return tuple(_search_or_fail(red.arc, blue, window) for blue in blues)


def continue_series(
    red: ContinuedRed, blues: Sequence[_Trajectory], window: SeparationWindow, *, tick: Tick | None = None,
    keep_at_s: Sequence[float] = (),
) -> ContinuedSeries:
    """Each sample carried on from where its last turn left it, searched against each of *blues* (SPC-140).

    Sample k starts from ``red.states[k]`` at the window start, flying ``red.bstars[k]``. With a burn, it burns again with
    the spread drawn afresh, draw k for sample k, in the RIC frame of its own state at its burn, and flies the
    hypothesis's B* after it plus its draw's offset, then any later burns of its transfer (SPC-187), each drawn from
    its own seed. A burn its last turn drew past that turn's end (``red.pending``) is made first, when it falls. Each
    blue is a trajectory from the window start, as the tree carried it. Sample order is kept, so turn k's sample is
    turn 1's. *tick* and *keep_at_s* serve as in run_separation_series. With ``red.blue_shift_s`` (SPC-202), sample k searches each blue read that many seconds on
    along its own orbit, as the turn that drew the shift did, so each blue arc must run that far past each end
    (rk45_arc's *pad_s*). Raises ValueError for a window the helper would refuse.
    """
    _check_span(window)
    started = time.monotonic()
    n, burn = len(red.states), red.burn
    draws = None if burn is None else generate_samples(replace(burn.hypothesis, n_samples=n))
    later = [] if burn is None else [generate_samples(replace(h, n_samples=n)) for h, _ in burn.then]
    keeper = _Keeper(keep_at_s, n, len(blues), window) if keep_at_s else None
    outcomes: list[tuple[Sampled | str, ...]] = []
    shifts = np.zeros(n) if red.blue_shift_s is None else np.asarray(red.blue_shift_s, dtype=float)
    for k in range(n):
        moved = [_shifted(blue, float(shifts[k])) for blue in blues]
        keep = _hearing(keeper, k, moved, float(shifts[k]))
        drawn = _drawn_burns(burn, None if draws is None else draws[k], [d[k] for d in later])
        burns = (*(red.pending[k] if red.pending else ()), *drawn)
        outcomes.append(_continue_sample((red.states[k], float(red.bstars[k])), burns, window, moved, keep))
        if tick is not None:
            tick(k + 1, n)
    ran = _Ran(0 if burn is None else burn.hypothesis.random_seed, started, keeper)
    series = tuple(
        _series_of(window, [outcome[b] for outcome in outcomes], ran, integration_s=(n + len(blues)) * window.span_s)
        for b in range(len(blues))
    )
    return ContinuedSeries(series, None if keeper is None else keeper.kept)
