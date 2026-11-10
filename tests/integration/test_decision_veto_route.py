"""Not permitted on the panel, the results, the record and the records page (SPC-195, evaluation F-04, gate G4).

Each friendly response row carries a labelled "Not permitted" checkbox and a labelled reason, required when the box
is ticked and at most 500 characters. A vetoed response is still evaluated and shown, greyed, with "Not permitted:"
and its reason in words beside it in the matrix, the rankings and the tree, and it is never the recommendation.
With every response vetoed nothing is recommended and the page says why. The record keeps which responses were
vetoed and why; the operator may still record a vetoed response as their decision, but only with a rationale, and
the page says it was marked not permitted. The reason is the operator's text and is shown as text everywhere.
"""

from __future__ import annotations

import dataclasses
import html
import json
import re
from typing import Any

from fastapi.testclient import TestClient

from spectre.domain.decision import Scenario, SelectorStrategy
from spectre.domain.decision_tree import evaluate_tree
from tests.integration.test_decision_hypothesis_panel import _panel
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_record_route import _decide, _page, _records, _row, _sign_in
from tests.integration.test_decision_tree_view import _results, _section
from tests.integration.test_form_labels import _unlabelled
from tests.integration.test_xss_escaping import _assert_inert, _assert_not_reflected
from tests.unit.test_decision_tree_select import _still

_REASON = "ROE 4: no burn towards a third party's asset."
_PAYLOAD = "<script>alert('xss')</script>"
_RESPONSE_RELOAD_WORDS = "The response fields do not match the friendly rows; reload the panel."
_TWO = {
    "fr_id": ["F1", "F2"], "fr_name": ["Hold", "Avoid"], "fr_type": ["no_action", "manoeuvre"],
    "fr_cost": ["0.0", "0.3"], "fr_rev": ["1.0", "0.8"], "fr_time": ["0.1", "4"],
}


def _flat(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _vetoed_form(ticked: list[str], reasons: list[str], **overrides: Any) -> dict[str, Any]:
    return _form(**{**_TWO, "fr_vetoed": ticked, "fr_veto_reason": reasons, **overrides})


def _best(client: TestClient, cookie: str, username: str) -> str:
    """The id every rule picks for _TWO with nothing vetoed, read from the record the evaluation wrote."""
    assert _evaluate(client, cookie, _form(**_TWO)).status_code == 200
    row = _records(client, username)[-1]
    assert row.minimax_id == row.minimin_id == row.expected_value_id
    return row.minimax_id


def _between(page: str, start: str, end: str) -> str:
    first = page.index(start)
    return page[first:page.index(end, first)]


class TestThePanel:
    def test_each_response_row_has_a_labelled_checkbox_and_reason(self, client: TestClient, auth_cookie: str) -> None:
        page = _panel(client, auth_cookie)
        block = _between(page, '<div class="fr-veto"', "</div>")
        assert re.search(r'<input type="checkbox" name="fr_vetoed" value="R1"', block)
        assert re.search(r'<input type="text" name="fr_veto_reason" maxlength="500"', block)
        assert "Not permitted" in _flat(block)
        assert "Reason not permitted" in _flat(block)
        assert _unlabelled(block) == []

    def test_a_row_added_on_the_panel_carries_the_same_fields_keyed_by_its_own_id(
        self, client: TestClient, auth_cookie: str,
    ) -> None:
        builder = _between(_panel(client, auth_cookie), "function addFrRow()", "document.getElementById('fr-rows')")
        assert 'name="fr_vetoed" value="R${c}"' in builder
        assert 'name="fr_veto_reason" maxlength="500"' in builder
        assert _unlabelled(_between(builder, '<div class="fr-veto"', "</div>")) == []

    def test_the_checkbox_keeps_its_own_width_so_its_words_stay_beside_it(
        self, client: TestClient, auth_cookie: str,
    ) -> None:
        """The stylesheet sets every input to the full width of its box; a checkbox stretched so pushes its label's
        words out under the reason beside it. Both the fixed row and an added row set the box's own width."""
        page = _panel(client, auth_cookie)
        fixed = _between(page, '<div class="fr-veto"', "</div>")
        added = _between(_between(page, "function addFrRow()", "document.getElementById('fr-rows')"),
                         '<div class="fr-veto"', "</div>")
        for block in (fixed, added):
            box = re.search(r'<input type="checkbox" name="fr_vetoed"[^>]*>', block)
            assert box is not None
            assert re.search(r'style="[^"]*\bwidth:auto\b', box.group(0))

    def test_it_adds_no_handler_attribute(self, client: TestClient, auth_cookie: str) -> None:
        block = _between(_panel(client, auth_cookie), '<div class="fr-veto"', "</div>")
        assert not re.search(r"\son[a-z]+=", block)


class TestTheReasonIsChecked:
    def test_a_ticked_box_needs_a_reason(self, client: TestClient, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _vetoed_form(["F2"], ["", "   "]))
        assert "Give the reason response row 2 is not permitted: it is required when Not permitted is ticked." in (
            _flat(resp.text)
        )

    def test_500_characters_are_taken(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_500")
        resp = _evaluate(client, cookie, _vetoed_form(["F2"], ["", "x" * 500]))
        assert "error-msg" not in resp.text
        assert json.loads(_records(client, "veto_500")[-1].responses)[1]["not_permitted"] == "x" * 500

    def test_501_are_refused_and_nothing_recorded(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_501")
        resp = _evaluate(client, cookie, _vetoed_form(["F2"], ["", "x" * 501]))
        assert "The reason in response row 2 is at most 500 characters; this one is 501." in _flat(resp.text)
        assert _records(client, "veto_501") == []

    def test_the_reason_is_stored_without_its_surrounding_space(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_strip")
        _evaluate(client, cookie, _vetoed_form(["F2"], ["", f"  {_REASON}  "]))
        assert json.loads(_records(client, "veto_strip")[-1].responses)[1]["not_permitted"] == _REASON

    def test_a_reason_with_no_tick_is_refused_not_dropped(self, client: TestClient, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _vetoed_form([], ["", _REASON]))
        assert ("Response row 2 has a reason for being not permitted, but Not permitted is not ticked: tick it, or "
                "clear the reason.") in _flat(resp.text)

    def test_a_reason_holding_a_control_character_is_refused(self, client: TestClient, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _vetoed_form(["F2"], ["", "no\x07burn"]))
        assert "The reason in response row 2 holds a control character; remove it and evaluate again." in (
            _flat(resp.text)
        )

    def test_a_tick_naming_no_row_is_refused(self, client: TestClient, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _vetoed_form(["F9"], ["", _REASON]))
        assert ("Not permitted names a response that is not exactly one row of the form; reload the panel and "
                "enter the responses again.") in _flat(resp.text)

    def test_a_tick_naming_two_rows_is_refused(self, client: TestClient, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _vetoed_form(["F1"], [_REASON, ""], fr_id=["F1", "F1"]))
        assert "Not permitted names a response that is not exactly one row of the form" in _flat(resp.text)

    def test_a_tick_with_no_reasons_posted_is_refused_and_nothing_recorded(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_no_reasons")
        resp = _evaluate(client, cookie, _form(**_TWO, fr_vetoed=["F2"]))
        assert _RESPONSE_RELOAD_WORDS in _flat(resp.text)
        assert _records(client, "veto_no_reasons") == []

    def test_reasons_that_do_not_fit_the_rows_are_refused(self, client: TestClient, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _vetoed_form(["F2"], [_REASON]))
        assert "error-msg" in resp.text
        assert "reload" in _flat(resp.text)

    def test_a_form_without_the_fields_vetoes_nothing(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_absent")
        assert "error-msg" not in _evaluate(client, cookie, _form(**_TWO)).text
        assert all("not_permitted" not in r for r in json.loads(_records(client, "veto_absent")[-1].responses))


class TestTheResults:
    def test_the_best_response_vetoed_is_never_the_recommendation(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_best")
        best = _best(client, cookie, "veto_best")
        other = "F1" if best == "F2" else "F2"
        reasons = [_REASON if fid == best else "" for fid in _TWO["fr_id"]]
        page = _evaluate(client, cookie, _vetoed_form([best], reasons)).text
        names = dict(zip(_TWO["fr_id"], _TWO["fr_name"], strict=True))
        headline = re.search(r'class="headline-pick"[^>]*>\s*([^<]+?)\s*<', page)
        assert headline is not None and headline.group(1) == names[other]
        row = _records(client, "veto_best")[-1]
        assert {row.recommended_id, row.minimax_id, row.minimin_id, row.expected_value_id} == {other}

    def test_it_is_shown_greyed_with_its_reason_in_the_matrix_and_the_rankings(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_shown")
        page = _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON])).text
        said = f"Not permitted: {_REASON}"
        assert said in _flat(_between(page, "<thead>", "</thead>"))
        assert said in _flat(_between(page, "Ranked Responses per Adversary Action", "Phase "))
        assert "Avoid (F2) is marked not permitted" in _flat(page)
        assert page.count('class="not-permitted"') >= 3
        assert 'data-permitted="no"' in page

    def test_each_of_its_matrix_cells_is_greyed(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_cells")
        page = _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON])).text
        cells = re.findall(
            r'<td data-permitted="(yes|no)".*?data-figure="composite_score".*?style="([^"]*)"', page, flags=re.S,
        )
        rows = len(cells) // 2
        assert rows >= 1
        assert [permitted for permitted, _ in cells] == ["yes", "no"] * rows
        for permitted, style in cells:
            assert ("color:var(--text-dim)" in style) is (permitted == "no")

    def test_it_carries_no_rank(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_rank")
        page = _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON])).text
        rankings = _flat(_between(page, "Ranked Responses per Adversary Action", "Phase "))
        assert rankings.index("#1 Hold") < rankings.index("Not ranked Avoid")
        assert "#2" not in rankings

    def test_with_every_response_vetoed_nothing_is_recommended_and_the_page_says_why(
        self, client: TestClient,
    ) -> None:
        cookie = _sign_in(client, "veto_all")
        page = _evaluate(client, cookie, _vetoed_form(["F1", "F2"], [_REASON, _REASON])).text
        headline = re.search(r'class="headline-pick"[^>]*>\s*([^<]+?)\s*<', page)
        assert headline is not None and headline.group(1) == "No recommendation"
        text = _flat(page)
        assert "No rule picks a response: every response is marked not permitted." in text
        assert "it has no pick, since every response is marked not permitted, so no recommendation is shown" in text
        assert "#1" not in _flat(_between(page, "Ranked Responses per Adversary Action", "Phase "))
        assert "★" not in _between(page, "<thead>", "</thead>")
        row = _records(client, "veto_all")[-1]
        assert (row.recommended_id, row.minimax_id, row.minimin_id, row.expected_value_id) == ("", "", "", "")

    def test_the_tree_shows_a_vetoed_responses_branches_with_its_reason(
        self, client: TestClient, auth_cookie: str,
    ) -> None:
        result = evaluate_tree(_veto_hold(_still(), _REASON), SelectorStrategy.MINIMAX)
        tree = _section(_results(client, auth_cookie, result))
        assert f"Not permitted: {_REASON}" in _flat(tree)
        assert "Never picked in any turn, being marked not permitted: Hold." in _flat(tree)
        plan = [m.start() for m in re.finditer("tree-plan", tree)]
        assert plan
        for at in plan:
            summary = tree[tree.rindex("<summary", 0, at):at]
            assert "our Hold" not in summary


def _tree_nodes(tree: str) -> list[tuple[int, str, str]]:
    """Each tree node in page order, as its turn, whether it is permitted, and its summary in words."""
    return [
        (int(turn), permitted, _flat(summary))
        for turn, permitted, summary in re.findall(
            r'<details class="tree-node" data-turn="(\d)" data-permitted="(yes|no)"[^>]*>\s*<summary[^>]*>(.*?)</summary>',
            tree, flags=re.S,
        )
    ]


def _veto_hold(scenario: Scenario, reason: str) -> Scenario:
    hold, *rest = scenario.friendly_responses
    return dataclasses.replace(
        scenario, friendly_responses=[dataclasses.replace(hold, vetoed=True, veto_reason=reason), *rest],
    )


class TestTheTreeGreysEverySequenceAVetoedResponseStarts:
    def test_a_later_branch_under_a_vetoed_branch_is_greyed_and_says_why(
        self, client: TestClient, auth_cookie: str,
    ) -> None:
        result = evaluate_tree(_veto_hold(_still(), _REASON), SelectorStrategy.MINIMAX)
        nodes = _tree_nodes(_section(_results(client, auth_cookie, result)))
        under, first = {"yes": [], "no": []}, "yes"
        for turn, permitted, summary in nodes:
            if turn == 1:
                first = permitted
                assert (permitted == "no") is ("our Hold" in summary)
            else:
                under[first].append((permitted, summary))
        assert under["no"] and under["yes"]
        for permitted, summary in under["no"]:
            assert permitted == "no"
            assert ("Excluded: it follows Hold in turn 1, which is marked not permitted." in summary
                    or f"Not permitted: {_REASON}" in summary)
        assert any("our Hold" not in summary for _, summary in under["no"])
        assert all(permitted == ("no" if "our Hold" in summary else "yes") for permitted, summary in under["yes"])


class TestTheRecord:
    def test_a_vetoed_response_needs_a_rationale_to_be_recorded_as_the_decision(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_decide")
        _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON]))
        record = _records(client, "veto_decide")[-1]
        refused = _decide(client, cookie, record.id, "response-1")
        assert "Give the rationale: it is required when the response chosen was marked not permitted." in (
            _flat(refused.text)
        )
        assert _row(client, record.id).decided_at is None
        taken = _decide(client, cookie, record.id, "response-1", "Legal cleared it at 14:02.")
        assert f"Avoid (F2) was marked not permitted: {_REASON}" in _flat(taken.text)
        row = _row(client, record.id)
        assert (row.decision, row.rationale) == ("response-1", "Legal cleared it at 14:02.")

    def test_a_permitted_response_needs_none(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_permitted")
        _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON]))
        record = _records(client, "veto_permitted")[-1]
        assert "error-msg" not in _decide(client, cookie, record.id, "response-0").text
        assert _row(client, record.id).decision == "response-0"

    def test_the_select_says_which_responses_were_marked_not_permitted(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_select")
        page = _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON])).text
        assert '<option value="response-1">Avoid (F2), marked not permitted</option>' in page
        assert '<option value="response-0">Hold (F1)</option>' in page

    def test_the_records_page_shows_what_was_vetoed_and_a_decision_marked_not_permitted(
        self, client: TestClient,
    ) -> None:
        cookie = _sign_in(client, "veto_page")
        _evaluate(client, cookie, _vetoed_form(["F2"], ["", _REASON]))
        record = _records(client, "veto_page")[-1]
        _decide(client, cookie, record.id, "response-1", "Overruled by the duty officer.")
        text = _flat(_page(client, cookie).text)
        assert f"Not permitted: Avoid (F2): {_REASON}" in text
        assert f"Avoid (F2) was marked not permitted: {_REASON}" in text

    def test_with_every_response_vetoed_the_records_page_says_why_no_rule_picked(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_page_all")
        _evaluate(client, cookie, _vetoed_form(["F1", "F2"], [_REASON, _REASON]))
        text = _flat(_page(client, cookie).text)
        assert "Minimax picks nothing, since every response was marked not permitted" in text
        assert "it had no pick, since every response was marked not permitted, so no recommendation was shown" in text


class TestTheReasonIsEscapedEverywhere:
    def test_on_the_results(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_xss_results")
        resp = _evaluate(client, cookie, _vetoed_form(["F2"], ["", _PAYLOAD]))
        _assert_inert(resp)
        assert resp.text.count("&lt;script&gt;") >= 3

    def test_on_the_records_page_and_the_decision(self, client: TestClient) -> None:
        cookie = _sign_in(client, "veto_xss_page")
        _evaluate(client, cookie, _vetoed_form(["F2"], ["", _PAYLOAD]))
        record = _records(client, "veto_xss_page")[-1]
        _assert_inert(_decide(client, cookie, record.id, "response-1", "Taken all the same."))
        resp = _page(client, cookie)
        _assert_inert(resp)
        assert resp.text.count("&lt;script&gt;") >= 2

    def test_in_the_tree(self, client: TestClient, auth_cookie: str) -> None:
        result = evaluate_tree(_veto_hold(_still(), _PAYLOAD), SelectorStrategy.MINIMAX)
        tree = _section(_results(client, auth_cookie, result))
        assert "<script>alert(" not in tree
        assert "&lt;script&gt;" in tree

    def test_never_echoed_in_a_refusal(self, client: TestClient, auth_cookie: str) -> None:
        _assert_not_reflected(_evaluate(client, auth_cookie, _vetoed_form([], ["", _PAYLOAD])),
                              marker="Response row 2 has a reason for being not permitted")
