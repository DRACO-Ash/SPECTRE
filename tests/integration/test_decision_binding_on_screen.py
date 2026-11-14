"""The decision panel offers the held objects to bind, and the result says what it is bound to (SPC-100).

Binding records which real objects a scenario is about and how old their
orbits are. Bound on both sides, a row whose action does not move red has its
closest approach computed by SGP4 (SPC-120), and a manoeuvre with no
hypothesis says why it is not; before SPC-120 the page after the "Bound to"
block was the same as the unbound page.
The panel's hypothesis section (SPC-114) is tested in
test_decision_hypothesis_panel.py; these forms post none.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any

import pytest

from spectre.domain.decision import BINDING_NOTE, COMPUTED_CAVEAT_ELSET, CUSTODY_NOTE
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
    """The page after the "Bound to" block, with computation time and the scenario epoch's minute masked."""
    start = html.index('class="scenario-binding"')
    after = re.sub(r"\d+\.\d+s", "#s", html[html.index("</div>", start):])
    return re.sub(r"Scenario epoch \d{4}-\d\d-\d\d \d\d:\d\d UTC", "Scenario epoch # UTC", after)


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
    def test_a_bound_evaluation_shows_what_it_is_bound_to(
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
        assert "Orbit current: 5.0 h old at evaluation, limit 72 h, the GEO figure, set for GEO." in text
        # SPC-215: each bound set states its regime and whose figures the engine applies to it.
        assert re.search(r"Regime GEO \(period 14\d\d min, e 0\.\d{3}\): staleness limit 72 h and element-set error "
                         r"2 km plus 1 km a day, GEO figure, set for GEO\.", _line(block, "Blue"))
        assert BINDING_NOTE in text
        assert held.log_entries[-1].endswith(" Bound to red RX and blue BY.")
        unbound = _evaluate(client, auth_cookie, _form())
        assert _UNBOUND in unbound.text
        # Inverted by SPC-120: a manoeuvre row with no hypothesis now says why its closest approach is not computed.
        assert _after_binding(html) != _after_binding(unbound.text)
        assert text.count("Not computed: a manoeuvre with no hypothesis names no burn") == 1
        assert "Not computed" not in _flat(re.sub(r"<[^>]+>", "", unbound.text))

    def test_a_bound_row_that_does_not_move_red_is_computed_on_screen(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """SPC-120: red's element set an hour older than blue's puts the two GEO objects about 15 degrees apart."""
        _hold(held, red_hours=6.0)
        bound = _evaluate(client, auth_cookie, _form(red_sat="RX", blue_sat="BY", adv_type=["no_action"]))
        assert bound.status_code == 200
        text = _flat(re.sub(r"<[^>]+>", "", bound.text))
        assert re.search(r"\d+\.\d km \(computed\)", text)
        assert re.search(r"Computed: \d[\d.,]* km at \d{4}-\d\d-\d\d \d\d:\d\d UTC( ± [^,]+)?, \d+(\.\d+)? h after the scenario epoch; SGP4, no burn\.", text)
        # The band beside the miss, with both sets' ages at the scenario epoch, which the wall clock sets (SPC-202).
        before, after = (re.escape(part) for part in COMPUTED_CAVEAT_ELSET.split("{ages}"))
        assert re.search(before + r"red's set \d+\.\d h old and blue's \d+\.\d h old" + after, html.unescape(text))
        # The no-action row at the form's P 0.6 and the remainder of P, 0.4, a no-action row too (SPC-203).
        assert "Phase 3 · computed closest approach in 2 cells · sampled in 0 cells" in text
        unbound = _flat(re.sub(r"<[^>]+>", "", _evaluate(client, auth_cookie, _form(adv_type=["no_action"])).text))
        assert "(computed)" not in unbound and "Phase 1" in unbound

    def test_a_bound_red_tracks_custody_is_computed_on_screen(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """K10, SPC-123: UDL is not connected in this session, so custody is degraded, shown as degraded and never
        as held or lost (SPC-179), and says so."""
        _hold(held)
        form = _form(red_sat="RX", blue_sat="BY", adv_type=["no_action"], horizon_hours="24")
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200
        text = html.unescape(_flat(re.sub(r"<[^>]+>", "", resp.text)))
        assert (
            "Custody at evaluation: Custody degraded: its orbit is current (5.0 h old, limit 72 h, the GEO figure, set "
            "for GEO), but whether its "
            "burns are normal cannot be judged. UDL is not connected, so no element-set history is held."
        ) in text
        assert ("Custody degraded through the 24 h horizon: its newest element set stays within its 72 h limit, "
                "the GEO figure, set for GEO, until") in text
        assert (
            "Degraded, neither held nor lost: how a burn changes your warning time can be judged, but whether it is "
            "normal cannot."
        ) in text
        assert "◐ custody degraded (computed)" in text and "✓ custody" not in text and "✗ custody" not in text
        assert CUSTODY_NOTE in text
        assert "Custody here is a rule of thumb" not in text
        assert "Basis: Custody: computed in every cell." in text

    def test_an_unbound_page_keeps_the_rule_of_thumb_and_says_bind_a_red_track(
        self, client: Any, auth_cookie: str,
    ) -> None:
        text = _flat(re.sub(r"<[^>]+>", "", _evaluate(client, auth_cookie, _form()).text))
        assert "Custody here is a rule of thumb" in text
        assert "Bind a red track to compute it from its element set and history." in text
        assert "Custody at evaluation" not in text

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
            f"Orbit out of date: {age} old at evaluation against a {limit} h limit, the {'LEO' if leo else 'GEO'} "
            f"figure, set for {'LEO' if leo else 'GEO'}, so a burn since its epoch would not be seen."
        ) in text
        assert "Blue: not bound." in text

    def test_a_training_object_is_marked_in_the_result(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held, red_training=True)
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        red = _line(_binding_block(resp.text), "Red")
        assert re.search(r"Data mode SIMULATED <span[^>]*>SIMULATED</span>, training\.", red)

    def test_an_alpha5_catalogue_number_is_read(self, client: Any, auth_cookie: str, held: Any) -> None:
        _hold(held, red_tle=_alpha5(_tle(datetime.now(tz=UTC) - timedelta(hours=5), satno=50322), "A0001"))
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        assert "error-msg" not in resp.text
        text = _flat(re.sub(r"<[^>]+>", "", resp.text))
        assert "Red: RX (RX), SATNO 100001." in text
        assert "None" not in text.replace("None of these", "")   # the decision choice (SPC-192) is words

    def test_a_bad_letter_is_refused_by_the_acceptance_check(self, client: Any, auth_cookie: str, held: Any) -> None:
        """I is no Alpha-5 letter, so the catalogue number does not read and the set is not bound (SPC-201)."""
        _hold(held, red_tle=_alpha5(_tle(datetime.now(tz=UTC) - timedelta(hours=5), satno=50322), "I0001"))
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        assert (
            "The element set for red track RX was refused: the catalogue number on line 1 cannot be read. Nothing "
            "was bound; add a sound element set for it." in resp.text
        )

    def test_an_unreadable_epoch_is_refused_by_the_acceptance_check(
        self, client: Any, auth_cookie: str, held: Any,
    ) -> None:
        """A held set whose epoch does not read is never bound (SPC-201); the result's "Epoch unreadable" line is
        held below, for a binding built in code."""
        line1, line2 = _tle(datetime.now(tz=UTC)).split("\n")
        _hold(held, red_tle=f"{line1[:20]}000{line1[23:]}\n{line2}")
        resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
        assert resp.status_code == 200
        text = _flat(re.sub(r"<[^>]+>", "", resp.text))
        assert "the epoch cannot be read. Nothing was bound; add a sound element set for it." in text
        assert "Evaluation error" not in text

    def test_a_binding_built_in_code_still_renders_what_it_cannot_read(self) -> None:
        """The result never reads more into a set than it holds, however it was bound: an unreadable number and
        epoch are said in words, as before the acceptance check (SPC-201) kept such sets from the panel."""
        from spectre.domain.decision import ScenarioBinding, evaluate_scenario
        from spectre.domain.models import RedTrack
        from spectre.web.decision_binding import bound_elset
        from tests.unit.test_decision_figure_basis import _render
        from tests.unit.test_decision_sampled import _scenario

        line1, line2 = _alpha5(_tle(datetime.now(tz=UTC)), "I0001").split("\n")
        unread = f"{line1[:20]}000{line1[23:]}\n{line2}"
        binding = ScenarioBinding(red=bound_elset("red", RedTrack(name="RX", tle=unread), datetime.now(tz=UTC)))
        text = _flat(re.sub(r"<[^>]+>", "", _render(evaluate_scenario(_scenario(binding=binding)))))
        assert "Red: RX (RX), SATNO unreadable." in text
        assert "Epoch unreadable" in text
        assert "Its epoch cannot be read, so its age is unknown; read it as out of date." in text

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


class TestTheBindRegionStandsAlone:
    """Found building SPC-130: inside the evaluate form, htmx 1.9.12 gives the bind region the form's target and
    disabled element; it cannot find that submit button, throws, and the region never refreshes."""

    def test_the_bind_region_takes_nothing_from_the_evaluate_form_around_it(
        self, client: Any, auth_cookie: str,
    ) -> None:
        from tests.integration.test_decision_prior_route import _INHERITED, _VOID

        class _ById(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.stack: list[tuple[str, dict[str, str]]] = []
                self.found: list[tuple[str, dict[str, str]]] | None = None

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                here = (tag, {k: v or "" for k, v in attrs})
                if self.found is None and here[1].get("id") == "decision-bind":
                    self.found = [*self.stack, here]
                if tag not in _VOID:
                    self.stack.append(here)

            def handle_endtag(self, tag: str) -> None:
                while self.stack and self.stack.pop()[0] != tag:
                    pass

        parser = _ById()
        parser.feed(client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie}).text)
        assert parser.found is not None
        *around, (_, region) = parser.found
        assert any(tag == "form" for tag, _ in around)
        taken = {name for _, attrs in around for name in attrs if name in _INHERITED}
        assert taken
        assert sorted(name for name in taken if name not in region) == []
        assert (region["hx-target"], region["hx-swap"]) == ("this", "innerHTML")
