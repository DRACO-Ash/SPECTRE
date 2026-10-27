"""Orbital event detection — apogee, perigee, ascending/descending node.

Propagates a TLE over a time window and detects geometry crossings
using true anomaly and geocentric latitude.  Replaces the inline
``_compute_orbital_events`` that previously lived in the maneuver route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

import numpy as np

from spectre.astro.propagator import TLE_ERRORS, TLEOrbit


class EventType(Enum):
    """Types of orbital geometry events."""

    APOGEE = "apogee"
    PERIGEE = "perigee"
    ASCENDING_NODE = "ascending_node"
    DESCENDING_NODE = "descending_node"


@dataclass
class OrbitalEvent:
    """An orbital geometry event at a specific epoch."""

    event_type: EventType
    epoch: datetime
    label: str = ""


# Longest span an event search covers: three of every event type even for a
# GEO object needs about three days.
_MAX_SCAN_S = 7 * 86400.0


def find_orbital_events(
    tle: str,
    start: datetime,
    stop: datetime,
    max_per_type: int = 3,
    step_s: float = 30.0,
) -> list[OrbitalEvent]:
    """Detect apogee, perigee, ascending-node, and descending-node times.

    Propagates the TLE with SGP4 at *step_s*-second intervals and looks
    for zero-crossings in true anomaly and geocentric latitude.

    Args:
        tle: Two- or three-line TLE string.
        start: Start of search window (UTC).
        stop: End of search window (UTC).
        max_per_type: Maximum events to return per event type.
        step_s: Propagation time step in seconds.

    Returns:
        List of :class:`OrbitalEvent`, sorted chronologically.
    """
    try:
        orbit = TLEOrbit(tle)
    except TLE_ERRORS:
        return []

    events: list[OrbitalEvent] = []
    counts: dict[EventType, int] = {}
    from spectre.astro.constants import MU_EARTH

    # The scan stops once every type has max_per_type events, and never
    # covers more than _MAX_SCAN_S: an equatorial orbit has no node crossings,
    # so its quota is never met. Unbounded, a long scenario window ran tens of
    # thousands of propagations on the event loop (audit F-040).
    window_s = min((stop - start).total_seconds(), _MAX_SCAN_S)
    n_steps = max(2, int(window_s / step_s))

    prev: tuple[float, float] | None = None
    for i in range(n_steps + 1):
        t = start + timedelta(seconds=i * step_s)
        try:
            sv = orbit.propagate(t)
        except RuntimeError:
            continue
        here = _anomaly_and_latitude(sv.r, sv.v, sv.r_mag, sv.v_mag, MU_EARTH)
        if prev is not None:
            for etype in _crossings(prev, here):
                _add_event(events, counts, etype, t, max_per_type)
        prev = here
        if len(counts) == len(EventType) and min(counts.values()) >= max_per_type:
            break

    events.sort(key=lambda ev: ev.epoch)
    return events


#: Below this eccentricity the orbit has no usable perigee direction.
_CIRCULAR_ECC = 1e-10
#: Apogee is true anomaly 180 deg. Perigee is the wrap through 0 deg, read as
#: a step from above 300 deg to below 60 deg so one sample step cannot miss it.
_APOGEE_TA = 180.0
_WRAP_FROM_TA = 300.0
_WRAP_TO_TA = 60.0


def _anomaly_and_latitude(
    r: np.ndarray, v: np.ndarray, r_mag: float, v_mag: float, mu: float,
) -> tuple[float, float]:
    """True anomaly and geocentric latitude, in degrees, of one state.

    TEME is close enough to inertial for node detection. A near-circular
    orbit has no defined perigee, so its true anomaly reads 0.
    """
    v_r = float(np.dot(r, v)) / r_mag
    e_vec = ((v_mag ** 2 - mu / r_mag) * r - r_mag * v_r * v) / mu
    ecc = float(np.linalg.norm(e_vec))
    ta = 0.0
    if ecc > _CIRCULAR_ECC:
        cos_ta = max(-1.0, min(1.0, float(np.dot(e_vec, r)) / (ecc * r_mag)))
        ta = math.degrees(math.acos(cos_ta))
        if v_r < 0:
            ta = 360.0 - ta
    lat = math.degrees(math.asin(r[2] / r_mag)) if r_mag > 0 else 0.0
    return ta, lat


def _crossings(prev: tuple[float, float], here: tuple[float, float]) -> list[EventType]:
    """The events between two consecutive (true anomaly, latitude) samples."""
    (prev_ta, prev_lat), (ta, lat) = prev, here
    rules = (
        (EventType.APOGEE, prev_ta < _APOGEE_TA <= ta),
        (EventType.PERIGEE, prev_ta > _WRAP_FROM_TA and ta < _WRAP_TO_TA),
        (EventType.ASCENDING_NODE, prev_lat < 0.0 <= lat),
        (EventType.DESCENDING_NODE, prev_lat >= 0.0 and lat < 0.0),
    )
    return [etype for etype, crossed in rules if crossed]


def _add_event(
    events: list[OrbitalEvent],
    counts: dict[EventType, int],
    etype: EventType,
    epoch: datetime,
    max_per_type: int,
) -> None:
    if counts.get(etype, 0) >= max_per_type:
        return
    label_name = etype.value.replace("_", " ").title()
    label = f"{label_name} @ {epoch.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    events.append(OrbitalEvent(event_type=etype, epoch=epoch, label=label))
    counts[etype] = counts.get(etype, 0) + 1
