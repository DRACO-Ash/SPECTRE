#!/usr/bin/env python3
"""Build the shipped manoeuvre evidence from a JCO TACREP_NOTSO export.

The intercept engine judges whether a plan's delta-V is realistic against
what satellites have actually spent on station, as JCO's NOTSO reporting
states it. This reads an export of those notifications (the UDL JSON, or
the zip it arrives in) and writes ``spectre/data/manoeuvre_evidence.json``:
per satellite, the number of on-station burns, the largest, the busiest
14 days, the latest, and the largest launch-phase burn; and the same across
the fleet. Catalogue numbers, satellite names and figures only: no message
text, analyst names or addresses are copied.

The export itself is not shipped: the App Store packager drops every zip it
stages, and this file is all the application reads.

Run:  python scripts/build-manoeuvre-evidence.py <export.json | export.zip>
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spectre.domain.manoeuvre_evidence import EVIDENCE_PATH, summarise, to_json  # noqa: E402


def _records(path: Path) -> list[dict[str, Any]]:
    """The notification records in *path*, a UDL JSON export or a zip of one."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [n for n in archive.namelist() if n.endswith(".json")]
            if len(members) != 1:
                raise SystemExit(f"{path.name}: expected one JSON export inside, found {len(members)}")
            data = json.loads(archive.read(members[0]))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"{path.name}: expected a list of notification records")
    return [r for r in data if isinstance(r, dict) and r.get("msgType") == "TACREP_NOTSO"]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-1])
        return 2
    path = Path(argv[0])
    records = _records(path)
    evidence = summarise(records, f"JCO TACREP_NOTSO export {path.stem}, {len(records):,} messages")
    EVIDENCE_PATH.write_text(json.dumps(to_json(evidence), indent=1) + "\n", encoding="utf-8")
    fleet = evidence.fleet
    print(
        f"{EVIDENCE_PATH.relative_to(ROOT)}: {fleet.satellites} satellites, {fleet.burns} on-station burns, "
        f"{fleet.first_report} to {fleet.last_report}; busiest 14 days: largest "
        f"{fleet.largest_window_m_s} m/s ({fleet.largest_window_satno}), nine in ten within "
        f"{fleet.typical_window_m_s} m/s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
