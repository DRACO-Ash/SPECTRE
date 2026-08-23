"""Reflected cross-site scripting guards on the raw-HTML error paths.

Most of SPECTRE renders through Jinja, which autoescapes. A handful of error
partials build markup with f-strings instead, which bypasses that entirely, so
escaping at the interpolation point is the only control in the path. SonarQube
flagged seven of these and was right about all seven.

These are behavioural tests: they push a payload through the real endpoint and
assert it comes back inert.
"""

from __future__ import annotations

import pytest

from tests.conftest import csrf_headers

_PAYLOAD = "<script>alert('xss')</script>"
_ESCAPED = "&lt;script&gt;"


def _assert_inert(body: bytes) -> None:
    """The payload must never appear as live markup."""
    text = body.decode()
    assert "<script>alert(" not in text, "payload reflected as executable markup"
    if "alert(" in text:
        assert _ESCAPED in text, "payload present but not escaped"


class TestGeometryErrors:
    def test_unparseable_epoch_is_escaped(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/geometry/intercept",
            data={
                "red_sat": "RED-1", "blue_sat": "BLUE-1",
                "burn_epoch": _PAYLOAD, "delta_v": "0.1",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        _assert_inert(resp.content)

    def test_unknown_satellite_name_is_escaped(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/geometry/intercept",
            data={
                "red_sat": _PAYLOAD, "blue_sat": "BLUE-1",
                "burn_epoch": "2026-01-01T00:00:00", "delta_v": "0.1",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        _assert_inert(resp.content)


class TestGcatErrors:
    def test_unknown_dataset_key_is_escaped(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/gcat/table",
            params={"dataset": _PAYLOAD},
            cookies={"spectre_session": auth_cookie},
        )
        _assert_inert(resp.content)


class TestAssetBadges:
    @pytest.mark.parametrize("endpoint", ["/assets/blue/quick-add", "/assets/red/quick-add"])
    def test_quick_add_button_id_is_escaped(
        self, client: object, auth_cookie: str, endpoint: str
    ) -> None:
        """btn_id is written into an id attribute straight from a form field."""
        resp = client.post(  # type: ignore[attr-defined]
            endpoint,
            data={"satno": "25544", "btn_id": _PAYLOAD},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        _assert_inert(resp.content)
