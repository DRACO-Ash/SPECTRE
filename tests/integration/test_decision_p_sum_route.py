"""The panel refuses rows whose P sum above 1, and the results show the remainder of P and each row's share (SPC-203).

P is the chance of each adversary action, the actions mutually exclusive, so the rows' P sum to at most 1, within a
rounding tolerance of 1e-9. Evaluate refuses a sum above 1 with a sentence naming the sum and saying the rows must be
mutually exclusive, before anything runs; three new rows at the panel's default P of 0.5 sum to 1.5 and are refused
until the operator sets P. A NOTSO suggestion applied at Evaluate replaces its row's P, so the sum is read with the
suggestions applied, and a sum above 1 they make is refused naming the rows that carry them. Below 1, the results
show the engine's remainder row, labelled as the engine's and not the operator's, and every row's share of expected
value beside its P. The route's clock is fixed and UDL is not connected, so no test reaches the network.
"""

from __future__ import annotations

import html
import re
from typing import Any

from spectre.domain.decision import ADVERSARY_FIELDS_NOTE, REMAINDER_NAME
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_prior_route import _P, held  # noqa: F401
from tests.unit._i13 import i13_problems

_THREE = {
    "adv_id": ["A1", "A2", "A3"], "adv_name": ["Approach", "Hold course", "Retask"],
    "adv_type": ["manoeuvre", "no_action", "sensor_retask"], "adv_conf": ["0.7", "0.7", "0.7"],
}


def _text(page: str) -> str:
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", page).split()))


def _page(client: Any, cookie: str, **form: Any) -> str:
    resp = _evaluate(client, cookie, _form(**form))
    assert resp.status_code == 200
    return resp.text


class TestASumAbove1IsRefusedAtThePanel:
    def test_three_rows_at_the_panels_default_are_refused_naming_the_sum(self, client: Any, auth_cookie: str) -> None:
        page = _page(client, auth_cookie, **_THREE, adv_prob=["0.5", "0.5", "0.5"])
        assert 'class="error-msg"' in page
        text = _text(page)
        assert "Your rows' P sum to 1.5, above 1." in text
        assert "the rows must be mutually exclusive, so their P sum to at most 1" in text
        assert "Ranked Responses" not in text

    def test_the_sentence_passes_the_house_checks(self, client: Any, auth_cookie: str) -> None:
        text = _text(_page(client, auth_cookie, **_THREE, adv_prob=["0.5", "0.4", "0.2"]))
        assert "Your rows' P sum to 1.1, above 1." in text
        assert [s for s in text.split(". ") if i13_problems(s)] == []

    def test_a_sum_of_exactly_1_evaluates_with_no_remainder_row(self, client: Any, auth_cookie: str) -> None:
        page = _page(client, auth_cookie, **_THREE, adv_prob=["0.1", "0.2", "0.7"])
        assert "error-msg" not in page
        assert REMAINDER_NAME not in _text(page)


class TestTheRemainderOnTheResults:
    def test_it_is_a_row_of_its_own_labelled_as_the_engines(self, client: Any, auth_cookie: str) -> None:
        page = _page(client, auth_cookie, **_THREE, adv_prob=["0.1", "0.2", "0.3"])
        assert "error-msg" not in page
        text = _text(page)
        assert f"{REMAINDER_NAME}: the engine's remainder, not your row" in text
        assert "This row is the engine's remainder, not your row: its P, 0.4, is 1 less the sum of your rows' P, 0.6" \
            in text
        assert "Conf: none" in text

    def test_every_row_shows_its_share_of_expected_value_beside_its_p(self, client: Any, auth_cookie: str) -> None:
        text = _text(_page(client, auth_cookie, **_THREE, adv_prob=["0.1", "0.2", "0.3"]))
        for share in ("0.1", "0.2", "0.3", "0.4"):
            assert re.search(rf"P={share} \((judgement|lookup)\) · Share={share} \((judgement|lookup)\)", text), share

    def test_the_panel_says_the_rows_must_be_mutually_exclusive(self, client: Any, auth_cookie: str) -> None:
        resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 200
        assert " ".join(ADVERSARY_FIELDS_NOTE.split()) in html.unescape(" ".join(resp.text.split()))
        assert "the rows must be mutually exclusive, so their P sum to at most 1" in ADVERSARY_FIELDS_NOTE


class TestWithNotsoSuggestionsApplied:
    def test_a_sum_above_1_they_make_is_refused_naming_the_rows_that_carry_them(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        """Row 1 typed at 0.6 takes the suggestion, 0.07; row 2 typed at 0.95 makes the sum 1.02 with it."""
        page = _page(client, auth_cookie, red_sat="RX", adv_id=["A1", "A2"], adv_name=["Approach", "Drift"],
                     adv_type=["manoeuvre", "posture_change"], adv_prob=["0.6", "0.95"], adv_conf=["0.7", "0.7"],
                     adv_prior=[f"A1|{_P}|"])
        assert 'class="error-msg"' in page
        assert "With the NOTSO suggestion applied to row 1, your rows' P sum to 1.02, above 1." in _text(page)

    def test_the_sum_is_read_with_the_suggestions_applied(
        self, client: Any, auth_cookie: str, held: Any,  # noqa: F811
    ) -> None:
        """Typed, rows 1 and 2 sum to 1.2; with row 1's suggestion of 0.07 applied they sum to 0.67, which is taken."""
        page = _page(client, auth_cookie, red_sat="RX", adv_id=["A1", "A2"], adv_name=["Approach", "Drift"],
                     adv_type=["manoeuvre", "posture_change"], adv_prob=["0.6", "0.6"], adv_conf=["0.7", "0.7"],
                     adv_prior=[f"A1|{_P}|"])
        assert "error-msg" not in page
        assert f"{REMAINDER_NAME}: the engine's remainder, not your row" in _text(page)
