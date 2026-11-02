"""The evaluated Decision Engine page states each figure's basis (SPC-101).

Through the real route: a Phase 1 result says every figure is a lookup, marks
each one, and puts the custody rule of thumb on screen rather than in a hover.
Nothing reads as computed.
"""

from __future__ import annotations

from typing import Any

from tests.integration.test_decision_input_validation import _evaluate, _form


def test_the_evaluated_page_states_every_basis(client: Any, auth_cookie: str) -> None:
    resp = _evaluate(client, auth_cookie, _form())
    assert resp.status_code == 200
    assert "error-msg" not in resp.text
    assert 'data-basis="lookup"' in resp.text
    assert "Every figure in every cell is a lookup." in resp.text
    assert "Custody here is a rule of thumb, not the held, degraded or lost custody shown on the sweep." in resp.text
    assert 'data-basis="computed"' not in resp.text
