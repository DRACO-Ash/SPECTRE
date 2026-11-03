"""An adversary action may carry a manoeuvre hypothesis; only a bound row samples from it (SPC-111).

The hypothesis says how the adversary might move: an archetype from the
Monte Carlo table, a delta-V and direction the operator entered, or a
manoeuvre detected in the object's element-set history. It travels with the
direction's basis and the archetype's name, so a reader can always tell how
it was made (audit F-104). It is checked when it is built and recorded in the
result's provenance and in the scenario's recorded value. On its own it
changes no figure: only in a scenario bound on both sides is its row's
closest approach sampled from it (SPC-112). These tests pin each half: the
hypothesis is carried and checked, and the lookup path never reads it.
"""

from __future__ import annotations

import dataclasses
import inspect
import itertools
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

import numpy as np
import pytest

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES, ManoeuvreHypothesis, generate_samples
from spectre.domain import decision
from spectre.domain.decision import (
    HYPOTHESIS_NOTE,
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    FriendlyResponse,
    HypothesisSource,
    PreManoeuvreState,
    Scenario,
    SelectorStrategy,
    compute_outcome_metrics,
    evaluate_scenario,
    find_robust_response,
    plan_sampling,
)
from spectre.domain.provenance import value_input
from tests.unit.test_decision_binding import _binding
from tests.unit.test_pol_status_ladder import _make_record, _manoeuvre

_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
_STATE = (7000.0, 0.0, 0.0, 0.0, 7.546, 0.0)
_AT = PreManoeuvreState(epoch_utc=_NOW, state_eci_km=_STATE)
#: A burn six hours after the scenario's epoch, so a provenance input dated at
#: the scenario cannot pass for one dated at the burn.
_BURN = _NOW + timedelta(hours=6)
_AT_BURN = PreManoeuvreState(epoch_utc=_BURN, state_eci_km=_STATE)
_SIGMAS = (
    "delta_v_magnitude_1sigma_km_s", "delta_v_pointing_1sigma_deg", "epoch_1sigma_seconds", "bstar_1sigma",
)


class _Tripwire:
    """A hypothesis that fails the test the moment anything looks inside it."""

    def __getattr__(self, name: str) -> NoReturn:
        raise AssertionError(f"the lookup path read hypothesis.{name}")

    def __bool__(self) -> NoReturn:
        raise AssertionError("the lookup path tested the hypothesis for truth")

    def __eq__(self, other: object) -> NoReturn:
        raise AssertionError("the lookup path compared the hypothesis")

    __hash__ = None  # type: ignore[assignment]

    def __iter__(self) -> NoReturn:
        raise AssertionError("the lookup path iterated the hypothesis")


def _never(*_: Any) -> NoReturn:
    raise AssertionError("the sampler ran")


def _raw(**overrides: Any) -> ManoeuvreHypothesis:
    """A hypothesis built by hand, to reach the carrier's own checks."""
    fields: dict[str, Any] = {
        "epoch_utc": _NOW, "delta_v_magnitude_km_s": 0.05, "delta_v_radial": 0.0,
        "delta_v_in_track": 0.05, "delta_v_cross_track": 0.0,
        "pre_manoeuvre_state_eci_km": np.array(_STATE), "direction_basis": "entered by the operator",
    }
    return ManoeuvreHypothesis(**{**fields, **overrides})


def _four_by_four(hypotheses: bool | Sequence[bool] = False) -> Scenario:
    """One adversary row and one friendly row per action type: 16 pairings.

    *hypotheses* is one flag for every row, or one per row, so some rows can
    carry a hypothesis while the others do not.
    """
    keys = list(MANOEUVRE_ARCHETYPES)
    mask = [hypotheses] * len(ActionType) if isinstance(hypotheses, bool) else list(hypotheses)
    adversaries = [
        AdversaryAction(
            id=f"A{i}", name=t.value, action_type=t, probability=0.25 + 0.1 * i, confidence=0.7,
            hypothesis=AdversaryHypothesis.from_archetype(keys[i], _AT_BURN) if mask[i] else None,
        )
        for i, t in enumerate(ActionType)
    ]
    friendlies = [
        FriendlyResponse(
            id=f"F{i}", name=t.value, action_type=t, cost=0.2 + 0.1 * i, reversibility=0.8 - 0.1 * i,
            time_to_execute_hours=2.0 + i,
        )
        for i, t in enumerate(ActionType)
    ]
    return Scenario(
        name="Hypothesis or not", epoch_utc=_NOW, adversary_actions=adversaries,
        friendly_responses=friendlies, horizon_hours=48.0,
    )


class TestTheLookupPathNeverReadsTheHypothesis:
    def test_the_lookup_path_never_reads_the_hypothesis(self) -> None:
        scenario = _four_by_four(hypotheses=True)
        for adversary in scenario.adversary_actions:
            adversary.hypothesis = _Tripwire()  # type: ignore[assignment]
        matrix = [
            [compute_outcome_metrics(a, f, scenario) for f in scenario.friendly_responses]
            for a in scenario.adversary_actions
        ]
        assert sum(len(row) for row in matrix) == 16
        chosen = {s: find_robust_response(scenario, matrix, s) for s in SelectorStrategy}
        assert set(chosen) == set(SelectorStrategy)
        assert len(SelectorStrategy) == 3
        assert all(r in scenario.friendly_responses for r in chosen.values())

    def test_the_tripwire_trips(self) -> None:
        with pytest.raises(AssertionError):
            bool(_Tripwire())
        with pytest.raises(AssertionError):
            _ = _Tripwire().hypothesis
        with pytest.raises(AssertionError):
            list(_Tripwire())
        with pytest.raises(AssertionError):
            _ = _Tripwire() == None  # noqa: E711 - the comparison is what must trip

    def test_the_lookup_path_never_reads_the_hypothesis_of_a_bound_scenario(self) -> None:
        """D19's mirror: binding the scenario does not make the lookup path read a hypothesis; sampling does."""
        scenario = _four_by_four(hypotheses=True)
        scenario.binding = _binding()
        for adversary in scenario.adversary_actions:
            adversary.hypothesis = _Tripwire()  # type: ignore[assignment]
        matrix = [
            [compute_outcome_metrics(a, f, scenario) for f in scenario.friendly_responses]
            for a in scenario.adversary_actions
        ]
        assert all(find_robust_response(scenario, matrix, s) in scenario.friendly_responses for s in SelectorStrategy)
        with pytest.raises(AssertionError, match="the lookup path read hypothesis.hypothesis"):
            plan_sampling(scenario, _never)

    def test_a_hypothesis_without_a_binding_changes_no_figure(self) -> None:
        """A regression pin: with and without agree on every figure, mark and choice.

        Every mix of rows with and without a hypothesis is run, not only all or
        none, so a selector that weighted the rows carrying one would show.
        """
        masks = list(itertools.product((False, True), repeat=len(ActionType)))
        assert len(masks) == 16
        for strategy in SelectorStrategy:
            plain = evaluate_scenario(_four_by_four(), strategy)
            for mask in masks:
                carried = evaluate_scenario(_four_by_four(mask), strategy)
                assert carried.outcome_matrix == plain.outcome_matrix, (strategy, mask)
                assert carried.ranked_per_adversary == plain.ranked_per_adversary, (strategy, mask)
                assert carried.robust_best_response.id == plain.robust_best_response.id, (strategy, mask)
                assert carried.basis == plain.basis, (strategy, mask)
                assert carried.basis_lines == plain.basis_lines, (strategy, mask)


class TestEachSourceSaysHowItWasMade:
    def test_an_archetype_carries_its_name_magnitude_and_dispersions(self) -> None:
        carried = AdversaryHypothesis.from_archetype("orbit_raise", _AT)
        h = carried.hypothesis
        assert carried.source is HypothesisSource.ARCHETYPE
        assert carried.archetype_key == "orbit_raise"
        assert carried.archetype == "Orbit Raise" == h.archetype
        assert carried.frame == "RIC"
        assert carried.delta_v_m_s == pytest.approx(50.0)
        assert h.delta_v_magnitude_1sigma_km_s == pytest.approx(0.050 * 0.05)
        assert (h.delta_v_pointing_1sigma_deg, h.epoch_1sigma_seconds) == (2.0, 30.0)
        assert carried.direction_ric == (0.0, 1.0, 0.0)
        assert "assumed in-track" in carried.direction_basis
        assert carried.sentence == (
            "Archetype Orbit Raise: 50.0 m/s; direction (RIC) assumed in-track: an archetype names no "
            "direction; dispersions from the Orbit Raise archetype."
        )

    def test_an_archetype_may_take_an_entered_direction(self) -> None:
        carried = AdversaryHypothesis.from_archetype("plane_change", _AT, direction_ric=(0.0, 0.0, -3.0))
        assert carried.direction_ric == (0.0, 0.0, -1.0)
        assert carried.hypothesis.delta_v_cross_track == pytest.approx(-0.100)
        assert carried.direction_basis == "entered by the operator"

    def test_an_entered_delta_v_keeps_its_direction_and_says_it_has_no_archetype(self) -> None:
        carried = AdversaryHypothesis.from_entered(12.0, (0.0, 3.0, 4.0), _AT, n_samples=7)
        h = carried.hypothesis
        assert h.n_samples == 7
        assert carried.source is HypothesisSource.ENTERED
        assert carried.archetype_key is None and carried.archetype == ""
        assert h.delta_v_magnitude_km_s == pytest.approx(0.012)
        assert carried.direction_ric == pytest.approx((0.0, 0.6, 0.8))
        assert (h.delta_v_in_track, h.delta_v_cross_track) == pytest.approx((0.0072, 0.0096))
        assert carried.sentence == (
            "Entered by the operator: 12.0 m/s; direction (RIC) entered by the operator; "
            "default dispersions, no archetype."
        )

    def test_an_entered_delta_v_may_take_an_archetypes_dispersions(self) -> None:
        carried = AdversaryHypothesis.from_entered(12.0, (1.0, 0.0, 0.0), _AT, archetype="plane_change")
        assert carried.archetype == "Plane Change"
        assert carried.hypothesis.delta_v_pointing_1sigma_deg == 3.0
        # 60 s, not the 30 s ManoeuvreHypothesis would give without the archetype.
        assert carried.hypothesis.epoch_1sigma_seconds == 60.0
        assert carried.hypothesis.delta_v_magnitude_1sigma_km_s == pytest.approx(0.012 * 0.05)
        assert carried.sentence.endswith("dispersions from the Plane Change archetype.")

    def test_a_zero_delta_v_is_accepted_and_keeps_its_direction(self) -> None:
        carried = AdversaryHypothesis.from_entered(0.0, (0.0, 0.0, 1.0), _AT)
        assert carried.delta_v_m_s == 0.0
        assert carried.direction_ric == (0.0, 0.0, 1.0)

    def test_a_detected_manoeuvre_keeps_the_detections_basis(self) -> None:
        mnv = _manoeuvre(0.013)
        carried = AdversaryHypothesis.from_detection(_make_record(), mnv, archetype="plane_change", n_samples=10)
        assert carried.source is HypothesisSource.DETECTED
        assert carried.archetype == "Plane Change"
        assert carried.hypothesis.n_samples == 10
        assert carried.hypothesis.epoch_utc == mnv.burn_epoch
        assert carried.direction_basis == "assumed in-track: no element breakdown"
        assert carried.sentence.startswith("Detected manoeuvre: 13.0 m/s; direction (RIC) assumed in-track")

    @pytest.mark.parametrize("dv_km_s", [0.0, 1e-16])
    def test_a_detection_of_no_or_almost_no_delta_v_keeps_its_direction(self, dv_km_s: float) -> None:
        carried = AdversaryHypothesis.from_detection(_make_record(), _manoeuvre(dv_km_s), archetype="phasing")
        assert carried.delta_v_m_s == pytest.approx(dv_km_s * 1000.0)
        assert carried.direction_ric == (0.0, 1.0, 0.0)
        assert carried.direction_basis == "assumed in-track: no element breakdown"

    def test_a_detection_with_an_unknown_archetype_is_refused_not_read_as_an_orbit_raise(self) -> None:
        with pytest.raises(ValueError, match="'loiter' is not a known manoeuvre archetype"):
            AdversaryHypothesis.from_detection(_make_record(), _manoeuvre(0.013), archetype="loiter")

    def test_the_carrier_says_what_it_changes_once_bound(self) -> None:
        """Inverted by SPC-123: with a red track bound, the burn time sets when custody is lost."""
        assert "changes no figure yet" not in HYPOTHESIS_NOTE
        assert "changes no figure unless both sides are bound" not in HYPOTHESIS_NOTE
        assert "and the row's other figures are still lookups" not in HYPOTHESIS_NOTE
        assert "With a red track bound, its burn time sets when custody is lost" in HYPOTHESIS_NOTE
        assert "closest approach of its row and its time are sampled from it" in HYPOTHESIS_NOTE
        assert "without one, a manoeuvre row's closest approach stays a lookup" in HYPOTHESIS_NOTE
        assert "its custody takes the worst case, a burn at the scenario epoch" in HYPOTHESIS_NOTE
        assert AdversaryHypothesis.from_archetype("phasing", _AT).note is HYPOTHESIS_NOTE


class TestTheHypothesisIsCheckedWhenBuilt:
    @pytest.mark.parametrize("dv", [math.nan, math.inf, -0.5])
    def test_an_entered_delta_v_must_be_finite_and_not_negative(self, dv: float) -> None:
        with pytest.raises(ValueError, match="delta-V must be finite and not negative"):
            AdversaryHypothesis.from_entered(dv, (0.0, 1.0, 0.0), _AT)

    @pytest.mark.parametrize("dv", [math.nan, -0.001])
    def test_a_hand_built_delta_v_is_checked_too(self, dv: float) -> None:
        with pytest.raises(ValueError, match="delta-V must be finite and not negative"):
            AdversaryHypothesis(_raw(delta_v_magnitude_km_s=dv), HypothesisSource.ENTERED)

    @pytest.mark.parametrize("direction", [(0.0, 0.0, 0.0), (0.0, math.nan, 1.0), (1.0, 0.0), (0.0, math.inf, 0.0)])
    def test_a_direction_must_be_normalisable(self, direction: tuple[float, ...]) -> None:
        with pytest.raises(ValueError, match="direction"):
            AdversaryHypothesis.from_entered(5.0, direction, _AT)

    @pytest.mark.parametrize(
        ("direction", "unit"),
        [((1e-200, 0.0, 0.0), (1.0, 0.0, 0.0)), ((1e200, 1e200, 0.0), (math.sqrt(0.5), math.sqrt(0.5), 0.0))],
    )
    def test_a_very_small_or_very_large_direction_is_normalised_not_refused(
        self, direction: tuple[float, float, float], unit: tuple[float, float, float],
    ) -> None:
        carried = AdversaryHypothesis.from_entered(5.0, direction, _AT)
        assert carried.direction_ric == pytest.approx(unit)

    def test_a_hand_built_direction_too_small_for_the_sampler_is_stored_where_it_can_read_it(self) -> None:
        carried = AdversaryHypothesis(_raw(delta_v_in_track=0.0, delta_v_cross_track=-1e-200), HypothesisSource.ENTERED)
        h = carried.hypothesis
        assert carried.direction_ric == (0.0, 0.0, -1.0)
        assert float(np.linalg.norm([h.delta_v_radial, h.delta_v_in_track, h.delta_v_cross_track])) >= 1e-15
        # The sampler points every burn cross-track, not in-track as it would for a direction it cannot read.
        samples = generate_samples(dataclasses.replace(h, n_samples=20, delta_v_pointing_1sigma_deg=0.0))
        assert np.all(samples[:, 2] < 0.0)
        assert np.allclose(samples[:, 1], 0.0)

    @pytest.mark.parametrize("field", _SIGMAS)
    @pytest.mark.parametrize("value", [math.nan, math.inf, -1.0])
    def test_every_dispersion_is_finite_and_not_negative(self, field: str, value: float) -> None:
        with pytest.raises(ValueError, match="must be finite and not negative"):
            AdversaryHypothesis(_raw(**{field: value}), HypothesisSource.ENTERED)

    def test_a_dispersion_of_zero_is_accepted(self) -> None:
        carried = AdversaryHypothesis(_raw(**dict.fromkeys(_SIGMAS, 0.0)), HypothesisSource.ENTERED)
        assert all(getattr(carried.hypothesis, f) == 0.0 for f in _SIGMAS)

    def test_a_hand_built_direction_of_zero_is_refused_not_assumed_in_track(self) -> None:
        with pytest.raises(ValueError, match="no direction is assumed in its place"):
            AdversaryHypothesis(_raw(delta_v_in_track=0.0), HypothesisSource.ENTERED)

    def test_an_unknown_archetype_is_refused(self) -> None:
        with pytest.raises(ValueError, match="'loiter' is not a known manoeuvre archetype; choose one of"):
            AdversaryHypothesis.from_archetype("loiter", _AT)
        with pytest.raises(ValueError, match="'loiter' is not a known manoeuvre archetype"):
            AdversaryHypothesis(_raw(archetype="Loiter"), HypothesisSource.ARCHETYPE, archetype_key="loiter")

    def test_the_archetype_name_matches_its_key(self) -> None:
        with pytest.raises(ValueError, match="names Plane Change, not Orbit Raise"):
            AdversaryHypothesis(_raw(archetype="Orbit Raise"), HypothesisSource.ARCHETYPE, archetype_key="plane_change")

    @pytest.mark.parametrize("source", [HypothesisSource.ARCHETYPE, HypothesisSource.DETECTED])
    def test_an_archetype_or_detection_names_its_archetype(self, source: HypothesisSource) -> None:
        with pytest.raises(ValueError, match="names its archetype"):
            AdversaryHypothesis(_raw(), source)

    def test_no_archetype_means_no_archetype_name(self) -> None:
        with pytest.raises(ValueError, match="names no archetype"):
            AdversaryHypothesis(_raw(archetype="Orbit Raise"), HypothesisSource.ENTERED)

    def test_the_direction_basis_and_frame_are_stated(self) -> None:
        with pytest.raises(ValueError, match="direction basis"):
            AdversaryHypothesis(_raw(direction_basis=""), HypothesisSource.ENTERED)
        with pytest.raises(ValueError, match="frame"):
            AdversaryHypothesis(_raw(), HypothesisSource.ENTERED, frame="ECI")

    def test_the_source_is_a_known_source(self) -> None:
        with pytest.raises(ValueError, match="source"):
            AdversaryHypothesis(_raw(), "guess")  # type: ignore[arg-type]

    @pytest.mark.parametrize("state", [(7000.0, 0.0, 0.0), (7000.0, 0.0, 0.0, 0.0, math.nan, 0.0)])
    def test_the_pre_manoeuvre_state_is_six_finite_numbers(self, state: tuple[float, ...]) -> None:
        with pytest.raises(ValueError, match="pre-manoeuvre state"):
            AdversaryHypothesis.from_entered(5.0, (0.0, 1.0, 0.0), PreManoeuvreState(_NOW, state))

    def test_the_sample_count_is_positive(self) -> None:
        with pytest.raises(ValueError, match="sample count"):
            AdversaryHypothesis.from_archetype("evasive", _AT, n_samples=0)

    def test_the_carrier_is_a_hypothesis_carrier(self) -> None:
        with pytest.raises(TypeError, match="ManoeuvreHypothesis"):
            AdversaryHypothesis("not a hypothesis", HypothesisSource.ENTERED)  # type: ignore[arg-type]

    def test_an_action_takes_the_carrier_not_a_bare_hypothesis(self) -> None:
        with pytest.raises(TypeError, match="AdversaryHypothesis"):
            AdversaryAction("A", "a", ActionType.MANOEUVRE, 0.5, 0.5, hypothesis=_raw())  # type: ignore[arg-type]

    def test_later_changes_to_the_callers_hypothesis_do_not_reach_the_carrier(self) -> None:
        raw = _raw()
        carried = AdversaryHypothesis(raw, HypothesisSource.ENTERED)
        raw.delta_v_magnitude_km_s = math.nan
        raw.pre_manoeuvre_state_eci_km[0] = math.nan
        assert carried.delta_v_m_s == pytest.approx(50.0)
        assert carried.hypothesis.pre_manoeuvre_state_eci_km[0] == 7000.0
        with pytest.raises(ValueError, match="read-only"):
            carried.hypothesis.pre_manoeuvre_state_eci_km[0] = 1.0

    @pytest.mark.parametrize(
        ("field", "value"),
        [("delta_v_magnitude_km_s", -1.0), ("delta_v_in_track", 0.0), ("archetype", "Orbit Raise"),
         ("direction_basis", ""), ("delta_v_pointing_1sigma_deg", math.nan), ("n_samples", 0)],
    )
    def test_no_field_of_the_carried_hypothesis_can_be_written(self, field: str, value: object) -> None:
        carried = AdversaryHypothesis.from_archetype("orbit_raise", _AT)
        before = (hash(carried), carried.sentence, carried.direction_ric)
        with pytest.raises(dataclasses.FrozenInstanceError, match=field):
            setattr(carried.hypothesis, field, value)
        with pytest.raises(dataclasses.FrozenInstanceError, match=field):
            delattr(carried.hypothesis, field)
        assert (hash(carried), carried.sentence, carried.direction_ric) == before

    def test_the_carried_state_cannot_be_made_writeable_again(self) -> None:
        state = AdversaryHypothesis.from_archetype("orbit_raise", _AT).hypothesis.pre_manoeuvre_state_eci_km
        with pytest.raises(ValueError, match="WRITEABLE"):
            state.flags.writeable = True

    def test_the_carried_hypothesis_is_still_a_manoeuvre_hypothesis_and_can_be_replaced(self) -> None:
        h = AdversaryHypothesis.from_archetype("orbit_raise", _AT).hypothesis
        assert isinstance(h, ManoeuvreHypothesis)
        reseeded = dataclasses.replace(h, random_seed=7)
        assert (reseeded.random_seed, reseeded.archetype) == (7, "Orbit Raise")


class TestTheHypothesisIsRecorded:
    def test_the_result_provenance_names_each_hypothesis(self) -> None:
        scenario = _four_by_four(hypotheses=True)
        p = evaluate_scenario(scenario).provenance
        assert p is not None
        assert [i.label for i in p.inputs] == ["scenario", *(f"hypothesis A{i} (archetype)" for i in range(4))]
        for ref, action in zip(p.inputs[1:], scenario.adversary_actions, strict=True):
            assert action.hypothesis is not None
            assert ref.sha256 == value_input(ref.label, action.hypothesis.recorded()).sha256
            # Dated at the burn, not at the scenario's epoch six hours earlier.
            assert ref.epoch == _BURN != scenario.epoch_utc

    def test_an_action_without_a_hypothesis_adds_no_input(self) -> None:
        p = evaluate_scenario(_four_by_four()).provenance
        assert p is not None
        assert [i.label for i in p.inputs] == ["scenario"]

    def test_the_recorded_value_names_the_source_basis_and_archetype(self) -> None:
        recorded = AdversaryHypothesis.from_archetype("orbit_raise", _AT).recorded()
        assert recorded["source"] == "archetype"
        assert recorded["archetype_key"] == "orbit_raise"
        assert recorded["frame"] == "RIC"
        inner = recorded["hypothesis"]
        assert isinstance(inner, dict)
        assert inner["archetype"] == "Orbit Raise"
        assert "assumed in-track" in inner["direction_basis"]
        assert inner["pre_manoeuvre_state_eci_km"] == list(_STATE)

    def test_the_recorded_value_keeps_every_figure_at_full_precision(self) -> None:
        nudged = PreManoeuvreState(_NOW, (7000.0 + 1e-9, *_STATE[1:]))
        dv_m_s = 12.345678901234
        carried = AdversaryHypothesis.from_entered(dv_m_s, (0.0, 1.0, 0.0), nudged)
        inner = carried.recorded()["hypothesis"]
        assert isinstance(inner, dict)
        assert inner["pre_manoeuvre_state_eci_km"][0] == 7000.0 + 1e-9 != 7000.0
        assert inner["delta_v_magnitude_km_s"] == carried.hypothesis.delta_v_magnitude_km_s

    def test_the_result_provenance_tells_two_hypotheses_apart(self) -> None:
        def hypothesis_hash(at: PreManoeuvreState) -> str:
            sc = _four_by_four((True, False, False, False))
            sc.adversary_actions[0].hypothesis = AdversaryHypothesis.from_archetype("orbit_raise", at)
            p = evaluate_scenario(sc).provenance
            assert p is not None
            assert p.inputs[1].label == "hypothesis A0 (archetype)"
            return p.inputs[1].sha256

        nudged = PreManoeuvreState(_BURN, (7000.0 + 1e-9, *_STATE[1:]))
        assert hypothesis_hash(_AT_BURN) != hypothesis_hash(nudged)

    def test_the_scenarios_recorded_value_tells_two_hypotheses_apart(self) -> None:
        def scenario_hash(hypothesis: AdversaryHypothesis | None) -> str:
            sc = _four_by_four()
            sc.adversary_actions[0] = dataclasses.replace(sc.adversary_actions[0], hypothesis=hypothesis)
            return value_input("scenario", sc).sha256

        nudged = PreManoeuvreState(_NOW, (7000.0 + 1e-9, *_STATE[1:]))
        hashes = {
            scenario_hash(None),
            scenario_hash(AdversaryHypothesis.from_archetype("orbit_raise", _AT)),
            scenario_hash(AdversaryHypothesis.from_archetype("orbit_raise", nudged)),
        }
        assert len(hashes) == 3

    def test_actions_carrying_equal_hypotheses_compare_equal(self) -> None:
        def action() -> AdversaryAction:
            return AdversaryAction(
                "A", "a", ActionType.MANOEUVRE, 0.5, 0.5, hypothesis=AdversaryHypothesis.from_archetype("phasing", _AT),
            )

        assert action() == action()
        assert hash(action().hypothesis) == hash(action().hypothesis)
        assert action().hypothesis != AdversaryHypothesis.from_archetype("evasive", _AT)
        assert action().hypothesis != "phasing"


class TestTheModelIsDescribed:
    def test_the_module_describes_the_hypothesis_as_sampled_only_when_bound(self) -> None:
        module = " ".join((decision.__doc__ or "").split())
        assert "future sprint" not in module
        assert "manoeuvre hypothesis" in module
        after = module.split("manoeuvre hypothesis", 1)[1]
        assert "on its own changes no figure" in after
        assert "until a later phase samples from it" not in after
        assert "closest approach is sampled" in after

    def test_the_domain_does_not_import_the_web_layer(self) -> None:
        assert "spectre.web" not in inspect.getsource(decision)
