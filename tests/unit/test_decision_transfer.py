"""Every burn of a transfer on one adversary row (SPC-184).

Owner ruling of 2026-11-05 (concept section 9, decision 13): a scenario opened from the sweep carries every burn
of the transfer, not its first alone. The burns are one adversary action with one P, never alternatives. Each
has its own UTC time and its own prograde, normal and radial parts in m/s, and they are applied to the red orbit
in time order wherever the row is sampled or computed. A burn at or before the bound red element set's epoch is
never applied, since the set may already include it: exactly those are dropped, the rest kept, and the result
says which and why. A row whose every burn is dropped is refused as a single burn that set may include is today.
Custody reads the earliest burn still applied; the cost counts the row's integration from its first applied
burn; the game tree, whose equal turns put a row's burn at one time in every turn, refuses such a row (D3, D7;
unequal turns are SPC-187). The single-burn path is unchanged: tests/unit/test_decision_sampled.py and the
reference cases hold it.

The engine's rules run against a fake sampler in milliseconds; the propagator's are checked on the plane-change
reference orbits.
"""

from __future__ import annotations

import dataclasses
import html
import re
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pytest

from spectre.astro.monte_carlo import (
    ManoeuvreHypothesis,
    SeparationSeries,
    SeparationWindow,
    _ric_to_eci_rotation,
    elset_state,
    nominal_red_arc,
    run_separation_series,
)
from spectre.domain import decision, decision_tree
from spectre.domain.decision import (
    AdversaryHypothesis,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    TurnRule,
    evaluate_scenario,
)
from spectre.domain.decision_transfer import MAX_TRANSFER_BURNS, TransferBurn, row_burns
from spectre.domain.provenance import Basis
from spectre.web.decision_job import evaluated_line
from spectre.web.decision_trajectory import trajectory_links
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit._i13 import i13_problems
from tests.unit.test_decision_custody import _HELD
from tests.unit.test_decision_sampled import _elset, _Fake, _scenario, _steady

_BURN_2 = EPOCH + timedelta(minutes=15)
_BURN_3 = EPOCH + timedelta(minutes=30)


def _later(at: datetime, prograde: float = 2.0, normal: float = 0.5, radial: float = -1.0) -> TransferBurn:
    return TransferBurn(at, prograde_m_s=prograde, normal_m_s=normal, radial_m_s=radial)


def _transfer(first_at: datetime = EPOCH, *later: TransferBurn, n: int = 50) -> AdversaryHypothesis:
    """A 1 m/s in-track first burn at *first_at* from red's own state there, then *later* (two by default)."""
    then = later or (_later(_BURN_2), _later(_BURN_3, 1.0, 0.0, 0.0))
    return _steady(n, at=first_at).with_transfer(then)


def _red_at(epoch: datetime) -> ScenarioBinding:
    """Red's element set dated *epoch*, its age counted to the scenario epoch, both sides current and custody held."""
    age = (EPOCH - epoch).total_seconds() / 3600.0
    red = dataclasses.replace(_elset("red", age=age, epoch=epoch), custody=_HELD)
    return ScenarioBinding(red=red, blue=_elset("blue"))


def _with(hypothesis: AdversaryHypothesis, binding: ScenarioBinding | None = None) -> Scenario:
    return _scenario({0: hypothesis}, binding=binding or _red_at(EPOCH - timedelta(hours=1)))


class _Recorder(_Fake):
    """The fake sampler, taking and recording the keywords the engine passes."""

    def __init__(self, **series: Any) -> None:
        super().__init__(**series)
        self.keywords: list[dict[str, Any]] = []

    def __call__(  # type: ignore[override]
        self, hypothesis: ManoeuvreHypothesis, blue: Any, window: SeparationWindow, **kw: Any,
    ) -> SeparationSeries:
        self.keywords.append(kw)
        return super().__call__(hypothesis, blue, window)


# ── The transfer as a hypothesis carries it ──

class TestAHypothesisCarriesItsTransfer:
    def test_the_later_burns_are_carried_in_time_order_after_the_first(self) -> None:
        carried = _transfer()
        assert [b.at_utc for b in carried.then] == [_BURN_2, _BURN_3]
        assert carried.then[0].dv_m_s == pytest.approx((2.0**2 + 0.5**2 + 1.0) ** 0.5)
        # Read in RIC as the sweep's first burn is: radial, then prograde as in-track, then normal as cross-track.
        assert carried.then[0].ric_km_s == pytest.approx((-0.001, 0.002, 0.0005))

    @pytest.mark.parametrize("then", [
        (_later(EPOCH - timedelta(seconds=1)),),
        (_later(_BURN_3), _later(_BURN_2)),
    ], ids=["before the first", "out of order"])
    def test_a_burn_out_of_time_order_is_refused(self, then: tuple[TransferBurn, ...]) -> None:
        with pytest.raises(ValueError, match="time order"):
            _steady(50).with_transfer(then)

    def test_more_burns_than_a_transfer_takes_are_refused(self) -> None:
        then = tuple(_later(EPOCH + timedelta(minutes=k)) for k in range(1, MAX_TRANSFER_BURNS + 1))
        with pytest.raises(ValueError, match=f"at most {MAX_TRANSFER_BURNS} burns"):
            _steady(50).with_transfer(then)

    @pytest.mark.parametrize(("at", "part"), [
        (_BURN_2.replace(tzinfo=None), 1.0), (_BURN_2, float("nan")), (_BURN_2, float("inf")),
    ], ids=["no UTC offset", "nan", "infinite"])
    def test_a_burn_with_no_utc_offset_or_a_part_not_finite_is_refused(self, at: datetime, part: float) -> None:
        with pytest.raises(ValueError, match="UTC time|finite"):
            TransferBurn(at, prograde_m_s=part, normal_m_s=0.0, radial_m_s=0.0)

    def test_the_record_names_every_later_burn_and_a_single_burn_records_as_before(self) -> None:
        single = _steady(50).recorded()
        assert "then" not in single
        recorded = _transfer().recorded()
        assert recorded["then"] == [
            {"at_utc": _BURN_2.isoformat(), "prograde_m_s": 2.0, "normal_m_s": 0.5, "radial_m_s": -1.0},
            {"at_utc": _BURN_3.isoformat(), "prograde_m_s": 1.0, "normal_m_s": 0.0, "radial_m_s": 0.0},
        ]
        assert {k: v for k, v in recorded.items() if k != "then"} == single
        assert _transfer() != _steady(50)


# ── Which burns a row applies ──

class TestWhichBurnsARowApplies:
    def test_a_single_burn_row_is_its_hypothesis_unchanged(self) -> None:
        carried = _steady(50)
        burns = row_burns(carried.hypothesis, carried.then, EPOCH + timedelta(hours=1), PLANE_CHANGE.red_tle)
        assert burns.first is carried.hypothesis
        assert (burns.then, burns.dropped, burns.several) == ((), (), False)

    def test_every_burn_after_the_red_set_is_applied_from_the_first(self) -> None:
        carried = _transfer()
        burns = row_burns(carried.hypothesis, carried.then, EPOCH - timedelta(hours=1), PLANE_CHANGE.red_tle)
        assert burns.first is carried.hypothesis
        assert [h.epoch_utc for h in burns.then] == [_BURN_2, _BURN_3]
        assert (burns.applied, burns.dropped) == ((1, 2, 3), ())

    @pytest.mark.parametrize("red_epoch", [EPOCH + timedelta(minutes=5), _BURN_2 - timedelta(minutes=1)])
    def test_a_burn_before_the_red_set_is_dropped_and_the_row_starts_from_the_next(self, red_epoch: datetime) -> None:
        carried = _transfer()
        burns = row_burns(carried.hypothesis, carried.then, red_epoch, PLANE_CHANGE.red_tle)
        assert (burns.applied, burns.dropped) == ((2, 3), (1,))
        assert burns.first.epoch_utc == _BURN_2
        # It starts from the bound red track's own state at burn 2, which may already include burn 1.
        red = elset_state(PLANE_CHANGE.red_tle, _BURN_2)
        assert red is not None
        assert list(burns.first.pre_manoeuvre_state_eci_km) == list(red.state_eci_km)
        assert (burns.first.delta_v_radial, burns.first.delta_v_in_track, burns.first.delta_v_cross_track) == (
            pytest.approx(-0.001), pytest.approx(0.002), pytest.approx(0.0005))
        assert [h.epoch_utc for h in burns.then] == [_BURN_3]

    def test_a_burn_at_the_red_sets_own_epoch_is_dropped(self) -> None:
        carried = _transfer()
        burns = row_burns(carried.hypothesis, carried.then, _BURN_2, PLANE_CHANGE.red_tle)
        assert (burns.applied, burns.dropped) == ((3,), (1, 2))
        assert burns.first.epoch_utc == _BURN_3

    def test_with_every_burn_dropped_the_row_keeps_its_first_for_the_refusal(self) -> None:
        carried = _transfer()
        burns = row_burns(carried.hypothesis, carried.then, _BURN_3 + timedelta(minutes=1), PLANE_CHANGE.red_tle)
        assert (burns.applied, burns.dropped, burns.all_dropped) == ((), (1, 2, 3), True)
        assert burns.first is carried.hypothesis and burns.then == ()

    def test_each_later_burn_draws_its_own_seed_and_the_spread_in_proportion(self) -> None:
        carried = _transfer()
        burns = row_burns(carried.hypothesis, carried.then, None, PLANE_CHANGE.red_tle)
        first = carried.hypothesis
        seeds = {first.random_seed, *(h.random_seed for h in burns.then)}
        assert len(seeds) == 3
        share = first.delta_v_magnitude_1sigma_km_s / first.delta_v_magnitude_km_s
        for h, burn in zip(burns.then, carried.then, strict=True):
            assert h.delta_v_magnitude_km_s == pytest.approx(burn.dv_m_s / 1000.0)
            assert h.delta_v_magnitude_1sigma_km_s == pytest.approx(share * h.delta_v_magnitude_km_s)
            assert (h.delta_v_pointing_1sigma_deg, h.epoch_1sigma_seconds, h.bstar_1sigma) == (
                first.delta_v_pointing_1sigma_deg, first.epoch_1sigma_seconds, first.bstar_1sigma)
        # The same burn draws the same seed whichever burns before it are dropped.
        later = row_burns(carried.hypothesis, carried.then, EPOCH + timedelta(minutes=1), PLANE_CHANGE.red_tle)
        assert later.first.random_seed == burns.then[0].random_seed


# ── The engine applies every burn applied, and says so ──

class TestTheEngineSamplesEveryBurn:
    def test_the_sampler_gets_the_first_burn_and_every_later_one(self) -> None:
        fake = _Recorder()
        scenario = _with(_transfer())
        evaluate_scenario(scenario, sampler=fake)
        hypothesis, _blue, _window = fake.calls[0]
        assert hypothesis.epoch_utc == EPOCH
        assert [h.epoch_utc for h in fake.keywords[0]["red_then"]] == [_BURN_2, _BURN_3]

    def test_a_single_burn_row_passes_no_later_burns(self) -> None:
        fake = _Recorder()
        evaluate_scenario(_with(_steady(50)), sampler=fake)
        assert "red_then" not in fake.keywords[0]

    def test_a_dropped_first_burn_starts_the_series_from_the_next(self) -> None:
        fake = _Recorder()
        early = EPOCH - timedelta(minutes=30)
        evaluate_scenario(_with(_transfer(early), _red_at(EPOCH)), sampler=fake)
        hypothesis, _blue, _window = fake.calls[0]
        assert hypothesis.epoch_utc == _BURN_2
        assert [h.epoch_utc for h in fake.keywords[0]["red_then"]] == [_BURN_3]

    def test_a_row_whose_every_burn_is_dropped_is_refused_as_a_single_burn_is(self) -> None:
        early = (EPOCH - timedelta(hours=2), EPOCH - timedelta(hours=1))
        carried = _transfer(early[0], _later(early[1]))
        fake = _Recorder()
        result = evaluate_scenario(_with(carried, _red_at(EPOCH - timedelta(minutes=30))), sampler=fake)
        single = evaluate_scenario(_with(_steady(50, at=early[0]), _red_at(EPOCH - timedelta(minutes=30))),
                                   sampler=_Recorder())
        assert fake.calls == []
        assert [c.ca_refusal for c in result.outcome_matrix[0]] == [c.ca_refusal for c in single.outcome_matrix[0]]
        assert "Not sampled: the red element set dates from" in str(result.outcome_matrix[0][0].ca_refusal)

    def test_a_row_whose_every_burn_is_at_the_red_sets_own_epoch_is_refused_too(self) -> None:
        # Equal times pass require_transfer and the route, and _after_burn alone refuses only a set strictly newer.
        at = EPOCH - timedelta(minutes=30)
        fake = _Recorder()
        result = evaluate_scenario(_with(_transfer(at, _later(at)), _red_at(at)), sampler=fake)
        assert fake.calls == []
        for cell in result.outcome_matrix[0]:
            assert cell.ca_percentiles is None
            assert cell.ca_refusal is not None and (
                "Not sampled: the red element set dates from 2026-10-17 11:30 UTC, at or after every burn of this "
                "row's transfer, so it may already include each, and sampling would apply them twice."
            ) in cell.ca_refusal
        assert "so the row is not sampled, as its cells say." in str(result.row_transfers[0])

    def test_each_figure_names_how_many_burns_it_applied(self) -> None:
        result = evaluate_scenario(_with(_transfer(EPOCH - timedelta(minutes=30)), _red_at(EPOCH)), sampler=_Recorder())
        flies = ("; red flies the 2 of this row's 3 burns due before the span searched ends, each at its own drawn "
                 "time if that is inside the span")
        for cell in result.outcome_matrix[0]:
            notes = dict(cell.figure_bases.items())
            assert notes["closest_approach_km"].kind is Basis.SAMPLED
            assert notes["closest_approach_km"].note.endswith(flies)
            assert notes["time_to_closest_hours"].note.endswith(flies)
            for name in ("custody_maintained", "custody_gap_hours"):
                assert notes[name].note.endswith("; it reads burn 2 of this row's 3, the earliest applied"), name
            assert notes["composite_score"].note.endswith("; it applies none of this row's 3 burns itself")
        # A lookup applies none.
        assert dict(result.outcome_matrix[0][0].figure_bases.items())["delta_v_cost_km_s"].note.endswith(
            "; it applies none of this row's 3 burns")

    def test_custody_with_every_burn_dropped_says_it_reads_none(self) -> None:
        carried = _transfer(EPOCH - timedelta(hours=2), _later(EPOCH - timedelta(hours=1)))
        result = evaluate_scenario(_with(carried, _red_at(EPOCH - timedelta(minutes=30))), sampler=_Recorder())
        notes = dict(result.outcome_matrix[0][0].figure_bases.items())
        assert notes["custody_maintained"].note.endswith(
            "; it reads none of this row's 2 burns, since none is newer than the red element set")

    def test_a_single_burn_rows_bases_are_unchanged(self) -> None:
        one = evaluate_scenario(_with(_steady(50)), sampler=_Recorder())
        assert all("this row's" not in basis.note for cell in one.outcome_matrix[0]
                   for _name, basis in cell.figure_bases.items())

    def test_custody_reads_the_earliest_burn_applied(self) -> None:
        dropped_first = _transfer(EPOCH - timedelta(minutes=30))
        result = evaluate_scenario(_with(dropped_first, _red_at(EPOCH)), sampler=_Recorder())
        at_burn_2 = evaluate_scenario(_with(_steady(50, at=_BURN_2), _red_at(EPOCH)), sampler=_Recorder())
        assert result.row_custody[0] == at_burn_2.row_custody[0]
        cell, single = result.outcome_matrix[0][0], at_burn_2.outcome_matrix[0][0]
        assert (cell.custody_maintained, cell.custody_gap_hours) == (single.custody_maintained, single.custody_gap_hours)

    def test_the_propagator_gap_measures_red_from_its_first_applied_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[ManoeuvreHypothesis, ...]] = []
        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", lambda *args: seen.append(args[3]) or 1.0)
        evaluate_scenario(_with(_transfer(EPOCH - timedelta(minutes=30)), _red_at(EPOCH)), sampler=_Recorder())
        assert [[h.epoch_utc for h in sampled] for sampled in seen] == [[_BURN_2]]

    def test_a_burn_at_the_end_of_the_span_is_flown_by_no_figure(self) -> None:
        # The propagator makes a burn only before the span ends, so one exactly at its end is not counted as flown.
        end = EPOCH + timedelta(hours=1)
        carried = _transfer(EPOCH, _later(_BURN_2), _later(end))
        burns = row_burns(carried.hypothesis, carried.then, None, PLANE_CHANGE.red_tle)
        assert (burns.applied_by(end), burns.after(end)) == (2, (3,))

    def test_the_cost_counts_from_the_first_applied_burn(self) -> None:
        dropped_first = _with(_transfer(EPOCH - timedelta(hours=2), _later(_BURN_2), n=500), _red_at(EPOCH))
        from_burn_2 = _with(_steady(500, at=_BURN_2).with_transfer(()), _red_at(EPOCH))
        rows = [r for r in decision._eligible_rows(dropped_first) if r is not None]
        alone = [r for r in decision._eligible_rows(from_burn_2) if r is not None]
        assert decision._cost(decision._Work(rows)) == pytest.approx(decision._cost(decision._Work(alone)))
        # Had it counted from burn 1, two hours before the window, it would cost more.
        first = _with(_steady(500, at=EPOCH - timedelta(hours=2)), _red_at(EPOCH - timedelta(hours=3)))
        whole = [r for r in decision._eligible_rows(first) if r is not None]
        assert decision._cost(decision._Work(whole)) > decision._cost(decision._Work(rows))

    def test_our_burn_is_sized_against_red_flying_every_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[ManoeuvreHypothesis, ...]] = []

        def spy(*_args: Any, then: tuple[ManoeuvreHypothesis, ...] = (), **_kw: Any) -> None:
            seen.append(then)

        monkeypatch.setattr(decision, "hypothesis_response_plan", spy)
        scenario = _with(_transfer())
        row = next(r for r in decision._eligible_rows(scenario) if r is not None)
        decision._size_row(row, decision.cast("Any", row.blue_track), decision._Responses((), {}), None)
        assert [h.epoch_utc for h in seen[0]] == [_BURN_2, _BURN_3]


@pytest.fixture(scope="module")
def dropped() -> ScenarioResult:
    return evaluate_scenario(_with(_transfer(EPOCH - timedelta(minutes=30)), _red_at(EPOCH)), sampler=_Recorder())


class TestTheResultAndTheLedgerNameEveryBurn:
    def test_the_result_says_which_burns_are_applied_and_which_dropped_and_why(self, dropped: ScenarioResult) -> None:
        assert dropped.row_transfers[0] == (
            "This row carries 3 burns of one transfer, one action with one P, listed in time order: burn 1 at "
            "11:30 UTC on 17 Oct, 1.0 m/s (prograde 1.0, normal 0.0 and radial 0.0 m/s); burn 2 at 12:15 UTC on "
            "17 Oct, 2.3 m/s (prograde 2.0, normal 0.5 and radial -1.0 m/s); burn 3 at 12:30 UTC on 17 Oct, 1.0 m/s "
            "(prograde 1.0, normal 0.0 and radial 0.0 m/s). Burn 1 is not applied: it is at or before the red "
            "element set's epoch, 12:00 UTC on 17 Oct, which may already include it. Burns 2 and 3 are applied, in "
            "time order."
        )
        # It never says every burn is applied when one is not.
        assert "applied in time order as one action" not in str(dropped.row_transfers[0])
        assert dropped.row_transfers[1:] == (None, None, None)

    def test_a_single_burn_result_names_no_transfer(self) -> None:
        assert evaluate_scenario(_with(_steady(50)), sampler=_Recorder()).row_transfers == (None,) * 4

    def test_every_burn_dropped_is_said(self) -> None:
        carried = _transfer(EPOCH - timedelta(hours=2), _later(EPOCH - timedelta(hours=1)))
        result = evaluate_scenario(_with(carried, _red_at(EPOCH - timedelta(minutes=30))), sampler=_Recorder())
        assert str(result.row_transfers[0]).endswith(
            "None of its 2 burns is applied: each is at or before the red element set's epoch, 11:30 UTC on 17 Oct, "
            "which may already include it, so the row is not sampled, as its cells say.")

    def test_provenance_carries_every_burn_applied_and_dropped(self, dropped: ScenarioResult) -> None:
        assert dropped.provenance is not None
        transfer = [ref for ref in dropped.provenance.inputs if ref.label.startswith("transfer A0")]
        expected = decision.value_input("transfer A0", {
            "applied": [
                {"burn": 2, "at_utc": _BURN_2.isoformat(), "prograde_m_s": 2.0, "normal_m_s": 0.5, "radial_m_s": -1.0},
                {"burn": 3, "at_utc": _BURN_3.isoformat(), "prograde_m_s": 1.0, "normal_m_s": 0.0, "radial_m_s": 0.0},
            ],
            "dropped": [{"burn": 1, "at_utc": (EPOCH - timedelta(minutes=30)).isoformat(), "prograde_m_s": 1.0,
                         "normal_m_s": 0.0, "radial_m_s": 0.0}],
            "red_epoch": EPOCH.isoformat(),
        })
        assert [(ref.label, ref.sha256) for ref in transfer] == [(expected.label, expected.sha256)]

    def test_the_ledger_line_names_the_burns_applied_and_dropped(self, dropped: ScenarioResult) -> None:
        line = evaluated_line(dropped.scenario, dropped)
        assert line.endswith(" Row A0 (manoeuvre): burns 2 and 3 of 3 applied; burn 1 dropped, at or before the red "
                             "element set's epoch.")
        single = evaluate_scenario(_with(_steady(50)), sampler=_Recorder())
        assert "applied;" not in evaluated_line(single.scenario, single)

    def test_every_sentence_keeps_i13_and_the_house_style(self, dropped: ScenarioResult) -> None:
        # Each figure's own words for the burns follow its last semicolon; the notes before them are as they were.
        sentences = [str(dropped.row_transfers[0]), *(b.note.rsplit(";", 1)[-1] for c in dropped.outcome_matrix[0]
                                                      for _n, b in c.figure_bases.items())]
        assert [s for s in sentences if i13_problems(s)] == []
        assert not any("—" in s or "--" in s for s in sentences)


# ── The game tree ──

class TestTheGameTreeRefusesARowOfSeveralBurns:
    def test_over_equal_turns_the_tree_is_refused_naming_why_and_the_one_turn_result_stands(self) -> None:
        # A record 0.28.0 to 0.36.0 wrote is built over equal turns, as it was then (SPC-187).
        scenario = dataclasses.replace(_with(_transfer()), turns=2, turn_rule=TurnRule.EQUAL)
        assert decision_tree.refused_before_run(scenario) == (
            "No tree built: row 1, manoeuvre, carries 3 burns of one transfer. Equal turns put a row's burn at the "
            "same time after every turn starts, so they cannot give each of its burns a turn of its own. This result "
            "is one turn."
        )
        assert decision_tree.depth_refusal(scenario) is None

    def test_the_engines_turns_refuse_it_only_with_fewer_turns_than_burns(self) -> None:
        # Owner ruling of 2026-11-05 on D3 (SPC-187): every burn falls inside a turn of its own.
        scenario = dataclasses.replace(_with(_transfer()), turns=2)
        assert decision_tree.refused_before_run(scenario) == (
            "No tree built: row 1, manoeuvre, makes 3 burns of one transfer within the span searched, and every burn "
            "falls inside a turn of its own, so it needs 3 turns, more than the 2 asked for. This result is one turn."
        )
        assert decision_tree.depth_refusal(scenario) is None
        # With three turns its burns fit, one to a turn: what refuses it then is its size.
        three = decision_tree.refused_before_run(dataclasses.replace(scenario, turns=3))
        assert three is not None and three.startswith("No tree built: 3 turns of 4 red moves and 4 responses make ")

    def test_every_tree_refusal_is_in_the_sentences_the_house_checks_run_on(self) -> None:
        unlisted = [name for name in dir(decision_tree) if name.startswith("TREE_")
                    and isinstance(getattr(decision_tree, name), str)
                    and getattr(decision_tree, name) not in decision_tree.SENTENCES]
        assert unlisted == []

    def test_a_single_burn_row_is_not_refused_for_its_burns(self) -> None:
        scenario = dataclasses.replace(_with(_steady(50, at=EPOCH + timedelta(minutes=5))), turns=2)
        refusal = decision_tree.refused_before_run(scenario)
        assert refusal is None or "burns of one transfer" not in refusal


# ── The propagator applies every burn, in time order ──

def _window() -> SeparationWindow:
    return SeparationWindow(start_utc=EPOCH, span_s=3600.0)


class TestThePropagatorAppliesEveryBurn:
    def test_a_later_burn_changes_the_nominal_arc_by_its_delta_v_at_its_time(self) -> None:
        carried = _transfer(EPOCH, _later(_BURN_2, 20.0, 5.0, -3.0))
        later = row_burns(carried.hypothesis, carried.then, None, PLANE_CHANGE.red_tle).then
        one = nominal_red_arc(carried.hypothesis, _window())
        both = nominal_red_arc(carried.hypothesis, _window(), later)
        assert one is not None and both is not None
        at_s = 900.0
        before = one(at_s - 1.0), both(at_s - 1.0)
        assert np.allclose(before[0], before[1], atol=1e-9)
        state = one(at_s)
        expected = _ric_to_eci_rotation(state[:3], state[3:]) @ np.array([-0.003, 0.020, 0.005])
        assert np.allclose(both(at_s)[3:] - state[3:], expected, atol=1e-9)
        assert np.allclose(both(at_s)[:3], state[:3], atol=1e-6)

    def test_a_series_flies_every_burn_and_costs_what_one_burn_from_the_first_costs(self) -> None:
        carried = _transfer(EPOCH, _later(_BURN_2, 20.0, 5.0, -3.0))
        later = row_burns(carried.hypothesis, carried.then, None, PLANE_CHANGE.red_tle).then
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        one = run_separation_series(carried.hypothesis, blue, _window())
        both = run_separation_series(carried.hypothesis, blue, _window(), red_then=later)
        assert both.n_failed == 0 and len(both.approaches) == 50
        assert [a.miss_km for a in both.approaches] != pytest.approx([a.miss_km for a in one.approaches])
        assert both.integration_s == one.integration_s

    def test_a_later_burn_after_the_window_changes_nothing(self) -> None:
        carried = _transfer(EPOCH, _later(EPOCH + timedelta(hours=2), 20.0, 5.0, -3.0))
        later = row_burns(carried.hypothesis, carried.then, None, PLANE_CHANGE.red_tle).then
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        one = run_separation_series(carried.hypothesis, blue, _window())
        both = run_separation_series(carried.hypothesis, blue, _window(), red_then=later)
        assert [a.miss_km for a in both.approaches] == pytest.approx([a.miss_km for a in one.approaches], abs=1e-9)


# ── What the results page shows ──

class TestTheResultsShowEveryBurn:
    def test_the_transfer_line_is_under_its_row(self, dropped: ScenarioResult) -> None:
        from tests.unit.test_decision_figure_basis import _render, _text

        page = _render(dropped)
        lines = re.findall(r'<div class="row-transfer"[^>]*>(.*?)</div>', page, re.S)
        assert [html.unescape(" ".join(line.split())) for line in lines] == [dropped.row_transfers[0]]
        assert "Burn 1 is not applied" in html.unescape(_text(page))

    def test_a_single_burn_result_shows_no_transfer_line(self) -> None:
        from tests.unit.test_decision_figure_basis import _render

        assert "row-transfer" not in _render(evaluate_scenario(_with(_steady(50)), sampler=_Recorder()))

    def test_the_trajectory_view_draws_the_first_burn_applied_and_says_the_rest_are_not_drawn(
        self, dropped: ScenarioResult,
    ) -> None:
        link = trajectory_links(dropped)[0][0]
        assert link is not None
        # Burn 1 is dropped, so the view draws burn 2: (prograde, normal, radial) = (2.0, 0.5, -1.0) m/s at 12:15.
        assert (link.dv_prograde, link.dv_normal, link.dv_radial) == (
            pytest.approx(2.0), pytest.approx(0.5), pytest.approx(-1.0))
        assert link.burn_epoch_str == "2026-10-17T12:00:00"
        assert link.coast_hours == pytest.approx(0.25)
        # Burn 1 is dropped, so the row applies 2 of its 3 burns.
        assert link.note == ("Draws burn 2, the first of the 2 burns this row applies; burn 3 is not drawn, since "
                             "this view takes one burn.")


# ── The other wordings, and a burn sized against every burn ──

class TestTheOtherWordings:
    def test_a_later_burn_that_is_not_a_transfer_burn_is_refused(self) -> None:
        with pytest.raises(TypeError, match="TransferBurns"):
            _steady(50).with_transfer(((_BURN_2, 1.0, 0.0, 0.0),))  # type: ignore[arg-type]

    def test_a_burn_after_the_span_searched_is_flown_by_no_figure_and_said(self) -> None:
        late = _transfer(EPOCH, _later(_BURN_2), _later(EPOCH + timedelta(hours=2)))
        result = evaluate_scenario(_with(late), sampler=_Recorder())
        assert str(result.row_transfers[0]).endswith(
            "Every burn is applied, in time order. Burn 3 comes after the span searched ends, at 13:00 UTC on 17 Oct, "
            "so no figure flies it.")
        note = dict(result.outcome_matrix[0][0].figure_bases.items())["closest_approach_km"].note
        assert note.endswith("; red flies the 2 of this row's 3 burns due before the span searched ends, each at its "
                             "own drawn time if that is inside the span")
        assert "in every sample" not in note

    def test_a_burn_due_after_the_span_is_never_handed_to_a_sample(self) -> None:
        # So no sample whose timing draw falls inside the span flies it, and "no figure flies it" holds exactly.
        fake = _Recorder()
        late = _transfer(EPOCH, _later(_BURN_2), _later(EPOCH + timedelta(hours=1)))
        evaluate_scenario(_with(late), sampler=fake)
        assert [h.epoch_utc for h in fake.keywords[0]["red_then"]] == [_BURN_2]

    def test_two_burns_after_the_span_are_named_together(self) -> None:
        late = _transfer(EPOCH, _later(EPOCH + timedelta(hours=2)), _later(EPOCH + timedelta(hours=3)))
        result = evaluate_scenario(_with(late), sampler=_Recorder())
        assert "Burns 2 and 3 come after the span searched ends" in str(result.row_transfers[0])
        assert str(result.row_transfers[0]).endswith("so no figure flies them.")

    def test_the_ledger_says_every_burn_applied_or_none(self) -> None:
        every = evaluate_scenario(_with(_transfer()), sampler=_Recorder())
        assert evaluated_line(every.scenario, every).endswith(" Row A0 (manoeuvre): burns 1, 2 and 3 of 3 applied.")
        carried = _transfer(EPOCH - timedelta(hours=2), _later(EPOCH - timedelta(hours=1)))
        none = evaluate_scenario(_with(carried, _red_at(EPOCH - timedelta(minutes=30))), sampler=_Recorder())
        assert evaluated_line(none.scenario, none).endswith(
            " Row A0 (manoeuvre): none of 2 burns applied, each at or before the red element set's epoch.")

    def test_one_burn_dropped_of_two_reads_in_the_singular(self) -> None:
        carried = _transfer(EPOCH - timedelta(minutes=30), _later(_BURN_2))
        result = evaluate_scenario(_with(carried, _red_at(EPOCH)), sampler=_Recorder())
        assert str(result.row_transfers[0]).endswith(
            "Burn 1 is not applied: it is at or before the red element set's epoch, 12:00 UTC on 17 Oct, which may "
            "already include it. Burn 2 is applied.")
        assert "in time order" not in str(result.row_transfers[0]).rsplit(".", 2)[-2]
        assert evaluated_line(result.scenario, result).endswith(
            " Row A0 (manoeuvre): burn 2 of 2 applied; burn 1 dropped, at or before the red element set's epoch.")

    def test_two_burns_dropped_read_in_the_plural(self) -> None:
        carried = _transfer(EPOCH - timedelta(minutes=40), _later(EPOCH - timedelta(minutes=20)), _later(_BURN_2))
        result = evaluate_scenario(_with(carried, _red_at(EPOCH)), sampler=_Recorder())
        assert "Burns 1 and 2 are not applied: each is at or before" in str(result.row_transfers[0])
        assert evaluated_line(result.scenario, result).endswith("; burns 1 and 2 dropped, at or before the red element "
                                                                "set's epoch.")

    def test_a_row_starting_where_red_cannot_be_propagated_keeps_the_first_burns_state(self) -> None:
        carried = _transfer()
        burns = row_burns(carried.hypothesis, carried.then, EPOCH + timedelta(minutes=1), "not an element set")
        assert burns.first.epoch_utc == _BURN_2
        assert list(burns.first.pre_manoeuvre_state_eci_km) == list(carried.hypothesis.pre_manoeuvre_state_eci_km)


def test_our_burn_sized_against_every_burn_names_them() -> None:
    """One real evaluation: red's three burns flown in every sample and in the nominal our burn is sized against, at 100
    samples, which converge on both seeds (SPC-224)."""
    from spectre.domain.decision import ActionType, FriendlyResponse
    from spectre.domain.decision_figures import ResponseBurnSpec

    scenario = _with(_transfer(n=100))   # converged on both seeds (SPC-224); at 50 seed 43 is not
    response = FriendlyResponse(
        id="F9", name="Open", action_type=ActionType.MANOEUVRE, cost=0.2, reversibility=0.8,
        time_to_execute_hours=0.1, burn=ResponseBurnSpec(target_km=30.0),
    )
    scenario = dataclasses.replace(scenario, adversary_actions=scenario.adversary_actions[:1],
                                   friendly_responses=[response])
    cell = evaluate_scenario(scenario).outcome_matrix[0][0]
    notes = dict(cell.figure_bases.items())
    assert cell.ca_refusal is None, cell.ca_refusal
    assert notes["delta_v_cost_km_s"].kind is Basis.COMPUTED
    assert notes["delta_v_cost_km_s"].note.endswith("; sized against red flying 3 of this row's 3 burns")
    assert "sized on red's nominal transfer (3 of its 3 burns) to put its closest approach at 30 km" in str(
        cell.ca_response_line)


def test_an_after_tca_refusal_names_the_transfer_red_flies(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.astro.response_burn import BurnRefusal
    from spectre.domain.decision import ActionType, FriendlyResponse
    from spectre.domain.decision_figures import ResponseBurnSpec

    monkeypatch.setattr(decision, "hypothesis_response_plan",
                        lambda *_a, **_k: (BurnRefusal("0", "after_tca", 0, 600.0),))
    response = FriendlyResponse(
        id="F9", name="Open", action_type=ActionType.MANOEUVRE, cost=0.2, reversibility=0.8,
        time_to_execute_hours=0.5, burn=ResponseBurnSpec(target_km=30.0),
    )
    scenario = _with(_transfer())
    scenario = dataclasses.replace(scenario, adversary_actions=scenario.adversary_actions[:1],
                                   friendly_responses=[response])
    cell = evaluate_scenario(scenario, sampler=_Recorder()).outcome_matrix[0][0]
    assert "(RK45, red flying its nominal transfer, 3 of its 3 burns)" in str(cell.response_refusal)
    single = dataclasses.replace(scenario, adversary_actions=[
        dataclasses.replace(scenario.adversary_actions[0], hypothesis=_steady(50))])
    assert "(RK45, red with the hypothesis's nominal burn)" in str(
        evaluate_scenario(single, sampler=_Recorder()).outcome_matrix[0][0].response_refusal)


def test_the_burn_line_names_the_burn_the_row_starts_from(dropped: ScenarioResult) -> None:
    from tests.unit.test_decision_figure_basis import _render

    assert dropped.row_starts == (
        "Starts at burn 2, 2026-10-17 12:15 UTC, +0.2 h from the scenario epoch, from the bound red track's state "
        "then: the burn before it is not applied.", None, None, None)
    lines = re.findall(r'<div class="row-burn"[^>]*>(.*?)</div>', _render(dropped), re.S)
    assert html.unescape(" ".join(lines[0].split())) == dropped.row_starts[0]
    every = evaluate_scenario(_with(_transfer()), sampler=_Recorder())
    assert every.row_starts == (None,) * 4


def test_a_transfer_starting_after_the_window_leaves_red_unburnt() -> None:
    carried = _transfer(EPOCH + timedelta(hours=2), _later(EPOCH + timedelta(hours=3), 20.0, 5.0, -3.0))
    later = row_burns(carried.hypothesis, carried.then, None, PLANE_CHANGE.red_tle).then
    one = nominal_red_arc(carried.hypothesis, _window())
    both = nominal_red_arc(carried.hypothesis, _window(), later)
    assert one is not None and both is not None
    assert np.allclose(both(1800.0), one(1800.0), atol=1e-9)
