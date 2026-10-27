"""The README's training tables are the gamification configuration.

Audit F-161. Every level title but Cadet, every threshold after 0 and four of
five axis names in README.md disagreed with gamification.yaml, and none of the
unlock conditions was mentioned.
"""

from __future__ import annotations

import re

from spectre.training.gamification import get_config
from tests.unit.test_deployment_contract import _repo_only


def _section(heading: str) -> str:
    readme = _repo_only("README.md").read_text(encoding="utf-8")
    start = readme.index(heading)
    end = readme.find("\n### ", start + len(heading))
    return readme[start:end if end != -1 else None]


def _rows(text: str) -> list[list[str]]:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in text.splitlines() if ln.startswith("|")]
    return [r for r in rows[2:] if r]


def test_the_level_table_is_the_configuration() -> None:
    cfg = get_config()
    rows = _rows(_section("### Levels and progression"))
    assert [(int(r[0]), r[1], int(re.sub(r"\D", "", r[2]))) for r in rows] == [
        (lv.level, lv.title, lv.total_points_required) for lv in cfg.levels
    ]
    for row in rows[1:]:
        assert row[3] and row[3] != "—", f"level {row[0]} has no unlock condition"


def test_the_axis_table_is_the_configuration() -> None:
    cfg = get_config()
    rows = _rows(_section("### Skill axes"))
    assert [r[0].strip("`") for r in rows] == [a.id for a in cfg.skill_axes]
