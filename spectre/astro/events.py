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

from spectre.astro.propagator import TLEOrbit


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
    except (ValueError, Exception):
        return []

    events: list[OrbitalEvent] = []
    counts: dict[EventType, int] = {}
    from spectre.astro.constants import MU_EARTH

    window_s = (stop - start).total_seconds()
    n_steps = max(2, int(window_s / step_s))

    prev_ta: float | None = None
    prev_lat: float | None = None

    for i in range(n_steps + 1):
        t = start + timedelta(seconds=i * step_s)
        try:
            sv = orbit.propagate(t)
        except RuntimeError:
            continue

        r = sv.r
        v = sv.v
        r_mag = sv.r_mag

        # Radial velocity.
        v_r = float(np.dot(r, v)) / r_mag

        # Eccentricity vector.
        v_mag = sv.v_mag
        ecc_factor = v_mag ** 2 - MU_EARTH / r_mag
        e_vec = (ecc_factor * r - r_mag * v_r * v) / MU_EARTH
        ecc = float(np.linalg.norm(e_vec))

        # True anomaly.
        if ecc > 1e-10:
            cos_ta = float(np.dot(e_vec, r)) / (ecc * r_mag)
            cos_ta = max(-1.0, min(1.0, cos_ta))
            ta = math.degrees(math.acos(cos_ta))
            if v_r < 0:
                ta = 360.0 - ta
        else:
            ta = 0.0

        # Geocentric latitude (TEME ≈ inertial for node detection).
        lat = math.degrees(math.asin(r[2] / r_mag)) if r_mag > 0 else 0.0

        if prev_ta is not None:
            # Apogee: TA crosses 180°.
            if prev_ta < 180.0 <= ta:
                _add_event(events, counts, EventType.APOGEE, t, max_per_type)

            # Perigee: TA wraps from >300 to <60.
            if prev_ta > 300.0 and ta < 60.0:
                _add_event(events, counts, EventType.PERIGEE, t, max_per_type)

        if prev_lat is not None:
            # Ascending node: latitude crosses 0 going positive.
            if prev_lat < 0.0 <= lat:
                _add_event(events, counts, EventType.ASCENDING_NODE, t, max_per_type)

            # Descending node: latitude crosses 0 going negative.
            if prev_lat >= 0.0 and lat < 0.0:
                _add_event(events, counts, EventType.DESCENDING_NODE, t, max_per_type)

        prev_ta = ta
        prev_lat = lat

    events.sort(key=lambda ev: ev.epoch)
    return events


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
