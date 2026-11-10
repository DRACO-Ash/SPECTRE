"""The decision panel takes a manoeuvre hypothesis per adversary row (SPC-114).

Each adversary row has an optional hypothesis section: an archetype, a
delta-V, a RIC direction, a delta-V spread, a sample count and a burn time in
hours from the scenario epoch, the moment Evaluate is pressed. A row whose
archetype is None stays a lookup. A hypothesis starts from the bound red
track's state at the burn time, so it needs a bound red track. Every field is
labelled, and every out-of-range value is refused inline as audit F-164
refuses the existing fields: HTTP 200, an error-msg, the field named.

No test runs a propagator: a scenario that would sample has its job captured
before it starts.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from typing import Any

import pytest

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES
from spectre.domain.decision import AdversaryHypothesis, Scenario, longest_horizon_h, pre_manoeuvre_state
from spectre.domain.manoeuvre_calibration import from_km_s
from spectre.web.decision_job import DecisionJob
from spectre.web.routes import decision as decision_routes
from tests.integration.test_decision_binding_on_screen import _hold
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_form_labels import _unlabelled

_FIELDS = (
    "hyp_archetype", "hyp_dv", "hyp_dir_r", "hyp_dir_i", "hyp_dir_c", "hyp_sigma", "hyp_samples", "hyp_burn_h",
)


def _hyp(rows: int = 1, **overrides: list[str]) -> dict[str, list[str]]:
    """The eight hypothesis columns for *rows* rows, Evasive with every optional field blank, burn at 0."""
    base = {
        "hyp_archetype": ["evasive"] * rows, "hyp_dv": [""] * rows, "hyp_dir_r": [""] * rows,
        "hyp_dir_i": [""] * rows, "hyp_dir_c": [""] * rows, "hyp_sigma": [""] * rows,
        "hyp_samples": ["500"] * rows, "hyp_burn_h": ["0"] * rows,
    }
    base.update(overrides)
    return base


def _bound_form(rows: int = 1, horizon: str = "1", **hyp: list[str]) -> dict[str, Any]:
    adv = {
        "adv_id": [f"A{i + 1}" for i in range(rows)], "adv_name": [f"Row {i + 1}" for i in range(rows)],
        "adv_type": ["manoeuvre"] * rows, "adv_prob": ["0.5"] * rows, "adv_conf": ["0.7"] * rows,
    }
    return _form(horizon_hours=horizon, red_sat="RX", blue_sat="BY", **adv, **_hyp(rows, **hyp))


@pytest.fixture
def held(auth_cookie: str) -> Iterator[Any]:
    from tests.integration.conftest import session_state

    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), list(state.blue_assets), state.decision_job)
    yield state
    state.red_tracks, state.blue_assets, state.decision_job = saved


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[DecisionJob]:
    """Each job the route would start, held here and never run."""
    jobs: list[DecisionJob] = []

    def capture(state: Any, _key: Any, job: DecisionJob) -> None:
        state.decision_job = job
        jobs.append(job)

    monkeypatch.setattr(decision_routes, "start_job", capture)
    return jobs


def _panel(client: Any, cookie: str) -> str:
    resp = client.get("/plan/decision/panel", cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


def _section(html: str) -> str:
    start = html.index('<details class="adv-hypothesis"')
    return html[start:html.index("</details>", start)]


def _scenario_of(jobs: list[DecisionJob]) -> Scenario:
    assert len(jobs) == 1, "no job started"
    return jobs[0].scenario


# ── H1, H2, H14: the section, its labels and its hint ──

class TestThePanel:
    def test_each_adversary_row_has_a_labelled_hypothesis_section(self, client: Any, auth_cookie: str) -> None:
        """H1."""
        section = _section(_panel(client, auth_cookie))
        assert "Manoeuvre hypothesis (optional)" in section
        for name in _FIELDS:
            assert f'name="{name}"' in section, name
        assert '<option value="">None: this row stays a lookup</option>' in section
        for key, row in MANOEUVRE_ARCHETYPES.items():
            assert f'<option value="{key}">{row.name}, typical {from_km_s(row.typical_delta_v_km_s):g} m/s</option>' in section
        samples = re.search(r'<input[^>]*name="hyp_samples"[^>]*>', section)
        assert samples is not None
        for attr in ('value="500"', 'min="100"', 'max="2000"', 'step="1"'):
            assert attr in samples.group(0)
        assert _unlabelled(section) == []
        assert ' id="' not in section, "the section is repeated per row, so it carries no ids"

    def test_an_added_row_has_the_same_labelled_fields(self, client: Any, auth_cookie: str) -> None:
        """H2."""
        html = _panel(client, auth_cookie)
        builder = html[html.index("function addAdvRow()"):html.index("function addFrRow()")]
        assert '<details class="adv-hypothesis"' in builder
        assert builder.count(">Manoeuvre hypothesis (optional)<") == 1
        for name in _FIELDS:
            assert f'name="{name}"' in builder, name
        # The row's existing fields are unlabelled (named in the SPC-114 design, out of its scope); this block is not.
        assert _unlabelled(_section(builder)) == []
        assert _section(builder) == _section(html), "the builder emits the same block as the first row"

    def test_the_hint_names_the_longest_horizon_that_fits(self, client: Any, auth_cookie: str) -> None:
        """H14."""
        flat = " ".join(_panel(client, auth_cookie).split())
        assert f"a horizon up to about {longest_horizon_h(500)} h fits" in flat
        assert "Starts from the bound red track's state at the burn time." in flat

    def test_the_horizon_field_takes_the_tenths_the_hint_names(self, client: Any, auth_cookie: str) -> None:
        """A step of 1 h made the browser refuse the tenths the hint offers; the server takes any positive horizon.

        The hint and the cap's refusal name tenths (0.3 h at 2,000 samples over 5 rows), so the field steps in tenths
        from 0.1 h.
        """
        page = _panel(client, auth_cookie)
        field = re.search(r'<input[^>]*name="horizon_hours"[^>]*>', page)
        assert field is not None
        attrs = dict(re.findall(r'\b(min|max|step)="([^"]*)"', field.group(0)))
        assert attrs == {"min": "0.1", "max": "720", "step": "0.1"}
        hint = re.search(r"a horizon up to about ([0-9.]+) h fits", " ".join(page.split()))
        assert hint is not None
        tenths = (float(hint.group(1)) - float(attrs["min"])) / float(attrs["step"])
        assert tenths == pytest.approx(round(tenths)), "the hint's horizon is not one the field can submit"


# ── H3, H13: each field is range-checked inline ──

_SAMPLES = "Samples in row 1 must be a whole number between 100 and 2000; got {}."


@pytest.mark.parametrize(("overrides", "sentence"), [
    ({"hyp_samples": ["99"]}, _SAMPLES.format("99")),
    ({"hyp_samples": ["2001"]}, _SAMPLES.format("2001")),
    ({"hyp_samples": ["500.5"]}, _SAMPLES.format("500.5")),
    ({"hyp_samples": [""]}, _SAMPLES.format("a blank field")),
    ({"hyp_dv": ["-1"]}, "Delta-V (m/s) in row 1 must be between 0 and 1000; got -1."),
    ({"hyp_dv": ["1001"]}, "Delta-V (m/s) in row 1 must be between 0 and 1000; got 1001."),
    ({"hyp_dv": ["nan"]}, "Delta-V (m/s) in row 1 must be between 0 and 1000; got nan."),
    ({"hyp_dv": ["fast"]}, "Enter a number for delta-V (m/s) in row 1."),
    ({"hyp_sigma": ["101"]}, "Delta-V spread, 1 sigma (m/s) in row 1 must be between 0 and 100; got 101."),
    ({"hyp_sigma": ["-1"]}, "Delta-V spread, 1 sigma (m/s) in row 1 must be between 0 and 100; got -1."),
    ({"hyp_dir_r": ["2"]}, "Radial direction in row 1 must be between -1 and 1; got 2."),
    ({"hyp_dir_c": ["-5"]}, "Cross-track direction in row 1 must be between -1 and 1; got -5."),
    (
        {"hyp_dir_r": ["0"], "hyp_dir_i": ["0"], "hyp_dir_c": ["0"]},
        "The direction in row 1 is zero in all three parts; leave all three blank for the archetype's assumed "
        "in-track direction.",
    ),
    ({"hyp_burn_h": ["-73"]}, "Burn time (hours from the scenario epoch) in row 1 must be between -72 and 1; got -73."),
    ({"hyp_burn_h": ["2"]}, "Burn time (hours from the scenario epoch) in row 1 must be between -72 and 1; got 2."),
    ({"hyp_burn_h": [""]}, "Enter a number for burn time (hours from the scenario epoch) in row 1."),
    ({"hyp_archetype": ["warp"]}, "Choose a listed archetype for row 1."),
], ids=[
    "samples 99", "samples 2001", "samples 500.5", "samples blank", "dv -1", "dv 1001", "dv nan", "dv text",
    "sigma 101", "sigma -1", "radial 2", "cross-track -5", "direction zero", "burn -73", "burn past horizon",
    "burn blank", "archetype warp",
])
def test_an_out_of_range_hypothesis_field_is_refused_inline(
    client: Any, auth_cookie: str, held: Any, overrides: dict[str, list[str]], sentence: str,
) -> None:
    """H3."""
    _hold(held)
    resp = _evaluate(client, auth_cookie, _bound_form(**overrides))
    assert resp.status_code == 200, "htmx swaps only a 2xx, so the refusal must be one"
    assert resp.text == f'<p class="error-msg">{html.escape(sentence)}</p>'


def test_a_hostile_sample_count_is_escaped(client: Any, auth_cookie: str, held: Any) -> None:
    """H13."""
    _hold(held)
    resp = _evaluate(client, auth_cookie, _bound_form(hyp_samples=["<script>alert(1)</script>"]))
    assert resp.status_code == 200
    assert "error-msg" in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text
    assert "<script>" not in resp.text


def test_misaligned_hypothesis_fields_ask_for_a_reload(client: Any, auth_cookie: str, held: Any) -> None:
    """H12."""
    _hold(held)
    resp = _evaluate(client, auth_cookie, _bound_form(rows=2, hyp_dv=[""]))
    assert resp.text == '<p class="error-msg">The hypothesis fields do not match the adversary rows; reload the panel.</p>'


def test_a_hypothesis_needs_a_bound_red_track(client: Any, auth_cookie: str, held: Any) -> None:
    """H5."""
    _hold(held)
    form = {**_bound_form(), "red_sat": ""}
    resp = _evaluate(client, auth_cookie, form)
    assert resp.text == (
        '<p class="error-msg">A manoeuvre hypothesis in row 1 starts from the bound red track: bind a red track, '
        "or set its archetype to None.</p>"
    )


def test_a_red_track_that_cannot_reach_the_burn_is_refused_inline(
    client: Any, auth_cookie: str, held: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H11."""
    _hold(held)
    monkeypatch.setattr(decision_routes, "pre_manoeuvre_state", lambda _tle, _at: None)
    resp = _evaluate(client, auth_cookie, _bound_form())
    assert resp.text == (
        '<p class="error-msg">The red element set cannot be propagated to the burn time in row 1.</p>'
    )


# ── H4, H6, H7, H15: what the route builds ──

class TestTheHypothesisBuilt:
    def test_a_row_set_to_none_stays_a_lookup(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],
    ) -> None:
        """H4."""
        _hold(held)
        resp = _evaluate(client, auth_cookie, _bound_form(rows=2, hyp_archetype=["evasive", ""],
                                                          hyp_samples=["500", "bad"]))
        assert resp.status_code == 200
        actions = _scenario_of(captured).adversary_actions
        assert actions[0].hypothesis is not None
        assert actions[1].hypothesis is None

    def test_an_archetype_at_burn_zero_starts_from_the_red_track_at_the_scenario_epoch(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],
    ) -> None:
        """H6."""
        _hold(held)
        resp = _evaluate(client, auth_cookie, _bound_form())
        assert 'hx-get="/plan/decision/job?job_id=' in resp.text
        scenario = _scenario_of(captured)
        at = pre_manoeuvre_state(held.red_tracks[0].tle, scenario.epoch_utc)
        assert at is not None
        assert scenario.adversary_actions[0].hypothesis == AdversaryHypothesis.from_archetype(
            "evasive", at, n_samples=500,
        )

    def test_entered_values_are_carried(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],
    ) -> None:
        """H7."""
        _hold(held)
        _evaluate(client, auth_cookie, _bound_form(
            hyp_archetype=["orbit_raise"], hyp_dv=["12.5"], hyp_dir_r=["1"], hyp_dir_i=["0"], hyp_dir_c=["0"],
            hyp_sigma=["0.4"], hyp_samples=["200"],
        ))
        scenario = _scenario_of(captured)
        at = pre_manoeuvre_state(held.red_tracks[0].tle, scenario.epoch_utc)
        assert at is not None
        expected = AdversaryHypothesis.from_entered(
            12.5, (1.0, 0.0, 0.0), at, archetype="orbit_raise", n_samples=200,
        ).with_spread(0.4)
        assert scenario.adversary_actions[0].hypothesis == expected

    def test_a_blank_field_keeps_its_row(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],
    ) -> None:
        """H15."""
        _hold(held)
        _evaluate(client, auth_cookie, _bound_form(rows=2, hyp_dv=["", "5"]))
        first, second = (a.hypothesis for a in _scenario_of(captured).adversary_actions)
        assert first is not None and second is not None
        assert first.delta_v_m_s == pytest.approx(2.0)
        assert second.delta_v_m_s == pytest.approx(5.0)


# ── H9, H10: the burn on screen, and a burn before the red element set ──

def test_a_burn_before_the_red_epoch_is_refused_and_its_burn_line_shown(
    client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],
) -> None:
    """H9 and H10: a burn 2 h ago, the red element set 1 h old; refused before anything runs, so inline."""
    _hold(held, red_hours=1.0)
    resp = _evaluate(client, auth_cookie, _bound_form(hyp_burn_h=["-2"]))
    assert captured == []
    text = " ".join(re.sub(r"<[^>]+>", "", resp.text).split()).replace("&#39;", "'").replace("&#x27;", "'")
    assert re.search(
        r"Burn at \d{4}-\d\d-\d\d \d\d:\d\d UTC, -2\.0 h from the scenario epoch, from the bound red track's "
        r"state then\.", text,
    )
    assert text.count("so it may already include the burn, and sampling would apply it twice.") == 1
    assert re.search(r"Not sampled: the red element set dates from .* UTC, after the burn at .* UTC", text)
