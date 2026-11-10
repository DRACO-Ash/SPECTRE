"""The panel records whether each adversary row's P was edited, and the guidance reads that record (SPC-183).

The owner ruled on 2026-11-05 (concept section 9, decision 11) that the form tracks whether each P was edited, so
a deliberate 0.5 is not read as the untouched default. The record is made on the server, with no script: the
NOTSO region inside the evaluate form is asked again on every change in the form, sending every row's id and P, and
it answers with a hidden field per edited row, keyed by the row's id, which the next change and Evaluate send back.
A row is edited once its P is posted as anything but the text the panel gave it, and stays edited after that, so
editing away from 0.5 and back to it is recorded. htmx 1.9.12 names in HX-Trigger-Name the element that asks, here
the region, not the field that changed, so the record compares each row's P with the panel's own text instead.
Evaluate reads the record and the P posted with it, so an edit to anything but 0.5 made just before pressing it
still counts; an edit away from 0.5 and back that the region has not yet answered is not recorded, and the row then
shows the guidance, the cautious side. A row whose P came from an applied NOTSO suggestion counts as edited. A row
whose P was never edited says its P is the panel's default and only its Conf the operator's.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from spectre.domain.decision import DEFAULT_P_VALUES, DEFAULT_PROBABILITY, OWN_VALUES
from spectre.web.decision_prior import UNEDITED_PROBABILITY, edited_rows
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_prior_route import _P, _lineage, _region, _text, held  # noqa: F401

_GUIDANCE = "Expected value rests on a probability the evidence has not earned."


def _recorded(page: str) -> list[str]:
    return re.findall(r'<input type="hidden" name="adv_p_edited" value="([^"]+)">', page)


class TestTheRecord:
    def test_the_unedited_text_is_what_the_panel_gives_every_row(self) -> None:
        assert UNEDITED_PROBABILITY == f"{DEFAULT_PROBABILITY}" == "0.5"

    @pytest.mark.parametrize(("ids", "probs", "recorded", "expected"), [
        (["A1", "A2"], ["0.5", "0.4"], [], ["A2"]),          # edited away from the panel's text
        (["A1", "A2"], ["0.5", "0.5"], ["A2"], ["A2"]),      # edited and back to 0.5: still the operator's own
        (["A1", "A2"], ["0.50", "0.5"], [], ["A1"]),         # any change of the text is an edit
        (["A1", "A2"], ["0.5", " 0.5 "], [], []),            # surrounding spaces are not an edit
        (["A1"], ["0.5"], ["A2"], []),                       # a row removed takes its record with it
        (["A1"], [], ["A1"], ["A1"]),                        # no P posted: the record alone
        (["A1"], [], [], []),                                # no P posted and none recorded: the default, untouched
    ], ids=["edited", "edited back", "retyped", "spaces", "row removed", "no P posted", "nothing posted"])
    def test_a_row_is_edited_once_its_p_leaves_the_panels_text(
        self, ids: list[str], probs: list[str], recorded: list[str], expected: list[str],
    ) -> None:
        assert edited_rows(ids, probs, recorded) == expected


class TestTheRegionCarriesIt:
    def test_an_edited_row_is_recorded_in_a_hidden_field_keyed_by_its_id(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        page = _region(client, auth_cookie, adv_id=["A1", "A2"], adv_name=["a", "b"],
                       adv_type=["manoeuvre", "manoeuvre"], adv_prob=["0.5", "0.4"])
        assert _recorded(page) == ["A2"]

    def test_the_record_survives_the_next_change(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        page = _region(client, auth_cookie, adv_id=["A1", "A2"], adv_name=["a", "b"],
                       adv_type=["manoeuvre", "manoeuvre"], adv_prob=["0.5", "0.5"], adv_p_edited=["A2"])
        assert _recorded(page) == ["A2"]

    def test_an_added_row_starts_unedited_and_a_removed_one_drops_out(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        page = _region(client, auth_cookie, adv_id=["A1", "A4"], adv_name=["a", "new"],
                       adv_type=["manoeuvre", "manoeuvre"], adv_prob=["0.3", "0.5"], adv_p_edited=["A1", "A2"])
        assert _recorded(page) == ["A1"]

    @pytest.mark.parametrize("params", [
        {"red_sat": ""}, {"horizon_hours": "nan"}, {"red_sat": "GONE"},
    ], ids=["no red track", "no horizon", "red track not held"])
    def test_the_record_is_carried_whatever_the_region_says(
        self, client: Any, auth_cookie: str, held: Any, params: dict[str, str],  # noqa: F811
    ) -> None:
        page = _region(client, auth_cookie, adv_prob=["0.5"], adv_p_edited=["A1"], **params)
        assert _recorded(page) == ["A1"]

    def test_a_row_id_in_the_record_is_escaped(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        page = _region(client, auth_cookie, adv_id=['"><script>x</script>'], adv_prob=["0.4"])
        assert "<script>x" not in page
        assert _recorded(page) == ["&#34;&gt;&lt;script&gt;x&lt;/script&gt;"]

    def test_the_record_is_inside_the_evaluate_form(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        """The region the record lives in sits inside the form, so Evaluate sends it; it sets its own target,
        indicator and disabled element (tests/integration/test_decision_prior_route.py)."""
        resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})
        *around, (_, region) = _lineage(resp.text, "adv-priors")
        assert any(tag == "form" for tag, _ in around)
        assert (region["hx-target"], region["hx-indicator"], region["hx-disabled-elt"]) == ("this", "this", "this")


class TestThePanelGivesEveryRowTheUneditedText:
    def test_every_p_the_panel_renders_or_adds_starts_at_the_unedited_text(self, client: Any, auth_cookie: str) -> None:
        """Server rows and rows the Add button builds start where the record compares from, so none reads as
        edited before the operator touches it; rows opened from the sweep are checked beside that route
        (tests/integration/test_decision_from_sweep_route.py)."""
        page = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie}).text
        values = re.findall(r'name="adv_prob" value="([^"]*)"', page)
        assert len(values) >= 2   # a server row and the Add button's row
        assert set(values) == {UNEDITED_PROBABILITY}


class TestEvaluateReadsTheRecord:
    def test_a_default_p_never_edited_is_untouched(self, client: Any, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _form(adv_prob=["0.5"], strategy="expected_value"))
        assert resp.status_code == 200 and "error-msg" not in resp.text
        text = _text(resp.text)
        assert _GUIDANCE in text
        assert DEFAULT_P_VALUES in text
        assert OWN_VALUES not in text

    def test_a_deliberate_half_is_the_operators_own(self, client: Any, auth_cookie: str) -> None:
        """SPC-183: recorded as edited, a P of 0.5 is not the untouched default, so no guidance is given."""
        resp = _evaluate(client, auth_cookie, _form(adv_prob=["0.5"], adv_p_edited=["A1"], strategy="expected_value"))
        assert resp.status_code == 200 and "error-msg" not in resp.text
        text = _text(resp.text)
        assert _GUIDANCE not in text
        assert OWN_VALUES in text

    def test_an_edit_not_yet_recorded_still_counts(self, client: Any, auth_cookie: str) -> None:
        """Changed just before Evaluate, the region's answer may not have landed: the P posted is read too."""
        resp = _evaluate(client, auth_cookie, _form(adv_prob=["0.50"], strategy="expected_value"))
        assert resp.status_code == 200 and "error-msg" not in resp.text
        assert _GUIDANCE not in _text(resp.text)

    def test_an_applied_suggestion_counts_as_edited(self, client: Any, auth_cookie: str, held: Any) -> None:  # noqa: F811
        """A row left at 0.5 whose P a ticked NOTSO suggestion replaces is edited by that tick."""
        resp = _evaluate(client, auth_cookie, _form(
            red_sat="RX", adv_prob=["0.5"], adv_prior=[f"A1|{_P}|"], strategy="expected_value",
        ))
        assert resp.status_code == 200 and "error-msg" not in resp.text
        text = _text(resp.text)
        assert f"P={_P} · Conf=0.7" in text
        assert _GUIDANCE not in text
