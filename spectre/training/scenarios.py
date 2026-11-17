"""Training scenario loader — reads from spectre/training/config/scenarios.yaml.

All scenario data is synthetic.  This module is read-only relative to the
YAML files; it never writes to them and never touches operational data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    # Earned only when the attempt is submitted within the scenario's time
    # limit, as the server measures it (audit F-168).
    time_limited: bool = False

    @property
    def accepted_answer(self) -> str:
        """The answer the scorer accepts, as the debrief shows it (audit 1-16).

        Empty for an objective that is only ticked.
        """
        if not self.answer:
            return ""
        if self.answer in VERDICT_LABELS:
            return VERDICT_LABELS[self.answer]
        tolerance = f" ± {self.tolerance:g}" if self.tolerance is not None else ""
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.answer}{tolerance}{unit}"


#: The verdict answers, and how the objective's radio buttons label them.
VERDICT_LABELS = {
    "compliant": "Compliant",
    "partially_compliant": "Partially Compliant",
    "non_compliant": "Non-Compliant",
}


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
    tool_workflow: str = ""

    @property
    def difficulty_colour(self) -> str:
        return {
            "easy":      "#22c55e",
            "moderate":  "#f59e0b",
            "hard":      "#ef4444",
            "very_hard": "#dc2626",
        }.get(self.difficulty, "#6b7280")

    @property
    def epoch(self) -> datetime | None:
        """The scenario's epoch in UTC, which training sets as the console's scenario start (audit 2-7, X3)."""
        try:
            moment = datetime.fromisoformat(str(self.scenario_epoch_utc).strip())
        except ValueError:
            return None
        return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)

    @property
    def workflow(self) -> tuple[str, list[str]]:
        """The tool workflow as its opening text and its numbered steps (audit 2-5, 3-17)."""
        return workflow_steps(self.tool_workflow)

    @property
    def blue_objects(self) -> list[ScenarioObject]:
        return [o for o in self.objects if o.side == "blue"]

    @property
    def red_objects(self) -> list[ScenarioObject]:
        return [o for o in self.objects if o.side == "red"]


def workflow_steps(text: str) -> tuple[str, list[str]]:
    """Split a folded workflow into the text before step 1 and one string per numbered step.

    Folded YAML joins "1. ... 2. ..." onto one line, so the steps ran together
    on screen (audit 2-5, 3-17). Steps are found in sequence, 1 then 2 and so
    on, each as a number and a full stop that starts a word and is followed by
    a space, so a figure such as 0.5 or a later "1." inside a step is not taken
    for a step. Text with no step 1 is all opening text.
    """
    starts: list[tuple[int, int]] = []
    pos = 0
    number = 1
    while match := re.compile(rf"(?<!\S){number}\.\s").search(text, pos):
        starts.append((match.start(), match.end()))
        pos = match.end()
        number += 1
    if not starts:
        return _lines(text), []
    ends = [start for start, _ in starts[1:]] + [len(text)]
    steps = [_step(text[body:end]) for (_, body), end in zip(starts, ends, strict=True)]
    return _lines(text[:starts[0][0]]), steps


def _lines(text: str) -> str:
    """*text* with each line stripped, so the folded indentation does not show."""
    return "\n".join(line.strip() for line in text.strip().splitlines())


def _step(text: str) -> str:
    """One step as running text: its wrapped lines joined, a lettered sub-item ("a. ...") kept on a line of its own."""
    joined = ""
    for line in _lines(text).splitlines():
        if not joined:
            joined = line
        elif re.match(r"[a-z]\.\s", line):
            joined += "\n" + line
        else:
            joined += " " + line
    return joined


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
            time_limited=bool(ob.get("time_limited", False)),
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
        tool_workflow=str(raw.get("tool_workflow", "")).strip(),
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
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        logger.error("Failed to load training scenarios: %s", exc)
        return []


def get_scenario(scenario_id: str) -> TrainingScenario | None:
    """Return a single scenario by ID, or None if not found."""
    return next((s for s in load_scenarios() if s.id == scenario_id), None)


def content_title(entry: str) -> str:
    """The title of the scenario, challenge or tutorial an unlock entry names (audit 1-24).

    An entry is ``kind:id``, shown as "Kind: Title"; a bare scenario id is
    shown as its title. One that names nothing known keeps its id.
    """
    kind, _, item = entry.partition(":")
    if not item:
        kind, item = "", entry
    if kind == "tutorial":
        # Deferred: tutorials is a sibling that reads YAML of its own.
        from spectre.training.tutorials import get_tutorial

        tutorial = get_tutorial(item)
        title = tutorial.title if tutorial else item
    else:
        scenario = get_scenario(item)
        title = scenario.title if scenario else item
    label = {"scenario": "Scenario", "challenge": "Challenge", "tutorial": "Tutorial"}.get(kind)
    return f"{label}: {title}" if label else title


def with_titles(text: str) -> str:
    """*text* with every scenario id in it replaced by that scenario's title (audit 4-16)."""
    for scenario in load_scenarios():
        text = re.sub(rf"\b{re.escape(scenario.id)}\b", scenario.title, text)
    return text


def scenarios_for_level(level: int) -> list[TrainingScenario]:
    """Return scenarios unlocked at or below *level*."""
    return [s for s in load_scenarios() if s.level_required <= level]
