"""Adversary satellite intelligence lookup.

Provides instant access to PAIR-derived satellite intelligence records
keyed by NORAD catalogue number.  Data sourced from the Adversary Satellite
Activity Report (UNCLASSIFIED // PAIR, 30 March 2026).
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
            _DATA = json.load(fh)
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
