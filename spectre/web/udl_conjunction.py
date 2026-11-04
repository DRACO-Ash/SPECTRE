"""Reading UDL conjunction (close approach) records for one object (SPC-031).

A conjunction record is UDL's statement that two objects pass close at a time
of closest approach (TCA). SPECTRE lists what UDL holds and computes nothing:
the miss distance and the probability of collision are UDL's figures as filed,
and the panel says so.

Every field is read tolerantly. A record with no readable TCA, or with a
date and no time, is skipped and counted; so is one that names two other
objects and not this one. A figure that is not a finite number in range is
shown as unreadable rather than guessed, and a reply of any other shape
yields nothing rather than an exception. Names arrive from UDL and are untrusted (audit
F-038); they are kept as plain text here and escaped by the template.

Interactions (SPC-173) reads the miss distance a second way, as a figure in
kilometres: a number, or a string holding nothing but a number, in metres or
a stated unit of metres or kilometres. Anything else is refused with a reason
that never repeats UDL's text. The field names are inferred and unverified
(SPC-033), so Interactions grades a conjunction as a probe.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

# ASSUMED UDL CONTRACT, inferred from UDL's published API and never seen live
# (this environment cannot reach UDL). A live check should confirm or correct
# exactly this list. Request: GET {UDL_BASE_URL}/conjunction, once with
# satNo1=N and once with satNo2=N, each with dataMode. Record fields read:
# id; tca or TCA (ISO 8601 date and time, UTC when no offset); missDistance or MISS_DISTANCE
# (metres unless missDistanceUnit or missDistanceUnits says otherwise);
# collisionProb or COLLISION_PROBABILITY (0 to 1); dataMode; satNo1, satNo2;
# and the nested objects sat1/sat2, else stateVector1/stateVector2, from
# which satNo, and objectName or OBJECT_NAME, are read. Upper-case spellings
# are the CCSDS conjunction data message keywords, accepted as for elsets.
CONJUNCTION_PATH = "/conjunction"
CONJUNCTION_SIDE_PARAMS = ("satNo1", "satNo2")

MAX_CONJUNCTIONS = 50

_TCA_KEYS = ("tca", "TCA")
_MISS_KEYS = ("missDistance", "MISS_DISTANCE")
_MISS_UNIT_KEYS = ("missDistanceUnit", "missDistanceUnits")
_PROB_KEYS = ("collisionProb", "COLLISION_PROBABILITY")
_NAME_KEYS = ("objectName", "OBJECT_NAME")
_NESTED_PREFIXES = ("sat", "stateVector")

# UDL's published schema gives missDistance in metres; a record that states
# its own unit overrides that, and the panel shows whichever applies.
_DEFAULT_MISS_UNIT = "m"
_UNIT_LIMIT = 16
#: The units Interactions reads a miss distance in, as kilometres per unit; any other is refused.
_KM_PER_UNIT: dict[str, float] = {
    "m": 0.001, "metre": 0.001, "metres": 0.001, "meter": 0.001, "meters": 0.001,
    "km": 1.0, "kilometre": 1.0, "kilometres": 1.0, "kilometer": 1.0, "kilometers": 1.0,
}
_NO_MISS = "UDL filed no miss distance"
_NOT_A_MISS = "the miss distance UDL filed is not a finite, non-negative number"
_UNKNOWN_UNIT = "the miss distance UDL filed is in a unit SPECTRE does not read"

NOT_GIVEN = "not given"
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class ConjunctionRow:
    """One close approach, ready to show: the other object, the TCA and UDL's figures."""

    other_satno: str
    other_name: str
    tca: datetime
    miss_distance: str
    collision_prob: str
    data_mode: str
    #: The miss distance as a figure for Interactions, None when refused, and *miss_problem* says why.
    miss_km: float | None = None
    miss_problem: str = ""

    @property
    def tca_text(self) -> str:
        return self.tca.strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass(frozen=True)
class ConjunctionReading:
    """The rows to list, newest TCA first, and what was counted on the way."""

    rows: list[ConjunctionRow]
    usable: int
    skipped: int
    unrelated: int = 0


def _first(rec: dict[str, Any], keys: Sequence[str]) -> Any:
    """The value under the first of *keys* that is present and not None."""
    for key in keys:
        if rec.get(key) is not None:
            return rec[key]
    return None


def _records(payload: Any) -> list[Any]:
    """The reply as a list of entries: a bare object is one, anything else none."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    return []


def _is_date_only(text: str) -> bool:
    """True when *text* is a calendar date with no time of day."""
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _parse_tca(raw: Any) -> datetime | None:
    """*raw* as a UTC instant, or None for anything that is not a date and time.

    A date alone is refused: midnight would claim a precision UDL never gave.
    A time whose offset carries it past the calendar's ends overflows, and is
    refused too.
    """
    if not isinstance(raw, str) or not raw.strip() or _is_date_only(raw.strip()):
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _finite(raw: Any) -> float | None:
    """*raw* as a finite float, or None. A bool is not a number here."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _miss_distance(rec: dict[str, Any]) -> str:
    raw = _first(rec, _MISS_KEYS)
    if raw is None:
        return NOT_GIVEN
    value = _finite(raw)
    if value is None or value < 0:
        return UNREADABLE
    stated = _first(rec, _MISS_UNIT_KEYS)
    unit = ("" if stated is None else str(stated).strip()[:_UNIT_LIMIT]) or _DEFAULT_MISS_UNIT
    if 0 < value < 1:
        # Significant figures, so a small stated figure never rounds to zero.
        return f"{value:.4g} {unit}"
    places = 3 if unit.lower().startswith("k") else 1
    return f"{value:,.{places}f} {unit}"


def _miss_km(rec: dict[str, Any]) -> tuple[float | None, str]:
    """The miss distance in kilometres, or None and why: unfiled, not a number, or in a unit not read."""
    raw = _first(rec, _MISS_KEYS)
    if raw is None:
        return None, _NO_MISS
    value = _finite(raw)
    if value is None or value < 0:
        return None, _NOT_A_MISS
    stated = _first(rec, _MISS_UNIT_KEYS)
    # A blank unit is no unit, as the panel reads it: one figure, one reading.
    unit = ("" if stated is None else str(stated).strip().lower()) or _DEFAULT_MISS_UNIT
    if unit not in _KM_PER_UNIT:
        return None, _UNKNOWN_UNIT
    return value * _KM_PER_UNIT[unit], ""


def _collision_prob(rec: dict[str, Any]) -> str:
    raw = _first(rec, _PROB_KEYS)
    if raw is None:
        return NOT_GIVEN
    value = _finite(raw)
    if value is None or not 0.0 <= value <= 1.0:
        return UNREADABLE
    return "0" if value == 0.0 else f"{value:.2e}"


def _nested(rec: dict[str, Any], side: int) -> dict[str, Any]:
    """The nested object for *side* (1 or 2), or an empty one."""
    for prefix in _NESTED_PREFIXES:
        obj = rec.get(f"{prefix}{side}")
        if isinstance(obj, dict):
            return obj
    return {}


def _satno_text(raw: Any) -> str:
    """A catalogue number as plain digits: 25544.0 and "025544" both read "25544".

    Anything that is not a whole number is kept as UDL gave it, trimmed.
    """
    if raw is None or isinstance(raw, bool):
        return ""
    value = _finite(raw)
    if value is not None and value.is_integer() and value >= 0:
        return str(int(value))
    return str(raw).strip()


def _side_satno(rec: dict[str, Any], side: int) -> str:
    raw = rec.get(f"satNo{side}")
    if raw is None:
        raw = _nested(rec, side).get("satNo")
    return _satno_text(raw)


def _other_side(rec: dict[str, Any], satno: int, found_by: str) -> int | None:
    """The side the other object is on, or None when the record is not about *satno*.

    The record's own numbers come first. Only when at most one side names a
    number does the query that found it decide; two numbers, neither this
    object, are another pair's close approach.
    """
    target = str(satno)
    sides = (_side_satno(rec, 1), _side_satno(rec, 2))
    if sides[0] == target:
        return 2
    if sides[1] == target:
        return 1
    if all(sides):
        return None
    return 1 if found_by == CONJUNCTION_SIDE_PARAMS[1] else 2


def _row(rec: dict[str, Any], tca: datetime, other: int, fallback_mode: str) -> ConjunctionRow:
    name = _first(_nested(rec, other), _NAME_KEYS)
    miss_km, miss_problem = _miss_km(rec)
    return ConjunctionRow(
        other_satno=_side_satno(rec, other),
        other_name="" if name is None else str(name).strip(),
        tca=tca,
        miss_distance=_miss_distance(rec),
        collision_prob=_collision_prob(rec),
        data_mode=str(rec.get("dataMode") or fallback_mode).strip().upper(),
        miss_km=miss_km,
        miss_problem=miss_problem,
    )


def _identity(rec: dict[str, Any], row: ConjunctionRow) -> tuple[str, ...]:
    """What makes two entries the same record, so one found by both queries lists once."""
    if rec.get("id"):
        return ("id", str(rec["id"]))
    return (row.tca.isoformat(), row.other_satno, row.miss_distance)


def read_conjunctions(pages: Sequence[tuple[str, Any]], satno: int, fallback_mode: str) -> ConjunctionReading:
    """Read the replies to the per-side queries into rows, newest TCA first, at most 50.

    *pages* pairs each reply with the query parameter that found it (satNo1
    or satNo2), which places the other object when at most one side names a
    number. *fallback_mode* is the data mode the lookup asked for, shown for
    a record that does not state its own. *skipped* counts entries with no
    usable TCA; *unrelated* counts records naming two other objects.
    """
    seen: dict[tuple[str, ...], ConjunctionRow] = {}
    skipped = unrelated = 0
    for found_by, payload in pages:
        for rec in _records(payload):
            tca = _parse_tca(_first(rec, _TCA_KEYS)) if isinstance(rec, dict) else None
            if tca is None:
                skipped += 1
                continue
            other = _other_side(rec, satno, found_by)
            if other is None:
                unrelated += 1
                continue
            row = _row(rec, tca, other, fallback_mode)
            seen.setdefault(_identity(rec, row), row)
    rows = sorted(seen.values(), key=lambda r: r.tca, reverse=True)
    return ConjunctionReading(
        rows=rows[:MAX_CONJUNCTIONS], usable=len(rows), skipped=skipped, unrelated=unrelated,
    )
