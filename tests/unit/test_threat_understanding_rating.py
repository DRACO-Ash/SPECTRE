"""Threat Understanding, SPC-164: the three categories, the caps and the statement.

One case per criterion row of section 6.1 of docs/threat_confidence_concept.md,
one per cap of section 6.2, the statement of section 6.3, and the
Understanding halves of the invariants I1, I3 and I4. The weakest category
governs, as PHIA's Analytical Confidence Rating and SPECTRE's own
``provenance.weakest()`` both read it.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import (
    Dimension,
    EvidenceItem,
    HeldBurn,
    Situation,
    ThreatUnderstanding,
    Understanding,
)

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_DAY = timedelta(days=1)
_BURN_AT = _NOW - 2 * _DAY


def _item(**kw: object) -> EvidenceItem:
    args: dict[str, object] = {
        "dimension": Dimension.BEHAVIOUR, "label": "burn", "derived_from": "elset-history:UDL",
        "source_grade": "B", "credibility": 2, "extraction": 0.9, "basis": Basis.COMPUTED,
        "observed_at": _NOW,
    }
    args.update(kw)
    return EvidenceItem(**args)  # type: ignore[arg-type]


def _sit(**kw: object) -> Situation:
    args: dict[str, object] = {"now": _NOW, "access": Band.CRITICAL, "custody": Custody.HELD,
                               "history_truncated": False, "data_mode": "REAL", "newest_elset_at": _NOW}
    args.update(kw)
    return Situation(**args)  # type: ignore[arg-type]


def _assess(items: Sequence[EvidenceItem], **kw: object) -> ThreatUnderstanding:
    return tu.assess(items, _sit(**kw))


def _why(rating: tu.UnderstandingRating, name: str) -> str:
    """The reason a category or cap gives for falling short of HIGH."""
    return dict(rating.reasons)[name]


# Strong, independent items, one per dimension, each earning it alone.
_IDENTITY = _item(dimension=Dimension.IDENTITY, label="gcat", derived_from="gcat:1", extraction=1.0)
_CAPABILITY = _item(dimension=Dimension.CAPABILITY, label="reserve", extraction=0.8)
_BEHAVIOUR = _item(label="burn", observed_at=_BURN_AT, floor_to=Band.HIGH, controlled=True)
_INTERACTIONS = _item(dimension=Dimension.INTERACTIONS, label="approach", derived_from="approach:1")
_SETTLED = HeldBurn(_NOW - 30 * _DAY, Normality.UNPRECEDENTED)


class TestInformationBase:
    """HIGH: Identity (or Interactions), Capability and Behaviour earned, two chains, an A or B in C or B."""

    def test_high_with_every_criterion_met(self) -> None:
        rating = _assess([_IDENTITY, _CAPABILITY, _BEHAVIOUR]).understanding
        assert rating.information_base is Understanding.HIGH

    def test_interactions_may_stand_in_for_identity(self) -> None:
        rating = _assess([_INTERACTIONS, _CAPABILITY, _BEHAVIOUR]).understanding
        assert rating.information_base is Understanding.HIGH

    def test_one_source_chain_is_not_enough_for_high(self) -> None:
        one_chain = [replace(i, derived_from="elset-history:UDL") for i in (_IDENTITY, _CAPABILITY, _BEHAVIOUR)]
        rating = _assess(one_chain).understanding
        assert rating.information_base is Understanding.MODERATE
        assert _why(rating, "information base") == "one source chain only"

    def test_an_a_or_b_grade_in_capability_or_behaviour_is_needed_for_high(self) -> None:
        graded_c = [_IDENTITY, *(replace(i, source_grade="C", credibility=1, extraction=1.0)
                                 for i in (_CAPABILITY, _BEHAVIOUR))]
        rating = _assess(graded_c).understanding
        assert rating.information_base is Understanding.MODERATE
        assert _why(rating, "information base") == "no source graded A or B in Capability or Behaviour"

    def test_moderate_with_two_dimensions_one_of_them_behaviour(self) -> None:
        rating = _assess([_IDENTITY, _BEHAVIOUR]).understanding
        assert rating.information_base is Understanding.MODERATE
        assert _why(rating, "information base") == "Capability not earned"

    def test_moderate_with_two_dimensions_one_a_computed_capability_reading(self) -> None:
        reading = replace(_CAPABILITY, ceiling_to=Band.MEDIUM)
        assert _assess([_IDENTITY, reading]).understanding.information_base is Understanding.MODERATE

    @pytest.mark.parametrize("basis", [Basis.LOOKUP, Basis.SAMPLED])
    def test_two_dimensions_without_behaviour_or_a_computed_capability_reading_are_low(self, basis: Basis) -> None:
        reading = replace(_CAPABILITY, ceiling_to=Band.MEDIUM, basis=basis)
        assert _assess([_IDENTITY, reading]).understanding.information_base is Understanding.LOW
        assert _assess([_IDENTITY, _CAPABILITY]).understanding.information_base is Understanding.LOW

    def test_a_rejected_detection_from_a_second_provider_is_not_a_second_source_chain(self) -> None:
        # Held, but q 0: it founds nothing, so the information base still rests on one chain.
        one_chain = [replace(i, derived_from="elset-history:UDL") for i in (_IDENTITY, _CAPABILITY, _BEHAVIOUR)]
        rejected = _item(label="second provider burn", derived_from="elset-history:COMM", source_grade="A",
                         extraction=tu.burn_extraction("REJECT"))
        rating = _assess([*one_chain, rejected]).understanding
        assert rating.information_base is Understanding.MODERATE
        assert _why(rating, "information base") == "one source chain only"

    def test_an_item_that_counts_with_a_chain_is_not_a_second_source_chain(self) -> None:
        """SPC-174 review finding 1: a propagation item rests on its edge's burns, so it adds no chain of its own."""
        one_chain = [replace(i, derived_from="elset-history:UDL") for i in (_IDENTITY, _CAPABILITY, _BEHAVIOUR)]
        derived = _item(dimension=Dimension.INTERACTIONS, label="1 hop from a hostile seed", derived_from="seed:1",
                        counts_with="elset-history:UDL")
        rating = _assess([*one_chain, derived]).understanding
        assert rating.information_base is Understanding.MODERATE
        assert _why(rating, "information base") == "one source chain only"

    def test_an_a_grade_with_no_standing_is_not_a_well_graded_source(self) -> None:
        graded_c = [_IDENTITY, *(replace(i, source_grade="C", credibility=1, extraction=1.0)
                                 for i in (_CAPABILITY, _BEHAVIOUR))]
        faint = _item(label="faint allied track", derived_from="allied:optical", source_grade="A", extraction=0.1)
        rating = _assess([*graded_c, faint]).understanding
        assert _why(rating, "information base") == "no source graded A or B in Capability or Behaviour"

    def test_one_dimension_is_low(self) -> None:
        rating = _assess([_BEHAVIOUR]).understanding
        assert rating.information_base is Understanding.LOW
        assert _why(rating, "information base") == "Identity not earned, Capability not earned"


class TestAnalyticalRigour:
    """The weakest basis among the readings that set the floor and the ceiling."""

    def test_high_when_a_computed_controlled_reading_sets_the_floor_and_access_the_ceiling(self) -> None:
        assert _assess([_BEHAVIOUR]).understanding.rigour is Understanding.HIGH

    def test_moderate_with_no_reading_because_access_alone_is_uncontrolled(self) -> None:
        rating = _assess([_IDENTITY]).understanding
        assert rating.rigour is Understanding.MODERATE
        assert _why(rating, "analytical rigour") == "computed from uncontrolled sources only"

    def test_moderate_when_the_computed_reading_is_uncontrolled(self) -> None:
        assert _assess([replace(_BEHAVIOUR, controlled=False)]).understanding.rigour is Understanding.MODERATE

    def test_moderate_when_a_sampled_figure_governs(self) -> None:
        rating = _assess([replace(_BEHAVIOUR, basis=Basis.SAMPLED)]).understanding
        assert rating.rigour is Understanding.MODERATE
        assert _why(rating, "analytical rigour") == "the floor rests on a sampled figure (burn)"

    def test_low_when_a_lookup_sets_the_floor(self) -> None:
        role = _item(dimension=Dimension.IDENTITY, label="dated role", derived_from="intel:1", extraction=0.5,
                     basis=Basis.LOOKUP, floor_to=Band.MEDIUM)
        rating = _assess([_IDENTITY, role]).understanding
        assert rating.rigour is Understanding.LOW
        assert _why(rating, "analytical rigour") == "the floor rests on a lookup (dated role)"

    def test_low_when_a_lookup_sets_the_ceiling(self) -> None:
        share = replace(_CAPABILITY, label="share", ceiling_to=Band.MEDIUM, basis=Basis.LOOKUP)
        rating = _assess([share]).understanding
        assert rating.rigour is Understanding.LOW
        assert _why(rating, "analytical rigour") == "the ceiling rests on a lookup (share)"

    def test_a_lookup_beside_a_computed_reading_at_the_same_band_does_not_govern(self) -> None:
        posture = replace(_BEHAVIOUR, label="posture", floor_to=Band.MEDIUM)
        anomaly = _item(label="anomaly", derived_from="anomaly:1", basis=Basis.LOOKUP, floor_to=Band.MEDIUM,
                        observed_at=_BURN_AT)
        assert _assess([posture, anomaly]).understanding.rigour is Understanding.HIGH

    def test_a_superseded_reading_lends_the_floor_nothing(self) -> None:
        # 120 days after an unprecedented burn, a later unusual burn has superseded its floor.
        # The floor now rests on the dated role, a lookup, so rigour is LOW, however strong
        # the superseded burn once was.
        now = _NOW + 120 * _DAY
        burns = (HeldBurn(_NOW, Normality.UNPRECEDENTED), HeldBurn(_NOW + 30 * _DAY, Normality.UNUSUAL))
        old = replace(_BEHAVIOUR, label="old burn", observed_at=_NOW)
        gcat = replace(_IDENTITY, observed_at=now - _DAY, basis=Basis.LOOKUP)
        role = _item(dimension=Dimension.IDENTITY, label="dated role", derived_from="intel:1", extraction=0.5,
                     observed_at=now - _DAY, basis=Basis.LOOKUP, floor_to=Band.MEDIUM)
        result = _assess([gcat, role, old], now=now, burns=burns, newest_elset_at=now)
        assert (result.range.floor, result.range.floor_support) == (
            Band.MEDIUM, tu.Support("dated role", Basis.LOOKUP, controlled=False))
        assert result.understanding.rigour is Understanding.LOW
        assert _why(result.understanding, "analytical rigour") == "the floor rests on a lookup (dated role)"

    def test_a_lapsed_lookup_ceiling_still_counts_so_ageing_cannot_raise_rigour(self) -> None:
        share = replace(_CAPABILITY, label="share", derived_from="share:1", ceiling_to=Band.MEDIUM,
                        basis=Basis.LOOKUP, source_grade="C", credibility=2, extraction=1.0)
        fresh = _assess([_CAPABILITY, share])
        assert (fresh.range.ceiling, fresh.understanding.rigour) == (Band.MEDIUM, Understanding.LOW)
        aged = _assess([_CAPABILITY, share], now=_NOW + 120 * _DAY)
        assert aged.range.ceiling is Band.CRITICAL
        assert aged.understanding.rigour is Understanding.LOW
        assert _why(aged.understanding, "analytical rigour") == (
            "the ceiling rested on a lookup (share), since decayed")

    def test_a_lapsed_ceiling_never_raises_rigour(self) -> None:
        # A computed, controlled ceiling that has lapsed lends the range nothing either.
        spent = replace(_CAPABILITY, label="spent", derived_from="allied:fuel", source_grade="A", credibility=1,
                        extraction=1.0, controlled=True, ceiling_to=Band.MINIMAL)
        aged = _assess([spent, _IDENTITY], now=_NOW + 300 * _DAY, newest_elset_at=_NOW + 300 * _DAY)
        assert aged.range.ceiling is Band.CRITICAL
        assert aged.understanding.rigour is Understanding.MODERATE

    def test_a_lookup_below_the_floor_does_not_govern(self) -> None:
        anomaly = _item(label="anomaly", basis=Basis.LOOKUP, floor_to=Band.MEDIUM, observed_at=_BURN_AT)
        assert _assess([_BEHAVIOUR, anomaly]).understanding.rigour is Understanding.HIGH


class TestComplexityAndVolatility:
    """HIGH: custody held, no conflict, the latest burn ROUTINE or held for 3 element-set limits."""

    def test_high_with_a_routine_latest_burn(self) -> None:
        rating = _assess([_BEHAVIOUR], burns=(HeldBurn(_BURN_AT, Normality.ROUTINE),)).understanding
        assert rating.volatility is Understanding.HIGH

    def test_high_with_no_burn_held(self) -> None:
        assert _assess([_BEHAVIOUR]).understanding.volatility is Understanding.HIGH

    @pytest.mark.parametrize(("regime", "limit_h", "held_days", "level"), [
        ("GEO", 72.0, 9.0, Understanding.HIGH),
        ("GEO", 72.0, 8.9, Understanding.MODERATE),
        ("LEO", 24.0, 3.0, Understanding.HIGH),
        ("LEO", 24.0, 2.9, Understanding.MODERATE),
    ])
    def test_a_hostile_burn_settles_after_3_element_set_limits_of_held_orbit(
        self, regime: str, limit_h: float, held_days: float, level: Understanding,
    ) -> None:
        burn = HeldBurn(_NOW - 10 * _DAY, Normality.UNPRECEDENTED)
        rating = _assess([_BEHAVIOUR], burns=(burn,), regime=regime, elset_limit_hours=limit_h,
                         newest_elset_at=burn.epoch + held_days * _DAY).understanding
        assert rating.volatility is level

    def test_an_unsettled_burn_is_named_with_its_age(self) -> None:
        rating = _assess([_BEHAVIOUR], burns=(HeldBurn(_NOW - timedelta(hours=33), Normality.UNUSUAL),)).understanding
        assert rating.volatility is Understanding.MODERATE
        assert _why(rating, "volatility") == "an unusual burn 1.4 d ago whose new orbit is not yet settled"

    def test_a_burn_too_little_history_to_judge_is_not_settled_either(self) -> None:
        rating = _assess([_BEHAVIOUR], burns=(HeldBurn(_BURN_AT, Normality.NOT_ENOUGH_HISTORY),)).understanding
        assert rating.volatility is Understanding.MODERATE
        assert _why(rating, "volatility") == (
            "a burn 2.0 d ago, too little history to judge it, whose new orbit is not yet settled")

    def test_no_element_set_held_after_the_burn_is_not_settled(self) -> None:
        rating = _assess([_BEHAVIOUR], burns=(_SETTLED,), newest_elset_at=None).understanding
        assert rating.volatility is Understanding.MODERATE

    @pytest.mark.parametrize(("custody", "level", "words"), [
        (Custody.DEGRADED, Understanding.MODERATE, "custody degraded"),
        (Custody.LOST, Understanding.LOW, "custody lost"),
    ])
    def test_custody(self, custody: Custody, level: Understanding, words: str) -> None:
        rating = _assess([_BEHAVIOUR], custody=custody).understanding
        assert rating.volatility is level
        assert _why(rating, "volatility") == words

    def test_a_conflict_is_moderate_and_names_both_items(self) -> None:
        share = replace(_CAPABILITY, label="share below half", ceiling_to=Band.MEDIUM)
        rating = _assess([_BEHAVIOUR, _CAPABILITY, share]).understanding
        assert rating.volatility is Understanding.MODERATE
        assert _why(rating, "volatility") == "conflicting evidence, burn against share below half"

    def test_possible_deception_is_moderate_and_named(self) -> None:
        status = _item(dimension=Dimension.CAPABILITY, label="status Degraded", derived_from="status:1",
                       source_grade="D", extraction=0.5, manufacturable=True, impaired_status=True,
                       ceiling_to=Band.MINIMAL, observed_at=None)
        rating = _assess([_BEHAVIOUR, status], burns=(_SETTLED,)).understanding
        assert rating.volatility is Understanding.MODERATE
        assert _why(rating, "volatility") == "possible deception, status Degraded"

    def test_the_latest_burn_governs_volatility(self) -> None:
        hostile = HeldBurn(_NOW - 2 * _DAY, Normality.UNPRECEDENTED)
        routine = HeldBurn(_NOW - _DAY, Normality.ROUTINE)
        assert _assess([_BEHAVIOUR], burns=(hostile, routine)).understanding.volatility is Understanding.HIGH
        later = HeldBurn(_NOW - _DAY, Normality.UNPRECEDENTED)
        earlier = HeldBurn(_NOW - 2 * _DAY, Normality.ROUTINE)
        assert _assess([_BEHAVIOUR], burns=(later, earlier)).understanding.volatility is Understanding.MODERATE

    def test_custody_and_truncation_must_be_stated(self) -> None:
        # Unknown reads as the weakest, so an adapter may not leave these out and be read as held and whole.
        with pytest.raises(TypeError, match="custody"):
            Situation(now=_NOW, access=Band.CRITICAL, history_truncated=False)  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="history_truncated"):
            Situation(now=_NOW, access=Band.CRITICAL, custody=Custody.HELD)  # type: ignore[call-arg]

    def test_a_truncated_history_is_moderate(self) -> None:
        rating = _assess([_BEHAVIOUR], history_truncated=True).understanding
        assert rating.volatility is Understanding.MODERATE
        assert _why(rating, "volatility") == "a truncated history"


class TestTheCaps:
    """Section 6.2: the data mode and a manual element set cap Understanding."""

    _FULL = (_IDENTITY, _CAPABILITY, _BEHAVIOUR)

    def test_the_full_picture_reads_high_on_real_data(self) -> None:
        rating = _assess(self._FULL).understanding
        assert (rating.level, rating.governing) == (Understanding.HIGH, ())
        assert rating.statement == (
            "Understanding HIGH. Information base, analytical rigour and volatility all meet their criteria.")

    @pytest.mark.parametrize("mode", ["SYNTHETIC", "TEST", "EXERCISE", "SIMULATED", " synthetic "])
    def test_an_exercise_mode_caps_at_low(self, mode: str) -> None:
        rating = _assess(self._FULL, data_mode=mode).understanding
        assert (rating.level, rating.governing) == (Understanding.LOW, ("data mode",))
        word = mode.strip().upper()
        assert rating.statement == (
            f"Understanding LOW. Governing: data mode, computed from {word} element sets: "
            "describes the exercise, not the satellite.")

    @pytest.mark.parametrize("mode", [None, "", "UNKNOWN", "SOMETHING NEW"])
    def test_an_unrecorded_mode_caps_at_moderate(self, mode: str | None) -> None:
        rating = _assess(self._FULL, data_mode=mode).understanding
        assert (rating.level, rating.governing) == (Understanding.MODERATE, ("data mode",))
        assert rating.statement == "Understanding MODERATE. Governing: data mode, the data mode is not recorded."

    @pytest.mark.parametrize(("confidence", "level"), [
        ("CONFIRMED", Understanding.HIGH), ("HIGH", Understanding.HIGH), ("MEDIUM", Understanding.MODERATE),
        ("LOW", Understanding.LOW), ("UNCONFIRMED", Understanding.LOW), (None, Understanding.LOW),
    ])
    def test_a_manual_element_set_caps_at_the_operators_confidence(
        self, confidence: str | None, level: Understanding,
    ) -> None:
        rating = _assess(self._FULL, data_mode="MANUAL", manual_confidence=confidence).understanding
        assert rating.level is level
        if level is not Understanding.HIGH:
            assert rating.governing == ("manual element set",)
            stated = (confidence or "unstated").lower()
            assert f"manual element set, entered at the operator's stated confidence, {stated}" in rating.statement

    def test_orbital_geometry_never_counts_towards_understanding(self) -> None:
        for subset in _subsets(_POOL):
            ratings = {_assess(subset, access=a, burns=_POOL_BURNS).understanding for a in Band}
            assert len(ratings) == 1, [i.label for i in subset]


class TestTheWeakestGoverns:
    def test_every_category_at_the_weakest_level_is_named(self) -> None:
        # Behaviour alone: information base LOW; custody lost: volatility LOW too.
        rating = _assess([_BEHAVIOUR], custody=Custody.LOST).understanding
        assert rating.level is Understanding.LOW
        assert rating.governing == ("information base", "volatility")
        assert rating.statement.startswith(
            "Understanding LOW. Governing: information base, Identity not earned, Capability not earned; "
            "volatility, custody lost.")

    def test_the_level_is_the_weakest_of_the_categories_and_caps(self) -> None:
        for subset in _subsets(_POOL):
            rating = _assess(subset, burns=_POOL_BURNS, data_mode="MANUAL", manual_confidence="MEDIUM").understanding
            assert rating.level == min(rating.information_base, rating.rigour, rating.volatility,
                                       Understanding.MODERATE)


_ROLE = _item(dimension=Dimension.IDENTITY, label="dated role", derived_from="intel-record:1", source_grade="C",
              extraction=0.5, observed_at=_NOW - _DAY, floor_to=Band.MEDIUM, basis=Basis.LOOKUP)
_GCAT = _item(dimension=Dimension.IDENTITY, label="gcat", derived_from="gcat:1", extraction=1.0,
              observed_at=_NOW - 30 * _DAY, basis=Basis.LOOKUP)
_UDL_RESERVE = _item(dimension=Dimension.CAPABILITY, label="UDL reserve", extraction=0.5)
_LOW_SHARE = _item(dimension=Dimension.CAPABILITY, label="commercial share below half",
                   derived_from="elset-history:COMM", source_grade="C", extraction=0.5, ceiling_to=Band.MEDIUM)
_UDL_BURN = _item(label="UDL burn", observed_at=_BURN_AT, floor_to=Band.HIGH, controlled=True)
_ALLIED = _item(label="allied track", derived_from="allied:optical", source_grade="A", credibility=1,
                observed_at=_BURN_AT + _DAY, floor_to=Band.HIGH, controlled=True)
_ANOMALY = _item(label="anomaly index", extraction=0.6, observed_at=_BURN_AT, floor_to=Band.MEDIUM,
                 basis=Basis.LOOKUP)
_SPENT = _item(dimension=Dimension.CAPABILITY, label="reserve exhausted", derived_from="allied:fuel",
               source_grade="A", credibility=1, extraction=1.0, ceiling_to=Band.MINIMAL)
_POOL = (_GCAT, _ROLE, _UDL_RESERVE, _LOW_SHARE, _UDL_BURN, _ALLIED, _ANOMALY, _SPENT)
_POOL_BURNS = (HeldBurn(_BURN_AT, Normality.UNPRECEDENTED),)


def _subsets(pool: Sequence[EvidenceItem]) -> list[tuple[EvidenceItem, ...]]:
    return [s for n in range(len(pool) + 1) for s in itertools.combinations(pool, n)]


def _conflicted(result: ThreatUnderstanding) -> set[str]:
    return {label for pair in result.range.conflicts for label in pair}


class TestTheInvariants:
    def test_i3_a_conflict_caps_understanding_at_moderate(self) -> None:
        checked = 0
        for subset in _subsets(_POOL):
            result = _assess(subset)
            if result.range.conflicts:
                checked += 1
                assert result.understanding.level <= Understanding.MODERATE
                for floor_item, ceiling_item in result.range.conflicts:
                    assert f"{floor_item} against {ceiling_item}" in _why(result.understanding, "volatility")
        assert checked > 50

    def test_i1_a_non_conflicting_item_lowers_understanding_only_through_rigour(self) -> None:
        # The concept's I1 says Understanding falls only for a new hostile burn. Its own
        # Analytical Rigour rule also lowers it when a new reading sets a bound on a
        # weaker footing (a lookup, or an uncontrolled source), so that is the one other
        # way it may fall; nothing else may lower it.
        checked = fell = 0
        for subset in _subsets(_POOL):
            before = _assess(subset)
            for extra in set(_POOL) - set(subset):
                after = _assess([*subset, extra])
                if _conflicted(after) != _conflicted(before):
                    continue
                checked += 1
                b, a = before.understanding, after.understanding
                assert a.information_base >= b.information_base
                assert a.volatility >= b.volatility
                if a.level < b.level:
                    fell += 1
                    assert a.rigour < b.rigour, ([i.label for i in subset], extra.label)
        assert checked > 500
        assert fell > 0

    @pytest.mark.parametrize("burns", [(), _POOL_BURNS, (*_POOL_BURNS, HeldBurn(_NOW, Normality.ROUTINE))])
    def test_i4_ageing_never_raises_understanding(self, burns: tuple[HeldBurn, ...]) -> None:
        offsets = (0, 1, 7, 30, 90, 365, 1000)
        for subset in _subsets(_POOL):
            levels = [_assess(subset, now=_NOW + d * _DAY, burns=burns).understanding.level for d in offsets]
            assert levels == sorted(levels, reverse=True), [i.label for i in subset]


_BAND_WORDS = r"\b(CRITICAL|HIGH|MEDIUM|MODERATE|LOW|MINIMAL)\b"


class TestTheStatement:
    """Section 6.3 and the statement's half of I13."""

    def test_the_statement_never_mentions_threat_a_percentage_or_a_bare_band(self) -> None:
        situations = [
            {"burns": _POOL_BURNS}, {"custody": Custody.LOST}, {"data_mode": "SYNTHETIC"},
            {"data_mode": "MANUAL", "manual_confidence": "HIGH"}, {"history_truncated": True},
        ]
        for subset, kw in itertools.product(_subsets(_POOL), situations):
            statement = _assess(subset, **kw).understanding.statement
            assert "threat" not in statement.lower()
            assert "%" not in statement
            for match in re.finditer(_BAND_WORDS, statement):
                assert statement[:match.start()].endswith("Understanding "), statement

    def test_the_statement_opens_with_the_level(self) -> None:
        for level_case in ([_BEHAVIOUR], [_IDENTITY, _BEHAVIOUR], [_IDENTITY, _CAPABILITY, _BEHAVIOUR]):
            rating = _assess(level_case).understanding
            assert rating.statement.startswith(f"Understanding {rating.level.name}. ")


class TestAssess:
    def test_the_verdict_uses_the_legacy_reading_inside_the_range(self) -> None:
        result = _assess([_IDENTITY, _CAPABILITY, _BEHAVIOUR], legacy=Band.MEDIUM)
        assert (result.range.floor, result.range.ceiling) == (Band.HIGH, Band.CRITICAL)
        assert (result.verdict.assessed, result.verdict.band) == (Band.HIGH, Band.HIGH)

    def test_with_no_capability_evidence_the_legacy_reading_is_access(self) -> None:
        result = _assess([_IDENTITY, _CAPABILITY, _BEHAVIOUR], access=Band.HIGH)
        assert result.verdict.assessed is Band.HIGH
        # Inside a range of HIGH to CRITICAL the point is access, not the floor.
        wide = _assess([_IDENTITY, _CAPABILITY, _BEHAVIOUR])
        assert (wide.range.floor, wide.understanding.level) == (Band.HIGH, Understanding.HIGH)
        assert (wide.verdict.assessed, wide.verdict.band) == (Band.CRITICAL, Band.CRITICAL)

    def test_understanding_low_reads_the_ceiling(self) -> None:
        result = _assess([_BEHAVIOUR], legacy=Band.MINIMAL)
        assert result.understanding.level is Understanding.LOW
        assert (result.verdict.band, result.verdict.at_ceiling) == (Band.CRITICAL, True)
