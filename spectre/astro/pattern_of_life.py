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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sgp4.api import Satrec

from spectre.astro.constants import (
    J2_EARTH,
    MU_EARTH,
    R_EARTH,
    SIDEREAL_DAY,
    classify_orbit_regime,
)
from spectre.astro.dv_estimation import (
    DvBreakdown,
    NoiseModel,
    build_breakdown,
    calibrate_noise,
    estimate_dv_mean_elements,
    secular_rates_deg_day,
    snapshot_from_record,
)

# ── Physical constants ────────────────────────────────────────────────────────

_EARTH_ROT  = 86400.0 / SIDEREAL_DAY  # rev/solar-day ≈ 1.002737

# ── Thresholds ────────────────────────────────────────────────────────────────

# Floor on the operator-supplied ΔV threshold (km/s). The real detection
# threshold is measured per object by ``calibrate_noise``; this is only the
# default for the form field.
_DV_NOISE_FLOOR   = 0.002   # km/s

# Beyond this gap the object could have done anything in between, so a single
# before/after pair cannot be read as one manoeuvre. Raised from 15 days once
# the estimator stopped degrading with the gap; detections beyond
# ``_LONG_GAP_WARN_DAYS`` are kept but flagged as possibly several burns.
_MAX_GAP_DAYS       = 30.0  # days
_LONG_GAP_WARN_DAYS = 10.0  # days

# Two detections of one burn by two different providers arrive within about a
# catalogue interval of each other. Detections whose measured burn epochs fall
# inside this window are merged into one event.
_MERGE_WINDOW_FLOOR_DAYS = 0.25


# Full forensic breakdowns are ~1.8 ms each against ~0.01 ms for the screening
# estimator. Detections are ranked by ΔV and the largest this many get the full
# treatment; beyond that the element figure stands and says so.
_MAX_FULL_BREAKDOWNS = 500
_DRIFT_STATIONARY = 0.05    # °/day — |drift| below this → "Stationary"
_DRIFT_SIGNIFICANT = 0.20   # °/day — above this → meaningful drift phase

# _SK_DV_LIMIT and _GEO_SK_BASELINE used to live here. Both are gone, and
# nothing in this module replaces them, because neither was a measurement.
#
# _SK_DV_LIMIT applied Table 3's ANNUAL station-keeping budgets as PER-EVENT
# limits: 50 m/s for GEO, against a real single north-south burn of about
# 1.8 m/s. Four of the open-source assessment's own named counterspace events
# classified as routine station-keeping as a result, including both
# Luch/Olymp-K relocations. _GEO_SK_BASELINE implied 209 m/s/yr against the
# cited 44 to 55.
#
# Those judgements now live in spectre/domain/pol_assessment.py, built on
# spectre/domain/manoeuvre_calibration.py, where the figures are cited and
# where the operator-facing unit is m/s. This module measures and stops there.


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

    # Quality metadata — populated from UDL elset record when available
    rms_residual:   float | None = None  # Fit residual from UDL (lower = better quality)
    element_set_no: int          = 0     # TLE element-set number from line 1 col 64–67


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

    #: Which element the manoeuvre principally moved. The operational label
    #: ("station keeping", "relocation", "plane change") is a judgement against
    #: cited per-regime budgets and is produced by
    #: :func:`spectre.domain.pol_assessment.assess_pattern_of_life`.
    dominant_element:   str

    tle_before: TLERecord
    tle_after:  TLERecord

    #: Sources other than this detection's own that reported the same burn
    #: inside the merge window. Empty when nothing corroborated it, which on a
    #: single-provider catalogue is every detection.
    corroborated_by: tuple[str, ...] = ()

    #: The full working behind ``delta_v_km_s``: both estimates, every term in
    #: the element decomposition, the element sets side by side with their
    #: provenance, the measured noise floor and a confidence verdict. This is
    #: what the drill-down renders. ``None`` only where the detection fell
    #: outside the forensic budget, in which case ``delta_v_km_s`` is the
    #: element-differencing figure.
    breakdown: DvBreakdown | None = None

    @property
    def burn_epoch(self) -> datetime:
        """When the burn happened, measured where possible.

        ``epoch`` is the after-element-set epoch, which can be wrong by the
        whole gap. The epoch-swept estimator dates the burn properly; fall back
        to ``epoch`` only when it could not.
        """
        bd = self.breakdown
        if bd is not None and bd.burn_epoch is not None and not bd.swept.burn_epoch_ambiguous:
            return bd.burn_epoch
        return self.epoch

    @property
    def confidence(self) -> str:
        return self.breakdown.confidence if self.breakdown else "UNASSESSED"


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

    #: Confirmed manoeuvres. Everything downstream — cumulative ΔV, propellant
    #: budget, anomaly score, intelligence assessment — is derived from these
    #: and only these.
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
    manoeuvre_alts:     list[float]
    manoeuvre_drift_deltas: list[float]  # change in drift rate at each manoeuvre

    # Drift phases
    drift_phases: list[DriftPhase]

    # Statistics
    total_dv_km_s:  float
    dv_stats:       PolStats | None
    interval_stats: PolStats | None

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

    # TLE cadence filter — populated when cadence filtering was applied
    quality_flags:          list[Any] = field(default_factory=list)  # list[QualityFlag]

    # ── Detection audit trail ────────────────────────────────────────────────
    # What the detector looked at and what it threw away, so the manoeuvre count
    # can be defended rather than merely reported.
    #: Detections that cleared the reporting floor but not the confirmation
    #: level. Shown to the operator as candidates, deliberately excluded from
    #: every derived statistic.
    candidate_manoeuvres:   list[Manoeuvre] = field(default_factory=list)

    noise_model:            NoiseModel | None = None
    pairs_examined:         int = 0
    rejected_below_floor:   int = 0   # screened out by the measured noise floor
    rejected_on_evidence:   int = 0   # survived the floor, failed the forensics
    skipped_long_gap:       int = 0   # gap too large to read as a single burn
    merged_duplicates:      int = 0   # same burn reported by more than one provider
    breakdowns_truncated:   int = 0   # detections past the forensic budget


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

    # Element Set Number — TLE line 1, columns 65-68 (1-indexed), right-justified
    try:
        esn = int(lines[-2][64:68].strip())
    except (ValueError, IndexError):
        esn = 0

    return TLERecord(
        epoch=epoch, tle=tle,
        sma_km=sma, ecc=ecc, inc_deg=inc_deg,
        raan_deg=raan_deg, argp_deg=argp_deg, mean_anomaly_deg=ma_deg,
        mean_motion_revday=n_revday, bstar=sat.bstar,
        alt_km=alt_km, period_min=period_min, regime=regime,
        geo_longitude_deg=geo_lon,
        geo_drift_rate_deg_day=geo_drift,
        element_set_no=esn,
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
    # See the note in spectre.astro.dv_estimation._j2_argp_rate_deg_day: the
    # previous form was the exact negative of the J2 perigee rate.
    rate = 0.75 * n * J2_EARTH * (R_EARTH / rec.sma_km) ** 2 * (5.0 * math.cos(math.radians(rec.inc_deg)) ** 2 - 1.0) / d
    return math.degrees(rate) * 86400.0


def _angle_diff(a: float, b: float) -> float:
    return (b - a + 180.0) % 360.0 - 180.0


def _estimate_dv(r_prev: TLERecord, r_cur: TLERecord) -> float:
    """Screening ΔV between two element sets, in km/s.

    Mean element differencing. Cheap enough to run on every consecutive pair in
    a long history, and structurally immune to the along-track phase error that
    made the previous propagation-difference method report thousands of metres
    per second for objects that never manoeuvred. See
    :mod:`spectre.astro.dv_estimation` for the measurements.

    This is the screening figure. Detections are re-estimated with the full
    machinery, which is more accurate still and dates the burn.
    """
    gap_days = (r_cur.epoch - r_prev.epoch).total_seconds() / 86400.0
    b = snapshot_from_record(r_prev)
    a = snapshot_from_record(r_cur)
    raan_rate, argp_rate = secular_rates_deg_day(r_prev.tle, b.sma_km, b.ecc, b.inc_deg)
    return estimate_dv_mean_elements(b, a, gap_days, raan_rate, argp_rate).dv_km_s


def _source_key(rec: TLERecord) -> str:
    """Which catalogue produced this fit.

    Differencing one organisation's orbit determination against another's
    measures the disagreement between them, not a manoeuvre. Two providers
    whose semi-major axes differ by 6 km put a standing 3.5 m/s on every
    provider switch, which buries every real station-keeping burn beneath it.
    Records with no attribution are grouped together rather than discarded.
    """
    return (rec.source or "").strip().upper() or "UNATTRIBUTED"


def _build_pairs(records: list[TLERecord]) -> list[tuple[TLERecord, TLERecord, float]]:
    """Consecutive element set pairs, matched within source where known.

    Falls back to plain consecutive pairing when the catalogue does not
    attribute its fits, or when splitting by source would leave too little to
    work with.
    """
    keys = {_source_key(r) for r in records}
    attributed = keys - {"UNATTRIBUTED"}

    # Any attribution at all is enough to separate. Requiring two NAMED
    # providers meant a catalogue of one named provider interleaved with
    # unattributed fits fell back to plain consecutive pairing, so every pair
    # crossed the attribution boundary: measured, 5 of 5 pairs. That is the
    # cross-provider differencing this function exists to prevent, and it
    # defeated the cross_source warning too, because one side had no source to
    # compare.
    if not attributed or (len(keys) < 2):
        return [
            (records[i - 1], records[i],
             (records[i].epoch - records[i - 1].epoch).total_seconds() / 86400.0)
            for i in range(1, len(records))
        ]

    pairs: list[tuple[TLERecord, TLERecord, float]] = []
    last: dict[str, TLERecord] = {}
    for rec in records:
        k = _source_key(rec)
        prev = last.get(k)
        if prev is not None:
            pairs.append((prev, rec, (rec.epoch - prev.epoch).total_seconds() / 86400.0))
        last[k] = rec
    pairs.sort(key=lambda t: t[1].epoch)
    return pairs


def _merge_duplicate_detections(manoeuvres: list[Manoeuvre],
                                window_days: float) -> tuple[list[Manoeuvre], int]:
    """Collapse one burn seen by more than one provider into one event.

    Two detections can only be the same burn if they came from DIFFERENT
    sources. Within a single source each record is differenced against the
    previous record from that same source, so one burn produces exactly one
    detection; two detections from one provider are two burns, however close
    together they fall.

    That is the whole correction. The previous version clustered on time alone
    and chained off the most recently added member, so it grew without bound
    while each successive step stayed inside the window. Measured: six real
    10 m/s burns 0.9 days apart in a one-fit-per-day single-provider catalogue
    produced five correct HIGH detections totalling 62.2 m/s, which the merge
    then collapsed to two totalling 31.8 m/s. Half the object's measured ΔV
    disappeared into ``merged_duplicates``, a counter documented as counting
    cross-provider duplicates, in a catalogue with one provider and no
    duplicates in it at all. A bounded span alone does not fix that; it only
    changes how much is lost.

    The sources that corroborated a surviving detection are recorded on it, so
    the evidence is auditable rather than reduced to a count.
    """
    if len(manoeuvres) < 2:
        return manoeuvres, 0

    order = {"HIGH": 0, "MODERATE": 1, "LOW": 2, "UNASSESSED": 3}
    ranked = sorted(manoeuvres, key=lambda m: m.burn_epoch)

    def _src(m: Manoeuvre) -> str:
        return _source_key(m.tle_after)

    def _close(a: Manoeuvre, b: Manoeuvre) -> bool:
        return abs((b.burn_epoch - a.burn_epoch).total_seconds()) / 86400.0 <= window_days

    merged: list[Manoeuvre] = []
    cluster: list[Manoeuvre] = [ranked[0]]
    for m in ranked[1:]:
        # Same burn only if no member of the cluster shares this detection's
        # source, and it sits inside the window of the cluster ANCHOR, not of
        # whatever was added last.
        same_burn = (
            _src(m) not in {_src(c) for c in cluster}
            and _close(cluster[0], m)
        )
        if same_burn:
            cluster.append(m)
        else:
            merged.append(_pick_best(cluster, order))
            cluster = [m]
    merged.append(_pick_best(cluster, order))
    return merged, len(manoeuvres) - len(merged)


def _pick_best(cluster: list[Manoeuvre], order: dict[str, int]) -> Manoeuvre:
    """The best-evidenced member of a cluster, carrying who else saw it.

    Highest confidence first, then the tightest element set bracket, since a
    shorter gap localises the burn better.
    """
    best = min(cluster, key=lambda x: (order.get(x.confidence, 3), x.gap_days))
    others = tuple(sorted({_source_key(c.tle_after) for c in cluster
                           if c is not best}))
    if others:
        best.corroborated_by = others
    return best


#: Which orbital element each ΔV channel moves.
_CHANNEL_ELEMENT = {
    "along_track": "altitude",
    "cross_track": "inclination",
    "radial":      "eccentricity",
}


def _dominant_element(d_alt: float, d_inc: float, d_ecc: float,
                      breakdown: DvBreakdown | None = None) -> str:
    """Which orbital element this manoeuvre principally moved.

    A measurement, not a judgement: whether that constitutes station-keeping,
    a relocation or a plane change depends on cited per-regime budgets, which
    are m/s and live in :mod:`spectre.domain.pol_assessment`.

    Where a breakdown is available the answer is simply whichever ΔV channel
    carries the most, which is what "dominant" means. The fallback compares raw
    element deltas scaled against each other with weights that have no physical
    basis; it survives only for pairs that fell outside the forensic budget.
    """
    if breakdown is not None and breakdown.components:
        top = max(breakdown.components, key=lambda c: c.dv_km_s)
        total = sum(c.dv_km_s for c in breakdown.components)
        if total > 0 and top.dv_km_s / total >= 0.6:
            return _CHANNEL_ELEMENT.get(top.channel, "mixed")
        return "mixed"

    scores = {"altitude": abs(d_alt), "inclination": abs(d_inc) * 100,
              "eccentricity": abs(d_ecc) * 1000}
    if all(v < 0.5 for v in scores.values()):
        return "mixed"
    if abs(d_inc) > 0.05 and abs(d_inc) > abs(d_alt) * 0.1:
        return "inclination"
    return max(scores, key=lambda k: scores[k])


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _pol_stats(values: list[float]) -> PolStats | None:
    if len(values) < 2:
        return None
    mu  = sum(values) / len(values)
    std = math.sqrt(sum((x - mu) ** 2 for x in values) / (len(values) - 1))
    return PolStats(mean=mu, std=std, p5=_percentile(values, 5), p95=_percentile(values, 95),
                    low_2sigma=mu - 2*std, high_2sigma=mu + 2*std, n=len(values))


def _downsample(records: list[Any], max_pts: int = 500) -> list[Any]:
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
    cur_dir     = _dir(geo_recs[0].geo_drift_rate_deg_day or 0.0)
    rates_in_phase: list[float] = [geo_recs[0].geo_drift_rate_deg_day or 0.0]

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
        d = _dir(rec.geo_drift_rate_deg_day or 0.0)
        if d != cur_dir:
            _flush(phase_start, rec, rates_in_phase, cur_dir)
            phase_start    = rec
            cur_dir        = d
            rates_in_phase = [rec.geo_drift_rate_deg_day or 0.0]
        else:
            rates_in_phase.append(rec.geo_drift_rate_deg_day or 0.0)

    _flush(phase_start, geo_recs[-1], rates_in_phase, cur_dir)
    return phases


# ── Public API ────────────────────────────────────────────────────────────────

def parse_tle_history(
    tle_text: str,
    satno: int | None = None,
    metadata: dict[str, tuple[str, str]] | None = None,
    rms_metadata: dict[str, float | None] | None = None,
) -> list[TLERecord]:
    """Parse a block of historical TLEs into chronologically-sorted TLERecords.

    Parameters
    ----------
    metadata:
        Maps TLE line-1 strings to ``(data_mode, source)`` tuples from UDL.
    rms_metadata:
        Maps TLE line-1 strings to RMS fit residuals from UDL (optional).
        Stored on each record as ``rms_residual`` for quality-based selection
        in :func:`~spectre.astro.tle_filter.filter_tle_history`.
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
                if rms_metadata and l1 in rms_metadata:
                    rec.rms_residual = rms_metadata[l1]
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
    quality_flags: list[Any] | None = None,
) -> PolAnalysis:
    """Run the full PoL analysis on a sorted list of TLERecords.

    Parameters
    ----------
    quality_flags:
        Optional list of warning strings from :func:`~spectre.astro.tle_filter.filter_tle_history`.
        Stored on the returned :class:`PolAnalysis` for display in the UI.
    """
    if not records:
        raise ValueError("No TLE records to analyse")

    regime    = records[len(records) // 2].regime
    span_days = (records[-1].epoch - records[0].epoch).total_seconds() / 86400.0

    # ── Manoeuvre detection ───────────────────────────────────────────────────
    #
    # Two passes. The first screens every consecutive pair with the cheap mean
    # element estimator and, from that whole distribution, measures what this
    # object's own fit scatter looks like. The second re-estimates only the
    # pairs that clear the measured floor, with the full forensic machinery.
    #
    # The floor has to be measured rather than assumed. A fixed threshold
    # cannot know that one object's catalogue is fed by a single sensor at one
    # fit per day while another's is nine fits a day from several providers
    # that disagree with each other. The median and median absolute deviation
    # are used because real burns, however large, move neither, so an object's
    # own manoeuvres cannot inflate the threshold meant to find them.

    pairs: list[tuple[TLERecord, TLERecord, float]] = []
    screen_dv: list[float] = []
    skipped_long_gap = 0
    for rp, rc, gap in _build_pairs(records):
        if gap > _MAX_GAP_DAYS:
            skipped_long_gap += 1
            continue
        pairs.append((rp, rc, gap))
        screen_dv.append(_estimate_dv(rp, rc))

    noise = calibrate_noise(screen_dv)
    # The operator's threshold and the measured floor are both lower bounds;
    # whichever is higher governs. Asking for 1 m/s on an object whose fits
    # disagree by 4 m/s does not make 1 m/s detectable.
    effective_threshold = max(dv_threshold, noise.floor_km_s)

    candidates = [(rp, rc, gap, dv)
                  for (rp, rc, gap), dv in zip(pairs, screen_dv, strict=True)
                  if dv >= effective_threshold]
    # Rank by screening ΔV so the largest events always get the full forensic
    # treatment even when the budget binds.
    candidates.sort(key=lambda c: c[3], reverse=True)
    rejected_below_floor = len(pairs) - len(candidates)
    # Captured before `candidates` is rebound to the candidate-TIER manoeuvre
    # list below. Reading it after the rebind made this counter the number of
    # low-confidence manoeuvres minus the budget, which is negative in every
    # realistic case and so reported zero however many detections were actually
    # truncated.
    pairs_over_forensic_budget = max(0, len(candidates) - _MAX_FULL_BREAKDOWNS)

    manoeuvres: list[Manoeuvre] = []
    for rank, (rp, rc, gap, screen) in enumerate(candidates):
        if rank < _MAX_FULL_BREAKDOWNS:
            bd = build_breakdown(rp, rc, gap, noise)
            if bd.confidence == "REJECT":
                continue
            dv = bd.dv_km_s
        else:
            bd, dv = None, screen

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

        dominant = _dominant_element(d_alt, d_inc, d_ecc, bd)
        manoeuvres.append(Manoeuvre(
            epoch=rc.epoch, gap_days=gap,
            delta_v_km_s=dv, delta_alt_km=d_alt, delta_inc_deg=d_inc,
            delta_ecc=d_ecc, delta_raan_corrected_deg=d_raan,
            delta_argp_corrected_deg=d_argp, delta_period_s=d_per,
            delta_drift_deg_day=d_drift,
            dominant_element=dominant,
            tle_before=rp, tle_after=rc, breakdown=bd,
        ))

    rejected_on_evidence = len(candidates[:_MAX_FULL_BREAKDOWNS]) - sum(
        1 for m in manoeuvres if m.breakdown is not None
    )

    # One burn seen by two providers is one burn.
    gaps_seen = sorted(g for _, _, g in pairs)
    median_gap = gaps_seen[len(gaps_seen) // 2] if gaps_seen else 0.0
    detections, merged_duplicates = _merge_duplicate_detections(
        manoeuvres, max(_MERGE_WINDOW_FLOOR_DAYS, median_gap),
    )

    # Two tiers. A detection is confirmed only where two independent estimators
    # agree on it, it stands ten times above the object's own measured fit
    # scatter, and nothing about the element sets' provenance objects. Those
    # carry the headline statistics. Everything else is kept and shown as a
    # candidate but left out of the cumulative ΔV, the propellant budget and
    # the anomaly score: an unconfirmed detection is not evidence of expended
    # fuel, and treating it as such is how a LEO smallsat comes to read as
    # having spent 36,000 m/s against a lifetime budget of 2,500.
    manoeuvres = [m for m in detections if m.confidence == "HIGH"]
    candidates = [m for m in detections if m.confidence != "HIGH"]

    # ── Drift phases ──────────────────────────────────────────────────────────
    drift_phases = _compute_drift_phases(records)

    # ── Statistics ────────────────────────────────────────────────────────────
    dv_vals   = [m.delta_v_km_s for m in manoeuvres]
    total_dv  = float(sum(dv_vals))
    sorted_m  = sorted(manoeuvres, key=lambda m: m.epoch)

    intervals: list[float] = []
    for j in range(1, len(sorted_m)):
        intervals.append((sorted_m[j].epoch - sorted_m[j-1].epoch).total_seconds() / 86400.0)

    dv_stats       = _pol_stats(dv_vals)
    interval_stats = _pol_stats(intervals)

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
        manoeuvre_alts=man_alts,
        manoeuvre_drift_deltas=man_drift_deltas,
        drift_phases=drift_phases,
        total_dv_km_s=round(total_dv, 4),
        dv_stats=dv_stats, interval_stats=interval_stats,
        next_manoeuvre_est=next_est,
        next_manoeuvre_uncertainty_days=next_unc,
        pol_status=pol_status, pol_status_reason=pol_reason,
        dv_threshold_km_s=dv_threshold,
        pol_high_dv=round(dv_stats.high_2sigma, 4)     if dv_stats else None,
        pol_high_interval=round(interval_stats.high_2sigma, 1) if interval_stats else None,
        pol_low_interval =round(interval_stats.low_2sigma,  1) if interval_stats else None,
        quality_flags=quality_flags or [],
        candidate_manoeuvres=sorted(candidates, key=lambda m: m.epoch),
        noise_model=noise,
        pairs_examined=len(pairs),
        rejected_below_floor=rejected_below_floor,
        rejected_on_evidence=rejected_on_evidence,
        skipped_long_gap=skipped_long_gap,
        merged_duplicates=merged_duplicates,
        breakdowns_truncated=pairs_over_forensic_budget,
    )
