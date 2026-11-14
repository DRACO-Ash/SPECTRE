"""The verdict switch's reference table, computed, read and rendered (SPC-175).

The data is tests/reference/threat_verdict_reference.csv; the owner reads it
as docs/threat_verdict_reference.md. Both are generated from the code, and
test_threat_verdict_reference fails if either drifts from it. To regenerate
after a deliberate change to the rule or the bundled data:

    PYTHONPATH=. python -c "from tests.unit._verdict_reference import write; write()"

The case is the pinned legacy one of test_threat_understanding_sweep: each
bundled red object against a deliverable 9 m/s GEO intercept (ACCESS
CRITICAL), custody held, no element-set history held.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.threat_assessment import Band
from spectre.web.routes import threat
from tests.unit.test_threat_understanding_sweep import _HELD, _NO_HISTORY, _NOW, _sweep_entry

_ROOT = Path(__file__).resolve().parents[2]
#: The data, beside the tests that read it, so the check that the table matches the code runs wherever they do.
REFERENCE_CSV = _ROOT / "tests" / "reference" / "threat_verdict_reference.csv"
#: The sheet the owner reads. docs/ does not travel in the submission package, so tests that read it skip there.
REFERENCE_MD = _ROOT / "docs" / "threat_verdict_reference.md"
COLUMNS = ("object", "name", "old_verdict", "new_verdict", "understanding", "reason")
_RED_COUNTRIES = frozenset({"CHN", "RUS", "IRN", "PRK"})


def _bundled_objects() -> list[dict[str, Any]]:
    hrr = json.loads((_ROOT / "spectre" / "data" / "hrr_default.json").read_text(encoding="utf-8"))
    return [o for o in hrr[0]["msgBody"] if o["country"] in _RED_COUNTRIES]


def bundled_red() -> list[str]:
    """The bundled red objects' catalogue numbers, in the bundled file's order."""
    return [o["satNo"] for o in _bundled_objects()]


def bundled(satno: str) -> tuple[dict[str, Any], tu.ThreatUnderstanding]:
    """One bundled red object's worst case and Threat Understanding, as the pinned legacy test builds them."""
    obj = next(o for o in _bundled_objects() if o["satNo"] == satno)
    context = threat.ConfidenceContext(data_mode=obj["tleDataMode"], custody=Custody.HELD)
    worst = threat._compute_worst_coa([_sweep_entry()], threat._red_capability(satno), 500.0, context)
    if worst is None:
        raise AssertionError(f"no worst case for {satno}")
    red = threat._Red(satno, f"{obj['line1']}\n{obj['line2']}", obj["orbitRegime"], _NO_HISTORY, _HELD, context)
    understanding = threat._red_understanding(red, worst, _NOW)
    if understanding is None:
        raise AssertionError(f"no Threat Understanding for {satno}")
    return worst, understanding


def computed_rows() -> list[dict[str, str]]:
    """Each bundled red object's old and new verdict, Understanding and reason, as the code computes them now."""
    rows = []
    for obj in _bundled_objects():
        worst, understanding = bundled(obj["satNo"])
        old = worst["threat_level"]
        switched = threat._with_verdict_switch(dict(worst), understanding, switch_on=True) or {}
        rows.append({"object": obj["satNo"], "name": obj["commonName"], "old_verdict": old,
                     "new_verdict": switched["threat_level"], "understanding": understanding.understanding.level.name,
                     "reason": switched["verdict_reason"]})
    return rows


def read_rows() -> list[dict[str, str]]:
    """The committed table."""
    with REFERENCE_CSV.open(encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _counts(rows: list[dict[str, str]]) -> str:
    by_level = Counter(r["understanding"] for r in rows)
    if len(by_level) == 1:
        (level,) = by_level
        return f"Understanding {level} for all {len(rows)}"
    return ", ".join(f"Understanding {level} for {n}" for level, n in sorted(by_level.items()))


def _largest_move(rows: list[dict[str, str]]) -> str:
    """The biggest change in the table, named, so the sheet leads with what the owner most needs to see."""
    def move(r: dict[str, str]) -> int:
        return int(Band[r["new_verdict"]]) - int(Band[r["old_verdict"]])

    biggest = max((move(r) for r in rows), default=0)
    if biggest == 0:
        return ""
    moved = [r for r in rows if move(r) == biggest]
    names = " and ".join(", ".join(r["name"] for r in moved).rsplit(", ", 1))
    return f" The largest move is {moved[0]['old_verdict']} to {moved[0]['new_verdict']}, for {names}."


def render_markdown(rows: list[dict[str, str]]) -> str:
    """The sign-off sheet: what the switch does, the case, the table and the owner's decision."""
    changed = sum(1 for r in rows if r["old_verdict"] != r["new_verdict"])
    table = "\n".join(
        f"| {r['object']} | {r['name']} | {r['old_verdict']} | {r['new_verdict']} | {r['understanding']} | "
        f"{r['reason']} |" for r in rows)
    return f"""# Threat verdict reference: sign-off for the verdict switch (SPC-175)

This is the sheet the owner signs before the verdict switch is turned on (Threat Understanding concept, section 9, decisions 2 and 3). It is generated from `tests/reference/threat_verdict_reference.csv`, and `tests/unit/test_threat_verdict_reference.py` fails if either file drifts from what the code computes, so what is signed here is what the switch does.

## What the switch changes

● Off, which is how every shipped configuration leaves it, the sweep and the screen show the current rule's verdict: the lower of geometric access and assessed capability, or access alone when nothing is known about capability. The Threat range and Understanding are shown beside it.
● On (`SPECTRE_THREAT_VERDICT_SWITCH=true` in the deployment's environment), they show the verdict of concept section 4.8: the Threat ceiling whenever Understanding is LOW or the Threat range spans four or more bands, and otherwise the current rule's verdict moved into the range.
● On the sweep, the switch changes only the verdict shown. The Threat range, Understanding, decide-by, the Decision Engine's picture, the ledger and its hash are the same either way.
● On the asset screen, it also ranks its actors by the verdict shown, so the actor named most dangerous can change. The notice of an actor whose verdict its own Threat range does not bear out no longer appears, because the verdict shown always sits inside that range.
● Each switched verdict carries its reason in one line, under the badge and in the verdict's cell, with what the current rule reads.

## The case

Each of the {len(rows)} bundled red objects against a deliverable 9 m/s GEO intercept (access CRITICAL), with custody held and no element-set history held, on its bundled element set. It is the case the pinned legacy verdicts in `tests/unit/test_threat_understanding_sweep.py` use. Every bundled element set is SYNTHETIC, so this is a demonstration case: on live data with histories held, Understanding rises and fewer verdicts read the ceiling.

## What it shows

{changed} of {len(rows)} verdicts change. {_counts(rows)}.{_largest_move(rows)}

| Object | Name | Old verdict | New verdict | Understanding | Reason |
|:-|:-|:-|:-|:-|:-|
{table}

## Decision

Concept section 9, decision 3: the verdict reads the Threat ceiling under Understanding LOW. Turning the switch on is a deployment setting, not a code change, and nothing in the image sets it.

● Agreed, the switch may be turned on: yes or no
● Owner:
● Date:
● Conditions or comments:
"""


def write() -> None:
    """Regenerate the table and the sheet from the code, after a deliberate change."""
    rows = computed_rows()
    with REFERENCE_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    REFERENCE_MD.write_text(render_markdown(rows), encoding="utf-8")
