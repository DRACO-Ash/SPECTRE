"""The job page says when a row is being drawn again on its second seed (SPC-224, evaluation F-35).

The second draw doubles a converged row's sampling time, so the page names it rather than seeming to start the
row again: "Checking hypothesis 1 of 1 on a second seed", and that its figures are the first seed's.
"""

from __future__ import annotations

from spectre.domain.decision import SECOND_SEED_STAGE, SamplingProgress, SelectorStrategy
from spectre.web.decision_job import JobState, job_view, new_job
from spectre.web.models import SessionKey
from spectre.web.planning_state import _store, get_session_state
from tests.unit.test_decision_sampled import _scenario


def test_the_page_names_the_second_draw() -> None:
    key = SessionKey(user_id=876_601, session_id="second-seed")
    state = get_session_state(key)
    job = new_job(_scenario(), SelectorStrategy.MINIMAX)
    job.state = JobState.RUNNING
    job.progress = SamplingProgress(1, 1, 20, 500, 12.0, SECOND_SEED_STAGE)
    state.decision_job = job
    try:
        message = job_view(state, job.job_id)["message"]
    finally:
        _store.pop(key, None)
    assert message == (
        "Checking hypothesis 1 of 1 on a second seed: 20 of 500 samples, 12 s of the 300 s budget used. Its figures "
        "are the first seed's; this draw says only whether they converged. Scenario epoch "
        f"{job.scenario.epoch_utc:%H:%M} UTC."
    )
