"""No function in the tree is over cognitive complexity 15 (audits F-069, F-096 to F-098, F-114, F-136).

CI's quality gate holds changed functions to 15. With the last two over it
split (_compute_drift_phases, _objects_for_group), the whole tree is now
under, and this keeps it so: a function nobody touched cannot drift back
over unseen.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "cognitive_complexity.py"


def test_every_function_is_at_most_15() -> None:
    if not _SCRIPT.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    spec = importlib.util.spec_from_file_location("_cc_meter_tree", _SCRIPT)
    assert spec is not None and spec.loader is not None
    meter = importlib.util.module_from_spec(spec)
    sys.modules["_cc_meter_tree"] = meter
    spec.loader.exec_module(meter)
    records = meter.walk_tree([_ROOT / "spectre", _ROOT / "tle_clustering"])
    assert len(records) > 500
    assert [(r["path"], r["name"], r["score"]) for r in records if r["score"] > 15] == []
