"""Interactions: what a satellite has approached, counted only when a burn of its own explains it.

Concept section 4.9 (docs/threat_confidence_concept.md). An edge from an
object v to a target x exists only when it is manoeuvre-attributable: a
confirmed burn by v preceded the approach within 7 days, and the approach
is closer than it was before the burn. A pass that orbital mechanics would
have brought anyway, with no burn behind it, adds nothing.

SPC-172 reads the first source, the warning change the sweep already flies
(``domain/warning_change.py``). That compares reach, not distance: warning
time is the shortest flight time among the intercepts the object can fly
within the sweep's delta-V budget. So closer here means in reach sooner than
before the burn, beyond the tolerance ``warning_change.classify`` reads a
change with: newly in reach, or warning cut. Lengthened, unchanged and no
longer in reach make no edge.

SPC-173 adds the second source, close approaches: the closest approach
computed from the element sets before and after the burns, and a UDL
conjunction the operator has looked up. There closer means a miss under
50 km, smaller than the figure from before the burns by more than the
position error both figures carry. A computed approach is searched only
while both element sets are within their limits (``approach_window``), and
a figure that cannot be read is refused; either refusal is a sentence the
ledger states, never an edge.

SPC-174 adds hostile seeds: analyst-adjudicated hostile objects, read from a
list the deployment configures (section 9, decision 5), never bundled. The
list never becomes classified, so a path names its seed by catalogue number
and name (decision 15, SPC-180). Suspicion
flows from an object to the seeds it approached, at most two hops away (it
approached the seed, or approached an object that approached it); a third
hop adds nothing, and a benign seed propagates nothing, not even trust
(section 8). ``seed_paths`` finds the paths; Threat Understanding grades
them, a reading of floor MEDIUM at most.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from spectre.domain.custody import age_text
from spectre.domain.warning_change import Change, TargetWarning, classify

__all__ = [
    "ATTRIBUTION_WINDOW", "MAX_HOPS", "MISS_FLOOR_KM", "NO_SEED_LIST", "Burn", "Edge", "Miss", "MissEdge",
    "MissSource", "SeedList", "SeedPath", "SetAge", "approach_window", "miss_edges", "parse_seed_list",
    "refused_seed_list", "seed_paths", "warning_edges",
]

#: A burn explains an approach only if it can have happened no longer than
#: this before it (section 4.9). Tuned, not sourced.
ATTRIBUTION_WINDOW: timedelta = timedelta(days=7)
#: The changes that bring a target closer: in reach sooner than before the burn.
_CLOSER = frozenset({Change.NEWLY_IN_REACH, Change.CUT})
#: A close approach is an edge only under this miss distance (section 4.6). Tuned, not sourced.
MISS_FLOOR_KM: float = 50.0
_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Burn:
    """One burn the warning change was flown across, as the edge rule reads it.

    *earliest* and *latest* are the times it can have happened (Pattern of
    Life's ``burn_window``); *epoch* is the estimator's burn epoch, the age
    clock its evidence is dated by. *detection* is its ``astro/dv_estimation``
    grade and *provider* the source of the element sets it was detected in.
    """

    epoch: datetime
    earliest: datetime
    latest: datetime
    confirmed: bool
    detection: str
    provider: str
    long_gap: bool = False


@dataclass(frozen=True)
class Edge:
    """A manoeuvre-attributable approach of *actor* to *target*, and the burns it rests on."""

    actor: str
    target: str
    ours: bool
    change: Change
    before_h: float | None
    after_h: float | None
    approach_at: datetime
    burns: tuple[Burn, ...]
    #: The target's catalogue number, "" when the sweep holds none: only a numbered target links on (SPC-174).
    target_satno: str = ""

    def __post_init__(self) -> None:
        _require_burns(self.actor, self.target, self.burns)

    @property
    def burn_at(self) -> datetime:
        """The latest burn's epoch: the age clock, since the approach exists only once the orbit after it is held.

        Dated by the earliest instead, a later burn the edge itself rests on
        would read as a hostile burn judged after it and end its floor.
        """
        return max(b.epoch for b in self.burns)


def _require_burns(actor: str, target: str, burns: tuple[Burn, ...]) -> None:
    if not burns:
        raise ValueError(f"{actor} to {target}: an edge rests on at least one burn")


def _explains(burn: Burn, approach_at: datetime) -> bool:
    """Confirmed, and within the window before the approach at every time it can have happened."""
    return burn.confirmed and burn.latest <= approach_at and approach_at - burn.earliest <= ATTRIBUTION_WINDOW


def warning_edges(actor: str, rows: Iterable[TargetWarning], burns: Sequence[Burn],
                  approach_at: datetime) -> tuple[Edge, ...]:
    """An edge from *actor* to each target the burns brought in reach, or in reach sooner, by *approach_at*.

    *rows* are the warning change's, before and after the burns; *burns* are
    every burn the change was flown across. The before orbit predates the
    first of them, so the change rests on them all: each must be confirmed
    and fall within 7 days before the approach, or there is no edge. Each
    row's change is read again by ``classify``, the warning change's own
    rule, so a mislabelled row cannot make an edge.
    """
    held = tuple(burns)
    if not held or not all(_explains(b, approach_at) for b in held):
        return ()
    return tuple(Edge(actor, r.name, r.ours, change, r.before_h, r.after_h, approach_at, held)
                 for r in rows if (change := classify(r.before_h, r.after_h)) in _CLOSER)


class MissSource(Enum):
    """Where a miss distance came from, as the ledger names it."""

    COMPUTED = "computed closest approach"
    UDL = "UDL conjunction"


@dataclass(frozen=True)
class Miss:
    """One close approach to judge: the miss at *tca*, and the figure for the same pair from before the burn.

    *before_at* is when the figure from before was true of the orbit: the
    epoch of the element set it was computed from, or the TCA of the earlier
    conjunction. *margin_km* is the position error the two figures carry
    between them, so a smaller change is not closer. *after_km* is None when
    the figure could not be read, and *problem* says why.
    """

    target: str
    target_satno: str
    ours: bool
    source: MissSource
    tca: datetime
    after_km: float | None
    before_km: float | None
    before_at: datetime | None
    margin_km: float = 0.0
    problem: str = ""


@dataclass(frozen=True)
class MissEdge:
    """A manoeuvre-attributable close approach of *actor* to *target*: under 50 km and closer than before."""

    actor: str
    target: str
    target_satno: str
    ours: bool
    source: MissSource
    before_km: float
    after_km: float
    approach_at: datetime
    burns: tuple[Burn, ...]

    def __post_init__(self) -> None:
        _require_burns(self.actor, self.target, self.burns)
        if not 0.0 <= self.after_km < min(MISS_FLOOR_KM, self.before_km):
            raise ValueError(f"{self.actor} to {self.target}: an edge is under 50 km and closer than before the burn")

    @property
    def burn_at(self) -> datetime:
        """The latest burn's epoch: the age clock, as for a warning edge."""
        return max(b.epoch for b in self.burns)


@dataclass(frozen=True)
class SetAge:
    """One element set as the staleness rule reads it: whose, its epoch (None when unreadable), its limit."""

    label: str
    epoch: datetime | None
    limit_hours: float


def _out_of_date(element_set: SetAge, now: datetime) -> str | None:
    """Why *element_set* earns no span at *now*: its epoch unread, or its age past the limit (ElsetAge.stale)."""
    if element_set.epoch is None:
        return f"the {element_set.label} element set's epoch cannot be read, so its age is unknown"
    age_h = (now - element_set.epoch).total_seconds() / _SECONDS_PER_HOUR
    if age_h > element_set.limit_hours:
        return (f"the {element_set.label} element set is out of date, {age_text(age_h)} old against a "
                f"{element_set.limit_hours:.0f} h limit")
    return None


def approach_window(burns: Sequence[Burn], red_after: SetAge, blue: SetAge,
                    now: datetime) -> tuple[datetime, datetime] | str:
    """Where to search the approach after *burns*, or why not, as the Decision Engine refuses a computed one.

    From the latest burn to 7 days after the earliest, ended sooner by the
    moment either element set passes its limit, since past that a miss would
    rest on an out-of-date orbit. Refused, in a sentence, when either set is
    out of date at *now* or of unknown age, or no such span is left.
    """
    if not burns:
        return "no confirmed burn to compare across"
    for element_set in (red_after, blue):
        refused = _out_of_date(element_set, now)
        if refused is not None:
            return refused
    start = max(b.latest for b in burns)
    end = min(min(b.earliest for b in burns) + ATTRIBUTION_WINDOW,
              *(s.epoch + timedelta(hours=s.limit_hours) for s in (red_after, blue) if s.epoch is not None))
    if end <= start:
        return "no time within 7 days after the burn falls inside both element sets' limits"
    return start, end


_NO_FIGURE_BEFORE = "no close approach to it from before the burn is held, so closer cannot be shown"
_NOT_READ = "its miss distance was not read"


def _rests_on(miss: Miss, burns: Sequence[Burn]) -> tuple[Burn, ...]:
    """The burns that can have happened between the figure from before and the approach."""
    after = miss.before_at
    return tuple(b for b in burns if (after is None or b.latest > after) and b.earliest <= miss.tca)


def _judge(actor: str, miss: Miss, burns: Sequence[Burn]) -> MissEdge | str | None:
    """An edge, a refusal to state, or None for an approach no burn explains or that is not closer."""
    if not any(_explains(b, miss.tca) for b in burns):
        return None
    if miss.after_km is None:
        return miss.problem or _NOT_READ
    if miss.after_km >= MISS_FLOOR_KM:
        return None
    if miss.before_km is None:
        return _NO_FIGURE_BEFORE
    return _closer(actor, miss, (miss.before_km, miss.after_km), burns)


def _closer(actor: str, miss: Miss, figures: tuple[float, float], burns: Sequence[Burn]) -> MissEdge | None:
    """An edge when every burn between the two figures explains the approach and it came closer beyond the margin."""
    before_km, after_km = figures
    between = _rests_on(miss, burns)
    if not between or not all(_explains(b, miss.tca) for b in between) or before_km - after_km <= miss.margin_km:
        return None
    return MissEdge(actor, miss.target, miss.target_satno, miss.ours, miss.source, before_km, after_km, miss.tca,
                    between)


def miss_edges(actor: str, misses: Iterable[Miss],
               burns: Sequence[Burn]) -> tuple[tuple[MissEdge, ...], tuple[str, ...]]:
    """The close approaches the burns explain and that came closer, and a sentence for each one refused.

    An approach no confirmed burn explains is an accidental pass: no edge, and
    nothing to state. One a burn could explain is refused, and the refusal
    stated, when its miss distance could not be read, or when it is under
    50 km with no figure from before the burn to compare. Otherwise it is an
    edge only under 50 km, closer than before by more than the position error
    both figures carry, and only when every burn between the two figures
    explains it, as the warning change's before orbit needs of every burn.
    """
    edges: list[MissEdge] = []
    refused: list[str] = []
    for miss in misses:
        judged = _judge(actor, miss, burns)
        if isinstance(judged, MissEdge):
            edges.append(judged)
        elif judged is not None:
            refused.append(f"{miss.source.value} with {miss.target} not counted: {judged}.")
    return tuple(edges), tuple(refused)


#: Suspicion propagates at most this many hops from an object to a seed (section 4.9). Tuned, not sourced.
MAX_HOPS: int = 2


@dataclass(frozen=True)
class SeedList:
    """The analyst-adjudicated seeds by catalogue number, and what the ledger says about the list.

    A refused list holds no seed: one malformed entry refuses it whole, so a
    partial list is never read as the whole.
    """

    hostile: frozenset[str]
    benign: frozenset[str]
    statement: str
    refused: bool = False


#: With no list configured, propagation adds nothing, and the ledger says so.
NO_SEED_LIST = SeedList(frozenset(), frozenset(), "no hostile seed list configured")

_SEED_FIELDS = frozenset({"satno", "disposition", "adjudicated_at", "note"})
_REQUIRED_FIELDS = ("satno", "disposition")
_DISPOSITIONS = frozenset({"hostile", "benign"})
_SATNO_DIGITS = 9
_NOTE_LIMIT = 500
_REFUSED = "hostile seed list refused, so propagation adds nothing: "
_NOT_A_LIST = "it must be an object holding only a seeds list"
_REPEATED_FIELD = "an object in it names one field twice"


class _SeedListError(ValueError):
    """Why a seed list is refused, in words that never repeat its contents."""


def refused_seed_list(reason: str) -> SeedList:
    """A list refused for *reason*: no seed, and the ledger says why."""
    return SeedList(frozenset(), frozenset(), _REFUSED + reason, refused=True)


def _catalogue_number(raw: Any) -> str | None:
    """A positive catalogue number of at most nine digits, as plain digits, or None."""
    if isinstance(raw, bool):
        return None
    text = raw.strip() if isinstance(raw, str) else None
    if isinstance(raw, int):
        value = raw
    elif text and text.isascii() and text.isdigit() and len(text) <= _SATNO_DIGITS:
        value = int(text)
    else:
        return None
    return str(value) if 0 < value < 10 ** _SATNO_DIGITS else None


def _is_iso_date(raw: Any) -> bool:
    if not isinstance(raw, str):
        return False
    for parse in (date.fromisoformat, datetime.fromisoformat):
        try:
            parse(raw)
        except ValueError:
            continue
        return True
    return False


def _optional_fields_problem(entry: dict[str, Any]) -> str | None:
    if "adjudicated_at" in entry and not _is_iso_date(entry["adjudicated_at"]):
        return "adjudicated_at is not an ISO 8601 date"
    note = entry.get("note", "")
    if not isinstance(note, str) or len(note) > _NOTE_LIMIT:
        return f"note must be text of at most {_NOTE_LIMIT} characters"
    return None


def _seed_entry(index: int, entry: Any) -> tuple[str, str]:
    """One entry as (catalogue number, disposition), or _SeedListError naming the entry and the rule."""
    if not isinstance(entry, dict):
        raise _SeedListError(f"entry {index} is not an object")
    if set(entry) - _SEED_FIELDS:
        raise _SeedListError(f"entry {index} has a field the list does not take")
    for name in _REQUIRED_FIELDS:
        if name not in entry:
            raise _SeedListError(f"entry {index} has no {name}")
    satno = _catalogue_number(entry["satno"])
    if satno is None:
        raise _SeedListError(f"entry {index}'s satno is not a catalogue number")
    if entry["disposition"] not in _DISPOSITIONS:
        raise _SeedListError(f"entry {index}'s disposition must be hostile or benign")
    problem = _optional_fields_problem(entry)
    if problem is not None:
        raise _SeedListError(f"entry {index}'s {problem}")
    return satno, str(entry["disposition"])


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """One JSON object, refused when it names a field twice: JSON would keep the last, a list that says two things."""
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise _SeedListError(_REPEATED_FIELD)
    return fields


def _seed_entries(text: str) -> list[Any]:
    try:
        document = json.loads(text, object_pairs_hook=_unique_fields)
    except _SeedListError:
        raise
    except (ValueError, RecursionError) as exc:
        raise _SeedListError("it is not JSON") from exc
    if not isinstance(document, dict) or set(document) != {"seeds"} or not isinstance(document["seeds"], list):
        raise _SeedListError(_NOT_A_LIST)
    return document["seeds"]


def _held_statement(hostile: int) -> str:
    if not hostile:
        return "hostile seed list held: it names no hostile seed"
    plural = "" if hostile == 1 else "s"
    return f"hostile seed list held: {hostile} hostile seed{plural}; a benign entry propagates nothing"


def parse_seed_list(text: str) -> SeedList:
    """The seed list in *text*, validated strictly, or refused whole with the entry and the rule it broke.

    The document is ``{"seeds": [...]}``; each entry holds ``satno`` (a
    catalogue number) and ``disposition`` ("hostile" or "benign"), and may
    hold ``adjudicated_at`` (an ISO 8601 date) and ``note`` (text). Nothing
    else is taken, and no number may appear twice.
    """
    by_disposition: dict[str, set[str]] = {"hostile": set(), "benign": set()}
    seen: set[str] = set()
    try:
        for index, raw in enumerate(_seed_entries(text), start=1):
            satno, disposition = _seed_entry(index, raw)
            if satno in seen:
                raise _SeedListError(f"entry {index} repeats an earlier entry's satno")
            seen.add(satno)
            by_disposition[disposition].add(satno)
    except _SeedListError as refused:
        return refused_seed_list(str(refused))
    hostile = frozenset(by_disposition["hostile"])
    return SeedList(hostile, frozenset(by_disposition["benign"]), _held_statement(len(hostile)))


@dataclass(frozen=True)
class SeedPath:
    """A path from an object to a hostile seed: the edges it walks, the object's own first.

    The seed list never becomes classified (section 9, decision 5), so a path
    names its seed by catalogue number and name, on screen and in the ledger
    (decision 15, SPC-180).
    """

    seed: str
    hops: int
    edges: tuple[Edge | MissEdge, ...]

    @property
    def seed_name(self) -> str:
        """The seed's name as the last edge's approach named it, or "" when it was held by number alone."""
        name = self.edges[-1].target.strip()
        return "" if not name or _node(name) == self.seed else name

    @property
    def seed_label(self) -> str:
        """The seed as the page names it: its name and catalogue number, or the number alone."""
        return f"{self.seed_name} ({self.seed})" if self.seed_name else self.seed


def _node(satno: str) -> str:
    """A catalogue number as one node: "0900", " 900 " and "900" are one object."""
    text = str(satno).strip()
    return str(int(text)) if text.isascii() and text.isdigit() else text


_Walk = tuple[str, tuple[Edge | MissEdge, ...]]


def _step(frontier: list[_Walk], leaving: dict[str, list[Edge | MissEdge]], start: str) -> list[_Walk]:
    """One hop further along every walk, never back to an object the walk has already passed."""
    walks: list[_Walk] = []
    for node, path in frontier:
        passed = {start, *(_node(e.target_satno) for e in path)}
        walks.extend((_node(e.target_satno), (*path, e)) for e in leaving.get(node, ())
                     if _node(e.target_satno) not in passed)
    return walks


def _path_key(path: SeedPath) -> tuple[object, ...]:
    return (path.hops, path.seed,
            tuple((_node(e.target_satno), e.burn_at.isoformat(), e.target, e.approach_at.isoformat())
                  for e in path.edges))


def seed_paths(actor: str, edges: Iterable[Edge | MissEdge], seeds: SeedList) -> tuple[SeedPath, ...]:
    """Every path of at most MAX_HOPS from *actor*, along the edges, to a hostile seed.

    An edge leads from the object that moved to the object it approached:
    suspicion flows from the seed to whoever approached it, not to what the
    seed approached. Only a numbered target links on. A benign seed is an
    object like any other: it neither propagates nor blocks.
    """
    if not seeds.hostile:
        return ()
    start = _node(actor)
    leaving: dict[str, list[Edge | MissEdge]] = defaultdict(list)
    for edge in edges:
        if _node(edge.target_satno):
            leaving[_node(edge.actor)].append(edge)
    paths: list[SeedPath] = []
    frontier: list[_Walk] = [(start, ())]
    for hops in range(1, MAX_HOPS + 1):
        frontier = _step(frontier, leaving, start)
        paths.extend(SeedPath(node, hops, path) for node, path in frontier if node in seeds.hostile)
    return tuple(sorted(paths, key=_path_key))
