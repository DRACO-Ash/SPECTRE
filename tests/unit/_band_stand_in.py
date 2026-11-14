"""A test stand-in that lets the Threat picture move figures, which the Decision Engine's matrix does not do.

The engine's outcome matrix reads no Threat band (SPC-204, evaluation F-14), so no collection outcome can change its
recommended response and collect first is never advised. To show that the advice follows the engine by itself, these
tests put this stand-in in place of decision._outcome, where every cell, lookup, sampled or computed, is made from its
figures: under a picture whose Threat floor is below the action line, a response that manoeuvres loses custody for
the whole horizon and has its closest approach brought inside the keep-out distance, and under one whose floor is at
or above the line, a response that does nothing does, as if the Threat band decided between acting and waiting. Two
figures move, not one: neither alone moves the picks of every fixture that reads the stand-in. It moves figures, never
a score, and the score follows from them through the engine's own scoring, whether the row's custody is the rule of
thumb or read from the bound red track's status. It is not the engine, and no test reading it says anything about the
engine's own matrix.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain import threat_understanding as tu

#: The share of the keep-out distance the disfavoured response's closest approach is brought to: inside it.
INSIDE = 0.5

@pytest.fixture
def band_moves_a_figure(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """decision._outcome with the disfavoured response's custody lost and its closest approach inside the keep-out
    distance, for the length of one test."""
    real = decision._outcome

    def stand_in(scenario: decision.Scenario, friendly: decision.FriendlyResponse, built: Any, custody: Any,
                 **extra: Any) -> decision.OutcomeMetrics:
        picture = scenario.threat
        if picture is not None:
            shown = picture.floor >= tu.ACTION_LINE
            disfavoured = decision.ActionType.NO_ACTION if shown else decision.ActionType.MANOEUVRE
            if friendly.action_type is disfavoured:
                lost = {"custody_maintained": False, "custody_gap_hours": scenario.horizon_hours,
                        "custody_degraded_hours": 0.0, "closest_approach_km": INSIDE * scenario.keep_out_km}
                built = built._replace(figures=built.figures._replace(**lost))
                if custody is not None:
                    custody = custody._replace(maintained=False, gap_hours=scenario.horizon_hours, degraded_hours=0.0)
        return real(scenario, friendly, built, custody, **extra)

    monkeypatch.setattr(decision, "_outcome", stand_in)
    yield
