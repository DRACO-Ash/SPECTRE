"""The Decision Engine reads Threat Understanding: collect first, and the minimax guidance (SPC-171).

The operator's fourth output is the recommended response. Concept section
4.10: when the threat range straddles the action line, the band where the
recommended response changes, and a cue SPECTRE can read lands before
decide-by, the advice is to collect first, naming the cue; when nothing lands
in time, or decide-by has passed, it is to act on the ceiling. Only a cue
with an outcome that takes the range off the line counts. Section 7.5: cues
that need an analyst or a sensor become collection rows, each named by its cue,
timed by its lookup duration and labelled "collection to narrow the threat
range", listed beside the ranking and never scored in it (concept section 9,
decision 12); the figure bases of every cell stay as they are; the
probability and the confidence are the operator's and are never filled in from
Understanding; and expected value, chosen while the evidence has not earned the
probability it weights by, says so and names what minimax would recommend.

Every sentence here is checked against I13. No test reaches the network or
reads the wall clock: every moment is fixed.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    BoundElset,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.domain.provenance import Basis, FigureBasis
from spectre.domain.threat_assessment import Band
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_HISTORY = tu.PULL_HISTORY
_RECORD = "analyst to date and source the intel record"


def _cue(observation: str = _HISTORY, steps: int = 3, hours: float = 0.5, *, fed: bool = True,
         record: bool = False) -> tu.Cue:
    return tu.Cue(
        observation=observation, dimensions=(tu.Dimension.BEHAVIOUR,), steps=steps, hours=hours,
        effect="could raise the Threat floor to HIGH", benign=(Band.MINIMAL, Band.CRITICAL),
        hostile=(Band.HIGH, Band.CRITICAL), record=record, fed=fed,
    )


def _outcomes(cue: tu.Cue, benign: tuple[Band, Band], hostile: tuple[Band, Band]) -> tu.Cue:
    """*cue* with the range it would read on each outcome."""
    return dataclasses.replace(cue, benign=benign, hostile=hostile)


#: A cue whose either outcome leaves a LOW to CRITICAL range across HIGH: it lowers the ceiling only to HIGH.
_UNDECIDING = _outcomes(_cue("pull its GCAT catalogue entry", steps=1, hours=0.25), (Band.LOW, Band.HIGH),
                        (Band.LOW, Band.CRITICAL))


def _advice(floor: Band = Band.MEDIUM, ceiling: Band = Band.CRITICAL, cues: tuple[tu.Cue, ...] = (_cue(),), *,
            decide_at: datetime | None = _NOW + timedelta(hours=6), **kw: Any) -> Any:
    return tu.collection_advice((floor, ceiling), cues, now=_NOW, decide_at=decide_at, **kw)


# ── Section 4.10: collection_advice ──────────────────────────────────────────

class TestCollectFirst:
    def test_a_straddle_with_time_to_collect_is_collect_first_naming_the_top_cue(self) -> None:
        advice = _advice()
        assert advice.advice is tu.Advice.COLLECT_FIRST
        assert advice.cue == _cue()
        assert advice.sentence == (
            "Collect first: pull its element-set history, about 30 min, lands before decide-by at 15:00 UTC on 4 Nov. "
            "The Threat range runs from MEDIUM to CRITICAL, across Threat HIGH, where your response changes, and "
            "this could raise the Threat floor to HIGH."
        )

    def test_the_same_range_with_decide_by_passed_is_act_on_the_ceiling(self) -> None:
        advice = _advice(decide_at=_NOW - timedelta(minutes=1))
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.cue is None
        assert advice.sentence == (
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat range runs from MEDIUM to CRITICAL, across "
            "Threat HIGH, where your response changes, and decide-by has passed."
        )

    def test_with_no_decide_by_no_collection_can_be_shown_to_land_in_time(self) -> None:
        """No deadline to collect against is not time to collect: the cautious reading acts on the ceiling."""
        advice = _advice(decide_at=None)
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.sentence.endswith("and no decide-by is set to collect against.")

    def test_the_best_cue_that_lands_in_time_is_named_when_a_better_one_does_not(self) -> None:
        slow, quick = _cue(_RECORD, steps=3, hours=4.0, record=True), _cue(steps=1, hours=0.5)
        advice = _advice(cues=(slow, quick), decide_at=_NOW + timedelta(hours=2))
        assert advice.advice is tu.Advice.COLLECT_FIRST
        assert advice.cue == quick

    def test_cues_are_ranked_by_steps_per_hour_whatever_order_they_arrive_in(self) -> None:
        one, three = _cue("pull its GCAT catalogue entry", steps=1, hours=0.25), _cue(steps=3, hours=0.5)
        assert _advice(cues=(one, three)).cue == three

    def test_a_cue_landing_exactly_at_decide_by_lands_in_time(self) -> None:
        assert _advice(decide_at=_NOW + timedelta(hours=0.5)).advice is tu.Advice.COLLECT_FIRST

    def test_a_cue_landing_after_decide_by_does_not(self) -> None:
        advice = _advice(decide_at=_NOW + timedelta(minutes=29))
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.sentence.endswith(
            "and no collection SPECTRE can read lands before decide-by at 09:29 UTC on 4 Nov.",
        )

    @pytest.mark.parametrize("cue", [_cue(steps=0), _cue(fed=False)], ids=["no steps", "not fed"])
    def test_a_cue_that_cannot_narrow_the_range_here_does_not_count(self, cue: tu.Cue) -> None:
        """A cue SPECTRE cannot read the result of would leave the range on screen as it is."""
        advice = _advice(cues=(cue,))
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.sentence.endswith("and no collection SPECTRE can read would narrow it.")

    def test_a_floor_at_the_action_line_acts_on_the_ceiling_whatever_could_be_collected(self) -> None:
        advice = _advice(floor=Band.HIGH)
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.sentence == (
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat floor is already HIGH, at or above Threat "
            "HIGH, where your response changes, so no collection changes the decision."
        )

    def test_a_ceiling_under_the_action_line_is_below_it(self) -> None:
        advice = _advice(floor=Band.MINIMAL, ceiling=Band.MEDIUM)
        assert advice.advice is tu.Advice.BELOW_ACTION_LINE
        assert advice.sentence == (
            "Below the action line: the Threat ceiling is MEDIUM, under Threat HIGH, where your response changes."
        )

    def test_the_action_line_is_the_operators_to_set(self) -> None:
        assert tu.ACTION_LINE is Band.HIGH
        lowers = _outcomes(_cue(), (Band.HIGH, Band.HIGH), (Band.HIGH, Band.CRITICAL))
        advice = _advice(action_line=Band.CRITICAL, floor=Band.HIGH, cues=(lowers,))
        assert advice.advice is tu.Advice.COLLECT_FIRST

    def test_a_cue_that_leaves_the_range_across_the_line_either_way_does_not_count(self) -> None:
        """Collecting it could not change the decision, so it spends time before decide-by for nothing."""
        advice = _advice(floor=Band.LOW, cues=(_UNDECIDING,))
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.cue is None
        assert advice.sentence == (
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat range runs from LOW to CRITICAL, across "
            "Threat HIGH, where your response changes, and no collection SPECTRE can read could move it off that line."
        )

    @pytest.mark.parametrize(("benign", "hostile"), [
        ((Band.LOW, Band.MEDIUM), (Band.LOW, Band.CRITICAL)), ((Band.LOW, Band.CRITICAL), (Band.HIGH, Band.CRITICAL)),
    ], ids=["the benign ceiling falls under the line", "the hostile floor reaches it"])
    def test_a_cue_with_an_outcome_off_the_line_counts(self, benign: tuple[Band, Band],
                                                       hostile: tuple[Band, Band]) -> None:
        """It is named over a quicker cue that could not change the decision."""
        cue = _outcomes(_cue(steps=1, hours=0.5), benign, hostile)
        assert cue.steps_per_hour < _UNDECIDING.steps_per_hour
        assert _advice(floor=Band.LOW, cues=(_UNDECIDING, cue)).cue == cue

    def test_the_cues_that_land_are_only_those_that_could_change_the_decision(self) -> None:
        deciding = _cue()
        landing = tu.landing_cues((_UNDECIDING, deciding), now=_NOW, decide_at=_NOW + timedelta(hours=6))
        assert landing == (deciding,)

    def test_the_model_ranks_the_cues_and_the_first_one_spectre_can_read_is_named(self) -> None:
        """With nothing held, holding conjunctions ranks first but cannot be read yet, so the history is named."""
        situation = tu.Situation(now=_NOW, access=Band.CRITICAL, custody=Custody.HELD, history_truncated=False)
        result = tu.assess((), situation, with_cues=True)
        assert not result.cues[0].fed
        advice = _advice(result.range.floor, result.range.ceiling, result.cues)
        assert advice.advice is tu.Advice.COLLECT_FIRST
        assert advice.cue is not None and advice.cue.observation == _HISTORY

    def test_only_the_record_cue_needs_someone_outside_spectre(self) -> None:
        assert _cue().inside_spectre
        assert not _cue(_RECORD, record=True).inside_spectre


@pytest.mark.parametrize("kw", [
    {}, {"decide_at": None}, {"decide_at": _NOW}, {"cues": ()}, {"decide_at": _NOW + timedelta(minutes=1)},
    {"floor": Band.HIGH}, {"floor": Band.LOW, "ceiling": Band.MEDIUM}, {"floor": Band.LOW, "cues": (_UNDECIDING,)},
])
def test_every_advice_sentence_keeps_i13(kw: dict[str, Any]) -> None:
    for part in _advice(**kw).sentence.split(". "):
        assert i13_problems(part) == [], part


# ── Section 7.5: the Decision Engine ─────────────────────────────────────────

def _red(name: str = "RED_X") -> BoundElset:
    return BoundElset(side="red", name=name, stk_name=name, satno=90002, tle="1 x\n2 x", data_mode="REAL",
                      epoch=None, age_hours=None, limit_hours=None)


def _picture(understanding: tu.Understanding = tu.Understanding.LOW, **kw: Any) -> Any:
    fields: dict[str, Any] = {
        "red": "RED_X", "floor": Band.MEDIUM, "ceiling": Band.CRITICAL, "understanding": understanding,
        "cues": (_cue(), _cue(_RECORD, steps=2, hours=4.0, record=True)),
        "decide_at": _NOW + timedelta(hours=6),
        "decide_by": "Decide by 15:00 UTC on 4 Nov for BLUE_1: its fastest intercept could arrive at 03:00 UTC on 5 Nov.",
        "assessed_at": _NOW - timedelta(minutes=20),
    }
    fields.update(kw)
    return decision.ThreatPicture(**fields)


def _scenario(picture: Any = None, *, probability: float = 0.3, bound: bool = True) -> Scenario:
    adversary = [
        AdversaryAction(id="A1", name="Approach", action_type=ActionType.MANOEUVRE, probability=probability,
                        confidence=0.6),
        AdversaryAction(id="A2", name="Hold", action_type=ActionType.NO_ACTION, probability=0.7, confidence=0.4),
    ]
    friendly = [
        FriendlyResponse(id="F1", name="Evade", action_type=ActionType.MANOEUVRE, cost=0.4, reversibility=0.5,
                         time_to_execute_hours=6.0),
        FriendlyResponse(id="F2", name="Watch", action_type=ActionType.NO_ACTION, cost=0.0, reversibility=1.0,
                         time_to_execute_hours=0.5),
    ]
    return Scenario(name="Moved", epoch_utc=_NOW, adversary_actions=adversary, friendly_responses=friendly,
                    binding=ScenarioBinding(red=_red()) if bound else None, threat=picture)


class TestThePictureBelongsToTheBoundRedTrack:
    def test_a_picture_needs_the_red_track_it_was_assessed_for(self) -> None:
        with pytest.raises(ValueError, match="bound red track"):
            _scenario(_picture(red="RED_Y"))
        with pytest.raises(ValueError, match="bound red track"):
            _scenario(_picture(), bound=False)

    def test_a_picture_with_its_floor_above_its_ceiling_is_refused(self) -> None:
        with pytest.raises(ValueError, match="floor"):
            _picture(floor=Band.CRITICAL, ceiling=Band.MEDIUM)


class TestCollectFirstRows:
    """A collect-first row is listed beside the ranking, never scored in it.

    Nothing in SPECTRE tasks a sensor and collecting moves no figure until what it finds is in the sweep, so a row
    scored as a sensor retask would win on a custody credit and a cost and reversibility made up for it.
    """

    def test_the_result_carries_the_advice_at_the_scenario_epoch(self) -> None:
        result = evaluate_scenario(_scenario(_picture()))
        assert result.collection is not None
        assert result.collection.advice is tu.Advice.COLLECT_FIRST
        assert result.collection.cue is not None and result.collection.cue.observation == _HISTORY

    def test_a_cue_that_needs_an_analyst_becomes_a_collection_row_named_by_the_cue(self) -> None:
        rows = evaluate_scenario(_scenario(_picture())).collection_rows
        assert [(r.name, r.hours) for r in rows] == [(_RECORD, 4.0)]
        assert rows[0].basis == FigureBasis(Basis.LOOKUP, decision.COLLECTION_NOTE)
        assert rows[0].basis.note.startswith("collection to narrow the threat range")
        assert rows[0].sentence == (
            f"{_RECORD}, 4 h: collection to narrow the threat range: the cue's tuned duration, a lookup. Not ranked "
            "against your responses: collecting moves no figure until what it finds is in the sweep."
        )
        for sentence in rows[0].sentence.split(". "):
            assert i13_problems(sentence) == [], sentence

    @pytest.mark.parametrize("strategy", list(SelectorStrategy))
    def test_a_collection_row_is_never_scored_ranked_or_recommended(self, strategy: SelectorStrategy) -> None:
        result = evaluate_scenario(_scenario(_picture(), probability=decision.DEFAULT_PROBABILITY), strategy)
        assert result.collection_rows
        assert [r.id for r in result.scenario.friendly_responses] == ["F1", "F2"]
        assert all(len(row) == 2 for row in result.outcome_matrix)
        assert result.robust_best_response.id in {"F1", "F2"}
        assert _RECORD not in (result.objective_guidance or "")

    def test_no_friendly_row_can_carry_a_collection(self) -> None:
        assert "collection" not in {f.name for f in dataclasses.fields(FriendlyResponse)}
        assert not hasattr(decision, "with_collection")

    def test_a_cue_inside_spectre_adds_no_row(self) -> None:
        assert evaluate_scenario(_scenario(_picture(cues=(_cue(),)))).collection_rows == ()

    def test_an_analyst_cue_that_lands_after_decide_by_adds_no_row(self) -> None:
        result = evaluate_scenario(_scenario(_picture(decide_at=_NOW + timedelta(hours=2))))
        assert result.collection_rows == ()

    def test_an_analyst_cue_that_could_not_change_the_decision_adds_no_row(self) -> None:
        record = dataclasses.replace(_UNDECIDING, observation=_RECORD, record=True)
        result = evaluate_scenario(_scenario(_picture(floor=Band.LOW, cues=(_cue(), record))))
        assert result.collection is not None and result.collection.advice is tu.Advice.COLLECT_FIRST
        assert result.collection_rows == ()

    @pytest.mark.parametrize("kw", [
        {"decide_at": _NOW - timedelta(hours=1)}, {"floor": Band.HIGH}, {"ceiling": Band.MEDIUM},
    ], ids=["decide-by passed", "floor at the line", "ceiling under it"])
    def test_with_no_collect_first_no_row_is_listed(self, kw: dict[str, Any]) -> None:
        assert evaluate_scenario(_scenario(_picture(**kw))).collection_rows == ()

    def test_with_no_picture_no_row_is_listed(self) -> None:
        assert evaluate_scenario(_scenario()).collection_rows == ()

    def test_figure_bases_stay_as_they_are(self) -> None:
        """Every cell reads the same with the picture held and its collection listed."""
        plain = evaluate_scenario(_scenario())
        collected = evaluate_scenario(_scenario(_picture()))
        assert collected.collection_rows
        assert collected.outcome_matrix == plain.outcome_matrix
        assert collected.basis_lines == plain.basis_lines

    @pytest.mark.parametrize("level", list(tu.Understanding))
    def test_probability_and_confidence_are_never_filled_in(self, level: tu.Understanding) -> None:
        scenario = _scenario(_picture(level))
        rows = [(a.probability, a.confidence) for a in scenario.adversary_actions]
        result = evaluate_scenario(scenario)
        assert [(a.probability, a.confidence) for a in result.scenario.adversary_actions] == rows == [
            (0.3, 0.6), (0.7, 0.4),
        ]


class TestTheThreatBesideTheFields:
    def test_each_row_carries_its_understanding_into_the_result(self) -> None:
        result = evaluate_scenario(_scenario(_picture(tu.Understanding.MODERATE)))
        assert result.row_understanding == (
            "Understanding MODERATE: shown beside P and Conf as context; it fills neither.",
        ) * 2

    def test_a_bound_red_track_with_no_picture_reads_not_assessed(self) -> None:
        result = evaluate_scenario(_scenario())
        assert result.row_understanding == (
            "Understanding not assessed: the engine holds no current picture from the sweep for RED_X, so nothing "
            "fills P or Conf.",
        ) * 2
        assert result.collection is None
        assert result.threat_lines == ()
        assert i13_problems(result.row_understanding[0] or "") == []

    def test_an_unbound_row_carries_none(self) -> None:
        assert evaluate_scenario(_scenario(bound=False)).row_understanding == (None, None)

    def test_the_threat_range_and_understanding_are_said_apart(self) -> None:
        result = evaluate_scenario(_scenario(_picture()))
        assert result.threat_lines == (
            "Threat range for RED_X: from MEDIUM to CRITICAL, as the sweep assessed it at 08:40 UTC on 4 Nov.",
            "Understanding LOW: the sweep's rating of RED_X.",
            "Decide by 15:00 UTC on 4 Nov for BLUE_1: its fastest intercept could arrive at 03:00 UTC on 5 Nov.",
        )
        for line in (*result.threat_lines, *result.row_understanding):
            assert i13_problems(line) == [], line

    def test_a_picture_with_no_sweep_time_or_deadline_says_so(self) -> None:
        result = evaluate_scenario(_scenario(_picture(assessed_at=None, decide_at=None, decide_by="")))
        assert result.threat_lines == (
            "Threat range for RED_X: from MEDIUM to CRITICAL, as the sweep assessed it.",
            "Understanding LOW: the sweep's rating of RED_X.",
        )


class TestTheMinimaxGuidance:
    _GUIDANCE = "Expected value rests on a probability the evidence has not earned."

    def test_expected_value_at_understanding_low_names_what_minimax_recommends(self) -> None:
        scenario = _scenario(_picture(tu.Understanding.LOW))
        result = evaluate_scenario(scenario, SelectorStrategy.EXPECTED_VALUE)
        minimax = evaluate_scenario(scenario, SelectorStrategy.MINIMAX).robust_best_response
        assert result.objective_guidance == (
            f"{self._GUIDANCE} Minimax, the cautious rule, needs no probability: it recommends {minimax.name}."
        )
        assert result.robust_strategy is SelectorStrategy.EXPECTED_VALUE   # recommended, never switched

    def test_expected_value_with_an_untouched_default_probability_says_so(self) -> None:
        result = evaluate_scenario(_scenario(probability=decision.DEFAULT_PROBABILITY, bound=False),
                                   SelectorStrategy.EXPECTED_VALUE)
        assert result.objective_guidance is not None
        assert result.objective_guidance.startswith(self._GUIDANCE)

    def test_expected_value_on_a_bound_red_track_with_no_picture_says_so(self) -> None:
        """Understanding not assessed is not earned: the cautious reading gives the guidance, saying only what the
        engine holds, never whether a sweep was run."""
        result = evaluate_scenario(_scenario(), SelectorStrategy.EXPECTED_VALUE)
        minimax = evaluate_scenario(_scenario(), SelectorStrategy.MINIMAX).robust_best_response
        assert result.objective_guidance == (
            "Expected value rests on a probability no current Threat picture for RED_X supports. Minimax, the "
            f"cautious rule, needs no probability: it recommends {minimax.name}."
        )
        for sentence in result.objective_guidance.split(". "):
            assert i13_problems(sentence) == [], sentence

    def test_a_picture_less_bound_row_at_the_default_probability_reads_the_picture_less_guidance(self) -> None:
        result = evaluate_scenario(_scenario(probability=decision.DEFAULT_PROBABILITY),
                                   SelectorStrategy.EXPECTED_VALUE)
        assert (result.objective_guidance or "").startswith("Expected value rests on a probability no current")

    def test_expected_value_on_earned_understanding_and_set_probabilities_says_nothing(self) -> None:
        result = evaluate_scenario(_scenario(_picture(tu.Understanding.MODERATE)), SelectorStrategy.EXPECTED_VALUE)
        assert result.objective_guidance is None

    @pytest.mark.parametrize("strategy", [SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN])
    def test_any_other_rule_says_nothing(self, strategy: SelectorStrategy) -> None:
        assert evaluate_scenario(_scenario(_picture()), strategy).objective_guidance is None

    def test_the_guidance_keeps_i13(self) -> None:
        guidance = evaluate_scenario(_scenario(_picture()), SelectorStrategy.EXPECTED_VALUE).objective_guidance
        assert guidance is not None and i13_problems(guidance) == []
