"""Monte Carlo simulation for manoeuvre outcome prediction.

Given a ManoeuvreHypothesis (baseline ΔV with uncertainty envelopes),
this module:

- Generates N perturbed ΔV samples (magnitude, pointing cone, timing, Bstar).
- Propagates each sample forward using a J2 + exponential drag numerical
  integrator (RK45 via scipy.integrate.solve_ivp).
- Aggregates the ensemble into a MonteCarloResult with regime probabilities,
  orbital element percentiles, and a 3-σ position cloud radius.

Design notes
------------
- Perturbations are applied in the Radial-In track-Cross track (RIC) frame and
  then rotated to ECI before integration — physically meaningful for pointing
  errors.
- Propagation uses J2 + simplified exponential atmosphere drag.  At 48 h, the
  MC uncertainty envelope from ΔV variation dominates over force-model error,
  so high-fidelity ephemeris is unnecessary.
- Concurrency: ThreadPoolExecutor (scipy/NumPy releases the GIL; no Windows
  spawn restrictions).
"""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp

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
        # Table 4: the most aggressive observed GEO repositioning, 90 degrees
        # in 3 days, cost about 170 m/s. 200 m/s sits just above it.
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
    position_3sigma_km: float      # 3-σ radius of position cloud at horizon
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
    bstar: float,
    bc_m2_kg: float,
) -> np.ndarray:
    """EOM: two-body + J2 + exponential drag (ECI frame, km, s).

    Parameters
    ----------
    state : (6,) — [x, y, z, vx, vy, vz]
    bstar : B* parameter from TLE (used for regime check only; drag uses bc)
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
    """Compute (sma_km, ecc, inc_deg, raan_deg, argp_deg, ta_deg) from state.

    Returns (sma_km, ecc, inc_deg) — sufficient for MC classification.
    """
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
        half = 3.0 * hypothesis.delta_v_magnitude_1sigma_km_s
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
    if span_s == 0.0:
        return state.copy()
    sol = solve_ivp(
        _j2_drag_ode,
        (0.0, span_s),
        state,
        method="RK45",
        rtol=1e-8,
        atol=1e-10,
        args=(bstar, _ballistic_coefficient_kg_m2(bstar)),
        dense_output=False,
    )
    return np.array(sol.y[:, -1]) if sol.success else None


# ── Convergence check ─────────────────────────────────────────────────────────

def check_convergence(
    sma_values: list[float],
    window_size: int = 200,
    tolerance_fraction: float = 0.01,
) -> bool:
    """Check if the running mean/std of SMA have stabilised."""
    if len(sma_values) < 2 * window_size:
        return False
    arr = np.array(sma_values)
    overall_mean = float(np.mean(arr))
    overall_std  = float(np.std(arr))
    recent_mean  = float(np.mean(arr[-window_size:]))
    recent_std   = float(np.std(arr[-window_size:]))

    mean_ok = abs(recent_mean - overall_mean) < tolerance_fraction * max(abs(overall_mean), 1e-6)
    std_ok  = (overall_std < 1e-9) or abs(recent_std - overall_std) < tolerance_fraction * overall_std
    return mean_ok and std_ok


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

    results: list[dict[str, Any]] = []
    n_diverged = 0

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
            out = future.result()
            if out is None:
                n_diverged += 1
            else:
                results.append(out)

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

    converged = check_convergence(sma_arr.tolist())

    return MonteCarloResult(
        hypothesis_satno=satno,
        prediction_horizon_hours=prediction_horizon_hours,
        n_samples_run=hypothesis.n_samples,
        n_samples_converged=n_converged,
        converged=converged,
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
    if norm == 0.0:
        return np.array([0.0, 1.0, 0.0]), "assumed in-track: no element breakdown"
    return ric / norm, (
        "split from the detection's element breakdown; "
        "sense of radial and cross-track parts not resolved"
    )
