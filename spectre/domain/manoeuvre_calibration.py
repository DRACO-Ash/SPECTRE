"""Realistic delta-v bands per manoeuvre kind, per regime, in metres per second.

Why this exists
---------------
The sweep reported a delta-v figure and banded it on four global constants:

    dv < 200 m/s -> CRITICAL, < 500 -> HIGH, < 1000 -> MEDIUM, else LOW

Measured against what satellites actually do, that band is saturated. Every
real counterspace manoeuvre on open record sits below 200 m/s:

    GEO relocation, 62 deg in 30 days (Luch/Olymp-K 2, 2025)      11 m/s
    GEO graveyard raise, >400 km (Luch/Olymp-K 1, 2025)           15 m/s
    LEO inspector campaign (Cosmos 2576 vs USA 314, 2024-25)   25-30 m/s
    GEO dock and tow (SJ-21 / Beidou-2 G2, 2022)                 ~60 m/s
    GEO dock and tow, round trip                                ~120 m/s
    Rapid GEO relocation, 90 deg in 3 days                      ~170 m/s

So the old thresholds scored a routine commercial repositioning and a hostile
rapid closure identically: both CRITICAL. A band that returns the same answer
for everything is not a measurement.

Worse, the sweep's default budget was 3,000 m/s. That is larger than the entire
discretionary reserve of every flown platform class except a hybrid servicer at
its upper bound, so the sweep was accepting as feasible intercepts that no real
object could fly.

What this module does
---------------------
Replaces the global constants with bands that depend on WHERE the object is and
WHAT KIND of manoeuvre it is being asked to perform, because 50 m/s is one
year of routine station-keeping in GEO and a major event in MEO.

Three postures, as the operator asked for them:

    BENIGN      efficient, minimum energy, long timeline. Indistinguishable
                from routine operations. The actor is not trying to surprise
                anyone and is conserving propellant.
    ANNOYANCE   deliberate and noticed, but affordable and repeatable.
                Shadowing, loitering, inspection, moderate repositioning. Real
                propellant spent to be somewhere you would rather they were
                not, and they could do it again next month.
    AGGRESSIVE  short timeline, high energy, chosen for effect rather than
                economy. Usually a meaningful fraction of the platform's whole
                remaining life, spent at once.

Every boundary below is traceable to a named table or observed case in
"Satellite Manoeuvre Delta-v: Feasibility Above 0.5 km/s and Budgets by Regime"
(Bluestaq Limited Space Watch, v1.0, 13 October 2026), cited inline as
Table 3 (station-keeping), Table 4 (aggressive manoeuvres) or Table 2
(platform ceilings).

What these bands do NOT cover
-----------------------------
They describe the behaviour of an object ALREADY ON STATION. They do not
describe commissioning: electric orbit raising from geostationary transfer
orbit costs 1,500-2,500 m/s and is entirely routine, and a Starlink ascent
costs about 130 m/s. The assessment separates these explicitly, and so does
this module by scope: the sweep asks what a red object must spend to reach a
blue asset from where it is now, which is never a commissioning burn. Reading a
posture off an orbit-raising manoeuvre would be a category error.

Units
-----
Everything in this module is METRES PER SECOND. The astro package computes in
km/s because MU_EARTH is in km^3/s^2 and SGP4 returns km and km/s; that is
left alone deliberately. Conversion happens once, at this boundary, in
``from_km_s``. There is no other conversion point, by design: a second one is
how a value ends up 1,000,000x wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ManoeuvreKind",
    "PlatformClass",
    "Posture",
    "PostureAssessment",
    "classify_posture",
    "fastest_delivery_hours",
    "from_km_s",
    "kind_for_method",
    "station_keeping_m_s_per_year",
]

#: Metres per second in one kilometre per second. The single conversion factor.
_M_S_PER_KM_S: float = 1000.0


def from_km_s(value_km_s: float) -> float:
    """Convert a km/s figure out of the astro layer into m/s for the operator.

    This is the ONLY place the conversion is written. Everything downstream of
    it is m/s and says so in its name.
    """
    return value_km_s * _M_S_PER_KM_S


class Posture(Enum):
    """What a given delta-v cost says about how the actor is behaving."""

    BENIGN = "BENIGN"
    ANNOYANCE = "ANNOYANCE"
    AGGRESSIVE = "AGGRESSIVE"
    #: Above any flown platform's discretionary reserve. Needs a tug, an
    #: orbital transfer vehicle, a kick stage, or refuelling.
    BEYOND_PLATFORM = "BEYOND PLATFORM"

    @property
    def label(self) -> str:
        return self.value


class ManoeuvreKind(Enum):
    """What the manoeuvre IS, operationally, rather than how it is solved.

    Two solvers that both answer "get from this orbit to that one by changing
    altitude" are the same kind, whether one is Hohmann and the other
    bi-elliptic. The cost calibration attaches to the kind, not the method.
    """

    ALTITUDE_CHANGE = "altitude change"
    PLANE_CHANGE = "plane change"
    PHASING = "phasing or relocation"
    PROXIMITY = "proximity operation"
    RENDEZVOUS = "rendezvous"


#: Threat-sweep method name -> operational kind.
#:
#: In GEO, phasing IS longitude relocation, which is why the GEO PHASING band
#: below carries the relocation figures from Table 4 rather than LEO's.
_METHOD_TO_KIND: dict[str, ManoeuvreKind] = {
    "hohmann": ManoeuvreKind.ALTITUDE_CHANGE,
    "bielliptic": ManoeuvreKind.ALTITUDE_CHANGE,
    "plane_change": ManoeuvreKind.PLANE_CHANGE,
    "phasing": ManoeuvreKind.PHASING,
    "lambert": ManoeuvreKind.RENDEZVOUS,
    "min_time": ManoeuvreKind.RENDEZVOUS,
    "vbar_hop": ManoeuvreKind.PROXIMITY,
    "hbar_hop": ManoeuvreKind.PROXIMITY,
}


def kind_for_method(method: str) -> ManoeuvreKind:
    """Map a solver name to the kind of manoeuvre it represents.

    An unrecognised method falls back to RENDEZVOUS, the most permissive band,
    so a new solver is never accidentally scored as more alarming than it is.
    """
    return _METHOD_TO_KIND.get(method.strip().lower(), ManoeuvreKind.RENDEZVOUS)


@dataclass(frozen=True)
class _Band:
    """Upper bound of BENIGN and of ANNOYANCE, in m/s, with its provenance."""

    benign_max_m_s: float
    annoyance_max_m_s: float
    basis: str


# ─────────────────────────────────────────────────────────────────────────────
# The bands. Keyed (regime, kind). Every figure cited.
# ─────────────────────────────────────────────────────────────────────────────

_BANDS: dict[tuple[str, ManoeuvreKind], _Band] = {
    # ── GEO ──────────────────────────────────────────────────────────────────
    ("GEO", ManoeuvreKind.PHASING): _Band(
        15.0, 100.0,
        "Table 4: 6 m/s for 10 deg in 10 days, 11 m/s for 62 deg in 30 days "
        "(matches the observed Luch/Olymp-K 2 move), 34 m/s for 180 deg in 30 "
        "days, 170 m/s for 90 deg in 3 days. The 100 m/s ceiling is the watch "
        "floor the assessment recommends for GEO, in place of 500 m/s.",
    ),
    ("GEO", ManoeuvreKind.PLANE_CHANGE): _Band(
        50.0, 160.0,
        "Table 4: 54 m/s per degree at GEO. 50 m/s is one year of north-south "
        "station-keeping (Table 3: 43-50 m/s/yr), so below it a plane change "
        "is indistinguishable from routine. 160 m/s is about 3 degrees, "
        "already above a chemical comsat's entire discretionary reserve "
        "(Table 2: 50-200 m/s).",
    ),
    ("GEO", ManoeuvreKind.PROXIMITY): _Band(
        10.0, 60.0,
        "Table 4: RPO burns of cm/s to m/s; GEO campaigns 10-60 m/s; dock and "
        "tow 60-120 m/s. The SJ-21 tow of Beidou-2 G2 cost about 60 m/s to "
        "raise and about 120 m/s round trip.",
    ),
    ("GEO", ManoeuvreKind.ALTITUDE_CHANGE): _Band(
        20.0, 60.0,
        "Table 3: GEO graveyard raise 7-11 m/s. Luch/Olymp-K 1 rose more than "
        "400 km above the protected region for about 15 m/s.",
    ),
    ("GEO", ManoeuvreKind.RENDEZVOUS): _Band(
        25.0, 120.0,
        "A rendezvous combines relocation with proximity work, so it is "
        "bounded below by the GEO relocation band and above by the observed "
        "dock-and-tow round-trip figure of about 120 m/s (Table 4).",
    ),
    # ── LEO ──────────────────────────────────────────────────────────────────
    ("LEO", ManoeuvreKind.ALTITUDE_CHANGE): _Band(
        60.0, 140.0,
        "Table 4: 500 to 600 km costs about 55 m/s; 300 to 530 km about 130 "
        "m/s. Starlink orbit raising is about 130 m/s.",
    ),
    ("LEO", ManoeuvreKind.PLANE_CHANGE): _Band(
        15.0, 70.0,
        "Table 4: 133 m/s per degree at LEO. Cosmos 2576 changed inclination "
        "by 0.1 degree, about 13 m/s. The 70 m/s ceiling is about 0.53 "
        "degrees.",
    ),
    ("LEO", ManoeuvreKind.PHASING): _Band(
        50.0, 200.0,
        "Table 4: 180 deg of phasing in about one day costs about 500 m/s, "
        "while practical rephasing over 3 to 8 days costs far less.",
    ),
    ("LEO", ManoeuvreKind.PROXIMITY): _Band(
        5.0, 30.0,
        "Table 4: collision avoidance is cm/s to about 1 m/s per burn. The "
        "observed Cosmos 2576 inspector campaign cost 25-30 m/s.",
    ),
    ("LEO", ManoeuvreKind.RENDEZVOUS): _Band(
        30.0, 150.0,
        "Bounded by the LEO altitude-change and phasing bands (Table 4).",
    ),
    # ── MEO ──────────────────────────────────────────────────────────────────
    ("MEO", ManoeuvreKind.ALTITUDE_CHANGE): _Band(
        25.0, 150.0,
        "Table 3: MEO disposal is 6-23 m/s to the graveyard and 150-290 m/s "
        "for direct re-entry.",
    ),
    ("MEO", ManoeuvreKind.PLANE_CHANGE): _Band(
        35.0, 140.0,
        "Table 6 gives about 7 degrees for 500 m/s at MEO, so about 71 m/s "
        "per degree. The bounds are about 0.5 and 2 degrees.",
    ),
    ("MEO", ManoeuvreKind.PHASING): _Band(
        25.0, 100.0,
        "Table 6: a navigation slot change costs tens of m/s.",
    ),
    ("MEO", ManoeuvreKind.PROXIMITY): _Band(
        5.0, 30.0,
        "No MEO-specific proximity figure is published. The LEO band from "
        "Table 4 (collision avoidance cm/s to about 1 m/s; the Cosmos 2576 "
        "campaign 25-30 m/s) is carried across, because proximity burns scale "
        "with relative rather than orbital velocity.",
    ),
    ("MEO", ManoeuvreKind.RENDEZVOUS): _Band(
        30.0, 150.0,
        "Bounded by the MEO slot-change and disposal figures (Tables 3 and 6).",
    ),
    # ── HEO and GTO ──────────────────────────────────────────────────────────
    ("HEO", ManoeuvreKind.ALTITUDE_CHANGE): _Band(
        75.0, 300.0,
        "Table 3: HEO and Molniya station-keeping is 50-70 m/s/yr. Table 6: "
        "apogee and perigee reshaping costs hundreds of m/s, and a full HEO to "
        "LEO change costs about 2,500 m/s.",
    ),
    ("HEO", ManoeuvreKind.PLANE_CHANGE): _Band(
        75.0, 300.0,
        "Table 3: HEO and Molniya station-keeping is 50-70 m/s/yr, which is "
        "argument-of-perigee and node control, so a plane change inside that "
        "is routine. Plane change at HEO is cheapest at apogee where orbital "
        "speed is low, so the upper bound is set by the Table 6 reshaping cost "
        "of hundreds of m/s rather than by a per-degree figure.",
    ),
    ("HEO", ManoeuvreKind.PHASING): _Band(
        75.0, 300.0,
        "Table 3: HEO and Molniya station-keeping is 50-70 m/s/yr. Table 6: "
        "apogee and perigee reshaping, which is how phasing is bought in a "
        "highly elliptical orbit, costs hundreds of m/s.",
    ),
    ("HEO", ManoeuvreKind.PROXIMITY): _Band(
        10.0, 60.0,
        "Proximity burns scale with relative velocity, so the GEO campaign "
        "band is carried across (Table 4).",
    ),
    ("HEO", ManoeuvreKind.RENDEZVOUS): _Band(
        75.0, 300.0,
        "Table 6: a rendezvous in a highly elliptical orbit is bought by "
        "apogee and perigee reshaping, which costs hundreds of m/s, against a "
        "station-keeping baseline of 50-70 m/s/yr (Table 3).",
    ),
}

# GTO is dynamically a trans-belt orbit like HEO, so it shares HEO's bands.
for _kind in ManoeuvreKind:
    _BANDS[("GTO", _kind)] = _BANDS[("HEO", _kind)]

#: Fallback when the regime is unrecognised or DEEP. Deliberately the widest
#: band in the table, so an unclassified object is never scored as more
#: alarming than the evidence supports.
_DEFAULT_BAND = _Band(
    75.0, 300.0,
    "Regime not recognised; the widest published band (HEO reshaping, Table 6) "
    "is used so an unclassified object is not over-scored.",
)


# ─────────────────────────────────────────────────────────────────────────────
# Routine station-keeping, for the "how many years of its budget is this?" line
# ─────────────────────────────────────────────────────────────────────────────

#: Annual station-keeping budget by regime, m/s per year (Table 3).
_STATION_KEEPING_M_S_PER_YEAR: dict[str, float] = {
    # 400-500 km averages under 25 m/s/yr and reaches about 100 at solar
    # maximum; the average is used.
    "LEO": 25.0,
    "MEO": 1.0,
    # 43-50 m/s/yr north-south plus 1-5 m/s/yr east-west.
    "GEO": 48.0,
    "HEO": 60.0,
    "GTO": 60.0,
}


def station_keeping_m_s_per_year(regime: str) -> float | None:
    """Routine annual station-keeping for *regime*, or None if not published."""
    return _STATION_KEEPING_M_S_PER_YEAR.get(regime.strip().upper())


# ─────────────────────────────────────────────────────────────────────────────
# Platform classes: what an object can actually spend, and how fast
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlatformClass:
    """A platform's discretionary reserve and the rate it can spend it.

    The rate matters as much as the reserve, and the application previously
    modelled neither. An all-electric GEO bus holds up to 1,500 m/s of margin
    but thrusts at about 0.27 N on roughly 3,000 kg, so it accelerates at
    9e-5 m/s^2 and needs about 64 DAYS to deliver 500 m/s. An impulsive
    transfer solution claiming that object arrives in six hours is not wrong
    arithmetic; it is the wrong question.
    """

    name: str
    discretionary_min_m_s: float
    discretionary_max_m_s: float
    typical_acceleration_m_s2: float
    basis: str

    def minimum_burn_hours(self, delta_v_m_s: float) -> float:
        """Hours of continuous thrust needed to deliver *delta_v_m_s*."""
        if self.typical_acceleration_m_s2 <= 0.0:
            return float("inf")
        return delta_v_m_s / self.typical_acceleration_m_s2 / 3600.0

    def can_deliver_within(self, delta_v_m_s: float, hours_available: float) -> bool:
        """True when this platform could both afford and physically deliver it.

        Affordability alone is not enough: the burn has to fit in the time the
        transfer solution assumes.
        """
        if delta_v_m_s > self.discretionary_max_m_s:
            return False
        return self.minimum_burn_hours(delta_v_m_s) <= hours_available


#: Table 2, with thrust and mass figures from Sections 1 and 2.
PLATFORM_CLASSES: tuple[PlatformClass, ...] = (
    PlatformClass(
        "Chemical GEO comsat, on station", 50.0, 200.0, 3.3e-3,
        "Table 2: about 2,500 m/s total, of which GTO to GEO takes 1,500-1,800 "
        "and 15 years of north-south keeping takes about 750, leaving 50-200 "
        "m/s discretionary. Acceleration from a 10 N on-station thruster on "
        "about 3,000 kg.",
    ),
    PlatformClass(
        "All-electric GEO bus", 500.0, 1500.0, 9.0e-5,
        "Table 2: margin up to about 500-1,500 m/s at millinewton thrust. "
        "Acceleration from a BPT-4000 class thruster at about 0.27 N on about "
        "3,000 kg, so weeks to months per move.",
    ),
    PlatformClass(
        "LEO smallsat, electric", 500.0, 2500.0, 2.1e-4,
        "Table 2: 500-2,500 m/s total, mostly drag make-up, collision "
        "avoidance and deorbit. Acceleration from the Starlink V2 Mini argon "
        "Hall thruster at 170 mN on about 800 kg.",
    ),
    PlatformClass(
        "Dedicated inspector or RPO platform, chemical", 800.0, 1600.0, 4.0e-3,
        "Table 2: 800-1,600 m/s total at Isp 220-320 s and 30-40 per cent "
        "propellant; observed campaigns cost 10-120 m/s each.",
    ),
    PlatformClass(
        "Hybrid servicer, MEV class", 1000.0, 3000.0, 1.0e-4,
        "Table 2: 1 to 3 km/s plausible, electric transfers with chemical "
        "proximity work. Unpublished, so treat as indicative.",
    ),
    PlatformClass(
        "Orbital transfer vehicle, storable chemical", 500.0, 1200.0, 5.0e-2,
        "Table 2 and Section 1: Impulse Space Mira is specified at 500 m/s "
        "with 300 kg and 900 m/s with 100 kg.",
    ),
)

#: The most capable flown platform's upper reserve. Above this, no object on
#: open record could perform the manoeuvre without a tug or refuelling.
#: Excludes the cryogenic kick stage (3,000-9,000 m/s), which has not flown.
_BEYOND_ANY_FLOWN_PLATFORM_M_S: float = 3000.0

#: Default sweep budget, m/s. The assessment's bottom line is that any inferred
#: on-station delta-v of 500 m/s or more, outside orbit raising, is a strong
#: anomaly flag. That makes 500 the right outer edge of the realistic envelope:
#: it sits above every manoeuvre on open record (the largest is about 170 m/s)
#: and at the lower bound of what an orbital transfer vehicle offers.
DEFAULT_SWEEP_BUDGET_M_S: float = 500.0


def fastest_delivery_hours(delta_v_m_s: float) -> tuple[float, str]:
    """Shortest time ANY flown platform class could deliver *delta_v_m_s*.

    Returns the hours and the name of the class that achieves it.

    The transfer solvers are impulsive: they assume the whole burn happens at a
    point. Over six hours against a chemical platform that is a fair
    approximation. Against an all-electric bus thrusting at 0.27 N it is not an
    approximation at all, it is the wrong question, because that platform needs
    about 64 days to deliver 500 m/s however much margin it holds.

    So a transfer whose time of flight is shorter than this figure cannot be
    flown by anything currently in orbit, whatever the delta-v arithmetic says.
    That is a physical filter, and it is independent of knowing which platform
    the object actually is.
    """
    affordable = [p for p in PLATFORM_CLASSES if delta_v_m_s <= p.discretionary_max_m_s]
    if not affordable:
        return (float("inf"), "none: beyond every flown platform's reserve")
    best = min(affordable, key=lambda p: p.minimum_burn_hours(delta_v_m_s))
    return (best.minimum_burn_hours(delta_v_m_s), best.name)


@dataclass(frozen=True)
class PostureAssessment:
    """What a delta-v figure means, with the reasoning kept visible."""

    posture: Posture
    delta_v_m_s: float
    regime: str
    kind: ManoeuvreKind
    benign_max_m_s: float
    annoyance_max_m_s: float
    basis: str
    station_keeping_years: float | None
    rationale: str

    @property
    def posture_label(self) -> str:
        return self.posture.label


def classify_posture(
    delta_v_m_s: float,
    regime: str,
    kind: ManoeuvreKind,
) -> PostureAssessment:
    """Say what *delta_v_m_s* means for this kind of manoeuvre in this regime.

    The same number means different things in different places. 50 m/s is one
    year of routine station-keeping in GEO and fifty years of it in MEO, so a
    single global threshold cannot be right in both.
    """
    regime_key = regime.strip().upper()
    band = _BANDS.get((regime_key, kind), _DEFAULT_BAND)

    if delta_v_m_s >= _BEYOND_ANY_FLOWN_PLATFORM_M_S:
        posture = Posture.BEYOND_PLATFORM
    elif delta_v_m_s <= band.benign_max_m_s:
        posture = Posture.BENIGN
    elif delta_v_m_s <= band.annoyance_max_m_s:
        posture = Posture.ANNOYANCE
    else:
        posture = Posture.AGGRESSIVE

    sk = station_keeping_m_s_per_year(regime_key)
    years = (delta_v_m_s / sk) if sk else None

    descriptor = {
        Posture.BENIGN: (
            "within what this object spends on routine operations, so the "
            "manoeuvre is efficient and indistinguishable from normal activity"
        ),
        Posture.ANNOYANCE: (
            "above routine but affordable and repeatable, consistent with "
            "deliberate shadowing, inspection or repositioning"
        ),
        Posture.AGGRESSIVE: (
            "well above what routine operations require, consistent with a "
            "short-notice manoeuvre chosen for effect rather than economy"
        ),
        Posture.BEYOND_PLATFORM: (
            "beyond the discretionary reserve of every platform class on open "
            "record, so it implies a tug, an orbital transfer vehicle, a kick "
            "stage, or in-orbit refuelling"
        ),
    }[posture]

    # An unknown regime must not render as "for a rendezvous in  is BENIGN".
    where = f" in {regime_key}" if regime_key else " (regime unknown)"
    rationale = (
        f"{delta_v_m_s:.0f} m/s for a {kind.value}{where} is "
        f"{posture.label}: {descriptor}."
    )
    if years is not None and years >= 0.1:
        rationale += (
            f" That is {years:.1f} years of this regime's routine "
            f"station-keeping budget ({sk:.0f} m/s per year), spent at once."
        )

    return PostureAssessment(
        posture=posture,
        delta_v_m_s=delta_v_m_s,
        regime=regime_key,
        kind=kind,
        benign_max_m_s=band.benign_max_m_s,
        annoyance_max_m_s=band.annoyance_max_m_s,
        basis=band.basis,
        station_keeping_years=years,
        rationale=rationale,
    )
