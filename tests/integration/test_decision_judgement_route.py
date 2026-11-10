"""The operator's judgements and the code version on the console's own results page (SPC-196, evaluation F-05).

The route's evaluation is shown with a "Judgement inputs" list naming every value the operator entered that enters a
score or a pick, each marked "(judgement)" in words, and the code version that computed it, from its provenance.
"""

from __future__ import annotations

import html
import re

from fastapi.testclient import TestClient

import spectre
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_record_route import _sign_in
from tests.integration.test_xss_escaping import _assert_inert


def _flat(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())


def section_titles(page: str) -> str:
    """The notes of the list's marks, as their titles carry them."""
    return " ".join(html.unescape(t) for t in re.findall(r'title="([^"]*)"', _section(page)))


def _section(page: str) -> str:
    match = re.search(r'<div[^>]*class="judgement-inputs".*?</div>', page, re.DOTALL)
    assert match is not None, "no Judgement inputs on the results page"
    return match.group(0)


class TestTheResultsPage:
    def test_every_value_the_operator_entered_is_marked_a_judgement(self, client: TestClient) -> None:
        cookie = _sign_in(client, "judgement_inputs")
        page = _evaluate(client, cookie, _form()).text
        text = _flat(_section(page))
        assert text.startswith("Judgement inputs:")
        for words in (
            "Weights: custody 0.35 (judgement), closest approach 0.25 (judgement), our delta-V 0.2 (judgement), "
            "time to execute 0.1 (judgement), reversibility 0.1 (judgement).",
            "Keep-out distance: 10 km (judgement).",
            "Horizon: 72 h (judgement).",
            "Turns: 1 (judgement).",
            "Hold (F1): type manoeuvre (judgement), cost 0.2 (judgement), reversibility 0.8 (judgement), time to "
            "execute 4 h (judgement).",
            "Approach (A1): type manoeuvre (judgement), P 0.6 (judgement), Conf 0.7 (judgement)",
        ):
            assert _flat(words) in text, words
        assert "entered on the panel" not in section_titles(page)
        assert "set or kept on the panel; a new panel starts it at 0.35" in section_titles(page)

    def test_the_code_version_is_shown_in_words(self, client: TestClient) -> None:
        cookie = _sign_in(client, "judgement_version")
        page = _evaluate(client, cookie, _form()).text
        assert (f"Code version {spectre.__version__}: the version SPECTRE reports for the code that computed this "
                "result, from its provenance.") in _flat(page)

    def test_a_name_in_the_list_is_inert(self, client: TestClient) -> None:
        cookie = _sign_in(client, "judgement_inert")
        payload = "<script>alert(1)</script>"
        resp = _evaluate(client, cookie, _form(adv_name=[payload], fr_name=[payload]))
        _assert_inert(resp)
        section = _section(resp.text)
        assert "&lt;script&gt;alert(1)&lt;/script&gt; (F1): type" in section
        assert "&lt;script&gt;alert(1)&lt;/script&gt; (A1): type" in section
