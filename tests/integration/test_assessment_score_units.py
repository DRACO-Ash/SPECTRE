"""An assessment score is never presented as a miss distance in km.

Audit F-131. Assessment methods carry a 0 to 100 score in
``intercept_range_km``. The result card already branched on that, but the
trade-space JSON (and its tooltip) and the clipboard text labelled it km
unconditionally, so a score of 73 was copied or plotted as a 73 km miss.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import csrf_headers
from tests.integration.test_web_routes_extended import _add_assets


def _apply(client: Any, cookie: str, method: str) -> Any:
    return client.post(
        "/plan/maneuver/apply-intercept",
        data={"red_sat": "ISS-RED", "blue_sat": "ISS-BLUE", "method": method,
              "coast_hours": "0.0", "intercept_hours": "2.0"},
        cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )


def test_the_clipboard_and_trade_space_keep_scores_and_misses_apart(client: Any, auth_cookie: str) -> None:
    _add_assets(client, auth_cookie)
    client.post("/plan/maneuver/clear-history", cookies={"spectre_session": auth_cookie},
                headers=csrf_headers(auth_cookie))
    scored = _apply(client, auth_cookie, "detectability")
    assert scored.status_code == 200
    assert "Miss Dist:" not in scored.text
    assert "Score:" in scored.text
    flown = _apply(client, auth_cookie, "hohmann")
    assert "Miss Dist:" in flown.text

    points = client.get("/plan/maneuver/trade-space-data", cookies={"spectre_session": auth_cookie}).json()
    by_method = {p["method"]: p for p in points}
    assert "miss_km" not in by_method["detectability"]
    assert 0 <= by_method["detectability"]["score"] <= 100
    assert "miss_km" in by_method["hohmann"]
    assert "score" not in by_method["hohmann"]
