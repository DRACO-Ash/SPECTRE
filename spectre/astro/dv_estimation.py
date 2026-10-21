"""Auditable ΔV estimation from pairs of mean element sets.

Why this module exists
----------------------
Pattern of Life originally estimated ΔV by propagating the *before* element
set to the *after* epoch and differencing the two velocity vectors. That
measures how far apart two trajectories have drifted, not how much ΔV
separated them, and the difference between those two quantities is enormous.

The velocity difference between two near-identical orbits is dominated by
along-track **phase**, which carries no ΔV information at all. Measured on a
550 km LEO orbit (v ≈ 7.6 km/s), two element sets describing the *same* orbit
at the *same* epoch and differing only in mean anomaly report:

===================  ====================  ===================
Phase disagreement   As along-track time   Reported ΔV
===================  ====================  ===================
0.001°               0.02 s                0.13 m/s
0.01°                0.16 s                1.33 m/s
0.1°                 1.6 s                 13.3 m/s
1.0°                 16 s                  133 m/s
5.0°                 80 s                  663 m/s
30°                  478 s                 3936 m/s
===================  ====================  ===================

True ΔV in every row of that table is zero. Worse, a real burn also changes
mean motion, so the phase error *accumulates with the gap*: a genuine 6.95 m/s
tangential burn that raises SMA by 12.66 km reads as 408 m/s across a 0.2 day
gap and 2015 m/s across a one day gap. The method is only correct when the two
element sets are compared at the instant of the burn, which never happens in
practice.

What replaces it
----------------
Two estimators, neither of which reads phase as ΔV.

The headline figure is **epoch-swept propagation**. Velocity differencing is
exact at the instant of the burn and only then, so instead of abandoning it,
the gap is searched for the epoch at which the two trajectories actually
coincide and the velocities are differenced there. Measured against known
synthetic burns it is accurate to better than 0.1% and, unlike the original,
its error does not grow with the gap. It also dates the manoeuvre, which the
detection loop previously assumed to be the after-epoch.

The second is **mean element differencing**, and it is what decomposes the
figure per variable. Phase (mean anomaly) is never read, so the estimate
is structurally immune to the failure above. Three orthogonal channels, each
inverted from Gauss's variational equations for a single impulse on a
near-circular orbit:

● **Along-track** — drives semi-major axis.   Δv = μ·Δa / (2·a²·v_perigee)
  Which is the familiar n·Δa/2 when the orbit is circular. First order in Δa/a, and it over-reports as that ratio grows: against the
  exact two-burn Hohmann total it is +1.1% at Δa/a = 0.015 (100 km in LEO),
  +5.5% at 0.073, and +10.9% at 0.145. The epoch-swept estimator tracks the
  Hohmann total to better than 0.4% across the same range, which is why it is
  the headline and this is the decomposition.
● **Radial** — drives the eccentricity vector. Δe = Δv/v   ⟹  Δv = v·Δe
  The part a tangential burn already explains is removed in quadrature, since
  a tangential burn moves the eccentricity vector along the apsidal line and a
  radial one rotates it.
● **Cross-track** — drives the orbit plane.    Δv = 2·v·sin(θ/2)

Secular J2 drift in RAAN and argument of perigee is removed before
differencing, so natural precession is not read as a plane change.

A second, independent estimator cross-checks the first. Velocity differencing
is exact at the instant of the burn and only then, so rather than abandoning
it, this searches the gap for the epoch at which the two trajectories actually
coincide and differences the velocities there. It shares no algebra with the
Gauss inversion — numerical SGP4 on both sides — so agreement between them is
real corroboration. It also dates the burn, which element differencing cannot.

Every intermediate value is retained on the returned objects. An operator who
does not believe a ΔV figure can read the element set that produced it, every
term in the sum, and the provenance of both fits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol

from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH

__all__ = [
    "DvBreakdown",
    "DvComponent",
    "DvEstimate",
    "NoiseModel",
    "StateSnapshot",
    "build_breakdown",
    "calibrate_noise",
    "estimate_dv_mean_elements",
    "snapshot_from_record",
    "secular_rates_deg_day",
    "estimate_dv_epoch_swept",
]


# ── Confidence bands ──────────────────────────────────────────────────────────

#: Both estimators must agree within this ratio for HIGH confidence.
_AGREEMENT_HIGH = 1.5
#: Beyond this ratio the two methods are telling different stories.
_AGREEMENT_POOR = 3.0

#: Signal-to-noise below this is indistinguishable from fit scatter.
_SNR_REJECT = 3.0
_SNR_LOW    = 5.0
_SNR_HIGH   = 10.0

#: Absolute floor on the empirical noise estimate (km/s). No real platform
#: manoeuvres below this and no element set resolves it, so a detection under
#: this figure is never reported however quiet the object's own history is.
_NOISE_ABSOLUTE_FLOOR_KM_S = 1.0e-4   # 0.1 m/s

#: Scale factor on the robust spread when setting the reporting floor.
_NOISE_SIGMA_MULTIPLIER = 5.0

#: Above this the measured "floor" is not fit scatter (km/s).
#:
#: Median and MAD are robust only while manoeuvres are a minority. Once more
#: than half the pairs contain a burn the median IS a burn, and the floor
#: climbs above the very events it exists to find: measured on a synthetic
#: catalogue, 50% contamination at 50 m/s produced a floor of 149 m/s and 60%
#: produced exactly 50 m/s, rejecting every detection. Two good element set
#: fits of one object agree to about a kilometre in semi-major axis, which is
#: well under a metre per second; even two providers 6 km apart disagree by
#: about 3.5 m/s. A floor of 50 m/s cannot be scatter.
_NOISE_IMPLAUSIBLE_CEILING_KM_S = 0.050

#: A single impulse leaves the two orbits sharing a point, so the epoch-swept
#: estimate is only a ΔV measurement where the two trajectories actually come
#: together. Two exceptions are expected and benign: a pure energy change
#: leaves concentric orbits |Δa| apart, and a plane change separates them by
#: roughly r·θ. The headline falls back to element differencing when the
#: measured mismatch exceeds this multiple of that expectation.
_SWEPT_MISS_TOLERANCE = 3.0
#: ...with a floor so that a sub-kilometre expectation does not reject a fit
#: that is well inside element set accuracy anyway. Taken as a fraction of the
#: semi-major axis rather than a fixed distance, which makes it one angular
#: tolerance (about 0.017° of along-track phase) at every altitude: ~2.1 km at
#: 550 km, ~12.6 km at GEO. A fixed 10 km floor was both far too loose in LEO,
#: where it admitted six-minute pairs whose fits disagreed by 8 km while the
#: orbit itself had moved 0.05 km, and arbitrary everywhere else.
_SWEPT_MISS_FLOOR_FRACTION = 3.0e-4


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StateSnapshot:
    """One element set, flattened for display beside its partner.

    Every field an operator needs to judge whether a ΔV figure is real, in one
    place: the orbit itself, the derived quantities the estimator used, and
    where the fit came from.
    """

    epoch:              datetime
    sma_km:             float
    alt_km:             float
    ecc:                float
    inc_deg:            float
    raan_deg:           float
    argp_deg:           float
    mean_anomaly_deg:   float
    mean_motion_revday: float
    period_min:         float
    bstar:              float

    #: Circular-equivalent orbital speed at this SMA (km/s). The scale factor
    #: that turns dimensionless element changes into ΔV.
    orbital_speed_km_s: float
    #: Mean motion in rad/s. Turns a Δa in km into a ΔV in km/s.
    mean_motion_rad_s:  float

    # Provenance. A before/after pair from two different sources is the most
    # common cause of a ΔV that looks real and is not.
    source:         str = ""
    data_mode:      str = ""
    rms_residual:   float | None = None
    element_set_no: int = 0

    @property
    def provenance_label(self) -> str:
        parts = [p for p in (self.source, self.data_mode) if p]
        if self.element_set_no:
            parts.append(f"set {self.element_set_no}")
        return " · ".join(parts) if parts else "unattributed"


@dataclass(frozen=True)
class DvComponent:
    """One orthogonal channel of the ΔV estimate, with its full working.

    ``inputs`` holds every number that entered the calculation, keyed by the
    symbol used in ``formula``. The operator can recompute the component by
    hand from this dictionary alone.
    """

    channel:    str              # "along_track" | "radial" | "cross_track"
    label:      str              # operator-facing name
    dv_km_s:    float
    driver:     str              # the orbital element this channel moves
    formula:    str              # the relation applied
    inputs:     dict[str, float] = field(default_factory=dict)
    note:       str = ""

    @property
    def dv_m_s(self) -> float:
        return self.dv_km_s * 1000.0


@dataclass(frozen=True)
class DvEstimate:
    """A total ΔV from one method, with its components and its caveats."""

    method:      str                       # machine name
    label:       str                       # operator-facing name
    dv_km_s:     float
    components:  tuple[DvComponent, ...] = ()
    notes:       tuple[str, ...] = ()
    failed:      bool = False
    failure_reason: str = ""
    #: When the manoeuvre actually happened, measured rather than assumed.
    #: Populated by the epoch-swept estimator; None for the Gauss inversion,
    #: which compares elements and so cannot date the burn.
    burn_epoch: datetime | None = None
    #: True when many instants across the gap fit equally well, so the burn
    #: time is indicative rather than measured.
    burn_epoch_ambiguous: bool = False
    #: How close the two fits come at that instant (km). A real manoeuvre pair
    #: nearly coincides; a large mismatch means they never describe one object
    #: at one place, so the velocity difference is not an impulse.
    position_mismatch_km: float | None = None

    @property
    def dv_m_s(self) -> float:
        return self.dv_km_s * 1000.0


@dataclass(frozen=True)
class NoiseModel:
    """Reporting floor calibrated from the object's own element set history.

    A fixed threshold cannot work. The scatter between successive fits depends
    on the object, the regime, the sensor mix, and how many organisations
    contribute to the catalogue. This measures it instead, from the whole
    distribution of consecutive-pair ΔV estimates.

    The statistic is the median plus five median absolute deviations. Both are
    robust: a minority of samples being real burns moves neither, however large
    those burns are, so an object's own manoeuvres cannot inflate the threshold
    meant to find them.

    The floor decides what is *reported*. What is *confirmed* is decided on
    evidence instead, by :func:`_judge`, because no quantile of this
    distribution works across catalogues: its tail is far heavier than any
    parametric fit to its core predicts, and on a sparse catalogue a high
    quantile is simply set by the object's own largest burn. Measured over four
    simulated catalogues, a 99.9th-percentile confirmation level missed every
    one of six known burns on the sparsest of them, while agreement between two
    independent estimators caught them with no false confirmations at all.
    """

    median_km_s:    float
    mad_km_s:       float
    floor_km_s:     float
    samples:        int
    method:         str = "median + 5·MAD"
    #: False when the robust statistics could not produce a usable floor and
    #: the absolute floor stood in. Nothing downstream should present an
    #: unmeasured floor as a measurement.
    floor_is_measured: bool = True

    def snr(self, dv_km_s: float) -> float | None:
        """Signal-to-noise of *dv_km_s* against the measured background."""
        if self.mad_km_s <= 0.0:
            return None
        return (dv_km_s - self.median_km_s) / self.mad_km_s

    @property
    def median_m_s(self) -> float:
        return self.median_km_s * 1000.0

    @property
    def mad_m_s(self) -> float:
        return self.mad_km_s * 1000.0

    @property
    def floor_m_s(self) -> float:
        return self.floor_km_s * 1000.0


@dataclass(frozen=True)
class DvBreakdown:
    """Everything behind a single ΔV figure.

    This is the answer to "why does it say that": the headline number and the
    two estimates that produced it, every term in the element decomposition,
    the element sets on each side with their provenance, the measured noise
    floor, and a verdict on whether the figure should be believed.
    """

    #: The headline. Epoch-swept where it succeeded, element differencing
    #: otherwise. ``headline_method`` says which.
    dv_km_s:        float
    headline_method: str

    swept:    DvEstimate   # epoch-swept propagation — the total, and the burn date
    elements: DvEstimate   # mean element differencing — the per-variable breakdown
    legacy:   DvEstimate   # the original method, for comparison only

    before:   StateSnapshot
    after:    StateSnapshot
    gap_days: float

    agreement_ratio: float | None
    snr:             float | None
    noise:           NoiseModel | None
    confidence:      str          # "HIGH" | "MODERATE" | "LOW" | "REJECT"
    confidence_reason: str
    warnings:        tuple[str, ...] = ()

    @property
    def dv_m_s(self) -> float:
        return self.dv_km_s * 1000.0

    @property
    def components(self) -> tuple[DvComponent, ...]:
        """Per-channel ΔV terms, from the element decomposition."""
        return self.elements.components

    @property
    def burn_epoch(self) -> datetime | None:
        """Measured instant of the burn, or None where it could not be dated."""
        return self.swept.burn_epoch

    @property
    def estimates(self) -> tuple[DvEstimate, ...]:
        """All three estimates, in the order an operator should read them."""
        return (self.swept, self.elements, self.legacy)

    @property
    def cross_source(self) -> bool:
        """True when the two fits came from different catalogue sources."""
        a, b = self.before.source.strip(), self.after.source.strip()
        return bool(a and b and a != b)

    @property
    def believable(self) -> bool:
        """True unless the evidence says this is not a manoeuvre."""
        return self.confidence != "REJECT"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _j2_raan_rate_deg_day(sma_km: float, ecc: float, inc_deg: float) -> float:
    """Secular RAAN precession from J2 (°/day). Negative for prograde orbits."""
    n = math.sqrt(MU_EARTH / sma_km ** 3)
    d = (1.0 - ecc ** 2) ** 2
    rate = -1.5 * n * J2_EARTH * (R_EARTH / sma_km) ** 2 * math.cos(math.radians(inc_deg)) / d
    return math.degrees(rate) * 86400.0


def _j2_argp_rate_deg_day(sma_km: float, ecc: float, inc_deg: float) -> float:
    """Secular argument-of-perigee rotation from J2 (°/day).

    0.75·n·J2·(Re/p)²·(5cos²i − 1). Written in sin² that is
    0.75·(4 − 5sin²i) = 3 − 3.75sin²i. The form that used to sit here,
    1.5·(2.5sin²i − 2) = 3.75sin²i − 3, is the exact NEGATIVE of it, so the
    correction added the natural perigee rotation instead of removing it and
    doubled it. On a 550 km, 53° orbit the rate is +3.10°/day, not −3.10.

    The blast radius was limited because :func:`secular_rates_deg_day` prefers
    SGP4's own ``argpdot`` wherever an element set is available and only falls
    back to this. "Limited" is not "none": the fallback runs whenever a TLE
    cannot be parsed, and ``pattern_of_life`` used the same inverted form for
    the perigee delta it shows the operator.
    """
    n = math.sqrt(MU_EARTH / sma_km ** 3)
    d = (1.0 - ecc ** 2) ** 2
    rate = (0.75 * n * J2_EARTH * (R_EARTH / sma_km) ** 2
            * (5.0 * math.cos(math.radians(inc_deg)) ** 2 - 1.0) / d)
    return math.degrees(rate) * 86400.0


def secular_rates_deg_day(tle: str, sma_km: float, ecc: float,
                          inc_deg: float) -> tuple[float, float]:
    """Secular RAAN and argument-of-perigee rates (°/day) for one element set.

    Read from SGP4's own initialised ``Satrec`` wherever the element set is
    available, because that is the drift the catalogue's own fits were produced
    against. The closed-form J2 rates above differ from it by enough to matter:
    on a 550 km orbit the mismatch puts 38 m/s of phantom plane change on a
    15 day gap, which is five times a real station-keeping burn.

    Falls back to the analytic rates when no element set is to hand.
    """
    try:
        from sgp4.api import Satrec
        lines = [ln.strip() for ln in tle.strip().splitlines() if ln.strip()]
        s = Satrec.twoline2rv(lines[-2], lines[-1])
        return (math.degrees(s.nodedot) * 1440.0, math.degrees(s.argpdot) * 1440.0)
    except Exception:  # noqa: BLE001 — any parse failure falls back to the closed form
        return (_j2_raan_rate_deg_day(sma_km, ecc, inc_deg),
                _j2_argp_rate_deg_day(sma_km, ecc, inc_deg))


def _plane_separation_rad(i1_deg: float, raan1_deg: float,
                          i2_deg: float, raan2_deg: float) -> float:
    """Angle between two orbit normals (radians).

    Spherical trigonometry on the two poles. Correct for any inclination pair
    and any node separation, unlike the small-angle sum-of-squares shortcut,
    which understates large plane changes and fails outright near the poles.
    """
    i1, i2 = math.radians(i1_deg), math.radians(i2_deg)
    d_raan = math.radians(_wrap180(raan2_deg - raan1_deg))
    # Unit normals in ECI.
    n1 = (math.sin(i1) * math.sin(0.0), -math.sin(i1) * math.cos(0.0), math.cos(i1))
    n2 = (math.sin(i2) * math.sin(d_raan), -math.sin(i2) * math.cos(d_raan), math.cos(i2))
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(n1, n2, strict=True))))
    return math.acos(dot)


# ── Snapshot construction ─────────────────────────────────────────────────────

class _RecordLike(Protocol):
    """The shape of a ``TLERecord``, taken structurally.

    Declared here rather than imported so this module stays importable from
    ``pattern_of_life`` without a circular import.
    """

    epoch:              datetime
    tle:                str
    sma_km:             float
    ecc:                float
    inc_deg:            float
    raan_deg:           float
    argp_deg:           float
    mean_anomaly_deg:   float
    mean_motion_revday: float
    bstar:              float
    alt_km:             float
    period_min:         float
    data_mode:          str
    source:             str
    rms_residual:       float | None
    element_set_no:     int


def snapshot_from_record(rec: _RecordLike) -> StateSnapshot:
    """Flatten a :class:`~spectre.astro.pattern_of_life.TLERecord` for display."""
    sma = float(rec.sma_km)
    return StateSnapshot(
        epoch              = rec.epoch,
        sma_km             = sma,
        alt_km             = float(rec.alt_km),
        ecc                = float(rec.ecc),
        inc_deg            = float(rec.inc_deg),
        raan_deg           = float(rec.raan_deg),
        argp_deg           = float(rec.argp_deg),
        mean_anomaly_deg   = float(rec.mean_anomaly_deg),
        mean_motion_revday = float(rec.mean_motion_revday),
        period_min         = float(rec.period_min),
        bstar              = float(getattr(rec, "bstar", 0.0) or 0.0),
        orbital_speed_km_s = math.sqrt(MU_EARTH / sma),
        mean_motion_rad_s  = math.sqrt(MU_EARTH / sma ** 3),
        source             = str(getattr(rec, "source", "") or ""),
        data_mode          = str(getattr(rec, "data_mode", "") or ""),
        rms_residual       = getattr(rec, "rms_residual", None),
        element_set_no     = int(getattr(rec, "element_set_no", 0) or 0),
    )


# ── Estimator 1: mean element differencing (Gauss inversion) ──────────────────

def estimate_dv_mean_elements(before: StateSnapshot, after: StateSnapshot,
                              gap_days: float,
                              raan_rate_deg_day: float | None = None,
                              argp_rate_deg_day: float | None = None) -> DvEstimate:
    """ΔV from the change in mean elements, decomposed per channel.

    Mean anomaly is deliberately not read. Secular drift is removed from RAAN
    and argument of perigee over *gap_days* before differencing, so natural
    precession does not register as a plane change. Pass the rates from
    :func:`secular_rates_deg_day` where the element set is available; the
    closed-form J2 rates are only a fallback.

    The three channels are orthogonal impulse directions, so the total is their
    root-sum-square, not their sum.
    """
    notes: list[str] = []

    # Reference scale. Taken from the before-state: the burn acts on that orbit.
    v = before.orbital_speed_km_s
    n = before.mean_motion_rad_s

    # ── Channel 1: along-track. Moves semi-major axis. ───────────────────────
    #
    # Δv = μ·Δa / (2·a²·v_burn). With v_burn the circular speed this collapses
    # to the familiar n·Δa/2, which is why that form is quoted for near-circular
    # orbits. It is only valid there: an eccentric orbit is cheapest to raise at
    # perigee, where the speed is highest, and assuming circular speed
    # over-reports the cost by 36% at e = 0.3 and 139% at e = 0.7. GTO and
    # Molniya objects sit squarely in that range.
    d_sma = after.sma_km - before.sma_km
    r_peri = before.sma_km * (1.0 - before.ecc)
    if r_peri > 0:
        v_peri = math.sqrt(MU_EARTH * (2.0 / r_peri - 1.0 / before.sma_km))
    else:
        v_peri = before.orbital_speed_km_s
    dv_along = (abs(MU_EARTH * d_sma / (2.0 * before.sma_km ** 2 * v_peri))
                if v_peri > 0 else 0.0)
    # First order in Δa/a. Over-reports the exact two-burn Hohmann total by
    # about 1% at Δa/a = 0.015 and 11% at 0.145, so the note says so once the
    # ratio is large enough to matter rather than leaving the operator to
    # discover it from the disagreement with the headline.
    ratio = abs(d_sma) / before.sma_km if before.sma_km > 0 else 0.0
    along_note = ("Prograde" if d_sma > 0 else "Retrograde") if d_sma else "No energy change"
    if ratio > 0.01:
        along_note += (f". Δa is {ratio * 100:.1f}% of the semi-major axis, where this "
                       "first-order relation over-reports the exact two-burn total by "
                       f"roughly {ratio * 75:.0f}%.")
    c_along = DvComponent(
        channel  = "along_track",
        label    = "Along-track (energy)",
        dv_km_s  = dv_along,
        driver   = "semi-major axis",
        formula  = "Δv = μ · Δa / (2 · a² · v_perigee)",
        inputs   = {
            "a_before_km":     before.sma_km,
            "a_after_km":      after.sma_km,
            "delta_a_km":      d_sma,
            "e_before":        before.ecc,
            "r_perigee_km":    r_peri,
            "v_perigee_km_s":  v_peri,
            "n_rad_s":         n,
        },
        note = along_note,
    )

    # ── Channel 2: radial. Moves the eccentricity vector. ────────────────────
    # J2 rotates argument of perigee secularly; remove it before differencing.
    argp_rate = (argp_rate_deg_day if argp_rate_deg_day is not None
                 else _j2_argp_rate_deg_day(before.sma_km, before.ecc, before.inc_deg))
    argp_j2_deg = argp_rate * gap_days
    argp_after_corr = after.argp_deg - argp_j2_deg

    e1x = before.ecc * math.cos(math.radians(before.argp_deg))
    e1y = before.ecc * math.sin(math.radians(before.argp_deg))
    e2x = after.ecc * math.cos(math.radians(argp_after_corr))
    e2y = after.ecc * math.sin(math.radians(argp_after_corr))
    d_evec = math.hypot(e2x - e1x, e2y - e1y)

    # A single tangential impulse of dv_along already changes eccentricity by
    # 2·dv_along/v, so removing that stops one burn being counted in two
    # channels. The removal is in QUADRATURE, not linear: a tangential burn
    # moves the eccentricity vector along the apsidal line while a radial burn
    # rotates it, so the two contributions are close to orthogonal. Subtracting
    # the magnitudes linearly under-reports the radial part of any mixed burn.
    d_e_explained = 2.0 * dv_along / v if v > 0 else 0.0
    d_e_residual  = math.sqrt(max(0.0, d_evec ** 2 - d_e_explained ** 2))
    dv_radial = v * d_e_residual
    c_radial = DvComponent(
        channel  = "radial",
        label    = "Radial (shape)",
        dv_km_s  = dv_radial,
        driver   = "eccentricity vector",
        formula  = "Δv = v · √(|Δe⃗|² − (2·Δv_along/v)²)",
        inputs   = {
            "e_before":            before.ecc,
            "e_after":             after.ecc,
            "argp_before_deg":     before.argp_deg,
            "argp_after_deg":      after.argp_deg,
            "argp_rate_deg_day":   argp_rate,
            "argp_j2_drift_deg":   argp_j2_deg,
            "argp_after_corr_deg": argp_after_corr,
            "delta_e_vector":      d_evec,
            "delta_e_explained":   d_e_explained,
            "delta_e_residual":    d_e_residual,
            "v_km_s":              v,
        },
        note = ("Eccentricity change fully explained by the along-track burn"
                if d_e_residual <= 0.0 else "Residual shape change beyond the energy burn"),
    )

    # ── Channel 3: cross-track. Moves the orbit plane. ───────────────────────
    raan_rate = (raan_rate_deg_day if raan_rate_deg_day is not None
                 else _j2_raan_rate_deg_day(before.sma_km, before.ecc, before.inc_deg))
    raan_j2_deg = raan_rate * gap_days
    raan_after_corr = after.raan_deg - raan_j2_deg

    theta = _plane_separation_rad(before.inc_deg, before.raan_deg,
                                  after.inc_deg, raan_after_corr)
    dv_cross = 2.0 * v * math.sin(theta / 2.0)
    c_cross = DvComponent(
        channel  = "cross_track",
        label    = "Cross-track (plane)",
        dv_km_s  = dv_cross,
        driver   = "inclination and RAAN",
        formula  = "Δv = 2 · v · sin(θ/2)",
        inputs   = {
            "inc_before_deg":      before.inc_deg,
            "inc_after_deg":       after.inc_deg,
            "delta_inc_deg":       _wrap180(after.inc_deg - before.inc_deg),
            "raan_before_deg":     before.raan_deg,
            "raan_after_deg":      after.raan_deg,
            "raan_rate_deg_day":   raan_rate,
            "raan_j2_drift_deg":   raan_j2_deg,
            "raan_after_corr_deg": raan_after_corr,
            "plane_angle_deg":     math.degrees(theta),
            "v_km_s":              v,
        },
        note = "Secular node drift removed before differencing",
    )

    total = math.sqrt(dv_along ** 2 + dv_radial ** 2 + dv_cross ** 2)

    if gap_days <= 0.0:
        notes.append("Zero or negative epoch gap: the drift corrections are nil, so "
                     "any node or perigee difference is read as a manoeuvre.")
    if abs(raan_j2_deg) > 1.0:
        notes.append(f"Removed {raan_j2_deg:+.3f}° of natural node drift over "
                     f"{gap_days:.3f} days before differencing.")

    return DvEstimate(
        method     = "mean_element",
        label      = "Mean element differencing",
        dv_km_s    = total,
        components = (c_along, c_radial, c_cross),
        notes      = tuple(notes),
    )


# ── Estimator 2: epoch-swept propagation (independent cross-check) ───────────

def estimate_dv_epoch_swept(
    before_tle: str, after_tle: str,
    t_before: datetime, t_after: datetime,
    coarse_steps: int = 64, refine_steps: int = 24,
) -> DvEstimate:
    """Find the instant inside the gap at which the two trajectories coincide.

    Velocity differencing is exact at the moment of the burn and only then: at
    that instant the two element sets describe the same point in space and
    differ by precisely the impulse. The original estimator evaluated it at the
    *after* epoch instead, where the trajectories have had the whole gap to
    diverge in phase. This searches the gap for the epoch of closest approach
    and reports the velocity difference there.

    It shares no algebra with :func:`estimate_dv_mean_elements` — full
    numerical SGP4 on both sides, no Gauss inversion, no small-angle
    assumption — so agreement between the two is real corroboration.

    As a by-product it dates the manoeuvre. The detection loop stamps events at
    the after-epoch, which can be wrong by the whole gap; ``burn_epoch`` on the
    returned estimate is the measured answer.
    """
    try:
        from spectre.astro.propagator import TLEOrbit
        orb_a = TLEOrbit(before_tle)
        orb_b = TLEOrbit(after_tle)
    except Exception as exc:  # noqa: BLE001 — a malformed element set is reportable
        return DvEstimate(
            method="epoch_swept", label="Epoch-swept propagation",
            dv_km_s=0.0, failed=True,
            failure_reason=f"Could not build propagator: {type(exc).__name__}: {exc}",
        )

    span_s = (t_after - t_before).total_seconds()
    if span_s <= 0.0:
        span_s = 0.0

    def _probe(frac: float) -> tuple[float, float] | None:
        """(position mismatch km, velocity difference km/s) at this point in the gap."""
        t = t_before + timedelta(seconds=span_s * frac)
        try:
            sa = orb_a.propagate(t)
            sb = orb_b.propagate(t)
        except Exception:  # noqa: BLE001 — SGP4 can diverge; that sample is simply unusable
            return None
        dr = math.sqrt(sum((float(y) - float(x)) ** 2 for x, y in zip(sa.r, sb.r, strict=True)))
        dv = math.sqrt(sum((float(y) - float(x)) ** 2 for x, y in zip(sa.v, sb.v, strict=True)))
        return dr, dv

    best_frac = 0.0
    best_dr = float("inf")
    best_dv = 0.0
    coarse: list[tuple[float, float, float]] = []   # (frac, dr, dv)
    for k in range(coarse_steps + 1):
        got = _probe(k / coarse_steps)
        if got is None:
            continue
        dr, dv = got
        coarse.append((k / coarse_steps, dr, dv))
        if dr < best_dr:
            best_dr, best_dv, best_frac = dr, dv, k / coarse_steps
    sampled = len(coarse)

    if sampled == 0:
        return DvEstimate(
            method="epoch_swept", label="Epoch-swept propagation",
            dv_km_s=0.0, failed=True,
            failure_reason="SGP4 failed at every sample across the gap.",
        )

    # Golden-section refine around the coarse minimum.
    half = 1.0 / coarse_steps
    lo, hi = max(0.0, best_frac - half), min(1.0, best_frac + half)
    for _ in range(refine_steps):
        if hi - lo < 1e-9:
            break
        m1, m2 = lo + (hi - lo) / 3.0, hi - (hi - lo) / 3.0
        p1, p2 = _probe(m1), _probe(m2)
        if p1 is None or p2 is None:
            break
        if p1[0] <= p2[0]:
            hi = m2
            if p1[0] < best_dr:
                best_dr, best_dv, best_frac = p1[0], p1[1], m1
        else:
            lo = m1
            if p2[0] < best_dr:
                best_dr, best_dv, best_frac = p2[0], p2[1], m2

    # A burn that only changes the orbit plane leaves the two trajectories
    # crossing at every node passage, so many instants look equally close and
    # the date is only good to a fraction of an orbit. Say so rather than
    # presenting an arbitrary pick as a measurement.
    comparable = sum(1 for _, dr, _ in coarse if dr <= max(best_dr * 2.0, best_dr + 1.0))
    ambiguous = comparable > max(3, sampled // 8)

    burn_epoch = t_before + timedelta(seconds=span_s * best_frac)
    notes = [
        f"Trajectories are closest {best_frac * 100:.0f}% of the way through the gap, "
        f"at {burn_epoch.strftime('%Y-%m-%d %H:%M:%S')} UTC.",
        f"Closest approach between the two fits: {best_dr:.3f} km.",
    ]
    if ambiguous:
        notes.append(f"{comparable} instants across the gap are equally close, so the "
                     "burn time is indicative only. Typical of a plane change, where "
                     "the orbits cross at every node passage.")
    if best_dr > 50.0:
        notes.append("The two element sets never come close together inside the gap. "
                     "They may not describe the same object, or the gap may not "
                     "contain the manoeuvre.")
    return DvEstimate(
        method="epoch_swept",
        label="Epoch-swept propagation",
        dv_km_s=best_dv,
        notes=tuple(notes),
        burn_epoch=burn_epoch,
        burn_epoch_ambiguous=ambiguous,
        position_mismatch_km=best_dr,
    )


# ── Estimator 3: the legacy propagation difference, kept for comparison ───────

def estimate_dv_propagation(before_tle: str, after_tle: str,
                            at_epoch: datetime) -> DvEstimate:
    """The original method: propagate both element sets to a common epoch.

    Retained only so the operator can see what the old figure was and why it
    differs. It is contaminated by along-track phase in proportion to the epoch
    gap and must never be the primary number. See this module's docstring for
    the measured scale of the contamination.
    """
    try:
        from spectre.astro.propagator import TLEOrbit
        sv_a = TLEOrbit(before_tle).propagate(at_epoch)
        sv_b = TLEOrbit(after_tle).propagate(at_epoch)
        dv = math.sqrt(sum((float(b) - float(a)) ** 2
                           for a, b in zip(sv_a.v, sv_b.v, strict=True)))
    except Exception as exc:  # noqa: BLE001 — any propagation failure is reportable
        return DvEstimate(
            method = "propagation_difference", label = "Propagation difference (legacy)",
            dv_km_s = 0.0, failed = True, failure_reason = f"{type(exc).__name__}: {exc}",
        )
    return DvEstimate(
        method  = "propagation_difference",
        label   = "Propagation difference (legacy)",
        dv_km_s = dv,
        notes   = ("Dominated by along-track phase; grows with the epoch gap "
                   "whether or not a manoeuvre occurred. Comparison only.",),
    )


# ── Noise calibration ─────────────────────────────────────────────────────────

def calibrate_noise(dv_samples: list[float]) -> NoiseModel:
    """Measure the reporting floor from the object's own per-step ΔV estimates.

    *dv_samples* is every consecutive-pair ΔV in km/s, manoeuvres included.
    Median and median absolute deviation are used because a minority of real
    burns cannot move either.
    """
    n = len(dv_samples)
    if n < 4:
        return NoiseModel(
            median_km_s=0.0, mad_km_s=0.0,
            floor_km_s=_NOISE_ABSOLUTE_FLOOR_KM_S,
            samples=n, method="insufficient samples — absolute floor",
        )

    ordered = sorted(dv_samples)

    def _median(xs: list[float]) -> float:
        m = len(xs)
        mid = m // 2
        return xs[mid] if m % 2 else (xs[mid - 1] + xs[mid]) / 2.0

    med = _median(ordered)
    mad = _median(sorted(abs(x - med) for x in dv_samples))
    floor = max(med + _NOISE_SIGMA_MULTIPLIER * mad, _NOISE_ABSOLUTE_FLOOR_KM_S)

    if floor >= _NOISE_IMPLAUSIBLE_CEILING_KM_S:
        return NoiseModel(
            median_km_s=med, mad_km_s=mad,
            floor_km_s=_NOISE_ABSOLUTE_FLOOR_KM_S, samples=n,
            method=(f"median+5·MAD gave {floor * 1000:.0f} m/s, which is far above any "
                    "element set fit scatter. More than half these pairs most likely "
                    "contain a manoeuvre, so the median is a burn rather than the "
                    "background. Fell back to the absolute floor and every detection "
                    "is reported for judgement."),
            floor_is_measured=False,
        )
    return NoiseModel(median_km_s=med, mad_km_s=mad, floor_km_s=floor, samples=n)


# ── Assembly ──────────────────────────────────────────────────────────────────

def build_breakdown(before: _RecordLike, after: _RecordLike, gap_days: float,
                    noise: NoiseModel | None = None) -> DvBreakdown:
    """Run every estimator on one element set pair and judge the result.

    *before* and *after* are ``TLERecord``-shaped objects, taken structurally
    so this module stays importable from ``pattern_of_life``.
    """
    b = snapshot_from_record(before)
    a = snapshot_from_record(after)
    tle_before = str(getattr(before, "tle", "") or "")
    tle_after  = str(getattr(after, "tle", "") or "")

    swept = estimate_dv_epoch_swept(tle_before, tle_after, b.epoch, a.epoch)

    # The orbit precesses at one rate before the burn and another after it, so
    # the drift to remove depends on when in the gap the burn happened. Without
    # that the correction is wrong in proportion to the gap: on a 15 day gap it
    # put 39 m/s of phantom plane change on a real 7 m/s burn. The swept
    # estimator has already measured the burn instant, so use it.
    rate_b = secular_rates_deg_day(tle_before, b.sma_km, b.ecc, b.inc_deg)
    rate_a = secular_rates_deg_day(tle_after, a.sma_km, a.ecc, a.inc_deg)
    frac_before = 0.5
    if swept.burn_epoch is not None and gap_days > 0:
        frac_before = min(1.0, max(0.0,
            (swept.burn_epoch - b.epoch).total_seconds() / 86400.0 / gap_days))
    raan_rate = rate_b[0] * frac_before + rate_a[0] * (1.0 - frac_before)
    argp_rate = rate_b[1] * frac_before + rate_a[1] * (1.0 - frac_before)

    elements = estimate_dv_mean_elements(b, a, gap_days, raan_rate, argp_rate)
    legacy   = estimate_dv_propagation(tle_before, tle_after, a.epoch)

    # How far apart should the two orbits be, given the element change the
    # pair actually shows? Energy change separates them by |Δa|; plane change
    # by roughly r·θ. Anything much beyond that and the two fits never describe
    # one object at one place, so the velocity difference between them is not
    # an impulse and must not be reported as one.
    theta_deg = 0.0
    for c in elements.components:
        if c.channel == "cross_track":
            theta_deg = float(c.inputs.get("plane_angle_deg", 0.0))
    # A radial burn separates the orbits at apsis by about a·|Δe⃗|, and
    # omitting that term set every radial burn aside: the swept estimate was
    # discarded, the headline fell back to element differencing, and the
    # confidence dropped to LOW, so a real eccentricity change could never be
    # confirmed and never reached the cumulative ΔV. Measured before the fix: a
    # 3.8 m/s radial burn with a 3.46 km mismatch against a 2.07 km allowance.
    d_e_vector = 0.0
    for c in elements.components:
        if c.channel == "radial":
            d_e_vector = float(c.inputs.get("delta_e_vector", 0.0))
    expected_miss = math.sqrt(
        (a.sma_km - b.sma_km) ** 2
        + (b.sma_km * math.radians(theta_deg)) ** 2
        + (b.sma_km * d_e_vector) ** 2
    )
    miss = swept.position_mismatch_km
    swept_usable = (
        not swept.failed
        and miss is not None
        and miss <= max(_SWEPT_MISS_FLOOR_FRACTION * b.sma_km,
                        _SWEPT_MISS_TOLERANCE * expected_miss)
    )

    if swept_usable:
        dv, headline = swept.dv_km_s, swept.method
    else:
        dv, headline = elements.dv_km_s, elements.method

    # Agreement between the two independent estimators. Skipped when both sit
    # under the absolute floor: the ratio of two numbers that are each
    # indistinguishable from zero says nothing about either.
    ratio: float | None = None
    if swept_usable:
        lo = min(swept.dv_km_s, elements.dv_km_s)
        hi = max(swept.dv_km_s, elements.dv_km_s)
        if hi >= _NOISE_ABSOLUTE_FLOOR_KM_S:
            ratio = hi / lo if lo > 0 else float("inf")

    snr = noise.snr(dv) if noise else None

    warnings: list[str] = []
    if b.source.strip() and a.source.strip() and b.source.strip() != a.source.strip():
        warnings.append(
            f"Element sets come from different sources ({b.source} → {a.source}). "
            "A difference between two providers' fits is not a manoeuvre."
        )
    if b.data_mode.strip() and a.data_mode.strip() and b.data_mode != a.data_mode:
        warnings.append(f"Data mode changes across the pair ({b.data_mode} → {a.data_mode}).")
    if gap_days <= 0.0:
        warnings.append(f"Non-positive epoch gap ({gap_days:.4f} days): the two fits "
                        "are effectively simultaneous and cannot bracket a manoeuvre.")
    if b.rms_residual is not None and a.rms_residual is not None:
        worst, best = max(b.rms_residual, a.rms_residual), min(b.rms_residual, a.rms_residual)
        if best > 0 and worst / best > 3.0:
            warnings.append(f"Fit quality differs sharply across the pair "
                            f"(RMS {b.rms_residual:.4g} → {a.rms_residual:.4g}).")
    if swept.failed:
        warnings.append(f"Epoch-swept estimator unavailable ({swept.failure_reason}). "
                        "Headline figure is from element differencing alone.")
    if not swept.failed and not swept_usable and miss is not None:
        warnings.append(
            f"The two fits never come within {miss:.1f} km of each other inside the "
            f"gap, against {expected_miss:.1f} km expected from the element change. "
            "The epoch-swept figure is not a ΔV and has been set aside; the headline "
            "is element differencing."
        )
    if ratio is not None and ratio > _AGREEMENT_POOR:
        warnings.append(f"The two estimators disagree by {ratio:.1f}×. The element "
                        "change is not a clean single impulse.")

    if not legacy.failed and dv > 0 and legacy.dv_km_s / dv > 10.0:
        legacy = replace(legacy, notes=(*legacy.notes,
            f"{legacy.dv_km_s / dv:.0f}× the headline figure. That multiple is the "
            "along-track phase this method cannot separate from ΔV, and is why the "
            "panel's ΔV figures changed."))

    confidence, reason = _judge(dv, swept, ratio, snr, noise, warnings)

    return DvBreakdown(
        dv_km_s=dv, headline_method=headline,
        swept=swept, elements=elements, legacy=legacy,
        before=b, after=a, gap_days=gap_days,
        agreement_ratio=ratio, snr=snr, noise=noise,
        confidence=confidence, confidence_reason=reason,
        warnings=tuple(warnings),
    )


def _judge(dv_km_s: float, swept: DvEstimate, ratio: float | None,
           snr: float | None, noise: NoiseModel | None,
           warnings: list[str]) -> tuple[str, str]:
    """Verdict on whether a ΔV figure should be believed.

    Ordered so that the disqualifying checks run first: a figure below the
    measured noise floor is not a quiet manoeuvre, it is not a manoeuvre.

    Only HIGH is a confirmation, and it takes all three of: the two independent
    estimators agreeing within 1.5×, a signal ten times the measured fit
    scatter, and no provenance objection. Measured over four simulated
    catalogues of known truth that combination returned no false confirmations
    on three and two on the sparsest, while relaxing the signal requirement to
    five admitted twelve to sixteen.
    """
    if noise and dv_km_s < noise.floor_km_s:
        return "REJECT", (f"{dv_km_s * 1000:.3f} m/s is below the measured detection "
                          f"floor of {noise.floor_m_s:.3f} m/s for this object.")
    if snr is not None and snr < _SNR_REJECT:
        return "REJECT", (f"Signal-to-noise {snr:.1f} against this object's own fit "
                          "scatter. Indistinguishable from element set noise.")

    blocking = [w for w in warnings
                if "different sources" in w or "Non-positive epoch gap" in w
                or "set aside" in w]
    if blocking:
        return "LOW", blocking[0]
    if ratio is not None and ratio > _AGREEMENT_POOR:
        return "LOW", f"Independent estimators disagree by {ratio:.1f}×."
    if snr is not None and snr < _SNR_LOW:
        return "LOW", f"Signal-to-noise {snr:.1f} — close to this object's fit scatter."

    agree = ratio is not None and ratio <= _AGREEMENT_HIGH
    strong = snr is not None and snr >= _SNR_HIGH
    if snr is None:
        # No measurable noise floor, because the object's own pair-to-pair
        # differences were all but identical and the MAD came out zero. Two
        # estimators agreeing says the arithmetic is consistent; it says
        # nothing about whether the figure stands above this object's scatter,
        # because the scatter could not be measured. Confirmation needs both.
        return "MODERATE", (
            "Estimators agree"
            + (f" within {ratio:.2f}×" if ratio is not None else "")
            + ", but this object's fit scatter could not be measured, so there "
            "is nothing to say the figure stands above it."
        )
    if agree and strong:
        return "HIGH", (f"Independent estimators agree within {ratio:.2f}×, "
                        f"at {snr:.0f}× the measured noise.")
    if strong:
        return "MODERATE", (f"Well above noise ({snr:.0f}×), but the estimators "
                            f"differ by {ratio:.1f}×." if ratio is not None
                            else f"Well above noise ({snr:.0f}×).")
    return "MODERATE", (f"Estimators agree within {ratio:.2f}×."
                        if ratio is not None else "Single estimator available.")
