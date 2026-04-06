"""Historical Photometry Analysis for space object characterisation.

Detects anomalous brightness changes that may correlate with manoeuvres,
attitude changes, or physical alterations (e.g. panel deployment/loss).

Pipeline
--------
1. Parse CSV observations into ``PhotometryObservation`` list.
2. Apply geometric corrections (range normalisation, Rozenberg airmass,
   lunar quality flagging) → ``CorrectedObservation`` list.
3. Fit a quadratic solar-phase-angle baseline using iterative sigma-clipping
   → ``PhotometryBaseline``.
4. Compute per-epoch residuals; run a two-sample Student's t-test on a
   recent window vs the baseline window → ``PhotometryChangeAssessment``.
5. Correlate any detected brightness change with manoeuvres from the PoL
   engine (within ±48 h).

Typical use::

    obs  = parse_photometry_csv(csv_text)
    corr = apply_geometric_corrections(obs)
    base = fit_baseline(corr)
    result = assess_photometry(obs, manoeuvres=pol.manoeuvres)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Sequence

logger = logging.getLogger(__name__)

# Earth radius (km) — used only for geometry checks
_R_EARTH_KM = 6371.0


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PhotometryObservation:
    """A single photometric measurement of a space object."""

    epoch_utc:          datetime
    apparent_magnitude: float
    uncertainty:        float            # 1-σ magnitude uncertainty
    filter_band:        str              # e.g. "V", "R", "unfiltered"
    observer_lat_deg:   float            # degrees north
    observer_lon_deg:   float            # degrees east
    observer_alt_m:     float            # metres above sea level
    range_km:           float            # observer–object distance
    solar_phase_angle_deg: float         # Sun–object–observer angle
    elevation_deg:      float            # object elevation above horizon
    lunar_phase_fraction: float          # 0 = new, 1 = full
    lunar_separation_deg: float          # angular separation object–Moon


@dataclass
class CorrectedObservation:
    """Observation after geometric/atmospheric corrections."""

    epoch_utc:           datetime
    reduced_magnitude:   float           # range-normalised, airmass-corrected
    solar_phase_angle_deg: float
    aspect_angle_deg:    float | None    # if available
    filter_band:         str
    quality_flag:        str             # "ok" | "lunar" | "low_elevation" | "reject"
    original:            PhotometryObservation


@dataclass
class PhotometryBaseline:
    """Fitted phase-angle baseline over a quiet period."""

    # Quadratic: mag = a0 + a1*phase + a2*phase**2
    a0: float
    a1: float
    a2: float
    covariance: list[list[float]]        # 3×3 covariance matrix (rows as lists)
    residual_std: float                  # robust σ of residuals (post sigma-clip)
    n_used: int
    n_outliers: int
    phase_coverage_deg: tuple[float, float]   # (min, max) phase angle in baseline
    epoch_range: tuple[datetime, datetime]


@dataclass
class PhotometryChangeAssessment:
    """Result of the brightness-change detection test."""

    # Statistics
    baseline_mean: float
    baseline_std:  float
    recent_mean:   float
    recent_std:    float
    mean_residual: float                 # recent_mean − baseline_mean
    t_statistic:   float
    p_value:       float

    # Significance
    significant_at_95: bool
    significant_at_99: bool

    # Interpretation
    magnitude_change:         float      # Δmag (positive = fainter)
    change_direction:         str        # "brightening" | "fading" | "none"
    estimated_change_epoch:   datetime | None
    confidence:               float      # [0, 1] — composite
    confounding_factors:      list[str]
    correlated_manoeuvre_epochs: list[datetime]

    def summary(self) -> str:
        if not self.significant_at_95:
            return (
                f"No significant brightness change detected "
                f"(|Δmag|={abs(self.magnitude_change):.3f}, p={self.p_value:.3f})."
            )
        sig = "99%" if self.significant_at_99 else "95%"
        mn  = self.correlated_manoeuvre_epochs
        mn_str = (
            f" Correlated with {len(mn)} manoeuvre(s)."
            if mn else " No correlated manoeuvres detected."
        )
        return (
            f"Significant {self.change_direction} detected at {sig} confidence "
            f"(Δmag={self.magnitude_change:+.3f}, p={self.p_value:.4f}).{mn_str}"
        )


# ── Geometric corrections ─────────────────────────────────────────────────────

def _rozenberg_airmass(elevation_deg: float) -> float:
    """Rozenberg (1966) airmass formula.

    More accurate than sec(z) below 10° elevation.
    """
    if elevation_deg <= 0.0:
        return 40.0   # clip at horizon
    el_rad = math.radians(elevation_deg)
    return 1.0 / (math.sin(el_rad) + 0.025 * math.exp(-11.0 * math.sin(el_rad)))


def apply_geometric_corrections(
    observations: Sequence[PhotometryObservation],
    extinction_coeff: float = 0.12,   # mag/airmass — typical V-band
    reference_range_km: float = 1000.0,
) -> list[CorrectedObservation]:
    """Apply range normalisation and atmospheric extinction correction.

    Reduced magnitude = apparent_mag
                       - 5 * log10(range_km / reference_range_km)
                       + extinction_coeff * (1 - airmass)   [relative]

    Quality flags
    -------------
    "lunar"        — lunar_separation < 20° or lunar_phase > 0.8
    "low_elevation"— elevation < 15°
    "reject"       — both lunar and low_elevation
    "ok"           — nominal
    """
    corrected: list[CorrectedObservation] = []

    for obs in observations:
        # Range normalisation: Δmag = 5 log10(range / ref)
        range_correction = 5.0 * math.log10(max(obs.range_km, 1.0) / reference_range_km)

        # Airmass correction (relative to zenith, not absolute)
        airmass = _rozenberg_airmass(obs.elevation_deg)
        atmo_correction = extinction_coeff * (airmass - 1.0)

        reduced = obs.apparent_magnitude - range_correction - atmo_correction

        # Quality flag
        lunar_bad = obs.lunar_phase_fraction > 0.80 or obs.lunar_separation_deg < 20.0
        elev_bad  = obs.elevation_deg < 15.0
        if lunar_bad and elev_bad:
            flag = "reject"
        elif lunar_bad:
            flag = "lunar"
        elif elev_bad:
            flag = "low_elevation"
        else:
            flag = "ok"

        corrected.append(CorrectedObservation(
            epoch_utc=obs.epoch_utc,
            reduced_magnitude=round(reduced, 4),
            solar_phase_angle_deg=obs.solar_phase_angle_deg,
            aspect_angle_deg=None,
            filter_band=obs.filter_band,
            quality_flag=flag,
            original=obs,
        ))

    return corrected


# ── Baseline fitting ──────────────────────────────────────────────────────────

def _eval_quadratic(coeffs: tuple[float, float, float], phase: float) -> float:
    a0, a1, a2 = coeffs
    return a0 + a1 * phase + a2 * phase * phase


def _fit_least_squares_quadratic(
    phases: list[float],
    mags: list[float],
) -> tuple[float, float, float, list[list[float]]]:
    """Fit mag = a0 + a1*x + a2*x^2 via normal equations (numpy-free).

    Returns (a0, a1, a2, cov3x3).  Uses standard normal equations X^T X b = X^T y.
    """
    n = len(phases)
    if n < 3:
        raise ValueError(f"Need at least 3 observations for quadratic fit, got {n}")

    # Build X^T X and X^T y
    sx0 = float(n)
    sx1 = sum(x for x in phases)
    sx2 = sum(x * x for x in phases)
    sx3 = sum(x * x * x for x in phases)
    sx4 = sum(x * x * x * x for x in phases)
    sy0 = sum(y for y in mags)
    sy1 = sum(x * y for x, y in zip(phases, mags))
    sy2 = sum(x * x * y for x, y in zip(phases, mags))

    # 3×3 normal matrix
    A = [
        [sx0, sx1, sx2],
        [sx1, sx2, sx3],
        [sx2, sx3, sx4],
    ]
    b_vec = [sy0, sy1, sy2]

    # Gauss elimination with partial pivoting
    def _gauss_solve(mat: list[list[float]], rhs: list[float]) -> list[float]:
        n_ = len(rhs)
        m = [row[:] + [rhs[i]] for i, row in enumerate(mat)]  # augmented
        for col in range(n_):
            # Partial pivot
            max_row = max(range(col, n_), key=lambda r: abs(m[r][col]))
            m[col], m[max_row] = m[max_row], m[col]
            if abs(m[col][col]) < 1e-15:
                raise ValueError("Singular normal matrix — degenerate phase coverage")
            for row in range(col + 1, n_):
                f = m[row][col] / m[col][col]
                for j in range(col, n_ + 1):
                    m[row][j] -= f * m[col][j]
        # Back substitution
        x = [0.0] * n_
        for i in range(n_ - 1, -1, -1):
            x[i] = m[i][n_] / m[i][i]
            for j in range(i + 1, n_):
                x[i] -= m[i][j] * x[j] / m[i][i]
        return x

    coeffs = _gauss_solve(A, b_vec)

    # Covariance: residual variance × (X^T X)^{-1}  (approximated from diagonal)
    residuals = [mags[i] - _eval_quadratic(tuple(coeffs), phases[i]) for i in range(n)]  # type: ignore[arg-type]
    res_var   = sum(r * r for r in residuals) / max(n - 3, 1)
    # Simplified diagonal covariance (off-diagonal entries zeroed)
    cov = [[res_var / max(A[i][i], 1e-12) if i == j else 0.0 for j in range(3)] for i in range(3)]

    return coeffs[0], coeffs[1], coeffs[2], cov


def fit_baseline(
    corrected: Sequence[CorrectedObservation],
    sigma_clip_threshold: float = 3.0,
    max_iterations: int = 5,
) -> PhotometryBaseline:
    """Fit a quadratic phase-function baseline with iterative sigma-clipping.

    Only observations flagged "ok" or "lunar" (mild contamination) are used.
    Returns the best-fit ``PhotometryBaseline``.
    """
    usable = [c for c in corrected if c.quality_flag in ("ok", "lunar")]
    if len(usable) < 5:
        raise ValueError(
            f"Insufficient good observations for baseline fit ({len(usable)} < 5)"
        )

    # Sort by epoch
    usable.sort(key=lambda c: c.epoch_utc)
    phases = [c.solar_phase_angle_deg for c in usable]
    mags   = [c.reduced_magnitude for c in usable]
    mask   = [True] * len(usable)
    n_outliers = 0

    a0, a1, a2, cov = _fit_least_squares_quadratic(phases, mags)

    for _ in range(max_iterations):
        active_phases = [phases[i] for i in range(len(usable)) if mask[i]]
        active_mags   = [mags[i]   for i in range(len(usable)) if mask[i]]
        if len(active_phases) < 5:
            break
        try:
            a0, a1, a2, cov = _fit_least_squares_quadratic(active_phases, active_mags)
        except ValueError:
            break

        residuals = [
            mags[i] - _eval_quadratic((a0, a1, a2), phases[i])
            for i in range(len(usable)) if mask[i]
        ]
        mean_r = sum(residuals) / len(residuals)
        std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in residuals) / max(len(residuals) - 1, 1))
        if std_r < 1e-12:
            break

        new_mask = mask[:]
        changed  = False
        ri = 0
        for i in range(len(usable)):
            if not mask[i]:
                continue
            if abs(residuals[ri] - mean_r) > sigma_clip_threshold * std_r:
                new_mask[i] = False
                n_outliers  += 1
                changed      = True
            ri += 1
        if not changed:
            break
        mask = new_mask

    # Final residual std
    final_phases = [phases[i] for i in range(len(usable)) if mask[i]]
    final_mags   = [mags[i]   for i in range(len(usable)) if mask[i]]
    final_resids = [
        final_mags[i] - _eval_quadratic((a0, a1, a2), final_phases[i])
        for i in range(len(final_phases))
    ]
    res_std = math.sqrt(
        sum(r * r for r in final_resids) / max(len(final_resids) - 1, 1)
    ) if len(final_resids) > 1 else 0.0

    return PhotometryBaseline(
        a0=round(a0, 6),
        a1=round(a1, 6),
        a2=round(a2, 6),
        covariance=cov,
        residual_std=round(res_std, 5),
        n_used=len(final_phases),
        n_outliers=n_outliers,
        phase_coverage_deg=(min(phases), max(phases)),
        epoch_range=(usable[0].epoch_utc, usable[-1].epoch_utc),
    )


# ── Change detection ──────────────────────────────────────────────────────────

def _t_test_two_sample(
    group_a: list[float],
    group_b: list[float],
) -> tuple[float, float]:
    """Welch's two-sample t-test.

    Returns (t_statistic, p_value_two_tailed).
    Uses an approximation of the t CDF via the regularised incomplete Beta function
    implemented with the continued fraction expansion (Lentz method).
    """
    na, nb = len(group_a), len(group_b)
    if na < 2 or nb < 2:
        return 0.0, 1.0

    mean_a = sum(group_a) / na
    mean_b = sum(group_b) / nb
    var_a  = sum((x - mean_a) ** 2 for x in group_a) / (na - 1)
    var_b  = sum((x - mean_b) ** 2 for x in group_b) / (nb - 1)

    se = math.sqrt(var_a / na + var_b / nb)
    if se < 1e-15:
        return 0.0, 1.0

    t = (mean_a - mean_b) / se

    # Welch–Satterthwaite degrees of freedom
    num   = (var_a / na + var_b / nb) ** 2
    denom = (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
    df    = num / denom if denom > 1e-15 else 1.0

    # p-value via regularised incomplete Beta (I_x(a,b), x = df/(df+t^2))
    x   = df / (df + t * t)
    p   = _regularised_incomplete_beta(x, df / 2.0, 0.5)
    # two-tailed
    return t, min(max(p, 0.0), 1.0)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete Beta (Numerical Recipes algorithm).

    Evaluates the CF that satisfies:
        I_x(a,b) = x^a * (1-x)^b / (a * B(a,b)) * betacf(a, b, x)

    when x < (a+1)/(a+b+2).
    """
    MAXIT = 200
    FPMIN = 1.0e-30
    EPS   = 3.0e-7
    qab   = a + b
    qap   = a + 1.0
    qam   = a - 1.0
    c     = 1.0
    d     = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2  = 2 * m
        aa  = m * (b - m) * x / ((qam + m2) * (a + m2))
        d   = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c   = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d   = 1.0 / d
        h  *= d * c
        aa  = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d   = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c   = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d   = 1.0 / d
        delta = d * c
        h  *= delta
        if abs(delta - 1.0) < EPS:
            return h
    return h


def _regularised_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularised incomplete Beta I_x(a,b).

    Used to compute the two-tailed p-value for Welch's t-test.
    Accurate to ~6 decimal places for the range needed here.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt    = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))

    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    else:
        return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def detect_change(
    corrected: Sequence[CorrectedObservation],
    baseline: PhotometryBaseline,
    recent_window_days: float = 30.0,
    baseline_window_days: float = 90.0,
) -> tuple[float, float, float, float, float, float]:
    """Compare recent residuals against baseline residuals.

    Returns
    -------
    (baseline_mean, baseline_std, recent_mean, recent_std, t_stat, p_value)
    """
    now_epoch = max((c.epoch_utc for c in corrected), default=datetime.now(UTC))
    recent_cutoff   = now_epoch - timedelta(days=recent_window_days)
    baseline_cutoff = now_epoch - timedelta(days=recent_window_days + baseline_window_days)

    baseline_residuals: list[float] = []
    recent_residuals:   list[float] = []

    for c in corrected:
        if c.quality_flag in ("reject",):
            continue
        predicted = _eval_quadratic(
            (baseline.a0, baseline.a1, baseline.a2),
            c.solar_phase_angle_deg,
        )
        residual = c.reduced_magnitude - predicted
        if baseline_cutoff <= c.epoch_utc < recent_cutoff:
            baseline_residuals.append(residual)
        elif c.epoch_utc >= recent_cutoff:
            recent_residuals.append(residual)

    if not baseline_residuals or not recent_residuals:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 1.0

    bm = sum(baseline_residuals) / len(baseline_residuals)
    bs = math.sqrt(sum((r - bm) ** 2 for r in baseline_residuals) / max(len(baseline_residuals) - 1, 1))
    rm = sum(recent_residuals) / len(recent_residuals)
    rs = math.sqrt(sum((r - rm) ** 2 for r in recent_residuals) / max(len(recent_residuals) - 1, 1))

    t, p = _t_test_two_sample(baseline_residuals, recent_residuals)
    return bm, bs, rm, rs, t, p


def _estimate_change_epoch(
    corrected: Sequence[CorrectedObservation],
    baseline: PhotometryBaseline,
    threshold_sigma: float = 2.0,
) -> datetime | None:
    """Scan forward in time; return first epoch where residual exceeds threshold."""
    obs_sorted = sorted(corrected, key=lambda c: c.epoch_utc)
    for c in obs_sorted:
        if c.quality_flag == "reject":
            continue
        predicted = _eval_quadratic(
            (baseline.a0, baseline.a1, baseline.a2),
            c.solar_phase_angle_deg,
        )
        if abs(c.reduced_magnitude - predicted) > threshold_sigma * baseline.residual_std:
            return c.epoch_utc
    return None


def correlate_with_manoeuvres(
    change_epoch: datetime | None,
    manoeuvres: list,        # list[Manoeuvre]
    window_hours: float = 48.0,
) -> list[datetime]:
    """Return epochs of manoeuvres within ±window_hours of change_epoch."""
    if change_epoch is None:
        return []
    window = timedelta(hours=window_hours)
    return [
        m.epoch for m in manoeuvres
        if abs((m.epoch - change_epoch).total_seconds()) <= window.total_seconds()
    ]


# ── Top-level pipeline ────────────────────────────────────────────────────────

def assess_photometry(
    observations: Sequence[PhotometryObservation],
    manoeuvres: list | None = None,
    extinction_coeff: float = 0.12,
    reference_range_km: float = 1000.0,
    sigma_clip: float = 3.0,
    recent_window_days: float = 30.0,
    baseline_window_days: float = 90.0,
) -> PhotometryChangeAssessment:
    """End-to-end photometry analysis pipeline.

    Parameters
    ----------
    observations:
        Raw photometric observations (sorted or unsorted).
    manoeuvres:
        PoL-detected manoeuvres for correlation (optional).
    extinction_coeff:
        V-band atmospheric extinction coefficient (mag/airmass).
    reference_range_km:
        Range at which reduced magnitude is normalised.
    sigma_clip:
        Sigma-clipping threshold for baseline fitting.
    recent_window_days:
        Length of the "recent" window tested against the baseline.
    baseline_window_days:
        Length of the historical baseline window.

    Returns
    -------
    PhotometryChangeAssessment
    """
    if not observations:
        raise ValueError("No observations provided")

    manoeuvres = manoeuvres or []

    # Step 1: geometric corrections
    corrected = apply_geometric_corrections(
        observations,
        extinction_coeff=extinction_coeff,
        reference_range_km=reference_range_km,
    )

    # Step 2: baseline fit
    try:
        baseline = fit_baseline(corrected, sigma_clip_threshold=sigma_clip)
    except ValueError as exc:
        logger.warning("Baseline fitting failed: %s", exc)
        # Return a degenerate assessment
        dummy_epoch = observations[0].epoch_utc
        return PhotometryChangeAssessment(
            baseline_mean=0.0, baseline_std=0.0,
            recent_mean=0.0, recent_std=0.0,
            mean_residual=0.0, t_statistic=0.0, p_value=1.0,
            significant_at_95=False, significant_at_99=False,
            magnitude_change=0.0, change_direction="none",
            estimated_change_epoch=None, confidence=0.0,
            confounding_factors=[str(exc)],
            correlated_manoeuvre_epochs=[],
        )

    # Step 3: change detection
    bm, bs, rm, rs, t, p = detect_change(
        corrected, baseline,
        recent_window_days=recent_window_days,
        baseline_window_days=baseline_window_days,
    )

    delta_mag = rm - bm
    if abs(delta_mag) < 0.01:
        direction = "none"
    elif delta_mag > 0:
        direction = "fading"    # positive residual = object is fainter than model
    else:
        direction = "brightening"

    sig95 = p < 0.05
    sig99 = p < 0.01

    # Confounding factors
    confounders: list[str] = []
    n_reject  = sum(1 for c in corrected if c.quality_flag == "reject")
    n_lunar   = sum(1 for c in corrected if c.quality_flag == "lunar")
    if n_reject > 0.2 * len(corrected):
        confounders.append(f"{n_reject} observations rejected (poor geometry/lunar contamination)")
    if n_lunar > 0:
        confounders.append(f"{n_lunar} observations affected by lunar proximity")
    if baseline.residual_std > 0.3:
        confounders.append(f"High baseline scatter (σ={baseline.residual_std:.3f} mag) — variable phase coverage")

    # Confidence: composite based on p-value and sample sizes
    if sig99:
        confidence = 0.99
    elif sig95:
        confidence = 0.95
    else:
        confidence = max(0.0, 1.0 - p)

    # Change epoch estimation
    change_ep = _estimate_change_epoch(corrected, baseline) if sig95 else None

    # Manoeuvre correlation
    corr_mnvs = correlate_with_manoeuvres(change_ep, manoeuvres)

    return PhotometryChangeAssessment(
        baseline_mean=round(bm, 4),
        baseline_std=round(bs, 4),
        recent_mean=round(rm, 4),
        recent_std=round(rs, 4),
        mean_residual=round(delta_mag, 4),
        t_statistic=round(t, 4),
        p_value=round(p, 6),
        significant_at_95=sig95,
        significant_at_99=sig99,
        magnitude_change=round(delta_mag, 4),
        change_direction=direction,
        estimated_change_epoch=change_ep,
        confidence=round(confidence, 4),
        confounding_factors=confounders,
        correlated_manoeuvre_epochs=corr_mnvs,
    )


# ── CSV parser ────────────────────────────────────────────────────────────────

def parse_photometry_csv(
    csv_text: str,
    epoch_col: str = "epoch_utc",
    mag_col: str = "apparent_magnitude",
) -> list[PhotometryObservation]:
    """Parse a CSV string into a list of PhotometryObservation.

    Required columns
    ----------------
    ``epoch_utc``, ``apparent_magnitude``

    Optional columns (filled with sensible defaults when absent)
    -----------------------------------------------------------
    ``uncertainty``, ``filter_band``, ``observer_lat_deg``, ``observer_lon_deg``,
    ``observer_alt_m``, ``range_km``, ``solar_phase_angle_deg``, ``elevation_deg``,
    ``lunar_phase_fraction``, ``lunar_separation_deg``
    """
    import csv
    import io

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if reader.fieldnames is None:
        raise ValueError("Empty CSV or missing header row")

    cols = [c.strip().lower() for c in reader.fieldnames]

    def _get(row: dict, key: str, default: float) -> float:
        for k, v in row.items():
            if k.strip().lower() == key and v.strip():
                try:
                    return float(v.strip())
                except ValueError:
                    pass
        return default

    def _get_str(row: dict, key: str, default: str) -> str:
        for k, v in row.items():
            if k.strip().lower() == key and v.strip():
                return v.strip()
        return default

    observations: list[PhotometryObservation] = []
    for i, row in enumerate(reader):
        # Epoch
        epoch_str = _get_str(row, epoch_col.lower(), "")
        if not epoch_str:
            logger.warning("Row %d: missing epoch — skipping", i)
            continue
        # Try ISO 8601
        try:
            epoch_str_clean = epoch_str.rstrip("Z")
            epoch = datetime.fromisoformat(epoch_str_clean).replace(tzinfo=UTC)
        except ValueError:
            logger.warning("Row %d: unparseable epoch %r — skipping", i, epoch_str)
            continue

        mag = _get(row, mag_col.lower(), float("nan"))
        if math.isnan(mag):
            logger.warning("Row %d: missing magnitude — skipping", i)
            continue

        observations.append(PhotometryObservation(
            epoch_utc=epoch,
            apparent_magnitude=mag,
            uncertainty=_get(row, "uncertainty", 0.05),
            filter_band=_get_str(row, "filter_band", "unfiltered"),
            observer_lat_deg=_get(row, "observer_lat_deg", 0.0),
            observer_lon_deg=_get(row, "observer_lon_deg", 0.0),
            observer_alt_m=_get(row, "observer_alt_m", 0.0),
            range_km=_get(row, "range_km", 1000.0),
            solar_phase_angle_deg=_get(row, "solar_phase_angle_deg", 45.0),
            elevation_deg=_get(row, "elevation_deg", 45.0),
            lunar_phase_fraction=_get(row, "lunar_phase_fraction", 0.0),
            lunar_separation_deg=_get(row, "lunar_separation_deg", 90.0),
        ))

    return observations
