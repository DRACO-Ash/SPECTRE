"""Each finished evaluation writes a durable decision record, and the operator's decision is captured on it (SPC-192).

Evaluation F-01: a finished evaluation was held in session memory and logged as one line, so nothing showed what
the operator decided, or why, once the sign-in ended. Here every evaluation that finishes, answered on the request
or run as a job, writes one DecisionRecord; one that is refused, stopped or fails writes none. The results page
asks for the decision, which a record accepts once, from the operator who ran it; the records page lists them.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from spectre.domain.decision import (
    RunControl,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.web import decision_job, decision_record
from spectre.web.decision_job import JobState, cancel_job, job_view, new_job, run_job, start_job
from spectre.web.decision_record import Operator, rule_picks, write_record
from spectre.web.models import DecisionRecord, SessionKey
from spectre.web.planning_state import _store, get_session_state
from spectre.web.routes import decision as decision_routes
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_job import _Fake, _release_every_fake, _render_job, _settled, _wait  # noqa: F401
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login, _user_id
from tests.integration.test_training_integrity import _db
from tests.integration.test_xss_escaping import _assert_inert
from tests.unit import _decision_tree_cases as cases
from tests.unit.test_decision_sampled import _scenario

_PASSWORD = "decision-record"
_UNRECORDED = (
    "This evaluation finished, but its decision record could not be written; the server log has the detail. "
    "No decision can be recorded against it."
)
_RECORDING = "The evaluation finished; writing its decision record."


def _sign_in(client: TestClient, name: str) -> str:
    """*name* signed in as an operator, created the first time it is asked for."""
    admin = _admin_cookies(client)
    _create_operator(client, admin, name, _PASSWORD)
    client.cookies.clear()
    resp = _login(client, name, _PASSWORD)
    client.cookies.clear()
    return str(resp.cookies["spectre_session"])  # type: ignore[attr-defined]


def _records(client: TestClient, username: str) -> list[DecisionRecord]:
    async def read(session: Any) -> list[DecisionRecord]:
        rows = await session.execute(
            select(DecisionRecord).where(DecisionRecord.username == username).order_by(DecisionRecord.id)
        )
        return list(rows.scalars().all())

    return _db(client, read)  # type: ignore[no-any-return]


def _count(client: TestClient) -> int:
    async def count(session: Any) -> int:
        return int((await session.execute(select(func.count()).select_from(DecisionRecord))).scalar_one())

    return _db(client, count)  # type: ignore[no-any-return]


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[ScenarioResult]:
    """Every result the route evaluates on the request, as the engine returned it."""
    seen: list[ScenarioResult] = []
    real = decision_routes.evaluate_tree

    def capture(scenario: Scenario, strategy: SelectorStrategy = SelectorStrategy.MINIMAX) -> ScenarioResult:
        result = real(scenario, strategy)
        seen.append(result)
        return result

    monkeypatch.setattr(decision_routes, "evaluate_tree", capture)
    return seen


# ── A record per finished evaluation ──

class TestAnEvaluationAnsweredOnTheRequest:
    def test_it_writes_one_record_of_what_was_recommended_by_every_rule(
        self, client: TestClient, captured: list[ScenarioResult],
    ) -> None:
        cookie = _sign_in(client, "rec_inline")
        before = datetime.now(UTC)
        resp = _evaluate(client, cookie, _form(scenario_name="Inline check", strategy="expected_value"))
        assert resp.status_code == 200
        assert "Heuristic ranking" in resp.text
        (row,) = _records(client, "rec_inline")
        (result,) = captured
        assert row.scenario_name == "Inline check"
        assert row.rule == "expected_value"
        assert (row.recommended_id, row.recommended_name) == (
            result.robust_best_response.id, result.robust_best_response.name,
        )
        picks = rule_picks(result)
        assert (row.minimax_id, row.minimin_id, row.expected_value_id) == (
            picks[SelectorStrategy.MINIMAX].id, picks[SelectorStrategy.MINIMIN].id,
            picks[SelectorStrategy.EXPECTED_VALUE].id,
        )
        assert result.provenance is not None
        assert row.code_version == result.provenance.code_version
        assert [h["sha256"] for h in json.loads(row.input_hashes)] == [i.sha256 for i in result.provenance.inputs]
        assert (row.turns, row.keep_out_km) == (1, 10.0)
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        assert before <= created <= datetime.now(UTC)
        assert row.decided_at is None

    def test_a_refused_evaluation_writes_none(self, client: TestClient) -> None:
        cookie = _sign_in(client, "rec_refused")
        resp = _evaluate(client, cookie, _form(horizon_hours="0"))
        assert "error-msg" in resp.text
        assert _records(client, "rec_refused") == []

    def test_the_results_ask_for_the_decision_on_that_record(self, client: TestClient) -> None:
        cookie = _sign_in(client, "rec_asks")
        text = _evaluate(client, cookie, _form()).text
        (row,) = _records(client, "rec_asks")
        assert f'hx-post="/plan/decision/records/{row.id}/decide"' in text
        assert "None of these" in text
        assert "Decision deferred" in text

    def test_a_record_that_cannot_be_written_says_so_and_asks_for_no_decision(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        def broken() -> Any:
            raise RuntimeError("<b>database secret</b>")

        cookie = _sign_in(client, "rec_broken")
        monkeypatch.setattr(decision_record, "_sessions", broken)
        text = " ".join(_evaluate(client, cookie, _form()).text.split())
        assert "Heuristic ranking" in text
        assert _UNRECORDED in text
        assert "/decide" not in text
        assert "database secret" not in text
        assert "Decision record for" in caplog.text


@pytest.fixture
def owner() -> Iterator[tuple[SessionKey, Any]]:
    key = SessionKey(user_id=876_600, session_id="decision-record-test")
    yield key, get_session_state(key)
    _store.pop(key, None)


class _Recorder:
    """A record writer that notes each result it is given, and may wait to be released first."""

    def __init__(self, *, hold: bool = False) -> None:
        self.results: list[ScenarioResult] = []
        self.release = threading.Event()
        self.entered = threading.Event()
        if not hold:
            self.release.set()

    async def __call__(self, result: ScenarioResult) -> int | None:
        self.entered.set()
        assert await asyncio.to_thread(self.release.wait, 5.0)
        self.results.append(result)
        return 41


class TestAJob:
    async def test_a_finished_job_writes_its_record_once(self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        key, state = owner
        fake = _Fake()
        fake.release.set()
        monkeypatch.setattr(decision_job, "evaluate_tree", fake)
        recorder = _Recorder()
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=recorder)
        state.decision_job = job
        await run_job(state, key, job)
        assert job.state is JobState.DONE
        assert recorder.results == [job.result]
        assert job.record_id == 41

    async def test_a_cancelled_job_writes_none(self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        key, state = owner
        fake = _Fake()
        monkeypatch.setattr(decision_job, "evaluate_tree", fake)
        recorder = _Recorder()
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=recorder)
        start_job(state, key, job)
        await _wait(fake.started)
        cancel_job(state, job.job_id)
        await _settled(job)
        assert job.state is JobState.STOPPED
        assert recorder.results == []
        assert job.record_id is None

    async def test_a_job_replaced_during_its_last_sample_writes_none(
        self, owner: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key, state = owner
        fake = _Fake(watch_stop=False)
        monkeypatch.setattr(decision_job, "evaluate_tree", fake)
        recorder = _Recorder()
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=recorder)
        start_job(state, key, job)
        await _wait(fake.started)
        state.decision_job = new_job(_scenario(), SelectorStrategy.MINIMAX)
        fake.release.set()
        await _settled(job)
        assert job.state is JobState.STOPPED
        assert recorder.results == []

    async def test_a_failed_job_writes_none(self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        key, state = owner
        monkeypatch.setattr(decision_job, "evaluate_tree", _Fake(fail=RuntimeError("boom")))
        recorder = _Recorder()
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=recorder)
        state.decision_job = job
        await run_job(state, key, job)
        assert job.state is JobState.FAILED
        assert recorder.results == []

    async def test_while_its_record_is_written_it_polls_and_cannot_be_cancelled(
        self, owner: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The evaluation has finished; a Cancel then would leave a record of results the page never showed."""
        key, state = owner
        fake = _Fake()
        fake.release.set()
        monkeypatch.setattr(decision_job, "evaluate_tree", fake)
        recorder = _Recorder(hold=True)
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=recorder)
        start_job(state, key, job)
        await _wait(recorder.entered)
        assert job.state is JobState.RECORDING
        view = job_view(state, job.job_id)
        assert (view["message"], view["polling"], view["progress"]) == (_RECORDING, True, None)
        cancel_job(state, job.job_id)
        assert not job.cancelled.is_set()
        page = " ".join(_render_job(view).split())
        assert 'hx-trigger="every 2s"' in page
        assert "/plan/decision/job/cancel" not in page
        recorder.release.set()
        await _settled(job)
        assert job.state is JobState.DONE
        assert job.record_id == 41

    async def test_a_tree_evaluation_writes_its_record_with_its_turns(
        self, owner: Any, client: TestClient,
    ) -> None:
        """A real two-turn tree, evaluated by the job's own evaluate_tree, recorded by the real writer."""
        cookie, job = await _tree_job(owner, client, "rec_tree", "Hold")
        assert job.result is not None and job.result.tree is not None and job.result.tree.selection is not None
        (row,) = _records(client, "rec_tree")
        assert row.id == job.record_id
        assert (row.turns, row.scenario_name) == (2, "Tree record")
        assert row.recommended_id == job.result.robust_best_response.id
        assert json.loads(row.tree_recommendation) == list(job.result.tree.selection.recommendation)
        text = _flat(_page(client, cookie))
        matrix = job.result.robust_best_response
        assert f"The one-turn matrix recommends {matrix.name} ({matrix.id})." in text
        assert f"Over the 2 turns, minimax picks {row.tree_pick_name} ({row.tree_pick_id}) for turn 1." in text
        assert "Turn 1: Hold." in text

    async def test_hostile_response_names_in_a_trees_lines_are_inert_on_the_records_page(
        self, owner: Any, client: TestClient,
    ) -> None:
        cookie, _job = await _tree_job(owner, client, "xss_tree", _PAYLOAD)
        resp = _page(client, cookie)
        _assert_inert(resp)
        assert "Turn 1: &lt;script&gt;" in resp.text

    async def test_a_job_whose_record_is_being_written_when_it_stops_being_wanted_stops_and_keeps_its_record(
        self, owner: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Replaced or signed out while recording: the evaluation finished and its record stands, but no results."""
        key, state = owner
        fake = _Fake()
        fake.release.set()
        monkeypatch.setattr(decision_job, "evaluate_tree", fake)
        for unwanted, reason in (
            (lambda: setattr(state, "decision_job", new_job(_scenario(), SelectorStrategy.MINIMAX)),
             "a newer evaluation replaced it"),
            (lambda: _store.pop(key, None), "this sign-in has ended"),
        ):
            recorder = _Recorder(hold=True)
            job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=recorder)
            _store[key] = (time.monotonic(), state)
            start_job(state, key, job)
            await _wait(recorder.entered)
            unwanted()
            recorder.release.set()
            await _settled(job)
            assert (job.state, job.stopped) == (JobState.STOPPED, reason)
            assert (len(recorder.results), job.record_id, job.result) == (1, 41, None)


async def _tree_job(owner: Any, client: TestClient, username: str, hold_name: str) -> tuple[str, Any]:
    """A real two-turn tree run as *username*'s job, recorded by the real writer, with Hold named *hold_name*."""
    key, state = owner
    cookie = _sign_in(client, username)
    user_id = _user_id(client, _admin_cookies(client), username)
    scenario = cases.scenario([cases.still()], [cases.hold(hold_name), cases.avoid(None)])
    scenario = dataclasses.replace(scenario, name="Tree record")

    async def record(result: ScenarioResult) -> int | None:
        return await write_record(result, Operator(user_id, username))

    job = new_job(scenario, SelectorStrategy.MINIMAX, record=record)
    state.decision_job = job
    await run_job(state, key, job)
    assert job.state is JobState.DONE, job.stopped
    return cookie, job


def _route_job(client: TestClient, monkeypatch: pytest.MonkeyPatch, username: str) -> tuple[str, Any, DecisionRecord]:
    """A job the route starts for *username*, run to its end, and the record it wrote.

    The evaluation waits until the request that started it has answered, so the record is written after that
    request's own session has closed, and the test reads it in a known order.
    """
    cookie = _sign_in(client, username)
    monkeypatch.setattr(decision_routes, "needs_a_run", lambda _s: True)
    answered = threading.Event()

    def quick(scenario: Scenario, strategy: SelectorStrategy, *, run: RunControl) -> ScenarioResult:
        assert answered.wait(5.0)
        return evaluate_scenario(scenario, strategy)

    monkeypatch.setattr(decision_job, "evaluate_tree", quick)
    assert "every 2s" in _evaluate(client, cookie, _form(scenario_name="Job check", **_TWO_RESPONSES)).text
    answered.set()
    job = session_state(cookie).decision_job  # type: ignore[attr-defined]

    async def settle() -> None:
        await asyncio.wait_for(asyncio.shield(job.task), timeout=5.0)

    client.portal.call(settle)  # type: ignore[union-attr]
    (row,) = _records(client, username)
    return cookie, job, row


def _job_page(client: TestClient, cookie: str, job: Any) -> str:
    resp = client.get("/plan/decision/job", params={"job_id": job.job_id}, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def test_a_job_started_by_the_route_records_and_its_results_ask_for_the_decision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cookie, job, row = _route_job(client, monkeypatch, "rec_job_route")
    assert row.scenario_name == "Job check"
    assert f'hx-post="/plan/decision/records/{row.id}/decide"' in _job_page(client, cookie, job)


def test_a_finished_jobs_results_shown_again_show_the_decision_already_made(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll or a late Cancel shows the results again: from the record as stored, not as it was written."""
    cookie, job, row = _route_job(client, monkeypatch, "rec_job_again")
    _decide(client, cookie, row.id, "response-1", "Avoid it.")
    page = _job_page(client, cookie, job)
    assert "Decision recorded " in page and ": Avoid (F2)." in page
    assert "Rationale: Avoid it." in page
    assert f'hx-post="/plan/decision/records/{row.id}/decide"' not in page


# ── The operator's decision: once, by the operator who ran it ──

_TWO_RESPONSES = {
    "fr_id": ["F1", "F2"], "fr_name": ["Hold", "Avoid"], "fr_type": ["no_action", "manoeuvre"],
    "fr_cost": ["0.0", "0.3"], "fr_rev": ["1.0", "0.8"], "fr_time": ["0.1", "4"],
}
_ONCE = "A decision is already recorded for this evaluation; a record takes one decision, once."
_NOT_YOURS = "No decision record of yours has that number."
_NO_RECORD = _NOT_YOURS
_CHOOSE = "Choose one of the listed decisions."
_SAY_WHY = "Give the rationale: it is required when none of these responses is chosen."


def _evaluated(client: TestClient, cookie: str, username: str, name: str = "Decide check") -> DecisionRecord:
    """Evaluate a two-response scenario as *cookie* and return the record it wrote."""
    before = len(_records(client, username))
    assert _evaluate(client, cookie, _form(scenario_name=name, **_TWO_RESPONSES)).status_code == 200
    rows = _records(client, username)
    assert len(rows) == before + 1
    return rows[-1]


def _decide(client: TestClient, cookie: str, record_id: int, decision: str, rationale: str = "") -> Any:
    return client.post(
        f"/plan/decision/records/{record_id}/decide", data={"decision": decision, "rationale": rationale},
        cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )


def _row(client: TestClient, record_id: int) -> DecisionRecord:
    async def read(session: Any) -> DecisionRecord:
        return (await session.execute(  # type: ignore[no-any-return]
            select(DecisionRecord).where(DecisionRecord.id == record_id)
        )).scalar_one()

    return _db(client, read)  # type: ignore[no-any-return]


def _flat(resp: Any) -> str:
    return " ".join(resp.text.split())


class TestTheDecision:
    def test_it_is_stored_with_its_own_utc_time(self, client: TestClient) -> None:
        cookie = _sign_in(client, "dec_once")
        record = _evaluated(client, cookie, "dec_once")
        before = datetime.now(UTC)
        resp = _decide(client, cookie, record.id, "response-1", "Avoid keeps the keep-out clear.")
        assert resp.status_code == 200
        row = _row(client, record.id)
        assert (row.decision, row.decision_name, row.rationale) == (
            "response-1", "Avoid (F2)", "Avoid keeps the keep-out clear.",
        )
        assert row.decided_at is not None
        decided = row.decided_at if row.decided_at.tzinfo else row.decided_at.replace(tzinfo=UTC)
        assert before <= decided <= datetime.now(UTC)
        text = _flat(resp)
        assert "Decision recorded " in text and ": Avoid (F2)." in text
        assert "Rationale: Avoid keeps the keep-out clear." in text
        assert 'hx-post="/plan/decision/records/' not in text

    def test_a_second_decision_is_refused_and_the_first_kept(self, client: TestClient) -> None:
        cookie = _sign_in(client, "dec_twice")
        record = _evaluated(client, cookie, "dec_twice")
        assert _decide(client, cookie, record.id, "deferred").status_code == 200
        resp = _decide(client, cookie, record.id, "response-0", "Changed my mind.")
        assert resp.status_code == 200
        assert _ONCE in _flat(resp)
        row = _row(client, record.id)
        assert (row.decision, row.decision_name, row.rationale) == ("deferred", "Decision deferred", None)

    def test_another_operator_is_refused(self, client: TestClient) -> None:
        owner_cookie = _sign_in(client, "dec_owner")
        record = _evaluated(client, owner_cookie, "dec_owner")
        other = _sign_in(client, "dec_other")
        resp = _decide(client, other, record.id, "response-0", "Not mine to make.")
        assert _NOT_YOURS in _flat(resp)
        assert "Hold (F1)" not in resp.text
        assert _row(client, record.id).decided_at is None

    def test_an_admin_is_refused_another_operators_decision(self, client: TestClient) -> None:
        cookie = _sign_in(client, "dec_admin_target")
        record = _evaluated(client, cookie, "dec_admin_target")
        admin = _admin_cookies(client)["spectre_session"]
        resp = _decide(client, admin, record.id, "response-0", "An admin deciding for them.")
        assert _NOT_YOURS in _flat(resp)
        assert _row(client, record.id).decided_at is None

    def test_of_two_posts_that_race_only_the_first_is_recorded(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The second read the record before the first wrote, so its own checks passed; the write itself refuses it."""
        cookie = _sign_in(client, "dec_race")
        record = _evaluated(client, cookie, "dec_race")
        assert _decide(client, cookie, record.id, "response-0", "First in.").status_code == 200
        monkeypatch.setattr(decision_record, "_refusal", lambda *_args: "")
        operator = Operator(record.user_id or 0, "dec_race")

        async def late(session: Any) -> decision_record.Decided:
            return await decision_record.decide(session, record.id, operator, "deferred", "Second in.")

        decided = _db(client, late)
        assert decided.problem == _ONCE
        assert decided.row is not None and decided.row.rationale == "First in."
        assert (_row(client, record.id).decision, _row(client, record.id).rationale) == ("response-0", "First in.")

    def test_an_unknown_record_is_refused(self, client: TestClient) -> None:
        cookie = _sign_in(client, "dec_unknown")
        assert _NO_RECORD in _flat(_decide(client, cookie, 999_999, "deferred"))

    @pytest.mark.parametrize(
        ("decision", "name"),
        [("", "blank"), ("response-2", "past"), ("response-x", "word"), ("maybe", "maybe"), ("response--1", "neg")],
    )
    def test_a_decision_not_on_the_list_is_refused(self, client: TestClient, decision: str, name: str) -> None:
        username = f"dec_unlisted_{name}"
        cookie = _sign_in(client, username)
        record = _evaluated(client, cookie, username)
        resp = _decide(client, cookie, record.id, decision, "Some reason.")
        assert _CHOOSE in _flat(resp)
        assert _row(client, record.id).decided_at is None
        assert f'hx-post="/plan/decision/records/{record.id}/decide"' in resp.text
        assert "Some reason." in resp.text


class TestTheRationale:
    def test_two_thousand_characters_are_taken(self, client: TestClient) -> None:
        cookie = _sign_in(client, "why_2000")
        record = _evaluated(client, cookie, "why_2000")
        assert _decide(client, cookie, record.id, "response-0", "x" * 2000).status_code == 200
        assert _row(client, record.id).rationale == "x" * 2000

    def test_one_more_is_refused_and_nothing_stored(self, client: TestClient) -> None:
        cookie = _sign_in(client, "why_2001")
        record = _evaluated(client, cookie, "why_2001")
        resp = _decide(client, cookie, record.id, "response-0", "x" * 2001)
        assert "The rationale is at most 2,000 characters; this one is 2,001." in _flat(resp)
        assert _row(client, record.id).decided_at is None

    @pytest.mark.parametrize(("rationale", "name"), [("", "blank"), ("   \n ", "spaces")])
    def test_none_of_these_needs_one(self, client: TestClient, rationale: str, name: str) -> None:
        username = f"why_none_{name}"
        cookie = _sign_in(client, username)
        record = _evaluated(client, cookie, username)
        assert _SAY_WHY in _flat(_decide(client, cookie, record.id, "none", rationale))
        assert _row(client, record.id).decided_at is None

    def test_none_of_these_with_one_is_taken(self, client: TestClient) -> None:
        cookie = _sign_in(client, "why_none_given")
        record = _evaluated(client, cookie, "why_none_given")
        _decide(client, cookie, record.id, "none", "  Both responses expose the asset.  ")
        row = _row(client, record.id)
        assert (row.decision, row.decision_name, row.rationale) == (
            "none", "None of these", "Both responses expose the asset.",
        )

    def test_a_deferred_decision_needs_none(self, client: TestClient) -> None:
        cookie = _sign_in(client, "why_deferred")
        record = _evaluated(client, cookie, "why_deferred")
        resp = _decide(client, cookie, record.id, "deferred")
        assert "No rationale given." in _flat(resp)
        assert _row(client, record.id).decision == "deferred"


class TestTheDecisionRoute:
    def test_it_refuses_a_post_without_the_csrf_token(self, client: TestClient) -> None:
        cookie = _sign_in(client, "csrf_decider")
        record = _evaluated(client, cookie, "csrf_decider")
        resp = client.post(
            f"/plan/decision/records/{record.id}/decide", data={"decision": "deferred"},
            cookies={"spectre_session": cookie},
        )
        assert resp.status_code == 403
        assert _row(client, record.id).decided_at is None

    def test_it_refuses_a_post_with_no_sign_in(self, client: TestClient) -> None:
        cookie = _sign_in(client, "anon_decider")
        record = _evaluated(client, cookie, "anon_decider")
        client.cookies.clear()
        resp = client.post(
            f"/plan/decision/records/{record.id}/decide", data={"decision": "deferred"},
            headers=csrf_headers(cookie), follow_redirects=False,
        )
        assert resp.status_code in (302, 403)
        assert _row(client, record.id).decided_at is None


# ── The records page ──

def _page(client: TestClient, cookie: str) -> Any:
    resp = client.get("/plan/decision/records", cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp


class TestTheRecordsPage:
    def test_it_lists_the_operators_own_records_newest_first(self, client: TestClient) -> None:
        cookie = _sign_in(client, "page_mine")
        first = _evaluated(client, cookie, "page_mine", "First look")
        second = _evaluated(client, cookie, "page_mine", "Second look")
        other = _sign_in(client, "page_theirs")
        _evaluated(client, other, "page_theirs", "Their look")
        text = _flat(_page(client, cookie))
        assert text.index("Second look") < text.index("First look")
        assert "Their look" not in text
        assert f"Record {second.id}" in text and f"Record {first.id}" in text
        assert "No decision recorded" in text

    def test_each_record_shows_the_rule_its_pick_and_all_three_rules_picks(self, client: TestClient) -> None:
        cookie = _sign_in(client, "page_rules")
        record = _evaluated(client, cookie, "page_rules")
        text = _flat(_page(client, cookie))
        assert f"Rule used: minimax. Recommended: {record.recommended_name} ({record.recommended_id})." in text
        assert f"Minimax picks {record.minimax_name} ({record.minimax_id})" in text
        assert f"minimin picks {record.minimin_name} ({record.minimin_id})" in text
        assert f"expected value picks {record.expected_value_name} ({record.expected_value_id})" in text

    def test_it_shows_the_decision_its_rationale_and_its_time(self, client: TestClient) -> None:
        cookie = _sign_in(client, "page_decided")
        record = _evaluated(client, cookie, "page_decided")
        _decide(client, cookie, record.id, "response-0", "Hold is enough.")
        text = _flat(_page(client, cookie))
        assert "Decided " in text and ": Hold (F1)." in text
        assert "Rationale: Hold is enough." in text
        assert "No decision recorded" not in text

    def test_an_admin_sees_every_record_and_whose_it_is(self, client: TestClient) -> None:
        mine = _sign_in(client, "page_admin_a")
        _evaluated(client, mine, "page_admin_a", "Alpha look")
        theirs = _sign_in(client, "page_admin_b")
        _evaluated(client, theirs, "page_admin_b", "Bravo look")
        text = _flat(_page(client, _admin_cookies(client)["spectre_session"]))
        assert "Alpha look" in text and "Bravo look" in text
        assert "Run by page_admin_a" in text and "Run by page_admin_b" in text
        assert "Every operator's records" in text

    def test_an_operator_is_not_told_whose_records_they_are(self, client: TestClient) -> None:
        cookie = _sign_in(client, "page_self")
        _evaluated(client, cookie, "page_self")
        text = _page(client, cookie).text
        assert "Run by" not in text
        assert "Your records" in text

    def test_it_survives_signing_out_and_in_again(self, client: TestClient) -> None:
        cookie = _sign_in(client, "page_return")
        record = _evaluated(client, cookie, "page_return", "Before sign-out")
        _decide(client, cookie, record.id, "none", "Neither response fits.")
        out = client.post("/logout", cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
                          follow_redirects=False)
        assert out.status_code in (302, 303)
        assert client.get("/plan/decision/records", cookies={"spectre_session": cookie},
                          follow_redirects=False).status_code == 302
        client.cookies.clear()
        again = str(_login(client, "page_return", _PASSWORD).cookies["spectre_session"])  # type: ignore[attr-defined]
        client.cookies.clear()
        text = _flat(_page(client, again))
        assert "Before sign-out" in text
        assert "Rationale: Neither response fits." in text

    def test_it_is_reachable_from_the_decision_panel(self, client: TestClient) -> None:
        cookie = _sign_in(client, "page_link")
        panel = client.get("/plan/decision/panel", cookies={"spectre_session": cookie})
        assert 'href="/plan/decision/records"' in panel.text

    def test_it_needs_a_sign_in(self, client: TestClient) -> None:
        client.cookies.clear()
        resp = client.get("/plan/decision/records", follow_redirects=False)
        assert resp.status_code == 302


# ── Escaping: a scenario name and a rationale are the operator's text, shown as text ──

_PAYLOAD = "<script>alert('xss')</script>"


class TestOperatorTextIsEscaped:
    def test_a_hostile_rationale_comes_back_inert_from_the_decision(self, client: TestClient) -> None:
        cookie = _sign_in(client, "xss_rationale")
        record = _evaluated(client, cookie, "xss_rationale")
        _assert_inert(_decide(client, cookie, record.id, "response-0", _PAYLOAD))

    def test_a_refused_hostile_rationale_comes_back_inert(self, client: TestClient) -> None:
        cookie = _sign_in(client, "xss_refused")
        record = _evaluated(client, cookie, "xss_refused")
        _assert_inert(_decide(client, cookie, record.id, "maybe", _PAYLOAD))

    def test_a_hostile_scenario_name_and_rationale_are_inert_on_the_records_page(self, client: TestClient) -> None:
        cookie = _sign_in(client, "xss_page")
        record = _evaluated(client, cookie, "xss_page", _PAYLOAD)
        _decide(client, cookie, record.id, "none", _PAYLOAD)
        resp = _page(client, cookie)
        _assert_inert(resp)
        assert resp.text.count("&lt;script&gt;") >= 2

    def test_a_hostile_response_name_is_inert_in_the_decision_select(self, client: TestClient) -> None:
        cookie = _sign_in(client, "xss_select")
        form = _form(**{**_TWO_RESPONSES, "fr_name": [_PAYLOAD, "Avoid"]})
        _assert_inert(_evaluate(client, cookie, form))


# ── A deleted account's records outlive it, and pass to no later namesake ──

def test_a_deleted_accounts_records_stay_readable_by_an_admin_and_pass_to_no_namesake(client: TestClient) -> None:
    cookie = _sign_in(client, "gone_operator")
    record = _evaluated(client, cookie, "gone_operator", "Before deletion")
    admin = _admin_cookies(client)
    old_id = _user_id(client, admin, "gone_operator")
    assert client.delete(f"/admin/users/{old_id}", cookies=admin, headers=csrf_headers(admin)).status_code == 200
    row = _row(client, record.id)
    assert (row.user_id, row.username) == (None, "gone_operator")
    namesake = _sign_in(client, "gone_operator")
    assert "Before deletion" not in _page(client, namesake).text
    assert _NOT_YOURS in _flat(_decide(client, namesake, record.id, "deferred"))
    admin_text = _flat(_page(client, _admin_cookies(client)["spectre_session"]))
    assert "Before deletion" in admin_text and "Run by gone_operator" in admin_text


# ── Review of SPC-192 ──

_CONTROL = "The rationale holds a control character, which a record cannot store; remove it and record again."


class TestTextTheDatabaseCannotStore:
    """PostgreSQL's text refuses U+0000, which SQLite stores: both databases must answer alike."""

    @pytest.mark.parametrize(("rationale", "name"), [("a\x00b", "nul"), ("a\x01b", "soh"), ("a\x1bb", "esc"),
                                                     ("a\x7fb", "del")])
    def test_a_rationale_holding_a_control_character_is_refused(
        self, client: TestClient, rationale: str, name: str,
    ) -> None:
        username = f"ctl_{name}"
        cookie = _sign_in(client, username)
        record = _evaluated(client, cookie, username)
        resp = _decide(client, cookie, record.id, "response-0", rationale)
        assert resp.status_code == 200
        assert _CONTROL in _flat(resp)
        assert _row(client, record.id).decided_at is None

    def test_line_breaks_and_tabs_are_taken(self, client: TestClient) -> None:
        cookie = _sign_in(client, "ctl_lines")
        record = _evaluated(client, cookie, "ctl_lines")
        assert _CONTROL not in _flat(_decide(client, cookie, record.id, "response-0", "Line one.\r\nLine\ttwo."))
        assert _row(client, record.id).rationale == "Line one.\r\nLine\ttwo."

    def test_a_nul_in_the_scenario_and_response_names_still_writes_the_record(self, client: TestClient) -> None:
        cookie = _sign_in(client, "ctl_names")
        form = _form(scenario_name="X\x00Y", **{**_TWO_RESPONSES, "fr_name": ["Ho\x00ld", "Avoid"]})
        assert _UNRECORDED not in _flat(_evaluate(client, cookie, form))
        (row,) = _records(client, "ctl_names")
        assert row.scenario_name == "X\ufffdY"
        _decide(client, cookie, row.id, "response-0", "Hold.")
        assert _row(client, row.id).decision_name == "Ho\ufffdld (F1)"


class TestARecordIsWrittenOnlyForAnAccountThatStillExists:
    def test_a_write_landing_after_its_account_was_deleted_writes_nothing_a_newcomer_could_inherit(
        self, client: TestClient, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The write began before the deletion and lands after it; SQLite may hand the freed id to the next account."""
        _sign_in(client, "gone_inflight")
        admin = _admin_cookies(client)
        old_id = _user_id(client, admin, "gone_inflight")
        assert client.delete(f"/admin/users/{old_id}", cookies=admin, headers=csrf_headers(admin)).status_code == 200
        newcomer = _sign_in(client, "gone_newcomer")
        result = evaluate_scenario(dataclasses.replace(_scenario(), name="In flight"))

        async def land() -> int | None:
            return await write_record(result, Operator(old_id, "gone_inflight"))

        assert client.portal.call(land) is None  # type: ignore[union-attr]
        assert _records(client, "gone_inflight") == []
        assert "In flight" not in _page(client, newcomer).text
        assert "no longer exists" in caplog.text

    def test_a_write_for_an_id_now_held_by_another_account_writes_nothing(self, client: TestClient) -> None:
        cookie = _sign_in(client, "gone_holder")
        holder = _user_id(client, _admin_cookies(client), "gone_holder")
        result = evaluate_scenario(dataclasses.replace(_scenario(), name="Not theirs"))

        async def land() -> int | None:
            return await write_record(result, Operator(holder, "gone_someone_else"))

        assert client.portal.call(land) is None  # type: ignore[union-attr]
        assert "Not theirs" not in _page(client, cookie).text


class TestRefusalsTellNothingOfAnotherOperatorsRecords:
    def test_a_record_of_anothers_and_one_that_does_not_exist_are_refused_alike(self, client: TestClient) -> None:
        owner = _sign_in(client, "enum_owner")
        record = _evaluated(client, owner, "enum_owner")
        other = _sign_in(client, "enum_other")
        theirs = _flat(_decide(client, other, record.id, "deferred"))
        missing = _flat(_decide(client, other, 2_000_000_000, "deferred"))
        assert _NOT_YOURS in theirs
        assert theirs.replace(str(record.id), "N") == missing.replace("2000000000", "N")

    def test_a_decided_record_refuses_any_second_post_as_decided(self, client: TestClient) -> None:
        """Whatever the second post holds, the refusal is that the record is decided."""
        cookie = _sign_in(client, "dec_second_any")
        record = _evaluated(client, cookie, "dec_second_any")
        _decide(client, cookie, record.id, "deferred")
        for decision, rationale in (("maybe", ""), ("none", ""), ("response-0", "x" * 2001)):
            assert _ONCE in _flat(_decide(client, cookie, record.id, decision, rationale))

    def test_a_record_let_go_of_its_account_after_it_was_read_is_not_decided(self, client: TestClient) -> None:
        """The account is deleted between the read and the write: the write itself checks whose the record is."""
        cookie = _sign_in(client, "dec_stale")
        record = _evaluated(client, cookie, "dec_stale")
        operator = Operator(record.user_id or 0, "dec_stale")

        async def stale(session: Any) -> decision_record.Decided:
            held = await session.get(DecisionRecord, record.id)
            table = DecisionRecord.__table__
            await session.execute(update(table).where(table.c.id == record.id).values(user_id=None))
            assert held.user_id == record.user_id   # the session still holds the record as it was read
            return await decision_record.decide(session, record.id, operator, "deferred", "")

        decided = _db(client, stale)
        assert (decided.row, decided.problem) == (None, _NOT_YOURS)
        assert _row(client, record.id).decided_at is None


class TestTheRecordNumberOnTheRoute:
    @pytest.mark.parametrize("record_id", ["0", "2147483648", "-1"])
    def test_a_number_outside_the_databases_integer_is_refused_before_it_is_read(
        self, client: TestClient, record_id: str,
    ) -> None:
        """PostgreSQL's INTEGER holds 2,147,483,647 at most; asyncpg raises on a larger one, SQLite does not."""
        cookie = _sign_in(client, "id_bounds")
        resp = client.post(
            f"/plan/decision/records/{record_id}/decide", data={"decision": "deferred"},
            cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
        )
        assert resp.status_code == 422

    def test_the_largest_is_read_and_refused_as_no_record(self, client: TestClient) -> None:
        cookie = _sign_in(client, "id_largest")
        assert _NOT_YOURS in _flat(_decide(client, cookie, 2_147_483_647, "deferred"))


def test_the_decision_form_names_its_own_target_indicator_and_disabled_element(client: TestClient) -> None:
    cookie = _sign_in(client, "form_htmx")
    text = _evaluate(client, cookie, _form()).text
    (row,) = _records(client, "form_htmx")
    form = re.search(rf'<form hx-post="/plan/decision/records/{row.id}/decide"[^>]*>', text)
    assert form is not None
    tag = form.group(0)
    assert f'hx-target="#decision-record-{row.id}"' in tag
    assert f'hx-indicator="#decision-record-indicator-{row.id}"' in tag
    assert 'hx-disabled-elt="find button[type=submit]"' in tag
    assert f'id="decision-record-{row.id}"' in text and f'id="decision-record-indicator-{row.id}"' in text


class TestResponseNamesAreEscapedWhereverARecordShowsThem:
    """The recommendation, all three picks and the decision's name are the operator's response names."""

    def _hostile(self, client: TestClient, username: str) -> tuple[str, DecisionRecord]:
        cookie = _sign_in(client, username)
        form = _form(**{**_TWO_RESPONSES, "fr_name": [_PAYLOAD, _PAYLOAD + " again"]})
        assert _evaluate(client, cookie, form).status_code == 200
        (row,) = _records(client, username)
        return cookie, row

    def test_the_decided_region_shows_them_inert(self, client: TestClient) -> None:
        cookie, row = self._hostile(client, "xss_decided")
        resp = _decide(client, cookie, row.id, "response-0")
        _assert_inert(resp)
        assert "Decision recorded" in resp.text

    def test_the_records_page_shows_them_inert(self, client: TestClient) -> None:
        cookie, row = self._hostile(client, "xss_listed")
        _decide(client, cookie, row.id, "response-1")
        resp = _page(client, cookie)
        _assert_inert(resp)
        text = _flat(resp)
        assert "Recommended: &lt;script&gt;" in text
        assert "Minimax picks &lt;script&gt;" in text
        assert "minimin picks &lt;script&gt;" in text
        assert "expected value picks &lt;script&gt;" in text
        assert ": &lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt; again (F2)." in text


class TestDecidingFromTheRecordsPage:
    """A record whose results are no longer on screen is decided where it is listed."""

    def test_an_undecided_record_of_ones_own_carries_the_decision_form(self, client: TestClient) -> None:
        cookie = _sign_in(client, "list_decide")
        record = _evaluated(client, cookie, "list_decide")
        text = _page(client, cookie).text
        assert f'hx-post="/plan/decision/records/{record.id}/decide"' in text
        assert f'<label for="decision-choice-{record.id}"' in text
        assert f'<label for="decision-rationale-{record.id}"' in text
        assert "No decision recorded" in text

    def test_a_decided_record_carries_none(self, client: TestClient) -> None:
        cookie = _sign_in(client, "list_decided")
        record = _evaluated(client, cookie, "list_decided")
        _decide(client, cookie, record.id, "deferred")
        assert "/decide" not in _page(client, cookie).text

    def test_an_admin_is_offered_their_own_and_not_another_operators(self, client: TestClient) -> None:
        theirs = _evaluated(client, _sign_in(client, "list_theirs"), "list_theirs", "Operator's own")
        admin = _admin_cookies(client)["spectre_session"]
        assert _evaluate(client, admin, _form(scenario_name="Admin's own")).status_code == 200
        (mine,) = [r for r in _records(client, "testadmin") if r.decided_at is None][-1:]
        text = _page(client, admin).text
        assert f'hx-post="/plan/decision/records/{mine.id}/decide"' in text
        assert f'hx-post="/plan/decision/records/{theirs.id}/decide"' not in text


class TestWhatTheRecordsPageSaysOfEachPick:
    def test_it_says_the_results_showed_one_rules_pick_and_the_others_were_worked_out_for_the_record(
        self, client: TestClient,
    ) -> None:
        cookie = _sign_in(client, "basis_rules")
        _evaluated(client, cookie, "basis_rules")
        text = _flat(_page(client, cookie))
        assert ("All three rules on the same matrix, worked out for this record; the results showed minimax's pick "
                "alone:") in text

    def test_expected_values_unearned_probability_is_said_beside_its_pick(
        self, client: TestClient, captured: list[ScenarioResult],
    ) -> None:
        cookie = _sign_in(client, "basis_ev")
        _evaluate(client, cookie, _form(adv_prob=["0.5"]))
        (result,) = captured
        guidance = dataclasses.replace(result, robust_strategy=SelectorStrategy.EXPECTED_VALUE).objective_guidance
        assert guidance is not None
        (row,) = _records(client, "basis_ev")
        assert row.expected_value_caveat == guidance
        assert guidance in _flat(_page(client, cookie))


def test_the_records_page_offers_sign_out(client: TestClient) -> None:
    cookie = _sign_in(client, "page_sign_out")
    text = _page(client, cookie).text
    form = re.search(r'<form method="post" action="/logout"[^>]*>(.*?)</form>', text, re.S)
    assert form is not None
    assert re.search(r'name="csrf_token" value="[^"]+"', form.group(1))
    assert "Sign Out" in form.group(1)
