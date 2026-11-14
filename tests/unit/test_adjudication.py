"""The adjudication log and the coverage report (SPC-176, concept section 7.6).

An analyst records agree or disagree with the Threat range and with
Understanding for one object, with a reason. The record keeps the range and
Understanding exactly as shown, and nothing in it moves a band: an override
is logged, never applied. The coverage rate, how often the earned range held
the analyst's judgement, is computed only once 30 or more adjudications
exist; before that the report says how many more are needed. It is written
as a count, never a percentage (section 8).
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import adjudication as adj
from spectre.domain.adjudication import Adjudication, Judgement, Subject, coverage_report, record
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Understanding
from tests.unit._i13 import i13_problems

_AT = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_HASH = "a" * 64


def _subject(floor: Band = Band.MEDIUM, ceiling: Band = Band.CRITICAL, *, satno: str = "40892",
             ledger_hash: str = _HASH, understanding: Understanding = Understanding.LOW) -> Subject:
    return Subject(satno=satno, name="TJS-1", floor=floor, ceiling=ceiling, understanding=understanding,
                   ledger_hash=ledger_hash, assessed_at=_AT)


def _agree(subject: Subject | None = None, *, minutes: int = 0) -> Adjudication:
    return Adjudication(subject=subject or _subject(), on_range=Judgement.AGREE, on_understanding=Judgement.AGREE,
                        reason="consistent with the imagery", analyst="analyst1",
                        recorded_at=_AT + timedelta(minutes=minutes))


def _disagree(threat: Band, subject: Subject | None = None, **kw: object) -> Adjudication:
    args: dict[str, object] = {
        "subject": subject or _subject(), "on_range": Judgement.DISAGREE, "on_understanding": Judgement.AGREE,
        "reason": "the burn was a station-keeping move", "analyst": "analyst1", "recorded_at": _AT,
        "analyst_threat": threat}
    args.update(kw)
    return Adjudication(**args)  # type: ignore[arg-type]


class TestTheSubjectIsTheRangeAsShown:
    def test_it_refuses_a_range_with_its_floor_above_its_ceiling(self) -> None:
        with pytest.raises(ValueError, match="floor above its ceiling"):
            _subject(Band.HIGH, Band.LOW)

    @pytest.mark.parametrize("bad", ["", "a" * 63, "g" * 64, "A" * 64])
    def test_it_refuses_anything_but_a_ledger_hash(self, bad: str) -> None:
        with pytest.raises(ValueError, match="ledger hash"):
            _subject(ledger_hash=bad)

    def test_it_reads_the_range_in_words(self) -> None:
        assert _subject().range_text == "Threat range MEDIUM to CRITICAL"
        assert _subject(Band.HIGH, Band.HIGH).range_text == "Threat range HIGH"


class TestAnAdjudication:
    def test_it_needs_a_reason(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            dataclasses.replace(_agree(), reason="   ")

    def test_a_reason_is_bounded(self) -> None:
        assert len(dataclasses.replace(_agree(), reason="x" * adj.MAX_REASON).reason) == adj.MAX_REASON
        with pytest.raises(ValueError, match="reason"):
            dataclasses.replace(_agree(), reason="x" * (adj.MAX_REASON + 1))

    def test_a_reason_is_held_on_one_line(self) -> None:
        assert dataclasses.replace(_agree(), reason="  two\nlines\r\tand a tab ").reason == "two lines and a tab"

    def test_a_reason_carries_no_control_or_direction_characters(self) -> None:
        # A bidi override (U+202E) or a bell is not whitespace, so only the printable check removes it.
        reason = dataclasses.replace(_agree(), reason="burn\u202eseen\x07twice\u200bhere").reason
        assert reason == "burn seen twice here"

    def test_disagreeing_with_the_range_names_the_analysts_threat(self) -> None:
        with pytest.raises(ValueError, match="names the Threat the analyst judges"):
            _disagree(None)  # type: ignore[arg-type]

    def test_agreeing_with_the_range_names_none(self) -> None:
        with pytest.raises(ValueError, match="agreeing with the Threat range"):
            dataclasses.replace(_agree(), analyst_threat=Band.HIGH)

    def test_disagreeing_with_understanding_names_a_different_level(self) -> None:
        with pytest.raises(ValueError, match="names the Understanding the analyst judges"):
            dataclasses.replace(_agree(), on_understanding=Judgement.DISAGREE)
        with pytest.raises(ValueError, match="names the Understanding the analyst judges"):
            dataclasses.replace(_agree(), on_understanding=Judgement.DISAGREE,
                                analyst_understanding=Understanding.LOW)
        changed = dataclasses.replace(_agree(), on_understanding=Judgement.DISAGREE,
                                      analyst_understanding=Understanding.MODERATE)
        assert changed.analyst_understanding is Understanding.MODERATE

    def test_agreeing_with_understanding_names_none(self) -> None:
        with pytest.raises(ValueError, match="agreeing with Understanding"):
            dataclasses.replace(_agree(), analyst_understanding=Understanding.HIGH)

    def test_it_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            _agree().subject = _subject(Band.MINIMAL, Band.MINIMAL)  # type: ignore[misc]


class TestWhetherTheRangeHeld:
    def test_agreement_holds(self) -> None:
        assert _agree().held is True

    @pytest.mark.parametrize(("threat", "held"), [
        (Band.MINIMAL, False), (Band.LOW, False), (Band.MEDIUM, True), (Band.HIGH, True), (Band.CRITICAL, True)])
    def test_a_disagreement_holds_only_inside_the_range(self, threat: Band, held: bool) -> None:
        assert _disagree(threat).held is held


class TestAnOverrideNeverChangesABand:
    def test_the_record_keeps_the_range_and_understanding_as_shown(self) -> None:
        subject = _subject()
        entry = _disagree(Band.MINIMAL, subject, on_understanding=Judgement.DISAGREE,
                          analyst_understanding=Understanding.HIGH)
        assert entry.subject is subject
        assert (entry.subject.floor, entry.subject.ceiling, entry.subject.understanding) == (
            Band.MEDIUM, Band.CRITICAL, Understanding.LOW)

    def test_recording_returns_a_new_log_and_leaves_the_old_one(self) -> None:
        before = (_agree(),)
        after = record(before, _disagree(Band.MINIMAL, _subject(satno="1", ledger_hash="b" * 64)))
        assert before == (_agree(),)
        assert len(after) == 2
        assert after[0] is before[0]

    def test_the_module_offers_nothing_that_returns_a_band(self) -> None:
        public = [getattr(adj, name) for name in adj.__all__]
        functions = [f for f in public if inspect.isfunction(f)]
        assert functions
        for function in functions:
            assert "Band" not in str(inspect.signature(function).return_annotation), function.__name__


class TestTheLog:
    def test_a_second_adjudication_of_the_same_picture_replaces_the_first(self) -> None:
        first = _agree()
        second = _disagree(Band.LOW)
        log = record(record((), first), second)
        assert log == (second,)

    def test_another_analyst_on_the_same_picture_is_another_entry(self) -> None:
        mine = _agree()
        theirs = dataclasses.replace(_agree(), analyst="analyst2")
        assert record(record((), mine), theirs) == (mine, theirs)

    def test_another_picture_of_the_same_object_is_another_entry(self) -> None:
        log = record(record((), _agree()), _agree(_subject(ledger_hash="c" * 64)))
        assert len(log) == 2

    def test_it_holds_at_most_max_held_the_newest_kept(self) -> None:
        log: tuple[Adjudication, ...] = ()
        for k in range(adj.MAX_HELD + 3):
            log = record(log, _agree(_subject(satno=str(k)), minutes=k))
        assert len(log) == adj.MAX_HELD
        assert log[0].subject.satno == "3"
        assert log[-1].subject.satno == str(adj.MAX_HELD + 2)


def _log(held: int, missed: int) -> tuple[Adjudication, ...]:
    log: tuple[Adjudication, ...] = ()
    for k in range(held):
        log = record(log, _agree(_subject(satno=f"h{k}")))
    for k in range(missed):
        log = record(log, _disagree(Band.MINIMAL, _subject(satno=f"m{k}")))
    return log


class TestTheCoverageReport:
    def test_with_none_it_says_how_many_are_needed(self) -> None:
        report = coverage_report(())
        assert (report.count, report.held, report.rate) == (0, 0, None)
        assert report.sentence == "No adjudications are recorded yet. A coverage rate needs 30, so 30 more are needed."

    def test_one_short_of_thirty_it_is_not_computed(self) -> None:
        report = coverage_report(_log(20, 9))
        assert (report.count, report.held, report.rate) == (29, 20, None)
        assert report.sentence == "29 adjudications are recorded. A coverage rate needs 30, so 1 more is needed."

    def test_one_reads_as_one(self) -> None:
        assert coverage_report(_log(1, 0)).sentence == (
            "1 adjudication is recorded. A coverage rate needs 30, so 29 more are needed.")

    def test_at_thirty_it_is_computed_and_written_as_a_count(self) -> None:
        assert adj.MIN_FOR_COVERAGE == 30
        report = coverage_report(_log(27, 3))
        assert (report.count, report.held) == (30, 27)
        assert report.rate == pytest.approx(0.9)
        assert report.sentence == "The earned Threat range held the analyst's judgement in 27 of 30 adjudications."

    def test_above_thirty_too(self) -> None:
        report = coverage_report(_log(31, 4))
        assert report.rate == pytest.approx(31 / 35)
        assert "31 of 35" in report.sentence

    @pytest.mark.parametrize("n", [0, 1, 2, 29, 30, 31])
    def test_no_percentage_and_no_shared_sentence(self, n: int) -> None:
        sentence = coverage_report(_log(n, 0)).sentence
        for part in sentence.split(". "):
            assert i13_problems(part) == [], part


class TestEachEntryInWords:
    def test_an_agreement(self) -> None:
        assert _agree().summary == (
            "TJS-1 (40892), Threat range MEDIUM to CRITICAL: agreed. Understanding LOW: agreed. "
            "Reason: consistent with the imagery.")

    def test_a_disagreement_outside_the_range(self) -> None:
        entry = _disagree(Band.LOW, on_understanding=Judgement.DISAGREE, analyst_understanding=Understanding.MODERATE)
        assert entry.summary == (
            "TJS-1 (40892), Threat range MEDIUM to CRITICAL: disagreed, the analyst judges Threat LOW, outside "
            "the range. Understanding LOW: disagreed, the analyst judges Understanding MODERATE. "
            "Reason: the burn was a station-keeping move.")

    def test_a_disagreement_inside_the_range(self) -> None:
        assert "the analyst judges Threat HIGH, inside the range" in _disagree(Band.HIGH).summary

    @pytest.mark.parametrize("entry", [
        _agree(), _disagree(Band.LOW), _disagree(Band.HIGH, on_understanding=Judgement.DISAGREE,
                                                 analyst_understanding=Understanding.HIGH)])
    def test_each_sentence_keeps_threat_and_understanding_apart(self, entry: Adjudication) -> None:
        body = entry.summary.split(" Reason: ")[0]
        for sentence in body.split(". "):
            assert i13_problems(sentence) == [], sentence
