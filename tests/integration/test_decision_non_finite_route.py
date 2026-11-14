"""The operator is told why an evaluation with a score that is not finite recommends nothing (SPC-221, F-32).

Probe P-14 injected a NaN lookup and the page printed "nan" in the matrix with a pick by row order. The page now
shows NON_FINITE_SCORE inline, a fixed sentence, and no figure at all; the server log names the cell.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain.decision import NON_FINITE_SCORE, ActionType, NonFiniteScoreError, SelectorStrategy
from spectre.web.auth import session_key_for
from spectre.web.decision_job import JobState, job_view, new_job, run_job
from spectre.web.planning_state import get_session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.unit.test_decision_sampled import _scenario


def test_the_page_says_why_and_shows_no_figure(
    client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setitem(decision._BASE_CA_KM, ActionType.MANOEUVRE, math.nan)
    with caplog.at_level(logging.ERROR):
        resp = _evaluate(client, auth_cookie, _form(adv_gap=["0.7"]))
    assert resp.status_code == 200
    assert resp.text == f'<p class="error-msg">{NON_FINITE_SCORE}</p>'
    assert "row 1 (Approach), response F1 (Hold) scores nan" in caplog.text


_GENERAL = "The evaluation failed; the server log has the detail. Nothing was scored."


@pytest.mark.parametrize(("error", "stopped", "message"), [
    (NonFiniteScoreError("row 1 (<b>Approach</b>), response F1 (Hold)", math.inf, 0, 0), NON_FINITE_SCORE,
     NON_FINITE_SCORE),
    (RuntimeError("<b>secret</b>"), "", _GENERAL),
], ids=["not finite", "any other"])
async def test_a_sampled_job_that_fails_shows_a_fixed_sentence_never_its_text(
    client: Any, auth_cookie: str, error: Exception, stopped: str, message: str,
) -> None:
    key = session_key_for(auth_cookie)
    assert key is not None
    state = get_session_state(key)
    job = new_job(_scenario(), SelectorStrategy.MINIMAX)
    state.decision_job = job

    def evaluate(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    await run_job(state, key, job, evaluate=evaluate)
    assert (job.state, job.stopped) == (JobState.FAILED, stopped)
    assert job_view(state, job.job_id)["message"] == message


def test_the_sentence() -> None:
    assert NON_FINITE_SCORE == (
        "Nothing is recommended: a composite score is not a finite number, so no rule can rank the responses on "
        "it. This is a fault in the engine or in a figure it was given, not in your entries; the server log "
        "names the cell."
    )
