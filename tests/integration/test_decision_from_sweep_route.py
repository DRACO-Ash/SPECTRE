"""Opening a decision scenario from a sweep entry, and evaluating it (SPC-150).

GET /plan/decision/from-sweep returns the Decision Engine panel filled from
the held sweep's entry: the red track, the blue asset when the target is
held, the departure burn as a hypothesis at its own UTC time, and the latest
detected burn, which evaluate builds from the element set before it in the
held history (hypothesis_from_tle_record, SPC-001). P and Conf keep the
engine's defaults and nothing is evaluated on the operator's behalf.

A burn the sweep fixed in time stays at that time however long the operator
takes to press Evaluate: a burn counted in hours from a panel opened minutes
earlier would move along the orbit by those minutes. Each route clock here
is fixed and UDL is not connected, so no test reads the wall clock or
reaches the network, and no sampled job is run.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.domain.decision import AdversaryHypothesis, HypothesisSource, Scenario
from spectre.domain.models import BlueAsset, RedTrack, ThreatAssessment, ThreatSweepEntry, ThreatTarget
from spectre.web.decision_job import DecisionJob
from spectre.web.decision_prior import UNEDITED_PROBABILITY
from spectre.web.routes import decision as decision_routes
from spectre.web.routes import threat as threat_routes
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_form_labels import _unlabelled
from tests.integration.test_sweep_burn_differential import (  # noqa: F401 - leo is a fixture
    _BUDGET,
    _ROUTINE,
    _arrange,
    _events_history,
    _spy,
    _sweep,
    leo,
)
from tests.unit.test_decision_from_sweep import _burn, _history
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_SWEPT = _NOW - timedelta(minutes=10)
_DEPART = _NOW + timedelta(hours=1)


def _entry(target: str = "ALPHA") -> ThreatSweepEntry:
    return ThreatSweepEntry(
        target=ThreatTarget(target, "40001", "hrr", 1), burn_epoch=_DEPART, burn_location="apogee",
        delta_v_m_s=70.0, tof_hours=5.0, dv_prograde=60.0, dv_normal=40.0, dv_radial=0.0, method="lambert",
        regime="GEO", departure_m_s=(30.0, 40.0, 0.0),
    )


@pytest.fixture
def held(auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A sweep of RX held, RX and Alpha held, the route's clock at _NOW; all restored afterwards."""
    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), list(state.blue_assets), state.last_threat_assessment,
             dict(state.elset_histories), state.threat_picture, state.decision_job, len(state.log_entries))
    red_tle = _tle(_NOW - timedelta(hours=5), satno=50322)
    state.red_tracks = [RedTrack("RX", red_tle, data_mode="REAL")]
    state.blue_assets = [BlueAsset("Alpha", _tle(_NOW - timedelta(hours=5), satno=40001), data_mode="REAL")]
    state.last_threat_assessment = ThreatAssessment(
        red_name="RX", sweep_epoch=_SWEPT, entries=[_entry()], target_count=1, red_tle=red_tle,
    )
    state.elset_histories = {}
    state.threat_picture = None
    monkeypatch.setattr(decision_routes, "_utc_now", lambda: _NOW)
    yield state
    (state.red_tracks, state.blue_assets, state.last_threat_assessment, state.elset_histories,
     state.threat_picture, state.decision_job, _logged) = saved


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[DecisionJob]:
    """Each job the route would start, held here and never run."""
    jobs: list[DecisionJob] = []

    def capture(state: Any, _key: Any, job: DecisionJob) -> None:
        state.decision_job = job
        jobs.append(job)

    monkeypatch.setattr(decision_routes, "start_job", capture)
    return jobs


def _open(client: Any, cookie: str, entry: str = "0", sweep: str | None = None) -> str:
    resp = client.get("/plan/decision/from-sweep", params={"entry": entry, "sweep": sweep or _SWEPT.isoformat()},
                      cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


def _text(page: str) -> str:
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", page).split()))


def _field(page: str, name: str) -> list[str]:
    """Each rendered field called *name*, leaving out the row builder's script, which emits an empty row."""
    rendered = page.split("<script>", 1)[0]
    return [m.group(0) for m in re.finditer(rf'<(?:input|select)[^>]*name="{name}"[^>]*>', rendered)]


class TestTheFilledPanel:
    def test_it_fills_the_bound_objects_the_departure_burn_and_says_what_and_from_which_sweep(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        page = _open(client, auth_cookie)
        text = _text(page)
        assert "Opened from the sweep of RX at 08:50 UTC on 4 Nov, 10 min ago" in text
        assert "Red track: RX, the object the sweep flew." in text
        assert "Blue asset: Alpha, the target ALPHA, held as a blue asset (SATNO 40001)." in text
        assert re.search(r'<option value="RX" selected>', page)
        assert re.search(r'<option value="Alpha" selected>', page)
        assert '<option value="intercept_approach" selected>' in page
        assert 'value="50"' in _field(page, "hyp_dv")[0]
        assert f'value="{_DEPART.isoformat()}"' in _field(page, "hyp_burn_at")[0]
        assert 'type="hidden"' in _field(page, "hyp_burn_at")[0]
        assert 'value="7"' in _field(page, "horizon_hours")[0]
        assert "var _advCount = 1;" in page

    def test_probability_and_confidence_keep_the_engines_defaults(self, client: Any, auth_cookie: str,
                                                                  held: Any) -> None:
        page = _open(client, auth_cookie)
        assert ['value="0.5"' in f for f in _field(page, "adv_prob")] == [True]
        assert ['value="0.7"' in f for f in _field(page, "adv_conf")] == [True]
        assert "Not pre-filled: P, Conf and Gap keep the engine's defaults" in _text(page)

    def test_a_p_left_as_the_sweep_opened_it_is_untouched_and_an_edited_one_is_not(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """SPC-183: a row opened from the sweep starts at the text the edit record compares from, so its P reads as
        untouched until the operator edits it, and as their own once the record says so."""
        page = _open(client, auth_cookie)
        assert [f'value="{UNEDITED_PROBABILITY}"' in f for f in _field(page, "adv_prob")] == [True]
        guidance = "Expected value rests on a probability"
        left = _evaluate(client, auth_cookie, _form(adv_prob=[UNEDITED_PROBABILITY], strategy="expected_value"))
        edited = _evaluate(client, auth_cookie, _form(adv_prob=[UNEDITED_PROBABILITY], adv_p_edited=["A1"],
                                                      strategy="expected_value"))
        assert guidance in _text(left.text)
        assert guidance not in _text(edited.text)

    def test_opening_evaluates_nothing(self, client: Any, auth_cookie: str, held: Any,
                                       captured: list[DecisionJob]) -> None:
        before = len(held.log_entries)
        page = _open(client, auth_cookie)
        assert captured == [] and held.decision_job is None
        assert len(held.log_entries) == before
        assert '<div id="decision-results"></div>' in page

    def test_the_detected_burn_is_a_second_row_with_its_fields_labelled(self, client: Any, auth_cookie: str,
                                                                        held: Any) -> None:
        held.elset_histories = {50322: _history(_burn(_NOW - timedelta(hours=6)))}
        page = _open(client, auth_cookie)
        assert [f'value="{v}"' in f for f, v in zip(_field(page, "hyp_detected"), ("", "1"), strict=True)] == [
            True, True]
        assert "var _advCount = 2;" in page
        rows = page[:page.index("+ Add Adversary Action")]
        blocks = re.findall(r'<details class="adv-hypothesis".*?</details>', rows, re.S)
        assert [_unlabelled(block) for block in blocks] == [[], []]

    def test_a_refused_open_shows_why_and_an_unfilled_panel(self, client: Any, auth_cookie: str, held: Any) -> None:
        page = _open(client, auth_cookie, sweep="2026-11-04T08:00:00+00:00")
        assert ("The sweep this was opened from is no longer the latest held. Open the scenario from the latest "
                "sweep.") in _text(page)
        assert '<option value="intercept_approach" selected>' not in page
        assert 'value="72"' in _field(page, "horizon_hours")[0]

    @pytest.mark.parametrize("entry", ["\u00b2", "9" * 5000], ids=["superscript", "5000-digits"])
    def test_an_entry_int_cannot_read_is_refused_not_a_server_error(self, client: Any, auth_cookie: str, held: Any,
                                                                    entry: str) -> None:
        page = _open(client, auth_cookie, entry=entry)
        assert "That entry is not in the latest sweep. Open the scenario from the latest sweep." in _text(page)

    def test_a_target_name_carrying_markup_is_escaped(self, client: Any, auth_cookie: str, held: Any) -> None:
        held.last_threat_assessment.entries = [_entry("<script>alert(1)</script>")]
        page = _open(client, auth_cookie)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def _sweep_form(**hyp: list[str]) -> dict[str, Any]:
    columns = {
        "hyp_archetype": ["intercept_approach"], "hyp_dv": ["50"], "hyp_dir_r": ["0"], "hyp_dir_i": ["0.6"],
        "hyp_dir_c": ["0.8"], "hyp_sigma": [""], "hyp_samples": ["500"], "hyp_burn_h": [""],
        "hyp_burn_at": [_DEPART.isoformat()], "hyp_detected": [""],
    }
    columns.update(hyp)
    return _form(horizon_hours="7", red_sat="RX", blue_sat="Alpha", **columns)


def _scenario(jobs: list[DecisionJob]) -> Scenario:
    assert len(jobs) == 1, "no job started"
    return jobs[0].scenario


def _refusal(client: Any, cookie: str, form: dict[str, Any]) -> str:
    resp = _evaluate(client, cookie, form)
    assert resp.status_code == 200
    assert "error-msg" in resp.text
    return _text(resp.text)


class TestEvaluatingAFilledScenario:
    def test_a_burn_fixed_from_the_sweep_stays_at_its_utc_time(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The operator presses Evaluate three minutes after the panel opened.
        monkeypatch.setattr(decision_routes, "_utc_now", lambda: _NOW + timedelta(minutes=3))
        resp = _evaluate(client, auth_cookie, _sweep_form())
        assert "error-msg" not in resp.text
        hypothesis = _scenario(captured).adversary_actions[0].hypothesis
        assert hypothesis is not None
        assert hypothesis.hypothesis.epoch_utc == _DEPART
        assert hypothesis.source is HypothesisSource.ENTERED
        assert hypothesis.delta_v_m_s == pytest.approx(50.0)

    def test_a_detected_row_starts_from_the_element_set_before_the_burn(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # What the route builds is the question, not whether the engine samples it: the engine refuses a burn
        # the bound red set may already include, so the scenario is taken as a job here and never run.
        monkeypatch.setattr(decision_routes, "needs_a_run", lambda _scenario: True)
        at = _NOW - timedelta(hours=6)
        burn = _burn(at)
        held.elset_histories = {50322: _history(burn)}
        form = _sweep_form(
            hyp_archetype=["repositioning"], hyp_dv=[""], hyp_dir_r=[""], hyp_dir_i=[""], hyp_dir_c=[""],
            hyp_samples=["150"], hyp_burn_at=[at.isoformat()], hyp_detected=["1"],
        )
        resp = _evaluate(client, auth_cookie, form)
        assert "error-msg" not in resp.text
        carried = _scenario(captured).adversary_actions[0].hypothesis
        assert carried is not None
        expected = AdversaryHypothesis.from_detection(burn.tle_before, burn, archetype="repositioning", n_samples=150)
        assert carried.source is HypothesisSource.DETECTED
        assert carried.hypothesis.epoch_utc == at
        assert list(carried.hypothesis.pre_manoeuvre_state_eci_km) == list(
            expected.hypothesis.pre_manoeuvre_state_eci_km)

    def test_a_detected_row_takes_the_operators_samples_and_spread(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(decision_routes, "needs_a_run", lambda _scenario: True)
        at = _NOW - timedelta(hours=6)
        held.elset_histories = {50322: _history(_burn(at))}
        form = _sweep_form(
            hyp_archetype=["repositioning"], hyp_dv=[""], hyp_dir_r=[""], hyp_dir_i=[""], hyp_dir_c=[""],
            hyp_sigma=["3"], hyp_samples=["150"], hyp_burn_at=[at.isoformat()], hyp_detected=["1"],
        )
        resp = _evaluate(client, auth_cookie, form)
        assert "error-msg" not in resp.text
        carried = _scenario(captured).adversary_actions[0].hypothesis
        assert carried is not None
        assert carried.hypothesis.n_samples == 150
        assert carried.spread_entered is True
        assert carried.hypothesis.delta_v_magnitude_1sigma_km_s == pytest.approx(0.003)

    def test_a_detected_row_whose_element_set_cannot_be_propagated_is_refused(
        self, client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        at = _NOW - timedelta(hours=6)
        held.elset_histories = {50322: _history(_burn(at))}

        def unpropagated(*_args: Any, **_kw: Any) -> AdversaryHypothesis:
            raise RuntimeError("SGP4 error 6 for SECRET-DETAIL")

        monkeypatch.setattr(AdversaryHypothesis, "from_detection", unpropagated)
        form = _sweep_form(hyp_archetype=["repositioning"], hyp_burn_at=[at.isoformat()], hyp_detected=["1"])
        refusal = _refusal(client, auth_cookie, form)
        assert "The red element set cannot be propagated to the burn time in row 1." in refusal
        assert "SECRET-DETAIL" not in refusal

    def test_a_detected_burn_no_longer_held_is_refused(self, client: Any, auth_cookie: str, held: Any) -> None:
        at = _NOW - timedelta(hours=6)
        form = _sweep_form(hyp_archetype=["repositioning"], hyp_burn_at=[at.isoformat()], hyp_detected=["1"])
        assert ("The detected burn in row 1, at 03:00 UTC on 4 Nov, is no longer in the held history for RX. Open "
                "the scenario from the sweep again.") in _refusal(client, auth_cookie, form)

    @pytest.mark.parametrize(("columns", "message"), [
        ({"hyp_burn_at": ["yesterday"]}, "The burn time in row 1 cannot be read; reload the panel."),
        ({"hyp_burn_at": ["2026-11-04T10:00:00"]}, "The burn time in row 1 cannot be read; reload the panel."),
        ({"hyp_burn_at": [(_NOW - timedelta(hours=73)).isoformat()]},
         "The burn time fixed in row 1, 08:00 UTC on 1 Nov, is more than 72 h before the scenario epoch. Open the "
         "scenario from the sweep again."),
        ({"hyp_burn_at": [(_NOW + timedelta(hours=8)).isoformat()]},
         "The burn time fixed in row 1, 17:00 UTC on 4 Nov, is after the horizon. Lengthen the horizon to cover it."),
        ({"hyp_burn_at": [""], "hyp_detected": ["1"]},
         "A detected burn in row 1 needs its burn time; reload the panel."),
        ({"hyp_burn_at": ["", ""]}, "The hypothesis fields do not match the adversary rows; reload the panel."),
    ])
    def test_a_fixed_burn_time_that_cannot_be_used_is_refused(
        self, client: Any, auth_cookie: str, held: Any, columns: dict[str, list[str]], message: str,
    ) -> None:
        assert message in _refusal(client, auth_cookie, _sweep_form(**columns))

    @pytest.mark.usefixtures("held")
    @pytest.mark.parametrize("burn_at", [_NOW - timedelta(hours=72), _NOW + timedelta(hours=7)])
    def test_a_fixed_burn_time_on_either_limit_is_accepted(
        self, client: Any, auth_cookie: str, captured: list[DecisionJob], burn_at: datetime,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Inclusive at 72 h before the scenario epoch and at the 7 h horizon, as _Inputs.number takes a typed hour.
        # The route's scenario is the question: a burn before the held red set is not sampled, so take it as a job.
        monkeypatch.setattr(decision_routes, "needs_a_run", lambda _scenario: True)
        page = _text(_evaluate(client, auth_cookie, _sweep_form(hyp_burn_at=[burn_at.isoformat()])).text)
        assert "more than 72 h before the scenario epoch" not in page
        assert "is after the horizon" not in page
        hypothesis = _scenario(captured).adversary_actions[0].hypothesis
        assert hypothesis is not None
        assert hypothesis.hypothesis.epoch_utc == burn_at

    def test_a_form_without_the_two_new_columns_still_evaluates(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],
    ) -> None:
        form = _sweep_form(hyp_burn_h=["1"])
        del form["hyp_burn_at"], form["hyp_detected"]
        resp = _evaluate(client, auth_cookie, form)
        assert "error-msg" not in resp.text
        hypothesis = _scenario(captured).adversary_actions[0].hypothesis
        assert hypothesis is not None
        assert hypothesis.hypothesis.epoch_utc == _NOW + timedelta(hours=1)


class TestTheSweepPageNamesTheWorstEntry:
    """The sweep route hands the card the worst entry's index beside the worst case, never inside it (SPC-175)."""

    def test_the_worst_case_control_opens_the_entry_the_card_describes(
        self, client: Any, auth_cookie: str, leo: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        monkeypatch.setattr(threat_routes, "start_watch", lambda *_a, **_k: None)
        records = _events_history(_ROUTINE)
        _arrange(leo, monkeypatch, records)
        _spy(monkeypatch, {records[-1].tle: 3.0})
        page = _sweep(client, auth_cookie)
        controls = re.findall(r'<button[^>]*aria-label="Open a decision scenario from the worst case[^>]*>', page)
        assert len(controls) == 1
        assessment = leo.last_threat_assessment
        assert f'"entry": {threat_routes.worst_entry_index(assessment.entries, _BUDGET)}' in controls[0]
        assert assessment.sweep_epoch.isoformat() in controls[0]

    def test_the_control_ranks_at_the_budget_swept_not_the_default(
        self, client: Any, auth_cookie: str, leo: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    ) -> None:
        # At 100 m/s the 300 m/s intercept cannot be flown, so the slow cheap one leaves the least warning; at the
        # 500 m/s default the fast one would. The card and its control have to rank at the budget swept.
        monkeypatch.setattr(threat_routes, "start_watch", lambda *_a, **_k: None)
        _arrange(leo, monkeypatch, _events_history(_ROUTINE))

        def run(
            _state: Any, _targets: Any, _manual: Any, _red_tle: str, _regime: str,
            epochs: list[tuple[str, datetime]], _budget: float,
        ) -> tuple[list[ThreatSweepEntry], list[str], list[Any]]:
            return [
                ThreatSweepEntry(target=ThreatTarget(name, "", "manual", 1), burn_epoch=epochs[0][1],
                                 burn_location="now", delta_v_m_s=dv, tof_hours=tof, dv_prograde=dv,
                                 dv_normal=0.0, dv_radial=0.0, method="hohmann", regime="LEO")
                for name, dv, tof in (("FASTDEAR", 300.0, 1.0), ("SLOWCHEAP", 50.0, 5.0))
            ], [], []

        monkeypatch.setattr(threat_routes, "_run_target_sweep", run)
        resp = client.post("/plan/threat/sweep", data={"red_sat": "RED-LEO", "tgt_group": "none", "max_dv_m_s": 100.0},
                           cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie))
        controls = re.findall(r'<button[^>]*aria-label="Open a decision scenario from the worst case[^>]*>', resp.text)
        assert len(controls) == 1
        opened = re.search(r'"entry": (\d+)', html.unescape(controls[0]))
        assert opened is not None
        assert leo.last_threat_assessment.entries[int(opened.group(1))].target.target_name == "SLOWCHEAP"
        assert "SLOWCHEAP" in controls[0]
