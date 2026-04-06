"""Training scenario loader — reads from sipc/training/config/scenarios.yaml.

All scenario data is synthetic.  This module is read-only relative to the
YAML files; it never writes to them and never touches operational data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config" / "scenarios.yaml"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ScenarioObject:
    satno: int
    name: str
    side: str               # "blue" | "red"
    regime: str
    tle_line1: str
    tle_line2: str

    @property
    def tle(self) -> str:
        return f"{self.name}\n{self.tle_line1}\n{self.tle_line2}"


@dataclass
class ScenarioObjective:
    id: str
    description: str
    skill_axis: str
    points: int
    answer: str | None = None
    tolerance: float | None = None
    unit: str | None = None


@dataclass
class ManoeuvreOption:
    id: str
    label: str
    dv_ms: float
    miss_distance_km: float
    feasible: bool
    optimal: bool
    reason: str


@dataclass
class ScenarioScoring:
    passing_score: int
    optimal_score: int


@dataclass
class TrainingScenario:
    id: str
    title: str
    level_required: int
    difficulty: str
    description: str
    briefing: str
    scenario_epoch_utc: str
    horizon_hours: int
    objects: list[ScenarioObject]
    objectives: list[ScenarioObjective]
    scoring: ScenarioScoring
    manoeuvre_options: list[ManoeuvreOption] = field(default_factory=list)
    time_limit_minutes: int | None = None
    challenge: bool = False
    challenge_scenarios: list[str] = field(default_factory=list)

    @property
    def difficulty_colour(self) -> str:
        return {
            "easy":      "#22c55e",
            "moderate":  "#f59e0b",
            "hard":      "#ef4444",
            "very_hard": "#dc2626",
        }.get(self.difficulty, "#6b7280")

    @property
    def blue_objects(self) -> list[ScenarioObject]:
        return [o for o in self.objects if o.side == "blue"]

    @property
    def red_objects(self) -> list[ScenarioObject]:
        return [o for o in self.objects if o.side == "red"]


# ── Loader ─────────────────────────────────────────────────────────────────────

def _parse_scenario(raw: dict[str, Any]) -> TrainingScenario:
    objects = [
        ScenarioObject(
            satno=int(o["satno"]),
            name=o["name"],
            side=o["side"],
            regime=o.get("regime", "LEO"),
            tle_line1=o.get("tle_line1", ""),
            tle_line2=o.get("tle_line2", ""),
        )
        for o in raw.get("objects", [])
    ]
    objectives = [
        ScenarioObjective(
            id=ob["id"],
            description=ob["description"],
            skill_axis=ob["skill_axis"],
            points=int(ob["points"]),
            answer=ob.get("answer"),
            tolerance=ob.get("tolerance"),
            unit=ob.get("unit"),
        )
        for ob in raw.get("objectives", [])
    ]
    manoeuvre_options = [
        ManoeuvreOption(
            id=m["id"],
            label=m["label"],
            dv_ms=float(m["dv_ms"]),
            miss_distance_km=float(m["miss_distance_km"]),
            feasible=bool(m["feasible"]),
            optimal=bool(m["optimal"]),
            reason=m.get("reason", ""),
        )
        for m in raw.get("manoeuvre_options", [])
    ]
    scoring_raw = raw.get("scoring", {})
    scoring = ScenarioScoring(
        passing_score=int(scoring_raw.get("passing_score", 0)),
        optimal_score=int(scoring_raw.get("optimal_score", 0)),
    )
    return TrainingScenario(
        id=raw["id"],
        title=raw["title"],
        level_required=int(raw.get("level_required", 1)),
        difficulty=raw.get("difficulty", "moderate"),
        description=str(raw.get("description", "")).strip(),
        briefing=str(raw.get("briefing", "")).strip(),
        scenario_epoch_utc=raw.get("scenario_epoch_utc", "2025-01-01T00:00:00Z"),
        horizon_hours=int(raw.get("horizon_hours", 24)),
        objects=objects,
        objectives=objectives,
        scoring=scoring,
        manoeuvre_options=manoeuvre_options,
        time_limit_minutes=raw.get("time_limit_minutes"),
        challenge=bool(raw.get("challenge", False)),
        challenge_scenarios=raw.get("challenge_scenarios", []),
    )


@lru_cache(maxsize=1)
def load_scenarios() -> list[TrainingScenario]:
    """Load and cache all training scenarios from YAML.

    Returns an empty list (with a warning) if the config file is missing
    or malformed — the application continues to run without scenarios.
    """
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return [_parse_scenario(s) for s in data.get("scenarios", [])]
    except FileNotFoundError:
        logger.warning("Training scenario config not found: %s", _CONFIG_PATH)
        return []
    except Exception as exc:
        logger.error("Failed to load training scenarios: %s", exc)
        return []


def get_scenario(scenario_id: str) -> TrainingScenario | None:
    """Return a single scenario by ID, or None if not found."""
    return next((s for s in load_scenarios() if s.id == scenario_id), None)


def scenarios_for_level(level: int) -> list[TrainingScenario]:
    """Return scenarios unlocked at or below *level*."""
    return [s for s in load_scenarios() if s.level_required <= level]
