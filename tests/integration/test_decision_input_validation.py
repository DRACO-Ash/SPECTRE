"""The Decision Engine refuses inputs outside their meaning, inline.

Audit F-164. decision_evaluate accepted any float for probability,
confidence, cost, reversibility, time, the weights and the horizon (negative,
NaN and zero included) and any number of rows. A zero horizon raised
ZeroDivisionError, surfaced as "Evaluation error", and an empty numeric field
returned a 422 that htmx does not swap, so the panel did nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import csrf_headers

#: What each row field took, before 0.42.0, on a row the form posted none for, by the column of ids it runs beside.
#: The route now refuses a missing one (SPC-222), so _form fills each in, as the panel posts each, and every test's
#: scenario is the one it always was.
_ROW_FILL: dict[str, tuple[str, str]] = {
    "adv_name": ("adv_id", "ADV-{row}"), "adv_type": ("adv_id", "manoeuvre"), "adv_prob": ("adv_id", "0.5"),
    "adv_conf": ("adv_id", "0.5"), "adv_gap": ("adv_id", "0.7"),
    "fr_name": ("fr_id", "FR-{row}"), "fr_type": ("fr_id", "manoeuvre"), "fr_cost": ("fr_id", "0.5"),
    "fr_rev": ("fr_id", "0.5"), "fr_time": ("fr_id", "6"),
}


def _form(*, pad: bool = True, **overrides: Any) -> dict[str, Any]:
    """A complete decision form, *overrides* applied. With *pad*, each row field the overrides leave short of its
    rows is filled to them with what the route gave a missing value before 0.42.0 (_ROW_FILL), so a test that names
    only the columns it is about posts every field, as the panel does; without it the form is posted as built."""
    form: dict[str, Any] = {
        "scenario_name": "Check", "horizon_hours": "72", "keep_out_km": "10",
        "adv_id": ["A1"], "adv_name": ["Approach"], "adv_type": ["manoeuvre"],
        "adv_prob": ["0.6"], "adv_conf": ["0.7"], "adv_gap": ["0.7"],
        "fr_id": ["F1"], "fr_name": ["Hold"], "fr_type": ["manoeuvre"],
        "fr_cost": ["0.2"], "fr_rev": ["0.8"], "fr_time": ["4"],
        "w_custody": "0.35", "w_ca": "0.25", "w_dv": "0.2", "w_time": "0.1", "w_rev": "0.1",
        "strategy": "minimax",
    }
    form.update(overrides)
    for field, (ids, fill) in _ROW_FILL.items():
        column, rows = list(form.get(field) or []), len(form.get(ids) or [])
        if pad and field in form and len(column) < rows:
            form[field] = column + [fill.format(row=row) for row in range(len(column) + 1, rows + 1)]
    return form


def _evaluate(client: Any, cookie: str, form: dict[str, Any]) -> Any:
    return client.post(
        "/plan/decision/evaluate", data=form,
        cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )


def test_a_valid_scenario_evaluates(client: Any, auth_cookie: str) -> None:
    resp = _evaluate(client, auth_cookie, _form())
    assert resp.status_code == 200
    assert "error-msg" not in resp.text


@pytest.mark.parametrize(("overrides", "message"), [
    ({"w_dv": "-0.2"}, "weight"),
    ({"w_custody": "nan"}, "weight"),
    ({"horizon_hours": "0"}, "horizon"),
    ({"horizon_hours": "721"}, "horizon"),
    ({"adv_prob": ["1.5"]}, "probability"),
    ({"adv_conf": ["-0.1"]}, "confidence"),
    ({"fr_cost": ["2"]}, "cost"),
    ({"fr_rev": ["nan"]}, "reversibility"),
    ({"fr_time": ["-1"]}, "time"),
    ({"adv_prob": [""]}, "probability"),
    ({"horizon_hours": ""}, "horizon"),
    ({"adv_id": [f"A{i}" for i in range(6)]}, "1 to 5"),
    ({"fr_id": [f"F{i}" for i in range(6)]}, "1 to 5"),
])
def test_an_out_of_range_input_is_refused_inline(
    client: Any, auth_cookie: str, overrides: dict[str, Any], message: str,
) -> None:
    resp = _evaluate(client, auth_cookie, _form(**overrides))
    assert resp.status_code == 200, "htmx swaps only a 2xx, so the refusal must be one"
    assert "error-msg" in resp.text
    assert message in resp.text.lower()
    assert "Evaluation error" not in resp.text
