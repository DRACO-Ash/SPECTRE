"""Routes that bind their fields through a form model validate as before.

SonarQube python:S107 (0.6.0 submission) flagged ``apply_intercept`` and
``decision_evaluate`` for their parameter counts, and the fields moved into
Pydantic form models. The form contract is what callers see, so it is pinned
here: the same names, the same bounds, the same 422 on a value out of range.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import csrf_headers
from tests.integration.test_web_routes_extended import _add_assets

_INTERCEPT = {"red_sat": "ISS-RED", "blue_sat": "ISS-BLUE", "method": "hohmann",
              "coast_hours": "0.0", "intercept_hours": "2.0"}


def _post(client: Any, cookie: str, path: str, data: dict[str, Any]) -> Any:
    return client.post(path, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))


class TestInterceptForm:
    def test_a_valid_form_is_computed(self, client: Any, auth_cookie: str) -> None:
        _add_assets(client, auth_cookie)
        resp = _post(client, auth_cookie, "/plan/maneuver/apply-intercept", _INTERCEPT)
        assert resp.status_code == 200
        assert "Intercept calculation failed" not in resp.text
        assert "ISS-RED" in resp.text

    @pytest.mark.parametrize(("field", "value"), [
        ("revolutions", "0"), ("revolutions", "51"), ("hops", "21"),
        ("max_dv_m_s", "-1"), ("coast_hours", "soon"),
    ])
    def test_a_field_out_of_range_is_refused(self, client: Any, auth_cookie: str, field: str, value: str) -> None:
        _add_assets(client, auth_cookie)
        resp = _post(client, auth_cookie, "/plan/maneuver/apply-intercept", {**_INTERCEPT, field: value})
        assert resp.status_code == 422

    def test_a_missing_required_field_is_refused(self, client: Any, auth_cookie: str) -> None:
        data = {k: v for k, v in _INTERCEPT.items() if k != "method"}
        assert _post(client, auth_cookie, "/plan/maneuver/apply-intercept", data).status_code == 422


class TestDecisionForm:
    _SCENARIO = {
        "scenario_name": "Form model", "horizon_hours": "72",
        "adv_id": ["A1", "A2"], "adv_name": ["Approach", "Hold"], "adv_type": ["RPO", "RPO"],
        "adv_prob": ["0.6", "0.4"], "adv_conf": ["0.8", "0.7"],
        "fr_id": ["F1"], "fr_name": ["Manoeuvre"], "fr_type": ["MANOEUVRE"],
        "fr_cost": ["0.2"], "fr_rev": ["0.5"], "fr_time": ["2"],
    }

    def test_parallel_arrays_are_read_by_their_form_names(self, client: Any, auth_cookie: str) -> None:
        resp = _post(client, auth_cookie, "/plan/decision/evaluate", self._SCENARIO)
        assert resp.status_code == 200
        assert "error-msg" not in resp.text
        assert "Manoeuvre" in resp.text, "the one friendly response is the recommendation"

    def test_a_blank_horizon_is_refused_not_defaulted(self, client: Any, auth_cookie: str) -> None:
        resp = _post(client, auth_cookie, "/plan/decision/evaluate", {**self._SCENARIO, "horizon_hours": ""})
        assert resp.status_code == 200
        assert "error-msg" in resp.text
        assert "horizon" in resp.text.lower()
