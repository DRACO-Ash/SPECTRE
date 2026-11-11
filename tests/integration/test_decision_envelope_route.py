"""The panel refuses a scenario outside the operating envelope it can see before anything runs (SPC-200, F-31).

Evaluation probe P-14 posted all five scoring weights at 0: the route left them as given, every score was 0, and the
pick followed row order with no flag. A recommendation with no basis was presented as one. All-zero weights are now
refused beside the form, in a sentence; any total above 0 is scaled to 1, as before.
"""

from __future__ import annotations

from typing import Any

from tests.integration.test_decision_input_validation import _evaluate, _form

_ALL_ZERO = {"w_custody": "0", "w_ca": "0", "w_dv": "0", "w_time": "0", "w_rev": "0"}


def test_all_five_weights_at_0_are_refused_with_a_sentence(client: Any, auth_cookie: str) -> None:
    resp = _evaluate(client, auth_cookie, _form(**_ALL_ZERO))
    assert resp.status_code == 200, "htmx swaps only a 2xx, so the refusal must be one"
    assert "error-msg" in resp.text
    assert (
        "Every scoring weight is 0, so every score would be 0 and no rule could pick a response on them. Set at "
        "least one weight above 0." in resp.text
    )
    assert "Outcome Matrix" not in resp.text


def test_one_weight_above_0_evaluates(client: Any, auth_cookie: str) -> None:
    resp = _evaluate(client, auth_cookie, _form(**{**_ALL_ZERO, "w_ca": "0.001"}))
    assert resp.status_code == 200
    assert "error-msg" not in resp.text
    assert "Outcome Matrix" in resp.text
