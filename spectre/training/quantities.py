"""The quantities a mission computes at start, from the bound element sets, with the console's own code (SPC-248).

No briefing figure and no answer is typed into a mission file. A mission names quantities, each one of the functions
registered here with its arguments, and the mission engine computes them when the mission starts, from the element
sets bound to its roles, at the mission clock. Each figure is computed the way the console shows it to the operator:

● Sub-satellite longitude, inclination, period and regime: the element card's own functions
  (spectre.web.element_card), at the mission clock, which is the console's scenario time.
● Ranges and closest approaches: SGP4 on the bound sets, TEME positions, a 2-minute scan refined to the second.
● Red objects in a regime: the Threat Sweep's own Target Group count (routes.threat._hrr_group_counts).
● Asset Screening's figures: the screen's own candidate selection, assessment and ranking, run on the training state
  at the wall clock, which is when the screen runs (routes.threat.threat_screen).
● Intelligence options: the records of spectre/data/adversary_intel.json, quoted, never edited.

A choice quantity returns its options as [{id, label, correct}], exactly one correct.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from spectre.astro.constants import classify_orbit_regime
from spectre.astro.pattern_of_life import _satrec_to_record as tle_record
from spectre.astro.propagator import TLEOrbit, state_to_keplerian
from spectre.data.intel import get_intel
from spectre.web.element_card import sub_satellite_longitude_deg

#: The regimes the regime question offers, in the element card's own words.
REGIMES = ("LEO", "MEO", "GEO", "HEO")
#: The five verdict bands Asset Screening prints, worst first.
VERDICTS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL")
#: The intelligence record's threat levels.
THREAT_LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
#: A sidereal day in minutes, to four places: the period of an object that holds its longitude.
SIDEREAL_DAY_MIN = 1436.0682
#: Longitude drift slower than this, degrees a sidereal day, reads as holding station: under half the last place the
#: element card prints a longitude to.
_HOLDING_DEG_DAY = 0.004
_SCAN_STEP_S = 120
_MAX_OPTIONS = 4


class QuantityError(ValueError):
    """A quantity could not be computed from the data bound: the mission cannot start on it."""


@dataclass(frozen=True)
class Bound:
    """One role's object: its catalogue number, name, side, the element set bound and where that set came from."""

    role: str
    satno: str
    name: str
    side: str
    tle: str
    data_mode: str
    country: str = ""


@dataclass
class Context:
    """What a quantity reads: the bound roles, the mission clock, the training state and the wall clock."""

    roles: dict[str, Bound]
    clock: datetime
    state: Any
    now: datetime
    cache: dict[str, Any] = field(default_factory=dict)

    def role(self, name: str) -> Bound:
        return self.roles[name]


Options = list[dict[str, Any]]


def _option(value: str, correct: str) -> dict[str, Any]:
    return {"id": value.lower().replace(" ", "-").replace("/", "-"), "label": value, "correct": value == correct}


def _options(values: list[str], correct: str) -> Options:
    """The options *values*, in the order given, with *correct* marked; *correct* is added when absent."""
    if correct not in values:
        values = [*values[: _MAX_OPTIONS - 1], correct]
    return [_option(v, correct) for v in values]


# ── The element card's figures ──────────────────────────────────────────────


def subsat_longitude(ctx: Context, role: str) -> float:
    """The longitude under *role* at the mission clock, degrees east in [-180, 180), as the element card shows it."""
    return sub_satellite_longitude_deg(ctx.role(role).tle, ctx.clock)


def inclination_deg(ctx: Context, role: str) -> float:
    """The element set's mean inclination, degrees, as the element card shows it."""
    return float(tle_record(ctx.role(role).tle).inc_deg)


def period_min(ctx: Context, role: str) -> float:
    """The element set's period, minutes, from its mean motion, as the element card shows it."""
    return float(tle_record(ctx.role(role).tle).period_min)


def regime_of(tle: str) -> str:
    """The element card's regime for *tle*."""
    return str(tle_record(tle).regime)


def regime_options(ctx: Context, role: str) -> Options:
    """LEO, MEO, GEO and HEO, with the element card's regime for *role* marked."""
    return _options(list(REGIMES), regime_of(ctx.role(role).tle))


def drift_deg_day(tle: str, at: datetime) -> float:
    """How far the longitude under the object moves over one sidereal day from *at*, degrees, east positive, by SGP4."""
    later = at + timedelta(minutes=SIDEREAL_DAY_MIN)
    moved = sub_satellite_longitude_deg(tle, later) - sub_satellite_longitude_deg(tle, at)
    return (moved + 180.0) % 360.0 - 180.0


def drift_word(tle: str, at: datetime) -> str:
    """Which way the object drifts in longitude over a sidereal day: "east", "west", or "holds station"."""
    rate = drift_deg_day(tle, at)
    if abs(rate) < _HOLDING_DEG_DAY:
        return "holds station"
    return "east" if rate > 0 else "west"


def drift_options(ctx: Context, role: str) -> Options:
    """East, west and holds station, with the way *role* drifts over a sidereal day from the clock marked."""
    return _options(["east", "west", "holds station"], drift_word(ctx.role(role).tle, ctx.clock))


def longitude_drift(ctx: Context, role: str) -> float:
    """How far *role*'s sub-satellite longitude moves over a sidereal day from the clock, degrees, east positive."""
    return drift_deg_day(ctx.role(role).tle, ctx.clock)


def longitude_words(ctx: Context, role: str) -> str:
    """*role*'s sub-satellite longitude at the clock as the element card writes it: "79.72° E"."""
    from spectre.web.element_card import longitude_text

    return longitude_text(subsat_longitude(ctx, role))


# ── Ranges ───────────────────────────────────────────────────────────────────


def range_at(tle_a: str, tle_b: str, at: datetime) -> float:
    """The distance between the two objects at *at*, km, from SGP4."""
    return float(np.linalg.norm(TLEOrbit(tle_a).propagate(at).r - TLEOrbit(tle_b).propagate(at).r))


def range_km(ctx: Context, a: str, b: str, hours: float = 0.0) -> float:
    """The range from *a* to *b*, km, *hours* after the mission clock."""
    return range_at(ctx.role(a).tle, ctx.role(b).tle, ctx.clock + timedelta(hours=hours))


def range_trend(ctx: Context, a: str, b: str, hours: float) -> str:
    """"closing" when the range in *hours* is less than now, else "opening"."""
    return "closing" if range_km(ctx, a, b, hours) < range_km(ctx, a, b) else "opening"


def closest_approach(tle_a: str, tle_b: str, start: datetime, hours: float) -> tuple[datetime, float]:
    """When, and how close, *a* and *b* come in the *hours* from *start*: a 2-minute scan refined to the second."""
    a, b = TLEOrbit(tle_a), TLEOrbit(tle_b)

    def dist(seconds: float) -> float:
        t = start + timedelta(seconds=seconds)
        return float(np.linalg.norm(a.propagate(t).r - b.propagate(t).r))

    span = int(hours * 3600)
    best = min(range(0, span + 1, _SCAN_STEP_S), key=dist)
    lo, hi = max(0.0, best - _SCAN_STEP_S), min(float(span), best + _SCAN_STEP_S)
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    while hi - lo > 1.0:
        left, right = hi - golden * (hi - lo), lo + golden * (hi - lo)
        if dist(left) < dist(right):
            hi = right
        else:
            lo = left
    seconds = round((lo + hi) / 2.0)
    return start + timedelta(seconds=seconds), dist(seconds)


def _approach(ctx: Context, a: str, b: str, hours: float) -> tuple[datetime, float]:
    key = f"tca:{a}:{b}:{hours}"
    if key not in ctx.cache:
        ctx.cache[key] = closest_approach(ctx.role(a).tle, ctx.role(b).tle, ctx.clock, hours)
    held: tuple[datetime, float] = ctx.cache[key]
    return held


def closest_approach_km(ctx: Context, a: str, b: str, hours: float) -> float:
    """How close *a* and *b* come in the *hours* after the mission clock, km."""
    return _approach(ctx, a, b, hours)[1]


def closest_approach_hours(ctx: Context, a: str, b: str, hours: float) -> float:
    """How long after the mission clock *a* and *b* come closest within *hours*, hours."""
    return (_approach(ctx, a, b, hours)[0] - ctx.clock).total_seconds() / 3600.0


def closest_approach_utc(ctx: Context, a: str, b: str, hours: float) -> str:
    """When *a* and *b* come closest within *hours* of the clock, as "01 Oct 12:34 UTC"."""
    return _approach(ctx, a, b, hours)[0].strftime("%d %b %H:%M UTC")


# ── The Threat Sweep's Target Group ─────────────────────────────────────────


def sweep_regime(tle: str, at: datetime) -> str:
    """The regime the Threat Sweep filters targets by for a red satellite: its osculating orbit's, at *at*."""
    kep = state_to_keplerian(TLEOrbit(tle).propagate(at))
    return classify_orbit_regime(kep.a, kep.ecc)


def red_count_in_regime(ctx: Context, role: str) -> int:
    """How many red watchlist objects the Threat Sweep's Target Group counts in *role*'s regime (Red HRR rows)."""
    from spectre.web.routes.threat import _hrr_group_counts  # the console's own count

    _, red = _hrr_group_counts(ctx.state, regime=sweep_regime(ctx.role(role).tle, ctx.now))
    return sum(count for _, count in red)


# ── Asset Screening ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Screened:
    """One Asset Screening the operator ran: when, how many candidates it considered, and the actors as it ranked
    them, each (catalogue number, name, verdict label), worst first."""

    at: str
    considered: int
    ranked: tuple[tuple[str, str, str], ...]

    @classmethod
    def of(cls, record: Any) -> Screened:
        """The screening in the console's record (spectre.web.planning_state.ScreeningRecord)."""
        return cls(record.at.isoformat(), int(record.considered), tuple(tuple(r) for r in record.ranked))

    def as_json(self) -> dict[str, Any]:
        return {"at": self.at, "considered": self.considered, "ranked": [list(r) for r in self.ranked]}

    @classmethod
    def from_json(cls, held: dict[str, Any]) -> Screened:
        return cls(str(held["at"]), int(held["considered"]), tuple(tuple(r) for r in held["ranked"]))


#: What a verdict question offers for an actor the screening did not rank (beyond the budget, or left out).
NOT_RANKED = "Not ranked"


def screening_candidates(screened: Screened, roles: dict[str, Bound]) -> int:
    """How many candidate actors the operator's screening considered."""
    del roles
    return screened.considered


def screening_top_options(screened: Screened, roles: dict[str, Bound]) -> Options:
    """The four actors the operator's screening ranks highest, by name, its first marked."""
    del roles
    if not screened.ranked:
        return [_option(NOT_RANKED, NOT_RANKED)]
    names = [name for _, name, _ in screened.ranked[:_MAX_OPTIONS]]
    return [_option(n, screened.ranked[0][1]) for n in sorted(names)]


def screening_verdict_options(screened: Screened, roles: dict[str, Bound], actor: str) -> Options:
    """The five verdict bands and Not ranked, with what the operator's screening gives *actor* marked."""
    satno = roles[actor].satno
    verdict = next((label for number, _, label in screened.ranked if number == satno), NOT_RANKED)
    return [_option(v, verdict) for v in (*VERDICTS, NOT_RANKED)]


def screening_rank(screened: Screened, roles: dict[str, Bound], actor: str) -> int:
    """Where the operator's screening ranks *actor*, as its # column counts, or 0 when it does not rank it."""
    satno = roles[actor].satno
    return next((i + 1 for i, (number, _, _) in enumerate(screened.ranked) if number == satno), 0)


# ── The intelligence record ──────────────────────────────────────────────────


def _record(ctx: Context, role: str) -> dict[str, Any]:
    record = get_intel(ctx.role(role).satno)
    if record is None:
        raise QuantityError(f"{ctx.role(role).name} has no intelligence record")
    return record


def intel_threat_options(ctx: Context, role: str) -> Options:
    """The record's assessed threat for *role*, marked, among the assessments of the red watchlist objects nearest
    it at the clock that carry a different one: its neighbours' roles, not an alphabetical list. Ordered by the
    neighbours' distance, the object's own placed by its catalogue number, so the right answer has no fixed place."""
    bound = ctx.role(role)
    own = str(_record(ctx, role)["assessed_threat"])
    neighbours: list[tuple[float, str]] = []
    for obj in ctx.state.hrr_objects:
        satno = str(obj.get("satno") or "").strip()
        record = get_intel(satno) if satno != bound.satno else None
        tle = ctx.state.hrr_tle_cache.get(satno)
        if record is None or not tle or str(record.get("assessed_threat", "")) in ("", own):
            continue
        neighbours.append((range_at(bound.tle, tle, ctx.clock), str(record["assessed_threat"])))
    distractors = list(dict.fromkeys(threat for _, threat in sorted(neighbours)))[: _MAX_OPTIONS - 1]
    labels = list(distractors)
    labels.insert(int(bound.satno) % (len(distractors) + 1), own)
    return [_option(v, own) for v in labels]


def intel_level_options(ctx: Context, role: str) -> Options:
    """CRITICAL, HIGH, MEDIUM and LOW, with the record's threat level for *role* marked."""
    return _options(list(THREAT_LEVELS), str(_record(ctx, role)["threat_level"]))


# ── The registry ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QuantityFn:
    """A registered quantity function: which of its arguments name roles, which are constants, and its kind.

    A *screened* one is not computed at start: it is read from the operator's own Asset Screening of the role its
    *screened* argument names, once they have run it (Asset Screening ranks at the wall clock, and its first-ranked
    actor can change within minutes, so a screening the engine ran at start could mark a correct reading wrong).
    """

    fn: Callable[..., Any] | Callable[..., Awaitable[Any]]
    roles: tuple[str, ...]
    constants: tuple[str, ...] = ()
    kind: str = "number"   # "number", "options" or "text"
    screened: str = ""


QUANTITIES: dict[str, QuantityFn] = {
    "subsat_longitude": QuantityFn(subsat_longitude, ("role",)),
    "longitude_words": QuantityFn(longitude_words, ("role",), kind="text"),
    "longitude_drift": QuantityFn(longitude_drift, ("role",)),
    "inclination_deg": QuantityFn(inclination_deg, ("role",)),
    "period_min": QuantityFn(period_min, ("role",)),
    "regime_options": QuantityFn(regime_options, ("role",), kind="options"),
    "drift_options": QuantityFn(drift_options, ("role",), kind="options"),
    "range_km": QuantityFn(range_km, ("a", "b"), ("hours",)),
    "range_trend": QuantityFn(range_trend, ("a", "b"), ("hours",), kind="text"),
    "closest_approach_km": QuantityFn(closest_approach_km, ("a", "b"), ("hours",)),
    "closest_approach_hours": QuantityFn(closest_approach_hours, ("a", "b"), ("hours",)),
    "closest_approach_utc": QuantityFn(closest_approach_utc, ("a", "b"), ("hours",), kind="text"),
    "red_count_in_regime": QuantityFn(red_count_in_regime, ("role",)),
    "screening_candidates": QuantityFn(screening_candidates, ("asset",), screened="asset"),
    "screening_top_options": QuantityFn(screening_top_options, ("asset",), kind="options", screened="asset"),
    "screening_verdict_options": QuantityFn(screening_verdict_options, ("asset", "actor"), kind="options",
                                            screened="asset"),
    "screening_rank": QuantityFn(screening_rank, ("asset", "actor"), screened="asset"),
    "intel_threat_options": QuantityFn(intel_threat_options, ("role",), kind="options"),
    "intel_level_options": QuantityFn(intel_level_options, ("role",), kind="options"),
}


async def compute(ctx: Context, name: str, args: dict[str, Any]) -> Any:
    """The value of the registered quantity *name* with *args*, awaited when the function is a coroutine."""
    value = QUANTITIES[name].fn(ctx, **args)
    if inspect.isawaitable(value):
        value = await value
    return value


def from_screening(name: str, args: dict[str, Any], screened: Screened, roles: dict[str, Bound]) -> Any:
    """The screened quantity *name* with *args*, read from the operator's screening *screened*."""
    entry = QUANTITIES[name]
    rest = {k: v for k, v in args.items() if k != entry.screened}
    return entry.fn(screened, roles, **rest)


def now_utc() -> datetime:
    """The wall clock, a seam for tests."""
    return datetime.now(UTC)
