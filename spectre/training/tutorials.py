"""Training tutorial loader — reads from spectre/training/config/tutorials.yaml."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config" / "tutorials.yaml"


@dataclass
class TutorialStep:
    heading: str
    body: str


@dataclass
class TutorialDef:
    id: str
    title: str
    points: int
    skill_axis: str
    steps: list[TutorialStep] = field(default_factory=list)


@lru_cache(maxsize=1)
def load_tutorials() -> list[TutorialDef]:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        result = []
        for t in data.get("tutorials", []):
            steps = [
                TutorialStep(heading=s["heading"], body=str(s.get("body", "")).strip())
                for s in t.get("steps", [])
            ]
            result.append(TutorialDef(
                id=t["id"],
                title=t["title"],
                points=int(t.get("points", 0)),
                skill_axis=t.get("skill_axis", "situational_awareness"),
                steps=steps,
            ))
        return result
    except FileNotFoundError:
        logger.warning("Tutorial config not found: %s", _CONFIG_PATH)
        return []
    except Exception as exc:
        logger.error("Failed to load tutorials: %s", exc)
        return []


def get_tutorial(tutorial_id: str) -> TutorialDef | None:
    return next((t for t in load_tutorials() if t.id == tutorial_id), None)


def tutorials_for_level(unlocked: list[str]) -> list[TutorialDef]:
    """Return tutorials whose IDs appear in the operator's unlocked list."""
    unlocked_ids = {u.removeprefix("tutorial:") for u in unlocked if u.startswith("tutorial:")}
    return [t for t in load_tutorials() if t.id in unlocked_ids]
