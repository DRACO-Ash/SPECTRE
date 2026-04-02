"""Pattern of Life (PoL) analysis from historical TLE sequences.

Given a chronological list of TLEs for a single object this module:
  - Extracts mean orbital elements at each epoch (direct from SGP4 Satrec)
  - Computes subsatellite geographic longitude for GEO/GSO objects
  - Estimates ΔV between successive TLEs (propagation-difference method)
  - Detects and classifies manoeuvres (SK / plane-change / repositioning)
  - Corrects RAAN and argp changes for J2 secular drift
  - Tracks longitude drift phases (East / West / Stationary)
  - Computes statistical Pattern of Life bounds (μ ± 2σ)
  - Scores the object on an anomaly scale vs GEO-SK baseline
  - Estimates propellant budget and remaining operational life
  - Produces an operator-level intelligence assessment
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from sgp4.api import Satrec

from sipc.astro.constants import (
    J2_EARTH,
    MU_EARTH,
    R_EARTH,
    SIDEREAL_DAY,
    classify_orbit_regime,
)
from sipc.astro.propagator import TLEOrbit

# ── Physical constants ────────────────────────────────────────────────────────

_G0_KM_S2   = 9.80665e-3        # km/s² — standard gravity
_ISP_MONO   = 220.0             # s  — monopropellant hydrazine (conservative)
_ISP_BI     = 320.0             # s  — bipropellant (GEO-typical)
_EARTH_ROT  = 86400.0 / SIDEREAL_DAY  # rev/solar-day ≈ 1.002737

# ── Thresholds ────────────────────────────────────────────────────────────────

_DV_NOISE_FLOOR   = 0.002   # km/s — below this = TLE noise
_MAX_GAP_DAYS     = 15.0    # days — skip ΔV computation for large gaps
_DRIFT_STATIONARY = 0.05    # °/day — |drift| below this → "Stationary"
_DRIFT_SIGNIFICANT = 0.20   # °/day — above this → meaningful drift phase

_SK_DV_LIMIT = {"GEO": 0.050, "LEO": 0.020, "MEO": 0.030,
                "HEO": 0.050, "GTO": 0.100, "DEEP": 0.050}

# GEO normal-SK baseline (used for anomaly scoring)
_GEO_SK_BASELINE = dict(
    dv_mean_ms      = 8.0,   # m/s  — typical single SK ΔV
    interval_days   = 14.0,  # days — typical NS/EW SK cadence
    lon_range_deg   = 1.0,   # °    — typical controlled slot box
    max_drift_deg_d = 0.05,  # °/d  — tolerable drift in SK slot
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TLERecord:
    """Mean orbital elements extracted from one TLE epoch."""

    epoch: datetime
    tle: str

    sma_km:               float
    ecc:                  float
    inc_deg:              float
    raan_deg:             float
    argp_deg:             float
    mean_anomaly_deg:     float
    mean_motion_revday:   float
    bstar:                float
    alt_km:               float
    period_min:           float
    regime:               str

    # GEO-specific — None for non-GEO objects
    geo_longitude_deg:      float | None = None
    geo_drift_rate_deg_day: float | None = None

    # UDL provenance — populated when TLE was fetched via UDL API
    data_mode: str = ""
    source:    str = ""


@dataclass
class Manoeuvre:
    """A detected manoeuvre between two successive TLEs."""

    epoch:                      datetime
    gap_days:                   float
    delta_v_km_s:               float
    delta_alt_km:               float
    delta_inc_deg:              float
    delta_ecc:                  float
    delta_raan_corrected_deg:   float
    delta_argp_corrected_deg:   float
    delta_period_s:             float
    delta_drift_deg_day:        float | None   # change in longitude drift rate

    dominant_element:   str
    manoeuvre_type:     str
    sk_subtype:         str

    tle_before: TLERecord
    tle_after:  TLERecord


@dataclass
class DriftPhase:
    """A contiguous period of consistent longitude drift direction."""

    start_epoch:    datetime
    end_epoch:      datetime
    direction:      str       # "EAST" | "WEST" | "STATIONARY"
    rate_deg_day:   float     # mean drift rate (°/day, signed)
    start_lon:      float     # starting longitude (°)
    end_lon:        float     # ending longitude (°)
    distance_deg:   float     # total arc traversed (°, signed)
    duration_days:  float
    peak_rate:      float     # maximum |drift rate| in phase


@dataclass
class AnomalyScore:
    """Multi-component anomaly score vs GEO-SK baseline (0–100 each)."""

    dv_magnitude:   float   # how large are the burns?
    lon_coverage:   float   # how far does it roam?
    drift_rate:     float   # how fast does it drift?
    sk_regularity:  float   # how irregular are the events?
    budget_rate:    float   # annual ΔV vs GEO-SK norm?
    overall:        float   # weighted composite
    risk_level:     str     # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "MINIMAL"


@dataclass
class PropellantBudget:
    """Rough propellant budget estimate from cumulative ΔV."""

    assumed_isp_s:          float
    assumed_propellant_kg:  float
    total_dv_km_s:          float
    propellant_used_pct:    float   # % of assumed propellant mass
    annual_dv_km_s:         float
    remaining_life_years:   float | None
    budget_class:           str     # "Conservative" | "Normal" | "High" | "Very High"


@dataclass
class IntelAssessment:
    """Operator-level intelligence assessment."""

    mission_profile:        str
    behaviour_class:        str
    risk_level:             str
    operational_signature:  str
    anomaly_narrative:      str
    notable_periods:        list[str]
    predicted_lon_30d:      float | None
    predicted_lon_60d:      float | None
    predicted_lon_90d:      float | None
    current_drift_dir:      str
    current_drift_rate:     float | None


@dataclass
class PolStats:
    mean:       float
    std:        float
    p5:         float
    p95:        float
    low_2sigma: float
    high_2sigma:float
    n:          int


@dataclass
class PolAnalysis:
    """Full Pattern of Life analysis result."""

    satno:      int
    name:       str
    tle_count:  int
    span_days:  float
    regime:     str

    records:    list[TLERecord]
    manoeuvres: list[Manoeuvre]

    # Down-sampled time-series for charts
    chart_epochs:   list[str]
    chart_alts:     list[float]
    chart_incs:     list[float]
    chart_eccs:     list[float]
    chart_raans:    list[float]
    chart_periods:  list[float]

    # GEO longitude time series
    chart_longitudes:   list[float]
    chart_drift_rates:  list[float]

    # Manoeuvre chart data
    manoeuvre_epochs:   list[str]
    manoeuvre_dvs:      list[float]   # m/s
    manoeuvre_types:    list[str]
    manoeuvre_alts:     list[float]
    manoeuvre_drift_deltas: list[float]  # change in drift rate at each manoeuvre

    # Drift phases
    drift_phases: list[DriftPhase]

    # Statistics
    total_dv_km_s:  float
    dv_stats:       PolStats | None
    interval_stats: PolStats | None

    # Classification
    dominant_activity:  str
    is_station_keeping: bool
    sk_type:            str

    # Scoring / assessment
    anomaly_score:      AnomalyScore | None
    propellant_budget:  PropellantBudget | None
    intel_assessment:   IntelAssessment | None

    # Prediction
    next_manoeuvre_est:               str | None
    next_manoeuvre_uncertainty_days:  float | None

    # PoL status (backward compat)
    pol_status:             str
    pol_status_reason:      str
    dv_threshold_km_s:      float
    pol_high_dv:            float | None
    pol_high_interval:      float | None
    pol_low_interval:       float | None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_tle_epoch(line1: str) -> datetime:
    epoch_str = line1[18:32].strip()
    yy = int(epoch_str[:2])
    year = 2000 + yy if yy < 57 else 1900 + yy
    day_frac = float(epoch_str[2:])
    day = int(day_frac)
    frac = day_frac - day
    base = datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day - 1)
    return base + timedelta(seconds=frac * 86400.0)


def _epoch_to_jd(epoch: datetime) -> float:
    """Julian Date from a UTC datetime."""
    # J2000 = JD 2451545.0 = 2000-01-01 12:00:00 UTC
    j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    dt_days = (epoch - j2000).total_seconds() / 86400.0
    return 2451545.0 + dt_days


def _gst_deg(epoch: datetime) -> float:
    """Greenwich Apparent Sidereal Time (degrees) at *epoch*."""
    jd = _epoch_to_jd(epoch)
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0


def _satrec_to_record(tle: str) -> TLERecord:
    lines = [ln.strip() for ln in tle.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("Need at least 2 TLE lines")
    l1, l2 = lines[-2], lines[-1]
    sat = Satrec.twoline2rv(l1, l2)

    n_rad_min = sat.no_kozai          # rad/min
    n_rad_s   = n_rad_min / 60.0
    sma       = (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)
    period_min = 2.0 * math.pi / n_rad_min
    epoch      = _parse_tle_epoch(l1)
    ecc        = sat.ecco
    inc_deg    = math.degrees(sat.inclo)
    raan_deg   = math.degrees(sat.nodeo) % 360.0
    argp_deg   = math.degrees(sat.argpo) % 360.0
    ma_deg     = math.degrees(sat.mo)   % 360.0
    alt_km     = sma - R_EARTH
    regime     = classify_orbit_regime(sma, ecc)
    n_revday   = n_rad_min * 60 * 24 / (2 * math.pi)

    # GEO longitude — approximate, near-equatorial circular assumption
    geo_lon = None
    geo_drift = None
    if regime in ("GEO", "DEEP") or (abs(inc_deg) < 15.0 and alt_km > 30000.0):
        mean_lon_eci = (raan_deg + argp_deg + ma_deg) % 360.0
        gst          = _gst_deg(epoch)
        lon          = (mean_lon_eci - gst) % 360.0
        geo_lon      = lon - 360.0 if lon > 180.0 else lon
        # Drift rate: positive = east
        geo_drift = 360.0 * (n_revday - _EARTH_ROT)

    return TLERecord(
        epoch=epoch, tle=tle,
        sma_km=sma, ecc=ecc, inc_deg=inc_deg,
        raan_deg=raan_deg, argp_deg=argp_deg, mean_anomaly_deg=ma_deg,
        mean_motion_revday=n_revday, bstar=sat.bstar,
        alt_km=alt_km, period_min=period_min, regime=regime,
        geo_longitude_deg=geo_lon,
        geo_drift_rate_deg_day=geo_drift,
    )


def _j2_raan_rate(rec: TLERecord) -> float:
    """J2 RAAN drift rate (°/day)."""
    n  = (MU_EARTH / rec.sma_km ** 3) ** 0.5
    d  = (1.0 - rec.ecc ** 2) ** 2
    rate = -1.5 * n * J2_EARTH * (R_EARTH / rec.sma_km) ** 2 * math.cos(math.radians(rec.inc_deg)) / d
    return math.degrees(rate) * 86400.0


def _j2_argp_rate(rec: TLERecord) -> float:
    """J2 arg-perigee drift rate (°/day)."""
    n  = (MU_EARTH / rec.sma_km ** 3) ** 0.5
    d  = (1.0 - rec.ecc ** 2) ** 2
    rate = 1.5 * n * J2_EARTH * (R_EARTH / rec.sma_km) ** 2 * (2.5 * math.sin(math.radians(rec.inc_deg)) ** 2 - 2.0) / d
    return math.degrees(rate) * 86400.0


def _angle_diff(a: float, b: float) -> float:
    return (b - a + 180.0) % 360.0 - 180.0


def _estimate_dv(r_prev: TLERecord, r_cur: TLERecord) -> float:
    try:
        orbit = TLEOrbit(r_prev.tle)
        sv_before = orbit.propagate(r_cur.epoch)
        sv_after  = TLEOrbit(r_cur.tle).propagate(r_cur.epoch)
        return float(np.linalg.norm(sv_after.v - sv_before.v))
    except Exception:
        v1 = math.sqrt(MU_EARTH / r_prev.sma_km)
        v2 = math.sqrt(MU_EARTH / r_cur.sma_km)
        dv_alt = abs(v2 - v1)
        dv_inc = 2.0 * v2 * abs(math.sin(math.radians(abs(_angle_diff(r_prev.inc_deg, r_cur.inc_deg)) / 2.0)))
        return math.hypot(dv_alt, dv_inc)


def _classify_manoeuvre(dv, d_alt, d_inc, d_ecc, regime):
    sk_limit = _SK_DV_LIMIT.get(regime, 0.050)
    scores = {"altitude": abs(d_alt), "inclination": abs(d_inc) * 100, "eccentricity": abs(d_ecc) * 1000}
    dominant = max(scores, key=lambda k: scores[k])
    if abs(d_inc) > 0.05 and abs(d_inc) > abs(d_alt) * 0.1:
        dominant = "inclination"
    if all(v < 0.5 for v in scores.values()):
        dominant = "mixed"

    if dv <= sk_limit:
        mtype  = "station_keeping"
        sk_sub = "NS" if abs(d_inc) > 0.02 else ("EW" if abs(d_alt) > 0.5 or abs(d_ecc) > 5e-5 else "combined")
    elif abs(d_inc) > 0.5:
        mtype, sk_sub = "plane_change", ""
    elif abs(d_alt) > 50.0 or dv > sk_limit * 5:
        mtype, sk_sub = "repositioning", ""
    else:
        mtype, sk_sub = "unknown", ""
    return dominant, mtype, sk_sub


def _percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _pol_stats(values):
    if len(values) < 2:
        return None
    mu  = sum(values) / len(values)
    std = math.sqrt(sum((x - mu) ** 2 for x in values) / (len(values) - 1))
    return PolStats(mean=mu, std=std, p5=_percentile(values, 5), p95=_percentile(values, 95),
                    low_2sigma=mu - 2*std, high_2sigma=mu + 2*std, n=len(values))


def _downsample(records, max_pts=500):
    if len(records) <= max_pts:
        return records
    step = len(records) / max_pts
    return [records[int(i * step)] for i in range(max_pts)]


# ── Drift phase analysis ──────────────────────────────────────────────────────

def _compute_drift_phases(records: list[TLERecord]) -> list[DriftPhase]:
    """Detect contiguous periods of East / West / Stationary longitude drift."""
    geo_recs = [r for r in records if r.geo_longitude_deg is not None and r.geo_drift_rate_deg_day is not None]
    if len(geo_recs) < 3:
        return []

    def _dir(rate: float) -> str:
        if rate > _DRIFT_STATIONARY:
            return "EAST"
        if rate < -_DRIFT_STATIONARY:
            return "WEST"
        return "STATIONARY"

    phases: list[DriftPhase] = []
    phase_start = geo_recs[0]
    cur_dir     = _dir(geo_recs[0].geo_drift_rate_deg_day)  # type: ignore[arg-type]
    rates_in_phase = [geo_recs[0].geo_drift_rate_deg_day]   # type: ignore[list-item]

    def _flush(start: TLERecord, end: TLERecord, rates: list[float], direction: str) -> None:
        dur = (end.epoch - start.epoch).total_seconds() / 86400.0
        if dur < 0.5:
            return
        mean_rate  = sum(rates) / len(rates)
        peak_rate  = max(abs(r) for r in rates)
        dist       = mean_rate * dur
        # Use signed raw longitude difference for distance (handles 180° wrap)
        start_lon  = start.geo_longitude_deg or 0.0
        end_lon    = end.geo_longitude_deg   or 0.0
        phases.append(DriftPhase(
            start_epoch=start.epoch, end_epoch=end.epoch,
            direction=direction, rate_deg_day=round(mean_rate, 3),
            start_lon=round(start_lon, 2), end_lon=round(end_lon, 2),
            distance_deg=round(dist, 2), duration_days=round(dur, 1),
            peak_rate=round(peak_rate, 3),
        ))

    for rec in geo_recs[1:]:
        d = _dir(rec.geo_drift_rate_deg_day)  # type: ignore[arg-type]
        if d != cur_dir:
            _flush(phase_start, rec, rates_in_phase, cur_dir)
            phase_start    = rec
            cur_dir        = d
            rates_in_phase = [rec.geo_drift_rate_deg_day]  # type: ignore[list-item]
        else:
            rates_in_phase.append(rec.geo_drift_rate_deg_day)  # type: ignore[arg-type]

    _flush(phase_start, geo_recs[-1], rates_in_phase, cur_dir)
    return phases


# ── Anomaly scoring ───────────────────────────────────────────────────────────

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _compute_anomaly_score(
    manoeuvres: list[Manoeuvre],
    drift_phases: list[DriftPhase],
    dv_stats: PolStats | None,
    interval_stats: PolStats | None,
    span_days: float,
    regime: str,
) -> AnomalyScore | None:
    if not manoeuvres or len(manoeuvres) < 2:
        return None

    bl = _GEO_SK_BASELINE

    # ΔV magnitude score (0=normal SK, 100=very large burns)
    mean_dv_ms = (dv_stats.mean * 1000) if dv_stats else 0.0
    dv_score   = _clamp01((mean_dv_ms - bl["dv_mean_ms"]) / (bl["dv_mean_ms"] * 4)) * 100

    # Longitude coverage score (GEO only)
    lons = [m.tle_after.geo_longitude_deg for m in manoeuvres if m.tle_after.geo_longitude_deg is not None]
    lon_range = (max(lons) - min(lons)) if len(lons) > 1 else 0.0
    lon_score = _clamp01(lon_range / 60.0) * 100   # 60° = full score

    # Drift rate score
    if drift_phases:
        max_drift = max(abs(p.rate_deg_day) for p in drift_phases)
        drift_score = _clamp01((max_drift - bl["max_drift_deg_d"]) / 1.5) * 100
    else:
        drift_score = 0.0

    # SK regularity score (coefficient of variation of intervals)
    if interval_stats and interval_stats.std > 0:
        cv = interval_stats.std / max(interval_stats.mean, 0.01)
        reg_score = _clamp01(cv / 2.0) * 100
    else:
        reg_score = 0.0

    # Annual ΔV budget score
    total_dv_ms = sum(m.delta_v_km_s for m in manoeuvres) * 1000
    annual_dv   = total_dv_ms / max(span_days / 365.25, 0.1)
    budget_score = _clamp01(annual_dv / 200.0) * 100   # 200 m/s/yr = full score

    # Weighted composite
    if regime in ("GEO", "DEEP"):
        overall = (dv_score * 0.20 + lon_score * 0.30 + drift_score * 0.25
                   + reg_score * 0.10 + budget_score * 0.15)
    else:
        overall = (dv_score * 0.30 + reg_score * 0.20 + budget_score * 0.25
                   + drift_score * 0.10 + lon_score * 0.15)

    if overall >= 75:
        risk = "CRITICAL"
    elif overall >= 55:
        risk = "HIGH"
    elif overall >= 35:
        risk = "MEDIUM"
    elif overall >= 15:
        risk = "LOW"
    else:
        risk = "MINIMAL"

    return AnomalyScore(
        dv_magnitude=round(dv_score,  1),
        lon_coverage=round(lon_score, 1),
        drift_rate  =round(drift_score, 1),
        sk_regularity=round(reg_score, 1),
        budget_rate =round(budget_score, 1),
        overall     =round(overall,   1),
        risk_level  =risk,
    )


# ── Propellant budget ─────────────────────────────────────────────────────────

def _compute_propellant_budget(
    total_dv_km_s: float,
    span_days: float,
    regime: str,
) -> PropellantBudget:
    isp = _ISP_BI if regime in ("GEO", "DEEP", "HEO") else _ISP_MONO
    ve  = isp * _G0_KM_S2     # exhaust velocity km/s
    # Assume ~30% of launch mass is propellant (typical GEO)
    assumed_prop_kg = 900.0   # kg — typical 3-tonne GEO platform
    mass_frac_used  = 1.0 - math.exp(-total_dv_km_s / ve) if ve > 0 else 0.0
    pct_used        = mass_frac_used * 100.0
    annual_dv       = total_dv_km_s / max(span_days / 365.25, 0.1)
    # Remaining propellant (rough)
    prop_remaining  = assumed_prop_kg * (1.0 - mass_frac_used)
    dv_remaining    = -ve * math.log(max(1.0 - prop_remaining / (assumed_prop_kg + assumed_prop_kg), 0.01)) if prop_remaining > 0 else 0.0
    life_remaining  = dv_remaining / annual_dv if annual_dv > 0 else None

    if annual_dv * 1000 > 100:
        budget_class = "Very High"
    elif annual_dv * 1000 > 50:
        budget_class = "High"
    elif annual_dv * 1000 > 20:
        budget_class = "Normal"
    else:
        budget_class = "Conservative"

    return PropellantBudget(
        assumed_isp_s         = isp,
        assumed_propellant_kg = assumed_prop_kg,
        total_dv_km_s         = round(total_dv_km_s, 4),
        propellant_used_pct   = round(pct_used, 1),
        annual_dv_km_s        = round(annual_dv, 4),
        remaining_life_years  = round(life_remaining, 1) if life_remaining and life_remaining < 50 else None,
        budget_class          = budget_class,
    )


# ── Intelligence assessment ───────────────────────────────────────────────────

def _intel_assessment(
    records: list[TLERecord],
    manoeuvres: list[Manoeuvre],
    drift_phases: list[DriftPhase],
    anomaly: AnomalyScore | None,
    propellant: PropellantBudget | None,
    regime: str,
    span_days: float,
) -> IntelAssessment:

    # Current state
    last_rec     = records[-1]
    last_drift   = last_rec.geo_drift_rate_deg_day
    cur_dir      = "EAST" if (last_drift or 0) > _DRIFT_STATIONARY else (
                   "WEST" if (last_drift or 0) < -_DRIFT_STATIONARY else "STATIONARY")

    # Longitude coverage
    lons = [r.geo_longitude_deg for r in records if r.geo_longitude_deg is not None]
    lon_range = (max(lons) - min(lons)) if len(lons) > 1 else 0.0

    # SK fraction
    n_mnv = len(manoeuvres)
    sk_n  = sum(1 for m in manoeuvres if m.manoeuvre_type == "station_keeping")
    sk_frac = sk_n / n_mnv if n_mnv > 0 else 1.0

    # Predictions (simple linear extrapolation of current drift)
    pred_30 = pred_60 = pred_90 = None
    if last_rec.geo_longitude_deg is not None and last_drift is not None:
        cur_lon = last_rec.geo_longitude_deg
        pred_30 = round(cur_lon + last_drift * 30,  2)
        pred_60 = round(cur_lon + last_drift * 60,  2)
        pred_90 = round(cur_lon + last_drift * 90,  2)

    # Notable periods (significant drift phases)
    notable: list[str] = []
    for ph in drift_phases:
        if ph.direction != "STATIONARY" and abs(ph.distance_deg) > 5.0:
            notable.append(
                f"{ph.start_epoch.strftime('%Y-%m-%d')} — {ph.end_epoch.strftime('%Y-%m-%d')}: "
                f"{ph.direction} drift {abs(ph.distance_deg):.1f}° at {abs(ph.rate_deg_day):.2f}°/day"
            )

    # Mission profile
    score = anomaly.overall if anomaly else 0.0

    if regime in ("GEO", "DEEP"):
        if lon_range > 30.0 or (anomaly and anomaly.drift_rate > 60):
            mission = "On-orbit Inspection / RPO Platform (GEO Belt Roamer)"
            bclass  = "Non-standard GEO — deliberate large-scale drift operations"
        elif lon_range > 5.0:
            mission = "GEO Longitude Relocation / Repositioning"
            bclass  = "Above-normal GEO drift — repositioning to new slot"
        elif sk_frac > 0.8:
            mission = "Standard GEO Station-Keeping"
            bclass  = "Normal GEO commercial / government operations"
        else:
            mission = "GEO — Irregular Operations"
            bclass  = "Mixed SK and repositioning — atypical for commercial operator"
    else:
        if score > 55:
            mission = f"Active Manoeuvring Platform ({regime})"
            bclass  = "High-activity orbit adjustment — non-passive payload"
        elif score > 25:
            mission = f"Operational Satellite with Periodic Correction ({regime})"
            bclass  = "Routine altitude / inclination maintenance"
        else:
            mission = f"Passive / Minimal-Manoeuvre Payload ({regime})"
            bclass  = "Low activity — possible debris or decommissioned asset"

    # Risk level
    risk = anomaly.risk_level if anomaly else "MINIMAL"

    # Narrative
    if regime in ("GEO", "DEEP") and lon_range > 20.0:
        narrative = (
            f"This object has traversed {lon_range:.1f}° of the GEO belt over {span_days:.0f} days — "
            f"a distance inconsistent with commercial or government station-keeping operations, which "
            f"typically maintain a ±0.1° longitude box. The pattern of alternating drift phases and "
            f"manoeuvres is consistent with a deliberate repositioning or proximity inspection mission. "
            f"Current drift: {cur_dir} at {abs(last_drift or 0):.3f}°/day."
        )
    elif score > 55:
        narrative = (
            f"Analysis of {len(manoeuvres)} detected manoeuvres over {span_days:.0f} days shows "
            f"activity significantly above the norm for this orbit regime. Manoeuvre ΔVs and "
            f"frequency are inconsistent with routine station-keeping. Recommend enhanced monitoring."
        )
    elif n_mnv == 0:
        narrative = (
            f"No manoeuvres detected above the analysis threshold over the {span_days:.0f}-day "
            f"observation period. Object appears passive. Consistent with debris, decommissioned "
            f"asset, or a platform with very low thrust profile."
        )
    else:
        narrative = (
            f"Activity is broadly consistent with normal operational behaviour for a {regime} satellite. "
            f"{n_mnv} manoeuvres detected — primarily {mission.lower()}."
        )

    # Operational signature (fingerprint)
    if n_mnv > 0:
        type_counts: dict[str, int] = {}
        for m in manoeuvres:
            type_counts[m.manoeuvre_type] = type_counts.get(m.manoeuvre_type, 0) + 1
        sig_parts = [f"{v} {k.replace('_',' ')}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])]
        if propellant:
            sig_parts.append(f"~{propellant.propellant_used_pct:.0f}% propellant consumed")
        if lon_range > 0:
            sig_parts.append(f"{lon_range:.1f}° GEO belt coverage")
        op_sig = " · ".join(sig_parts)
    else:
        op_sig = "No manoeuvres detected — passive object"

    return IntelAssessment(
        mission_profile       = mission,
        behaviour_class       = bclass,
        risk_level            = risk,
        operational_signature = op_sig,
        anomaly_narrative     = narrative,
        notable_periods       = notable[:8],
        predicted_lon_30d     = pred_30,
        predicted_lon_60d     = pred_60,
        predicted_lon_90d     = pred_90,
        current_drift_dir     = cur_dir,
        current_drift_rate    = round(last_drift, 3) if last_drift is not None else None,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def parse_tle_history(
    tle_text: str,
    satno: int | None = None,
    metadata: dict[str, tuple[str, str]] | None = None,
) -> list[TLERecord]:
    """Parse a block of historical TLEs into chronologically-sorted TLERecords.

    *metadata* optionally maps TLE line-1 strings to ``(data_mode, source)``
    tuples retrieved from the UDL response, which are stored on each record
    for provenance tracking and display in the elset table.
    """
    raw_lines = [ln.rstrip() for ln in tle_text.splitlines()]
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        if not line:
            i += 1
            continue
        if (
            line.startswith("1 ")
            and len(line) >= 69
            and i + 1 < len(raw_lines)
            and raw_lines[i + 1].strip().startswith("2 ")
        ):
            pairs.append((line, raw_lines[i + 1].strip()))
            i += 2
            continue
        i += 1

    records: list[TLERecord] = []
    seen: set[str] = set()
    for l1, l2 in pairs:
        try:
            rec = _satrec_to_record(f"{l1}\n{l2}")
            key = rec.epoch.strftime("%Y%j%H%M%S")
            if key not in seen:
                seen.add(key)
                if metadata and l1 in metadata:
                    rec.data_mode, rec.source = metadata[l1]
                records.append(rec)
        except Exception:
            continue

    records.sort(key=lambda r: r.epoch)
    return records


def analyse_pattern_of_life(
    records: list[TLERecord],
    satno: int = 0,
    name: str = "UNKNOWN",
    dv_threshold: float = _DV_NOISE_FLOOR,
) -> PolAnalysis:
    """Run the full PoL analysis on a sorted list of TLERecords."""
    if not records:
        raise ValueError("No TLE records to analyse")

    regime    = records[len(records) // 2].regime
    span_days = (records[-1].epoch - records[0].epoch).total_seconds() / 86400.0

    # ── Manoeuvre detection ───────────────────────────────────────────────────
    manoeuvres: list[Manoeuvre] = []
    for i in range(1, len(records)):
        rp, rc = records[i - 1], records[i]
        gap = (rc.epoch - rp.epoch).total_seconds() / 86400.0
        if gap > _MAX_GAP_DAYS:
            continue
        dv = _estimate_dv(rp, rc)
        if dv < dv_threshold:
            continue

        d_alt  = rc.alt_km  - rp.alt_km
        d_inc  = _angle_diff(rp.inc_deg,  rc.inc_deg)
        d_ecc  = rc.ecc     - rp.ecc
        d_per  = (rc.period_min - rp.period_min) * 60.0

        raan_j2  = _j2_raan_rate(rp)  * gap
        argp_j2  = _j2_argp_rate(rp)  * gap
        d_raan   = _angle_diff(rp.raan_deg + raan_j2, rc.raan_deg)
        d_argp   = _angle_diff(rp.argp_deg + argp_j2, rc.argp_deg)

        d_drift  = None
        if rp.geo_drift_rate_deg_day is not None and rc.geo_drift_rate_deg_day is not None:
            d_drift = rc.geo_drift_rate_deg_day - rp.geo_drift_rate_deg_day

        dominant, mtype, sk_sub = _classify_manoeuvre(dv, d_alt, d_inc, d_ecc, regime)
        manoeuvres.append(Manoeuvre(
            epoch=rc.epoch, gap_days=gap,
            delta_v_km_s=dv, delta_alt_km=d_alt, delta_inc_deg=d_inc,
            delta_ecc=d_ecc, delta_raan_corrected_deg=d_raan,
            delta_argp_corrected_deg=d_argp, delta_period_s=d_per,
            delta_drift_deg_day=d_drift,
            dominant_element=dominant, manoeuvre_type=mtype, sk_subtype=sk_sub,
            tle_before=rp, tle_after=rc,
        ))

    # ── Drift phases ──────────────────────────────────────────────────────────
    drift_phases = _compute_drift_phases(records)

    # ── Statistics ────────────────────────────────────────────────────────────
    dv_vals   = [m.delta_v_km_s for m in manoeuvres]
    total_dv  = sum(dv_vals)
    sorted_m  = sorted(manoeuvres, key=lambda m: m.epoch)

    intervals: list[float] = []
    for j in range(1, len(sorted_m)):
        intervals.append((sorted_m[j].epoch - sorted_m[j-1].epoch).total_seconds() / 86400.0)

    dv_stats       = _pol_stats(dv_vals)
    interval_stats = _pol_stats(intervals)

    # Classification
    if manoeuvres:
        tc: dict[str, int] = {}
        for m in manoeuvres:
            tc[m.manoeuvre_type] = tc.get(m.manoeuvre_type, 0) + 1
        dominant_activity = max(tc, key=lambda k: tc[k])
    else:
        dominant_activity = "none_detected"

    sk_count = sum(1 for m in manoeuvres if m.manoeuvre_type == "station_keeping")
    is_sk    = len(manoeuvres) > 0 and sk_count / len(manoeuvres) >= 0.6
    if is_sk:
        ns_n = sum(1 for m in manoeuvres if m.sk_subtype == "NS")
        ew_n = sum(1 for m in manoeuvres if m.sk_subtype == "EW")
        sk_type = "inclination (NS)" if ns_n > ew_n * 2 else ("altitude (EW)" if ew_n > ns_n * 2 else "combined (EW+NS)")
    else:
        sk_type = "N/A"

    # Prediction
    next_est = next_unc = None
    if interval_stats and interval_stats.n >= 3 and sorted_m:
        pred = sorted_m[-1].epoch + timedelta(days=interval_stats.mean)
        next_est = pred.strftime("%Y-%m-%d %H:%M UTC")
        next_unc = round(interval_stats.std * 2.0, 1)

    # PoL status
    pol_status = "NORMAL"
    pol_reason = "All metrics within normal historical bounds."
    if manoeuvres and dv_stats:
        last_dv = manoeuvres[-1].delta_v_km_s if (
            records[-1].epoch - manoeuvres[-1].epoch
        ).total_seconds() / 86400.0 < 10 else None
        if last_dv and dv_stats.std > 0:
            z = (last_dv - dv_stats.mean) / dv_stats.std
            if z > 3.0:
                pol_status = "ANOMALOUS"
                pol_reason = f"Latest ΔV {last_dv:.4f} km/s is {z:.1f}σ above historical mean."
            elif z > 2.0:
                pol_status = "CAUTION"
                pol_reason = f"Latest ΔV {last_dv:.4f} km/s is {z:.1f}σ above mean — approaching anomalous threshold."
    if not manoeuvres:
        pol_reason = "No manoeuvres detected — object appears passive."

    # Scoring + assessment
    anomaly_score    = _compute_anomaly_score(manoeuvres, drift_phases, dv_stats, interval_stats, span_days, regime)
    propellant_budget = _compute_propellant_budget(total_dv, span_days, regime)
    intel = _intel_assessment(records, manoeuvres, drift_phases, anomaly_score, propellant_budget, regime, span_days)

    # ── Chart data ────────────────────────────────────────────────────────────
    cr = _downsample(records, 500)
    chart_epochs    = [r.epoch.strftime("%Y-%m-%d") for r in cr]
    chart_alts      = [round(r.alt_km, 2)          for r in cr]
    chart_incs      = [round(r.inc_deg, 4)          for r in cr]
    chart_eccs      = [round(r.ecc, 6)              for r in cr]
    chart_raans     = [round(r.raan_deg, 4)         for r in cr]
    chart_periods   = [round(r.period_min, 4)       for r in cr]
    chart_lons      = [round(r.geo_longitude_deg, 3) if r.geo_longitude_deg is not None else 0 for r in cr]
    chart_drifts    = [round(r.geo_drift_rate_deg_day, 4) if r.geo_drift_rate_deg_day is not None else 0 for r in cr]

    man_epochs        = [m.epoch.strftime("%Y-%m-%d") for m in sorted_m]
    man_dvs           = [round(m.delta_v_km_s * 1000, 3) for m in sorted_m]
    man_types         = [m.manoeuvre_type              for m in sorted_m]
    man_alts          = [round(m.tle_after.alt_km, 1)  for m in sorted_m]
    man_drift_deltas  = [round(m.delta_drift_deg_day, 3) if m.delta_drift_deg_day is not None else 0 for m in sorted_m]

    return PolAnalysis(
        satno=satno, name=name, tle_count=len(records),
        span_days=round(span_days, 1), regime=regime,
        records=records, manoeuvres=sorted_m,
        chart_epochs=chart_epochs, chart_alts=chart_alts,
        chart_incs=chart_incs, chart_eccs=chart_eccs,
        chart_raans=chart_raans, chart_periods=chart_periods,
        chart_longitudes=chart_lons, chart_drift_rates=chart_drifts,
        manoeuvre_epochs=man_epochs, manoeuvre_dvs=man_dvs,
        manoeuvre_types=man_types, manoeuvre_alts=man_alts,
        manoeuvre_drift_deltas=man_drift_deltas,
        drift_phases=drift_phases,
        total_dv_km_s=round(total_dv, 4),
        dv_stats=dv_stats, interval_stats=interval_stats,
        dominant_activity=dominant_activity,
        is_station_keeping=is_sk, sk_type=sk_type,
        anomaly_score=anomaly_score,
        propellant_budget=propellant_budget,
        intel_assessment=intel,
        next_manoeuvre_est=next_est,
        next_manoeuvre_uncertainty_days=next_unc,
        pol_status=pol_status, pol_status_reason=pol_reason,
        dv_threshold_km_s=dv_threshold,
        pol_high_dv=round(dv_stats.high_2sigma, 4)     if dv_stats else None,
        pol_high_interval=round(interval_stats.high_2sigma, 1) if interval_stats else None,
        pol_low_interval =round(interval_stats.low_2sigma,  1) if interval_stats else None,
    )
