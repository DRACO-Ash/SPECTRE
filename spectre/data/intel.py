"""Adversary satellite intelligence lookup.

Satellite intelligence records keyed by NORAD catalogue number. Each record
names its own sources in its ``source`` field. Across the set these are open
sources (McDowell 2025; CSIS Space Threat Assessment 2025; Secure World
Foundation Global Counterspace Capabilities 2025; RAND 2025; COSMIC November
2025), the JCO threat list, and the Iran Space order of battle (PAIR/PatchPlus,
February 2026). This docstring used to credit the whole set to one PAIR report
(audit F-146).

The file's ``_meta`` block carries its handling marking, UNCLASS // PAIR as
ruled by the Technical Director on 24 October 2026, and the union of the
records' sources. Keys starting with an underscore are not records.

``threat_level`` (CRITICAL, HIGH, MEDIUM, LOW) is an analyst judgement carried
with the record, with no stated method; it is shown as such, not as a score.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spectre.astro.catalogue import catalogue_number

_DATA: dict[str, dict[str, Any]] | None = None


def _load() -> dict[str, dict[str, Any]]:
    global _DATA
    if _DATA is None:
        path = Path(__file__).parent / "adversary_intel.json"
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        _DATA = {k: v for k, v in loaded.items() if not k.startswith("_")}
    return _DATA


def get_intel(satno: int | str | None) -> dict[str, Any] | None:
    """Return the intelligence record for a satellite by NORAD number, or None."""
    if satno is None:
        return None
    return _load().get(str(satno).strip())


def satno_from_tle(tle: str) -> int | None:
    """The NORAD catalogue number in line 1 of *tle*, or None when it cannot be read.

    TLE line 1 reads ``1 NNNNNC ...``: the number is in columns 3 to 7, as
    five digits or as an Alpha-5 letter and four digits (SPC-026). The reader
    is ``spectre.astro.catalogue``, shared with the history parser.
    """
    for line in tle.strip().splitlines():
        line = line.strip()
        if line.startswith("1 ") and len(line) >= 7:
            number = catalogue_number(line[2:7])
            if number is not None:
                return number
    return None
