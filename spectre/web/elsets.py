"""Element set freshness: how old a held set is, and the refresh at UDL connect.

An element set is a measurement with a date on it. A sweep or a red card that
does not say how old its orbit is reads as current whatever the epoch, and in
service a 13-day-old GEO set was briefed as if it were today's.

Staleness uses the thresholds the TLE filter already applies to data gaps
(spectre.config.constants.TLE_FILTER): 72 hours for the regimes GEO and DEEP
(a perigee beyond GEO), where tracking updates are slower and the orbit changes
slowly, and 24 hours for everything else, HEO and Molniya-class included.
Neither is sourced for any regime. Each age states the set's regime, by its
period and eccentricity, and whose limit it is: "LEO figure applied to
HEO/Molniya, unsourced for this regime" (SPC-215, evaluation F-29).

Every element set the session is about to hold passes the one acceptance check first (SPC-201, evaluation F-25):
refused names the set's failures in a sentence, logs it without the set's text, and the caller stores nothing.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from spectre.astro.along_track import RegimeBasis, regime_basis
from spectre.astro.elset_check import (
    FUTURE_EPOCH_TOLERANCE,
    HELD_KEPT,
    NOT_STORED,
    ElsetCheck,
    check_elset,
    history_refusal,
    hours_or_days,
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
_SECONDS_PER_HOUR = 3600.0
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


@dataclass(frozen=True)
class PassedOver:
    """A set newer than the one a fetch took, which the acceptance check refused (SPC-243): the provider that filed
    it, its epoch and each failure in words. Never the set's text, so it can be logged and shown as it is."""

    source: str
    epoch: datetime
    failures: tuple[str, ...]


_SECONDS_PER_MINUTE = 60.0


def _epoch_words(epoch: datetime) -> str:
    """An epoch to the millisecond, rounded: "2026-11-13 12:28:48.002 UTC". Providers' sets for one orbit can be a
    millisecond apart, so a coarser epoch would show a refused set and the set used at the same time."""
    rounded = epoch + timedelta(microseconds=500)
    return f"{rounded:%Y-%m-%d %H:%M:%S}.{rounded.microsecond // 1000:03d} UTC"


def _gap_words(seconds: float) -> str:
    """How much older the set used is: seconds to the millisecond under a minute, minutes under an hour, then hours
    or days as the ages read."""
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds:.3f} s"
    if seconds < _SECONDS_PER_HOUR:
        return f"{seconds / _SECONDS_PER_MINUTE:.1f} min"
    return hours_or_days(seconds / _SECONDS_PER_HOUR)


def _from(source: str) -> str:
    return f"from {source}" if source else "from an unnamed provider"


def _epochs(sets: Sequence[PassedOver]) -> str:
    """The sets' epochs in words: "epoch X" for one, "epochs X to Y", oldest first, for several."""
    if len(sets) == 1:
        return f"epoch {_epoch_words(sets[0].epoch)}"
    return f"epochs {_epoch_words(sets[-1].epoch)} to {_epoch_words(sets[0].epoch)}"


def passed_over_sentence(
    name: str, passed: Sequence[PassedOver], used_source: str, used_epoch: datetime | None,
) -> str:
    """The sentence naming each newer set refused before the set used for the object *name* was taken (SPC-243):
    its provider, its epoch and why, then whose set was used and how much older it is. Sets from one provider
    refused for the same reasons are named together. Never any set's text. *passed* is newest first and not empty.
    """
    groups: dict[tuple[str, tuple[str, ...]], list[PassedOver]] = {}
    for item in passed:
        groups.setdefault((item.source, item.failures), []).append(item)
    if len(groups) == 1:
        sets = passed
        counted = "A newer element set" if len(sets) == 1 else f"{len(sets)} newer element sets"
        verb = "was" if len(sets) == 1 else "were"
        lead = (f"{counted} for {name}, {_from(sets[0].source)} with {_epochs(sets)}, {verb} refused: "
                f"{'; '.join(sets[0].failures)}.")
    else:
        lead = " ".join([f"{len(passed)} newer element sets for {name} were refused.", *(
            f"{len(sets)} {_from(source)} with {_epochs(sets)}: {'; '.join(failures)}."
            for (source, failures), sets in groups.items()
        )])
    whose = f"{used_source}'s" if used_source else "an unnamed provider's"
    if used_epoch is None:
        return f"{lead} The set used is {whose}."
    gap = _gap_words((passed[0].epoch - used_epoch).total_seconds())
    than = "" if len(passed) == 1 else " than the newest refused"
    return f"{lead} The set used is {whose}, epoch {_epoch_words(used_epoch)}, {gap} older{than}."


# PLR0913: the set and where it entered, all but the name and the set named at the call.
def refused(  # noqa: PLR0913
    name: str, tle: str, *, outcome: str = NOT_STORED, satno: int | None = None,
    record: Mapping[str, object] | None = None, now: datetime | None = None,
) -> str | None:
    """The sentence refusing *tle* for the object *name*, logged, or None when the acceptance check accepts it. With
    *satno*, a set for another catalogue number is refused too; *record*, the UDL record it came in, adds that
    record's ephemeris type and UCT flag to the check. A set dated more than FUTURE_EPOCH_TOLERANCE after *now*, the
    wall clock unless given, is refused too (SPC-226)."""
    check = check_elset(tle, satno, record=record, now=datetime.now(tz=UTC) if now is None else now)
    if check.accepted:
        return None
    sentence = check.refusal(name, outcome=outcome)
    log_refusal(sentence)
    return sentence


@dataclass(frozen=True)
class RefusedElset:
    """An element set UDL answered with that the acceptance check refused: nothing was stored (SPC-201).

    fetch_tle_for_satno returns it in place of the set, so each caller can name the object as its operator knows
    it and say what became of any set already held. *check* is the newest set's. When the fetch stopped at its cap,
    *checked* sets were checked and *unchecked* older ones were not, and the sentence says so (SPC-243).
    """

    satno: int
    check: ElsetCheck
    checked: int = 0
    unchecked: int = 0

    def sentence(self, name: str, *, outcome: str = NOT_STORED) -> str:
        sentence = self.check.refusal(name, outcome=outcome)
        if not self.unchecked:
            return sentence
        older = "1 older one was" if self.unchecked == 1 else f"{self.unchecked} older ones were"
        return f"{sentence} Only the newest {self.checked} element sets were checked; {older} not."


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
    # The set's regime and whose limit it is (SPC-215); None when the set's elements cannot be read.
    regime: RegimeBasis | None = None
    # How far the epoch is after the moment aged at, hours, when that is more than FUTURE_EPOCH_TOLERANCE: the set is
    # dated in the future (SPC-226, evaluation F-38). 0 otherwise, a clock a little ahead reading as now.
    ahead_hours: float = 0.0

    @property
    def future(self) -> bool:
        """Whether the set is dated in the future, past the clock-skew tolerance: never current (SPC-226)."""
        return self.ahead_hours > 0.0

    @property
    def regime_line(self) -> str:
        """The regime and whose limit applies, for beside the age: "HEO/Molniya: staleness limit 24 h, LEO figure
        applied to HEO/Molniya, unsourced for this regime"; empty when the regime cannot be read."""
        if self.regime is None:
            return ""
        return f"{self.regime.regime}: staleness limit {self.limit_hours:.0f} h, {self.regime.applied}"

    @property
    def days(self) -> float:
        return self.hours / _HOURS_PER_DAY

    @property
    def stale(self) -> bool:
        """Past the regime's limit, or dated in the future, which is no more current than a set past it (SPC-226)."""
        return self.future or self.hours > self.limit_hours

    @property
    def label(self) -> str:
        """Hours under a day, days beyond it: "10.0 h", "13.0 d"; a set dated in the future says how far ahead it is,
        "2.0 d in the future"."""
        if self.future:
            return f"{hours_or_days(self.ahead_hours)} in the future"
        return hours_or_days(self.hours)


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
    """How old *tle* is at *now*, or None when its epoch cannot be read.

    An epoch after *now* reads as 0 h within FUTURE_EPOCH_TOLERANCE, for clock skew; past it the set is dated in the
    future, ahead_hours says by how much, and it is never current (SPC-226, evaluation F-38). Until 0.42.0 any later
    epoch read as 0 h, current.
    """
    epoch = _epoch_of(tle)
    if epoch is None:
        return None
    hours = max((now - epoch).total_seconds() / _SECONDS_PER_HOUR, 0.0)
    return ElsetAge(
        epoch=epoch, hours=hours, limit_hours=_limit_hours(tle), regime=regime_basis(tle),
        ahead_hours=ahead_hours(epoch, now),
    )


def ahead_hours(epoch: datetime, now: datetime) -> float:
    """How far *epoch* is after *now*, hours, when that is more than FUTURE_EPOCH_TOLERANCE; 0 within it, a clock a
    little ahead reading as now, and 0 for an epoch at or before *now* (SPC-226)."""
    return (epoch - now).total_seconds() / _SECONDS_PER_HOUR if epoch - now > FUTURE_EPOCH_TOLERANCE else 0.0


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
    state: SessionState, item: _Held, credentials: tuple[str, str], sem: asyncio.Semaphore, refresh: ElsetRefresh,
) -> str:
    """Fetch the newest set for *item* and keep it if it is newer: 'updated', 'current' or 'failed', or the sentence
    refusing what UDL answered, when the held set is kept (SPC-201). A set kept that was taken over newer ones the
    check refused has the sentence naming those added to *refresh* (SPC-243)."""
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
        note = got.passed_over_note(item.label)
        if note:
            refresh.passed_over.append(note)
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
        *(_refresh_one(state, item, (username, password), sem, refresh) for item in held),
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
