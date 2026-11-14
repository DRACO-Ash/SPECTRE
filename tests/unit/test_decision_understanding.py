"""The Decision Engine reads Threat Understanding: collect first, and the minimax guidance (SPC-171).

The operator's fourth output is the recommended response. Concept section
4.10: when the threat range straddles the action line, the Threat band at
which the owner may set that a response changes (HIGH by default, tuned, not
sourced), and a cue SPECTRE can read lands before decide-by, the sweep's
advice is to collect first, naming the cue; when nothing lands in time, or
decide-by has passed, it is to act on the ceiling. Any cue with value above 0
counts, whether or not one of its outcomes takes the range off the line (the
owner's ruling of 2026-11-05 on concept section 9, decision 10, SPC-182); a cue
whose result SPECTRE cannot read never counts, since its result never lands.
The engine collects first only for a cue whose outcomes give different
recommended responses (SPC-204), which
the matrix, reading no Threat band, never gives, so the engine's tests of
collect first put the stand-in of tests/unit/_band_stand_in.py in place. Section 7.5: cues
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
from tests.unit._band_stand_in import band_moves_a_figure  # noqa: F401 (a fixture, used by name)
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_HISTORY = tu.PULL_HISTORY
_RECORD = "analyst to date and source the intel record"
#: The age the engine shows beside every figure and sentence a picture assessed 20 min before evaluation feeds.
_AGE = "from the sweep's picture assessed 20 min before this evaluation"


def _cue(observation: str = _HISTORY, steps: int = 3, hours: float = 0.5, *, fed: bool = True,
         record: bool = False) -> tu.Cue:
    return tu.Cue(
        observation=observation, dimensions=(tu.Dimension.BEHAVIOUR,), steps=steps, hours=hours,
        effect="could raise the Threat floor to HIGH", benign=(Band.MINIMAL, Band.CRITICAL),
        hostile=(Band.HIGH, Band.CRITICAL), record=record, fed=fed,
    )


def _outcomes(cue: tu.Cue, benign: tuple[Band, Band], hostile: tuple[Band, Band],
              now: tuple[Band, Band] = (Band.LOW, Band.CRITICAL)) -> tu.Cue:
    """*cue* with the range it would read on each outcome, and its effect worded from them against the range *now*,
    as the model words it, so the fixture never says what its outcomes do not do."""
    parts = [
        *([f"raise the Threat floor to {hostile[0].name}"] if hostile[0] > now[0] else []),
        *([f"lower the Threat ceiling to {benign[1].name}"] if benign[1] < now[1] else []),
    ]
    effect = "could " + " or ".join(parts) if parts else "would firm up Behaviour and move no Threat band"
    return dataclasses.replace(cue, benign=benign, hostile=hostile, effect=effect)


#: A cue whose either outcome leaves a LOW to CRITICAL range across HIGH: it lowers the ceiling only to HIGH, so it
#: has value above 0 without taking the range off the line.
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
            "The Threat range runs from MEDIUM to CRITICAL, across the action line at Threat HIGH, and this could "
            "raise the Threat floor to HIGH."
        )
        assert advice.action_line == tu.ACTION_LINE_MEANS

    def test_the_same_range_with_decide_by_passed_is_act_on_the_ceiling(self) -> None:
        advice = _advice(decide_at=_NOW - timedelta(minutes=1))
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.cue is None
        assert advice.sentence == (
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat range runs from MEDIUM to CRITICAL, across "
            "the action line at Threat HIGH, and decide-by has passed."
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
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat floor is already HIGH, at or above the "
            "action line at Threat HIGH, so no collection could take the range below it."
        )

    def test_a_ceiling_under_the_action_line_is_below_it(self) -> None:
        advice = _advice(floor=Band.MINIMAL, ceiling=Band.MEDIUM)
        assert advice.advice is tu.Advice.BELOW_ACTION_LINE
        assert advice.sentence == (
            "Below the action line: the Threat ceiling is MEDIUM, under the action line at Threat HIGH."
        )

    def test_the_action_line_is_the_operators_to_set(self) -> None:
        assert tu.ACTION_LINE is Band.HIGH
        lowers = _outcomes(_cue(), (Band.HIGH, Band.HIGH), (Band.HIGH, Band.CRITICAL), now=(Band.HIGH, Band.CRITICAL))
        advice = _advice(action_line=Band.CRITICAL, floor=Band.HIGH, cues=(lowers,))
        assert advice.advice is tu.Advice.COLLECT_FIRST

    def test_a_cue_that_leaves_the_range_across_the_line_either_way_still_counts(self) -> None:
        """Concept section 9, decision 10 (SPC-182): any cue with value above 0 may trigger collect first."""
        advice = _advice(floor=Band.LOW, cues=(_UNDECIDING,))
        assert advice.advice is tu.Advice.COLLECT_FIRST
        assert advice.cue == _UNDECIDING
        assert advice.sentence == (
            "Collect first: pull its GCAT catalogue entry, about 15 min, lands before decide-by at 15:00 UTC on "
            "4 Nov. The Threat range runs from LOW to CRITICAL, across the action line at Threat HIGH, and this "
            "could lower the Threat ceiling to HIGH."
        )

    @pytest.mark.parametrize(("benign", "hostile"), [
        ((Band.LOW, Band.MEDIUM), (Band.LOW, Band.CRITICAL)), ((Band.LOW, Band.CRITICAL), (Band.HIGH, Band.CRITICAL)),
    ], ids=["the benign ceiling falls under the line", "the hostile floor reaches it"])
    def test_a_cue_off_the_line_is_ranked_with_the_rest_by_steps_per_hour(
            self, benign: tuple[Band, Band], hostile: tuple[Band, Band]) -> None:
        """Taking the range off the line earns no precedence: the quicker cue with value above 0 is named."""
        cue = _outcomes(_cue(steps=1, hours=0.5), benign, hostile)
        assert cue.steps_per_hour < _UNDECIDING.steps_per_hour
        assert _advice(floor=Band.LOW, cues=(_UNDECIDING, cue)).cue == _UNDECIDING

    def test_the_cues_that_land_are_every_one_with_value_above_0_spectre_can_read(self) -> None:
        other = _cue()
        unread, still = _cue(_RECORD, fed=False), _cue("pull its GCAT catalogue entry", steps=0)
        landing = tu.landing_cues((_UNDECIDING, other, unread, still), now=_NOW, decide_at=_NOW + timedelta(hours=6))
        assert landing == (other, _UNDECIDING)

    def test_a_cue_whose_result_spectre_cannot_read_never_counts_however_much_it_could_move(self) -> None:
        """Its result never lands, so it cannot be collected before decide-by (SPC-182, Claude's call, kept)."""
        advice = _advice(floor=Band.LOW, cues=(_cue(steps=4, hours=0.25, fed=False),))
        assert advice.advice is tu.Advice.ACT_ON_CEILING
        assert advice.sentence.endswith("and no collection SPECTRE can read would narrow it.")

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
    advice = _advice(**kw)
    for part in (*advice.sentence.split(". "), advice.action_line):
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


def _scenario(picture: Any = None, *, probability: float = 0.3, bound: bool = True, edited: bool = True) -> Scenario:
    adversary = [
        AdversaryAction(id="A1", name="Approach", action_type=ActionType.MANOEUVRE, probability=probability,
                        confidence=0.6, probability_edited=edited),
        # The rest of P, so the rows' P sum to 1 and the engine adds no remainder row (SPC-203): 0.7 beside 0.3.
        AdversaryAction(id="A2", name="Hold", action_type=ActionType.NO_ACTION, probability=1.0 - probability,
                        confidence=0.4),
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


@pytest.mark.usefixtures("band_moves_a_figure")
class TestCollectFirstRows:
    """A collect-first row is listed beside the ranking, never scored in it.

    The engine lists rows only when it collects first, which needs a cue whose outcomes change its recommended
    response: the stand-in (tests/unit/_band_stand_in.py) lets the picture move a figure, so here they do.

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
            f"{_RECORD}, 4 h: collection to narrow the threat range: the cue's tuned duration, a lookup ({_AGE}). "
            "Not ranked against your responses: collecting moves no figure until what it finds is in the sweep."
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



class TestThePictureMovesNoFigure:
    def test_figure_bases_stay_as_they_are(self) -> None:
        """Every cell reads the same with the picture held as with none: the engine's matrix reads no Threat band."""
        plain = evaluate_scenario(_scenario())
        collected = evaluate_scenario(_scenario(_picture()))
        assert collected.collection is not None
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
            f"Understanding MODERATE: shown beside P and Conf as context; it fills neither ({_AGE}).",
        ) * 2

    def test_a_bound_red_track_with_no_picture_reads_not_assessed(self) -> None:
        result = evaluate_scenario(_scenario())
        assert result.row_understanding == (
            "Understanding not assessed: the engine reads no picture from the sweep for RED_X, so nothing fills P "
            "or Conf.",
        ) * 2
        assert result.collection is None
        assert result.threat_lines == ()
        assert i13_problems(result.row_understanding[0] or "") == []

    def test_an_unbound_row_carries_none(self) -> None:
        assert evaluate_scenario(_scenario(bound=False)).row_understanding == (None, None)

    def test_the_threat_range_and_understanding_are_said_apart(self) -> None:
        result = evaluate_scenario(_scenario(_picture()))
        assert result.threat_lines == (
            f"Threat range for RED_X: from MEDIUM to CRITICAL ({_AGE}, at 08:40 UTC on 4 Nov).",
            f"Understanding LOW: the sweep's rating of RED_X ({_AGE}).",
            "Decide by 15:00 UTC on 4 Nov for BLUE_1: its fastest intercept could arrive at 03:00 UTC on 5 Nov "
            f"({_AGE}).",
        )
        for line in (*result.threat_lines, *result.row_understanding):
            assert i13_problems(line) == [], line

    def test_a_picture_with_no_deadline_says_so(self) -> None:
        result = evaluate_scenario(_scenario(_picture(decide_at=None, decide_by="")))
        assert result.threat_lines == (
            f"Threat range for RED_X: from MEDIUM to CRITICAL ({_AGE}, at 08:40 UTC on 4 Nov).",
            f"Understanding LOW: the sweep's rating of RED_X ({_AGE}).",
        )


class TestTheMinimaxGuidance:
    _GUIDANCE = "Expected value rests on a probability the evidence has not earned."

    def test_expected_value_at_understanding_low_names_what_minimax_recommends(self) -> None:
        scenario = _scenario(_picture(tu.Understanding.LOW))
        result = evaluate_scenario(scenario, SelectorStrategy.EXPECTED_VALUE)
        minimax = evaluate_scenario(scenario, SelectorStrategy.MINIMAX).robust_best_response
        assert result.objective_guidance == (
            f"Expected value rests on a probability the evidence has not earned ({_AGE}). Minimax, the cautious "
            f"rule, needs no probability: it picks {minimax.name}."
        )
        assert result.robust_strategy is SelectorStrategy.EXPECTED_VALUE   # recommended, never switched

    def test_expected_value_with_an_untouched_default_probability_says_so(self) -> None:
        """SPC-183: the form records that row 1's P was never edited, so it is the panel's default, untouched."""
        result = evaluate_scenario(_scenario(probability=decision.DEFAULT_PROBABILITY, bound=False, edited=False),
                                   SelectorStrategy.EXPECTED_VALUE)
        assert result.objective_guidance is not None
        assert result.objective_guidance.startswith(self._GUIDANCE)

    def test_a_deliberate_default_probability_is_not_read_as_untouched(self) -> None:
        """SPC-183, the owner's ruling of 2026-11-05 (concept section 9, decision 11): a P the operator edited to
        0.5 is theirs, so the guidance reads the record, not the value."""
        scenario = _scenario(_picture(tu.Understanding.MODERATE), probability=decision.DEFAULT_PROBABILITY)
        assert evaluate_scenario(scenario, SelectorStrategy.EXPECTED_VALUE).objective_guidance is None

    def test_an_unedited_probability_is_the_panels_default(self) -> None:
        """A P the form says was never edited holds the value the panel gave the row; anything else is refused."""
        with pytest.raises(ValueError, match="not edited"):
            _scenario(probability=0.3, edited=False)

    def test_expected_value_on_a_bound_red_track_with_no_picture_says_so(self) -> None:
        """Understanding not assessed is not earned: the cautious reading gives the guidance, saying only what the
        engine holds, never whether a sweep was run."""
        result = evaluate_scenario(_scenario(), SelectorStrategy.EXPECTED_VALUE)
        minimax = evaluate_scenario(_scenario(), SelectorStrategy.MINIMAX).robust_best_response
        assert result.objective_guidance == (
            "Expected value rests on a probability no Threat picture for RED_X supports. Minimax, the cautious "
            f"rule, needs no probability: it picks {minimax.name}."
        )
        for sentence in result.objective_guidance.split(". "):
            assert i13_problems(sentence) == [], sentence

    def test_a_picture_less_bound_row_at_the_default_probability_reads_the_picture_less_guidance(self) -> None:
        result = evaluate_scenario(_scenario(probability=decision.DEFAULT_PROBABILITY),
                                   SelectorStrategy.EXPECTED_VALUE)
        assert (result.objective_guidance or "").startswith("Expected value rests on a probability no Threat")

    def test_expected_value_on_earned_understanding_and_set_probabilities_says_nothing(self) -> None:
        result = evaluate_scenario(_scenario(_picture(tu.Understanding.MODERATE)), SelectorStrategy.EXPECTED_VALUE)
        assert result.objective_guidance is None

    @pytest.mark.parametrize("strategy", [SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN])
    def test_any_other_rule_says_nothing(self, strategy: SelectorStrategy) -> None:
        assert evaluate_scenario(_scenario(_picture()), strategy).objective_guidance is None

    def test_the_guidance_keeps_i13(self) -> None:
        guidance = evaluate_scenario(_scenario(_picture()), SelectorStrategy.EXPECTED_VALUE).objective_guidance
        assert guidance is not None and i13_problems(guidance) == []


class TestThePicturesAgeBesideEveryFigureItFeeds:
    """SPC-181, the owner's ruling of 2026-11-05 (concept section 9, decision 9): the engine reads the picture at any
    age, and says how old it was at evaluation beside every figure and sentence it feeds."""

    _OLD = "from the sweep's picture assessed 3 h 10 min before this evaluation"

    @pytest.mark.parametrize(("age", "words"), [
        (timedelta(seconds=59), "under 1 min"), (timedelta(minutes=1), "1 min"), (timedelta(minutes=59), "59 min"),
        (timedelta(hours=1), "1 h"), (timedelta(hours=3, minutes=10, seconds=59), "3 h 10 min"),
        (timedelta(hours=23, minutes=59), "23 h 59 min"), (timedelta(days=1), "1 d"),
        (timedelta(days=2, hours=4, minutes=30), "2 d 4 h"),
    ])
    def test_the_age_is_in_words_rounded_down(self, age: timedelta, words: str) -> None:
        assert decision.picture_age_words(age) == words

    @pytest.mark.usefixtures("band_moves_a_figure")
    def test_a_picture_hours_old_carries_its_age_beside_every_sentence_it_feeds(self) -> None:
        picture = _picture(assessed_at=_NOW - timedelta(hours=3, minutes=10))
        result = evaluate_scenario(_scenario(picture), SelectorStrategy.EXPECTED_VALUE)
        assert result.threat_lines[0] == f"Threat range for RED_X: from MEDIUM to CRITICAL ({self._OLD}, at 05:50 UTC on 4 Nov)."
        assert all(line.endswith(f"({self._OLD}).") for line in result.threat_lines[1:])
        assert result.collection is not None and result.collection.advice is tu.Advice.COLLECT_FIRST
        assert result.collection.sentence.endswith(
            f"could raise the Threat floor to HIGH. Under its benign outcome the engine recommends Watch (F2); under "
            f"its hostile outcome, Evade (F1) ({self._OLD}).")
        assert [row.sentence.split(". ")[0] for row in result.collection_rows] == [
            f"{_RECORD}, 4 h: collection to narrow the threat range: the cue's tuned duration, a lookup ({self._OLD})",
        ]
        assert (result.objective_guidance or "").startswith(
            f"Expected value rests on a probability the evidence has not earned ({self._OLD}). Minimax",
        )
        assert all(note is not None and note.endswith(f"({self._OLD}).") for note in result.row_understanding)
        for text in (*result.threat_lines, result.collection.sentence, result.collection_rows[0].sentence,
                     result.objective_guidance or "", *(n or "" for n in result.row_understanding)):
            for sentence in text.split(". "):
                assert i13_problems(sentence) == [], sentence

    def test_a_picture_days_old_is_read_with_decide_by_passed(self) -> None:
        """Its age moves nothing but the words: decide-by has passed, so the advice is to act on the ceiling."""
        result = evaluate_scenario(_scenario(_picture(assessed_at=_NOW - timedelta(days=2, hours=1),
                                                      decide_at=_NOW - timedelta(days=1))))
        assert result.collection is not None
        assert result.collection.sentence == (
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat range runs from MEDIUM to CRITICAL, across "
            "the action line at Threat HIGH, and decide-by has passed. No collection the picture holds can change the "
            "recommended response: the outcome matrix reads no Threat band (from the sweep's picture assessed 2 d 1 h "
            "before this evaluation)."
        )
        assert result.collection_rows == ()

    def test_guidance_the_picture_does_not_feed_carries_no_age(self) -> None:
        """At Understanding MODERATE an untouched P alone is what is not earned, so the picture's age is not beside
        it."""
        scenario = _scenario(_picture(tu.Understanding.MODERATE), probability=decision.DEFAULT_PROBABILITY,
                             edited=False)
        guidance = evaluate_scenario(scenario, SelectorStrategy.EXPECTED_VALUE).objective_guidance
        assert guidance is not None
        assert guidance.startswith("Expected value rests on a probability the evidence has not earned. Minimax")

    def test_a_picture_states_when_it_was_assessed(self) -> None:
        """With no time it was assessed, its age cannot be shown beside what it feeds, so there is no picture."""
        with pytest.raises(TypeError, match="assessed_at"):
            decision.ThreatPicture(red="RED_X", floor=Band.MEDIUM, ceiling=Band.CRITICAL,  # type: ignore[call-arg]
                                   understanding=tu.Understanding.LOW)

    def test_a_picture_assessed_after_the_evaluation_is_refused(self) -> None:
        with pytest.raises(ValueError, match="assessed after"):
            _scenario(_picture(assessed_at=_NOW + timedelta(seconds=1)))
        assert _scenario(_picture(assessed_at=_NOW)).threat is not None


class TestTheDecideByIsRestatedAtTheEvaluation:
    """A picture read at any age carries the sweep's decide-by, worded against the sweep's own clock. Once that
    deadline has passed by the evaluation, the engine says so against the evaluation, so the line never says "Decide
    by" a past time or counts hours "from now" from the sweep, and it agrees with the advice below it (concept
    section 7.5, item 5: one deadline)."""

    _OLD = "from the sweep's picture assessed 3 d before this evaluation"
    _PASSED_AT_SWEEP = ("Decide-by has passed for BLUE_1: an intercept could arrive at 11:00 UTC on 1 Nov, 2.0 h from "
                        "now, inside your response time of 4 h.")

    def _lines(self, **kw: Any) -> tuple[str, ...]:
        fields: dict[str, Any] = {"assessed_at": _NOW - timedelta(days=3), "target": "BLUE_1"}
        fields.update(kw)
        return evaluate_scenario(_scenario(_picture(**fields))).threat_lines

    def test_a_deadline_set_at_the_sweep_and_passed_since_says_it_has_passed(self) -> None:
        lines = self._lines(decide_at=_NOW - timedelta(days=2, hours=18), arrival=_NOW - timedelta(days=2, hours=6))
        assert lines[2] == (
            "Decide-by has passed for BLUE_1: it was 15:00 UTC on 1 Nov, and the intercept it was set against could "
            f"have arrived at 03:00 UTC on 2 Nov, before this evaluation ({self._OLD})."
        )
        assert not any(line.startswith("Decide by ") for line in lines)

    def test_one_passed_at_the_sweep_counts_its_hours_from_the_evaluation_not_the_sweep(self) -> None:
        at_sweep = ("Decide-by has passed for BLUE_1: an intercept could arrive at 11:00 UTC on 4 Nov, 5.2 h from "
                    "now, inside your response time of 6 h.")
        lines = self._lines(assessed_at=_NOW - timedelta(hours=3, minutes=10), decide_by=at_sweep,
                            decide_at=_NOW - timedelta(hours=4), arrival=_NOW + timedelta(hours=2))
        assert lines[2] == (
            "Decide-by has passed for BLUE_1: it was 05:00 UTC on 4 Nov, and an intercept could arrive at 11:00 UTC "
            "on 4 Nov, 2.0 h after this evaluation (from the sweep's picture assessed 3 h 10 min before this "
            "evaluation)."
        )
        assert "from now" not in " ".join(lines)

    def test_its_arrival_passed_too_says_it_could_have_arrived(self) -> None:
        lines = self._lines(decide_by=self._PASSED_AT_SWEEP, decide_at=_NOW - timedelta(days=3, hours=2),
                            arrival=_NOW - timedelta(days=2, hours=22))
        assert lines[2] == (
            "Decide-by has passed for BLUE_1: it was 07:00 UTC on 1 Nov, and the intercept it was set against could "
            f"have arrived at 11:00 UTC on 1 Nov, before this evaluation ({self._OLD})."
        )

    def test_with_no_arrival_held_it_says_only_when_the_deadline_was(self) -> None:
        lines = self._lines(decide_at=_NOW - timedelta(days=2, hours=18), arrival=None, target="")
        assert lines[2] == f"Decide-by has passed: it was 15:00 UTC on 1 Nov ({self._OLD})."

    def test_a_deadline_still_ahead_is_shown_as_the_sweep_worded_it(self) -> None:
        """Its sentence holds only clock times, which do not age."""
        lines = self._lines(decide_at=_NOW + timedelta(hours=6), arrival=_NOW + timedelta(hours=18))
        assert lines[2] == ("Decide by 15:00 UTC on 4 Nov for BLUE_1: its fastest intercept could arrive at 03:00 UTC "
                            f"on 5 Nov ({self._OLD}).")

    def test_the_line_and_the_advice_agree_that_the_deadline_has_passed(self) -> None:
        result = evaluate_scenario(_scenario(_picture(assessed_at=_NOW - timedelta(days=3), target="BLUE_1",
                                                      decide_at=_NOW - timedelta(days=2, hours=18),
                                                      arrival=_NOW - timedelta(days=2, hours=6))))
        assert result.collection is not None and "decide-by has passed" in result.collection.sentence
        assert result.threat_lines[2].startswith("Decide-by has passed for BLUE_1")
        for sentence in result.threat_lines[2].split(". "):
            assert i13_problems(sentence) == [], sentence
