"""Which red objects can act against an asset: payloads still able to manoeuvre.

Asset screening took every red-country object on the HRR watchlist in a
compatible regime as a candidate actor. In service that put a CZ-3B rocket
body at the top of an AEHF-1 screen as the most dangerous actor, with apogee
kick motors and payloads launched two decades ago ranked beside it, because
the ranking reads geometry and delta-V, which a spent stage has as much of as
an inspector.

An actor here is a payload. A rocket body or a piece of debris cannot choose a
course of action, whatever its orbit, and a payload far past its working life
is very unlikely to have the propellant or the operator to fly one. The
assessed intelligence record overrides both tests: an object it holds as
Operational or Degraded is screened whatever the catalogue or its age says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: UDL on-orbit ``objectType`` values that are never an actor.
_NON_ACTOR_TYPES = {"ROCKET BODY": "rocket body", "DEBRIS": "debris"}

#: Names that mark a stage or a fragment when the catalogue has no record:
#: rocket bodies and apogee and perigee kick motors, then debris.
_NAME_MARKERS = (
    (re.compile(r"(?:^|[\s(])(?:R/B|AKM|PKM)(?:$|[\s)])", re.IGNORECASE), "rocket body"),
    (re.compile(r"(?:^|[\s(])DEB(?:$|[\s)])", re.IGNORECASE), "debris"),
)

#: ASSUMPTION, for the analyst to confirm: a payload launched more than this
#: many years ago, and not held as operational by the intelligence record, is
#: taken to be past its working life. GEO communications satellites are
#: designed for about 15 years.
WORKING_LIFE_YEARS = 15

#: Intelligence statuses that keep an object in the screen whatever its age.
_ACTIVE_STATUSES = frozenset({"OPERATIONAL", "DEGRADED"})

#: The international designator in TLE line 1 starts with the launch year's
#: last two digits (columns 10 and 11), the same pivot as the epoch year.
_DESIGNATOR_YEAR = slice(9, 11)
_YEAR_PIVOT = 57


@dataclass(frozen=True)
class Exclusion:
    """Why one object is not screened as an actor."""

    kind: str     # "rocket body", "debris", "decayed" or "past working life"
    detail: str   # one clause for the operator, e.g. "launched 2004"


def _launch_year(record: dict[str, Any] | None, tle: str | None) -> int | None:
    """The launch year from the catalogue, or from the TLE's international designator."""
    launch = str((record or {}).get("launchDate") or "")[:4]
    if launch.isdigit():
        return int(launch)
    line1 = next((ln for ln in (tle or "").splitlines() if ln.startswith("1 ")), "")
    digits = line1[_DESIGNATOR_YEAR]
    if len(digits) == len("00") and digits.isdigit():
        year = int(digits)
        return 2000 + year if year < _YEAR_PIVOT else 1900 + year
    return None


def _type_exclusion(name: str, record: dict[str, Any] | None) -> Exclusion | None:
    """A rocket body, debris or decayed object, by catalogue record or, lacking one, by name."""
    if record:
        kind = _NON_ACTOR_TYPES.get(str(record.get("objectType") or "").strip().upper())
        if kind:
            return Exclusion(kind, f"catalogued as {kind}")
        if str(record.get("category") or "").strip().lower() == "decayed" or record.get("decayDate"):
            return Exclusion("decayed", "catalogued as decayed")
        return None
    return next(
        (Exclusion(kind, f"named as {kind}") for marker, kind in _NAME_MARKERS if marker.search(name)),
        None,
    )


def why_not_an_actor(
    name: str,
    record: dict[str, Any] | None,
    tle: str | None,
    intel: dict[str, Any] | None,
    this_year: int,
) -> Exclusion | None:
    """Why the object called *name* cannot act, or None if it is screened.

    *record* is its UDL on-orbit catalogue entry, *tle* its element set and
    *intel* its assessed intelligence record; any may be missing.
    """
    if intel and str(intel.get("status") or "").strip().upper() in _ACTIVE_STATUSES:
        return None
    excluded = _type_exclusion(name, record)
    if excluded:
        return excluded
    year = _launch_year(record, tle)
    if year is not None and this_year - year > WORKING_LIFE_YEARS:
        return Exclusion("past working life", f"launched {year}")
    return None
