"""Scenarios for the game-tree tests (SPC-140): the reference element sets, bound, with still and Evasive rows.

The element sets are tests/unit/_decision_reference.py's: coplanar_leo passes 10.006 km at about 14,484 s with no
burn, and 3.085 m/s retrograde in-track at the epoch reaches 20 km; plane_change crosses near the pole at about
1,411 s.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from spectre.astro.monte_carlo import SeparationSeries
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    pre_manoeuvre_state,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, ReferenceCase


def bound(side: str, case: ReferenceCase = COPLANAR_LEO, *, age: float = 0.0) -> BoundElset:
    """One side of *case*, current at the epoch, with a 24 h limit."""
    tle = case.red_tle if side == "red" else case.blue_tle
    return BoundElset(
        side=side, name=f"{side.upper()}_{case.name}", stk_name=f"{side.upper()}_{case.name}",  # type: ignore[arg-type]
        satno=90002 if side == "red" else 90001, tle=tle, data_mode="REAL", epoch=EPOCH, age_hours=age,
        limit_hours=24.0,
    )


def binding(case: ReferenceCase = COPLANAR_LEO) -> ScenarioBinding:
    return ScenarioBinding(red=bound("red", case), blue=bound("blue", case))


def still(name: str = "Hold course", row_id: str = "A0", kind: ActionType = ActionType.NO_ACTION) -> AdversaryAction:
    return AdversaryAction(row_id, name, kind, 0.5, 0.7)


def evasive(
    case: ReferenceCase = COPLANAR_LEO, *, n: int = 50, offset_h: float = 0.0, row_id: str = "A1",
) -> AdversaryAction:
    """The Evasive archetype burning *offset_h* after the epoch, from red's state then."""
    at = pre_manoeuvre_state(case.red_tle, EPOCH + timedelta(hours=offset_h))
    assert at is not None
    hypothesis = AdversaryHypothesis.from_archetype("evasive", at, n_samples=n)
    return AdversaryAction(row_id, "Evasive", ActionType.MANOEUVRE, 0.5, 0.7, hypothesis=hypothesis)


def hold(name: str = "Hold", row_id: str = "F0") -> FriendlyResponse:
    return FriendlyResponse(row_id, name, ActionType.NO_ACTION, 0.0, 1.0, 0.0)


def avoid(
    target_km: float | None = 20.0, *, hours: float = 0.0, name: str = "Avoid", row_id: str = "F1",
) -> FriendlyResponse:
    spec = None if target_km is None else ResponseBurnSpec(target_km=target_km)
    return FriendlyResponse(row_id, name, ActionType.MANOEUVRE, 0.3, 0.8, hours, burn=spec)


def scenario(
    rows: Sequence[AdversaryAction], responses: Sequence[FriendlyResponse], *, turns: int = 2,
    horizon_h: float = 6.0, bind: ReferenceCase | ScenarioBinding | None = COPLANAR_LEO,
) -> Scenario:
    """A scenario bound on both sides to a reference case, or to the binding given, or unbound for None.

    Each row's P is set to its share of the rows' sum, so the rows' P sum to 1 and the engine adds no remainder row
    (SPC-203): these cases test the tree's mechanics, and every share, so every expected-value pick and update, is the
    one the rows gave before. A row whose P was never edited must hold the panel's default, and one carrying a NOTSO
    suggestion the suggestion's P, so rows holding either are taken as given. The remainder's own tests build their
    rows apart (tests/unit/test_decision_p_remainder.py).
    """
    held = binding(bind) if isinstance(bind, ReferenceCase) else bind
    total = math.fsum(row.probability for row in rows)
    if total > 0.0 and all(row.probability_edited and row.accepted_prior is None for row in rows):
        rows = [dataclasses.replace(row, probability=row.probability / total) for row in rows]
    return Scenario(
        name="Tree", epoch_utc=EPOCH, adversary_actions=list(rows), friendly_responses=list(responses),
        horizon_hours=horizon_h, binding=held, turns=turns,
    )


class Recorder:
    """A sampler that runs the real series and records what it was asked, so a test can see the tree's keep times."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> SeparationSeries:
        self.calls.append(dict(kwargs))
        return self.inner(*args, **kwargs)
