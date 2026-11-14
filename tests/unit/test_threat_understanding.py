"""Threat Understanding, SPC-162: evidence items, reliability, freshness and coverage.

Each class pins one rule of section 4.2 to 4.5 of
docs/threat_confidence_concept.md. Hypothesis is not installed, so the
invariants are checked over exhaustive ``itertools`` subsets of a small pool
and over parametrised grids, never over random draws.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Depth, Dimension, EvidenceItem, HeldBurn

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_TOL = 1e-9


def _item(**kw: object) -> EvidenceItem:
    args: dict[str, object] = {
        "dimension": Dimension.BEHAVIOUR, "label": "burn", "derived_from": "elset-history:UDL",
        "source_grade": "B", "credibility": 2, "extraction": 0.9, "basis": Basis.COMPUTED,
        "observed_at": _NOW,
    }
    args.update(kw)
    return EvidenceItem(**args)  # type: ignore[arg-type]


def _hostile(at: datetime, normality: Normality = Normality.UNPRECEDENTED) -> HeldBurn:
    return HeldBurn(epoch=at, normality=normality)


class TestTheAdmiraltyGradesAreWeighted:
    """Section 4.3: the letter grades the source, the digit the information."""

    @pytest.mark.parametrize(("letter", "weight"), [
        ("A", 0.9), ("B", 0.8), ("C", 0.6), ("D", 0.3), ("E", 0.1), ("F", 0.3),
    ])
    def test_each_source_letter_has_its_weight(self, letter: str, weight: float) -> None:
        assert tu.SOURCE_RELIABILITY[letter] == weight

    @pytest.mark.parametrize(("digit", "weight"), [(1, 1.0), (2, 0.85), (3, 0.6), (4, 0.4), (5, 0.2), (6, 0.3)])
    def test_each_credibility_digit_has_its_weight(self, digit: int, weight: float) -> None:
        assert tu.CREDIBILITY[digit] == weight

    def test_an_item_reads_its_grade_as_letter_and_digit(self) -> None:
        assert _item(source_grade="C", credibility=3).grade == "C3"

    @pytest.mark.parametrize(("field", "value", "reason"), [
        ("source_grade", "G", "source grade"),
        ("credibility", 7, "credibility"),
        ("extraction", 1.5, "extraction"),
        ("extraction", -0.1, "extraction"),
    ])
    def test_a_grade_off_the_scale_is_refused(self, field: str, value: object, reason: str) -> None:
        with pytest.raises(ValueError, match=reason):
            _item(**{field: value})


class TestTheReliabilityOfOneItem:
    """q_i = min(cap_i, r_src x r_cred x r_ext x f_i)."""

    def test_the_gcat_entry_of_the_worked_example(self) -> None:
        # Row 2: B2, a catalogue field read directly, refreshed 30 days ago.
        gcat = _item(dimension=Dimension.IDENTITY, derived_from="gcat:99001", extraction=1.0,
                     observed_at=_NOW - timedelta(days=30))
        assert tu.reliability(gcat, _NOW) == pytest.approx(0.8 * 0.85 * 1.0 * 0.5 ** (30 / 365))
        assert round(tu.reliability(gcat, _NOW), 2) == 0.64

    def test_every_grade_extraction_and_age_gives_a_q_between_0_and_1(self) -> None:
        ages = (None, 0.0, 1.0, 30.0, 400.0, 5000.0)
        checked = 0
        for letter, digit, extraction, age, flags in itertools.product(
            tu.SOURCE_RELIABILITY, tu.CREDIBILITY, (0.0, 0.1, 0.5, 1.0), ages,
            ((False, False), (True, False), (False, True), (True, True)),
        ):
            item = _item(source_grade=letter, credibility=digit, extraction=extraction,
                         observed_at=None if age is None else _NOW - timedelta(days=age),
                         manufacturable=flags[0], routine=flags[1])
            assert 0.0 <= tu.reliability(item, _NOW) <= 1.0
            checked += 1
        assert checked == 6 * 6 * 4 * len(ages) * 4

    def test_a_manufacturable_item_is_capped_however_well_graded(self) -> None:
        declared = _item(source_grade="A", credibility=1, extraction=1.0, manufacturable=True)
        assert tu.reliability(declared, _NOW) == tu.MANUFACTURABLE_CAP == 0.3

    def test_a_routine_verdict_is_capped_because_its_baseline_is_its_own(self) -> None:
        routine = _item(source_grade="A", credibility=1, extraction=1.0, routine=True)
        assert tu.reliability(routine, _NOW) == tu.ROUTINE_CAP == 0.5

    def test_the_cap_only_ever_lowers(self) -> None:
        weak = _item(source_grade="E", credibility=5, extraction=0.3, manufacturable=True)
        assert tu.reliability(weak, _NOW) == pytest.approx(0.1 * 0.2 * 0.3)


class TestExtractionReliability:
    """Our own processing chain, graded apart from the source (KBT)."""

    @pytest.mark.parametrize(("grade", "weight"), [("HIGH", 0.9), ("MODERATE", 0.6), ("LOW", 0.3), ("REJECT", 0.0)])
    def test_the_burn_detection_grade_sets_extraction(self, grade: str, weight: float) -> None:
        assert tu.burn_extraction(grade) == weight

    def test_a_burn_across_a_long_gap_is_halved(self) -> None:
        assert tu.burn_extraction("HIGH", long_gap=True) == pytest.approx(0.45)

    def test_a_poor_fit_is_halved_and_the_two_compound(self) -> None:
        assert tu.burn_extraction("HIGH", poor_fit=True) == pytest.approx(0.45)
        assert tu.burn_extraction("MODERATE", long_gap=True, poor_fit=True) == pytest.approx(0.15)

    def test_an_unknown_detection_grade_is_refused(self) -> None:
        with pytest.raises(ValueError, match="detection grade"):
            tu.burn_extraction("MAYBE")

    def test_assumed_assessed_and_catalogue_figures(self) -> None:
        assert (tu.ASSUMED_FIGURE_EXTRACTION, tu.ASSESSED_LABEL_EXTRACTION, tu.CATALOGUE_FIELD_EXTRACTION) == (
            0.5, 0.5, 1.0)

    @pytest.mark.parametrize(("confidence", "weight"), [
        ("CONFIRMED", 1.0), ("HIGH", 0.9), ("MEDIUM", 0.6), ("LOW", 0.3), ("UNCONFIRMED", 0.1),
        ("", 0.1), (None, 0.1), ("probably", 0.1),
    ])
    def test_a_manual_element_set_takes_the_operators_confidence(self, confidence: str | None, weight: float) -> None:
        # An unstated or unknown confidence is read as the weakest, UNCONFIRMED.
        assert tu.manual_extraction(confidence) == weight

    def test_the_manual_confidences_are_the_ones_the_sweep_form_offers(self) -> None:
        from spectre.web.routes.threat import _CONFIDENCES
        assert tuple(tu.MANUAL_EXTRACTION) == _CONFIDENCES


class TestFreshness:
    """f_i = 0.5^(age_i / h_d) x reset_i."""

    @pytest.mark.parametrize(("dimension", "regime", "days"), [
        (Dimension.IDENTITY, "GEO", 365.0), (Dimension.CAPABILITY, "GEO", 90.0),
        (Dimension.INTERACTIONS, "LEO", 30.0), (Dimension.BEHAVIOUR, "GEO", 60.0),
        (Dimension.BEHAVIOUR, "LEO", 14.0), (Dimension.BEHAVIOUR, "MEO", 30.0),
        (Dimension.BEHAVIOUR, "HEO", 30.0), (Dimension.BEHAVIOUR, "DEEP", 30.0),
        (Dimension.BEHAVIOUR, " geo ", 60.0),
    ])
    def test_each_dimension_and_regime_has_its_half_life(self, dimension: Dimension, regime: str, days: float) -> None:
        assert tu.half_life_days(dimension, regime) == days

    @pytest.mark.parametrize("dimension", list(Dimension))
    @pytest.mark.parametrize("regime", ["GEO", "LEO", "MEO"])
    def test_freshness_falls_strictly_with_age(self, dimension: Dimension, regime: str) -> None:
        ages = (0.0, 0.5, 1.0, 7.0, 30.0, 90.0, 365.0, 1000.0)
        values = [tu.freshness(_item(dimension=dimension, observed_at=_NOW - timedelta(days=a)), _NOW, regime=regime)
                  for a in ages]
        assert values[0] == 1.0
        assert all(later < earlier for earlier, later in itertools.pairwise(values))

    def test_one_half_life_halves(self) -> None:
        item = _item(dimension=Dimension.CAPABILITY, observed_at=_NOW - timedelta(days=90))
        assert tu.freshness(item, _NOW) == pytest.approx(0.5)

    def test_an_undated_item_counts_as_one_half_life_old(self) -> None:
        undated = _item(dimension=Dimension.IDENTITY, observed_at=None)
        year_old = _item(dimension=Dimension.IDENTITY, observed_at=_NOW - timedelta(days=365))
        assert tu.freshness(undated, _NOW) == pytest.approx(0.5)
        assert tu.freshness(undated, _NOW) == pytest.approx(tu.freshness(year_old, _NOW))
        assert tu.freshness(undated, _NOW + timedelta(days=900)) == pytest.approx(0.5)

    def test_an_epoch_ahead_of_the_clock_counts_as_fresh_not_fresher(self) -> None:
        assert tu.freshness(_item(observed_at=_NOW + timedelta(hours=2)), _NOW) == 1.0


class TestTheFreshnessReset:
    """QDF: an unusual burn makes the object a hot topic, and older Capability and Behaviour evidence halves."""

    _BURN = _NOW - timedelta(days=2)

    @pytest.mark.parametrize("normality", [Normality.UNUSUAL, Normality.UNPRECEDENTED])
    @pytest.mark.parametrize("dimension", [Dimension.CAPABILITY, Dimension.BEHAVIOUR])
    def test_evidence_from_before_a_hostile_burn_halves(self, normality: Normality, dimension: Dimension) -> None:
        before = _item(dimension=dimension, observed_at=self._BURN - timedelta(hours=1))
        assert tu.freshness(before, _NOW, burns=(_hostile(self._BURN, normality),)) == pytest.approx(
            0.5 * tu.freshness(before, _NOW))

    @pytest.mark.parametrize("normality", [Normality.ROUTINE, Normality.NOT_ENOUGH_HISTORY])
    def test_a_burn_not_judged_hostile_resets_nothing(self, normality: Normality) -> None:
        before = _item(observed_at=self._BURN - timedelta(hours=1))
        assert tu.freshness(before, _NOW, burns=(_hostile(self._BURN, normality),)) == tu.freshness(before, _NOW)

    @pytest.mark.parametrize("dimension", [Dimension.IDENTITY, Dimension.INTERACTIONS])
    def test_identity_and_interactions_are_not_reset(self, dimension: Dimension) -> None:
        before = _item(dimension=dimension, observed_at=self._BURN - timedelta(hours=1))
        assert tu.freshness(before, _NOW, burns=(_hostile(self._BURN),)) == tu.freshness(before, _NOW)

    def test_evidence_from_at_or_after_the_burn_is_not_reset(self) -> None:
        for at in (self._BURN, self._BURN + timedelta(hours=1)):
            item = _item(observed_at=at)
            assert tu.freshness(item, _NOW, burns=(_hostile(self._BURN),)) == tu.freshness(item, _NOW)

    def test_a_burn_after_the_clock_has_not_happened_yet(self) -> None:
        item = _item(observed_at=self._BURN - timedelta(hours=1))
        later = _hostile(_NOW + timedelta(hours=1))
        assert tu.freshness(item, _NOW, burns=(later,)) == tu.freshness(item, _NOW)

    def test_an_undated_capability_item_is_older_than_any_burn(self) -> None:
        undated = _item(dimension=Dimension.CAPABILITY, observed_at=None)
        assert tu.freshness(undated, _NOW, burns=(_hostile(self._BURN),)) == pytest.approx(0.25)

    def test_the_reset_follows_the_latest_hostile_burn(self) -> None:
        between = _item(observed_at=self._BURN - timedelta(days=5))
        older = _hostile(self._BURN - timedelta(days=10))
        assert tu.freshness(between, _NOW, burns=(older,)) == tu.freshness(between, _NOW)
        assert tu.freshness(between, _NOW, burns=(older, _hostile(self._BURN))) == pytest.approx(
            0.5 * tu.freshness(between, _NOW))


def _pool() -> list[EvidenceItem]:
    """Eight items over three dimensions, two sharing one history."""
    day = timedelta(days=1)
    return [
        _item(dimension=Dimension.IDENTITY, label="gcat", derived_from="gcat:1", extraction=1.0,
              observed_at=_NOW - 30 * day),
        _item(dimension=Dimension.IDENTITY, label="intel", derived_from="intel-record:1", source_grade="C",
              credibility=3, extraction=0.5, observed_at=None),
        _item(dimension=Dimension.CAPABILITY, label="reserve", extraction=0.5),
        _item(dimension=Dimension.CAPABILITY, label="propellant used", extraction=0.5, observed_at=_NOW - day),
        _item(dimension=Dimension.CAPABILITY, label="commercial reserve", derived_from="elset-history:COMM",
              source_grade="C", extraction=0.5),
        _item(label="burn", observed_at=_NOW - 2 * day),
        _item(label="allied track", derived_from="allied:optical", source_grade="A", credibility=1,
              observed_at=_NOW - day, controlled=True),
        _item(label="declared station keeping", derived_from="notso:OP", source_grade="D", manufacturable=True),
    ]


class TestIndependenceAndCoverage:
    """Section 4.5: one group counts once, and coverage is a noisy-OR across groups."""

    def test_within_a_group_only_the_strongest_counts(self) -> None:
        # Four figures from one element-set history are one piece of evidence.
        figures = [_item(dimension=Dimension.CAPABILITY, label=name, extraction=x)
                   for name, x in (("propellant used", 0.5), ("reserve", 0.5), ("anomaly", 0.6), ("burn count", 1.0))]
        cover = tu.coverage(figures, _NOW)
        assert cover[Dimension.CAPABILITY] == pytest.approx(0.8 * 0.85 * 1.0)

    def test_coverage_is_a_noisy_or_across_groups(self) -> None:
        a = _item(derived_from="elset-history:UDL")
        b = _item(derived_from="allied:optical", source_grade="A", credibility=1)
        qa, qb = tu.reliability(a, _NOW), tu.reliability(b, _NOW)
        assert tu.coverage([a, b], _NOW)[Dimension.BEHAVIOUR] == pytest.approx(1 - (1 - qa) * (1 - qb))

    def test_a_dimension_with_nothing_held_has_no_coverage(self) -> None:
        assert tu.coverage([], _NOW) == dict.fromkeys(Dimension, 0.0)

    def test_an_item_not_yet_observed_at_the_clock_is_not_counted(self) -> None:
        later = _item(observed_at=_NOW + timedelta(days=1))
        assert tu.coverage([later], _NOW)[Dimension.BEHAVIOUR] == 0.0

    def test_adding_any_item_never_lowers_any_coverage(self) -> None:
        pool = _pool()
        for size in range(len(pool)):
            for subset in itertools.combinations(range(len(pool)), size):
                before = tu.coverage([pool[i] for i in subset], _NOW)
                for extra in set(range(len(pool))) - set(subset):
                    after = tu.coverage([pool[i] for i in (*subset, extra)], _NOW)
                    assert all(after[d] >= before[d] - _TOL for d in Dimension), (subset, extra)

    def test_i2_a_duplicate_or_a_weaker_copy_in_its_group_changes_nothing(self) -> None:
        pool = _pool()
        for size in range(1, len(pool) + 1):
            for subset in itertools.combinations(pool, size):
                before = tu.coverage(list(subset), _NOW)
                for member in subset:
                    for copy in (member, _copy_weaker(member)):
                        assert tu.coverage([*subset, copy], _NOW) == before

    def test_coverage_does_not_depend_on_the_order_items_arrive(self) -> None:
        pool = _pool()[:6]
        expected = tu.coverage(pool, _NOW)
        for order in itertools.permutations(pool):
            assert tu.coverage(list(order), _NOW) == expected

    @pytest.mark.parametrize("dimension", list(Dimension))
    def test_manufactured_items_count_once_because_the_operator_declares_them_all(self, dimension: Dimension) -> None:
        # Section 2.4: items sharing a source are one group. A NOTSO filing, a declared
        # mission and a website all come from the object's operator, so together they
        # are worth no more than the strongest of them, and never earn a dimension.
        declared = [_item(dimension=dimension, label=name, derived_from=f"{name}:OP", source_grade="A",
                          credibility=1, extraction=1.0, manufacturable=True)
                    for name in ("notso", "declared mission", "website")]
        assert {d.group for d in declared} == {(dimension, "declared by the operator")}
        for size in range(1, len(declared) + 1):
            for subset in itertools.combinations(declared, size):
                u = tu.coverage(list(subset), _NOW)[dimension]
                assert u == tu.MANUFACTURABLE_CAP
                assert tu.depth(u) is not Depth.EARNED

    def test_a_single_capped_manufacturable_item_never_earns_a_dimension(self) -> None:
        checked = 0
        for letter, digit, dimension in itertools.product(tu.SOURCE_RELIABILITY, tu.CREDIBILITY, Dimension):
            declared = _item(dimension=dimension, source_grade=letter, credibility=digit, extraction=1.0,
                             manufacturable=True)
            u = tu.coverage([declared], _NOW)[dimension]
            assert u <= tu.MANUFACTURABLE_CAP
            assert tu.depth(u) is not Depth.EARNED
            checked += 1
        assert checked == 6 * 6 * len(Dimension)


def _copy_weaker(item: EvidenceItem) -> EvidenceItem:
    from dataclasses import replace
    return replace(item, label=f"{item.label} (copy)", extraction=item.extraction / 2)


class TestDepth:
    """Earned at 0.5, partial at 0.25; both tuned, not sourced."""

    @pytest.mark.parametrize(("u", "expected"), [
        (0.0, Depth.NONE), (0.249, Depth.NONE), (0.25, Depth.PARTIAL), (0.499, Depth.PARTIAL),
        (0.5, Depth.EARNED), (1.0, Depth.EARNED),
    ])
    def test_each_threshold(self, u: float, expected: Depth) -> None:
        assert tu.depth(u) is expected
        assert (tu.EARNED, tu.PARTIAL) == (0.5, 0.25)


class TestTheItemsRules:
    """What an item may claim, refused at construction so no adapter can build a wrong one."""

    def test_capability_only_ever_lowers_the_ceiling(self) -> None:
        with pytest.raises(ValueError, match="Capability only lowers the ceiling"):
            _item(dimension=Dimension.CAPABILITY, floor_to=Band.MEDIUM)

    @pytest.mark.parametrize("dimension", [Dimension.IDENTITY, Dimension.BEHAVIOUR, Dimension.INTERACTIONS])
    def test_only_capability_lowers_the_ceiling(self, dimension: Dimension) -> None:
        with pytest.raises(ValueError, match="only Capability lowers the ceiling"):
            _item(dimension=dimension, ceiling_to=Band.MEDIUM)

    def test_a_routine_verdict_carries_no_reading(self) -> None:
        with pytest.raises(ValueError, match="routine"):
            _item(routine=True, floor_to=Band.LOW)

    @pytest.mark.parametrize(("dimension", "reading"), [
        (Dimension.IDENTITY, {"floor_to": Band.MEDIUM}),
        (Dimension.BEHAVIOUR, {"floor_to": Band.CRITICAL}),
        (Dimension.CAPABILITY, {"ceiling_to": Band.MINIMAL}),
    ])
    def test_a_claim_the_adversary_controls_carries_no_reading(
        self, dimension: Dimension, reading: dict[str, Band],
    ) -> None:
        # Section 4.6: "NOTSO filing, declared mission: No reading. Coverage only".
        with pytest.raises(ValueError, match="coverage only"):
            _item(dimension=dimension, source_grade="D", manufacturable=True, **reading)

    def test_of_the_claims_the_adversary_controls_only_an_impaired_status_carries_a_reading(self) -> None:
        status = _item(dimension=Dimension.CAPABILITY, source_grade="D", manufacturable=True, impaired_status=True,
                       ceiling_to=Band.MINIMAL)
        assert status.has_reading

    @pytest.mark.parametrize("band", [Band.HIGH, Band.CRITICAL])
    def test_a_prior_never_raises_the_floor_above_medium(self, band: Band) -> None:
        # Section 4.6: "A prior never raises the floor higher" than MEDIUM.
        with pytest.raises(ValueError, match="prior never raises the floor above MEDIUM"):
            _item(dimension=Dimension.IDENTITY, basis=Basis.COMPUTED, floor_to=band)
        assert _item(dimension=Dimension.IDENTITY, floor_to=Band.MEDIUM).floor_to is Band.MEDIUM

    @pytest.mark.parametrize("dimension", [Dimension.BEHAVIOUR, Dimension.INTERACTIONS])
    @pytest.mark.parametrize("band", [Band.HIGH, Band.CRITICAL])
    def test_an_uncalibrated_lookup_never_raises_the_floor_above_medium(
        self, dimension: Dimension, band: Band,
    ) -> None:
        # Section 4.6: the anomaly index rung is "capped at MEDIUM, because the index is uncalibrated".
        with pytest.raises(ValueError, match="uncalibrated lookup never raises the floor above MEDIUM"):
            _item(dimension=dimension, basis=Basis.LOOKUP, floor_to=band)
        assert _item(dimension=dimension, basis=Basis.LOOKUP, floor_to=Band.MEDIUM).floor_to is Band.MEDIUM
        assert _item(dimension=dimension, basis=Basis.COMPUTED, floor_to=band).floor_to is band

    def test_an_impaired_status_is_capability_evidence(self) -> None:
        with pytest.raises(ValueError, match="impaired status"):
            _item(impaired_status=True)

    def test_the_group_is_the_dimension_and_the_source_chain(self) -> None:
        assert _item().group == (Dimension.BEHAVIOUR, "elset-history:UDL")


class TestTheModelIsPure:
    def test_the_domain_does_not_import_the_web_layer(self) -> None:
        import inspect
        assert "spectre.web" not in inspect.getsource(tu)
