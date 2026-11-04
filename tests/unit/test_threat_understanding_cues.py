"""Threat Understanding, SPC-170: cues and the value of information.

Section 4.10 of docs/threat_confidence_concept.md. For each dimension not yet
earned, SPECTRE re-runs the range twice with one hypothetical group of the
cue's typical grade: once carrying the most benign reading the dimension
admits, once the most hostile. The steps of range the cue would remove are

    VOI = (ceiling now - ceiling benign) + (floor hostile - floor now)

and cues are ranked by steps per hour to collect. Contrast B of section 4.12
is the fixed case: conjunctions, then a second provider's history, then the
analyst dating the record. Each cue names the observation, the steps it
would remove and the time it takes. Every unearned dimension carries one
(I11).
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Depth, Dimension, EvidenceItem, HeldBurn, Situation
from tests.unit.test_threat_understanding_worked_example import (
    _BURN,
    _INTEL,
    _NOW,
    _ROWS,
    _UDL_BURN,
    _UDL_RESERVE,
    _situation,
)

_CONJUNCTIONS = "hold UDL conjunctions for it"
_SECOND = "pull a second provider's element-set history"
_FIRST = "pull its element-set history"
_RECORD = "analyst to date and source the intel record"
_GCAT = "pull its GCAT catalogue entry"


def _contrast_b() -> tuple[tuple[EvidenceItem, ...], Situation]:
    """Row 4 of the worked example, but the latest burn is ROUTINE. Its record's role is CRITICAL (row 1)."""
    routine = replace(_UDL_BURN, label="latest burn, routine", floor_to=None, routine=True)
    situation = _situation(4, burns=(HeldBurn(_BURN, Normality.ROUTINE),))
    return (*_ROWS[:3], routine), tu.with_record(situation, {"threat_level": "CRITICAL"})


def _row(row: int) -> tuple[tuple[EvidenceItem, ...], Situation]:
    return _ROWS[:row], _situation(row)


#: Every case the tests below sweep: the eight rows of section 4.12 and contrast B.
_CASES = [*(_row(r) for r in range(8)), _contrast_b()]


def _summary(cues: tuple[tu.Cue, ...]) -> list[tuple[str, int, float, float]]:
    return [(c.observation, c.steps, c.hours, c.steps_per_hour) for c in cues]


class TestContrastB:
    def test_it_ranks_as_in_section_4_12(self) -> None:
        cues = tu.cues(*_contrast_b())
        assert _summary(cues) == [(_CONJUNCTIONS, 3, 0.25, 12.0), (_SECOND, 4, 0.5, 8.0), (_RECORD, 2, 4.0, 0.5)]
        assert [c.effect for c in cues] == [
            "could raise the Threat floor to HIGH", "could lower the Threat ceiling to MINIMAL",
            "could raise the Threat floor to MEDIUM"]

    def test_each_cue_carries_the_two_hypothetical_ranges(self) -> None:
        conjunctions, second, record = tu.cues(*_contrast_b())
        assert (conjunctions.benign, conjunctions.hostile) == ((Band.MINIMAL, Band.CRITICAL), (Band.HIGH, Band.CRITICAL))
        assert (second.benign, second.hostile) == ((Band.MINIMAL, Band.MINIMAL), (Band.MINIMAL, Band.CRITICAL))
        assert record.hostile == (Band.MEDIUM, Band.CRITICAL)

    def test_the_cues_name_the_dimensions_they_would_close(self) -> None:
        assert [c.dimensions for c in tu.cues(*_contrast_b())] == [
            (Dimension.INTERACTIONS,), (Dimension.CAPABILITY,), (Dimension.IDENTITY,)]


class TestTheOrder:
    def test_order_follows_steps_per_hour_not_steps(self) -> None:
        cues = tu.cues(*_contrast_b())
        by_steps = sorted(cues, key=lambda c: -c.steps)
        assert [c.observation for c in by_steps] != [c.observation for c in cues]
        assert [c.steps_per_hour for c in cues] == sorted((c.steps_per_hour for c in cues), reverse=True)

    @pytest.mark.parametrize("case", range(len(_CASES)))
    def test_every_case_is_ranked_by_steps_per_hour_then_by_time(self, case: int) -> None:
        cues = tu.cues(*_CASES[case])
        assert cues
        keys = [(-c.steps_per_hour, c.hours, c.observation) for c in cues]
        assert keys == sorted(keys)

    def test_steps_per_hour_is_steps_over_hours(self) -> None:
        for cue in tu.cues(*_contrast_b()):
            assert cue.steps_per_hour == pytest.approx(cue.steps / cue.hours)


class TestValueOfInformation:
    def test_voi_is_zero_when_both_hypotheticals_give_the_same_range(self) -> None:
        # Row 5: the floor is HIGH on the burn and its allied track; a hostile approach
        # could raise it no further and Interactions has no benign reading.
        items, situation = _row(5)
        now = tu.threat_range(items, situation)
        (conjunctions,) = [c for c in tu.cues(items, situation) if c.observation == _CONJUNCTIONS]
        assert conjunctions.benign == conjunctions.hostile == (now.floor, now.ceiling)
        assert conjunctions.steps == 0
        assert conjunctions.effect == "would firm up Interactions and move no Threat band"

    @pytest.mark.parametrize("case", range(len(_CASES)))
    def test_steps_follow_the_formula_within_the_range(self, case: int) -> None:
        items, situation = _CASES[case]
        now = tu.threat_range(items, situation)
        width = int(now.ceiling) - int(now.floor)
        for cue in tu.cues(items, situation):
            # I1: a hypothetical group never widens the range, so neither half of the sum is negative.
            ceiling_half, floor_half = int(now.ceiling) - int(cue.benign[1]), int(cue.hostile[0]) - int(now.floor)
            assert ceiling_half >= 0 and floor_half >= 0, cue.observation
            assert cue.steps == min(width, ceiling_half + floor_half), cue.observation
            if cue.benign == cue.hostile == (now.floor, now.ceiling):
                assert cue.steps == 0, cue.observation

    def test_a_cue_never_removes_more_steps_than_the_range_has(self) -> None:
        # Capability and Behaviour both partial on one history: a second provider could
        # lower the ceiling to MINIMAL (4 steps) or raise the floor to HIGH (3 steps).
        partial = EvidenceItem(
            dimension=Dimension.BEHAVIOUR, label="anomaly index 20", derived_from="elset-history:UDL",
            source_grade="B", credibility=2, extraction=tu.ASSUMED_FIGURE_EXTRACTION, basis=Basis.LOOKUP,
            observed_at=_NOW, controlled=True)
        items = (_UDL_RESERVE, partial)
        situation = _situation(0)
        (second,) = [c for c in tu.cues(items, situation) if c.observation == _SECOND]
        assert (second.benign[1], second.hostile[0]) == (Band.MINIMAL, Band.HIGH)
        assert second.steps == 4
        assert second.dimensions == (Dimension.CAPABILITY, Dimension.BEHAVIOUR)
        assert second.effect == "could raise the Threat floor to HIGH or lower the Threat ceiling to MINIMAL"

    def test_asking_changes_nothing_held(self) -> None:
        items, situation = _contrast_b()
        before = tu.assess(items, situation)
        tu.cues(items, situation)
        assert tu.assess(items, situation) == before


class TestWhichCuesAreOffered:
    @pytest.mark.parametrize("case", range(len(_CASES)))
    def test_no_collection_cue_for_an_earned_dimension(self, case: int) -> None:
        items, situation = _CASES[case]
        coverage = tu.threat_range(items, situation).coverage
        for cue in tu.cues(items, situation):
            if not cue.record:
                assert all(tu.depth(coverage[d]) is not Depth.EARNED for d in cue.dimensions), cue.observation

    def test_with_every_dimension_earned_only_the_record_cue_is_left(self) -> None:
        items, situation = _row(7)
        coverage = tu.threat_range(items, situation).coverage
        assert all(tu.depth(u) is Depth.EARNED for u in coverage.values())
        assert [c.observation for c in tu.cues(items, situation)] == [_RECORD]

    @pytest.mark.parametrize("case", range(len(_CASES)))
    def test_every_unearned_dimension_carries_a_cue(self, case: int) -> None:
        """I11, the cue half."""
        items, situation = _CASES[case]
        coverage = tu.threat_range(items, situation).coverage
        offered = {d for c in tu.cues(items, situation) for d in c.dimensions}
        assert {d for d, u in coverage.items() if tu.depth(u) is not Depth.EARNED} <= offered

    def test_with_nothing_held_the_catalogue_and_the_history_are_the_cues(self) -> None:
        cues = tu.cues((), _situation(0))
        assert _summary(cues) == [(_CONJUNCTIONS, 3, 0.25, 12.0), (_FIRST, 3, 0.5, 6.0), (_GCAT, 0, 0.25, 0.0)]
        assert cues[1].dimensions == (Dimension.CAPABILITY, Dimension.BEHAVIOUR)

    def test_a_held_catalogue_entry_is_refreshed_not_pulled_again(self) -> None:
        old = replace(_ROWS[1], observed_at=_NOW.replace(year=2024))
        (identity,) = [c for c in tu.cues((old,), _situation(0)) if Dimension.IDENTITY in c.dimensions]
        assert identity.observation == "refresh its GCAT catalogue entry"

    def test_a_dated_record_needs_no_dating(self) -> None:
        dated = replace(_INTEL, observed_at=_NOW, credibility=2)
        assert _RECORD not in [c.observation for c in tu.cues((dated, *_ROWS[1:4]), _situation(4))]

    def test_one_record_cue_however_many_items_the_record_gave(self) -> None:
        status = EvidenceItem(
            dimension=Dimension.CAPABILITY, label="recorded status Operational", derived_from="status:RED-GEO-1",
            source_grade="D", credibility=3, extraction=tu.ASSESSED_LABEL_EXTRACTION, basis=Basis.LOOKUP,
            observed_at=None, manufacturable=True)
        copy = replace(_INTEL, label="intel record, second reading")
        observations = [c.observation for c in tu.cues((_INTEL, copy, status, *_ROWS[1:4]), _situation(4))]
        assert observations.count(_RECORD) == 1


_BAND_WORDS = re.compile(r"\b(MINIMAL|LOW|MEDIUM|HIGH|CRITICAL|MODERATE)\b")


class TestTheCueWords:
    def test_each_cue_names_the_observation_the_steps_and_the_time(self) -> None:
        assert [tu.cue_text(c) for c in tu.cues(*_contrast_b())] == [
            "hold UDL conjunctions for it: could raise the Threat floor to HIGH, 3 Threat steps, about 15 min",
            "pull a second provider's element-set history: could lower the Threat ceiling to MINIMAL, "
            "4 Threat steps, about 30 min",
            "analyst to date and source the intel record: could raise the Threat floor to MEDIUM, "
            "2 Threat steps, about 4.0 h"]

    def test_one_step_is_singular(self) -> None:
        cue = tu.Cue(observation="x", dimensions=(Dimension.IDENTITY,), steps=1, hours=2.0, effect="y",
                     benign=(Band.MINIMAL, Band.LOW), hostile=(Band.LOW, Band.LOW))
        assert tu.cue_text(cue) == "x: y, 1 Threat step, about 2.0 h"

    @pytest.mark.parametrize("case", range(len(_CASES)))
    def test_no_bare_band_and_no_percentage(self, case: int) -> None:
        for cue in tu.cues(*_CASES[case]):
            text = tu.cue_text(cue)
            assert "%" not in text and "per cent" not in text
            assert "Understanding" not in text
            for match in _BAND_WORDS.finditer(text):
                assert "Threat" in text[:match.start()], text


class TestWhatIsMissing:
    def test_with_nothing_held_everything_is_missing(self) -> None:
        assert tu.missing(tu.threat_range((), _situation(0))) == (
            "Identity not earned", "Capability not earned", "Behaviour not earned", "Interactions not earned",
            "no intel record held", "no GCAT catalogue entry held", "no element-set history held",
            "no own or allied sensor track", "no approaches or conjunctions held", "photometry not uploaded",
            "no NOTSO filing held")

    def test_at_row_4_a_second_provider_is_missing(self) -> None:
        assert tu.missing(tu.threat_range(*_row(4))) == (
            "Capability partial", "Interactions not earned", "no second provider's history",
            "no own or allied sensor track", "no approaches or conjunctions held", "photometry not uploaded",
            "no NOTSO filing held")

    def test_at_row_7_only_what_the_model_cannot_yet_hold_is_missing(self) -> None:
        assert tu.missing(tu.threat_range(*_row(7))) == ("photometry not uploaded", "no NOTSO filing held")

    def test_held_photometry_and_notso_are_not_missing(self) -> None:
        held = [EvidenceItem(dimension=Dimension.BEHAVIOUR, label=label, derived_from=root, source_grade="C",
                             credibility=2, extraction=0.5, basis=Basis.SAMPLED, observed_at=_NOW)
                for label, root in (("photometry change", "photometry:upload"), ("NOTSO filing", "notso:op"))]
        found = tu.missing(tu.threat_range((*_ROWS[:7], *held), _situation(7)))
        assert "photometry not uploaded" not in found and "no NOTSO filing held" not in found


class TestAssessCarriesTheCues:
    def test_on_request_and_not_otherwise(self) -> None:
        items, situation = _contrast_b()
        assert tu.assess(items, situation).cues == ()
        assert tu.assess(items, situation, with_cues=True).cues == tu.cues(items, situation)


class TestOnlyWhatSpectreCanReadIsFed:
    """A cue is fed when SPECTRE can take what it collects into the model today.

    Nothing turns a conjunction into evidence until SPC-172 and SPC-173, and
    the sweep holds one merged history per object (section 9, decision 8), so
    those two cues are worked out, ranked and kept, but marked as not fed.
    """

    def test_contrast_b_keeps_its_ranking_and_marks_the_two_it_cannot_read(self) -> None:
        assert [(c.observation, c.fed) for c in tu.cues(*_contrast_b())] == [
            (_CONJUNCTIONS, False), (_SECOND, False), (_RECORD, True)]

    def test_with_nothing_held_the_history_and_the_catalogue_are_fed(self) -> None:
        assert [(c.observation, c.fed) for c in tu.cues((), _situation(0))] == [
            (_CONJUNCTIONS, False), (_FIRST, True), (_GCAT, True)]


class TestTheRecordCueFollowsTheRecordsLevel:
    """Section 5.1: a dated and sourced record sets floor MEDIUM only when its threat level is HIGH or CRITICAL."""

    @pytest.mark.parametrize("level", ["HIGH", "CRITICAL"])
    def test_a_high_or_critical_record_could_raise_the_floor_to_medium(self, level: str) -> None:
        situation = tu.with_record(_situation(3), {"threat_level": level})
        assert situation.record_prior is Band.MEDIUM
        (record,) = [c for c in tu.cues(_ROWS[:3], situation) if c.record]
        assert record.hostile == (Band.MEDIUM, Band.CRITICAL)
        assert record.effect == "could raise the Threat floor to MEDIUM"

    @pytest.mark.parametrize("level", ["MINIMAL", "LOW", "MEDIUM", "", "unknown"])
    def test_any_lower_level_moves_no_band_when_dated(self, level: str) -> None:
        situation = tu.with_record(_situation(0), {"threat_level": level})
        assert situation.record_prior is None
        (record,) = [c for c in tu.cues((_INTEL, *_ROWS[1:2]), situation) if c.record]
        assert record.hostile == record.benign == (Band.MINIMAL, Band.CRITICAL)
        assert (record.steps, record.effect) == (0, "would firm up Identity and move no Threat band")

    def test_with_no_record_given_no_prior_is_assumed(self) -> None:
        assert tu.with_record(_situation(0), None).record_prior is None
        (record,) = [c for c in tu.cues((_INTEL,), _situation(0)) if c.record]
        assert record.steps == 0


class TestTheCueWithNoInterceptInView:
    """With no intercept there is no ACCESS, so a cue names what it firms up and its time, not Threat steps."""

    def test_it_names_the_dimensions_and_the_time_and_no_threat_band(self) -> None:
        assert [tu.cue_text(c, threat=False) for c in tu.cues(*_contrast_b())] == [
            "hold UDL conjunctions for it: would firm up Interactions, about 15 min",
            "pull a second provider's element-set history: would firm up Capability, about 30 min",
            "analyst to date and source the intel record: would firm up Identity, about 4.0 h"]

    def test_two_dimensions_are_both_named(self) -> None:
        (history,) = [c for c in tu.cues((), _situation(0)) if c.observation == _FIRST]
        assert tu.cue_text(history, threat=False) == (
            "pull its element-set history: would firm up Capability and Behaviour, about 30 min")


class TestTheBenignBehaviourHypotheticalIsRoutine:
    def test_benign_behaviour_is_a_routine_burn_and_nothing_else_is(self) -> None:
        def probe(dimension: Dimension) -> tu._Probe:
            return tu._Probe(dimension, "hypothetical:x", "B", 2, 0.9, Basis.COMPUTED)

        assert probe(Dimension.BEHAVIOUR).item(_NOW, hostile=False).routine is True
        assert probe(Dimension.BEHAVIOUR).item(_NOW, hostile=True).routine is False
        assert probe(Dimension.CAPABILITY).item(_NOW, hostile=False).routine is False


class TestCustodyAcrossTheHistorysWindow:
    """Section 5.3: "no burns" counts only if custody was held across the window, judged on the history's own sets.

    Every panel judges it the same way, so one object reads one strip whichever
    element set the panel itself is looking at.
    """

    _SIGNALS = tu.HistorySignals(provider="18SDS", newest_at=_NOW - timedelta(hours=6), span_days=60.0,
                                 detection_floor_m_s=0.4)

    def test_a_newest_set_within_the_limit_holds_custody(self) -> None:
        assert tu.window_custody(self._SIGNALS, _NOW, 72.0) is Custody.HELD
        assert tu.window_custody(self._SIGNALS, _NOW, 6.0) is Custody.HELD

    def test_a_newest_set_past_the_limit_loses_it(self) -> None:
        assert tu.window_custody(self._SIGNALS, _NOW, 5.9) is Custody.LOST

    def test_a_truncated_history_degrades_it(self) -> None:
        assert tu.window_custody(replace(self._SIGNALS, truncated=True), _NOW, 72.0) is Custody.DEGRADED
