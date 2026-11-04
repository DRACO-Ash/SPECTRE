"""What turn 1 lets us see of red, and the update it makes (SPC-141).

The likelihood model is the bound red track's custody, as the sweep judges it, carried over each turn with the red
burns on the path: custody lost at a burn in the turn shows a burn, held through the turn shows none, and lost for
any other reason, or never read, shows nothing. The posterior after turn 1 is each row's P restricted to the rows
that give what we see, renormalised, with any NOTSO interval carried into its range. Nothing here writes a P.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.notso import NOTSOType
from spectre.domain import decision
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import ActionType, AdversaryAction, Scenario
from spectre.domain.notso_prior import NotsoPrior
from spectre.domain.provenance import Basis
from spectre.domain.turn_update import (
    INDEPENDENT_TURNS,
    LIKELIHOOD_MODEL,
    POSTERIOR_EVERY_ROW,
    POSTERIOR_NO_WEIGHT,
    POSTERIOR_ONE_ROW,
    POSTERIOR_SHARES,
    SENTENCES,
    Seen,
    burns_on,
    likelihood,
    posteriors,
    seen_after,
)
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import EPOCH
from tests.unit._i13 import i13_problems

_TURN_S = 3 * 3600.0
_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _custody(state: Custody = Custody.HELD, *, age: float = 0.0) -> decision.ScenarioBinding:
    red = dataclasses.replace(cases.bound("red", age=age), custody=CustodyStatus(state, f"Custody {state.value}."))
    return decision.ScenarioBinding(red=red, blue=cases.bound("blue"))


def _evasive(offset_h: float = 1.0, row_id: str = "A1", p: float = 0.5) -> AdversaryAction:
    return dataclasses.replace(cases.evasive(n=50, offset_h=offset_h, row_id=row_id), probability=p)


def _scenario(rows: list[AdversaryAction], bind: decision.ScenarioBinding | None = None, turns: int = 2) -> Scenario:
    return cases.scenario(rows, [cases.hold()], turns=turns, bind=bind or _custody())


def _prior(probability: float, events: int = 5) -> NotsoPrior:
    """*events* over 100 days carried over 72 h, at *probability*."""
    return NotsoPrior(
        red="RX", action_type=ActionType.MANOEUVRE, probability=probability, confidence=None, events=events,
        notices=events, span_start=_NOW - timedelta(days=100), span_end=_NOW, covered_days=100.0, gaps=0,
        horizon_hours=72.0, mapped=(NOTSOType.MANOEUVRE,), confidence_line="",
    )


class TestWhatATurnShows:
    def test_a_burn_while_custody_is_held_shows_a_burn_and_a_still_row_shows_none(self) -> None:
        """21: custody held at the epoch; Evasive burns 1 h into a 3 h turn and Hold course does not."""
        scenario = _scenario([cases.still(), _evasive()])
        assert seen_after(scenario, (1,), _TURN_S) is Seen.BURN
        assert seen_after(scenario, (0,), _TURN_S) is Seen.NO_BURN
        assert likelihood(scenario, _TURN_S) == (Seen.NO_BURN, Seen.BURN)

    @pytest.mark.parametrize("state", [Custody.LOST, Custody.DEGRADED])
    def test_custody_lost_or_degraded_at_the_epoch_shows_nothing(self, state: Custody) -> None:
        """22: the custody rule counts degraded as lost, so no turn shows anything."""
        scenario = _scenario([cases.still(), _evasive()], _custody(state))
        assert likelihood(scenario, _TURN_S) == (Seen.NOTHING, Seen.NOTHING)

    def test_custody_not_read_or_no_red_track_shows_nothing(self) -> None:
        """22: with no custody read there is nothing to see by, so the update cannot move the weights."""
        unread = _scenario([cases.still(), _evasive()], cases.binding())
        assert likelihood(unread, _TURN_S) == (Seen.NOTHING, Seen.NOTHING)
        no_red = dataclasses.replace(unread, binding=None)
        assert seen_after(no_red, (1,), _TURN_S) is Seen.NOTHING

    def test_an_element_set_that_ages_out_first_shows_nothing(self) -> None:
        """23: the red set is 23 h old against its 24 h limit, so custody ages out 1 h in, before the 2 h burn; at
        0.5 h the burn comes first and is seen."""
        late = _scenario([cases.still(), _evasive(2.0)], _custody(age=23.0))
        assert likelihood(late, _TURN_S) == (Seen.NOTHING, Seen.NOTHING)
        early = _scenario([cases.still(), _evasive(0.5)], _custody(age=23.0))
        assert likelihood(early, _TURN_S) == (Seen.NOTHING, Seen.BURN)

    def test_after_a_burn_the_next_turn_shows_nothing(self) -> None:
        """24: custody lost at turn 1's burn stays lost, so turn 2 shows nothing whatever red does in it; a still
        turn 1 keeps custody, and turn 2's burn is then seen."""
        scenario = _scenario([cases.still(), _evasive()])
        assert seen_after(scenario, (1, 0), _TURN_S) is Seen.NOTHING
        assert seen_after(scenario, (1, 1), _TURN_S) is Seen.NOTHING
        assert seen_after(scenario, (0, 1), _TURN_S) is Seen.BURN
        assert seen_after(scenario, (0, 0), _TURN_S) is Seen.NO_BURN

    def test_a_burn_at_a_turns_start_belongs_to_that_turn(self) -> None:
        """24: a burn at 0 h after each turn starts is turn 2's in turn 2, not turn 1's at turn 1's end."""
        scenario = _scenario([cases.still(), _evasive(0.0)])
        assert burns_on(scenario, (0, 1), _TURN_S) == (EPOCH + timedelta(seconds=_TURN_S),)
        assert seen_after(scenario, (0,), _TURN_S) is Seen.NO_BURN
        assert seen_after(scenario, (0, 1), _TURN_S) is Seen.BURN

    def test_each_turns_burn_is_its_stated_offset_after_that_turn_starts(self) -> None:
        """24: Evasive in turns 1 and 3 of three 2 h turns burns at 1 h and 5 h."""
        scenario = _scenario([cases.still(), _evasive()], turns=3)
        assert burns_on(scenario, (1, 0, 1), 7200.0) == (EPOCH + timedelta(hours=1), EPOCH + timedelta(hours=5))


class TestThePosteriorAfterTurnOne:
    def test_rows_that_give_the_same_thing_share_the_weight_by_their_p(self) -> None:
        """25: two burning rows, P 0.3 and 0.1, and Hold course at 0.5: a burn leaves 0.75 and 0.25 between them;
        no burn leaves only Hold course."""
        rows = [_evasive(p=0.3), _evasive(2.0, "A2", 0.1), cases.still()]
        scenario = _scenario(rows)
        burn, none = posteriors(scenario, likelihood(scenario, _TURN_S))
        assert burn.seen is Seen.BURN
        assert burn.shares == pytest.approx((0.75, 0.25, None))
        assert burn.shares[2] is None
        assert burn.ranges[0] == pytest.approx((0.75, 0.75))
        assert burn.ranges[1] == pytest.approx((0.25, 0.25))
        assert burn.ranges[2] is None
        assert burn.line == POSTERIOR_SHARES.format(
            seen="a burn", shares="row 1, Evasive, 0.75 of the weight, from your P; row 2, Evasive, 0.25 of the "
            "weight, from your P",
        )
        assert none.seen is Seen.NO_BURN
        assert none.shares == (None, None, 1.0)
        assert none.line == POSTERIOR_ONE_ROW.format(seen="no burn", row=3, name="Hold course")
        for posterior in (burn, none):
            assert posterior.basis.kind is Basis.LOOKUP

    def test_a_share_is_never_shown_above_what_it_is(self) -> None:
        """25: 2 / 3 reads 0.66, not 0.67, and a default P is named as untouched."""
        rows = [_evasive(p=0.2), _evasive(2.0, "A2", 0.1), cases.still()]
        scenario = _scenario(rows)
        burn, _ = posteriors(scenario, likelihood(scenario, _TURN_S))
        assert "row 1, Evasive, 0.66 of the weight, from your P;" in burn.line
        assert "row 2, Evasive, 0.33 of the weight" in burn.line
        untouched = _scenario([_evasive(), _evasive(2.0, "A2", 0.2), cases.still()])
        burn, _ = posteriors(untouched, likelihood(untouched, _TURN_S))
        assert "row 1, Evasive, 0.71 of the weight, from the default P of 0.5, untouched;" in burn.line

    def test_when_every_row_gives_the_same_thing_the_weights_stand(self) -> None:
        """26: custody not read, so every row gives nothing and the posterior is the prior."""
        rows = [_evasive(p=0.3), cases.still()]
        scenario = _scenario(rows, cases.binding())
        (only,) = posteriors(scenario, likelihood(scenario, _TURN_S))
        assert only.seen is Seen.NOTHING
        assert only.shares == pytest.approx((0.375, 0.625))
        assert only.line == POSTERIOR_EVERY_ROW.format(seen="nothing")

    def test_no_weight_no_update(self) -> None:
        """27: both burning rows at P 0, so a burn has no prior weight to update."""
        rows = [_evasive(p=0.0), _evasive(2.0, "A2", 0.0), cases.still()]
        scenario = _scenario(rows)
        burn, _ = posteriors(scenario, likelihood(scenario, _TURN_S))
        assert burn.shares == (None, None, None)
        assert burn.ranges == (None, None, None)
        assert burn.line == POSTERIOR_NO_WEIGHT.format(seen="a burn")

    def test_a_notso_interval_carries_into_the_range(self) -> None:
        """28: row 1's P 0.13 is a NOTSO suggestion in 0.04 to 0.30; row 2's 0.1 is the operator's. Its share is
        least with row 1 at its low edge and most at its high edge, and row 2's the other way round."""
        prior = _prior(0.13)
        rows = [dataclasses.replace(_evasive(p=0.13), accepted_prior=prior), _evasive(2.0, "A2", 0.1), cases.still()]
        scenario = _scenario(rows)
        burn, _ = posteriors(scenario, likelihood(scenario, _TURN_S))
        interval = prior.interval
        lo, hi = interval.checked_low, interval.high
        assert burn.shares[0] == pytest.approx(0.13 / 0.23)
        assert burn.ranges[0] == pytest.approx((lo / (lo + 0.1), hi / (hi + 0.1)))
        assert burn.ranges[1] == pytest.approx((0.1 / (hi + 0.1), 0.1 / (lo + 0.1)))
        assert burn.ranges[2] is None
        low, high = burn.ranges[0]
        assert low < burn.shares[0] < high
        assert re.search(r"row 1, Evasive, 0\.56 of the weight, 0\.\d\d to 0\.\d\d across the NOTSO intervals, from the "
                         r"NOTSO suggestion you applied;", burn.line)
        shown = re.search(r"row 1, Evasive, 0\.56 of the weight, (0\.\d\d) to (0\.\d\d)", burn.line)
        assert shown is not None
        assert float(shown[1]) <= low
        assert float(shown[2]) >= high

    def test_a_row_at_p_0_beside_a_notso_row_takes_none_of_the_weight(self) -> None:
        """28: a NOTSO P is never 0, nor the edge it is checked from, so its row keeps all the weight at every
        corner and the row at P 0 none."""
        prior = _prior(0.04, events=3)
        rows = [dataclasses.replace(_evasive(p=0.04), accepted_prior=prior), _evasive(2.0, "A2", 0.0), cases.still()]
        scenario = _scenario(rows)
        burn, _ = posteriors(scenario, likelihood(scenario, _TURN_S))
        assert burn.shares[:2] == (1.0, 0.0)
        assert burn.ranges[:2] == ((1.0, 1.0), (0.0, 0.0))


class TestTheSentences:
    @pytest.mark.parametrize("sentence", SENTENCES)
    def test_each_passes_the_house_checks(self, sentence: str) -> None:
        """29."""
        assert i13_problems(sentence) == []
        assert "\u2014" not in sentence
        assert "\u2013" not in sentence
        assert "--" not in sentence
        assert "%" not in sentence

    def test_the_model_names_what_each_row_gives(self) -> None:
        """29."""
        scenario = _scenario([cases.still(), _evasive()])
        from spectre.domain.turn_update import model_lines

        model, independent = model_lines(scenario, likelihood(scenario, _TURN_S))
        assert model == LIKELIHOOD_MODEL.format(rows="Row 1, Hold course, gives no burn; row 2, Evasive, gives a burn")
        assert independent == INDEPENDENT_TURNS
        assert "not calibrated" in LIKELIHOOD_MODEL
