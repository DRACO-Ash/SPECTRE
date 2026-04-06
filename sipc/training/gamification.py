"""Gamification engine for SIPC training.

Loads config from gamification.yaml and provides:
  - award_points()   — compute and apply a point award
  - check_level_up() — determine if the operator has levelled up
  - get_config()     — the full parsed gamification config
  - LevelDef / AxisDef dataclasses for typed access

All DB writes are done by the caller (training routes) after calling these
pure functions — this module has no SQLAlchemy dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config" / "gamification.yaml"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class AxisDef:
    id: str
    label: str
    description: str
    colour: str


@dataclass
class PointActionDef:
    action_id: str
    label: str
    base_points: int
    axis_weights: dict[str, float]      # must sum to 1.0
    speed_multiplier: bool = False


@dataclass
class LevelUnlockCondition:
    condition_type: str          # "default" | "tutorial_complete" | "axis_threshold" | "scenario_count" | "challenge_count"
    tutorial_id: str | None = None
    axis: str | None = None
    min_points: float | None = None
    count: int | None = None


@dataclass
class LevelDef:
    level: int
    title: str
    description: str
    total_points_required: int
    unlock_condition: LevelUnlockCondition
    unlocks: list[str] = field(default_factory=list)


@dataclass
class GamificationConfig:
    skill_axes: list[AxisDef]
    point_actions: list[PointActionDef]
    levels: list[LevelDef]
    efficiency_bonus_dv_threshold_ms: float = 50.0

    @property
    def axes_by_id(self) -> dict[str, AxisDef]:
        return {a.id: a for a in self.skill_axes}

    @property
    def actions_by_id(self) -> dict[str, PointActionDef]:
        return {a.action_id: a for a in self.point_actions}

    def level_def(self, level: int) -> LevelDef | None:
        return next((lv for lv in self.levels if lv.level == level), None)


# ── Config loader ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_config() -> GamificationConfig:
    """Load and cache the gamification config from YAML."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("Gamification config not found: %s", _CONFIG_PATH)
        raw = {}

    axes = [
        AxisDef(id=a["id"], label=a["label"],
                description=a.get("description", ""), colour=a.get("colour", "#6b7280"))
        for a in raw.get("skill_axes", [])
    ]
    actions = [
        PointActionDef(
            action_id=pa["action_id"],
            label=pa["label"],
            base_points=int(pa.get("base_points", 0)),
            axis_weights={k: float(v) for k, v in pa.get("axis_weights", {}).items()},
            speed_multiplier=bool(pa.get("speed_multiplier", False)),
        )
        for pa in raw.get("point_actions", [])
    ]
    levels = []
    for lv in raw.get("levels", []):
        cond_raw = lv.get("unlock_condition", {})
        cond = LevelUnlockCondition(
            condition_type=cond_raw.get("type", "default"),
            tutorial_id=cond_raw.get("tutorial_id"),
            axis=cond_raw.get("axis"),
            min_points=cond_raw.get("min_points"),
            count=cond_raw.get("count"),
        )
        levels.append(LevelDef(
            level=int(lv["level"]),
            title=lv["title"],
            description=lv.get("description", ""),
            total_points_required=int(lv.get("total_points_required", 0)),
            unlock_condition=cond,
            unlocks=lv.get("unlocks", []),
        ))

    return GamificationConfig(
        skill_axes=axes,
        point_actions=actions,
        levels=levels,
        efficiency_bonus_dv_threshold_ms=float(raw.get("efficiency_bonus_dv_threshold_ms", 50.0)),
    )


# ── Point award ────────────────────────────────────────────────────────────────

@dataclass
class PointAward:
    """Result of a single point-award calculation."""
    action_id:    str
    base_points:  int
    total_points: int
    axis_deltas:  dict[str, float]   # axis_id → points to add to that axis


def award_points(
    action_id: str,
    axis_points: dict[str, float],
    speed_factor: float = 1.0,
) -> PointAward:
    """Compute a point award for *action_id*.

    Parameters
    ----------
    action_id:
        One of the ``action_id`` values from gamification.yaml.
    axis_points:
        Current per-axis totals (read-only; not modified here).
    speed_factor:
        Speed multiplier [0.5, 1.5] applied when ``speed_multiplier: true``
        in the action definition.

    Returns
    -------
    PointAward with the earned points and per-axis deltas.
    Raises KeyError if action_id is unknown.
    """
    cfg     = get_config()
    action  = cfg.actions_by_id.get(action_id)
    if action is None:
        raise KeyError(f"Unknown point action: {action_id!r}")

    multiplier   = max(0.5, min(2.0, speed_factor)) if action.speed_multiplier else 1.0
    total        = int(round(action.base_points * multiplier))
    axis_deltas  = {axis: total * weight for axis, weight in action.axis_weights.items()}

    return PointAward(
        action_id=action_id,
        base_points=action.base_points,
        total_points=total,
        axis_deltas=axis_deltas,
    )


# ── Level-up check ─────────────────────────────────────────────────────────────

@dataclass
class LevelUpResult:
    levelled_up: bool
    new_level: int
    new_level_def: LevelDef | None
    newly_unlocked: list[str]


def check_level_up(
    current_level: int,
    total_points: int,
    axis_points: dict[str, float],
    tutorials_completed: list[str],
    scenarios_passed: int,
    challenges_passed: int,
) -> LevelUpResult:
    """Check whether the operator should advance to the next level.

    Tests the *next* level's unlock condition.  Only advances one level
    per call — the caller should loop if multiple advances are possible.

    Returns
    -------
    LevelUpResult.  If ``levelled_up=False``, no advancement occurred.
    """
    cfg      = get_config()
    next_lv  = cfg.level_def(current_level + 1)
    if next_lv is None:
        return LevelUpResult(levelled_up=False, new_level=current_level, new_level_def=None, newly_unlocked=[])

    cond = next_lv.unlock_condition

    # Points prerequisite (always required)
    if total_points < next_lv.total_points_required:
        return LevelUpResult(levelled_up=False, new_level=current_level, new_level_def=None, newly_unlocked=[])

    # Condition-specific gate
    if cond.condition_type == "default":
        passes = True

    elif cond.condition_type == "tutorial_complete":
        passes = bool(cond.tutorial_id and cond.tutorial_id in tutorials_completed)

    elif cond.condition_type == "axis_threshold":
        axis_val = axis_points.get(cond.axis or "", 0.0)
        passes   = axis_val >= (cond.min_points or 0.0)

    elif cond.condition_type == "scenario_count":
        passes = scenarios_passed >= (cond.count or 0)

    elif cond.condition_type == "challenge_count":
        passes = challenges_passed >= (cond.count or 0)

    else:
        passes = False

    if not passes:
        return LevelUpResult(levelled_up=False, new_level=current_level, new_level_def=None, newly_unlocked=[])

    return LevelUpResult(
        levelled_up=True,
        new_level=current_level + 1,
        new_level_def=next_lv,
        newly_unlocked=next_lv.unlocks,
    )


# ── Progress helpers ──────────────────────────────────────────────────────────

def points_to_next_level(current_level: int, total_points: int) -> int | None:
    """Points still needed to meet the *next* level's threshold.

    Returns None if already at the maximum level.
    """
    cfg     = get_config()
    next_lv = cfg.level_def(current_level + 1)
    if next_lv is None:
        return None
    return max(0, next_lv.total_points_required - total_points)


def level_progress_fraction(current_level: int, total_points: int) -> float:
    """Fraction of progress toward next level [0.0, 1.0]."""
    cfg      = get_config()
    cur_lv   = cfg.level_def(current_level)
    next_lv  = cfg.level_def(current_level + 1)
    if next_lv is None:
        return 1.0
    cur_threshold  = cur_lv.total_points_required if cur_lv else 0
    next_threshold = next_lv.total_points_required
    span = next_threshold - cur_threshold
    if span <= 0:
        return 1.0
    return min(1.0, max(0.0, (total_points - cur_threshold) / span))


def recommended_next_step(
    axis_points: dict[str, float],
    tutorials_completed: list[str],
    current_level: int,
) -> str:
    """Return a human-readable recommendation based on the weakest skill axis."""
    cfg = get_config()
    if not axis_points:
        return "Complete the Orientation tutorial to begin your training."

    # Find the weakest axis
    all_axes  = [a.id for a in cfg.skill_axes]
    weakest   = min(all_axes, key=lambda a: axis_points.get(a, 0.0))
    axis_def  = cfg.axes_by_id.get(weakest)
    axis_label = axis_def.label if axis_def else weakest

    next_lv = cfg.level_def(current_level + 1)
    if next_lv and next_lv.unlock_condition.condition_type == "tutorial_complete":
        tid = next_lv.unlock_condition.tutorial_id or ""
        if tid not in tutorials_completed:
            return f"Complete the '{tid.replace('_', ' ').title()}' tutorial to unlock Level {current_level + 1}."

    return (
        f"Your weakest axis is {axis_label}. "
        f"Focus on scenarios that reward {axis_label.lower()} to improve your score."
    )
