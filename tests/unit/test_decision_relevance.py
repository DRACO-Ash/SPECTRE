"""Collect first only when a collection can change the recommended response (SPC-204, evaluation finding F-14).

The Decision Engine's collect-first advice rested on the Threat range's band steps against a fixed, unsourced
action line, and called that line where "your response changes". But the threat picture moves no figure in the
outcome matrix (decision.ThreatPicture), so no collection outcome could change the engine's recommendation: probe
P-10 evaluated one bound scenario under opposite pictures and found the matrix and the pick identical, while one
picture was told to collect first.

Decision relevance is now computed from the engine. For a scenario with a threat picture and a cue, the engine
builds its matrix again under each of the cue's outcomes, the picture's range moved to the benign and to the hostile
(floor, ceiling), through its own cell step from the plans the evaluation made, which are built with no picture in
them, and takes the recommended response under each with the same rule: the evaluation the engine would run under
each outcome's picture, which a test sets against a whole evaluation under each. The matrix reads no Threat band
today, so the two are always the same, and that is a tested, stated result, not an assumption: the advice says the
collection would narrow the Threat range but cannot change the recommended response, and never says to collect
first. Should a later release let a band move a figure, the advice follows; a test stand-in that lets the picture
move one response's custody and closest approach shows it.

Every sentence here is checked against I13.
"""

from __future__ import annotations

import dataclasses
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain import threat_understanding as tu
from spectre.domain.decision import (
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    ThreatPicture,
    cue_relevance,
    evaluate_scenario,
)
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Advice, Cue, Dimension, Understanding
from tests.unit._band_stand_in import band_moves_a_figure  # noqa: F401 (a fixture, used by name)
from tests.unit._i13 import i13_problems
from tests.unit.test_deployment_contract import _repo_only

_EPOCH = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
_MINIMAX, _MINIMIN, _EV = SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE
_ROOT = Path(__file__).resolve().parents[2]


def _cue(hours: float = 1.0, observation: str = "probe collection", *, record: bool = False) -> Cue:
    """P-10's cue: either outcome takes the range off the action line, and it lands well before decide-by."""
    return Cue(observation=observation, dimensions=(Dimension.BEHAVIOUR,), steps=2, hours=hours,
               effect="could settle it", benign=(Band.LOW, Band.MEDIUM), hostile=(Band.HIGH, Band.CRITICAL),
               record=record)


def _bound() -> Scenario:
    """P-10's bound scenario: the plane-change pair, one row per action type, at its own epoch."""
    from tests.unit.test_decision_sampled import _binding
    from tests.unit.test_decision_sampled import _scenario as bound_rows

    return dataclasses.replace(bound_rows(binding=_binding()), epoch_utc=_EPOCH)


def _picture(red: str, floor: Band, ceiling: Band, understanding: Understanding, cues: tuple[Cue, ...]) -> Any:
    return ThreatPicture(red=red, floor=floor, ceiling=ceiling, understanding=understanding, cues=cues,
                         decide_at=_EPOCH + timedelta(hours=10), assessed_at=_EPOCH - timedelta(minutes=20))


_AGE = "from the sweep's picture assessed 20 min before this evaluation"


def _sentences(result: ScenarioResult) -> list[str]:
    advice = result.collection
    texts = [] if advice is None else [advice.sentence, advice.action_line]
    return [*texts, *(row.sentence for row in result.collection_rows), *result.threat_lines]


# ── Probe P-10, inverted ─────────────────────────────────────────────────────

class TestProbeP10Inverted:
    """The same bound scenario under opposite threat pictures: one straddling the action line with a cue that lands
    in time, one entirely at CRITICAL. The matrix and the pick are the same, as P-10 found, and the advice now says so
    instead of telling the operator to collect first."""

    @pytest.fixture(scope="class")
    @classmethod
    def seen(cls) -> dict[str, ScenarioResult]:
        base = _bound()
        red = base.binding.red.stk_name  # type: ignore[union-attr]
        pictures = {
            "straddle": _picture(red, Band.LOW, Band.CRITICAL, Understanding.LOW, (_cue(),)),
            "critical": _picture(red, Band.CRITICAL, Band.CRITICAL, Understanding.HIGH, ()),
        }
        return {name: evaluate_scenario(dataclasses.replace(base, threat=p), _MINIMAX) for name, p in pictures.items()}

    def test_opposite_pictures_give_the_same_matrix_and_pick(self, seen: dict[str, ScenarioResult]) -> None:
        straddle, critical = seen["straddle"], seen["critical"]
        assert straddle.robust_best_response.id == critical.robust_best_response.id
        assert ([[c.composite_score for c in row] for row in straddle.outcome_matrix]
                == [[c.composite_score for c in row] for row in critical.outcome_matrix])

    def test_the_cue_cannot_change_the_recommendation_and_the_advice_says_so(
        self, seen: dict[str, ScenarioResult],
    ) -> None:
        advice = seen["straddle"].collection
        assert advice is not None
        assert advice.advice is Advice.CANNOT_CHANGE_RESPONSE
        assert advice.sentence == (
            'Collecting "probe collection" would narrow the Threat range but cannot change the recommended response: '
            f"the outcome matrix reads no Threat band ({_AGE})."
        )
        assert advice.action_line == ""

    def test_nothing_in_the_engine_says_collect_first(self, seen: dict[str, ScenarioResult]) -> None:
        for result in seen.values():
            assert result.collection_rows == ()
            for sentence in _sentences(result):
                assert "collect first" not in sentence.lower(), sentence

    @pytest.mark.parametrize("rule", [_MINIMAX, _MINIMIN, _EV])
    def test_the_relevance_is_computed_under_each_outcome_not_assumed(
        self, seen: dict[str, ScenarioResult], rule: SelectorStrategy,
    ) -> None:
        result = seen["straddle"]
        relevance = cue_relevance(result, _cue(), rule)
        pick = decision.find_robust_response(result.scenario, result.outcome_matrix, rule)
        assert (relevance.benign, relevance.hostile) == (pick, pick)
        assert not relevance.changes
        assert not relevance.moved

    def test_a_full_evaluation_under_each_outcomes_picture_gives_the_same_matrix(
        self, seen: dict[str, ScenarioResult],
    ) -> None:
        """What the relevance scores again is what the engine computes: under the benign and the hostile picture a
        whole new evaluation gives the matrix it gave under the picture held."""
        held = seen["straddle"]
        picture = held.scenario.threat
        for floor, ceiling in (_cue().benign, _cue().hostile):
            moved = dataclasses.replace(picture, floor=floor, ceiling=ceiling)
            again = evaluate_scenario(dataclasses.replace(held.scenario, threat=moved), _MINIMAX)
            assert again.outcome_matrix == held.outcome_matrix

    def test_every_sentence_keeps_i13(self, seen: dict[str, ScenarioResult]) -> None:
        for result in seen.values():
            for text in _sentences(result):
                for sentence in text.split(". "):
                    assert i13_problems(sentence) == [], sentence


# ── A cue whose outcomes do change the pick: a test stand-in ─────────────────

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _understanding(picture: Any, **kw: Any) -> Scenario:
    from tests.unit.test_decision_understanding import _scenario

    return _scenario(picture, **kw)


def _held(cues: tuple[Cue, ...] = (_cue(0.5),), **kw: Any) -> Any:
    """The understanding tests' red track, its range across the action line, decide-by 6 h away."""
    fields: dict[str, Any] = {
        "red": "RED_X", "floor": Band.MEDIUM, "ceiling": Band.CRITICAL, "understanding": Understanding.LOW,
        "cues": cues, "decide_at": datetime(2026, 11, 4, 15, 0, tzinfo=UTC),
        "assessed_at": datetime(2026, 11, 4, 8, 40, tzinfo=UTC),
    }
    fields.update(kw)
    return ThreatPicture(**fields)


@pytest.mark.usefixtures("band_moves_a_figure")
class TestWhenACuesOutcomesChangeThePick:
    """With the stand-in (tests/unit/_band_stand_in.py), Watch (F2) is the pick under the picture held, its floor
    MEDIUM, and under the cue's benign outcome, and Evade (F1), our manoeuvre, under its hostile one, its floor HIGH:
    the collection decides the response, so it is collected first."""

    def test_the_two_outcomes_give_different_picks(self) -> None:
        result = evaluate_scenario(_understanding(_held()), _MINIMAX)
        assert result.robust_best_response.id == "F2"
        relevance = cue_relevance(result, _cue(0.5), _MINIMAX)
        assert (relevance.benign.id, relevance.hostile.id) == ("F2", "F1")
        assert relevance.changes and relevance.moved

    def test_it_is_collected_first_and_the_advice_names_the_pick_under_each_outcome(self) -> None:
        advice = evaluate_scenario(_understanding(_held()), _MINIMAX).collection
        assert advice is not None and advice.advice is Advice.COLLECT_FIRST
        assert advice.cue == _cue(0.5)
        assert advice.sentence == (
            "Collect first: probe collection, about 30 min, lands before decide-by at 15:00 UTC on 4 Nov. The Threat "
            "range runs from MEDIUM to CRITICAL, across the action line at Threat HIGH, and this could settle it. "
            "Under its benign outcome the engine recommends Watch (F2); under its hostile outcome, Evade (F1) "
            "(from the sweep's picture assessed 20 min before this evaluation)."
        )
        assert advice.action_line == tu.ACTION_LINE_MEANS

    def test_a_cue_that_changes_the_pick_but_lands_after_decide_by_is_not_collected_first(self) -> None:
        advice = evaluate_scenario(_understanding(_held((_cue(8.0),))), _MINIMAX).collection
        assert advice is not None and advice.advice is Advice.ACT_ON_CEILING

    @pytest.mark.parametrize("rule", [_MINIMAX, _MINIMIN, _EV])
    def test_under_every_rule(self, rule: SelectorStrategy) -> None:
        result = evaluate_scenario(_understanding(_held()), rule)
        assert result.collection is not None and result.collection.advice is Advice.COLLECT_FIRST

    def test_the_cue_that_changes_the_pick_is_named_over_a_quicker_one_that_cannot(self) -> None:
        """A quicker cue that could take the range off the action line, so the sweep alone would name it, but whose
        outcomes both leave the Threat floor below it: under the stand-in neither moves the pick."""
        quick = dataclasses.replace(_cue(0.25, "pull its GCAT catalogue entry"), hostile=(Band.MEDIUM, Band.CRITICAL))
        assert tu.landing_cues((quick, _cue(0.5)), now=_NOW, decide_at=_held().decide_at)[0] == quick
        advice = evaluate_scenario(_understanding(_held((quick, _cue(0.5)))), _MINIMAX).collection
        assert quick.steps_per_hour > _cue(0.5).steps_per_hour
        assert advice is not None and advice.cue == _cue(0.5)

    def test_an_analyst_cue_that_changes_the_pick_is_listed_as_a_collection_row(self) -> None:
        record = _cue(4.0, "analyst to date and source the intel record", record=True)
        result = evaluate_scenario(_understanding(_held((_cue(0.5), record))), _MINIMAX)
        assert [(row.name, row.hours) for row in result.collection_rows] == [(record.observation, 4.0)]

    def test_every_sentence_keeps_i13(self) -> None:
        result = evaluate_scenario(_understanding(_held()), _MINIMAX)
        for text in _sentences(result):
            for sentence in text.split(". "):
                assert i13_problems(sentence) == [], sentence


def test_a_picture_that_moves_scores_but_not_the_pick_says_the_pick_holds_either_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stand-in moving every score a little under the benign outcome: the scores move, the pick does not."""
    real = decision._score

    def nudged(scenario: Scenario, friendly: FriendlyResponse, figures: Any) -> float:
        picture = scenario.threat
        return real(scenario, friendly, figures) + (0.001 if picture is not None and picture.ceiling < Band.HIGH
                                                    else 0.0)

    monkeypatch.setattr(decision, "_score", nudged)
    result = evaluate_scenario(_understanding(_held()), _MINIMAX)
    relevance = cue_relevance(result, _cue(0.5), _MINIMAX)
    assert relevance.moved and not relevance.changes
    assert result.collection is not None
    assert result.collection.sentence == (
        'Collecting "probe collection" would narrow the Threat range, but under either of its outcomes the engine '
        f"recommends Evade (F1) ({_AGE})."
    )


def test_the_matrix_is_said_to_read_no_threat_band_only_when_no_cues_picture_moves_a_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stand-in moving every score a little only under a picture whose ceiling is HIGH, which another cue's benign
    outcome gives and the named cue's outcomes do not: the named cue moves no score, but the matrix does read a band,
    so the advice says the pick holds either way and never that the matrix reads no Threat band."""
    real = decision._score

    def nudged(scenario: Scenario, friendly: FriendlyResponse, figures: Any) -> float:
        picture = scenario.threat
        return real(scenario, friendly, figures) + (0.001 if picture is not None and picture.ceiling is Band.HIGH
                                                    else 0.0)

    monkeypatch.setattr(decision, "_score", nudged)
    late = dataclasses.replace(_cue(8.0, "task a sensor"), benign=(Band.MEDIUM, Band.HIGH))
    result = evaluate_scenario(_understanding(_held((_cue(0.5), late))), _MINIMAX)
    assert not cue_relevance(result, _cue(0.5), _MINIMAX).moved
    assert cue_relevance(result, late, _MINIMAX).moved
    assert result.collection is not None
    assert result.collection.advice is Advice.CANNOT_CHANGE_RESPONSE
    assert decision.NO_BAND_READ not in result.collection.sentence
    assert result.collection.sentence == (
        'Collecting "probe collection" would narrow the Threat range, but under either of its outcomes the engine '
        f"recommends Evade (F1) ({_AGE})."
    )


# ── The same evaluation the engine would run under each outcome's picture ────

def _whole(result: ScenarioResult, cue: Cue, rule: SelectorStrategy) -> tuple[list[str | None], bool]:
    """The pick of a whole new evaluation under each of *cue*'s outcomes' pictures, and whether either matrix differs
    from a whole new evaluation's under the picture held: what the relevance must agree with, done here only."""
    held = result.scenario.threat
    assert held is not None

    def under(floor: Band, ceiling: Band) -> ScenarioResult:
        moved = dataclasses.replace(held, floor=floor, ceiling=ceiling)
        return evaluate_scenario(dataclasses.replace(result.scenario, threat=moved), rule)

    again = under(held.floor, held.ceiling).outcome_matrix
    outcomes = [under(*cue.hostile if hostile else cue.benign) for hostile in (False, True)]
    picks = [None if o.robust_best_response is None else o.robust_best_response.id for o in outcomes]
    return picks, any(o.outcome_matrix != again for o in outcomes)


def _relevance(result: ScenarioResult, cue: Cue, rule: SelectorStrategy) -> tuple[list[str | None], bool]:
    seen = cue_relevance(result, cue, rule)
    return [None if p is None else p.id for p in (seen.benign, seen.hostile)], seen.moved


class TestTheSameEvaluation:
    """The relevance builds the matrix again under each outcome's picture through the engine's own cell step, so it
    agrees with a whole new evaluation under each, whether or not the picture moves a figure."""

    @pytest.mark.parametrize("rule", [_MINIMAX, _MINIMIN, _EV])
    def test_on_the_lookup_path_the_engine_reading_no_band(self, rule: SelectorStrategy) -> None:
        result = evaluate_scenario(_understanding(_held()), rule)
        pick = result.robust_best_response
        assert _relevance(result, _cue(0.5), rule) == _whole(result, _cue(0.5), rule) == ([pick.id, pick.id], False)

    @pytest.mark.parametrize("rule", [_MINIMAX, _MINIMIN, _EV])
    def test_on_p10s_bound_scenario_the_engine_reading_no_band(self, rule: SelectorStrategy) -> None:
        base = _bound()
        red = base.binding.red.stk_name  # type: ignore[union-attr]
        picture = _picture(red, Band.LOW, Band.CRITICAL, Understanding.LOW, (_cue(),))
        result = evaluate_scenario(dataclasses.replace(base, threat=picture), rule)
        pick = result.robust_best_response
        assert _relevance(result, _cue(), rule) == _whole(result, _cue(), rule) == ([pick.id, pick.id], False)

    @pytest.mark.usefixtures("band_moves_a_figure")
    @pytest.mark.parametrize("rule", [_MINIMAX, _MINIMIN, _EV])
    def test_with_a_stand_in_that_lets_the_picture_move_a_figure(self, rule: SelectorStrategy) -> None:
        """The stand-in moves the manoeuvre's custody and closest approach under the benign picture and the watch's
        under the hostile one, figures, not a score: the relevance sees the move, as a whole evaluation does."""
        result = evaluate_scenario(_understanding(_held()), rule)
        assert _relevance(result, _cue(0.5), rule) == _whole(result, _cue(0.5), rule) == (["F2", "F1"], True)

    def test_the_plans_are_built_with_no_picture_in_them(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sampling, the computed plan, custody and the span searched are planned from the scenario with its picture
        taken out, so no band can reach them: a band can reach a figure only in the cell step built again."""
        seen: list[Any] = []
        for name in ("_pre_plan", "_plan_sampling", "_plan_computed", "_custody_plan", "_searched_span_s"):
            real = getattr(decision, name)

            def spy(scenario: Scenario, *args: Any, _real: Any = real, **kwargs: Any) -> Any:
                seen.append(scenario.threat)
                return _real(scenario, *args, **kwargs)

            monkeypatch.setattr(decision, name, spy)
        result = evaluate_scenario(_understanding(_held()), _MINIMAX)
        assert result.scenario.threat is not None
        assert len(seen) == 5
        assert seen == [None] * 5

    def test_the_matrix_under_each_picture_is_built_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = evaluate_scenario(_understanding(_held()), _MINIMAX)
        calls: list[Any] = []
        real = decision._build_matrix

        def counted(scenario: Scenario, plan: Any) -> Any:
            calls.append(scenario.threat)
            return real(scenario, plan)

        monkeypatch.setattr(decision, "_build_matrix", counted)
        for rule in (_MINIMAX, _MINIMIN, _EV):
            cue_relevance(result, _cue(0.5), rule)
            assert result.collection_under(rule) is not None
        assert len(calls) == 3


def test_a_result_the_engine_did_not_build_is_scored_again_from_its_cells_figures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result built by hand holds no plan to build its matrix from, so each cell is scored again from the figures
    it was built from under each outcome's picture: a picture that moves a score is still seen."""
    real = decision._score

    def nudged(scenario: Scenario, friendly: FriendlyResponse, figures: Any) -> float:
        picture = scenario.threat
        return real(scenario, friendly, figures) + (0.001 if picture is not None and picture.ceiling < Band.HIGH
                                                    else 0.0)

    monkeypatch.setattr(decision, "_score", nudged)
    result = dataclasses.replace(evaluate_scenario(_understanding(_held()), _MINIMAX), matrix_plan=None)
    relevance = cue_relevance(result, _cue(0.5), _MINIMAX)
    assert relevance.moved and not relevance.changes
    assert relevance.benign.id == relevance.hostile.id == "F1"  # type: ignore[union-attr]


# ── Where the sweep does not collect first ───────────────────────────────────

#: The sentence, before the picture's age is put beside it.
_NONE_CAN = (
    "No collection the picture holds can change the recommended response: the outcome matrix reads no Threat band"
)


class TestWhereTheSweepDoesNotCollectFirst:
    """Wherever no cue's outcomes can change the recommended response, the engine's advice says so, the sweep's own
    advice to act on the ceiling or that the range is below the action line included."""

    def test_act_on_the_ceiling_with_decide_by_passed(self) -> None:
        advice = evaluate_scenario(_understanding(_held(decide_at=_NOW - timedelta(minutes=5))), _MINIMAX).collection
        assert advice is not None and advice.advice is Advice.ACT_ON_CEILING
        assert _NONE_CAN in advice.sentence
        assert advice.sentence == (
            "Act on the ceiling: treat it as Threat CRITICAL. The Threat range runs from MEDIUM to CRITICAL, across the "
            f"action line at Threat HIGH, and decide-by has passed. {_NONE_CAN} ({_AGE})."
        )
        assert "collect first" not in advice.sentence.lower()

    def test_act_on_the_ceiling_with_the_floor_at_the_action_line(self) -> None:
        advice = evaluate_scenario(_understanding(_held(floor=Band.HIGH)), _MINIMAX).collection
        assert advice is not None and advice.advice is Advice.ACT_ON_CEILING
        assert _NONE_CAN in advice.sentence

    def test_below_the_action_line(self) -> None:
        advice = evaluate_scenario(_understanding(_held(floor=Band.LOW, ceiling=Band.MEDIUM)), _MINIMAX).collection
        assert advice is not None and advice.advice is Advice.BELOW_ACTION_LINE
        assert _NONE_CAN in advice.sentence

    def test_with_no_cue_the_sweeps_advice_stands_as_it_is(self) -> None:
        picture = _held((), decide_at=_NOW - timedelta(minutes=5))
        result = evaluate_scenario(_understanding(picture), _MINIMAX)
        assert result.collection == picture.advice(_NOW)
        assert "No collection" not in result.collection.sentence  # type: ignore[union-attr]

    def test_where_a_cues_outcomes_move_scores_but_no_pick(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = decision._score

        def nudged(scenario: Scenario, friendly: FriendlyResponse, figures: Any) -> float:
            picture = scenario.threat
            return real(scenario, friendly, figures) + (0.001 if picture is not None and picture.ceiling < Band.HIGH
                                                        else 0.0)

        monkeypatch.setattr(decision, "_score", nudged)
        advice = evaluate_scenario(_understanding(_held(decide_at=_NOW - timedelta(minutes=5))), _MINIMAX).collection
        assert advice is not None
        assert ("No collection the picture holds can change the recommended response: each cue's two outcomes give "
                f"the same one ({_AGE}).") in advice.sentence
        assert decision.NO_BAND_READ not in advice.sentence

    @pytest.mark.usefixtures("band_moves_a_figure")
    def test_a_cue_that_could_change_the_pick_but_decide_by_has_passed_adds_nothing(self) -> None:
        picture = _held(decide_at=_NOW - timedelta(minutes=5))
        advice = evaluate_scenario(_understanding(picture), _MINIMAX).collection
        assert advice is not None and advice.advice is Advice.ACT_ON_CEILING
        assert "No collection" not in advice.sentence
        assert advice == picture.advice(_NOW)

    def test_every_sentence_keeps_i13(self) -> None:
        for picture in (_held(decide_at=_NOW - timedelta(minutes=5)), _held(floor=Band.LOW, ceiling=Band.MEDIUM)):
            for text in _sentences(evaluate_scenario(_understanding(picture), _MINIMAX)):
                for sentence in text.split(". "):
                    assert i13_problems(sentence) == [], sentence


# ── The wording, everywhere ─────────────────────────────────────────────────

_SEARCHED = ("spectre/**/*.py", "spectre/web/templates/**/*.html", "spectre/web/static/**/*.js",
             "spectre/web/static/**/*.css", "docs/**/*.md", "docs/generate_guide.py", "docs/*.docx", "*.md")
#: Histories that record earlier wording, never rewritten.
_HISTORIES = ("docs/CHANGE-LEDGER.md", "CHANGELOG.md")
#: The old wording in any case, with any spacing, quotation mark or line break between its words.
_OLD_WORDING = re.compile(r"where\W+your\W+response\W+changes", re.IGNORECASE)


def _text(path: Path) -> str:
    """A file's text; for the operator guide, its document's text, each run's tags dropped."""
    if path.suffix == ".docx":
        with zipfile.ZipFile(path) as docx:
            return re.sub(r"<[^>]+>", "", docx.read("word/document.xml").decode("utf-8"))
    return path.read_text(encoding="utf-8")


def test_no_sentence_says_the_action_line_is_where_your_response_changes() -> None:
    found = [
        str(path.relative_to(_ROOT)) for pattern in _SEARCHED for path in sorted(_ROOT.glob(pattern))
        if str(path.relative_to(_ROOT)) not in _HISTORIES and _OLD_WORDING.search(_text(path))
    ]
    assert found == []


@pytest.mark.parametrize("written", [
    "where your response changes", "Where your response changes", 'where "your response changes"',
    "where your\n  response changes", "WHERE YOUR RESPONSE CHANGES",
])
def test_the_guard_finds_the_old_wording_however_it_is_written(written: str) -> None:
    assert _OLD_WORDING.search(written)


def test_the_guard_reads_the_operator_guide() -> None:
    assert "Decision Engine" in _text(_repo_only("docs/SPECTRE_Operator_Guide.docx"))


def test_the_action_line_is_described_as_what_it_is() -> None:
    assert tu.ACTION_LINE_MEANS == (
        "The action line is the Threat band at which the owner may set that a response changes: Threat HIGH by "
        "default, tuned, not sourced."
    )
    assert i13_problems(tu.ACTION_LINE_MEANS) == []


def test_the_sweeps_own_advice_keeps_its_range_narrowing_purpose_with_the_new_wording() -> None:
    advice = tu.collection_advice((Band.LOW, Band.CRITICAL), (_cue(),), now=_EPOCH,
                                  decide_at=_EPOCH + timedelta(hours=10))
    assert advice.advice is Advice.COLLECT_FIRST
    assert advice.sentence == (
        "Collect first: probe collection, about 1.0 h, lands before decide-by at 22:00 UTC on 1 Jun. The Threat range "
        "runs from LOW to CRITICAL, across the action line at Threat HIGH, and this could settle it."
    )
    assert advice.action_line == tu.ACTION_LINE_MEANS
