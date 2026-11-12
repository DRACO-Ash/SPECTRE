"""Threat Understanding, SPC-163: readings, the threat range, voiding, conflicts and the verdict.

Each class pins one rule of sections 4.4 (persistence), 4.6, 4.7 and 4.8 of
docs/threat_confidence_concept.md, and the invariants I1, I3, I5, I6, I7 and
I9 of section 4.11. Invariants are checked over exhaustive ``itertools``
subsets of small pools, because Hypothesis is not installed.
"""

from __future__ import annotations

import itertools
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
    Status,
    ThreatRange,
    Understanding,
)

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_DAY = timedelta(days=1)
_BURN_AT = _NOW - 2 * _DAY
_TOL = 1e-9


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
                               "history_truncated": False}
    args.update(kw)
    return Situation(**args)  # type: ignore[arg-type]


def _range(items: Sequence[EvidenceItem], **kw: object) -> ThreatRange:
    return tu.threat_range(items, _sit(**kw))


def _row(result: ThreatRange, label: str) -> tu.LedgerRow:
    return next(r for r in result.ledger if r.item.label == label)


_GCAT = _item(dimension=Dimension.IDENTITY, label="gcat", derived_from="gcat:1", extraction=1.0,
              observed_at=_NOW - 30 * _DAY)
_ROLE = _item(dimension=Dimension.IDENTITY, label="dated role", derived_from="intel-record:1", source_grade="C",
              extraction=0.5, observed_at=_NOW - _DAY, floor_to=Band.MEDIUM, basis=Basis.LOOKUP)
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


def _conflicted(result: ThreatRange) -> set[str]:
    return {label for pair in result.conflicts for label in pair}


class TestAReadingNeedsAnEarnedDimensionAndItsOwnQ:
    """Section 4.6: a reading applies only when its dimension is earned and its own q is at least 0.25."""

    def test_a_reading_in_an_unearned_dimension_is_listed_not_applied(self) -> None:
        result = _range([_ROLE])
        assert (result.floor, result.ceiling) == (Band.MINIMAL, Band.CRITICAL)
        row = _row(result, "dated role")
        assert (row.applied, row.status) == (False, Status.BELOW_THRESHOLD)
        assert "Identity not earned" in row.note

    def test_a_reading_below_its_own_threshold_is_listed_not_applied(self) -> None:
        weak = replace(_ROLE, source_grade="C", credibility=3)          # q 0.18
        result = _range([_GCAT, weak])
        assert result.floor is Band.MINIMAL
        assert _row(result, "dated role").status is Status.BELOW_THRESHOLD
        assert "below 0.25" in _row(result, "dated role").note

    def test_an_earned_dimension_and_a_strong_enough_item_raise_the_floor(self) -> None:
        result = _range([_GCAT, _ROLE])
        assert (result.floor, result.ceiling) == (Band.MEDIUM, Band.CRITICAL)
        assert (_row(result, "dated role").applied, _row(result, "dated role").status) == (True, Status.COUNTED)

    def test_a_weaker_copys_reading_counts_once_at_its_chains_best_reliability(self) -> None:
        # Concept section 9, decision 6 (SPC-186): the share below half (q 0.34) alone earns no Capability,
        # but read from the same history as the ample reserve (q 0.61) it counts once, at the chain's q.
        ample = replace(_UDL_RESERVE, label="UDL reserve ample", extraction=0.9)
        share = replace(_UDL_RESERVE, label="UDL share below half", ceiling_to=Band.MEDIUM)
        alone = _range([ample])
        result = _range([ample, share])
        assert (alone.ceiling, result.ceiling, result.coverage) == (Band.CRITICAL, Band.MEDIUM, alone.coverage)
        row = _row(result, "UDL share below half")
        assert (row.status, row.applied) == (Status.COUNTED, True)
        assert row.note == ("its reading counts once, at its source chain's best reliability, q 0.61 from UDL "
                            "reserve ample")
        assert (_row(result, "UDL reserve ample").status, _row(result, "UDL reserve ample").applied) == (
            Status.COUNTED, False)

    def test_a_weaker_reading_from_the_same_history_is_folded_under_a_stronger_one(self) -> None:
        # The anomaly index (q 0.41) shares the burn's history (q 0.61): only the burn reads.
        unusual = replace(_UDL_BURN, label="UDL burn unusual", floor_to=Band.MEDIUM, controlled=False)
        posture = replace(_ANOMALY, label="UDL posture", basis=Basis.COMPUTED, floor_to=Band.MEDIUM)
        allied = replace(_ALLIED, floor_to=None)
        result = _range([unusual, posture, allied], burns=_POOL_BURNS)
        assert (_row(result, "UDL burn unusual").applied, _row(result, "UDL posture").applied) == (True, False)
        assert _row(result, "UDL posture").status is Status.FOLDED

    def test_a_stronger_coverage_only_figure_from_the_same_history_never_folds_a_reading(self) -> None:
        # Concept section 9, decision 6, owner ruling 2026-11-05 (SPC-186): the strongest reading in the
        # chain counts once, at the chain's best reliability, so a new copy never widens the range.
        posture = _item(label="UDL posture", extraction=0.6, floor_to=Band.MEDIUM)
        vouch = replace(_ALLIED, floor_to=None)
        count = _item(label="UDL burn count", extraction=1.0)
        assert _range([posture, vouch]).floor is Band.MEDIUM
        result = _range([posture, vouch, count])
        assert result.floor is Band.MEDIUM
        assert (_row(result, "UDL posture").applied, _row(result, "UDL posture").status) == (True, Status.COUNTED)
        assert _row(result, "UDL posture").note == (
            "its reading counts once, at its source chain's best reliability, q 0.68 from UDL burn count")

    def test_on_equal_q_the_reading_leads_whatever_order_the_labels_sort_in(self) -> None:
        posture = _item(label="z posture aggressive", floor_to=Band.MEDIUM)
        figure = _item(label="a burn count")
        vouch = replace(_ALLIED, floor_to=None)
        result = _range([posture, figure, vouch])
        assert result.floor is Band.MEDIUM
        assert _row(result, "z posture aggressive").applied

    @pytest.mark.parametrize(("extraction", "applies"), [(0.3125, True), (0.3124, False)])
    def test_a_q_of_exactly_one_quarter_is_enough_to_read(self, extraction: float, applies: bool) -> None:
        # B1 x 0.3125 is 0.25 exactly. Behaviour is earned by the allied track.
        reading = _item(label="posture", derived_from="small", credibility=1, extraction=extraction,
                        floor_to=Band.MEDIUM)
        result = _range([reading, replace(_ALLIED, floor_to=None)])
        assert _row(result, "posture").applied is applies
        assert result.floor is (Band.MEDIUM if applies else Band.MINIMAL)

    @pytest.mark.parametrize(("extraction", "applies"), [(0.625, True), (0.6249, False)])
    def test_a_coverage_of_exactly_one_half_earns_the_dimension(self, extraction: float, applies: bool) -> None:
        # B1 x 0.625 is 0.5 exactly: the item earns Behaviour alone, and reads.
        reading = _item(label="posture", credibility=1, extraction=extraction, floor_to=Band.MEDIUM)
        result = _range([reading])
        assert result.floor is (Band.MEDIUM if applies else Band.MINIMAL)


class TestTheStrongestReadingInAChainCountsOnce:
    """Concept section 9, decision 6, owner ruling 2026-11-05 (SPC-186).

    Any reading from a source chain counts once, at the chain's best
    reliability, so a new copy never widens the range.
    """

    _VOUCH = replace(_ALLIED, floor_to=None)

    def test_a_reading_too_weak_alone_reads_at_its_chains_best_q(self) -> None:
        weak = _item(label="UDL posture", source_grade="C", credibility=3, extraction=0.6, floor_to=Band.MEDIUM)
        count = _item(label="UDL burn count", extraction=1.0)
        assert tu.reliability(weak, _NOW) < 0.25 <= tu.reliability(count, _NOW)
        assert _range([weak, self._VOUCH]).floor is Band.MINIMAL
        assert _range([weak, count, self._VOUCH]).floor is Band.MEDIUM

    def test_below_threshold_names_the_chains_q(self) -> None:
        weak = _item(label="UDL posture", source_grade="C", credibility=3, extraction=0.5, floor_to=Band.MEDIUM)
        count = _item(label="UDL burn count", source_grade="C", credibility=3, extraction=0.6)
        result = _range([weak, count, self._VOUCH])
        assert result.floor is Band.MINIMAL
        row = _row(result, "UDL posture")
        assert (row.status, row.note) == (Status.BELOW_THRESHOLD, f"q {tu.reliability(count, _NOW):.2f} below 0.25")

    def test_the_strongest_reading_leads_whatever_its_q(self) -> None:
        unusual = _item(label="UDL burn unusual", floor_to=Band.MEDIUM, extraction=1.0)
        unprecedented = _item(label="UDL burn unprecedented", floor_to=Band.HIGH, extraction=0.5, controlled=True)
        result = _range([unusual, unprecedented, self._VOUCH])
        assert result.floor is Band.HIGH
        assert _row(result, "UDL burn unusual").status is Status.FOLDED
        assert _row(result, "UDL burn unusual").note == "same source chain as UDL burn unprecedented; not counted again"

    def test_a_floor_a_later_hostile_burn_has_ended_does_not_lead_over_a_live_one(self) -> None:
        # Concept section 9, decision 7: only a later unusual or unprecedented burn ends a hostile floor.
        early = _item(label="UDL burn early", floor_to=Band.HIGH, observed_at=_NOW - 3 * _DAY, extraction=1.0,
                      controlled=True)
        late = _item(label="UDL burn late", floor_to=Band.MEDIUM, observed_at=_BURN_AT, extraction=1.0)
        result = _range([early, late, self._VOUCH], burns=(HeldBurn(_BURN_AT, Normality.UNUSUAL),))
        assert result.floor is Band.MEDIUM
        assert (_row(result, "UDL burn late").applied, _row(result, "UDL burn early").applied) == (True, False)

    def test_an_ended_floor_alone_in_its_chain_still_reads_while_earned(self) -> None:
        early = _item(label="UDL burn early", floor_to=Band.HIGH, observed_at=_NOW - 3 * _DAY, extraction=1.0,
                      controlled=True)
        count = _item(label="UDL burn count", extraction=1.0)
        burns = (HeldBurn(_BURN_AT, Normality.UNUSUAL),)
        assert _range([early, self._VOUCH], burns=burns).floor is Band.HIGH
        result = _range([early, count, self._VOUCH], burns=burns)
        assert result.floor is Band.HIGH
        # Read on its own q, not the later count's 0.68, since the unusual burn ended it (decision 7).
        own = tu.reliability(early, _NOW, burns=burns)
        assert _row(result, "UDL burn early").note == (
            f"its reading counts once, at its own q {own:.2f}, since a later burn ended it")
        assert round(own, 2) < round(tu.reliability(count, _NOW), 2)

    def test_a_later_copy_never_revives_a_floor_a_later_burn_has_ended(self) -> None:
        # Decision 7: once a later unusual burn ends it, the floor is tested on its own q (0.10 now), never on a
        # later copy's (0.68), so the copy cannot bring it back.
        ended = _item(label="UDL posture", source_grade="C", credibility=3, extraction=0.6, floor_to=Band.HIGH,
                      observed_at=_NOW - 3 * _DAY)
        count = _item(label="UDL burn count", extraction=1.0, observed_at=_NOW)
        burns = (HeldBurn(_BURN_AT, Normality.UNUSUAL),)
        assert round(tu.reliability(ended, _NOW, burns=burns), 2) == 0.10
        assert _range([ended, self._VOUCH], burns=burns).floor is Band.MINIMAL
        result = _range([ended, count, self._VOUCH], burns=burns)
        assert result.floor is Band.MINIMAL
        row = _row(result, "UDL posture")
        assert (row.applied, row.status) == (False, Status.BELOW_THRESHOLD)
        assert row.note == "q 0.10 below 0.25"

    def test_a_new_copy_in_any_chain_never_widens_the_range(self) -> None:
        # Every member of every group gains copies: the same reading or none, weaker or stronger. The pool's burn
        # is judged at the same moment as the pool's floors, so no floor here is one a later burn has ended: the one
        # exception to the property, decision 7, is pinned by the two tests above.
        checked = 0
        for subset in _subsets(_POOL):
            before = _range(subset, burns=_POOL_BURNS)
            for member in subset:
                for extraction in (member.extraction / 2, 1.0):
                    for reading in ({}, {"floor_to": None, "ceiling_to": None}):
                        copy = replace(member, label=f"{member.label} (copy)", extraction=extraction, **reading)
                        after = _range([*subset, copy], burns=_POOL_BURNS)
                        if _conflicted(after) != _conflicted(before):
                            # A copy that adds or settles a conflict is I3's, which widens the range on purpose.
                            continue
                        checked += 1
                        assert after.floor >= before.floor and after.ceiling <= before.ceiling, (
                            [i.label for i in subset], copy.label, extraction, reading)
        assert checked > 3000


class TestTheRange:
    """floor = min(ACCESS, max(F)), ceiling = min(ACCESS, min(C))."""

    def test_with_no_evidence_the_range_is_minimal_to_access(self) -> None:
        for access in Band:
            result = _range([], access=access)
            assert (result.floor, result.ceiling, result.bands) == (Band.MINIMAL, access, int(access) + 1)

    def test_access_bounds_both_ends(self) -> None:
        result = _range([_UDL_BURN], access=Band.MEDIUM, burns=_POOL_BURNS)
        assert (result.floor, result.ceiling) == (Band.MEDIUM, Band.MEDIUM)

    def test_the_strongest_floor_and_the_lowest_ceiling_govern(self) -> None:
        share = replace(_LOW_SHARE, ceiling_to=Band.HIGH)
        result = _range([_UDL_BURN, _ANOMALY, _UDL_RESERVE, share, replace(_SPENT, ceiling_to=Band.CRITICAL)],
                        burns=_POOL_BURNS)
        assert (result.floor, result.ceiling) == (Band.HIGH, Band.HIGH)

    def test_i6_the_ceiling_never_exceeds_access_and_the_floor_never_the_ceiling(self) -> None:
        for access in Band:
            for subset in _subsets(_POOL):
                result = _range(subset, access=access, burns=_POOL_BURNS)
                assert result.floor <= result.ceiling <= access, (access, [i.label for i in subset])


class TestManufacturedEvidenceCannotClearAnObject:
    """I5: manufacturable benign items alone never pull the ceiling below MEDIUM."""

    _DECLARED = tuple(
        _item(dimension=Dimension.CAPABILITY, label=f"declared {name}", derived_from=f"{name}:OP", source_grade="A",
              credibility=1, extraction=1.0, manufacturable=True)
        for name in ("notso", "mission", "website")
    )
    _STATUS = _item(dimension=Dimension.CAPABILITY, label="status Degraded", derived_from="status:1",
                    source_grade="A", credibility=1, extraction=1.0, manufacturable=True, impaired_status=True,
                    ceiling_to=Band.MINIMAL)

    def test_i5_every_subset_of_manufactured_items_leaves_the_ceiling_at_medium_or_above(self) -> None:
        pool = (*self._DECLARED, self._STATUS, _UDL_RESERVE)
        lowest = Band.CRITICAL
        for subset in _subsets(pool):
            result = _range(subset, sees_routine_station_keeping=True)
            assert result.ceiling >= Band.MEDIUM, [i.label for i in subset]
            lowest = min(lowest, result.ceiling)
        # The status reads, at MEDIUM, once the UDL reserve has earned Capability.
        assert lowest is Band.MEDIUM

    def test_manufactured_items_alone_never_earn_capability_so_never_move_the_ceiling(self) -> None:
        # The operator is one source: the three declarations and the status count once, at 0.3.
        for subset in _subsets((*self._DECLARED, self._STATUS)):
            result = _range(subset, sees_routine_station_keeping=True)
            assert result.ceiling is Band.CRITICAL, [i.label for i in subset]
            assert result.coverage[Dimension.CAPABILITY] <= tu.MANUFACTURABLE_CAP

    def test_access_below_medium_still_governs(self) -> None:
        assert _range([self._STATUS, _UDL_RESERVE], access=Band.LOW,
                      sees_routine_station_keeping=True).ceiling is Band.LOW


class TestAnImpairedStatusIsVoidedByANewerBurn:
    """Section 4.7, I7: an impaired status never lowers the ceiling while a newer confirmed burn is held."""

    _STATUS = TestManufacturedEvidenceCannotClearAnObject._STATUS
    # Capability earned by evidence that carries no reading, so only the status could lower the ceiling.
    _EARNERS = (_UDL_RESERVE, replace(_SPENT, label="allied fuel gauge", ceiling_to=None))

    @pytest.mark.parametrize("normality", list(Normality))
    @pytest.mark.parametrize("custody", list(Custody))
    @pytest.mark.parametrize("dated", [True, False])
    def test_i7_the_ceiling_is_what_it_would_be_without_the_status(
        self, normality: Normality, custody: Custody, dated: bool,
    ) -> None:
        status = replace(self._STATUS, observed_at=_BURN_AT - _DAY if dated else None)
        burns = (HeldBurn(_BURN_AT, normality),)
        kw = {"burns": burns, "custody": custody, "sees_routine_station_keeping": True}
        with_status = _range([*self._EARNERS, status], **kw)
        assert with_status.ceiling == _range(list(self._EARNERS), **kw).ceiling
        row = _row(with_status, "status Degraded")
        assert (row.status, row.applied) == (Status.VOIDED, False)
        assert row.note == "voided: possible deception, a confirmed burn newer than the record is held"
        assert with_status.possible_deception == ("status Degraded",)

    def test_a_record_newer_than_every_burn_is_not_voided(self) -> None:
        status = replace(self._STATUS, observed_at=_BURN_AT + _DAY)
        result = _range([*self._EARNERS, status], burns=(HeldBurn(_BURN_AT, Normality.ROUTINE),),
                        sees_routine_station_keeping=True)
        assert result.possible_deception == ()
        # Not voided, but a burn is held, so the status is not corroborated either.
        assert _row(result, "status Degraded").status is Status.UNCORROBORATED

    def test_a_record_dated_at_the_burn_itself_is_not_voided(self) -> None:
        # Voided only by a burn newer than the record.
        status = replace(self._STATUS, observed_at=_BURN_AT)
        result = _range([*self._EARNERS, status], burns=(HeldBurn(_BURN_AT, Normality.UNUSUAL),),
                        sees_routine_station_keeping=True)
        assert result.possible_deception == ()
        assert _row(result, "status Degraded").status is Status.UNCORROBORATED

    def test_a_burn_after_the_clock_has_not_happened_so_voids_nothing(self) -> None:
        status = replace(self._STATUS, observed_at=_NOW - _DAY)
        result = _range([*self._EARNERS, status], burns=(HeldBurn(_NOW + timedelta(hours=1), Normality.UNUSUAL),),
                        sees_routine_station_keeping=True)
        assert result.possible_deception == ()
        assert (result.ceiling, _row(result, "status Degraded").applied) == (Band.MEDIUM, True)

    def test_an_analyst_assessed_impairment_still_never_lowers_the_ceiling_below_medium(self) -> None:
        # Not manufacturable (an allied analyst's assessment), but still a status: MEDIUM at the lowest.
        assessed = replace(self._STATUS, label="impairment assessed", derived_from="allied:analyst",
                           manufacturable=False)
        result = _range([*self._EARNERS, assessed], sees_routine_station_keeping=True)
        assert (result.ceiling, _row(result, "impairment assessed").applied) == (Band.MEDIUM, True)

    def test_a_corroborated_status_lowers_the_ceiling_to_medium_never_lower(self) -> None:
        result = _range([*self._EARNERS, self._STATUS], sees_routine_station_keeping=True)
        assert result.ceiling is Band.MEDIUM
        assert _row(result, "status Degraded").applied

    @pytest.mark.parametrize(("custody", "sees"), [
        (Custody.DEGRADED, True), (Custody.LOST, True), (Custody.HELD, False),
    ])
    def test_without_corroboration_the_status_is_coverage_only(self, custody: Custody, sees: bool) -> None:
        result = _range([self._STATUS, _UDL_RESERVE], custody=custody, sees_routine_station_keeping=sees)
        assert result.ceiling is Band.CRITICAL
        assert _row(result, "status Degraded").status is Status.UNCORROBORATED
        assert _row(result, "status Degraded").note.startswith("not corroborated")


class TestConflictsNeverNarrowTheRange:
    """Section 4.7, I3: a floor above a ceiling removes both readings and names both items."""

    def test_both_readings_of_a_conflicting_pair_are_removed_and_named(self) -> None:
        result = _range([_UDL_BURN, _UDL_RESERVE, _LOW_SHARE], burns=_POOL_BURNS)
        assert (result.floor, result.ceiling) == (Band.MINIMAL, Band.CRITICAL)
        assert result.conflicts == (("UDL burn", "commercial share below half"),)
        for label in ("UDL burn", "commercial share below half"):
            row = _row(result, label)
            assert (row.status, row.applied) == (Status.CONFLICT, False)
        assert _row(result, "UDL burn").note == "in conflict with commercial share below half"

    def test_a_copy_of_a_conflicting_reading_goes_with_it(self) -> None:
        copy = replace(_UDL_BURN, label="UDL burn copy", extraction=0.45)
        result = _range([_UDL_BURN, copy, _UDL_RESERVE, _LOW_SHARE], burns=_POOL_BURNS)
        assert result.coverage[Dimension.BEHAVIOUR] == 0.0
        row = _row(result, "UDL burn copy")
        assert (row.status, row.applied) == (Status.FOLDED, False)
        assert row.note == "same source chain as UDL burn, which is in conflict; not counted"

    def test_a_floor_equal_to_a_ceiling_is_no_conflict(self) -> None:
        posture = _item(label="posture aggressive", derived_from="allied:optical", source_grade="A", credibility=1,
                        extraction=1.0, floor_to=Band.MEDIUM)
        result = _range([posture, _UDL_RESERVE, _LOW_SHARE])
        assert result.conflicts == ()
        assert (result.floor, result.ceiling) == (Band.MEDIUM, Band.MEDIUM)

    def test_i3_adding_a_conflicting_item_never_narrows_the_range(self) -> None:
        checked = 0
        for subset in _subsets(_POOL):
            before = _range(subset, burns=_POOL_BURNS)
            for extra in set(_POOL) - set(subset):
                after = _range([*subset, extra], burns=_POOL_BURNS)
                if extra.label not in _conflicted(after):
                    continue
                checked += 1
                assert after.floor <= before.floor and after.ceiling >= before.ceiling, (
                    [i.label for i in subset], extra.label)
                for floor_label, ceiling_label in after.conflicts:
                    for label, other in ((floor_label, ceiling_label), (ceiling_label, floor_label)):
                        row = _row(after, label)
                        assert (row.status, row.applied) == (Status.CONFLICT, False)
                        assert other in row.note
        assert checked > 100

    def test_a_ceiling_decayed_before_the_floor_was_judged_is_no_conflict(self) -> None:
        # Section 4.7 finds conflicts among applicable readings. A reserve share read
        # 200 days ago had decayed (q 0.1) long before the fresh burn was judged, so it
        # does not remove the burn's floor: suspicion persists, trust decays.
        old_share = replace(_SPENT, label="old share below half", ceiling_to=Band.MEDIUM,
                            observed_at=_NOW - 200 * _DAY)
        floors = [_UDL_BURN, _ALLIED]
        result = _range([*floors, old_share], burns=_POOL_BURNS)
        assert result.conflicts == ()
        assert (result.floor, result.ceiling) == (Band.HIGH, Band.CRITICAL)
        assert _row(result, "old share below half").status is Status.DECAYED

    def test_a_conflict_once_found_is_not_dissolved_by_ageing(self) -> None:
        # Both readings were in effect together. As the share decays, the pair stays named.
        items = [_UDL_BURN, _UDL_RESERVE, _LOW_SHARE]
        for days in (0, 30, 300, 3000):
            result = tu.threat_range(items, _sit(now=_NOW + days * _DAY, burns=_POOL_BURNS))
            assert result.conflicts == (("UDL burn", "commercial share below half"),), days
            assert (result.floor, result.ceiling) == (Band.MINIMAL, Band.CRITICAL)

    def test_i2_a_duplicate_or_a_weaker_copy_changes_no_band_and_no_coverage(self) -> None:
        checked = 0
        for subset in _subsets(_POOL):
            before = _range(subset, burns=_POOL_BURNS)
            for member in subset:
                for copy in (member, replace(member, label=f"{member.label} (copy)", extraction=member.extraction / 2)):
                    after = _range([*subset, copy], burns=_POOL_BURNS)
                    assert (after.floor, after.ceiling, after.coverage, after.conflicts) == (
                        before.floor, before.ceiling, before.coverage, before.conflicts), (
                        [i.label for i in subset], copy.label)
                    checked += 1
        assert checked == 2 * 8 * 2 ** 7

    def test_i1_adding_a_non_conflicting_item_never_widens_and_never_lowers_coverage(self) -> None:
        checked = 0
        for subset in _subsets(_POOL):
            before = _range(subset, burns=_POOL_BURNS)
            for extra in set(_POOL) - set(subset):
                after = _range([*subset, extra], burns=_POOL_BURNS)
                if _conflicted(after) != _conflicted(before):
                    continue
                checked += 1
                assert after.floor >= before.floor and after.ceiling <= before.ceiling, (
                    [i.label for i in subset], extra.label)
                assert all(after.coverage[d] >= before.coverage[d] - _TOL for d in Dimension)
        assert checked > 500

    def test_the_range_does_not_depend_on_the_order_items_arrive(self) -> None:
        items = (_GCAT, _ROLE, _UDL_BURN, _LOW_SHARE, _UDL_RESERVE, _ANOMALY)
        expected = _range(items, burns=_POOL_BURNS)
        for order in itertools.permutations(items):
            assert _range(order, burns=_POOL_BURNS) == expected


class TestRoutineMovesNoBand:
    """I9, and the "Coverage only" row of section 4.6: a ROUTINE verdict adds coverage and moves nothing."""

    _ROUTINE = _item(label="latest burn ROUTINE", derived_from="elset-history:COMM", source_grade="A",
                     credibility=1, extraction=1.0, routine=True)
    _WAITING = _item(label="posture aggressive", derived_from="elset-history:SMALL", source_grade="C",
                     credibility=2, extraction=0.6, floor_to=Band.MEDIUM)

    @pytest.mark.parametrize("history", ["elset-history:COMM", "elset-history:UDL"])
    def test_i9_adding_a_routine_verdict_to_any_subset_moves_no_band(self, history: str) -> None:
        # From the same history as the UDL burn and the anomaly index, the ROUTINE verdict
        # (q 0.5) outweighs the anomaly index (q 0.41), and still folds no reading.
        routine = replace(self._ROUTINE, derived_from=history)
        pool = (*_POOL, self._WAITING)
        for subset in _subsets(pool):
            before = _range(subset, burns=_POOL_BURNS)
            after = _range([*subset, routine], burns=_POOL_BURNS)
            assert (after.floor, after.ceiling) == (before.floor, before.ceiling), [i.label for i in subset]
            assert after.coverage[Dimension.BEHAVIOUR] >= before.coverage[Dimension.BEHAVIOUR]

    def test_a_routine_verdict_from_the_same_history_folds_no_reading(self) -> None:
        # The ROUTINE verdict (q 0.5) outweighs the anomaly index (q 0.41) from the same
        # history, so it counts for coverage; but it leads no reading, so the floor stays.
        routine = replace(self._ROUTINE, derived_from="elset-history:UDL", observed_at=_BURN_AT)
        vouch = replace(_ALLIED, floor_to=None, observed_at=_BURN_AT)
        result = _range([_ANOMALY, vouch, routine], burns=_POOL_BURNS)
        assert result.floor is Band.MEDIUM
        row = _row(result, "anomaly index")
        assert (row.applied, row.counted) == (True, False)

    def test_a_routine_verdict_counts_towards_coverage_but_vouches_for_no_reading(self) -> None:
        # The posture item alone (q 0.306) does not earn Behaviour; with the ROUTINE verdict
        # Behaviour reads 0.65, but the self-referential baseline vouches for nothing.
        result = _range([self._WAITING, self._ROUTINE])
        assert result.coverage[Dimension.BEHAVIOUR] == pytest.approx(1 - (1 - 0.306) * (1 - 0.5))
        assert result.floor is Band.MINIMAL
        assert "Behaviour not earned" in _row(result, "posture aggressive").note


class TestSuspicionPersistsTrustDecays:
    """Section 4.4: a floor earned when judged stays until a later burn is judged; a ceiling decays."""

    _T0 = _NOW - _DAY
    _BURN = _item(label="UDL burn", observed_at=_NOW - _DAY, floor_to=Band.HIGH, controlled=True)
    _HOSTILE = HeldBurn(_NOW - _DAY, Normality.UNPRECEDENTED)

    def test_a_floor_earned_when_judged_stays_as_its_coverage_decays(self) -> None:
        later = _sit(now=_NOW + 60 * _DAY, burns=(self._HOSTILE,))
        result = tu.threat_range([self._BURN], later)
        assert result.coverage[Dimension.BEHAVIOUR] < tu.EARNED
        assert result.floor is Band.HIGH
        row = _row(result, "UDL burn")
        assert (row.status, row.applied) == (Status.PERSISTING, True)
        assert row.note == "kept until a later unusual or unprecedented burn is judged; re-observe"
        assert result.reobserve == ("UDL burn",)

    @pytest.mark.parametrize("normality", [Normality.UNUSUAL, Normality.UNPRECEDENTED])
    def test_a_later_hostile_burn_lets_it_decay(self, normality: Normality) -> None:
        later = _sit(now=_NOW + 60 * _DAY, burns=(self._HOSTILE, HeldBurn(_NOW + 10 * _DAY, normality)))
        result = tu.threat_range([self._BURN], later)
        assert result.floor is Band.MINIMAL
        row = _row(result, "UDL burn")
        assert row.status is Status.DECAYED
        assert row.note.endswith("; a later unusual or unprecedented burn has been judged")

    @pytest.mark.parametrize("normality", [Normality.ROUTINE, Normality.NOT_ENOUGH_HISTORY])
    def test_a_later_routine_or_unjudged_burn_does_not(self, normality: Normality) -> None:
        # ROUTINE lowers nothing (section 5.3, section 8, I9): routine-looking station
        # keeping is how an adversary would feign benignity.
        later = _sit(now=_NOW + 60 * _DAY, burns=(self._HOSTILE, HeldBurn(_NOW + 10 * _DAY, normality)))
        result = tu.threat_range([self._BURN], later)
        assert result.floor is Band.HIGH
        assert _row(result, "UDL burn").status is Status.PERSISTING

    def test_an_undated_floor_is_older_than_any_hostile_burn(self) -> None:
        # The role prior (undated, q 0.4) was judged while the GCAT entry vouched for
        # Identity. Three years on GCAT has decayed, so the prior persists, unless a
        # hostile burn is held: an undated record is older than any burn.
        gcat = replace(_GCAT, observed_at=_NOW)
        role = replace(_ROLE, source_grade="B", credibility=1, extraction=1.0, observed_at=None)
        later = _NOW + 3 * 365 * _DAY
        quiet = tu.threat_range([gcat, role], _sit(now=later))
        assert (quiet.floor, _row(quiet, "dated role").status) == (Band.MEDIUM, Status.PERSISTING)
        burnt = tu.threat_range([gcat, role], _sit(now=later, burns=_POOL_BURNS))
        assert (burnt.floor, _row(burnt, "dated role").status) == (Band.MINIMAL, Status.DECAYED)

    def test_a_floor_never_earned_does_not_persist(self) -> None:
        weak = replace(self._BURN, source_grade="E")
        result = tu.threat_range([weak], _sit(now=_NOW + 60 * _DAY, burns=(self._HOSTILE,)))
        assert (result.floor, _row(result, "UDL burn").status) == (Band.MINIMAL, Status.BELOW_THRESHOLD)

    def test_a_later_item_does_not_vouch_for_an_earlier_step(self) -> None:
        # The posture (q 0.4) alone did not earn Behaviour when it was judged. The allied
        # track arrives 60 days later, when the posture has decayed to 0.2: it was never read.
        posture = _item(label="posture", derived_from="small", credibility=1, extraction=0.5,
                        observed_at=_NOW - 60 * _DAY, floor_to=Band.MEDIUM)
        track = replace(_ALLIED, observed_at=_NOW, floor_to=None, extraction=1.0)
        result = _range([posture, track])
        assert result.floor is Band.MINIMAL
        assert _row(result, "posture").status is Status.BELOW_THRESHOLD

    def test_an_item_is_not_judged_before_it_was_observed(self) -> None:
        # The allied track earned Behaviour 130 days ago and has decayed to 0.2. The posture
        # (q 0.3) arrives now, when the two together cover 0.44: it was never read.
        track = replace(_ALLIED, observed_at=_NOW - 130 * _DAY, floor_to=None, extraction=1.0)
        posture = _item(label="posture", derived_from="small", credibility=1, extraction=0.375,
                        observed_at=_NOW, floor_to=Band.MEDIUM)
        result = _range([track, posture])
        assert result.coverage[Dimension.BEHAVIOUR] < tu.EARNED
        assert result.floor is Band.MINIMAL

    def test_an_epoch_ahead_of_the_clock_counts_as_observed_now(self) -> None:
        early = replace(_UDL_BURN, observed_at=_NOW + timedelta(hours=2))
        result = _range([early], burns=_POOL_BURNS)
        assert result.floor is Band.HIGH
        assert _row(result, "UDL burn").age_days == 0.0

    def test_a_ceiling_decays_normally(self) -> None:
        spent = replace(_SPENT, observed_at=self._T0)
        assert tu.threat_range([spent], _sit()).ceiling is Band.MINIMAL
        result = tu.threat_range([spent], _sit(now=_NOW + 300 * _DAY))
        assert result.ceiling is Band.CRITICAL
        row = _row(result, "reserve exhausted")
        assert (row.status, row.applied) == (Status.DECAYED, False)
        assert row.note.startswith("earned when judged; decayed to q 0.09")

    def test_i4_ageing_never_lowers_the_floor_before_a_later_burn(self) -> None:
        offsets = (0, 1, 7, 30, 90, 365, 1000)
        for subset in _subsets(_POOL):
            floors = [tu.threat_range(subset, _sit(now=_NOW + d * _DAY, burns=_POOL_BURNS)).floor for d in offsets]
            assert floors == sorted(floors), [i.label for i in subset]


class TestTheLedger:
    """I10 (the ledger half; the hash is SPC-166) and I11 (basis and grade; cues are SPC-170)."""

    def test_every_row_carries_a_basis_a_grade_and_an_age(self) -> None:
        result = _range(_POOL, burns=_POOL_BURNS)
        assert len(result.ledger) == len(_POOL)
        for row in result.ledger:
            assert isinstance(row.item.basis, Basis)
            assert row.item.grade[0] in tu.SOURCE_RELIABILITY and int(row.item.grade[1]) in tu.CREDIBILITY
            assert 0.0 <= row.q <= 1.0
            assert row.age_days is not None and row.age_days >= 0.0

    def test_an_undated_row_has_no_age(self) -> None:
        undated = replace(_GCAT, observed_at=None)
        assert _row(_range([undated]), "gcat").age_days is None

    def test_the_same_inputs_give_the_same_ledger(self) -> None:
        assert _range(_POOL, burns=_POOL_BURNS) == _range(list(reversed(_POOL)), burns=_POOL_BURNS)


class TestTheVerdictRule:
    """Section 4.8: the legacy reading sets the point inside the range; LOW or a wide range reads the ceiling."""

    def test_the_assessed_point_is_the_legacy_reading_clamped_to_the_range(self) -> None:
        assert tu.verdict_for(Band.CRITICAL, Band.LOW, Band.MEDIUM, Understanding.HIGH).assessed is Band.MEDIUM
        assert tu.verdict_for(Band.MINIMAL, Band.LOW, Band.MEDIUM, Understanding.HIGH).assessed is Band.LOW
        assert tu.verdict_for(Band.LOW, Band.LOW, Band.MEDIUM, Understanding.HIGH).assessed is Band.LOW

    def test_i6_across_every_band_and_level(self) -> None:
        for legacy, floor, ceiling in itertools.product(Band, Band, Band):
            if floor > ceiling:
                continue
            for level in Understanding:
                v = tu.verdict_for(legacy, floor, ceiling, level)
                assert floor <= v.assessed <= ceiling
                wide = int(ceiling) - int(floor) + 1 >= 4
                assert v.at_ceiling == (level is Understanding.LOW or wide)
                assert v.band == (ceiling if v.at_ceiling else v.assessed)

    def test_a_range_of_three_bands_at_moderate_reads_the_assessed_point(self) -> None:
        v = tu.verdict_for(Band.LOW, Band.LOW, Band.HIGH, Understanding.MODERATE)
        assert (v.band, v.at_ceiling) == (Band.LOW, False)

    def test_a_range_of_four_bands_reads_the_ceiling(self) -> None:
        v = tu.verdict_for(Band.LOW, Band.LOW, Band.CRITICAL, Understanding.HIGH)
        assert (v.band, v.at_ceiling) == (Band.CRITICAL, True)

    def test_a_range_upside_down_is_refused(self) -> None:
        with pytest.raises(ValueError, match="floor above the ceiling"):
            tu.verdict_for(Band.LOW, Band.HIGH, Band.LOW, Understanding.HIGH)
