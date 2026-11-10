"""A sampled evaluation runs as a session job the page polls (SPC-113).

POST /plan/decision/evaluate answers a scenario that samples nothing on the
request, as before. One that would sample starts a job and returns a partial
that polls GET /plan/decision/job every 2 s until the result replaces it. One
sampled evaluation runs at a time on the server, under a 300 s budget that
starts when it runs, and it stops at its next sample when it is cancelled,
replaced, signed out of, or the server shuts down. Every outcome is named on
the page; none is exception text.

The evaluation is stood in with a fake that waits on threading events, so no
test runs a propagator, reaches the network or depends on the wall clock.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    EvaluationStoppedError,
    RunControl,
    SamplingProgress,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.web import decision_job
from spectre.web.auth import session_key_for
from spectre.web.decision_job import DecisionJob, JobState, job_view, new_job, run_job, start_job, still_wanted
from spectre.web.models import SessionKey
from spectre.web.planning_state import _store, clear_session_state, get_session_state
from spectre.web.routes import decision as decision_routes
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.unit.test_decision_figure_basis import _TEMPLATE_DIR
from tests.unit.test_decision_sampled import _scenario

_WAIT_S = 5.0
#: How many 5 ms waits a fake makes for its release or a stop before it gives up, about twice _WAIT_S: a test that
#: fails before releasing its fake must not leave a worker thread the loop's executor waits on for minutes.
_FAKE_WAITS = 2_000
_NO_JOB = "No evaluation is held for this sign-in: a newer one replaced it, or the sign-in changed."
_FAILED = "The evaluation failed; the server log has the detail. Nothing was scored."
_STARTING_SOON = (
    f"Starting: no other evaluation holds the sampling slot on this server, and the {EVALUATION_BUDGET_S:.0f} s "
    "budget starts when sampling does."
)


class _Fake:
    """An evaluation that starts, reports one sample, then waits for *release* or a stop, checking stop as it waits.

    Records whether it ran on a thread with an event loop, so a test can tell it ran off the loop. With
    *watch_stop* false it waits for *release* alone, as a last sample does, so the job reaches its end unaware of a
    stop. Every fake is released when its test ends, and gives up after _FAKE_WAITS waits, so a failing test fails
    fast rather than hanging the loop's executor.
    """

    live: ClassVar[list[_Fake]] = []

    def __init__(self, *, fail: Exception | None = None, watch_stop: bool = True) -> None:
        self.started, self.release = threading.Event(), threading.Event()
        self.fail, self.watch_stop = fail, watch_stop
        self.on_loop: list[bool] = []
        _Fake.live.append(self)

    def __call__(self, scenario: Scenario, strategy: SelectorStrategy, *, run: RunControl) -> ScenarioResult:
        try:
            asyncio.get_running_loop()
            self.on_loop.append(True)
        except RuntimeError:
            self.on_loop.append(False)
        self.started.set()
        if self.fail is not None:
            raise self.fail
        run.progress(SamplingProgress(row=1, rows=1, done=1, total=500, elapsed_s=0.0))
        for _ in range(_FAKE_WAITS):
            if self.release.wait(0.005):
                return evaluate_scenario(scenario, strategy)
            reason = run.stop() if self.watch_stop else None
            if reason:
                raise EvaluationStoppedError(reason)
        raise RuntimeError("the fake evaluation was never released")


@pytest.fixture(autouse=True)
def _release_every_fake() -> Iterator[None]:
    """Release every fake a test made, so none outlives it."""
    yield
    for fake in _Fake.live:
        fake.release.set()
    _Fake.live.clear()


async def _wait(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, _WAIT_S), "the fake evaluation never got there"


async def _settled(job: DecisionJob) -> None:
    """Wait for the job's task, bounded, so a hung job fails the test rather than hanging it."""
    assert job.task is not None
    await asyncio.wait_for(asyncio.shield(job.task), timeout=_WAIT_S)


@pytest.fixture
def owner() -> Iterator[tuple[SessionKey, Any]]:
    """A sign-in of its own, removed afterwards."""
    key = SessionKey(user_id=876_543, session_id="decision-job-test")
    state = get_session_state(key)
    yield key, state
    _store.pop(key, None)


@pytest.fixture
def second() -> Iterator[tuple[SessionKey, Any]]:
    key = SessionKey(user_id=876_544, session_id="decision-job-test-2")
    state = get_session_state(key)
    yield key, state
    _store.pop(key, None)


def _job() -> DecisionJob:
    return new_job(_scenario(), SelectorStrategy.MINIMAX)


@pytest.fixture
def fake_evaluate(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[_Fake]]:
    """Each job's evaluation is the next fake on the list; run_job reads the module's at call time."""
    fakes: list[_Fake] = []

    def next_fake(scenario: Scenario, strategy: SelectorStrategy, *, run: RunControl) -> ScenarioResult:
        return fakes.pop(0)(scenario, strategy, run=run)

    monkeypatch.setattr(decision_job, "evaluate_tree", next_fake)
    yield fakes


def _poll(client: Any, cookie: str, job_id: str) -> Any:
    return client.get("/plan/decision/job", params={"job_id": job_id}, cookies={"spectre_session": cookie})


def _held(cookie: str) -> DecisionJob:
    job = session_state(cookie).decision_job  # type: ignore[attr-defined]
    assert isinstance(job, DecisionJob)
    return job


# ── J1, J9: the POST answers a lookup at once and starts a job for a sampled evaluation ──

def test_a_scenario_that_would_sample_starts_a_job_the_page_polls(
    client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """J1."""
    monkeypatch.setattr(decision_routes, "needs_a_run", lambda _s: True)
    resp = _evaluate(client, auth_cookie, _form())
    assert resp.status_code == 200
    assert 'hx-get="/plan/decision/job?job_id=' in resp.text
    assert 'hx-trigger="every 2s"' in resp.text
    assert 'hx-target="#decision-results"' in resp.text
    assert "Heuristic ranking" not in resp.text
    job = _held(auth_cookie)
    assert f"job_id={job.job_id}" in resp.text


def test_the_first_page_of_a_job_on_an_idle_server_does_not_say_it_waits_for_another(
    client: Any, auth_cookie: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job is queued when the page is rendered, but nothing else holds the slot, so it says it is starting."""
    monkeypatch.setattr(decision_routes, "needs_a_run", lambda _s: True)
    text = " ".join(_evaluate(client, auth_cookie, _form()).text.split())
    assert "Waiting for another evaluation" not in text
    assert _STARTING_SOON in text


def test_a_lookup_scenario_is_answered_on_the_request_and_holds_no_job(client: Any, auth_cookie: str) -> None:
    """J9: and an inline answer replaces any job held, so its poll cannot overwrite it."""
    session_state(auth_cookie).decision_job = _job()  # type: ignore[attr-defined]
    resp = _evaluate(client, auth_cookie, _form())
    assert resp.status_code == 200
    assert "Heuristic ranking" in resp.text
    assert "every 2s" not in resp.text
    assert session_state(auth_cookie).decision_job is None  # type: ignore[attr-defined]


# ── J2 to J4, J6, J10, J11: the job's lifecycle ──

async def test_a_job_that_completes_holds_its_result_and_logs_it(owner: Any, fake_evaluate: list[_Fake]) -> None:
    """J2."""
    key, state = owner
    fake = _Fake()
    fake.release.set()
    fake_evaluate.append(fake)
    job = _job()
    state.decision_job = job
    await run_job(state, key, job)
    assert job.state is JobState.DONE
    assert job.result is not None and job.result.robust_best_response is not None
    assert job.stopped == ""
    assert any(line.startswith("[Decision] Evaluated 'What if': 4 adversary actions") for line in state.log_entries)


async def test_a_newer_evaluation_replaces_a_running_one(owner: Any, fake_evaluate: list[_Fake]) -> None:
    """J3: the first stops at its next check, and its id no longer finds anything."""
    key, state = owner
    first, second = _Fake(), _Fake()
    fake_evaluate.extend([first, second])
    old = _job()
    start_job(state, key, old)
    await _wait(first.started)
    new = _job()
    start_job(state, key, new)
    await _settled(old)
    assert old.state is JobState.STOPPED
    assert old.stopped == "a newer evaluation replaced it"
    assert old.result is None
    assert job_view(state, old.job_id)["message"] == _NO_JOB
    await _wait(second.started)
    second.release.set()
    await _settled(new)
    assert new.state is JobState.DONE


async def test_a_job_replaced_during_its_last_sample_is_not_scored_or_logged(
    owner: Any, fake_evaluate: list[_Fake],
) -> None:
    """The evaluation returns unaware of the replacement, as a last sample does; the job re-checks before keeping it."""
    key, state = owner
    fake = _Fake(watch_stop=False)
    fake_evaluate.append(fake)
    job = _job()
    start_job(state, key, job)
    await _wait(fake.started)
    state.decision_job = _job()
    fake.release.set()
    await _settled(job)
    assert job.state is JobState.STOPPED
    assert job.stopped == "a newer evaluation replaced it"
    assert job.result is None
    assert not any(line.startswith("[Decision] Evaluated") for line in state.log_entries)


async def test_signing_out_mid_run_stops_the_job(owner: Any, fake_evaluate: list[_Fake]) -> None:
    """J4."""
    key, state = owner
    fake = _Fake()
    fake_evaluate.append(fake)
    job = _job()
    start_job(state, key, job)
    await _wait(fake.started)
    clear_session_state(key)
    await _settled(job)
    assert job.state is JobState.STOPPED
    assert job.stopped == "this sign-in has ended"
    assert job.result is None


async def test_a_second_session_waits_for_the_first(
    owner: Any, second: Any, fake_evaluate: list[_Fake],
) -> None:
    """J6: one sampled evaluation at a time on the server; the second is queued, and its budget has not started."""
    (key_a, state_a), (key_b, state_b) = owner, second
    fake_a, fake_b = _Fake(), _Fake()
    fake_evaluate.extend([fake_a, fake_b])
    job_a, job_b = _job(), _job()
    start_job(state_a, key_a, job_a)
    await _wait(fake_a.started)
    start_job(state_b, key_b, job_b)
    assert job_view(state_b, job_b.job_id)["message"].startswith("Waiting for another evaluation on this server"), (
        "the first page, rendered before the task runs, must already say the slot is held"
    )
    for _ in range(20):
        await asyncio.sleep(0)
    assert job_a.state is JobState.RUNNING
    assert job_b.state is JobState.QUEUED
    assert not fake_b.started.is_set()
    assert job_view(state_b, job_b.job_id)["message"].startswith("Waiting for another evaluation on this server")
    fake_a.release.set()
    await _settled(job_a)
    await _wait(fake_b.started)
    assert job_b.state is JobState.RUNNING
    fake_b.release.set()
    await _settled(job_b)
    assert (job_a.state, job_b.state) == (JobState.DONE, JobState.DONE)


async def test_two_jobs_started_together_the_second_says_it_waits_once_the_first_holds_the_slot(
    owner: Any, second: Any, fake_evaluate: list[_Fake],
) -> None:
    """Both found the slot free when started; the second learns otherwise when its task asks for the slot."""
    (key_a, state_a), (key_b, state_b) = owner, second
    fake_a, fake_b = _Fake(), _Fake()
    fake_evaluate.extend([fake_a, fake_b])
    job_a, job_b = _job(), _job()
    start_job(state_a, key_a, job_a)
    start_job(state_b, key_b, job_b)
    assert not job_b.waiting
    await _wait(fake_a.started)
    for _ in range(20):
        await asyncio.sleep(0)
    assert job_b.state is JobState.QUEUED
    assert job_view(state_b, job_b.job_id)["message"].startswith("Waiting for another evaluation on this server")
    fake_a.release.set()
    await _wait(fake_b.started)
    fake_b.release.set()
    await _settled(job_b)


async def test_the_evaluation_runs_off_the_event_loop(owner: Any, fake_evaluate: list[_Fake]) -> None:
    """J10."""
    key, state = owner
    fake = _Fake()
    fake.release.set()
    fake_evaluate.append(fake)
    job = _job()
    state.decision_job = job
    await run_job(state, key, job)
    assert fake.on_loop == [False], "the evaluation ran on the event loop"


async def test_server_shutdown_stops_a_running_job(owner: Any, fake_evaluate: list[_Fake]) -> None:
    """J11: the lifespan's shutdown sets the stop, so a worker thread does not hold the exit for up to the budget."""
    from fastapi.testclient import TestClient

    from spectre.web.app import app

    key, state = owner
    try:
        with TestClient(app):
            job = _job()
            state.decision_job = job
            assert still_wanted(state, key, job) == ""
        assert still_wanted(state, key, job) == "the server is shutting down"
        fake = _Fake()
        fake_evaluate.append(fake)
        await run_job(state, key, job)
        assert job.state is JobState.STOPPED
        assert job.stopped == "the server is shutting down"
        assert not fake.started.is_set(), "a job taken off the queue after shutdown must not start"
    finally:
        decision_job.server_starting()
    assert still_wanted(state, key, job) == ""


def test_a_second_lifespan_lets_jobs_run_again(owner: Any) -> None:
    """J11: a lifespan run again in the same process (a second TestClient after a shutdown) clears the stop."""
    from fastapi.testclient import TestClient

    from spectre.web.app import app

    key, state = owner
    job = _job()
    state.decision_job = job
    try:
        with TestClient(app):
            pass
        assert still_wanted(state, key, job) == "the server is shutting down"
        with TestClient(app):
            assert still_wanted(state, key, job) == "", "the restarted server stopped a job it had not been asked to"
    finally:
        decision_job.server_starting()


# ── J5, J7, J8: the page ──

async def test_cancel_stops_the_job_and_says_nothing_was_scored(
    client: Any, auth_cookie: str, fake_evaluate: list[_Fake],
) -> None:
    """J5."""
    key = session_key_for(auth_cookie)
    assert key is not None
    state = get_session_state(key)
    fake = _Fake()
    fake_evaluate.append(fake)
    job = _job()
    start_job(state, key, job)
    await _wait(fake.started)
    resp = client.post(
        "/plan/decision/job/cancel", data={"job_id": job.job_id},
        cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
    )
    assert resp.status_code == 200
    assert "Evaluation stopped: you cancelled it. Nothing was scored; evaluate again to see the figures." in resp.text
    assert "every 2s" not in resp.text
    await _settled(job)
    assert job.state is JobState.STOPPED and job.stopped == "you cancelled it"


async def test_cancelling_a_finished_job_shows_its_results(
    client: Any, auth_cookie: str, fake_evaluate: list[_Fake],
) -> None:
    """A Cancel sent just after the last poll showed it running: the job is done, so its results are shown."""
    key = session_key_for(auth_cookie)
    assert key is not None
    state = get_session_state(key)
    fake = _Fake()
    fake.release.set()
    fake_evaluate.append(fake)
    job = _job()
    state.decision_job = job
    await run_job(state, key, job)
    resp = client.post(
        "/plan/decision/job/cancel", data={"job_id": job.job_id},
        cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
    )
    assert resp.status_code == 200
    assert "Heuristic ranking" in resp.text
    assert "every 2s" not in resp.text
    assert job.state is JobState.DONE and not job.cancelled.is_set()


def test_cancelling_another_id_changes_nothing(client: Any, auth_cookie: str) -> None:
    job = _job()
    session_state(auth_cookie).decision_job = job  # type: ignore[attr-defined]
    resp = client.post(
        "/plan/decision/job/cancel", data={"job_id": "not-this-one"},
        cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
    )
    assert resp.status_code == 200
    assert _NO_JOB in resp.text
    assert not job.cancelled.is_set() and job.state is JobState.QUEUED


async def test_a_failed_evaluation_shows_a_fixed_sentence_never_its_exception(
    client: Any, auth_cookie: str, fake_evaluate: list[_Fake], caplog: pytest.LogCaptureFixture,
) -> None:
    """J7."""
    key = session_key_for(auth_cookie)
    assert key is not None
    state = get_session_state(key)
    fake_evaluate.append(_Fake(fail=RuntimeError("<b>secret</b>")))
    job = _job()
    state.decision_job = job
    await run_job(state, key, job)
    assert job.state is JobState.FAILED
    assert f"Decision evaluation {job.job_id} failed" in caplog.text
    page = _poll(client, auth_cookie, job.job_id).text
    assert _FAILED in page
    assert "secret" not in page
    assert "every 2s" not in page


async def test_polling_a_finished_job_renders_the_results_and_stops_polling(
    client: Any, auth_cookie: str, fake_evaluate: list[_Fake],
) -> None:
    """J8."""
    key = session_key_for(auth_cookie)
    assert key is not None
    state = get_session_state(key)
    fake = _Fake()
    fake.release.set()
    fake_evaluate.append(fake)
    job = _job()
    state.decision_job = job
    await run_job(state, key, job)
    resp = _poll(client, auth_cookie, job.job_id)
    assert resp.status_code == 200
    assert "Heuristic ranking" in resp.text
    assert "every 2s" not in resp.text


def test_polling_a_running_job_shows_its_progress(client: Any, auth_cookie: str) -> None:
    job = _job()
    job.state = JobState.RUNNING
    job.progress = SamplingProgress(row=2, rows=3, done=1250, total=2000, elapsed_s=41.4)
    session_state(auth_cookie).decision_job = job  # type: ignore[attr-defined]
    text = _poll(client, auth_cookie, job.job_id).text
    epoch = job.scenario.epoch_utc.strftime("%H:%M")
    assert (f"Sampling hypothesis 2 of 3: 1,250 of 2,000 samples, 41 s of the {EVALUATION_BUDGET_S:.0f} s budget used. "
            f"Scenario epoch {epoch} UTC.") in text
    assert re.search(r'<progress[^>]*\bmax="2000"[^>]*\bvalue="1250"', text)
    form = re.search(r'<form\b[^>]*hx-post="/plan/decision/job/cancel"[^>]*>(.*?)</form>', text, re.S)
    assert form is not None, "the running job has no cancel form"
    assert f'name="job_id" value="{job.job_id}"' in form.group(1)
    assert re.search(r'<button\b[^>]*\btype="submit"[^>]*>\s*Cancel\s*</button>', form.group(1)), (
        "the cancel form has no Cancel button, so the operator cannot submit it"
    )
    assert 'hx-trigger="every 2s"' in text


def test_polling_an_unknown_id_says_no_evaluation_is_held(client: Any, auth_cookie: str) -> None:
    session_state(auth_cookie).decision_job = _job()  # type: ignore[attr-defined]
    resp = _poll(client, auth_cookie, "<script>x</script>")
    assert resp.status_code == 200
    assert _NO_JOB in resp.text
    assert "<script>x" not in resp.text
    assert "every 2s" not in resp.text


# ── J12: the partial renders under StrictUndefined in every state ──

def _render_job(view: dict[str, Any]) -> str:
    from spectre.web.app import templates as app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(app_templates.env.filters)
    env.globals.update(app_templates.env.globals)
    return env.get_template("partials/decision_job.html").render(**view, csrf_token="")


def _in_state(state: JobState, **changes: Any) -> DecisionJob:
    job = _job()
    job.state = state
    for name, value in changes.items():
        setattr(job, name, value)
    return job


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        (_in_state(JobState.QUEUED), _STARTING_SOON),
        (_in_state(JobState.QUEUED, waiting=True), f"Yours starts after it, and its {EVALUATION_BUDGET_S:.0f} s budget starts then."),
        (_in_state(JobState.RUNNING), "no sample has finished yet"),
        (_in_state(JobState.RUNNING, progress=SamplingProgress(1, 1, 5, 500, 2.0)), "5 of 500 samples"),
        (_in_state(JobState.STOPPED, stopped="you cancelled it"), "Evaluation stopped: you cancelled it."),
        (_in_state(JobState.FAILED), _FAILED),
        (None, _NO_JOB),
    ],
    ids=["queued", "queued behind another", "running before a sample", "running", "stopped", "failed", "none held"],
)
def test_the_job_partial_renders_in_every_state(job: DecisionJob | None, expected: str) -> None:
    """J12."""
    state = get_session_state(SessionKey(user_id=876_545, session_id="render"))
    state.decision_job = job
    try:
        html = _render_job(job_view(state, job.job_id if job is not None else "none"))
    finally:
        _store.pop(SessionKey(user_id=876_545, session_id="render"), None)
    assert expected in " ".join(html.split())
    polls = job is not None and job.state in (JobState.QUEUED, JobState.RUNNING)
    assert ('hx-trigger="every 2s"' in html) is polls


def test_a_job_has_an_id_the_page_cannot_guess() -> None:
    assert len(_job().job_id) >= 10 and _job().job_id != _job().job_id


def test_a_stopped_job_shows_no_progress_bar(owner: Any) -> None:
    """Progress is shown only while the job runs; a stopped job keeps its last progress but does not show it."""
    _key, state = owner
    job = _in_state(JobState.STOPPED, stopped="you cancelled it", progress=SamplingProgress(1, 1, 5, 500, 2.0))
    state.decision_job = job
    view = job_view(state, job.job_id)
    assert view["progress"] is None
    assert "<progress" not in _render_job(view)


def test_still_wanted_gives_its_reasons_in_order(owner: Any) -> None:
    """Cancelled, then shutting down, then signed out, then replaced: each named only when those before it are not."""
    key, state = owner
    job = _job()
    state.decision_job = job
    assert still_wanted(state, key, job) == ""
    held = _store[key]
    job.cancelled.set()
    decision_job.server_stopping()
    try:
        clear_session_state(key)
        state.decision_job = _job()
        assert still_wanted(state, key, job) == "you cancelled it"
        job.cancelled.clear()
        assert still_wanted(state, key, job) == "the server is shutting down"
    finally:
        decision_job.server_starting()
    assert still_wanted(state, key, job) == "this sign-in has ended"
    _store[key] = held
    assert still_wanted(state, key, job) == "a newer evaluation replaced it"


async def test_a_job_task_is_held_until_it_finishes() -> None:
    """The loop holds tasks only weakly, so the module holds each job's task until it is done (audit F-143)."""
    go = asyncio.Event()

    async def wait_for_go() -> None:
        await go.wait()

    task = decision_job._spawn(wait_for_go())
    assert task in decision_job._TASKS
    go.set()
    await asyncio.wait_for(task, timeout=_WAIT_S)
    await asyncio.sleep(0)
    assert task not in decision_job._TASKS


def test_the_epoch_is_shown_in_utc(owner: Any) -> None:
    _key, state = owner
    job = _job()
    job.scenario.epoch_utc = datetime(2026, 11, 3, 9, 41, tzinfo=UTC)
    job.state = JobState.RUNNING
    job.progress = SamplingProgress(1, 1, 1, 50, 0.4)
    state.decision_job = job
    assert job_view(state, job.job_id)["message"].endswith("Scenario epoch 09:41 UTC.")
