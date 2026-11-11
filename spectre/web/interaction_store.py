"""Interactions held per object between sweeps, and the close approaches a sweep judges (SPC-173).

Concept section 4.9: an edge is learnt on the sweep that flies it, but it is
the object's. The session holds each object's edges, so a later sweep, the
intel card and the screen read the same ones, ageing on Interactions' 30-day
half-life. A sweep that evaluates the same burns again replaces the kinds it
re-evaluated, so a figure superseded by newer element sets does not linger.

Two sources are added to the warning change here. The closest approach is
computed from what the sweep already holds: the red set from before the
burns, the set it flew and each target in reach. A UDL conjunction is read
only as the operator looked it up (``routes/udl.py``): nothing here fetches.
Its field names are inferred and unverified (SPC-033), so it is graded as a
probe and the ledger says so. It counts only when filed as REAL data, and
is closer than the one before only by more than UDL_MARGIN_KM.

SPC-174 reads the hostile seed list from the path the deployment configures
(SPECTRE_HOSTILE_SEEDS): owner data, possibly classified, never bundled. A
file that cannot be read, is too large or is malformed is refused whole and
the refusal stated; its contents and its path never reach the page.
"""

from __future__ import annotations

import logging
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from spectre.astro.along_track import position_error_km
from spectre.astro.elset_approach import ElsetFailure, burn_approach
from spectre.astro.monte_carlo import REENTRY_FLOOR_KM, SeparationWindow
from spectre.config.settings import get_settings
from spectre.domain import interaction_graph as ig
from spectre.web.elsets import elset_age, limit_hours_for_regime
from spectre.web.log_safety import log_safe
from spectre.web.udl_conjunction import ConjunctionReading, ConjunctionRow

logger = logging.getLogger(__name__)

#: An edge older than four Interactions half-lives is worth a sixteenth of itself fresh: dropped. Tuned, not sourced.
EDGE_MAX_AGE = timedelta(days=120)
#: The most edges held for one object, the newest kept. Tuned, not sourced.
MAX_EDGES = 50
#: The most targets a sweep searches a closest approach for, soonest in reach first. Tuned, not sourced.
MAX_COMPUTED = 8
#: The largest seed list read, 1 MiB: a list of catalogue numbers is far smaller. Tuned, not sourced.
SEED_FILE_LIMIT = 1024 * 1024
#: The position error two filed conjunctions carry between them: SPC-118's error at epoch in the slow regimes,
#: the larger, for red and blue in each figure, added as the worst case (8 km). A UDL record states no element
#: set age and SPECTRE does not read its covariance, so this is the least error either figure can carry.
UDL_MARGIN_KM = 2 * 2 * position_error_km(0.0, "GEO")
#: The data mode a conjunction must be filed in to say anything about the object itself.
REAL_MODE = "REAL"

WARNING_KIND = "warning"
COMPUTED_KIND = "computed"
UDL_KIND = "udl"
#: What a sweep with warning-change figures re-evaluates; conjunctions are re-judged only while held.
SWEPT_KINDS = frozenset({WARNING_KIND, COMPUTED_KIND})

_COMPUTED = ig.MissSource.COMPUTED.value
_UNNUMBERED = "an unnumbered object"
_NOT_REAL = "it was not filed as REAL data, so it says nothing about the object itself"
_NO_BEFORE_EPOCH = "the red element set from before the burn has no readable epoch"
_SGP4_FAILED = "SGP4 could not propagate the {side} element set"
#: The SGP4 search's altitude floor, the RK45 path's own (SPC-200, evaluation F-30).
_DECAYED = (
    "the {side} object is below the {floor:g} km re-entry floor at an instant searched, so it has decayed or is "
    "decaying"
)
_NOT_SEARCHED = "Closest approaches were computed for the first {cap} targets in reach; {more} more were not searched."
_PROBE = ("{n} UDL conjunction{s} {are} held from the lookup at {at:%Y-%m-%d %H:%M} UTC. Their field names are "
          "inferred and unverified (SPC-033), so each is graded as a probe.")


@dataclass(frozen=True)
class HeldConjunctions:
    """One object's conjunctions as the operator last looked them up, and when."""

    satno: str
    rows: tuple[ConjunctionRow, ...]
    looked_up_at: datetime
    data_mode: str


@dataclass
class InteractionStore:
    """Every object's held edges, its last sweep's refusals and its looked-up conjunctions, by catalogue number."""

    edges: dict[str, tuple[ig.Edge | ig.MissEdge, ...]] = field(default_factory=dict)
    notes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    conjunctions: dict[str, HeldConjunctions] = field(default_factory=dict)


class HeldInteractions(NamedTuple):
    """What the session holds for one object: its edges and what the ledger states about them."""

    edges: tuple[ig.Edge | ig.MissEdge, ...] = ()
    paths: tuple[ig.SeedPath, ...] = ()
    notes: tuple[str, ...] = ()


class HistoryBurns(NamedTuple):
    """The confirmed burns the object's held history shows, and the time it starts: what an edge may rest on."""

    confirmed: frozenset[datetime]
    since: datetime


class Target(NamedTuple):
    """A target in reach after the burn, as the closest-approach search reads it."""

    name: str
    satno: str
    ours: bool
    tle: str | None


def _key(satno: object) -> str:
    """A catalogue number as one key: "041838", " 41838 " and 41838 are one object."""
    text = str(satno).strip()
    return str(int(text)) if text.isdigit() else text


def interaction_store(state: Any) -> InteractionStore:
    """The session's store, made on first use."""
    held = getattr(state, "interaction_store", None)
    if not isinstance(held, InteractionStore):
        held = InteractionStore()
        state.interaction_store = held
    return held


def kind_of(edge: ig.Edge | ig.MissEdge) -> str:
    """Which source an edge came from: the warning change, a computed approach or a UDL conjunction."""
    if isinstance(edge, ig.MissEdge):
        return COMPUTED_KIND if edge.source is ig.MissSource.COMPUTED else UDL_KIND
    return WARNING_KIND


def _current(edges: Sequence[ig.Edge | ig.MissEdge], now: datetime) -> tuple[ig.Edge | ig.MissEdge, ...]:
    """Those under EDGE_MAX_AGE at *now*, the newest MAX_EDGES, in one order whatever the arrival order."""
    kept = sorted((e for e in edges if now - e.burn_at <= EDGE_MAX_AGE), key=lambda e: e.burn_at, reverse=True)
    return tuple(sorted(kept[:MAX_EDGES], key=lambda e: (e.burn_at, kind_of(e), e.target)))


def _unconfirmed(edge: ig.Edge | ig.MissEdge, history: HistoryBurns | None) -> bool:
    """Whether the held history covers one of the edge's burns and no longer confirms it."""
    if history is None:
        return False
    return any(b.epoch >= history.since and b.epoch not in history.confirmed for b in edge.burns)


class Evaluated(NamedTuple):
    """What one sweep judged again: its burns, the kinds of edge it re-judged, and what the history confirms."""

    burns: tuple[ig.Burn, ...]
    kinds: frozenset[str]
    history: HistoryBurns | None = None


def hold_edges(state: Any, actor: str, edges: Sequence[ig.Edge | ig.MissEdge], now: datetime,
               evaluated: Evaluated) -> None:
    """Hold *edges* for *actor*, replacing the held ones of the kinds evaluated that rest only on its burns.

    Those are what this sweep judged again; an edge on a burn it did not
    judge, or of a kind it could not, is kept until it ages out, unless the
    object's held history covers that burn's time and no longer confirms it:
    an edge never outlives the burn it rests on.
    """
    store = interaction_store(state)
    epochs = {b.epoch for b in evaluated.burns}
    kept = [e for e in store.edges.get(_key(actor), ())
            if not (kind_of(e) in evaluated.kinds and all(b.epoch in epochs for b in e.burns))
            and not _unconfirmed(e, evaluated.history)]
    store.edges[_key(actor)] = _current([*kept, *edges], now)


def hold_conjunctions(state: Any, satno: int, reading: ConjunctionReading, data_mode: str, now: datetime) -> None:
    """Hold what the operator's conjunction lookup read for *satno*, for the sweep to judge without fetching."""
    interaction_store(state).conjunctions[_key(satno)] = HeldConjunctions(
        satno=_key(satno), rows=tuple(reading.rows), looked_up_at=now, data_mode=data_mode)


def _other(row: ConjunctionRow) -> str:
    """The other object as the ledger names it: its name and number as UDL gave them, escaped where shown."""
    number = row.other_satno or _UNNUMBERED
    return f"{row.other_name} ({number})" if row.other_name else number


def _real(row: ConjunctionRow) -> bool:
    """Filed as REAL data: the record's own mode, or the lookup's where the record stated none."""
    return row.data_mode == REAL_MODE


def _before(row: ConjunctionRow, rows: Sequence[ConjunctionRow]) -> ConjunctionRow | None:
    """The latest readable REAL conjunction with the same object before *row*."""
    earlier = [r for r in rows if r.other_satno == row.other_satno and r.tca < row.tca and r.miss_km is not None
               and _real(r)]
    return max(earlier, key=lambda r: r.tca, default=None)


def conjunction_misses(held: HeldConjunctions, blue_satnos: frozenset[str]) -> tuple[ig.Miss, ...]:
    """Each held conjunction as a miss to judge, against the latest readable one with the same object before it.

    Closer means closer by more than UDL_MARGIN_KM. One not filed as REAL
    data (exercise, test or simulated) is refused, and the refusal stated
    whenever a burn could explain it: it says nothing about the real object.
    """
    misses = []
    for row in held.rows:
        prior = _before(row, held.rows) if row.other_satno else None
        real = _real(row)
        misses.append(ig.Miss(
            target=_other(row), target_satno=row.other_satno, ours=row.other_satno in blue_satnos,
            source=ig.MissSource.UDL, tca=row.tca, after_km=row.miss_km if real else None,
            before_km=None if prior is None else prior.miss_km, before_at=None if prior is None else prior.tca,
            margin_km=UDL_MARGIN_KM, problem=row.miss_problem if real else _NOT_REAL,
        ))
    return tuple(misses)


def _set_age(label: str, tle: str | None, now: datetime) -> ig.SetAge:
    age = elset_age(tle, now) if tle else None
    if age is None:
        return ig.SetAge(label, None, limit_hours_for_regime(""))
    return ig.SetAge(label, age.epoch, age.limit_hours)


def _search(burns: Sequence[ig.Burn], before_tle: str, after_tle: str, target: Target,
            now: datetime) -> ig.Miss | str:
    """One target's closest approach before and after the burns, or why it was not searched."""
    red_after, blue = _set_age("red", after_tle, now), _set_age(target.name, target.tle, now)
    window = ig.approach_window(burns, red_after, blue, now)
    if isinstance(window, str):
        return window
    before = elset_age(before_tle, now)
    if before is None:
        return _NO_BEFORE_EPOCH
    start, end = window
    found = burn_approach((before_tle, before.epoch), (after_tle, red_after.epoch or now),
                          (target.tle or "", blue.epoch or now), SeparationWindow(start, (end - start).total_seconds()))
    if isinstance(found, ElsetFailure):
        failed = _DECAYED if found.reason == "reentered" else _SGP4_FAILED
        return failed.format(side=found.side, floor=REENTRY_FLOOR_KM)
    return ig.Miss(target=target.name, target_satno=target.satno, ours=target.ours, source=ig.MissSource.COMPUTED,
                   tca=found.after_tca, after_km=found.after.approach.miss_km,
                   before_km=found.before.approach.miss_km, before_at=before.epoch, margin_km=found.margin_km)


def computed_misses(burns: Sequence[ig.Burn], before_tle: str, after_tle: str, targets: Sequence[Target],
                    now: datetime) -> tuple[tuple[ig.Miss, ...], tuple[str, ...]]:
    """The closest approach to each target, soonest in reach first, before and after the burns, or why not.

    *before_tle* is the red set from before the first burn, flown as if it
    had not burned; *after_tle* the set the sweep flew. At most MAX_COMPUTED
    targets are searched, and the rest are named. Nothing is fetched.
    """
    if not burns:
        return (), ()
    misses: list[ig.Miss] = []
    refused: list[str] = []
    for target in targets[:MAX_COMPUTED]:
        found = _search(burns, before_tle, after_tle, target, now)
        if isinstance(found, ig.Miss):
            misses.append(found)
        else:
            refused.append(f"{_COMPUTED} with {target.name} not counted: {found}.")
    if len(targets) > MAX_COMPUTED:
        refused.append(_NOT_SEARCHED.format(cap=MAX_COMPUTED, more=len(targets) - MAX_COMPUTED))
    return tuple(misses), tuple(refused)


def _probe_note(held: HeldConjunctions | None) -> tuple[str, ...]:
    if held is None:
        return ()
    n = len(held.rows)
    return (_PROBE.format(n=n, s="" if n == 1 else "s", are="is" if n == 1 else "are", at=held.looked_up_at),)


class SweepFindings(NamedTuple):
    """What one sweep learnt about the red object.

    *burns* are the confirmed burns in its window; *warning* the edges its
    warning change attributes to them; *computed* the closest approaches and
    the refusals of the search, None when the warning change had no figures.
    *history* is what the object's held history confirms.
    """

    burns: tuple[ig.Burn, ...]
    warning: tuple[ig.Edge, ...] = ()
    computed: tuple[tuple[ig.Miss, ...], tuple[str, ...]] | None = None
    blue_satnos: frozenset[str] = frozenset()
    history: HistoryBurns | None = None


def sweep_interactions(state: Any, actor: str, found: SweepFindings, now: datetime) -> HeldInteractions:
    """Judge what one sweep learnt about *actor*, hold it, and read back all the object holds.

    With no figures (*computed* None) only the held conjunctions are judged
    again, and the warning and computed edges already held stay as they were.
    """
    store = interaction_store(state)
    held_conjunctions = store.conjunctions.get(_key(actor))
    kinds = set() if found.computed is None else set(SWEPT_KINDS)
    misses, refused = ((), ()) if found.computed is None else found.computed
    computed_edges, computed_refused = ig.miss_edges(actor, misses, found.burns)
    udl_edges: tuple[ig.MissEdge, ...] = ()
    udl_refused: tuple[str, ...] = ()
    if held_conjunctions is not None:
        kinds.add(UDL_KIND)
        udl_edges, udl_refused = ig.miss_edges(
            actor, conjunction_misses(held_conjunctions, found.blue_satnos), found.burns)
    hold_edges(state, actor, (*found.warning, *computed_edges, *udl_edges), now,
               Evaluated(found.burns, frozenset(kinds), found.history))
    store.notes[_key(actor)] = (*refused, *computed_refused, *udl_refused, *_probe_note(held_conjunctions))
    return held_interactions(state, actor, now)


_SEED_CACHE: dict[str, tuple[tuple[int, int], ig.SeedList]] = {}


def _read_seed_text(path: Path) -> str | ig.SeedList:
    """The file's text, or the refused list saying why it cannot be read: missing, not a file, too large or not UTF-8.

    Only a regular file is opened: a FIFO or a device reports no size and
    could block or read without end on the request path. The read itself is
    bounded too, so a file that grew after its size was checked is refused.
    """
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return ig.refused_seed_list("the configured path is not a regular file")
        with path.open("rb") as file:
            raw = file.read(SEED_FILE_LIMIT + 1)
        if len(raw) > SEED_FILE_LIMIT:
            return ig.refused_seed_list("the configured file is larger than 1 MiB")
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ig.refused_seed_list("the configured file is not UTF-8 text")
    except OSError:
        return ig.refused_seed_list("the configured file cannot be read")


def load_seed_list(path: str) -> ig.SeedList:
    """The seed list at *path*, validated strictly, or NO_SEED_LIST with none set.

    Read again whenever the file changes. A refusal names the rule broken,
    never the file's contents, and the log names the path and nothing more.
    """
    if not path.strip():
        return ig.NO_SEED_LIST
    file = Path(path.strip())
    try:
        info = file.stat()
        signature = (info.st_mtime_ns, info.st_size)
    except OSError:
        signature = (-1, -1)
    cached = _SEED_CACHE.get(path)
    if cached is not None and cached[0] == signature and signature != (-1, -1):
        return cached[1]
    text = _read_seed_text(file)
    seeds = text if isinstance(text, ig.SeedList) else ig.parse_seed_list(text)
    if seeds.refused:
        # The statement names the rule broken, never the contents.
        logger.warning("Hostile seed list at %s: %s", log_safe(str(file)), log_safe(seeds.statement))
    _SEED_CACHE[path] = (signature, seeds)
    return seeds


def configured_seed_list() -> ig.SeedList:
    """The seed list at the path the deployment configures (SPECTRE_HOSTILE_SEEDS), or NO_SEED_LIST."""
    return load_seed_list(get_settings().hostile_seeds_path)


def held_interactions(state: Any, satno: str, now: datetime) -> HeldInteractions:
    """What the session holds for *satno* at *now*: its edges, its paths to hostile seeds, and the ledger's notes.

    Edges under EDGE_MAX_AGE count; the paths run through every object's held
    edges; the notes are its last sweep's refusals and what the seed list is.
    """
    seeds = configured_seed_list()
    store = getattr(state, "interaction_store", None)
    if not isinstance(store, InteractionStore):
        return HeldInteractions(notes=(seeds.statement,))
    key = _key(satno)
    every = [e for edges in store.edges.values() for e in _current(edges, now)]
    return HeldInteractions(edges=_current(store.edges.get(key, ()), now), paths=ig.seed_paths(key, every, seeds),
                            notes=(*store.notes.get(key, ()), seeds.statement))
