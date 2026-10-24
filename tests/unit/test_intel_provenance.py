"""The intelligence records say where they come from and what their levels are.

Audit F-146. The module docstring attributed the whole dataset to one PAIR
report, though the records cite open sources (McDowell, CSIS, SWF, RAND), the
JCO threat list and one PAIR/PatchPlus order of battle, and the threat levels
were shown with no word on how they were set. The file-level handling marking
awaits a ruling and is not asserted here.
"""

from __future__ import annotations

import json
from pathlib import Path

from spectre.data import intel

_CARD = Path(intel.__file__).resolve().parents[1] / "web" / "templates" / "partials" / "pair_card.html"


def test_every_record_names_its_source() -> None:
    records = json.loads(Path(intel.__file__).with_name("adversary_intel.json").read_text(encoding="utf-8"))
    assert records
    assert all(str(r.get("source") or "").strip() for r in records.values())


def test_the_module_does_not_credit_one_report_with_everything() -> None:
    doc = " ".join((intel.__doc__ or "").split())
    assert "Data sourced from the Adversary Satellite Activity Report" not in doc
    for source in ("McDowell", "CSIS", "Secure World Foundation", "RAND", "JCO"):
        assert source in doc


def test_the_card_calls_the_threat_level_a_judgement() -> None:
    assert "analyst judgement" in _CARD.read_text(encoding="utf-8")
