"""The decision panel takes our burn per friendly response (SPC-121).

Each friendly row has an optional section, "Our burn (manoeuvre responses only)": a target separation in km, a
delta-V budget in m/s and an axis. A manoeuvre response given a target has its burn sized when the scenario is bound
on both sides; a blank target leaves its delta-V a lookup; any other response's fields are not read. Every row posts
all three fields, blanks included, so the columns stay aligned with the rows. Every field is labelled, and an
out-of-range value is refused inline, naming the field and the row.

No test runs a propagator: a scenario that would size a burn has its job captured before it starts.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from spectre.astro.response_burn import BurnAxis
from spectre.domain.decision import SamplingProgress, Scenario
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.web.decision_job import DecisionJob, JobState, job_view
from tests.integration.test_decision_binding_on_screen import _hold
from tests.integration.test_decision_hypothesis_panel import _panel, _scenario_of, captured, held  # noqa: F401
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_job import _job
from tests.integration.test_form_labels import _unlabelled

_FIELDS = ("fr_target", "fr_budget", "fr_axis")
_RELOAD = "The response fields do not match the friendly rows; reload the panel."


def _section(html: str) -> str:
    start = html.index('<details class="fr-burn"')
    return html[start:html.index("</details>", start)]


def _responses(types: list[str], **columns: list[str]) -> dict[str, Any]:
    rows = len(types)
    fields: dict[str, Any] = {
        "fr_id": [f"F{i + 1}" for i in range(rows)], "fr_name": [f"Response {i + 1}" for i in range(rows)],
        "fr_type": types, "fr_cost": ["0.3"] * rows, "fr_rev": ["0.8"] * rows, "fr_time": ["0"] * rows,
        "fr_target": [""] * rows, "fr_budget": [""] * rows, "fr_axis": ["cheapest"] * rows,
    }
    fields.update(columns)
    return fields


def _bound(**fields: Any) -> dict[str, Any]:
    return _form(
        horizon_hours="6", red_sat="RX", blue_sat="BY", adv_type=["no_action"], **fields,
    )


class TestThePanel:
    def test_each_friendly_row_has_labelled_burn_fields(self, client: Any, auth_cookie: str) -> None:
        """46: the template row."""
        html = _panel(client, auth_cookie)
        row = html[html.index('<div class="fr-row"'):html.index("+ Add Friendly Response")]
        section = _section(row)
        assert ">Our burn (manoeuvre responses only)<" in section
        for name in _FIELDS:
            assert f'name="{name}"' in section, name
        for label in ("Target separation (km)", "Delta-V budget (m/s)", "Axis"):
            assert label in section, label
        for axis in BurnAxis:
            assert f'value="{axis.value}"' in section, axis
        assert _unlabelled(section) == []
        assert ' id="' not in section, "the section is repeated per row, so it carries no ids"

    def test_an_added_row_has_the_same_labelled_fields(self, client: Any, auth_cookie: str) -> None:
        """46: the row builder."""
        html = _panel(client, auth_cookie)
        builder = html[html.index("function addFrRow()"):html.index("function removeRow(")]
        section = _section(builder)
        for name in _FIELDS:
            assert f'name="{name}"' in section, name
        assert _unlabelled(section) == []

    def test_the_hint_counts_burns_against_the_cap(self, client: Any, auth_cookie: str) -> None:
        text = " ".join(_panel(client, auth_cookie).split())
        assert "at 500 samples a horizon up to about 9.4 h fits with no burn to size, 7.0 h with one and 3.4 h with five" in text


class TestTheForm:
    def test_a_negative_target_is_refused_naming_field_and_row(self, client: Any, auth_cookie: str) -> None:
        """47."""
        form = _form(**_responses(["manoeuvre", "manoeuvre"], fr_target=["", "-5"]))
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200
        assert "Target separation (km) in row 2 must be above 0 and at most 100000; got -5." in resp.text

    @pytest.mark.parametrize(
        ("columns", "message"),
        [
            ({"fr_budget": ["2000"]}, "Delta-V budget (m/s) in row 1 must be above 0 and at most 1000; got 2000."),
            ({"fr_axis": ["sideways"]}, "Choose a listed axis for row 1."),
            ({"fr_target": ["nan"]}, "Target separation (km) in row 1 must be above 0 and at most 100000; got nan."),
        ],
    )
    def test_each_field_is_checked(self, client: Any, auth_cookie: str, columns: dict[str, list[str]], message: str) -> None:
        form = _form(**_responses(["manoeuvre"], fr_target=["20"]))
        form.update(columns)
        resp = _evaluate(client, auth_cookie, form)
        assert message in resp.text

    def test_mismatched_response_columns_are_refused(self, client: Any, auth_cookie: str) -> None:
        """48."""
        form = _form(**_responses(["manoeuvre", "manoeuvre"], fr_budget=["50"]))
        resp = _evaluate(client, auth_cookie, form)
        assert _RELOAD in resp.text

    def test_a_form_without_the_section_still_evaluates(self, client: Any, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _form())
        assert resp.status_code == 200 and "error-msg" not in resp.text

    def test_an_unbound_target_says_on_the_page_it_was_not_used(self, client: Any, auth_cookie: str) -> None:
        """Unbound, nothing can be sized: the cell says so rather than showing the lookup alone."""
        resp = _evaluate(client, auth_cookie, _form(**_responses(["manoeuvre"], fr_target=["20"])))
        assert resp.status_code == 200, resp.text
        assert "No burn is shown for the 20 km target: it is sized against this" in resp.text

    def test_the_route_builds_our_burn_for_a_manoeuvre_row_only(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
    ) -> None:
        _hold(held, red_leo=True)
        form = _bound(**_responses(
            ["manoeuvre", "sensor_retask", "manoeuvre"], fr_target=["20", "30", ""], fr_budget=["", "", "10"],
            fr_axis=["radial", "cheapest", "cheapest"],
        ))
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200, resp.text
        scenario: Scenario = _scenario_of(captured)
        assert [r.burn for r in scenario.friendly_responses] == [
            ResponseBurnSpec(20.0, 0.05, BurnAxis.RADIAL), None, None,
        ]


class TestTheJobPage:
    def test_the_job_message_names_the_sizing_stage(self) -> None:
        """43."""
        job = _job()
        job.state = JobState.RUNNING
        job.progress = SamplingProgress(1, 2, 3, 16, 2.4, stage="sizing", label="Avoid")
        view: dict[str, Any] = job_view_for(job)
        epoch = job.scenario.epoch_utc.strftime("%H:%M")
        assert view["message"] == (
            f"Sizing our burn for Avoid: trial 3 of at most 16, 2 s of the 120 s budget used. Scenario epoch {epoch} UTC."
        )

    def test_the_progress_bar_is_labelled_for_sizing(self, client: Any, auth_cookie: str) -> None:
        from tests.integration.conftest import session_state
        from tests.integration.test_decision_job import _poll

        job = _job()
        job.state = JobState.RUNNING
        job.progress = SamplingProgress(1, 2, 3, 16, 2.4, stage="sizing", label="Avoid")
        session_state(auth_cookie).decision_job = job  # type: ignore[attr-defined]
        text = _poll(client, auth_cookie, job.job_id).text
        assert re.search(r"Trials flown sizing our burn\s*<progress[^>]*max=\"16\"[^>]*value=\"3\"", text)

    def test_a_hostile_response_name_is_escaped_on_the_job_page(self, client: Any, auth_cookie: str) -> None:
        """The response's name reaches the page through the sizing sentence, so autoescape must hold it."""
        from tests.integration.conftest import session_state
        from tests.integration.test_decision_job import _poll

        job = _job()
        job.state = JobState.RUNNING
        job.progress = SamplingProgress(1, 1, 1, 16, 0.5, stage="sizing", label="<script>alert(1)</script>")
        session_state(auth_cookie).decision_job = job  # type: ignore[attr-defined]
        text = _poll(client, auth_cookie, job.job_id).text
        assert "<script>alert(1)</script>" not in text
        assert "Sizing our burn for &lt;script&gt;alert(1)&lt;/script&gt;: trial 1 of at most 16" in text


def job_view_for(job: DecisionJob) -> dict[str, Any]:
    from types import SimpleNamespace

    return job_view(SimpleNamespace(decision_job=job), job.job_id)  # type: ignore[arg-type]
