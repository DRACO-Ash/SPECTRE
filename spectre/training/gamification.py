"""Gamification engine for SPECTRE training.

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

    config = GamificationConfig(skill_axes=axes, point_actions=actions, levels=levels)
    for problem in unlock_problems(config):
        logger.error("gamification.yaml: %s", problem)
    return config


def _unlock_problem(level: int, entry: str, scenarios: dict[str, object], tutorials: set[str]) -> str | None:
    """What is wrong with one ``kind:id`` unlock entry at *level*, if anything."""
    kind, _, item = entry.partition(":")
    if kind == "tutorial":
        return None if item in tutorials else f"level {level} unlocks {entry}, which does not exist"
    if kind not in {"scenario", "challenge"}:
        return f"level {level} unlocks {entry}, which is not a scenario, challenge or tutorial"
    scenario = scenarios.get(item)
    if scenario is None:
        return f"level {level} unlocks {entry}, which does not exist"
    if getattr(scenario, "challenge", False) != (kind == "challenge"):
        return f"level {level} lists {entry}, but its challenge flag says otherwise"
    required = getattr(scenario, "level_required", None)
    if required != level:
        return f"level {level} unlocks {entry}, but the scenario requires level {required}"
    return None


def unlock_problems(config: GamificationConfig) -> list[str]:
    """Every unlock entry that does not match the scenarios and tutorials.

    Scenarios are gated by their own level_required, so the unlock lists
    only announce them. They announced content that was locked or absent:
    level 2 named three Level 3 scenarios and level 6 two challenges that
    do not exist (audit F-169). Every scenario must also be announced once.
    """
    # Deferred: scenarios and tutorials are siblings that read YAML of their own.
    from spectre.training.scenarios import load_scenarios
    from spectre.training.tutorials import load_tutorials

    scenarios: dict[str, object] = {s.id: s for s in load_scenarios()}
    tutorials = {t.id for t in load_tutorials()}
    problems: list[str] = []
    announced: list[str] = []
    for lv in config.levels:
        for entry in lv.unlocks:
            problem = _unlock_problem(lv.level, entry, scenarios, tutorials)
            if problem:
                problems.append(problem)
            if not entry.startswith("tutorial:"):
                announced.append(entry.partition(":")[2])
    problems.extend(
        f"scenario {sid} is announced {announced.count(sid)} times, not once"
        for sid in scenarios if announced.count(sid) != 1
    )
    return problems


# ── Point award ────────────────────────────────────────────────────────────────

@dataclass
class PointAward:
    """Result of a single point-award calculation."""
    action_id:    str
    base_points:  int
    total_points: int
    axis_deltas:  dict[str, float]   # axis_id → points to add to that axis


def award_points(action_id: str) -> PointAward:
    """Compute a point award for *action_id*.

    The award depends on the action alone, not on the operator's current
    per-axis totals; the caller adds the deltas to those totals.

    Parameters
    ----------
    action_id:
        One of the ``action_id`` values from gamification.yaml.

    Returns
    -------
    PointAward with the earned points and per-axis deltas.
    Raises KeyError if action_id is unknown.
    """
    cfg     = get_config()
    action  = cfg.actions_by_id.get(action_id)
    if action is None:
        raise KeyError(f"Unknown point action: {action_id!r}")

    total        = action.base_points
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


@dataclass
class ProgressSnapshot:
    """What the level gates read from an operator's progress."""
    current_level: int
    total_points: int
    axis_points: dict[str, float]
    tutorials_completed: list[str]
    scenarios_passed: int
    challenges_passed: int


@dataclass
class LevelGate:
    """One condition the next level needs: what it asks, whether it is met, and how to meet it."""
    label: str
    met: bool
    how: str


def snapshot(progress: object) -> ProgressSnapshot:
    """The fields of a TrainingProgress (or anything shaped like one) the gates read."""
    return ProgressSnapshot(
        current_level=int(getattr(progress, "current_level", 1)),
        total_points=int(getattr(progress, "total_points", 0)),
        axis_points=dict(getattr(progress, "axis_points", {}) or {}),
        tutorials_completed=list(getattr(progress, "tutorials_completed", []) or []),
        scenarios_passed=int(getattr(progress, "scenarios_passed", 0)),
        challenges_passed=int(getattr(progress, "challenges_passed", 0)),
    )


def _axis_sources(axis: str) -> str:
    """How an axis grows, from the point actions' weights and the tutorials that feed it."""
    cfg = get_config()
    # Deferred: tutorials is a sibling that reads YAML of its own.
    from spectre.training.tutorials import load_tutorials

    earn = {
        "scenario_completed": "passing a scored scenario",
        "challenge_passed": "passing a challenge",
        "challenge_passed_first_try": "passing a challenge on the first attempt",
    }
    parts = [
        f"{earn.get(a.action_id, a.label.lower())} (+{a.base_points * a.axis_weights[axis]:g})"
        for a in cfg.point_actions if a.axis_weights.get(axis, 0.0) > 0
    ]
    parts += [f"the {t.title} tutorial (+{t.points})" for t in load_tutorials() if t.skill_axis == axis]
    return "; ".join(parts) if parts else "nothing yet"


def _tutorial_gate(cond: LevelUnlockCondition, p: ProgressSnapshot) -> LevelGate:
    # Deferred: tutorials is a sibling that reads YAML of its own.
    from spectre.training.tutorials import get_tutorial

    tid = cond.tutorial_id or ""
    tutorial = get_tutorial(tid)
    title = tutorial.title if tutorial else tid
    return LevelGate(f"Complete the {title} tutorial", tid in p.tutorials_completed,
                     "Open it in the Tutorials tab and mark it complete.")


def _axis_gate(cond: LevelUnlockCondition, p: ProgressSnapshot) -> LevelGate:
    axis = cond.axis or ""
    axis_def = get_config().axes_by_id.get(axis)
    label = axis_def.label if axis_def else axis
    have = p.axis_points.get(axis, 0.0)
    need = cond.min_points or 0.0
    return LevelGate(f"{need:,.0f} {label} points (you have {have:,.0f})", have >= need,
                     f"{label} grows by {_axis_sources(axis)}.")


def _scenario_count_gate(cond: LevelUnlockCondition, p: ProgressSnapshot) -> LevelGate:
    # A first mission pass counts here too (spectre.web.routes.missions), as the gate says (SPC-248).
    return LevelGate(f"Pass {cond.count} scored scenarios or missions (you have passed {p.scenarios_passed})",
                     p.scenarios_passed >= (cond.count or 0),
                     "Earn a star on a mission, or reach a scored scenario's pass score.")


def _challenge_count_gate(cond: LevelUnlockCondition, p: ProgressSnapshot) -> LevelGate:
    return LevelGate(f"Pass {cond.count} challenges (you have passed {p.challenges_passed})",
                     p.challenges_passed >= (cond.count or 0), "Challenges are listed in the Challenges tab.")


#: The gate each unlock condition type sets beyond its points; the default level sets none.
_CONDITION_GATES = {
    "tutorial_complete": _tutorial_gate,
    "axis_threshold": _axis_gate,
    "scenario_count": _scenario_count_gate,
    "challenge_count": _challenge_count_gate,
}


def next_level_gates(progress: object) -> list[LevelGate]:
    """Every condition the next level needs, points first, as check_level_up tests them (audit 1-19).

    Empty at the highest level.
    """
    p = snapshot(progress)
    next_lv = get_config().level_def(p.current_level + 1)
    if next_lv is None:
        return []
    need = next_lv.total_points_required
    gates = [LevelGate(f"{need:,} total points (you have {p.total_points:,})", p.total_points >= need,
                       "Points come from tutorials, mission and scenario passes, and challenge passes.")]
    cond = next_lv.unlock_condition
    gate = _CONDITION_GATES.get(cond.condition_type)
    if gate is not None:
        gates.append(gate(cond, p))
    return gates


def recommended_next_step(progress: object) -> str:
    """The full condition for the next level and what to do about the first unmet part (audit 1-19).

    It used to name the weakest axis, which said nothing about the gate in
    front of the operator and hid the pass and challenge counts.
    """
    p = snapshot(progress)
    next_lv = get_config().level_def(p.current_level + 1)
    if next_lv is None:
        return "You have reached the highest level."
    gates = next_level_gates(progress)
    needs = " and ".join(g.label[0].lower() + g.label[1:] for g in gates)
    sentence = f"Level {next_lv.level} ({next_lv.title}) needs {needs}."
    unmet = next((g for g in gates if not g.met), None)
    if unmet is None:
        return f"{sentence} You meet every condition: your next scored pass or completion advances you."
    return f"{sentence} {unmet.how}"
