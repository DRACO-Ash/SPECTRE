"""A sampled evaluation runs off the event loop (0.13.0).

Sampling a closest approach can take about 9 s within its cap. On the event
loop that stalls every signed-in session, the burn watch included, until
SPC-113 adds its own time budget, so the route hands the evaluation to a
worker thread.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from spectre.web.routes import decision
from tests.integration.test_decision_input_validation import _evaluate, _form


def test_the_evaluation_does_not_run_on_the_event_loop(
    client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []
    real = decision.evaluate_scenario

    def spy(*args: Any, **kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return real(*args, **kwargs)

    monkeypatch.setattr(decision, "evaluate_scenario", spy)
    resp = _evaluate(client, auth_cookie, _form())
    assert resp.status_code == 200
    assert seen == [False], "the evaluation ran on the event loop"
