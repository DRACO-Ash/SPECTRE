"""Pattern of Life (PoL) measurements from historical TLE sequences.

Given element sets for a single object, this module measures and stops there:
  ● parses the history into mean elements from SGP4's own Satrec, dropping
    and counting element sets that will not parse;
  ● for GEO and GSO objects, the subsatellite longitude and the drift SGP4
    flies over one sidereal day;
  ● screens consecutive pairs against a noise floor measured from the
    object's own fit scatter (``dv_estimation.calibrate_noise``), and
    confirms detections with the forensic ΔV breakdown
    (``dv_estimation.build_breakdown``: epoch-swept propagation and mean
    element differencing, J2-corrected);
  ● merges the same burn reported by more than one provider;
  ● tracks longitude drift phases (east, west, stationary);
  ● computes ΔV and interval statistics, a small-sample prediction interval
    for the next burn, and a status scoring the latest burn against the
    earlier ones.

Judgements against cited per-regime budgets (station-keeping classification,
anomaly scoring, propellant budget, the operator-level assessment) live in
``spectre.domain.pol_assessment``, built on
``spectre.domain.manoeuvre_calibration``. This header used to list them here,
with a propagation-difference ΔV method the module no longer uses (audit
F-095).
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from scipy.stats import t as student_t
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


# ── Element set format ────────────────────────────────────────────────────────

# A TLE line is 69 columns by definition, the last of them the checksum, so
# anything past column 69 is not element set data. The whole supplied line was
# being stored on the record and rendered to the operator from there, which let
# text appended past the checksum reach the console verbatim.
#
# THIS CUT IS NOT THE CONTROL, and reading it as one is how the escaping gets
# weakened later. It BOUNDS a payload to 69 columns per line; it does not
# sanitise one. A complete, working `<img src=x onerror=...>` fits inside 69
# columns, survives this truncation intact, and still reaches the record and
# the DOM. The load-bearing control is that pol_results.html renders the stored
# text with no `| safe`, and the integration test that holds it there carries
# its payload INSIDE the columns for exactly this reason.
#
# What the cut does buy is that a record carries element set data and nothing
# else, so every future consumer of rec.tle starts from a bounded value.
#
# The length guard that used to spell the number out now reads this constant:
# parse_tle_history was split into helpers, so editing that line no longer
# drags its old complexity score into the quality gate's new-code window.
_TLE_LINE_COLUMNS = 69

#: Longitudes east of this wrap to the western hemisphere, so the drift series
#: reads as a continuous track rather than jumping the dateline.
_LONGITUDE_WRAP_DEG = 180.0

#: Two intervals give one gap and no spread; three is the smallest sample from
#: which a next-manoeuvre estimate carries any uncertainty worth printing.
_MIN_INTERVALS_FOR_PREDICTION = 3

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

# Fewest distinct attribution keys a history must carry before its fits are
# split by source. With fewer, every consecutive pair crosses the attribution
# boundary, which is the cross-provider differencing the split exists to
# prevent; the measurement behind that is recorded at the call site.
_MIN_DISTINCT_SOURCES_TO_SPLIT = 2

# Fewest detections for a merge to be possible at all. One detection has
# nothing beside it to be a duplicate of.
_MIN_MANOEUVRES_TO_MERGE = 2


# Full forensic breakdowns are ~1.8 ms each against ~0.01 ms for the screening
# estimator. Detections are ranked by ΔV and the largest this many get the full
# treatment; beyond that the element figure stands and says so.
_MAX_FULL_BREAKDOWNS = 500
_DRIFT_STATIONARY = 0.05    # °/day — |drift| below this → "Stationary"
_DRIFT_SIGNIFICANT = 0.20   # °/day — above this → meaningful drift phase

# Backward-compatible PoL status. This is an outlier test against the object's
# OWN measured history and nothing more; whether the behaviour matters
# operationally is a judgement against cited budgets and is made in
# spectre/domain/pol_assessment.py.
_STATUS_RECENT_DAYS     = 10.0  # days: older than this and there is no "latest" manoeuvre
_STATUS_ANOMALOUS_SIGMA = 3.0   # σ above the historical mean ΔV → "ANOMALOUS"
_STATUS_CAUTION_SIGMA   = 2.0   # σ above the historical mean ΔV → "CAUTION"
_STATUS_MIN_PRIOR       = 3     # earlier manoeuvres needed to score the latest

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
    def long_gap(self) -> bool:
        """True when the bracketing gap is long enough to hide several burns."""
        return self.gap_days > _LONG_GAP_WARN_DAYS

    @property
    def burn_window(self) -> tuple[datetime, datetime]:
        """Earliest and latest times the burn can have happened.

        The measured burn epoch where the estimator dated it; otherwise the
        bracket between the element sets either side, since the burn lies
        somewhere in that gap.
        """
        if self.burn_epoch is not self.epoch:
            return self.burn_epoch, self.burn_epoch
        return self.tle_before.epoch, self.epoch

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
    malformed_element_sets: int = 0   # pairs that would not parse, dropped
    breakdowns_truncated:   int = 0   # detections past the forensic budget
    # Newest archived epoch when the archive pull hit its record cap, so the
    # history may have a gap between it and the current element set.
    history_truncated_at:   datetime | None = None


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


def _geo_drift_deg_day(sat: Satrec, epoch: datetime) -> float | None:
    """Longitude drift (deg/day, positive east) that SGP4 flies from *epoch*.

    The Earth-fixed longitude change over one sidereal day of propagation,
    which cancels the daily swing an eccentric orbit adds. Mean motion alone
    leaves out the secular node and perigee rates (J2 alone is about
    0.0134 deg/day at GEO) and the deep-space terms SGP4 applies there
    (audit F-093). None if SGP4 reports an error.
    """
    jd = _epoch_to_jd(epoch)
    lons = []
    for days in (0.0, SIDEREAL_DAY / 86400.0):
        err, r, _ = sat.sgp4(jd + days, 0.0)
        if err:
            return None
        lons.append(math.degrees(math.atan2(r[1], r[0])) - _gst_deg(epoch + timedelta(days=days)))
    change = (lons[1] - lons[0] + 180.0) % 360.0 - 180.0
    return change / (SIDEREAL_DAY / 86400.0)


def _satrec_to_record(tle: str) -> TLERecord:
    # Cut to _TLE_LINE_COLUMNS here rather than only at the template, so the
    # record carries element set data and nothing else. See the constant.
    lines = [ln.strip()[:_TLE_LINE_COLUMNS] for ln in tle.strip().splitlines() if ln.strip()]
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
        geo_lon      = lon - 360.0 if lon > _LONGITUDE_WRAP_DEG else lon
        geo_drift    = _geo_drift_deg_day(sat, epoch)

    # Element Set Number — TLE line 1, columns 65-68 (1-indexed), right-justified
    try:
        esn = int(lines[-2][64:68].strip())
    except (ValueError, IndexError):
        esn = 0

    return TLERecord(
        epoch=epoch, tle="\n".join(lines),
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
    if not attributed or (len(keys) < _MIN_DISTINCT_SOURCES_TO_SPLIT):
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
    if len(manoeuvres) < _MIN_MANOEUVRES_TO_MERGE:
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


#: Name of the inclination element as this module reports it. Held once because
#: it is a map value, a score key and a return value in the same file (S1192).
_ELEMENT_INCLINATION = "inclination"

#: Which orbital element each ΔV channel moves.
_CHANNEL_ELEMENT = {
    "along_track": "altitude",
    "cross_track": _ELEMENT_INCLINATION,
    "radial":      "eccentricity",
}

#: Share of the total ΔV one channel must carry before it is named as the
#: element this manoeuvre moved. Below it the burn moved more than one element,
#: so "mixed" is the honest answer rather than whichever channel was largest.
_DOMINANT_CHANNEL_SHARE = 0.6

#: Floor on the scaled element deltas used by the fallback below. The scaling
#: (km, degrees × 100, eccentricity × 1000) has no physical basis, as the
#: function's docstring says, so this is a screening cut and not a measurement:
#: under it nothing moved far enough to name an element at all.
_ELEMENT_SCORE_FLOOR = 0.5

#: Inclination change in degrees above which the fallback names a plane change
#: outright, provided it also outweighs the altitude change. Same caveat: a
#: screening cut on a path that runs only where no forensic breakdown exists.
_PLANE_CHANGE_INC_DEG = 0.05


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
        if total > 0 and top.dv_km_s / total >= _DOMINANT_CHANNEL_SHARE:
            return _CHANNEL_ELEMENT.get(top.channel, "mixed")
        return "mixed"

    scores = {"altitude": abs(d_alt), _ELEMENT_INCLINATION: abs(d_inc) * 100,
              "eccentricity": abs(d_ecc) * 1000}
    if all(v < _ELEMENT_SCORE_FLOOR for v in scores.values()):
        return "mixed"
    if abs(d_inc) > _PLANE_CHANGE_INC_DEG and abs(d_inc) > abs(d_alt) * 0.1:
        return _ELEMENT_INCLINATION
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

def _drift_direction(rate: float) -> str:
    """EAST, WEST or STATIONARY for a longitude drift rate in degrees a day."""
    if rate > _DRIFT_STATIONARY:
        return "EAST"
    if rate < -_DRIFT_STATIONARY:
        return "WEST"
    return "STATIONARY"


def _drift_phase(start: TLERecord, end: TLERecord, rates: list[float], direction: str) -> DriftPhase | None:
    """One drift phase from *start* to *end*, or ``None`` if under half a day."""
    dur = (end.epoch - start.epoch).total_seconds() / 86400.0
    if dur < 0.5:  # noqa: PLR2004
        return None
    mean_rate = sum(rates) / len(rates)
    return DriftPhase(
        start_epoch=start.epoch, end_epoch=end.epoch,
        direction=direction, rate_deg_day=round(mean_rate, 3),
        start_lon=round(start.geo_longitude_deg or 0.0, 2), end_lon=round(end.geo_longitude_deg or 0.0, 2),
        distance_deg=round(mean_rate * dur, 2), duration_days=round(dur, 1),
        peak_rate=round(max(abs(r) for r in rates), 3),
    )


def _direction_runs(geo_recs: list[TLERecord]) -> list[tuple[TLERecord, TLERecord, list[float], str]]:
    """(start, end, rates, direction) for each run of one drift direction.

    A run ends at the first record of the next, so consecutive phases share
    their boundary record; the last ends at the last record.
    """
    runs: list[tuple[TLERecord, TLERecord, list[float], str]] = []
    start = geo_recs[0]
    rates = [start.geo_drift_rate_deg_day or 0.0]
    direction = _drift_direction(rates[0])
    for rec in geo_recs[1:]:
        rate = rec.geo_drift_rate_deg_day or 0.0
        if _drift_direction(rate) == direction:
            rates.append(rate)
            continue
        runs.append((start, rec, rates, direction))
        start, rates, direction = rec, [rate], _drift_direction(rate)
    runs.append((start, geo_recs[-1], rates, direction))
    return runs


def _compute_drift_phases(records: list[TLERecord]) -> list[DriftPhase]:
    """Detect contiguous periods of East / West / Stationary longitude drift."""
    geo_recs = [r for r in records if r.geo_longitude_deg is not None and r.geo_drift_rate_deg_day is not None]
    if len(geo_recs) < 3:  # noqa: PLR2004
        return []
    phases = (_drift_phase(*run) for run in _direction_runs(geo_recs))
    return [p for p in phases if p is not None]


# ── Public API ────────────────────────────────────────────────────────────────

def _tle_line_pairs(tle_text: str) -> list[tuple[str, str]]:
    """Every line-1 and line-2 pairing in *tle_text*, in the order found.

    A history block interleaves element sets with blank lines and occasional
    stray text, so the scan steps two lines at a time only where a line 1 of
    full width is actually followed by a line 2.
    """
    raw_lines = [ln.rstrip() for ln in tle_text.splitlines()]
    pairs: list[tuple[str, str]] = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index].strip()
        following = raw_lines[index + 1].strip() if index + 1 < len(raw_lines) else ""
        if (
            line.startswith("1 ")
            and len(line) >= _TLE_LINE_COLUMNS
            and following.startswith("2 ")
        ):
            pairs.append((line, following))
            index += 2
            continue
        index += 1
    return pairs


def _record_from_pair(l1: str, l2: str, seen: set[str]) -> TLERecord | None:
    """Parse one pair, or None when it is unusable or a duplicate epoch.

    A history block routinely carries the same element set twice from two
    providers. A malformed pair raises ValueError or ZeroDivisionError, which
    the caller catches and counts so that it drops out rather than stopping
    the parse.
    """
    rec = _satrec_to_record(f"{l1}\n{l2}")
    key = rec.epoch.strftime("%Y%j%H%M%S")
    if key in seen:
        return None
    seen.add(key)
    return rec


def _apply_metadata(
    rec: TLERecord,
    l1: str,
    metadata: dict[str, tuple[str, str]] | None,
    rms_metadata: dict[str, float | None] | None,
) -> bool:
    """Attach the UDL provenance for *l1*, or False when it was unusable.

    Before parse_tle_history was split into helpers this assignment sat inside
    the try that wrapped the whole record, so a metadata value that would not
    unpack into two names dropped that one element set and the history carried
    on. The split moved it out and the same value then ended the entire parse,
    silently, which this module never chose. The catch is back and as broad as
    the one it restores: provenance arriving in an unexpected shape is a reason
    to lose one element set, not a reason to lose the object's whole history.
    """
    try:
        if metadata and l1 in metadata:
            rec.data_mode, rec.source = metadata[l1]
        if rms_metadata and l1 in rms_metadata:
            rec.rms_residual = rms_metadata[l1]
    except Exception:  # noqa: BLE001
        return False
    return True


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
    records, _ = parse_tle_history_counted(tle_text, satno, metadata, rms_metadata)
    return records


def parse_tle_history_counted(
    tle_text: str,
    satno: int | None = None,
    metadata: dict[str, tuple[str, str]] | None = None,
    rms_metadata: dict[str, float | None] | None = None,
) -> tuple[list[TLERecord], int]:
    """As :func:`parse_tle_history`, also returning how many pairs were malformed.

    A corrupt epoch raised ValueError and a zero mean motion ZeroDivisionError
    out of the whole parse, so one bad element set lost the analysis (audit
    F-083). Each now drops out and is counted.
    """
    records: list[TLERecord] = []
    seen: set[str] = set()
    malformed = 0
    for l1, l2 in _tle_line_pairs(tle_text):
        try:
            rec = _record_from_pair(l1, l2, seen)
        except (ValueError, ZeroDivisionError):
            malformed += 1
            continue
        if rec is None:
            continue
        if not _apply_metadata(rec, l1, metadata, rms_metadata):
            continue
        records.append(rec)

    records.sort(key=lambda r: r.epoch)
    return records, malformed


def _screen_pairs(
    records: list[TLERecord],
) -> tuple[list[tuple[TLERecord, TLERecord, float]], list[float], int]:
    """Every usable consecutive pair and its cheap screening ΔV.

    Pairs separated by more than ``_MAX_GAP_DAYS`` are counted and dropped
    rather than measured, because the object could have done anything in
    between and one before/after pair cannot be read as a single burn.
    """
    pairs: list[tuple[TLERecord, TLERecord, float]] = []
    screen_dv: list[float] = []
    skipped_long_gap = 0
    for rp, rc, gap in _build_pairs(records):
        if gap > _MAX_GAP_DAYS:
            skipped_long_gap += 1
            continue
        pairs.append((rp, rc, gap))
        screen_dv.append(_estimate_dv(rp, rc))
    return pairs, screen_dv, skipped_long_gap


def _detect_manoeuvres(
    candidates: list[tuple[TLERecord, TLERecord, float, float]],
    noise: NoiseModel,
) -> list[Manoeuvre]:
    """Re-estimate the screened candidates, in rank order, into detections.

    *candidates* arrives ranked by screening ΔV, so the largest events always
    get the full forensic treatment even when the budget binds. The first
    ``_MAX_FULL_BREAKDOWNS`` can be thrown out by that treatment; past the
    budget the screening figure stands, and the absent breakdown is what says
    so.
    """
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
    return manoeuvres


def _pol_status_for_history(
    latest_epoch: datetime,
    manoeuvres: list[Manoeuvre],
) -> tuple[str, str]:
    """Status of the latest manoeuvre, scored against the ones before it.

    Leave-one-out. Scoring the latest delta-V against statistics that already
    include it caps its z-score at (n - 1) / sqrt(n) (Samuelson's inequality),
    so ANOMALOUS could not happen below 11 manoeuvres and a burn 100 times its
    only predecessor read NORMAL (audit F-026).
    """
    prior = [m.delta_v_km_s for m in manoeuvres[:-1]]
    return _pol_status_and_reason(latest_epoch, manoeuvres, _pol_stats(prior), len(prior))


def _pol_status_and_reason(
    latest_epoch: datetime,
    manoeuvres: list[Manoeuvre],
    prior_stats: PolStats | None,
    n_prior: int = _STATUS_MIN_PRIOR,
) -> tuple[str, str]:
    """The backward-compatible PoL status and the sentence explaining it.

    *prior_stats* describe the manoeuvres before the latest, of which there
    are *n_prior*. *latest_epoch* is the epoch of the last element set in the
    history: a manoeuvre older than ``_STATUS_RECENT_DAYS`` against it is not
    "the latest" and leaves the status at NORMAL, because an object that has
    simply stopped manoeuvring is not an anomaly. A recent manoeuvre with
    fewer than ``_STATUS_MIN_PRIOR`` before it is INSUFFICIENT, not NORMAL:
    there is nothing to measure it against.
    """
    if not manoeuvres:
        return "NORMAL", "No manoeuvres detected — object appears passive."
    age_days = (latest_epoch - manoeuvres[-1].epoch).total_seconds() / 86400.0
    if age_days >= _STATUS_RECENT_DAYS:
        return "NORMAL", "All metrics within normal historical bounds."
    if prior_stats is None or n_prior < _STATUS_MIN_PRIOR:
        return "INSUFFICIENT", (
            f"Only {n_prior} earlier manoeuvre(s); at least {_STATUS_MIN_PRIOR} are needed "
            "to judge whether the latest is unusual."
        )
    last_dv = manoeuvres[-1].delta_v_km_s
    if prior_stats.std > 0:
        z = (last_dv - prior_stats.mean) / prior_stats.std
    else:
        z = math.inf if last_dv > prior_stats.mean else 0.0
    if z > _STATUS_ANOMALOUS_SIGMA:
        return "ANOMALOUS", f"Latest ΔV {last_dv:.4f} km/s is {z:.1f}σ above the earlier mean."
    if z > _STATUS_CAUTION_SIGMA:
        return "CAUTION", (
            f"Latest ΔV {last_dv:.4f} km/s is {z:.1f}σ above the earlier mean — "
            "approaching anomalous threshold."
        )
    return "NORMAL", "All metrics within normal historical bounds."


def _burn_epoch_of(m: Manoeuvre) -> datetime:
    return m.burn_epoch


def _burn_intervals(manoeuvres: list[Manoeuvre], burn_time: Any) -> list[float]:
    """Days between successive burns, in burn order."""
    times = sorted(burn_time(m) for m in manoeuvres)
    return [(b - a).total_seconds() / 86400.0 for a, b in itertools.pairwise(times)]


def _next_manoeuvre(
    manoeuvres: list[Manoeuvre], burn_time: Any = _burn_epoch_of,
) -> tuple[str | None, float | None]:
    """Predicted next burn and the half-width (days) of its 95% interval.

    The band is a prediction interval for the next interval between burns,
    t(0.975, n-1) x s x sqrt(1 + 1/n). It was 2 s, which with three intervals
    understates a 95% band by more than half (t = 4.30), and was timed on the
    after-element-set epochs rather than the burns (audit F-094). None below
    _MIN_INTERVALS_FOR_PREDICTION intervals.
    """
    intervals = _burn_intervals(manoeuvres, burn_time)
    stats_ = _pol_stats(intervals)
    if stats_ is None or stats_.n < _MIN_INTERVALS_FOR_PREDICTION:
        return None, None
    last = max(burn_time(m) for m in manoeuvres)
    pred = last + timedelta(days=stats_.mean)
    t_factor = float(student_t.ppf(0.975, stats_.n - 1))
    return pred.strftime("%Y-%m-%d %H:%M UTC"), round(t_factor * stats_.std * math.sqrt(1.0 + 1.0 / stats_.n), 1)


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

    pairs, screen_dv, skipped_long_gap = _screen_pairs(records)

    noise = calibrate_noise(screen_dv)
    # The operator's threshold and the measured floor are both lower bounds;
    # whichever is higher governs. Asking for 1 m/s on an object whose fits
    # disagree by 4 m/s does not make 1 m/s detectable.
    effective_threshold = max(dv_threshold, noise.floor_km_s)

    screened_pairs = [(rp, rc, gap, dv)
                      for (rp, rc, gap), dv in zip(pairs, screen_dv, strict=True)
                      if dv >= effective_threshold]
    # Rank by screening ΔV so the largest events always get the full forensic
    # treatment even when the budget binds.
    screened_pairs.sort(key=lambda c: c[3], reverse=True)
    rejected_below_floor = len(pairs) - len(screened_pairs)
    # This used to be called `candidates`, and so did the candidate-TIER
    # manoeuvre list two dozen lines below. Reading the counter after the
    # rebind made it the number of low-confidence manoeuvres minus the budget,
    # which is negative in every realistic case and so reported zero however
    # many detections were actually truncated. Capturing it early fixed the
    # count; the two names are now distinct, which is what stops it recurring.
    pairs_over_forensic_budget = max(0, len(screened_pairs) - _MAX_FULL_BREAKDOWNS)

    detected = _detect_manoeuvres(screened_pairs, noise)

    rejected_on_evidence = len(screened_pairs[:_MAX_FULL_BREAKDOWNS]) - sum(
        1 for m in detected if m.breakdown is not None
    )

    # One burn seen by two providers is one burn.
    gaps_seen = sorted(g for _, _, g in pairs)
    median_gap = gaps_seen[len(gaps_seen) // 2] if gaps_seen else 0.0
    detections, merged_duplicates = _merge_duplicate_detections(
        detected, max(_MERGE_WINDOW_FLOOR_DAYS, median_gap),
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

    dv_stats       = _pol_stats(dv_vals)
    interval_stats = _pol_stats(_burn_intervals(manoeuvres, _burn_epoch_of))
    next_est, next_unc = _next_manoeuvre(manoeuvres, _burn_epoch_of)

    # PoL status
    pol_status, pol_reason = _pol_status_for_history(records[-1].epoch, manoeuvres)

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
