"""The decision panel offers the held objects to bind, and the result says what it is bound to (SPC-100).

Binding records which real objects a scenario is about and how old their
orbits are. It changes no figure: the page after the "Bound to" block is the
same as the unbound page, computation time aside.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.domain.decision import BINDING_NOTE
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_form_labels import _unlabelled
from tests.unit.test_elset_freshness import _checksummed, _tle

_UNBOUND = "Scenario not bound to a red track or blue asset."


@pytest.fixture
def held(auth_cookie: str) -> Iterator[Any]:
    from tests.integration.conftest import session_state

    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), list(state.blue_assets))
    yield state
    state.red_tracks, state.blue_assets = saved


def _hold(
    state: Any, *, red_hours: float = 5.0, red_tle: str | None = None, red_leo: bool = False,
    red_training: bool = False,
) -> None:
    from spectre.domain.models import BlueAsset, RedTrack

    now = datetime.now(tz=UTC)
    red = red_tle or _tle(now - timedelta(hours=red_hours), satno=50322, leo=red_leo)
    state.red_tracks = [RedTrack("RX", red, data_mode="SIMULATED", training=red_training)]
    state.blue_assets = [BlueAsset("BY", _tle(now - timedelta(hours=5), satno=40001), data_mode="REAL")]


def _get(client: Any, cookie: str, path: str) -> str:
    resp = client.get(path, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


def _flat(html: str) -> str:
    return " ".join(html.split())


def _select(html: str, select_id: str) -> str:
    match = re.search(rf'<select[^>]*id="{select_id}"[^>]*>(.*?)</select>', html, re.S)
    assert match, f"no select {select_id}"
    return match.group(1)


def _alpha5(tle: str, satno: str = "A0001") -> str:
    """*tle* renumbered with an Alpha-5 catalogue number, checksums recomputed."""
    return "\n".join(_checksummed(f"{line[:2]}{satno}{line[7:]}") for line in tle.split("\n"))


def _binding_block(html: str) -> str:
    start = html.index('class="scenario-binding"')
    return html[start:html.index("</div>", start)]


def _line(block: str, side: str) -> str:
    """The <p> in the "Bound to" block that starts with *side*, whitespace collapsed."""
    for para in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S):
        flat = _flat(para)
        if flat.startswith(f"{side}:"):
            return flat
    raise AssertionError(f"no {side} line in the binding block")


def _after_binding(html: str) -> str:
    """The page after the "Bound to" block, with computation time masked."""
    start = html.index('class="scenario-binding"')
    return re.sub(r"\d+\.\d+s", "#s", html[html.index("</div>", start):])


class TestThePanel:
    def test_the_panel_offers_held_objects_and_says_binding_changes_nothing(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        _hold(held)
        html = _get(client, auth_cookie, "/plan/decision/panel")
        for select_id, label in (("dec-red-sat", "RX (RX) · SIMULATED"), ("dec-blue-sat", "BY (BY) · REAL")):
            options = re.findall(r"<option[^>]*>([^<]*)</option>", _select(html, select_id))
            assert options[0].strip() == "Not bound", select_id
            assert label in [o.strip() for o in options], select_id
        assert BINDING_NOTE in _flat(html)
        assert "lookup only" not in html

    def test_with_nothing_held_the_panel_says_so(self, client: Any, auth_cookie: str, held: Any) -> None:
        held.red_tracks, held.blue_assets = [], []
        html = _get(client, auth_cookie, "/plan/decision/panel")
        text = _flat(html)
        assert "No red track is held. Add one under Red Tracks to bind it here." in text
        assert "No blue asset is held. Add one under Blue Assets to bind it here." in text
        assert "Not bound" in _select(html, "dec-red-sat") and "Not bound" in _select(html, "dec-blue-sat")

    def test_the_bind_fields_are_labelled(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held)
        fragment = _get(client, auth_cookie, "/plan/decision/bind")
        assert _unlabelled(fragment) == []
        assert 'id="decision-bind"' not in fragment, "the fragment must not re-emit its own wrapper"
        panel = _get(client, auth_cookie, "/plan/decision/panel")
        assert panel.count('id="dec-red-sat"') == 1 and panel.count('id="dec-blue-sat"') == 1
        assert panel.count('id="decision-bind"') == 1
        wrapper = re.search(r'<div id="decision-bind"([^>]*)>', panel)
        assert wrapper, "no #decision-bind wrapper"
        attrs = _flat(wrapper.group(1))
        # Rebuilt each time it comes into view, into the wrapper, sending the current choices.
        assert 'hx-get="/plan/decision/bind"' in attrs
        assert 'hx-trigger="intersect"' in attrs
        assert 'hx-swap="innerHTML"' in attrs, "outerHTML would replace the observed wrapper"
        assert 'hx-include="#dec-red-sat, #dec-blue-sat"' in attrs

    def test_the_bind_refresh_keeps_a_held_choice(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held)
        kept = _get(client, auth_cookie, "/plan/decision/bind?red_sat=RX&blue_sat=BY")
        assert re.search(r'<option value="RX" selected>', _select(kept, "dec-red-sat"))
        assert re.search(r'<option value="BY" selected>', _select(kept, "dec-blue-sat"))
        gone = _get(client, auth_cookie, "/plan/decision/bind?red_sat=GONE")
        selected = re.findall(r"<option[^>]*selected[^>]*>([^<]*)</option>", gone)
        assert [s.strip() for s in selected] == ["Not bound", "Not bound"]
        crossed = _get(client, auth_cookie, "/plan/decision/bind?red_sat=BY&blue_sat=RX")
        selected = re.findall(r"<option[^>]*selected[^>]*>([^<]*)</option>", crossed)
        assert [s.strip() for s in selected] == ["Not bound", "Not bound"], "a choice is kept only on its own side"

    def test_a_training_object_is_marked_in_the_panel(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held, red_training=True)
        options = _flat(_select(_get(client, auth_cookie, "/plan/decision/bind"), "dec-red-sat"))
        assert "RX (RX) · SIMULATED · training" in options

    def test_the_bind_fragment_needs_a_sign_in(self, client: Any) -> None:
        # The module's client keeps the cookie its sign-in set; this request goes without it.
        saved = dict(client.cookies)
        client.cookies.clear()
        try:
            panel = client.get("/plan/decision/panel", follow_redirects=False)
            bind = client.get("/plan/decision/bind", follow_redirects=False)
        finally:
            client.cookies.update(saved)
        assert bind.status_code == panel.status_code == 302
        assert bind.headers["location"] == panel.headers["location"]


class TestTheResult:
    def test_a_bound_evaluation_shows_what_it_is_bound_to_and_changes_no_figure(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        _hold(held)
        bound = _evaluate(client, auth_cookie, _form(red_sat="RX", blue_sat="BY"))
        assert bound.status_code == 200
        html = bound.text
        text = _flat(re.sub(r"<[^>]+>", "", html))
        epoch = held.red_tracks[0].tle
        from spectre.web.elsets import elset_age

        age = elset_age(epoch, datetime.now(tz=UTC))
        assert age is not None
        assert "Red: RX (RX), SATNO 50322." in text
        assert "Blue: BY (BY), SATNO 40001." in text
        assert f"Epoch {age.epoch.strftime('%Y-%m-%d %H:%M UTC')}" in text
        assert re.search(r'<span class="badge-ok"[^>]*>5\.0 h old</span>', html)
        assert "Data mode SIMULATED" in text
        block = _binding_block(html)
        # The caution badge sits on the simulated red, and not on the real blue.
        assert re.search(r'Data mode SIMULATED <span class="provenance-badge"[^>]*>SIMULATED</span>', _line(block, "Red"))
        blue = _line(block, "Blue")
        assert "Data mode REAL" in blue
        assert "provenance-badge" not in blue[blue.index("Data mode REAL"):blue.index("Orbit current")]
        assert "Orbit current: 5.0 h old at evaluation, limit 72 h." in text
        assert BINDING_NOTE in text
        assert held.log_entries[-1].endswith(" Bound to red RX and blue BY.")
        unbound = _evaluate(client, auth_cookie, _form())
        assert _UNBOUND in unbound.text
        assert _after_binding(html) == _after_binding(unbound.text), "binding changed something on screen"

    @pytest.mark.parametrize("case", [
        (13 * 24.0, False, "13.0 d", 72),
        (48.0, True, "2.0 d", 24),
    ])
    def test_a_stale_set_is_bound_and_flagged_as_the_red_card_flags_it(
        self, client: Any, auth_cookie: str, held: Any, case: tuple[float, bool, str, int],
    ) -> None:
        hours, leo, age, limit = case
        _hold(held, red_hours=hours, red_leo=leo)
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        assert "error-msg" not in resp.text
        badge = re.search(rf'<span class="badge-warn"\s+title="([^"]*)">{re.escape(age)} old STALE</span>', resp.text)
        assert badge, "no STALE badge"
        assert badge.group(1) == f"Age at evaluation. STALE is past {limit} hours, the limit for this regime"
        text = _flat(re.sub(r"<[^>]+>", "", resp.text))
        assert (
            f"Orbit out of date: {age} old at evaluation against a {limit} h limit, "
            "so a burn since its epoch would not be seen."
        ) in text
        assert "Blue: not bound." in text

    def test_a_training_object_is_marked_in_the_result(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held, red_training=True)
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        red = _line(_binding_block(resp.text), "Red")
        assert re.search(r"Data mode SIMULATED <span[^>]*>SIMULATED</span>, training\.", red)

    def test_an_alpha5_catalogue_number_reads_as_unreadable(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        _hold(held, red_tle=_alpha5(_tle(datetime.now(tz=UTC) - timedelta(hours=5), satno=50322)))
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        assert "error-msg" not in resp.text
        text = _flat(re.sub(r"<[^>]+>", "", resp.text))
        assert "Red: RX (RX), SATNO unreadable." in text
        assert "None" not in text

    def test_an_unreadable_epoch_renders(self, client: Any, auth_cookie: str, held: Any) -> None:
        line1, line2 = _tle(datetime.now(tz=UTC)).split("\n")
        _hold(held, red_tle=f"{line1[:20]}000{line1[23:]}\n{line2}")
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        text = _flat(re.sub(r"<[^>]+>", "", resp.text))
        assert "Epoch unreadable" in text
        assert "Its epoch cannot be read, so its age is unknown; read it as out of date." in text
        assert "None" not in text
        assert "Evaluation error" not in text

    def test_a_vanished_object_is_refused_inline(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held)
        resp = _evaluate(client, auth_cookie, _form(red_sat="GONE"))
        assert resp.status_code == 200
        assert "error-msg" in resp.text
        assert "Red track GONE is no longer held in this session. Choose another or leave it unbound." in resp.text
        assert "Evaluation error" not in resp.text

    def test_an_unbound_evaluation_is_as_before(self, client: Any, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _form())
        assert resp.status_code == 200
        text = _flat(re.sub(r"<[^>]+>", "", resp.text))
        assert _UNBOUND in text
        assert "Every figure in every cell is a lookup." in text
