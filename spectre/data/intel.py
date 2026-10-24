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
    """Extract the NORAD catalogue number from a TLE string.

    TLE Line 1 format: ``1 NNNNNC ...``
    The five-digit NORAD number occupies columns 3–7 (1-indexed).
    """
    for line in tle.strip().splitlines():
        line = line.strip()
        if line.startswith("1 ") and len(line) >= 7:
            try:
                return int(line[2:7])
            except ValueError:
                pass
    return None
