"""The operator sets the keep-out distance on the decision panel (SPC-191, evaluation F-10).

A miss at or inside the keep-out distance scores the full closest-approach penalty, and each tenfold beyond it
scores less, down to none at 50,000 km. The panel offers it as a labelled number field, "Keep-out distance (km)",
at the default of 10 km, which is Claude's choice and unsourced, and says so. An out-of-range or non-finite value is
refused with a sentence, as every other panel number is (audit F-164), and so is a cleared field or a form without
it, as a cleared horizon is; a scenario opened from the sweep takes the default. The result states the distance it
scored with, as entered, and its basis.
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest

from spectre.domain import decision
from tests.integration.test_decision_from_sweep_route import _open, held  # noqa: F401 - held is a fixture
from tests.integration.test_decision_input_validation import _evaluate, _form

_SCORE = re.compile(r'data-figure="composite_score"[^>]*>\s*([0-9.]+)\s*<', re.S)
_FIELD = re.compile(r'<label[^>]*>\s*Keep-out distance \(km\)\s*<input[^>]*name="keep_out_km"[^>]*>', re.S)


def _panel(client: Any, cookie: str) -> str:
    resp = client.get("/plan/decision/panel", cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


def _flat(page: str) -> str:
    return " ".join(html.unescape(page).split())


def _scored(client: Any, cookie: str, **overrides: Any) -> tuple[list[str], str]:
    resp = _evaluate(client, cookie, _form(**overrides))
    assert resp.status_code == 200
    assert "error-msg" not in resp.text, resp.text
    return _SCORE.findall(resp.text), _flat(resp.text)


class TestThePanel:
    def test_the_field_is_labelled_at_the_default_within_its_range(self, client: Any, auth_cookie: str) -> None:
        found = _FIELD.search(_panel(client, auth_cookie))
        assert found is not None
        for attr in ('type="number"', 'value="10"', 'min="0.1"', 'max="10000"'):
            assert attr in found.group(0), attr

    def test_the_panel_says_the_default_is_claudes_choice_and_unsourced(self, client: Any, auth_cookie: str) -> None:
        assert " ".join(decision.KEEP_OUT_NOTE.split()) in _flat(_panel(client, auth_cookie))
        assert "10 km, is Claude's choice and unsourced" in decision.KEEP_OUT_NOTE

    def test_a_scenario_opened_from_the_sweep_takes_the_default(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811 - the fixture imported above
    ) -> None:
        found = _FIELD.search(_open(client, auth_cookie))
        assert found is not None
        assert 'value="10"' in found.group(0)


class TestTheEvaluation:
    def test_the_distance_is_carried_to_the_score(self, client: Any, auth_cookie: str) -> None:
        """The form's lookup cell: a manoeuvre against our manoeuvre at cost 0.2, so closest approach is
        200 x (1 + 5 x 0.2) = 400 km and our delta-V 0.2 x 50 = 10 m/s; custody held; 4 h of 72; reversibility 0.8.

        K 10 km: 0.25 x ln 125 / ln 5,000 + 0.20 x ln 11 / ln 1,001 + 0.10 x 4 / 72 + 0.10 x 0.2
               = 0.25 x 0.566890 + 0.20 x 0.347081 + 0.005556 + 0.02 = 0.236694, shown 0.237.
        K 1 km:  0.25 x ln 125 / ln 50,000 + the rest = 0.25 x 0.446249 + 0.094972 = 0.206534, shown 0.207.
        """
        assert _scored(client, auth_cookie, keep_out_km="10")[0] == ["0.237"]
        assert _scored(client, auth_cookie, keep_out_km="1")[0] == ["0.207"]

    def test_the_result_states_the_distance_and_its_basis(self, client: Any, auth_cookie: str) -> None:
        text = _scored(client, auth_cookie, keep_out_km="25")[1]
        assert "full penalty at or inside the keep-out distance of 25 km" in text
        assert "its default, 10 km, is Claude's choice and unsourced" in text

    @pytest.mark.parametrize("value", ["0.05", "0", "-3", "10000.5", "50000", "nan", "inf", "-inf", "ten"])
    def test_an_out_of_range_or_non_finite_distance_is_refused_with_a_sentence(
        self, client: Any, auth_cookie: str, value: str,
    ) -> None:
        resp = _evaluate(client, auth_cookie, _form(keep_out_km=value))
        assert resp.status_code == 200
        assert "error-msg" in resp.text
        text = _flat(resp.text)
        assert "keep-out distance" in text.lower()
        assert not _SCORE.search(resp.text)

    @pytest.mark.parametrize("value", ["0.1", "10000"])
    def test_either_end_of_the_range_is_accepted(self, client: Any, auth_cookie: str, value: str) -> None:
        scores, text = _scored(client, auth_cookie, keep_out_km=value)
        assert scores
        assert f"keep-out distance of {float(value):g} km" in text

    def test_a_cleared_distance_is_refused_not_scored_at_the_default(self, client: Any, auth_cookie: str) -> None:
        """A cleared horizon is refused, not taken as 72 h; a cleared keep-out distance is refused, not taken as
        10 km. FastAPI reads a blank field as absent, so a form without the field is refused alike."""
        form = _form(keep_out_km="")
        without = {k: v for k, v in _form(keep_out_km="10").items() if k != "keep_out_km"}
        for posted in (form, without):
            resp = _evaluate(client, auth_cookie, posted)
            assert resp.status_code == 200
            assert "Enter a number for the keep-out distance (km)." in _flat(resp.text)
            assert not _SCORE.search(resp.text)

    def test_the_operators_distance_is_stated_as_entered(self, client: Any, auth_cookie: str) -> None:
        text = _scored(client, auth_cookie, keep_out_km="1234.5678")[1]
        assert "keep-out distance of 1234.5678 km" in text


class TestThePanelWithoutItsContext:
    def test_it_offers_no_default_it_cannot_give_the_basis_of(self) -> None:
        """The panel renders with no context (its other fields fall back); the keep-out field then shows no figure
        and no range of its own, so no default appears without its basis, and a blank is refused when posted."""
        from pathlib import Path

        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        from spectre.web.app import templates as app_templates

        root = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
        env = Environment(loader=FileSystemLoader(str(root)), autoescape=True, undefined=StrictUndefined)
        env.filters.update(app_templates.env.filters)
        page = env.get_template("partials/decision_panel.html").render(pol=None)
        found = _FIELD.search(page)
        assert found is not None
        assert 'value=""' in found.group(0)
        assert "min=" not in found.group(0) and "max=" not in found.group(0)
