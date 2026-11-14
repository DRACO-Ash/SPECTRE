"""An evaluation answered on the request runs off the event loop (0.13.0).

A scenario that samples nothing is still evaluated on the request, on a
worker thread, so a slow evaluation never stalls the other signed-in
sessions or the burn watch. One that samples runs as a session job, also on a
worker thread (SPC-113, tests/integration/test_decision_job.py).
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
    real = decision.evaluate_tree

    def spy(*args: Any, **kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return real(*args, **kwargs)

    monkeypatch.setattr(decision, "evaluate_tree", spy)
    resp = _evaluate(client, auth_cookie, _form())
    assert resp.status_code == 200
    assert seen == [False], "the evaluation ran on the event loop"
