"""Element set freshness: how old a held set is, and the refresh at UDL connect.

An element set is a measurement with a date on it. A sweep or a red card that
does not say how old its orbit is reads as current whatever the epoch, and in
service a 13-day-old GEO set was briefed as if it were today's.

Staleness uses the thresholds the TLE filter already applies to data gaps
(spectre.config.constants.TLE_FILTER): 72 hours for the regimes GEO and DEEP
(a perigee beyond GEO), where tracking updates are slower and the orbit changes
slowly, and 24 hours for everything else, HEO and Molniya-class included.

Every element set the session is about to hold passes the one acceptance check first (SPC-201, evaluation F-25):
refused names the set's failures in a sentence, logs it without the set's text, and the caller stores nothing.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spectre.astro.elset_check import (
    HELD_KEPT,
    NOT_STORED,
    ElsetCheck,
    check_elset,
    history_refusal,
    refused_type,
)
from spectre.astro.propagator import TLE_ERRORS, regime_from_tle
from spectre.config.constants import TLE_FILTER
from spectre.data.intel import satno_from_tle
from spectre.web.log_safety import log_safe
from spectre.web.planning_state import ElsetRefresh, SessionState

if TYPE_CHECKING:
    from spectre.web.routes.udl import FetchedElset

logger = logging.getLogger(__name__)

_HOURS_PER_DAY = 24.0
_SLOW_REGIMES = frozenset({"GEO", "DEEP"})

#: Element sets in these provenances came from UDL and may be refreshed from
#: it. MANUAL (entered by hand) is never overwritten; SYNTHETIC (the bundled
#: bootstrap) is always replaced when UDL has the object.
UDL_MODES = frozenset({"REAL", "TEST", "EXERCISE", "SIMULATED"})
_SYNTHETIC = "SYNTHETIC"

#: Parallel UDL requests during a refresh, the bound the sweep's own fetch uses.
_REFRESH_CONCURRENCY = 10


#: The longest refusal sentence the log keeps: a name and every failure the check can name fit well inside it.
_REFUSAL_LOG_LIMIT = 1000


def log_refusal(sentence: str) -> None:
    """Log a refusal sentence: it names the object and what failed, never the set's text (SPC-201)."""
    logger.warning("%s", log_safe(sentence, limit=_REFUSAL_LOG_LIMIT))


def log_skipped_by_type(subject: str, sets: Iterable[tuple[str, Mapping[str, object]]]) -> None:
    """Log the UDL sets for *subject* ("SATNO 90002") passed over for their type or correlation, counted by type
    and provider, never their text.

    How often providers file SGP4-XP sets and uncorrelated tracks for the objects operators hold is the evidence a
    later SGP4-XP propagator would be judged on, so each skip is counted where it happens.
    """
    counts: Counter[tuple[str, str]] = Counter()
    for tle, record in sets:
        kind = refused_type(tle, record)
        if kind:
            counts[(kind, str(record.get("source") or "an unnamed source").strip())] += 1
    if counts:
        named = "; ".join(f"{n} {kind} from {source}" for (kind, source), n in counts.items())
        logger.info("%s: element sets skipped by type: %s", log_safe(subject), log_safe(named, limit=500))


def refused(
    name: str, tle: str, *, outcome: str = NOT_STORED, satno: int | None = None,
    record: Mapping[str, object] | None = None,
) -> str | None:
    """The sentence refusing *tle* for the object *name*, logged, or None when the acceptance check accepts it. With
    *satno*, a set for another catalogue number is refused too; *record*, the UDL record it came in, adds that
    record's ephemeris type and UCT flag to the check."""
    check = check_elset(tle, satno, record=record)
    if check.accepted:
        return None
    sentence = check.refusal(name, outcome=outcome)
    log_refusal(sentence)
    return sentence


@dataclass(frozen=True)
class RefusedElset:
    """An element set UDL answered with that the acceptance check refused: nothing was stored (SPC-201).

    fetch_tle_for_satno returns it in place of the set, so each caller can name the object as its operator knows
    it and say what became of any set already held.
    """

    satno: int
    check: ElsetCheck

    def sentence(self, name: str, *, outcome: str = NOT_STORED) -> str:
        return self.check.refusal(name, outcome=outcome)


class ElsetHistory(list[str]):
    """The element sets a history fetch kept, in order, and the check of each it refused (SPC-201).

    A list, so a caller that reads only the sets reads it as before; one that can tell the operator asks for the
    refusal sentence.
    """

    def __init__(self, kept: Iterable[str] = (), refused: Sequence[ElsetCheck] = ()) -> None:
        super().__init__(kept)
        self.refused: tuple[ElsetCheck, ...] = tuple(refused)

    def refusal(self, name: str) -> str | None:
        """The sentence saying which sets in the history for *name* were refused and why; None when none was."""
        if not self.refused:
            return None
        return history_refusal(name, len(self.refused), [f for check in self.refused for f in check.failures])


def provenance(claimed: str) -> str:
    """The data mode to record for a set added through a form: a UDL mode, or MANUAL."""
    mode = claimed.strip().upper()
    return mode if mode in UDL_MODES else "MANUAL"


#: A provider name arrives in a form field, so it is bounded before it is kept.
_PROVIDER_MAX_LEN = 64


def provider(claimed_mode: str, claimed_source: str) -> str:
    """The provider to record for a set added through a form: only a UDL set has one.

    Editing a fetched set drops its mode tag, so its provider is dropped with it.
    """
    if provenance(claimed_mode) == "MANUAL":
        return ""
    return claimed_source.strip()[:_PROVIDER_MAX_LEN]


@dataclass(frozen=True)
class ElsetAge:
    """The age of one element set at a given moment, against its regime's limit."""

    epoch: datetime
    hours: float
    limit_hours: float

    @property
    def days(self) -> float:
        return self.hours / _HOURS_PER_DAY

    @property
    def stale(self) -> bool:
        return self.hours > self.limit_hours

    @property
    def label(self) -> str:
        """Hours under a day, days beyond it: "10.0 h", "13.0 d"."""
        if self.hours < _HOURS_PER_DAY:
            return f"{self.hours:.1f} h"
        return f"{self.days:.1f} d"


def _epoch_of(tle: str) -> datetime | None:
    from spectre.web.routes.udl import _parse_tle_epoch

    line1 = next((ln.strip() for ln in tle.splitlines() if ln.strip().startswith("1 ")), "")
    return _parse_tle_epoch(line1) if line1 else None


def limit_hours_for_regime(regime: str) -> float:
    """The staleness limit for a regime; the stricter one for any regime not known to be slow."""
    key = "staleness_warn_geo_h" if regime.strip().upper() in _SLOW_REGIMES else "staleness_warn_leo_h"
    return float(TLE_FILTER[key])


def _limit_hours(tle: str) -> float:
    """The staleness limit for *tle*'s regime; the stricter one if it cannot be read."""
    try:
        regime = regime_from_tle(tle)
    except TLE_ERRORS:
        regime = ""
    return limit_hours_for_regime(regime)


def elset_age(tle: str, now: datetime) -> ElsetAge | None:
    """How old *tle* is at *now*, or None when its epoch cannot be read."""
    epoch = _epoch_of(tle)
    if epoch is None:
        return None
    hours = max((now - epoch).total_seconds() / 3600.0, 0.0)
    return ElsetAge(epoch=epoch, hours=hours, limit_hours=_limit_hours(tle))


def _is_newer(candidate: str, held: str) -> bool:
    """Whether *candidate* has a later epoch than *held*; any readable one beats none."""
    new_epoch, old_epoch = _epoch_of(candidate), _epoch_of(held)
    if new_epoch is None:
        return False
    return old_epoch is None or new_epoch > old_epoch


@dataclass
class _Held:
    """One held element set the refresh may replace, and how to write it back."""

    label: str
    satno: int
    tle: str
    mode: str


def _held_sets(state: SessionState) -> list[_Held]:
    """Every element set the session holds that came from UDL or the bootstrap."""
    held: list[_Held] = []
    for side, objects in (("red", state.red_tracks), ("blue", state.blue_assets)):
        for obj in objects:
            satno = satno_from_tle(obj.tle)
            if satno is not None and not obj.training and obj.data_mode in UDL_MODES:
                held.append(_Held(f"{side} {obj.name}", satno, obj.tle, obj.data_mode))
    for key, tle in state.hrr_tle_cache.items():
        mode = state.hrr_tle_data_mode.get(key, "REAL")
        if key.isdigit() and (mode in UDL_MODES or mode == _SYNTHETIC):
            held.append(_Held(f"target {key}", int(key), tle, mode))
    return held


def _write_back(state: SessionState, item: _Held, got: FetchedElset) -> None:
    """Put the fetched set, its mode and, on a track or asset, its provider wherever *item* came from."""
    side, _, name = item.label.partition(" ")
    if side == "target":
        state.hrr_tle_cache[name] = got.tle
        state.hrr_tle_data_mode[name] = got.data_mode
        return
    objects = state.red_tracks if side == "red" else state.blue_assets
    for obj in objects:
        if obj.name == name and obj.tle == item.tle:
            obj.tle, obj.data_mode, obj.elset_source = got.tle, got.data_mode, got.source


async def _refresh_one(
    state: SessionState, item: _Held, credentials: tuple[str, str], sem: asyncio.Semaphore,
) -> str:
    """Fetch the newest set for *item* and keep it if it is newer: 'updated', 'current' or 'failed', or the sentence
    refusing what UDL answered, when the held set is kept (SPC-201)."""
    from spectre.web.routes.udl import fetch_tle_for_satno, remember_sources

    # A UDL set is refreshed in its own mode: one fetched as EXERCISE while the
    # session ran REAL must not come back as live data (SPC-030). Only the
    # bootstrap set, which has no UDL mode, takes the session's.
    asked = item.mode if item.mode in UDL_MODES else (state.udl_data_mode or "REAL")
    async with sem:
        got = await fetch_tle_for_satno(
            item.satno, *credentials, data_mode=asked, source=state.udl_tle_source,
        )
    if got is None:
        return "failed"
    if isinstance(got, RefusedElset):
        return got.sentence(item.label, outcome=HELD_KEPT)
    # Source discovery reads the ISS, a LEO object, so a provider filing only
    # for the held GEO objects is learnt here and offered in the TLE Source list.
    remember_sources(state, [got.source])
    if item.mode == _SYNTHETIC or _is_newer(got.tle, item.tle):
        _write_back(state, item, got)
        return "updated"
    return "current"


async def refresh_held_elsets(state: SessionState, username: str, password: str) -> None:
    """Replace every held UDL or bootstrap element set with UDL's newest, if newer.

    Run in the background at UDL connect. Red tracks and blue assets that came
    from UDL, and the sweep's target cache, are refreshed; a set entered by
    hand or loaded by a training scenario is left alone. The outcome is kept
    on *state* so the page can say what was refreshed and when.
    """
    refresh = ElsetRefresh(started_at=datetime.now(tz=UTC))
    state.elset_refresh = refresh
    held = _held_sets(state)
    sem = asyncio.Semaphore(_REFRESH_CONCURRENCY)
    outcomes = await asyncio.gather(
        *(_refresh_one(state, item, (username, password), sem) for item in held),
        return_exceptions=True,
    )
    for item, outcome in zip(held, outcomes, strict=True):
        if outcome == "updated":
            refresh.updated.append(item.label)
        elif outcome == "current":
            refresh.current += 1
        elif isinstance(outcome, str) and outcome != "failed":
            refresh.refused.append(outcome)
        else:
            refresh.failed.append(item.label)
    refresh.running = False
    refresh.finished_at = datetime.now(tz=UTC)
    state.append_log(
        f"[UDL] Element sets refreshed: {len(refresh.updated)} updated, "
        f"{refresh.current} already current, {len(refresh.failed)} failed, {len(refresh.refused)} refused"
    )
    logger.info(
        "Element set refresh: %d updated, %d current, %d failed, %d refused",
        len(refresh.updated), refresh.current, len(refresh.failed), len(refresh.refused),
    )
