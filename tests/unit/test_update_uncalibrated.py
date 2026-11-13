"""The update's likelihood is said to be uncalibrated wherever its probability is shown (SPC-210, evaluation F-22).

The update after turn 1 rests on the custody rule as its likelihood, and no held history has been scored against it:
the calibration harness exists (spectre.domain.likelihood_calibration) but has no data yet. So wherever the page
shows the update's probability, its share of the weight on a row, it says in the same section that the likelihood
is uncalibrated with no calibration data yet: in the likelihood model's line and in the update's basis. The page is
rendered for every observation under expected value, and fails this test if a share is shown without the words.
"""

from __future__ import annotations

import html
import re

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import Seen, SelectorStrategy
from spectre.domain.tree_selectors import NO_OBSERVATION
from spectre.domain.turn_update import LIKELIHOOD_MODEL, POSTERIOR_NOTE, SENTENCES, UNCALIBRATED
from spectre.web.tree_view import tree_view
from tests.unit._tree_view_cases import sampled_result
from tests.unit.test_lookup_relations import _TEMPLATE

_EV = SelectorStrategy.EXPECTED_VALUE


def _update_section(observed: Seen | None, strategy: SelectorStrategy = _EV) -> str:
    """The tree's update section as the page shows it, its tags dropped; "" when the page has none."""
    from spectre.web.app import templates

    result = sampled_result(strategy, observed)
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE.parents[1])), autoescape=True, undefined=StrictUndefined)
    env.filters.update(templates.env.filters)
    page = env.get_template("partials/decision_results.html").render(result=result, tree=tree_view(result))
    found = re.search(r'<div class="tree-update".*?</div>', page, flags=re.DOTALL)
    return "" if found is None else " ".join(html.unescape(re.sub(r"<[^>]+>", " ", found.group(0))).split())


class TestTheWords:
    def test_they_say_it_is_uncalibrated_with_no_data_yet(self) -> None:
        assert UNCALIBRATED == (
            "the likelihood is uncalibrated, with no calibration data yet: no held history of what red did has been "
            "scored against it (SPC-210)"
        )

    def test_the_likelihood_models_line_and_the_updates_basis_carry_them(self) -> None:
        assert UNCALIBRATED in LIKELIHOOD_MODEL
        assert POSTERIOR_NOTE.endswith(f"a lookup; {UNCALIBRATED}")
        assert UNCALIBRATED in SENTENCES


class TestThePage:
    @pytest.mark.parametrize("observed", [Seen.BURN, Seen.NO_BURN])
    def test_a_shown_share_is_said_to_rest_on_an_uncalibrated_likelihood(self, observed: Seen) -> None:
        section = _update_section(observed)
        assert "of the weight" in section or "all the weight" in section
        assert section.count(UNCALIBRATED) == 2

    def test_the_model_line_says_it_before_any_observation_is_stated(self) -> None:
        section = _update_section(None)
        assert NO_OBSERVATION in section
        assert section.count(UNCALIBRATED) == 1

    @pytest.mark.parametrize("observed", [None, Seen.BURN, Seen.NO_BURN, Seen.NOTHING])
    def test_no_share_is_ever_shown_without_the_words(self, observed: Seen | None) -> None:
        section = _update_section(observed)
        shows_a_share = "of the weight" in section or "all the weight" in section
        assert not shows_a_share or UNCALIBRATED in section
        assert section != ""

    def test_minimax_shows_no_share_so_no_update_to_label(self) -> None:
        section = _update_section(Seen.BURN, SelectorStrategy.MINIMAX)
        assert "of the weight" not in section
        assert "all the weight" not in section
