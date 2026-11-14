"""The weight stability beside the recommendation, on the results and on the record (SPC-205, evaluation F-16).

Beside the headline the results say, in words, the overall smallest change of one weight that changes the
recommendation and what it makes it, with a details element listing every weight. A rule chosen other than the
primary has its pick's stability beside it. A game tree's picks are not covered, and one line says so. The record
keeps the recommendation's line as the results showed it, in a column of its own that init_db adds to an older
database in place; the Decision records page shows it, and says when a record holds none.
"""

from __future__ import annotations

import dataclasses
import html
import re

import pytest
from fastapi.testclient import TestClient

from spectre.config import settings as settings_module
from spectre.domain.decision import Scenario, ScenarioResult, SelectorStrategy
from spectre.domain.rule_comparison import compare_rules
from spectre.domain.weight_stability import STABILITY_BASIS, STABILITY_MARK, TREE_NOT_COVERED, weight_stability
from spectre.web.decision_record import NO_STABILITY, Operator, listed
from spectre.web.routes import decision as decision_routes
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_record_route import _records, _sign_in
from tests.unit.test_decision_rule_comparison import _tree_result
from tests.unit.test_weight_stability import _X, _Y, _result

_ENV = "SPECTRE_PRIMARY_RULE"
_MINIMAX, _EV = SelectorStrategy.MINIMAX, SelectorStrategy.EXPECTED_VALUE


def _flat(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


@pytest.fixture(autouse=True)
def _primary_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    settings_module.primary_rule_of.cache_clear()


@pytest.fixture
def hand_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route evaluates the hand-built matrix of tests/unit/test_weight_stability.py under the rule posted."""
    def evaluate(_scenario: Scenario, strategy: SelectorStrategy = _MINIMAX) -> ScenarioResult:
        return _result((_X, _Y), strategy)

    monkeypatch.setattr(decision_routes, "evaluate_tree", evaluate)


@pytest.fixture
def two_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hand-built matrix asked for over 2 turns, its tree refused before it ran, as an unbound scenario's is."""
    def evaluate(_scenario: Scenario, strategy: SelectorStrategy = _MINIMAX) -> ScenarioResult:
        result = _result((_X, _Y), strategy)
        return dataclasses.replace(result, scenario=dataclasses.replace(result.scenario, turns=2))

    monkeypatch.setattr(decision_routes, "evaluate_tree", evaluate)


class TestTheComparisonCarriesIt:
    def test_the_recommendations_stability_is_the_domains_own(self) -> None:
        result = _result((_X, _Y), _MINIMAX)
        compared = compare_rules(result, _MINIMAX)
        assert compared.stability == weight_stability(result, _MINIMAX)
        assert compared.chosen_stability is None
        assert compared.stability_basis == STABILITY_BASIS
        assert compared.tree_not_covered is None

    def test_a_chosen_rule_other_than_the_primary_has_its_own_beside_it(self) -> None:
        result = _result((_X, _Y), _EV)
        compared = compare_rules(result, _MINIMAX)
        assert compared.chosen_stability is not None
        assert compared.chosen_stability.rule is _EV
        assert compared.chosen_stability.line == (
            "Expected value's pick, the rule chosen, holds unless a weight moves by more than 0.083: custody's weight "
            "from 0.250 past 0.334 makes it Resp Y (Y)."
        )

    def test_a_tree_says_its_picks_are_not_covered(self) -> None:
        assert compare_rules(_tree_result(), _MINIMAX).tree_not_covered == TREE_NOT_COVERED


@pytest.mark.usefixtures("hand_built")
class TestTheResultsPage:
    def test_the_line_sits_beside_the_recommendation_with_every_weight_in_a_details_element(
        self, client: TestClient,
    ) -> None:
        cookie = _sign_in(client, "stability_page")
        page = _evaluate(client, cookie, _form()).text
        stability = weight_stability(_result((_X, _Y), _MINIMAX), _MINIMAX)
        assert stability.line.startswith("The recommendation holds unless a weight moves by ")
        headline = page.index('class="headline-pick"')
        line = page.index('class="weight-stability"')
        assert headline < line < page.index('class="rule-picks"')
        details = page[page.index("<details", line):page.index("</details>", line)]
        assert "<summary" in details and "Every weight" in details
        text = _flat(page)
        assert f"{stability.line} (lookup)" in text   # every figure states its basis, beside it
        stated = page[line:page.index("</p>", line)]
        assert 'data-basis="lookup"' in stated and f'title="{STABILITY_MARK.note}"' in stated
        for weight in stability.weight_lines:
            assert weight in _flat(details)
        assert STABILITY_BASIS in text
        assert TREE_NOT_COVERED not in text

    def test_a_chosen_rule_other_than_the_primary_shows_its_own(self, client: TestClient) -> None:
        cookie = _sign_in(client, "stability_chosen")
        text = _flat(_evaluate(client, cookie, _form(strategy="expected_value")).text)
        assert "Expected value's pick, the rule chosen, holds unless a weight moves by more than 0.083" in text
        assert weight_stability(_result((_X, _Y), _MINIMAX), _MINIMAX).line in text

    def test_the_record_keeps_the_line_and_the_records_page_shows_it(self, client: TestClient) -> None:
        cookie = _sign_in(client, "stability_record")
        _evaluate(client, cookie, _form())
        (row,) = _records(client, "stability_record")
        line = weight_stability(_result((_X, _Y), _MINIMAX), _MINIMAX).line
        assert row.weight_stability == line
        page = client.get("/plan/decision/records", cookies={"spectre_session": cookie}).text
        assert f"Weight stability: {line}" in _flat(page)

    def test_a_record_holding_none_says_so(self, client: TestClient) -> None:
        cookie = _sign_in(client, "stability_none")
        _evaluate(client, cookie, _form())
        (row,) = _records(client, "stability_none")
        row.weight_stability = None
        assert listed(row, Operator(0, "stability_none")).stability == NO_STABILITY
        assert NO_STABILITY == (
            "Weight stability: not recorded; this record was written by a version of SPECTRE that did not record it."
        )


@pytest.mark.usefixtures("two_turns")
def test_a_tree_result_says_its_picks_are_not_covered(client: TestClient) -> None:
    cookie = _sign_in(client, "stability_tree")
    text = _flat(_evaluate(client, cookie, _form()).text)
    assert TREE_NOT_COVERED in text
    (row,) = _records(client, "stability_tree")
    assert row.weight_stability is not None
    records = _flat(client.get("/plan/decision/records", cookies={"spectre_session": cookie}).text)
    assert f"Weight stability: {row.weight_stability} {TREE_NOT_COVERED}" in records


def test_the_records_page_says_a_tree_is_not_covered_only_for_a_tree_record_holding_a_line(
    client: TestClient,
) -> None:
    cookie = _sign_in(client, "stability_one_turn")
    _evaluate(client, cookie, _form())
    (row,) = _records(client, "stability_one_turn")
    viewer = Operator(0, "stability_one_turn")
    assert listed(row, viewer).tree_not_covered is None
    row.turns = 2
    assert listed(row, viewer).tree_not_covered == TREE_NOT_COVERED
    row.weight_stability = None
    assert listed(row, viewer).tree_not_covered is None


def test_a_real_evaluation_records_what_its_page_showed(client: TestClient) -> None:
    cookie = _sign_in(client, "stability_real")
    text = _flat(_evaluate(client, cookie, _form()).text)
    (row,) = _records(client, "stability_real")
    assert row.weight_stability is not None and row.weight_stability in text
