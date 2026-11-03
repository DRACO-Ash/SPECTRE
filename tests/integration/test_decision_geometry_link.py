"""The geometry route opened from a Decision Engine cell (SPC-124).

A cell's Show trajectory form posts the bound pair, the window and one burn to the existing Hill-frame route, with
the element-set epochs the evaluation used and an allowlisted context. The route then says what the view is: a
Clohessy-Wiltshire picture from both SGP4 states at its start, which shows the shape of the approach, not the
cell's figures, which come from the propagator the context names. Where the element set now held is not the one
the evaluation used, it says so. Every sentence is fixed text; nothing posted is echoed.

The held objects are the plane_change reference element sets, posted at their own epoch, so no test reads the
wall clock.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE

_AT = "%Y-%m-%dT%H:%M:%S"
_VIEW_NOTE = (
    "A Clohessy-Wiltshire picture of the red track relative to the blue asset, from both SGP4 states at its start: "
    "it shows the shape of the approach, not the figures in the cell, which come from {propagator}. Where they "
    "differ, the cell's figures stand."
)
_SGP4 = "SGP4 for both orbits, from their element sets, with no burn"
_RK45 = "RK45 with J2 and exponential drag for both orbits"
_OURS = (
    "Our burn is drawn as the opposite change in the red track's velocity relative to the blue asset, which is how "
    "it moves the pair in this frame."
)


@pytest.fixture
def held(auth_cookie: str) -> Iterator[tuple[str, str]]:
    """The plane_change pair held as RED-PC and BLUE-PC; their stk_names."""
    from spectre.domain.models import BlueAsset, RedTrack

    state: Any = session_state(auth_cookie)
    saved = (list(state.red_tracks), list(state.blue_assets))
    state.red_tracks = [RedTrack("RED-PC", PLANE_CHANGE.red_tle, data_mode="REAL")]
    state.blue_assets = [BlueAsset("BLUE-PC", PLANE_CHANGE.blue_tle, data_mode="REAL")]
    yield state.red_tracks[0].stk_name, state.blue_assets[0].stk_name
    state.red_tracks, state.blue_assets = saved


def raw(client: Any, cookie: str, names: tuple[str, str], **fields: str) -> str:
    """The route's response as served."""
    data = {
        "red_sat": names[0], "blue_sat": names[1], "burn_epoch_str": EPOCH.strftime(_AT), "dv_prograde": "0",
        "dv_normal": "0", "dv_radial": "0", "tof_hours": "1", "coast_hours": "0", "method": "decision",
        "red_epoch": EPOCH.strftime(_AT), "blue_epoch": EPOCH.strftime(_AT),
    } | fields
    resp = client.post(
        "/plan/geometry/intercept", data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )
    assert resp.status_code == 200
    assert 'geom-panel"' in resp.text, resp.text[:300]
    return str(resp.text)


def geometry(client: Any, cookie: str, names: tuple[str, str], **fields: str) -> str:
    """The response as text, whitespace collapsed and entities read."""
    return html.unescape(" ".join(raw(client, cookie, names, **fields).split()))


class TestTheDecisionNote:
    def test_a_computed_sgp4_cell_names_sgp4(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        page = geometry(client, auth_cookie, held, context="decision-sgp4")
        assert _VIEW_NOTE.format(propagator=_SGP4) in page
        assert _OURS not in page

    def test_our_burn_is_said_to_be_drawn_reversed(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        page = geometry(client, auth_cookie, held, context="decision-rk45", our_burn="true", dv_prograde="3.085")
        assert _VIEW_NOTE.format(propagator=_RK45) in page
        assert _OURS in page

    def test_our_burn_needs_an_allowlisted_context(
        self, client: Any, auth_cookie: str, held: tuple[str, str],
    ) -> None:
        """Only a Decision Engine cell can say its burn is ours; the same flag from anywhere else says nothing."""
        for context in ("", "decision-other"):
            page = geometry(client, auth_cookie, held, context=context, our_burn="true", dv_prograde="3.085")
            assert _OURS not in page and "Clohessy-Wiltshire picture" not in page

    def test_the_intercept_panel_is_unchanged(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        page = geometry(client, auth_cookie, held, red_epoch="", blue_epoch="")
        assert "Clohessy-Wiltshire picture" not in page and "Drawn from the element set" not in page


class TestTheHeldElementSet:
    def test_a_newer_held_element_set_is_named(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        """54: the evaluation used an element set from 6 h before the one held now."""
        used = EPOCH - timedelta(hours=6)
        page = geometry(client, auth_cookie, held, context="decision-sgp4", red_epoch=used.strftime(_AT))
        assert (
            "Drawn from the element set now held for red, epoch 2026-10-17 12:00 UTC, not the one this evaluation "
            "used, epoch 2026-10-17 06:00 UTC."
        ) in page
        assert "now held for blue" not in page

    def test_the_same_element_sets_say_nothing(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        page = geometry(client, auth_cookie, held, context="decision-sgp4")
        assert "Drawn from the element set" not in page

    def test_an_unreadable_epoch_is_not_compared(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        page = geometry(client, auth_cookie, held, context="decision-sgp4", blue_epoch="not a time")
        assert "Drawn from the element set" not in page and "not a time" not in page


_IDS = re.compile(r'\bid="([^"]+)"')
_INTERCEPT_OPENER = "form[hx-target='#intercept-geometry-container'] button[type=submit]"
_DECISION_OPENER = "form.show-trajectory[data-geometry-opener] button[type=submit]"


def _opener(page: str) -> str:
    found = re.search(r"var OPENER = (\"[^\n]*\");", page)
    assert found is not None, "the panel names the control that opened it"
    return str(json.loads(found.group(1)))


class TestBothPanelsOnOnePage:
    """The operator page can hold the intercept result's Hill-frame panel and a Decision Engine cell's at once."""

    def test_the_two_panels_share_no_id(self, client: Any, auth_cookie: str, held: tuple[str, str]) -> None:
        """A shared id sends getElementById to the first panel: the second draws on a canvas already in use, and
        its close and Escape act on the other panel."""
        decision = raw(client, auth_cookie, held, context="decision-rk45")
        intercept = raw(client, auth_cookie, held, red_epoch="", blue_epoch="", method="lambert")
        decision_ids, intercept_ids = set(_IDS.findall(decision)), set(_IDS.findall(intercept))
        assert {"geom-panel", "geom-panel-heading", "cw-chart-vr"} <= intercept_ids
        assert {"decision-geom-panel", "decision-geom-panel-heading", "decision-cw-chart-vr"} <= decision_ids
        assert not decision_ids & intercept_ids, decision_ids & intercept_ids
        assert 'aria-labelledby="decision-geom-panel-heading"' in decision

    def test_neither_panel_puts_its_controls_on_window(
        self, client: Any, auth_cookie: str, held: tuple[str, str],
    ) -> None:
        """A global set by the second panel's script would drive the first panel's tabs and close button."""
        for page in (raw(client, auth_cookie, held, context="decision-sgp4"),
                     raw(client, auth_cookie, held, red_epoch="", blue_epoch="")):
            assert "window.geomTab" not in page and "window.spectreCloseGeometryPanel" not in page
            assert "onclick=" not in page

    def test_each_panel_returns_focus_to_its_own_opener(
        self, client: Any, auth_cookie: str, held: tuple[str, str],
    ) -> None:
        assert _opener(raw(client, auth_cookie, held, context="decision-rk45")) == _DECISION_OPENER
        assert _opener(raw(client, auth_cookie, held, red_epoch="", blue_epoch="")) == _INTERCEPT_OPENER
        from tests.unit.test_decision_figure_basis import _TEMPLATE_DIR

        intercept_result = (_TEMPLATE_DIR / "partials" / "intercept_result.html").read_text(encoding="utf-8")
        assert 'hx-target="#intercept-geometry-container"' in intercept_result
