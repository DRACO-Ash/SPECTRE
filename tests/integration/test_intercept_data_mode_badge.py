"""The Data Mode badge states the element sets' provenance, not the request.

Audit F-133. The badge showed the mode the operator asked for, defaulting to
REAL, while the re-fetch silently kept the original element sets when there
were no credentials, no number or a failed fetch. A result computed from
pasted sets carried "Data Mode: REAL".
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import csrf_headers
from tests.integration.test_web_routes_extended import _add_assets


@pytest.mark.parametrize("path", ["apply-intercept", "apply-all-intercepts"])
def test_without_a_fetch_the_badge_does_not_read_real(client: Any, auth_cookie: str, path: str) -> None:
    from spectre.web.planning_state import get_session_state

    _add_assets(client, auth_cookie)
    state = get_session_state("testadmin")
    assert not state.udl_username, "precondition: no UDL session, so nothing can be fetched"
    resp = client.post(
        f"/plan/maneuver/{path}",
        data={"red_sat": "ISS-RED", "blue_sat": "ISS-BLUE", "method": "hohmann",
              "coast_hours": "0.0", "intercept_hours": "2.0", "intercept_data_mode": "REAL"},
        cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
    )
    assert resp.status_code == 200
    flat = " ".join(resp.text.split())
    assert "Data Mode: REAL" not in flat
    assert "Data Mode: UNVERIFIED" in flat
