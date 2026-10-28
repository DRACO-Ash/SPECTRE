"""Element set freshness: how old a held set is, and the refresh at UDL connect.

An element set is a measurement with a date on it. A sweep or a red card that
does not say how old its orbit is reads as current whatever the epoch, and in
service a 13-day-old GEO set was briefed as if it were today's.

Staleness uses the thresholds the TLE filter already applies to data gaps
(spectre.config.constants.TLE_FILTER): 72 hours for GEO and deep space, where
tracking updates are slower and the orbit changes slowly, and 24 hours for
everything else.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spectre.astro.propagator import TLE_ERRORS, regime_from_tle
from spectre.config.constants import TLE_FILTER
from spectre.data.intel import satno_from_tle
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


def provenance(claimed: str) -> str:
    """The data mode to record for a set added through a form: a UDL mode, or MANUAL."""
    mode = claimed.strip().upper()
    return mode if mode in UDL_MODES else "MANUAL"


#: A provider name arrives in a form field, so it is bounded before it is kept.
_PROVIDER_MAX_LEN = 64


def provider(claimed_mode: str, claimed_source: str) -> str:
    """The provider to record for a set added through a form: only a UDL set has one."""
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


def _limit_hours(tle: str) -> float:
    """The staleness limit for *tle*'s regime; the stricter one if it cannot be read."""
    try:
        regime = regime_from_tle(tle)
    except TLE_ERRORS:
        regime = ""
    key = "staleness_warn_geo_h" if regime in _SLOW_REGIMES else "staleness_warn_leo_h"
    return float(TLE_FILTER[key])


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
    """Put the fetched set wherever *item* came from."""
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
    """Fetch the newest set for *item* and keep it if it is newer: 'updated', 'current' or 'failed'."""
    from spectre.web.routes.udl import fetch_tle_for_satno, remember_sources

    async with sem:
        got = await fetch_tle_for_satno(
            item.satno, *credentials,
            data_mode=state.udl_data_mode or "REAL", source=state.udl_tle_source,
        )
    if got is None:
        return "failed"
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
        else:
            refresh.failed.append(item.label)
    refresh.running = False
    refresh.finished_at = datetime.now(tz=UTC)
    state.append_log(
        f"[UDL] Element sets refreshed: {len(refresh.updated)} updated, "
        f"{refresh.current} already current, {len(refresh.failed)} failed"
    )
    logger.info(
        "Element set refresh: %d updated, %d current, %d failed",
        len(refresh.updated), refresh.current, len(refresh.failed),
    )
