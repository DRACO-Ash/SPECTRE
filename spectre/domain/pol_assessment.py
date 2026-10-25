"""Interpretation of a Pattern of Life measurement, against cited figures.

``spectre.astro.pattern_of_life`` measures. This module decides what the
measurements mean. The split matters for two reasons.

**Units.** The astro package works in km and km/s throughout, because
``MU_EARTH`` is in km³/s² and SGP4 returns km/s. Everything an operator reads
is m/s. Putting the interpretation here keeps that conversion at one boundary
instead of threading it through the physics.

**Provenance.** Every threshold in this module comes from the open-source
assessment *Satellite Manoeuvre Delta-v: Feasibility Above 0.5 km/s and Budgets
by Regime* (Bluestaq Limited Space Watch, v1.0, 13 October 2026), through
:mod:`spectre.domain.manoeuvre_calibration`, which already held those figures
for the threat sweep. Pattern of Life carried its own separate copies, uncited,
and they were wrong in a specific and costly way:

● ``_SK_DV_LIMIT`` applied Table 3's **annual** station-keeping budgets as
  **per-event** limits. Its GEO value was 50 m/s against a real single
  north-south burn of about 1.8 m/s. Four of the assessment's own named
  counterspace events classified as routine station-keeping, including both
  Luch/Olymp-K relocations.
● ``_GEO_SK_BASELINE`` implied 209 m/s/yr against Table 3's 44 to 55, so every
  GEO object was scored against a baseline four times its real budget.
● The anomaly score awarded a full budget term at 200 m/s/yr for every regime,
  so a navigation satellite burning twice its regime's entire annual budget
  scored one point out of a hundred.
● The propellant model reported the fraction of **total spacecraft mass** under
  a label naming the fraction of the **propellant load**, understating by the
  propellant mass fraction: roughly tenfold for a LEO smallsat. It assumed
  900 kg of propellant on a 3-tonne platform for every object in every regime,
  and computed remaining ΔV with a denominator of ``prop + prop``, returning a
  constant 1,495 m/s whatever the object.

Two sets of numbers for the same physics is worse than one set that is wrong,
because only one of them ever gets updated. There is now one set, and it is the
cited one.

One exception, stated rather than hidden (audit F-036): the anomaly index's
component weights and three of its normalisers (60 degrees of longitude,
1.5 degrees per day of drift, an interval coefficient of variation of 2) are
tuned, not sourced, and the risk ladder over it is a convention. The index is a
heuristic and the panel labels it so; its budget and ΔV terms rest on the cited
figures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple

from spectre.astro.constants import _GEO_BAND_ALT
from spectre.domain.manoeuvre_calibration import (
    ON_STATION_ANOMALY_EXPLANATIONS,
    ON_STATION_ANOMALY_M_S,
    ManoeuvreKind,
    PlatformClass,
    Posture,
    PostureAssessment,
    classify_posture,
    from_km_s,
    per_event_station_keeping_m_s,
    platform_class_for_regime,
    platform_total_budget_m_s,
    propellant_mass_fraction,
    station_keeping_m_s_per_year,
)

__all__ = [
    "AnomalyAssessment",
    "IntelAssessment",
    "DetectionLimits",
    "ManoeuvreView",
    "PolAssessment",
    "PropellantAssessment",
    "assess_pattern_of_life",
]

# ─────────────────────────────────────────────────────────────────────────────
# Constants, each with its source
# ─────────────────────────────────────────────────────────────────────────────

#: Standard gravity, m/s². Used with Isp to get exhaust velocity.
_G0_M_S2: float = 9.80665

#: Assumed specific impulse by regime, seconds (Table 1).
#:
#: A guess from the orbit alone, and stated as one wherever it is shown. It
#: matters more than it looks: exhaust velocity scales with it, so an electric
#: platform expends roughly a tenth the propellant mass a chemical one does for
#: the same ΔV. Getting this wrong by an order of magnitude is exactly what the
#: previous model did by applying one chemical figure to every object.
_ASSUMED_ISP_S: dict[str, float] = {
    # "Electric (Hall-effect, gridded ion), Isp of 1,500 to
    # 3,500 s"; LEO smallsats sit at the lower end, so 1,600 s. The
    # Starlink V2 Mini argon Hall thruster is specified at 2,500 s.
    "LEO":  1600.0,
    # All-electric bus, 1,500-3,500 s; the midpoint.
    "MEO":  2500.0,
    "DEEP": 2500.0,
    # "Chemical bipropellant (Isp about 300 to 325 s)". On-station keeping on a
    # chemical comsat runs on the same system.
    "GEO":  320.0,
    "HEO":  320.0,
    "GTO":  320.0,
}

#: Above this many times the regime's routine annual budget, the spend rate is
#: itself the finding. Table 3 gives the routine figures; an object running at
#: five times them is not doing routine operations.
_RATE_NOTABLE_MULTIPLE: float = 2.0
_RATE_ALARMING_MULTIPLE: float = 5.0

#: Anomaly score weights. Unchanged in shape from the original; what changed is
#: that the budget term is now measured against the object's own regime.
_W_GEO = {"dv": 0.20, "lon": 0.30, "drift": 0.25, "regularity": 0.10, "budget": 0.15}
_W_OTHER = {"dv": 0.30, "lon": 0.15, "drift": 0.10, "regularity": 0.20, "budget": 0.25}

#: Overall anomaly score at or above which each risk level is reported,
#: highest rung first. The thresholds are the ones the nested ternary used;
#: they are named because the posture floor in the intel narrative has to
#: order the same five labels, and two hand-written copies of one ordering
#: are how the two come to disagree.
_RISK_LADDER: tuple[tuple[float, str], ...] = (
    (75.0, "CRITICAL"),
    (55.0, "HIGH"),
    (35.0, "MEDIUM"),
    (15.0, "LOW"),
)
#: Reported when the score sits below every rung.
_RISK_FLOOR_LEVEL: str = "MINIMAL"
#: The same labels in increasing order of concern, derived from the ladder
#: so that it cannot drift out of step with it.
_RISK_ORDER: tuple[str, ...] = (
    _RISK_FLOOR_LEVEL, *(level for _, level in reversed(_RISK_LADDER)),
)

#: Named events from the assessment, used to tell an operator in concrete terms
#: what this object's measured detection floor can and cannot see.
#: (description, ΔV in m/s, whether it is routine traffic management)
_REFERENCE_EVENTS: tuple[tuple[str, float, bool], ...] = (
    ("Collision avoidance, any regime (Table 4)",            1.0,   True),
    ("GEO north-south station-keeping, per burn (Table 3)",  1.8,   True),
    ("GEO graveyard raise, 300 km (Table 3)",                9.0,   False),
    ("Luch/Olymp-K 2, 62° relocation (observed 2025)",       11.0,  False),
    ("Luch/Olymp-K 1, raise above GEO (observed 2025)",      15.0,  False),
    ("Cosmos 2576 inspector campaign (observed 2024-25)",    27.5,  False),
    ("GEO relocation, 180° in 30 days (Table 4)",            34.0,  False),
    ("SJ-21 dock and tow of Beidou-2 G2 (observed 2022)",    60.0,  False),
    ("SJ-21 tow, round trip (observed)",                     120.0, False),
    ("Rapid GEO relocation, 90° in 3 days (Table 4)",        170.0, False),
)


# ─────────────────────────────────────────────────────────────────────────────
# Per-manoeuvre interpretation
# ─────────────────────────────────────────────────────────────────────────────

#: Which measured ΔV channel corresponds to which operational manoeuvre kind.
#: In GEO an along-track burn IS a longitude relocation, which is why the two
#: regimes map the same channel differently.
_CHANNEL_TO_KIND: dict[tuple[bool, str], ManoeuvreKind] = {
    (True,  "along_track"): ManoeuvreKind.PHASING,          # GEO: drift start
    (True,  "cross_track"): ManoeuvreKind.PLANE_CHANGE,
    (True,  "radial"):      ManoeuvreKind.ALTITUDE_CHANGE,
    (False, "along_track"): ManoeuvreKind.ALTITUDE_CHANGE,
    (False, "cross_track"): ManoeuvreKind.PLANE_CHANGE,
    (False, "radial"):      ManoeuvreKind.ALTITUDE_CHANGE,
    # A manoeuvre that moves altitude and plane together, above the
    # station-keeping ceiling, is the signature of inspection or shadowing
    # work. Note this is the OPPOSITE fallback to kind_for_method, which sends
    # an unrecognised SOLVER to the widest band so a new solver cannot be
    # scored as more alarming than it is. Here the object has already
    # manoeuvred and we are reading its behaviour, so the permissive choice is
    # the unsafe one: Cosmos 2576's inspector campaign, 25 to 30 m/s in LEO
    # across altitude and inclination together, reads BENIGN against the
    # rendezvous band and ANNOYANCE against the proximity band it belongs in.
    (True,  "mixed"):       ManoeuvreKind.PROXIMITY,
    (False, "mixed"):       ManoeuvreKind.PROXIMITY,
}

#: Upper edge of the GEO protected region, km of altitude: GEO altitude plus
#: 200 km, as the IADC Space Debris Mitigation Guidelines define the region
#: (GEO altitude plus or minus 200 km, latitude within 15 degrees). A raise that
#: ends above it is disposal, not relocation, and the two look identical in the
#: elements alone. It was 36,186 km, the regime band edge (GEO plus 400 km),
#: so a standard 300 km graveyard raise read as relocation (audit F-116).
_GEO_PROTECTED_HALF_WIDTH_KM: float = 200.0
_GEO_PROTECTED_MAX_ALT_KM: float = _GEO_BAND_ALT + _GEO_PROTECTED_HALF_WIDTH_KM

#: Operator label for a manoeuvre inside the routine per-event budget.
#: Three places decide on this one string: the classifier that assigns it,
#: the routine test that reads it back, and the Monte Carlo archetype map.
_LABEL_STATION_KEEPING: str = "station keeping"

#: Thrust duration, hours, beyond which a burn is reported as slow. A
#: manoeuvre an electric bus has to spend more than a day delivering is not
#: something an operator can read as an impulsive event on one element set.
_SLOW_BURN_HOURS: float = 24.0

#: Share of the measured ΔV the largest channel must carry before the
#: manoeuvre is attributed to that channel. Below it the burn moved altitude
#: and plane together, which is the inspection signature, not one of either.
_DOMINANT_CHANNEL_FRACTION: float = 0.6


@dataclass(frozen=True)
class ManoeuvreView:
    """One measured manoeuvre, interpreted. Every ΔV here is m/s."""

    manoeuvre:        Any            # the astro Manoeuvre, for epoch and deltas
    delta_v_m_s:      float
    kind:             ManoeuvreKind
    classification:   str            # operator-facing label
    sk_subtype:       str
    posture:          PostureAssessment
    sk_ceiling_m_s:   float
    sk_ceiling_basis: str
    confirmed:        bool

    #: True when this single manoeuvre exceeds what any platform in this regime
    #: could hold in total. The assessment's second watchlist recommendation.
    exceeds_on_station_anomaly: bool
    exceeds_platform_ceiling:   bool
    escalation:                 str

    #: How long THIS object's assumed platform class would need to deliver the
    #: ΔV, and how long the fastest flown class would. The assessment's third
    #: watchlist recommendation is to characterise electric platforms by rate
    #: rather than reserve: an all-electric GEO bus holds up to 1,500 m/s but
    #: thrusts at 0.27 N on 3,000 kg, so it needs about 22 days to deliver
    #: 170 m/s. An impulsive reading of that is not imprecise, it is the wrong
    #: question, and it rules out any scenario needing the move on short
    #: notice.
    burn_hours:          float | None
    burn_platform:       str
    fastest_burn_hours:  float | None
    fastest_platform:    str

    @property
    def posture_label(self) -> str:
        return self.posture.posture_label

    @property
    def is_routine(self) -> bool:
        return self.classification == _LABEL_STATION_KEEPING

    @property
    def burn_days(self) -> float | None:
        return self.burn_hours / 24.0 if self.burn_hours is not None else None

    @property
    def monte_carlo_archetype(self) -> str:
        """The nearest Monte Carlo archetype for this classification.

        ``spectre.astro.monte_carlo`` keys its dispersion models on its own
        archetype names, which predate this vocabulary. Mapping here keeps the
        drill-down's ▶ MC button working without either module having to know
        the other's labels.
        """
        return {
            _LABEL_STATION_KEEPING: "station_keeping",
            "plane change":       "plane_change",
            "relocation":         "phasing",
            "altitude change":    "orbit_raise",
            "graveyard disposal": "orbit_raise",
            "orbit reshaping":    "repositioning",
            "combined manoeuvre": "repositioning",
        }.get(self.classification, "repositioning")

    @property
    def burn_is_slow(self) -> bool:
        """True when delivering this ΔV takes more than a day of thrust."""
        return self.burn_hours is not None and self.burn_hours > _SLOW_BURN_HOURS


def _dominant_channel(manoeuvre: Any) -> str:
    """Which ΔV channel carries this manoeuvre, from the measured breakdown."""
    breakdown = getattr(manoeuvre, "breakdown", None)
    components = getattr(breakdown, "components", ()) if breakdown else ()
    if not components:
        return ""
    top = max(components, key=lambda c: c.dv_km_s)
    total = sum(c.dv_km_s for c in components)
    if total <= 0 or top.dv_km_s / total < _DOMINANT_CHANNEL_FRACTION:
        return "mixed"
    # components arrives through getattr, so its element type is unknown to
    # the checker however well typed the breakdown is.
    return str(top.channel)


# Six measured quantities about one burn, with no sub-group that travels
# together anywhere else: the ΔV, the channel it came out of, the regime and
# ceiling it is judged against, and the two altitude figures that separate a
# graveyard raise from the start of a drift. A holder object would carry the
# same six values behind a constructor without reducing what the classifier
# has to know, and the caller and the direct unit tests both pass them
# positionally.
def _classify(delta_v_m_s: float, channel: str, regime: str,  # noqa: PLR0913, PLR0917
              sk_ceiling_m_s: float,
              alt_after_km: float | None = None,
              delta_alt_km: float = 0.0) -> tuple[str, str, ManoeuvreKind]:
    """Operator label, station-keeping subtype, and the calibration kind.

    The ceiling is derived from Table 3's annual budget and the object's own
    cadence, not asserted. Below it, a burn is indistinguishable from routine
    maintenance whatever channel it sits in.
    """
    is_geo = regime.strip().upper() in ("GEO", "DEEP")
    kind = _CHANNEL_TO_KIND.get((is_geo, channel), ManoeuvreKind.RENDEZVOUS)

    if delta_v_m_s <= sk_ceiling_m_s:
        subtype = {"cross_track": "NS", "along_track": "EW"}.get(channel, "combined")
        return (_LABEL_STATION_KEEPING, subtype, kind)

    # A raise that ends above the GEO protected region is a graveyard disposal.
    # In the elements alone it is indistinguishable from the start of a drift,
    # so the altitude it ends at is the only thing that separates them.
    if (is_geo and channel == "along_track" and delta_alt_km > 0
            and alt_after_km is not None and alt_after_km > _GEO_PROTECTED_MAX_ALT_KM):
        return ("graveyard disposal", "", ManoeuvreKind.ALTITUDE_CHANGE)

    label = {
        "cross_track": "plane change",
        "along_track": "relocation" if is_geo else "altitude change",
        "radial":      "orbit reshaping",
        "mixed":       "combined manoeuvre",
    }.get(channel, "manoeuvre")
    return (label, "", kind)


def _escalation_text(delta_v_m_s: float, channel: str, _regime: str) -> str:
    """What a manoeuvre above the on-station anomaly threshold implies.

    The assessment gives four explanations for an inferred on-station ΔV of
    0.5 km/s or more. The measured decomposition distinguishes the first from
    the rest, so say which one the orbit change actually supports rather than
    listing all four and leaving the operator to choose.

    *_regime* is not read: the four explanations are not regime-specific. It
    stays in the signature because the caller and the direct unit tests both
    pass it positionally.
    """
    if channel == "cross_track":
        leading = ON_STATION_ANOMALY_EXPLANATIONS[0]
        rest = ON_STATION_ANOMALY_EXPLANATIONS[1:]
    else:
        leading = ON_STATION_ANOMALY_EXPLANATIONS[2]
        rest = tuple(e for e in ON_STATION_ANOMALY_EXPLANATIONS if e != leading)
    return (
        f"{delta_v_m_s:,.0f} m/s in a single manoeuvre is at or above the "
        f"{ON_STATION_ANOMALY_M_S:,.0f} m/s the assessment treats as high "
        f"priority for an object on station. The measured decomposition is "
        f"dominated by the {channel.replace('_', '-')} channel, which is most "
        f"consistent with {leading}. The alternatives are: "
        + "; ".join(rest) + "."
    )


def _view(manoeuvre: Any, regime: str, sk_ceiling_m_s: float,
          sk_basis: str, confirmed: bool) -> ManoeuvreView:
    from spectre.domain.manoeuvre_calibration import fastest_delivery_hours

    delta_v_m_s = from_km_s(float(getattr(manoeuvre, "delta_v_km_s", 0.0)))
    channel = _dominant_channel(manoeuvre) or "mixed"
    label, subtype, kind = _classify(
        delta_v_m_s, channel, regime, sk_ceiling_m_s,
        alt_after_km=getattr(getattr(manoeuvre, "tle_after", None), "alt_km", None),
        delta_alt_km=float(getattr(manoeuvre, "delta_alt_km", 0.0) or 0.0),
    )

    ceiling = platform_total_budget_m_s(regime)
    over_anomaly = delta_v_m_s >= ON_STATION_ANOMALY_M_S
    over_ceiling = delta_v_m_s > ceiling

    escalation = ""
    if over_ceiling:
        escalation = (
            f"{delta_v_m_s:,.0f} m/s in one manoeuvre exceeds the {ceiling:,.0f} m/s "
            f"that Table 2 puts as the entire lifetime budget of any {regime} "
            "platform. A single burn cannot exceed what the platform could ever "
            "hold, so either the element sets do not describe one object, or this "
            "is not the platform class assumed."
        )
    elif over_anomaly:
        escalation = _escalation_text(delta_v_m_s, channel, regime)

    assumed = platform_class_for_regime(regime)
    own_hours = assumed.minimum_burn_hours(delta_v_m_s)
    fastest_hours, fastest_name = fastest_delivery_hours(delta_v_m_s)
    return ManoeuvreView(
        manoeuvre=manoeuvre,
        delta_v_m_s=delta_v_m_s,
        kind=kind,
        classification=label,
        sk_subtype=subtype,
        posture=classify_posture(delta_v_m_s, regime, kind),
        sk_ceiling_m_s=sk_ceiling_m_s,
        sk_ceiling_basis=sk_basis,
        confirmed=confirmed,
        exceeds_on_station_anomaly=over_anomaly,
        exceeds_platform_ceiling=over_ceiling,
        escalation=escalation,
        burn_hours=None if math.isinf(own_hours) else own_hours,
        burn_platform=assumed.name,
        fastest_burn_hours=None if math.isinf(fastest_hours) else fastest_hours,
        fastest_platform=fastest_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# The propellant model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PropellantAssessment:
    """What the observed spend implies about the tank, built on Table 2.

    The headline figure is ``propellant_used_pct``, and it now means what its
    name says: the fraction of the PROPELLANT LOAD consumed.
    ``total_mass_fraction_pct`` is kept beside it because that is the quantity
    the previous model reported under this name, and a reader comparing against
    an older screenshot needs to see both to understand why they differ.
    """

    platform:            PlatformClass
    regime:              str
    assumed_isp_s:       float
    propellant_fraction: float

    spent_m_s:              float   # cumulative ΔV over the whole span
    spent_since_reset_m_s:  float   # since the last refuelling, if any
    reserve_reset:          datetime | None

    propellant_used_pct:     float  # of the TANK. The honest figure.
    total_mass_fraction_pct: float  # what the old label actually measured

    discretionary_min_m_s:       float
    discretionary_max_m_s:       float
    discretionary_remaining_m_s: float
    lifetime_budget_m_s:         float
    exceeds_lifetime_budget:     bool

    annual_rate_m_s:    float
    routine_annual_m_s: float | None
    rate_multiple:      float | None

    narrative: str
    caveats:   tuple[str, ...] = ()

    @property
    def rate_class(self) -> str:
        if self.rate_multiple is None:
            return "Unknown"
        if self.rate_multiple >= _RATE_ALARMING_MULTIPLE:
            return "Far above routine"
        if self.rate_multiple >= _RATE_NOTABLE_MULTIPLE:
            return "Above routine"
        return "Within routine"


class _Spend(NamedTuple):
    """Confirmed ΔV, in m/s, three ways.

    *discretionary_since_reset* leaves out routine station-keeping: Table 2's
    discretionary reserve is what remains AFTER the routine share of the
    lifetime budget, so counting maintenance burns against it would empty a
    well-behaved GEO object's reserve within a few years (audit F-118).
    """

    total: float
    since_reset: float
    discretionary_since_reset: float


def _assess_propellant(
    regime: str, spend: _Spend, span_days: float, reserve_reset: datetime | None,
) -> PropellantAssessment:
    total_dv_m_s, since_reset_m_s = spend.total, spend.since_reset
    platform = platform_class_for_regime(regime)
    isp = _ASSUMED_ISP_S.get(regime.strip().upper(), 320.0)
    ve_m_s = isp * _G0_M_S2
    fraction = propellant_mass_fraction(regime)

    # Fraction of INITIAL TOTAL MASS that had to be expelled for this ΔV.
    mass_frac = 1.0 - math.exp(-since_reset_m_s / ve_m_s) if ve_m_s > 0 else 0.0
    # Fraction of the PROPELLANT LOAD that represents. This division is the
    # whole correction: without it the figure understates by 1/fraction, which
    # is a factor of ten for a LEO smallsat.
    used_pct = min(100.0, mass_frac / fraction * 100.0) if fraction > 0 else 0.0

    years = max(span_days / 365.25, 1e-6)
    annual = since_reset_m_s / years
    routine = station_keeping_m_s_per_year(regime)
    multiple = (annual / routine) if routine else None

    lifetime = platform_total_budget_m_s(regime)
    remaining = max(0.0, platform.discretionary_max_m_s - spend.discretionary_since_reset)

    caveats = [
        f"Platform class assumed from the orbit regime alone: {platform.name}. "
        f"{platform.basis}",]
    if not platform.discretionary_is_published:
        caveats.append(
            f"Table 2 gives no discretionary figure for this class, so the "
            f"{platform.discretionary_max_m_s:,.0f} m/s above is its TOTAL "
            "lifetime budget standing in for one. Most of that total is "
            "committed to routine operations, so the reserve genuinely "
            "available for manoeuvring against another object is smaller, by "
            "an amount the open sources do not state."
        )
    caveats += [
        f"Specific impulse assumed at {isp:,.0f} s and propellant at "
        f"{fraction * 100:.0f} per cent of mass, both from Table 2's stated "
        "assumptions for this class. These are rocket-equation estimates, not "
        "published budgets; the assessment rates them moderate confidence.",
    ]
    if reserve_reset is not None:
        caveats.append(
            f"Counted from the reserve reset on {reserve_reset.strftime('%Y-%m-%d')}. "
            f"{total_dv_m_s:,.1f} m/s was spent across the whole observed span; the "
            f"figure above is the {since_reset_m_s:,.1f} m/s spent since. The "
            "transferred quantity is not modelled: the assessment marks the one "
            "reported refuelling mass as secondary reporting, unconfirmed."
        )

    if since_reset_m_s > lifetime:
        narrative = (
            f"{since_reset_m_s:,.1f} m/s exceeds the {lifetime:,.0f} m/s that Table 2 "
            f"puts as the entire lifetime budget of a {regime} platform. This is not "
            "a propellant reading, it is evidence that the detections, the element "
            "sets, or the assumption that these describe one object are wrong."
        )
    elif multiple is not None and multiple >= _RATE_ALARMING_MULTIPLE:
        narrative = (
            f"Spending {annual:,.1f} m/s a year against a routine {regime} budget of "
            f"{routine:,.0f} m/s ({multiple:.1f} times), and about "
            f"{used_pct:.1f} per cent of the assumed tank. That rate is not routine "
            "operations."
        )
    elif multiple is not None:
        narrative = (
            f"Spending {annual:,.1f} m/s a year against a routine {regime} budget of "
            f"{routine:,.0f} m/s ({multiple:.1f} times), and about "
            f"{used_pct:.1f} per cent of the assumed tank. Roughly "
            f"{remaining:,.0f} m/s of discretionary reserve remains on the "
            f"{platform.name} assumption."
        )
    else:
        narrative = (
            f"About {used_pct:.1f} per cent of the assumed tank, at "
            f"{annual:,.1f} m/s a year. No published routine budget for {regime}, "
            "so there is nothing to compare the rate against."
        )

    return PropellantAssessment(
        platform=platform, regime=regime, assumed_isp_s=isp,
        propellant_fraction=fraction,
        spent_m_s=total_dv_m_s, spent_since_reset_m_s=since_reset_m_s,
        reserve_reset=reserve_reset,
        propellant_used_pct=round(used_pct, 2),
        total_mass_fraction_pct=round(mass_frac * 100.0, 4),
        discretionary_min_m_s=platform.discretionary_min_m_s,
        discretionary_max_m_s=platform.discretionary_max_m_s,
        discretionary_remaining_m_s=round(remaining, 1),
        lifetime_budget_m_s=lifetime,
        exceeds_lifetime_budget=since_reset_m_s > lifetime,
        annual_rate_m_s=round(annual, 2),
        routine_annual_m_s=routine,
        rate_multiple=round(multiple, 2) if multiple is not None else None,
        narrative=narrative, caveats=tuple(caveats),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly scoring, measured against the object's own regime
# ─────────────────────────────────────────────────────────────────────────────

#: Confirmed manoeuvres needed before an anomaly score means anything. Three of
#: the five terms are about the spread across a series: longitude coverage,
#: drift and station-keeping regularity are all undefined for a single burn,
#: so scoring one would report the floor as a measurement.
_MIN_VIEWS_FOR_ANOMALY: int = 2


@dataclass(frozen=True)
class AnomalyAssessment:
    dv_magnitude:  float
    lon_coverage:  float
    drift_rate:    float
    sk_regularity: float
    budget_rate:   float
    overall:       float
    risk_level:    str
    basis:         str


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _risk_level(overall: float) -> str:
    """The risk label for an overall anomaly score, highest rung first."""
    for threshold, level in _RISK_LADDER:
        if overall >= threshold:
            return level
    return _RISK_FLOOR_LEVEL


# Normalisers at which a component reaches full score. Tuned, not sourced
# (audit F-036): the module docstring and the basis line both say so.
_ANOMALY_FULL_LON_DEG = 60.0
_ANOMALY_FULL_DRIFT_DEG_DAY = 1.5
_ANOMALY_FULL_CV = 2.0
_ANOMALY_TUNED_NOTE = (
    " The component weights and the longitude, drift and interval normalisers "
    "(60 degrees, 1.5 degrees per day, a coefficient of variation of 2) are tuned, "
    "not sourced, so the overall figure is a heuristic index, not a measurement."
)


def _assess_anomaly(
    views: list[ManoeuvreView], pol: Any, regime: str,
    propellant: PropellantAssessment,
) -> AnomalyAssessment | None:
    if len(views) < _MIN_VIEWS_FOR_ANOMALY:
        return None

    routine = station_keeping_m_s_per_year(regime)
    sk_ceiling = views[0].sk_ceiling_m_s

    # ΔV magnitude, against a real single station-keeping burn rather than a
    # flat 8 m/s. Full score at ten times a routine burn.
    mean_dv = sum(v.delta_v_m_s for v in views) / len(views)
    dv_score = _clamp01((mean_dv - sk_ceiling) / max(sk_ceiling * 9.0, 1e-6)) * 100

    lons = [v.manoeuvre.tle_after.geo_longitude_deg for v in views
            if v.manoeuvre.tle_after.geo_longitude_deg is not None]
    lon_range = (max(lons) - min(lons)) if len(lons) > 1 else 0.0
    lon_score = _clamp01(lon_range / _ANOMALY_FULL_LON_DEG) * 100

    phases = getattr(pol, "drift_phases", []) or []
    if phases:
        max_drift = max(abs(p.rate_deg_day) for p in phases)
        # Table 3: GEO east-west keeping holds a slot to about 0.05 deg/day.
        drift_score = _clamp01((max_drift - 0.05) / _ANOMALY_FULL_DRIFT_DEG_DAY) * 100
    else:
        drift_score = 0.0

    intervals = getattr(pol, "interval_stats", None)
    if intervals and intervals.std > 0:
        reg_score = _clamp01((intervals.std / max(intervals.mean, 0.01)) / _ANOMALY_FULL_CV) * 100
    else:
        reg_score = 0.0

    # The correction that matters: full budget score at five times the regime's
    # OWN routine annual figure, not at a flat 200 m/s/yr for everything.
    if routine:
        budget_score = _clamp01(propellant.annual_rate_m_s
                                / (routine * _RATE_ALARMING_MULTIPLE)) * 100
        basis = (f"Budget term measured against {regime}'s routine "
                 f"{routine:.0f} m/s per year (Table 3); full score at "
                 f"{routine * _RATE_ALARMING_MULTIPLE:.0f} m/s per year. ΔV term "
                 f"measured against a {sk_ceiling:.2f} m/s routine burn.")
    else:
        budget_score = 0.0
        basis = (f"No published station-keeping budget for {regime}, so the "
                 "budget term is not scored rather than guessed.")

    basis += _ANOMALY_TUNED_NOTE
    w = _W_GEO if regime.strip().upper() in ("GEO", "DEEP") else _W_OTHER
    overall = (dv_score * w["dv"] + lon_score * w["lon"] + drift_score * w["drift"]
               + reg_score * w["regularity"] + budget_score * w["budget"])

    risk = _risk_level(overall)

    return AnomalyAssessment(
        dv_magnitude=round(dv_score, 1), lon_coverage=round(lon_score, 1),
        drift_rate=round(drift_score, 1), sk_regularity=round(reg_score, 1),
        budget_rate=round(budget_score, 1), overall=round(overall, 1),
        risk_level=risk, basis=basis,
    )


# ─────────────────────────────────────────────────────────────────────────────
# What the detector can and cannot see
# ─────────────────────────────────────────────────────────────────────────────

#: One GEO north-south station-keeping burn, m/s, from Table 3 and listed among
#: the reference events above. A detection floor at or below it is the floor
#: that separates "this object is quiet" from "this method cannot see routine
#: housekeeping", which is the distinction the panel exists to make.
_GEO_NS_STATION_KEEPING_M_S: float = 1.8


@dataclass(frozen=True)
class DetectionLimits:
    """The measured floor, stated in terms of real manoeuvres.

    "No manoeuvres detected" is a materially misleading thing to tell an
    operator about a Starlink-class object that flew more than forty collision
    avoidance manoeuvres last year. Those burns are centimetres per second to
    about one metre per second (Table 4), and no element-set differencing
    method will ever see them. That is a limit of the technique, not a defect,
    and the panel has to say so rather than leave the operator to infer that a
    quiet object is a passive one.
    """

    floor_m_s:    float
    median_m_s:   float
    mad_m_s:      float
    samples:      int
    visible:      tuple[tuple[str, float], ...]
    invisible:    tuple[tuple[str, float], ...]
    narrative:    str

    @property
    def sees_routine_station_keeping(self) -> bool:
        return self.floor_m_s <= _GEO_NS_STATION_KEEPING_M_S


# *_regime* is not read: the reference events and the measured floor are both
# regime-independent. It stays in the signature because the caller and the
# direct unit tests both pass it positionally.
def _assess_detection(noise: Any, _regime: str) -> DetectionLimits | None:
    if noise is None:
        return None
    floor = from_km_s(noise.floor_km_s)
    visible = tuple((label, dv) for label, dv, _ in _REFERENCE_EVENTS if dv >= floor)
    invisible = tuple((label, dv) for label, dv, _ in _REFERENCE_EVENTS if dv < floor)

    missed_routine = [lbl for lbl, dv, routine in _REFERENCE_EVENTS
                      if routine and dv < floor]
    narrative = (
        f"Detection floor {floor:.2f} m/s, measured from this object's own "
        f"{noise.samples} consecutive element set pairs rather than assumed. "
        "Nothing below it can be told apart from the disagreement between "
        "successive fits."
    )
    if missed_routine:
        narrative += (
            " That puts routine traffic management below the floor: "
            + ", ".join(missed_routine)
            + ". A quiet result here means no manoeuvre LARGE ENOUGH TO SEE, not a "
            "passive object. Starlink alone flew more than 355,000 collision "
            "avoidance manoeuvres in twelve months, none of which any element-set "
            "method could resolve."
        )
    if invisible and not missed_routine:
        narrative += (
            " Counterspace-scale behaviour is above it: the smallest event on "
            "open record that this would catch is "
            f"{visible[0][1]:.0f} m/s ({visible[0][0]})." if visible else ""
        )
    return DetectionLimits(
        floor_m_s=round(floor, 3),
        median_m_s=round(from_km_s(noise.median_km_s), 3),
        mad_m_s=round(from_km_s(noise.mad_km_s), 3),
        samples=noise.samples,
        visible=visible, invisible=invisible, narrative=narrative,
    )


# ─────────────────────────────────────────────────────────────────────────────
# The assembled assessment
# ─────────────────────────────────────────────────────────────────────────────

#: Measured inter-manoeuvre intervals needed before the observed cadence is
#: used in place of the regime's assumed one. With one or two gaps a single
#: long one sets the mean, and the mean sets the per-event station-keeping
#: ceiling that decides routine from not.
_MIN_INTERVALS_FOR_CADENCE: int = 3


@dataclass(frozen=True)
class PolAssessment:
    """Everything a Pattern of Life measurement means, in m/s, with citations."""

    regime:      str
    manoeuvres:  list[ManoeuvreView]
    candidates:  list[ManoeuvreView]
    propellant:  PropellantAssessment
    anomaly:     AnomalyAssessment | None
    detection:   DetectionLimits | None
    intel:       IntelAssessment

    sk_ceiling_m_s:   float
    sk_ceiling_basis: str

    #: Manoeuvres the assessment's watchlist says to treat as high priority.
    escalations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_dv_m_s(self) -> float:
        return sum(v.delta_v_m_s for v in self.manoeuvres)

    @property
    def slow_burns(self) -> list[ManoeuvreView]:
        """Confirmed manoeuvres needing more than a day of continuous thrust."""
        return [v for v in self.manoeuvres if v.burn_is_slow]


def assess_pattern_of_life(
    pol: Any, reserve_reset: datetime | None = None,
) -> PolAssessment:
    """Interpret a ``PolAnalysis`` against the cited figures.

    *reserve_reset* is an operator-supplied refuelling date. The assessment's
    fourth watchlist recommendation is to track refuelling as a capability
    multiplier: SJ-25 class activity removes the end-of-life ΔV constraint on a
    GEO inspector. Cumulative ΔV is monotonic, so without this an object that
    has been refuelled reads as progressively more exhausted exactly as it
    becomes more capable. Everything before the reset is retained and reported
    separately; the transferred quantity is not modelled, because the one
    reported figure is secondary reporting the assessment marks unconfirmed.
    """
    regime = str(getattr(pol, "regime", "") or "")
    confirmed = list(getattr(pol, "manoeuvres", []) or [])
    candidates = list(getattr(pol, "candidate_manoeuvres", []) or [])

    intervals = getattr(pol, "interval_stats", None)
    observed_cadence = intervals.mean if intervals and intervals.n >= _MIN_INTERVALS_FOR_CADENCE else None
    sk_ceiling, sk_basis = per_event_station_keeping_m_s(regime, observed_cadence)

    confirmed_views = [_view(m, regime, sk_ceiling, sk_basis, True) for m in confirmed]
    candidate_views = [_view(m, regime, sk_ceiling, sk_basis, False) for m in candidates]

    span_days = float(getattr(pol, "span_days", 0.0) or 0.0)
    counted = confirmed_views
    if reserve_reset is not None:
        counted = [v for v in confirmed_views if v.manoeuvre.epoch >= reserve_reset]
        records = getattr(pol, "records", []) or []
        if records:
            span_days = max(
                (records[-1].epoch - max(reserve_reset, records[0].epoch))
                .total_seconds() / 86400.0, 1e-6)
    spend = _Spend(
        total=sum(v.delta_v_m_s for v in confirmed_views),
        since_reset=sum(v.delta_v_m_s for v in counted),
        discretionary_since_reset=sum(v.delta_v_m_s for v in counted if not v.is_routine),
    )

    propellant = _assess_propellant(regime, spend, span_days, reserve_reset)
    anomaly = _assess_anomaly(confirmed_views, pol, regime, propellant)
    detection = _assess_detection(getattr(pol, "noise_model", None), regime)

    escalations = tuple(v.escalation for v in confirmed_views if v.escalation)
    if propellant.exceeds_lifetime_budget:
        escalations = (*escalations, propellant.narrative)

    intel = _assess_intel(
        pol, regime, confirmed_views,
        _Components(anomaly=anomaly, propellant=propellant, detection=detection),
    )

    return PolAssessment(
        regime=regime,
        manoeuvres=confirmed_views, candidates=candidate_views,
        propellant=propellant, anomaly=anomaly, detection=detection, intel=intel,
        sk_ceiling_m_s=sk_ceiling, sk_ceiling_basis=sk_basis,
        escalations=escalations,
    )


# ─────────────────────────────────────────────────────────────────────────────
# The operator-level narrative
# ─────────────────────────────────────────────────────────────────────────────

#: Longitude span, degrees, beyond which a GEO object is not holding a slot.
#: Table 3 puts east-west keeping at 1 to 5 m/s/yr, which holds a box of about
#: a tenth of a degree, so anything past a few degrees is a deliberate move.
_GEO_SLOT_DEGREES: float = 2.0
#: Past this, the object is working the belt rather than relocating within it.
_GEO_ROAMER_DEGREES: float = 30.0
#: Drift rate, degrees per day, inside which the object reads as holding its
#: slot rather than moving. Table 3's east-west keeping budget holds a GEO
#: slot to about this rate.
_STATIONARY_DRIFT_DEG_DAY: float = 0.05
#: How far ahead the longitude predictions run, days. Fixed by the three
#: predicted_lon_* fields the panel renders.
_PREDICTION_HORIZON_DAYS: tuple[int, int, int] = (30, 60, 90)
#: Longitude travelled, degrees, before a drift phase is listed as notable.
#: A GEO slot is about a tenth of a degree wide, so a few degrees is already a
#: deliberate move; below this the list fills with slot-keeping wander and the
#: periods that matter stop standing out.
_NOTABLE_DRIFT_DEGREES: float = 5.0

#: The anomaly score needs two manoeuvres to say anything, so a single
#: large burn used to fall through to MINIMAL: a 450 m/s AGGRESSIVE
#: relocation reported "minimal risk" because it happened only once. The
#: worst posture observed is a floor under the score, never a ceiling.
_POSTURE_FLOOR: dict[Posture, str] = {
    Posture.BEYOND_PLATFORM: "CRITICAL",
    Posture.AGGRESSIVE: "HIGH",
    Posture.ANNOYANCE: "MEDIUM",
    Posture.BENIGN: _RISK_FLOOR_LEVEL,
}


@dataclass(frozen=True)
class IntelAssessment:
    """What the behaviour adds up to, for an operator rather than an analyst."""

    mission_profile:       str
    behaviour_class:       str
    risk_level:            str
    operational_signature: str
    anomaly_narrative:     str
    notable_periods:       list[str]
    predicted_lon_30d:     float | None
    predicted_lon_60d:     float | None
    predicted_lon_90d:     float | None
    current_drift_dir:     str
    current_drift_rate:    float | None


def _drift_direction(drift: float | None) -> str:
    """Which way the object is drifting, or that it is holding its slot."""
    rate = drift or 0
    if rate > _STATIONARY_DRIFT_DEG_DAY:
        return "EAST"
    if rate < -_STATIONARY_DRIFT_DEG_DAY:
        return "WEST"
    return "STATIONARY"


def _predicted_longitudes(
    last: Any, drift: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Where the current drift rate puts the object at each horizon.

    A prediction needs a longitude to start from and a rate to apply to it,
    so an object missing either gets no figure rather than one extrapolated
    from an assumed zero.
    """
    if last is not None and last.geo_longitude_deg is not None and drift is not None:
        d30, d60, d90 = _PREDICTION_HORIZON_DAYS
        return (round(last.geo_longitude_deg + drift * d30, 2),
                round(last.geo_longitude_deg + drift * d60, 2),
                round(last.geo_longitude_deg + drift * d90, 2))
    return (None, None, None)


def _mission_profile(
    regime: str, is_geo: bool, lon_range: float,
    views: list[ManoeuvreView], above_routine: int,
) -> tuple[str, str]:
    """Mission profile, keyed on cited budgets rather than an ad-hoc score."""
    postures = [v.posture.posture for v in views]
    aggressive = sum(1 for p in postures if p in (Posture.AGGRESSIVE, Posture.BEYOND_PLATFORM))
    if is_geo and lon_range > _GEO_ROAMER_DEGREES:
        mission = "On-orbit inspection or RPO platform (GEO belt roamer)"
        bclass = (f"Traverses {lon_range:.0f}° of the belt. Table 3's east-west "
                  "keeping budget holds a slot to about a tenth of a degree, so "
                  "this is deliberate, sustained relocation.")
    elif is_geo and lon_range > _GEO_SLOT_DEGREES:
        mission = "GEO longitude relocation"
        bclass = (f"Moved {lon_range:.1f}° in longitude, beyond any station-keeping "
                  "box but within what a routine slot change costs.")
    elif aggressive:
        mission = f"Active manoeuvring platform ({regime})"
        bclass = (f"{aggressive} of {len(views)} confirmed manoeuvres priced above "
                  "what routine operations require for this regime.")
    elif above_routine:
        mission = f"Operational satellite with periodic correction ({regime})"
        bclass = (f"{above_routine} of {len(views)} confirmed manoeuvres above the "
                  f"{views[0].sk_ceiling_m_s:.2f} m/s routine burn for this regime, "
                  "none of them priced aggressively.")
    elif views:
        mission = f"Routine station-keeping ({regime})"
        bclass = ("Every confirmed manoeuvre sits inside the routine per-burn "
                  "budget derived from Table 3.")
    else:
        mission = f"No manoeuvre detected above the measured floor ({regime})"
        bclass = ("Nothing was resolved above this object's own fit scatter. That "
                  "is not the same as passive.")
    return (mission, bclass)


def _risk_with_posture_floor(
    anomaly: AnomalyAssessment | None, views: list[ManoeuvreView],
) -> str:
    """The anomaly risk level, floored by the worst posture observed."""
    risk = anomaly.risk_level if anomaly else _RISK_FLOOR_LEVEL
    if not views:
        return risk
    worst = max((v.posture.posture for v in views), key=lambda p: list(Posture).index(p))
    floor = _POSTURE_FLOOR.get(worst, _RISK_FLOOR_LEVEL)
    if _RISK_ORDER.index(floor) > _RISK_ORDER.index(risk):
        return floor
    return risk


def _quiet_narrative(detection: DetectionLimits, span_days: float) -> str:
    """What a quiet result means.

    This is the case that used to mislead: it asserted the object was
    passive, when routine traffic management sits below the floor for most
    LEO objects.
    """
    return (
        f"No manoeuvre was resolved above the measured detection floor of "
        f"{detection.floor_m_s:.2f} m/s over {span_days:.0f} days. "
        + ("That floor is above routine traffic management, so this object "
           "may well be manoeuvring regularly without any of it being "
           "visible to element-set differencing. "
           if not detection.sees_routine_station_keeping else
           "The floor is below a routine station-keeping burn, so a genuinely "
           "active object would have shown something. ")
        + "A quiet result is evidence about what can be seen, not about what "
        "the object is doing."
    )


def _roamer_narrative(
    lon_range: float, span_days: float, direction: str, drift: float | None,
) -> str:
    """The narrative for an object working the belt rather than holding a slot."""
    return (
        f"This object has traversed {lon_range:.1f}° of the GEO belt over "
        f"{span_days:.0f} days, against an east-west station-keeping budget "
        "that holds a slot to about a tenth of a degree. The pattern of "
        f"alternating drift phases and manoeuvres is consistent with "
        f"deliberate repositioning or proximity work. Current drift: "
        f"{direction} at {abs(drift or 0):.3f}°/day."
    )


def _rate_narrative(
    regime: str, views: list[ManoeuvreView], span_days: float,
    propellant: PropellantAssessment, above_routine: int,
) -> str:
    """The narrative when the spend rate, not the geometry, is the finding."""
    rate_multiple = propellant.rate_multiple
    if rate_multiple is not None and rate_multiple >= _RATE_ALARMING_MULTIPLE:
        return (
            f"{len(views)} confirmed manoeuvres over {span_days:.0f} days, at "
            f"{propellant.annual_rate_m_s:,.1f} m/s a year against a routine "
            f"{regime} budget of {propellant.routine_annual_m_s:,.0f} m/s. "
            f"Spending {rate_multiple:.1f} times the routine rate is itself the "
            "finding, whatever the individual manoeuvres were for."
        )
    return (
        f"{len(views)} confirmed manoeuvres over {span_days:.0f} days, "
        f"{above_routine} of them above the routine per-burn budget. "
        f"Consumption is {propellant.annual_rate_m_s:,.1f} m/s a year"
        + (f", {rate_multiple:.1f} times the routine {regime} figure."
           if rate_multiple is not None else ".")
    )


def _operational_signature(
    views: list[ManoeuvreView], propellant: PropellantAssessment, lon_range: float,
) -> str:
    """The one-line summary of what was seen, for the panel header."""
    if not views:
        return "Nothing resolved above the measured detection floor"
    counts: dict[str, int] = {}
    for v in views:
        counts[v.classification] = counts.get(v.classification, 0) + 1
    parts = [f"{n} {label}" for label, n in sorted(counts.items(), key=lambda x: -x[1])]
    parts.append(f"~{propellant.propellant_used_pct:.1f}% of the assumed tank")
    if lon_range > 0:
        parts.append(f"{lon_range:.1f}° of belt covered")
    slow = [v for v in views if v.burn_is_slow]
    if slow:
        parts.append(f"{len(slow)} needing over a day of continuous thrust")
    return " · ".join(parts)


@dataclass(frozen=True)
class _Components:
    """The three component assessments the narrative is written from.

    They are derived together in :func:`assess_pattern_of_life`, travel
    together from there, and every one of them is optional to the narrative in
    a different way, so they are passed as one value rather than as three
    positional arguments the caller has to keep in order.
    """

    anomaly:    AnomalyAssessment | None
    propellant: PropellantAssessment
    detection:  DetectionLimits | None


def _assess_intel(
    pol: Any, regime: str, views: list[ManoeuvreView], components: _Components,
) -> IntelAssessment:
    records = list(getattr(pol, "records", []) or [])
    span_days = float(getattr(pol, "span_days", 0.0) or 0.0)
    is_geo = regime.strip().upper() in ("GEO", "DEEP")

    last = records[-1] if records else None
    drift = getattr(last, "geo_drift_rate_deg_day", None) if last else None
    direction = _drift_direction(drift)

    lons = [r.geo_longitude_deg for r in records if r.geo_longitude_deg is not None]
    lon_range = (max(lons) - min(lons)) if len(lons) > 1 else 0.0

    pred_30, pred_60, pred_90 = _predicted_longitudes(last, drift)

    notable = [
        f"{p.start_epoch:%Y-%m-%d} to {p.end_epoch:%Y-%m-%d}: {p.direction} drift "
        f"{abs(p.distance_deg):.1f}° at {abs(p.rate_deg_day):.2f}°/day"
        for p in (getattr(pol, "drift_phases", []) or [])
        if p.direction != "STATIONARY" and abs(p.distance_deg) > _NOTABLE_DRIFT_DEGREES
    ][:8]

    above_routine = sum(1 for v in views if not v.is_routine)

    mission, bclass = _mission_profile(regime, is_geo, lon_range, views, above_routine)
    risk = _risk_with_posture_floor(components.anomaly, views)

    if not views and components.detection is not None:
        narrative = _quiet_narrative(components.detection, span_days)
    elif is_geo and lon_range > _GEO_ROAMER_DEGREES:
        narrative = _roamer_narrative(lon_range, span_days, direction, drift)
    else:
        narrative = _rate_narrative(
            regime, views, span_days, components.propellant, above_routine,
        )

    signature = _operational_signature(views, components.propellant, lon_range)

    return IntelAssessment(
        mission_profile=mission, behaviour_class=bclass, risk_level=risk,
        operational_signature=signature, anomaly_narrative=narrative,
        notable_periods=notable,
        predicted_lon_30d=pred_30, predicted_lon_60d=pred_60, predicted_lon_90d=pred_90,
        current_drift_dir=direction,
        current_drift_rate=round(drift, 3) if drift is not None else None,
    )
