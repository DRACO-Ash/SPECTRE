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
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "cognitive_complexity.py"
_LIMIT = 15


def _meter() -> ModuleType:
    if not _SCRIPT.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    spec = importlib.util.spec_from_file_location("_cc_meter_tree", _SCRIPT)
    assert spec is not None and spec.loader is not None
    meter = importlib.util.module_from_spec(spec)
    sys.modules["_cc_meter_tree"] = meter
    spec.loader.exec_module(meter)
    return meter


def _over_the_limit(records: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    return [(r["path"], r["name"], r["score"]) for r in records if r["score"] > _LIMIT]


def test_every_function_is_at_most_15() -> None:
    records = _meter().walk_tree([_ROOT / "spectre", _ROOT / "tle_clustering"])
    assert len(records) > 500
    assert _over_the_limit(records) == []


def _nested_ifs(name: str, depth: int) -> str:
    """A function of *depth* nested ifs, which S3776 scores 1 + 2 + ... + depth."""
    lines = [f"def {name}(a):"]
    lines += ["    " * (level + 1) + f"if a[{level}]:" for level in range(depth)]
    lines += ["    " * (depth + 1) + "return 1", "    return 0"]
    return "\n".join(lines) + "\n"


def test_the_guard_sees_a_function_over_the_limit() -> None:
    """SPC-074: planted functions either side of the limit, so the limit is pinned from both edges.

    Nested ifs score triangular numbers (15, then 21), so a sixth, unnested
    if beside five nested ones makes the 16 that sits one over the line: a
    limit raised anywhere from 16 to 20 stops reporting it.
    """
    one_over = _nested_ifs("one_over", 5).replace("    return 0\n", "    if a[9]:\n        return 2\n    return 0\n")
    source = _nested_ifs("at_the_limit", 5) + one_over + _nested_ifs("well_over", 6)
    records = _meter().measure_source(source, "planted.py")
    assert {r["name"]: r["score"] for r in records} == {"at_the_limit": 15, "one_over": 16, "well_over": 21}
    assert _over_the_limit(records) == [("planted.py", "one_over", 16), ("planted.py", "well_over", 21)]
