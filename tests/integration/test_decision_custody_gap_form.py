"""The decision panel takes each adversary row's custody gap share apart from its confidence (SPC-161).

Each row posts adv_prob, the operator's likelihood that the action happens,
which the expected-value selector weights the row by; adv_conf, how sure the
intelligence behind that likelihood is, which moves no figure; and adv_gap,
the share of the horizon the rule of thumb loses custody for when the row is
a manoeuvre and our response neither manoeuvres nor retasks a sensor. The
panel says so beside the fields, each of the three is labelled, and an out-of-range
share is refused inline like every other field (audit F-164).
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest

from spectre.domain import decision
from tests.integration.test_decision_input_validation import _evaluate, _form

_SCORE = re.compile(r'data-figure="composite_score"[^>]*>\s*([0-9.]+)\s*<', re.S)


def _scores(client: Any, cookie: str, **overrides: Any) -> list[str]:
    """Each cell's score on the page for one manoeuvre row against doing nothing, where custody is lost; the row at
    P 1, certain, so no remainder row joins it (SPC-203)."""
    resp = _evaluate(client, cookie, _form(fr_type=["no_action"], **{"adv_prob": ["1.0"], **overrides}))
    assert resp.status_code == 200
    assert "error-msg" not in resp.text
    scores = _SCORE.findall(resp.text)
    assert scores, "no score on the page"
    return scores


def _panel(client: Any, cookie: str) -> str:
    resp = client.get("/plan/decision/panel", cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


class TestTheEvaluation:
    def test_raising_intelligence_confidence_leaves_every_score_alone(self, client: Any, auth_cookie: str) -> None:
        unsure = _scores(client, auth_cookie, adv_conf=["0.1"], adv_gap=["0.5"])
        assert _scores(client, auth_cookie, adv_conf=["0.9"], adv_gap=["0.5"]) == unsure

    def test_the_posted_share_sets_the_gap(self, client: Any, auth_cookie: str) -> None:
        """0.35 x the share + 0.25 x ln 250 / ln 5,000 + 0.10 x (4/72) + 0.10 x (1 - 0.8): the 200 km miss in orders
        of magnitude from the default 10 km keep-out (SPC-191), 0.25 x 0.648272 = 0.162068, so 0.187624 and 0.537624.
        """
        assert _scores(client, auth_cookie, adv_gap=["0.0"]) == ["0.188"]
        assert _scores(client, auth_cookie, adv_gap=["1.0"]) == ["0.538"]

    @pytest.mark.parametrize("confidence", ["0.13", "0.9"])
    def test_the_posted_confidence_is_recorded_on_the_row(
        self, client: Any, auth_cookie: str, confidence: str,
    ) -> None:
        """Conf moves no figure, so the row is the only place the operator sees it was taken."""
        resp = _evaluate(client, auth_cookie, _form(adv_conf=[confidence]))
        assert resp.status_code == 200
        assert "error-msg" not in resp.text
        assert f"Conf={confidence}" in resp.text

    def test_a_form_without_the_share_takes_the_default(self, client: Any, auth_cookie: str) -> None:
        default = _scores(client, auth_cookie, adv_gap=[str(decision.DEFAULT_CUSTODY_GAP_FRACTION)])
        assert _scores(client, auth_cookie) == default

    @pytest.mark.parametrize("share", ["-0.1", "1.5", "nan", ""])
    def test_an_out_of_range_share_is_refused_inline(self, client: Any, auth_cookie: str, share: str) -> None:
        resp = _evaluate(client, auth_cookie, _form(adv_gap=[share]))
        assert resp.status_code == 200
        assert "error-msg" in resp.text
        assert "custody gap share in row 1" in resp.text.lower()


class TestThePanel:
    def test_the_panel_says_what_each_field_means(self, client: Any, auth_cookie: str) -> None:
        text = " ".join(html.unescape(_panel(client, auth_cookie)).split())
        assert " ".join(decision.ADVERSARY_FIELDS_NOTE.split()) in text
        for meaning in ("expected-value", "moves no figure", "share of the horizon"):
            assert meaning in decision.ADVERSARY_FIELDS_NOTE

    def test_each_row_posts_a_labelled_share_at_the_default(self, client: Any, auth_cookie: str) -> None:
        page = _panel(client, auth_cookie)
        first = page[page.index('<div class="adv-row"'):page.index('onclick="addAdvRow()"')]
        builder = page[page.index("function addAdvRow()"):page.index("function addFrRow()")]
        for row in (first, builder):
            gap = re.search(r'<input[^>]*name="adv_gap"[^>]*>', row)
            assert gap is not None
            for attr in (f'value="{decision.DEFAULT_CUSTODY_GAP_FRACTION}"', 'min="0"', 'max="1"'):
                assert attr in gap.group(0)
            for field in ("adv_prob", "adv_conf", "adv_gap"):
                assert re.search(rf'<label[^>]*>\s*[^<]*<input[^>]*name="{field}"', row), field
