"""What NOTSOs show satellites have spent on station, as evidence for realism.

The intercept engine priced every method against a 500 m/s budget, and a
plan costing hundreds of m/s was ranked beside one costing three. JCO's
TACREP_NOTSO reporting states the delta-V of the manoeuvres it sees, and in
the 3,124 messages from April 2022 to March 2026 the largest a satellite
spent on station in any 14 days was 172 m/s. The burns above that were
satellites climbing from transfer orbit to GEO after launch, which is not an
operation against another satellite.

This module reads NOTSO records and keeps every stated burn once, sorted
into three phases:

● launch phase: the text around it describes reaching orbit (GTO,
  circularise, inject, insert, perigee raise, apogee burn);
● uncertain: JCO says the figure is unreliable;
● on station: everything else.

It summarises the on-station burns per satellite and across the fleet.
``scripts/build-manoeuvre-evidence.py`` writes the summary to
``spectre/data/manoeuvre_evidence.json``; at run time the same summary is
also built from the NOTSO cache, so a manoeuvre reported after the shipped
export still counts.

Limits, for the analyst: a burn is dated by the record that first reported
it, usually within a day of the burn. Two different burns of exactly the
same size on the same satellite are counted once. A burn NOTSOs never
reported is not counted, so every figure is a floor on what a satellite has
done, not a ceiling on what it could do.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from spectre.data.notso_cache import record_satnos

logger = logging.getLogger(__name__)

#: The shipped summary, built from the JCO export by the script above.
EVIDENCE_PATH = Path(__file__).resolve().parent.parent / "data" / "manoeuvre_evidence.json"

#: An operation is several burns. The busiest window is the most a satellite
#: spent on station within this many days.
WINDOW_DAYS = 14

#: Launch-phase wording beside a burn this small is a trim after reaching
#: orbit, not the climb itself, so the burn counts as on station.
_LAUNCH_PHASE_FLOOR_M_S = 20.0

#: The share of satellites whose busiest window stays within the "typical"
#: figure: nine in ten.
_TYPICAL_QUANTILE = 0.9

_FIELDS = ("Event_Description", "Follow_Up_Assessment", "NOTSO", "previewText")

#: "Delta V: 3.7 m/s", "Delta v: 3.7m/s", "delta-v of 9.45 m/s", "delta v of 1 m/s".
_DELTA_V = re.compile(r"delta[- ]?v(?:\s*:\s*|\s+of\s+)(\d+(?:\.\d+)?)", re.IGNORECASE)
#: Wording that places a burn in the climb to orbit. Three patterns rather
#: than one: as a single alternation it scored 23 against Sonar's regex
#: complexity limit of 20 (python:S5843).
_LAUNCH_PHASE = (
    re.compile(r"\bGTO\b|circulari[sz]|apogee burn|orbit[- ]raising|transfer orbit|launch", re.IGNORECASE),
    re.compile(r"\bin(?:sert|ject)\w*(?: \w+)? into\b", re.IGNORECASE),
    re.compile(r"perigee (?:altitude )?(?:was )?rais", re.IGNORECASE),
)
_UNCERTAIN = re.compile(r"high uncertainty|sparse|only been indicated", re.IGNORECASE)

#: Characters either side of a stated burn read to decide its phase. A JCO
#: follow-up puts its context in the sentences before the figure.
_CONTEXT_BEFORE = 700
_CONTEXT_AFTER = 300

ON_STATION = "on station"
LAUNCH_PHASE = "launch phase"
UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class StatedBurn:
    """One burn a NOTSO states, the first time it was reported."""

    satno: str
    delta_v_m_s: float
    reported: datetime
    phase: str


@dataclass(frozen=True)
class ObjectEvidence:
    """What one satellite has been seen to spend."""

    satno: str
    name: str
    on_station_burns: int
    largest_burn_m_s: float
    busiest_window_m_s: float
    last_burn: str            # ISO date of the latest on-station burn, "" if none
    launch_phase_max_m_s: float


@dataclass(frozen=True)
class FleetEvidence:
    """The on-station record across every satellite, with its source."""

    satellites: int
    burns: int
    largest_window_m_s: float      # the most any satellite spent in a window
    largest_window_satno: str
    typical_window_m_s: float      # nine in ten satellites stay within this
    first_report: str
    last_report: str
    source: str


@dataclass(frozen=True)
class Evidence:
    """The fleet record and each satellite's, keyed by catalogue number."""

    fleet: FleetEvidence
    objects: dict[str, ObjectEvidence]

    def of(self, satno: str | None) -> ObjectEvidence | None:
        """One satellite's record, or None if NOTSOs never stated a burn for it."""
        return self.objects.get(str(satno or "").strip())


def _reported(rec: dict[str, Any]) -> datetime | None:
    text = str(rec.get("createdAt") or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _phase(text: str, start: int, end: int, delta_v_m_s: float) -> str:
    if delta_v_m_s < _LAUNCH_PHASE_FLOOR_M_S:
        return ON_STATION
    context = text[max(0, start - _CONTEXT_BEFORE): end + _CONTEXT_AFTER]
    if any(p.search(context) for p in _LAUNCH_PHASE):
        return LAUNCH_PHASE
    if _UNCERTAIN.search(context):
        return UNCERTAIN
    return ON_STATION


def _record_text(rec: dict[str, Any]) -> str:
    body = rec.get("msgBody") or {}
    return "\n".join(str(body.get(k) or "") for k in _FIELDS)


def _record_name(rec: dict[str, Any], satno: str) -> str:
    """The satellite's common name, or the one its event class gives after the number."""
    body = rec.get("msgBody") or {}
    name = str(body.get("Sat_Common_Name") or "").strip(" ,")
    if name:
        return name
    parts = [p.strip() for p in str(body.get("Event_Class") or "").split("/")]
    if satno in parts and parts.index(satno) + 1 < len(parts):
        return parts[parts.index(satno) + 1]
    return ""


def stated_burns(records: Iterable[dict[str, Any]]) -> tuple[list[StatedBurn], dict[str, str]]:
    """Every burn the records state, once each, with the satellites' names.

    Only a record naming one satellite is read: a message about several
    cannot say which of them a figure belongs to. A burn repeated in later
    follow-ups is kept at its first report, and once any report places it
    in the launch phase it stays there.
    """
    burns: dict[tuple[str, float], StatedBurn] = {}
    names: dict[str, str] = {}
    for rec in sorted(records, key=lambda r: str(r.get("createdAt") or "")):
        satnos = record_satnos(rec)
        reported = _reported(rec)
        if len(satnos) != 1 or reported is None:
            continue
        satno = next(iter(satnos))
        names[satno] = names.get(satno) or _record_name(rec, satno)
        text = _record_text(rec)
        for m in _DELTA_V.finditer(text):
            dv = round(float(m.group(1)), 2)
            phase = _phase(text, m.start(), m.end(), dv)
            seen = burns.get((satno, dv))
            if seen is None:
                burns[(satno, dv)] = StatedBurn(satno, dv, reported, phase)
            elif phase == LAUNCH_PHASE and seen.phase != LAUNCH_PHASE:
                burns[(satno, dv)] = StatedBurn(satno, dv, seen.reported, phase)
    return list(burns.values()), names


def busiest_window_m_s(burns: list[StatedBurn]) -> float:
    """The most *burns* add up to within any window of WINDOW_DAYS."""
    ordered = sorted(burns, key=lambda b: b.reported)
    window = timedelta(days=WINDOW_DAYS)
    best = 0.0
    for i, first in enumerate(ordered):
        total = sum(b.delta_v_m_s for b in ordered[i:] if b.reported - first.reported <= window)
        best = max(best, total)
    return round(best, 2)


def _quantile(values: list[float], q: float) -> float:
    """The *q* quantile of *values* by linear interpolation between ranks."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (pos - low), 2)


def summarise(records: Iterable[dict[str, Any]], source: str) -> Evidence:
    """The per-satellite and fleet on-station record from NOTSO *records*."""
    burns, names = stated_burns(records)
    by_sat: dict[str, list[StatedBurn]] = {}
    for b in burns:
        by_sat.setdefault(b.satno, []).append(b)
    objects: dict[str, ObjectEvidence] = {}
    for satno, own in by_sat.items():
        station = [b for b in own if b.phase == ON_STATION]
        launch = [b.delta_v_m_s for b in own if b.phase == LAUNCH_PHASE]
        objects[satno] = ObjectEvidence(
            satno=satno,
            name=names.get(satno, ""),
            on_station_burns=len(station),
            largest_burn_m_s=max((b.delta_v_m_s for b in station), default=0.0),
            busiest_window_m_s=busiest_window_m_s(station),
            last_burn=max(b.reported for b in station).date().isoformat() if station else "",
            launch_phase_max_m_s=max(launch, default=0.0),
        )
    windows = {s: o.busiest_window_m_s for s, o in objects.items() if o.on_station_burns}
    top = max(windows, key=lambda s: windows[s], default="")
    reports = sorted(b.reported for b in burns)
    fleet = FleetEvidence(
        satellites=len(windows),
        burns=sum(o.on_station_burns for o in objects.values()),
        largest_window_m_s=windows.get(top, 0.0),
        largest_window_satno=top,
        typical_window_m_s=_quantile(list(windows.values()), _TYPICAL_QUANTILE),
        first_report=reports[0].date().isoformat() if reports else "",
        last_report=reports[-1].date().isoformat() if reports else "",
        source=source,
    )
    return Evidence(fleet=fleet, objects=objects)


def to_json(evidence: Evidence) -> dict[str, Any]:
    """The summary as the shipped file holds it: figures and names, no message text."""
    return {
        "fleet": vars(evidence.fleet),
        "objects": {s: vars(o) for s, o in sorted(evidence.objects.items(), key=lambda kv: int(kv[0]))},
    }


def from_json(data: dict[str, Any]) -> Evidence:
    """The summary back from the shipped file."""
    return Evidence(
        fleet=FleetEvidence(**data["fleet"]),
        objects={s: ObjectEvidence(**o) for s, o in data["objects"].items()},
    )


def _larger(a: ObjectEvidence, b: ObjectEvidence) -> ObjectEvidence:
    """One satellite's record from two sources: the larger figure of each."""
    return ObjectEvidence(
        satno=a.satno,
        name=a.name or b.name,
        on_station_burns=max(a.on_station_burns, b.on_station_burns),
        largest_burn_m_s=max(a.largest_burn_m_s, b.largest_burn_m_s),
        busiest_window_m_s=max(a.busiest_window_m_s, b.busiest_window_m_s),
        last_burn=max(a.last_burn, b.last_burn),
        launch_phase_max_m_s=max(a.launch_phase_max_m_s, b.launch_phase_max_m_s),
    )


def merged(shipped: Evidence, live: Evidence) -> Evidence:
    """The shipped record with whatever the live NOTSO cache adds to it.

    Each source counts burns on its own, so a satellite's figures are the
    larger of the two rather than a sum, which would count a burn reported
    in both twice. The fleet's largest window can only grow.
    """
    objects = dict(shipped.objects)
    for satno, own in live.objects.items():
        objects[satno] = _larger(objects[satno], own) if satno in objects else own
    fleet = shipped.fleet
    live_top = live.fleet.largest_window_m_s
    if live_top > fleet.largest_window_m_s:
        fleet = FleetEvidence(**{
            **vars(fleet),
            "largest_window_m_s": live_top,
            "largest_window_satno": live.fleet.largest_window_satno,
        })
    return Evidence(fleet=fleet, objects=objects)


@lru_cache(maxsize=1)
def shipped_evidence() -> Evidence:
    """The record built from the JCO export, as shipped."""
    return from_json(json.loads(EVIDENCE_PATH.read_text(encoding="utf-8")))


def current_evidence() -> Evidence:
    """The shipped record merged with the NOTSO cache as it stands now."""
    from spectre.data.notso_cache import get_notso_cache

    shipped = shipped_evidence()
    try:
        live = summarise(get_notso_cache().all_records(), "NOTSO cache")
    # Whatever is wrong with the cache, the shipped record still stands.
    except Exception:
        logger.warning("NOTSO cache unreadable; realism uses the shipped evidence only", exc_info=True)
        return shipped
    return merged(shipped, live)
