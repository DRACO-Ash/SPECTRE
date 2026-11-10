"""Every rule's pick on the results page, the deployment's primary rule, and both on the record (SPC-194, F-03).

The results show the picks of minimax, minimin and expected value side by side, each with its meaning, and a line
saying whether they agree; the headline is the primary rule's pick, SPECTRE_PRIMARY_RULE, which the panel's selector
defaults to; a chosen rule other than the primary is shown beside it. The record keeps the primary rule and whether
the chosen rule differed.
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spectre.config import settings as settings_module
from spectre.domain.decision import Scenario, ScenarioResult, SelectorStrategy
from spectre.domain.rule_comparison import MEANINGS, PICKS_BASIS, compare_rules
from spectre.web.decision_job import evaluated_line
from spectre.web.decision_record import Operator, listed
from spectre.web.models import DecisionRecord
from spectre.web.routes import decision as decision_routes
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_record_route import _records, _sign_in
from tests.integration.test_xss_escaping import _assert_inert
from tests.unit.test_decision_rule_comparison import _ONE_WAY, _THREE_WAYS, _scored, _tree_result

_ENV = "SPECTRE_PRIMARY_RULE"


def _flat(text: str) -> str:
    """The page's text with its tags dropped, entities read and white space collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


@pytest.fixture
def scored(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[float, ...], ...]]:
    """The route evaluates for real, then its matrix's scores are set to the scores the test pushes."""
    pushed: list[tuple[tuple[float, ...], ...]] = []

    def evaluate(scenario: Scenario, strategy: SelectorStrategy = SelectorStrategy.MINIMAX) -> ScenarioResult:
        return _scored(pushed[-1], strategy)

    monkeypatch.setattr(decision_routes, "evaluate_tree", evaluate)
    return pushed


@pytest.fixture(autouse=True)
def _primary_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    settings_module.primary_rule_of.cache_clear()


class TestTheResultsShowEveryRule:
    def test_three_picks_each_with_its_meaning_and_what_they_rest_on(
        self, client: TestClient, scored: list[Any],
    ) -> None:
        scored.append(_THREE_WAYS)
        cookie = _sign_in(client, "rules_three")
        text = _flat(_evaluate(client, cookie, _form()).text)
        for words, pick in (("Minimax", "Avoid (R2)"), ("Minimin", "Hold (R1)"), ("Expected value", "Retask (R3)")):
            assert f"{words}: {pick}" in text
        for meaning in MEANINGS.values():
            assert meaning in text
        assert PICKS_BASIS in text

    def test_a_disagreement_is_said_and_names_the_picks(self, client: TestClient, scored: list[Any]) -> None:
        scored.append(_THREE_WAYS)
        cookie = _sign_in(client, "rules_disagree")
        text = _flat(_evaluate(client, cookie, _form()).text)
        assert ("The rules disagree: minimax picks Avoid (R2); minimin picks Hold (R1); expected value picks "
                "Retask (R3).") in text

    def test_agreement_is_said(self, client: TestClient, scored: list[Any]) -> None:
        scored.append(_ONE_WAY)
        cookie = _sign_in(client, "rules_agree")
        text = _flat(_evaluate(client, cookie, _form()).text)
        assert "All three rules agree: each picks Avoid (R2)." in text
        assert "The rules disagree" not in text

    def test_a_real_evaluation_shows_its_own_three_picks(self, client: TestClient) -> None:
        cookie = _sign_in(client, "rules_real")
        text = _flat(_evaluate(client, cookie, _form()).text)
        (row,) = _records(client, "rules_real")
        for words, name, rid in (("Minimax", row.minimax_name, row.minimax_id),
                                 ("Minimin", row.minimin_name, row.minimin_id),
                                 ("Expected value", row.expected_value_name, row.expected_value_id)):
            assert f"{words}: {name} ({rid})" in text
        assert "All three rules agree" in text or "The rules disagree" in text


class TestThePrimaryRule:
    def test_the_headline_is_the_primary_rules_pick_and_a_chosen_rule_is_shown_beside_it(
        self, client: TestClient, scored: list[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scored.append(_THREE_WAYS)
        monkeypatch.setenv(_ENV, "minimax")
        cookie = _sign_in(client, "rules_chosen")
        page = _evaluate(client, cookie, _form(strategy="expected_value")).text
        headline = re.search(r'class="headline-pick"[^>]*>\s*([^<]+?)\s*<', page)
        assert headline is not None and headline.group(1) == "Avoid"
        assert ("This deployment's primary rule is minimax: it picks Avoid (R2). You chose expected value: it picks "
                "Retask (R3). The recommendation shown is the primary rule's pick.") in _flat(page)

    def test_a_primary_rule_set_for_the_deployment_is_the_headline(
        self, client: TestClient, scored: list[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scored.append(_THREE_WAYS)
        monkeypatch.setenv(_ENV, "minimin")
        cookie = _sign_in(client, "rules_minimin")
        page = _evaluate(client, cookie, _form(strategy="minimin")).text
        headline = re.search(r'class="headline-pick"[^>]*>\s*([^<]+?)\s*<', page)
        assert headline is not None and headline.group(1) == "Hold"
        assert ("This deployment's primary rule is minimin, the rule chosen: the recommendation is its pick, "
                "Hold (R1).") in _flat(page)

    @pytest.mark.parametrize(("setting", "selected"), [
        (None, "minimax"), ("minimax", "minimax"), ("minimin", "minimin"), ("expected_value", "expected_value"),
        ("nonsense", "minimax"),
    ])
    def test_the_panels_selector_defaults_to_the_primary_rule(
        self, client: TestClient, auth_cookie: str, monkeypatch: pytest.MonkeyPatch, setting: str | None,
        selected: str,
    ) -> None:
        if setting is not None:
            monkeypatch.setenv(_ENV, setting)
        page = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie}).text
        strategy = page[page.index('name="strategy"'):page.index("</select>", page.index('name="strategy"'))]
        assert re.findall(r'<option value="(\w+)" selected', strategy) == [selected]
        assert f"primary rule is {selected.replace('_', ' ')}" in _flat(page)

    def test_an_unknown_strategy_posted_falls_back_to_the_primary_rule(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(_ENV, "minimin")
        cookie = _sign_in(client, "rules_fallback")
        _evaluate(client, cookie, _form(strategy="maximin"))
        (row,) = _records(client, "rules_fallback")
        assert (row.rule, row.primary_rule, row.rule_differed) == ("minimin", "minimin", False)


class TestTheRecordKeepsThePrimaryRule:
    def test_the_primary_rule_and_that_the_chosen_rule_differed(
        self, client: TestClient, scored: list[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scored.append(_THREE_WAYS)
        monkeypatch.setenv(_ENV, "minimax")
        cookie = _sign_in(client, "rules_record")
        _evaluate(client, cookie, _form(strategy="expected_value"))
        _evaluate(client, cookie, _form(strategy="minimax"))
        first, second = _records(client, "rules_record")
        assert (first.rule, first.primary_rule, first.rule_differed) == ("expected_value", "minimax", True)
        assert (second.rule, second.primary_rule, second.rule_differed) == ("minimax", "minimax", False)

    def test_the_records_page_says_the_primary_rule_and_its_pick(
        self, client: TestClient, scored: list[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scored.append(_THREE_WAYS)
        monkeypatch.setenv(_ENV, "minimax")
        cookie = _sign_in(client, "rules_listed")
        _evaluate(client, cookie, _form(strategy="minimin"))
        text = _flat(client.get("/plan/decision/records", cookies={"spectre_session": cookie}).text)
        assert ("Primary rule: minimax; the recommendation shown was its pick, Avoid (R2). The rule used, minimin, "
                "differed from it.") in text
        assert "Rule used: minimin, picking Hold (R1)." in text
        assert "Recommended:" not in text

    def test_a_record_from_before_the_primary_rule_says_none_was_recorded(self) -> None:
        row = DecisionRecord(
            id=1, created_at=None, user_id=1, username="old", scenario_name="Old", rule="minimax",
            recommended_id="R1", recommended_name="Hold", minimax_id="R1", minimax_name="Hold", minimin_id="R1",
            minimin_name="Hold", expected_value_id="R1", expected_value_name="Hold", tree_recommendation="[]",
            code_version="0.27.0", calibration_source="", input_hashes="[]",
            responses='[{"id": "R1", "name": "Hold"}]', turns=1, keep_out_km=10.0, primary_rule="",
            rule_differed=None,
        )
        assert listed(row, Operator(1, "old")).primary == (
            "Primary rule: not recorded; this record was written by a version of SPECTRE that did not record one."
        )
        assert listed(row, Operator(1, "old")).used == "Rule used: minimax. Recommended: Hold (R1)."

    def test_hostile_names_in_the_rule_lines_are_inert(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cookie = _sign_in(client, "rules_xss")
        payload = "<script>alert(1)</script>"
        resp = _evaluate(client, cookie, _form(fr_name=[payload], strategy="minimin"))
        _assert_inert(resp)
        assert "&lt;script&gt;alert(1)&lt;/script&gt; (F1)" in resp.text
        listed_page = client.get("/plan/decision/records", cookies={"spectre_session": cookie})
        _assert_inert(listed_page)



def _style_of(page: str, cls: str) -> str:
    found = re.search(rf'class="{cls}"[^>]*style="([^"]*)"', page)
    assert found is not None, cls
    return found.group(1)


def _rem(style: str) -> float:
    size = re.search(r"font-size:\s*([\d.]+)rem", style)
    assert size is not None, style
    return float(size.group(1))


class TestHowTheLinesRead:
    def test_no_line_under_the_headline_is_set_larger_than_it(
        self, client: TestClient, scored: list[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The theme sets every p and li to the body size, so each line under the headline sets its own, smaller."""
        scored.append(_THREE_WAYS)
        monkeypatch.setenv(_ENV, "minimin")
        cookie = _sign_in(client, "rules_sizes")
        page = _evaluate(client, cookie, _form(strategy="minimax")).text
        headline = _rem(_style_of(page, "headline-pick"))
        block = page[page.index('class="rule-picks"'):page.index("</div>", page.index('class="rule-picks"'))]
        lines = re.findall(r"<(?:p|li)\b[^>]*>", block)
        assert len(lines) >= 6
        for tag in lines:
            style = re.search(r'style="([^"]*)"', tag)
            assert style is not None, tag
            assert _rem(style.group(1)) < headline, tag
        assert _rem(_style_of(page, "star-legend")) < headline

    def test_the_star_is_said_to_mark_the_rule_chosen_beside_the_primary(
        self, client: TestClient, scored: list[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scored.append(_THREE_WAYS)
        monkeypatch.setenv(_ENV, "minimin")
        cookie = _sign_in(client, "rules_star")
        text = _flat(_evaluate(client, cookie, _form(strategy="minimax")).text)
        assert ("\u2605 and the blue highlights mark Avoid (R2), the pick of minimax, the rule chosen; the "
                "recommendation above is Hold (R1), the pick of minimin, the deployment's primary rule.") in text

    @pytest.mark.parametrize(("p", "agree", "colour"), [((0.25, 0.75), "yes", "var(--text-primary)"),
                                                       ((0.0, 0.0), "no", "var(--gold)")])
    def test_a_disagreement_on_the_tree_is_flagged_as_on_the_matrix(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, p: tuple[float, float], agree: str, colour: str,
    ) -> None:
        def evaluate(scenario: Scenario, strategy: SelectorStrategy = SelectorStrategy.MINIMAX) -> ScenarioResult:
            return _tree_result(strategy, p=p)

        expected = compare_rules(_tree_result(p=p), SelectorStrategy.MINIMAX)
        assert expected.tree_agree is (agree == "yes")
        monkeypatch.setattr(decision_routes, "evaluate_tree", evaluate)
        # The hand-built tree has no orbits for the tree view to draw; the line under test sits above it.
        monkeypatch.setattr(decision_routes, "tree_view", lambda _result: None)
        cookie = _sign_in(client, f"rules_tree_{agree}")
        page = _evaluate(client, cookie, _form()).text
        tag = re.search(r'<p class="tree-rules-agreement"[^>]*>', page)
        assert tag is not None
        assert f'data-agree="{agree}"' in tag.group(0)
        assert f"color:{colour}" in tag.group(0)


class TestEveryRowAtPZero:
    """A real evaluation with its only row at P 0: expected value has no weight to pick on, and says so."""

    def test_the_results_say_expected_value_has_no_pick(self, client: TestClient) -> None:
        cookie = _sign_in(client, "rules_p0")
        text = _flat(_evaluate(client, cookie, _form(adv_prob=["0"])).text)
        assert "Expected value: no pick, since every row has P 0" in text
        assert ("The rules disagree: minimax and minimin pick Hold (F1); expected value has no pick, since every row "
                "has P 0.") in text
        (row,) = _records(client, "rules_p0")
        assert (row.expected_value_id, row.expected_value_name) == ("", "")
        page = _flat(client.get("/plan/decision/records", cookies={"spectre_session": cookie}).text)
        assert "expected value picks nothing, since every row had P 0." in page

    def test_a_primary_rule_with_no_pick_shows_no_recommendation(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(_ENV, "expected_value")
        cookie = _sign_in(client, "rules_p0_primary")
        page = _evaluate(client, cookie, _form(adv_prob=["0"], strategy="expected_value")).text
        headline = re.search(r'class="headline-pick"[^>]*>\s*([^<]+?)\s*<', page)
        assert headline is not None and headline.group(1) == "No recommendation"
        assert ("This deployment's primary rule is expected value, the rule chosen: it has no pick, since every row "
                "has P 0, so no recommendation is shown.") in _flat(page)
        (row,) = _records(client, "rules_p0_primary")
        assert (row.recommended_id, row.recommended_name) == ("", "")
        listed_page = _flat(client.get("/plan/decision/records", cookies={"spectre_session": cookie}).text)
        assert "Rule used: expected value, with no pick, since every row had P 0." in listed_page
        assert ("Primary rule: expected value, the rule used; it had no pick, since every row had P 0, so no "
                "recommendation was shown.") in listed_page


class TestTheSessionLog:
    def test_it_names_the_primary_rules_pick_and_the_rule_chosen_beside_it(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(_ENV, "minimax")
        result = _scored(_THREE_WAYS, SelectorStrategy.MINIMIN)
        line = evaluated_line(result.scenario, result)
        assert ("Modelled recommendation: Avoid (R2), the pick of minimax, the primary rule; the rule chosen, "
                "minimin, picks Hold (R1).") in line

    def test_the_primary_rule_chosen_is_named_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, "minimin")
        result = _scored(_THREE_WAYS, SelectorStrategy.MINIMIN)
        line = evaluated_line(result.scenario, result)
        assert "Modelled recommendation: Hold (R1), the pick of minimin, the primary rule and the rule chosen." in line
