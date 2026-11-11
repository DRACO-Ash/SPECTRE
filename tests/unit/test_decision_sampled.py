"""A bound row whose action carries a hypothesis scores on its sampled closest approach (SPC-112).

Only a row whose adversary action carries a manoeuvre hypothesis (SPC-111),
in a scenario bound to a red track and a blue asset (SPC-100), is sampled.
Its closest approach is the P5 of the separation series' misses (SPC-110),
its time to closest approach the earliest TCA at or below P5, and both say
they are sampled; every other figure, and every other row, is a lookup
exactly as before, except that a bound row whose action does not move red
has its closest approach computed by SGP4 (SPC-120,
tests/unit/test_decision_computed.py). A row that cannot be sampled honestly
is refused with a sentence in each of its cells and keeps its lookups. The cost is capped
before anything runs, at what one evaluation can run within its 300 s budget
(SPC-113; raised from 120 s by the owner's ruling of 2026-11-05, SPC-178).

D1 to D17 inject a fake sampler, so they run in milliseconds and test the
domain's rules, not the propagator; D18 runs the real series once.
"""

from __future__ import annotations

import dataclasses
import html
import math
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, NamedTuple, NoReturn

import numpy as np
import pytest

from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.monte_carlo import (
    BlueTrack,
    ManoeuvreHypothesis,
    SeparationSeries,
    SeparationWindow,
    elset_state,
    percentile_half_width_km,
    run_separation_series,
)
from spectre.domain import decision
from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    LOOKUP_BASES,
    MAX_SAMPLE_HOURS,
    SET_UP_S_PER_SAMPLE,
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    HypothesisSource,
    OutcomeMetrics,
    PreManoeuvreState,
    RowSampling,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    evaluate_scenario,
    outcome_bases,
    plan_sampling,
)
from spectre.domain.provenance import Basis, FigureBasis
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit.test_decision_figure_basis import _render, _text

#: Inverted by SPC-123: custody may be computed in a refused cell, so the suffix speaks for the closest approach.
_LOOKUPS = " This cell's closest approach is a lookup."
_RED_AT_EPOCH = elset_state(PLANE_CHANGE.red_tle, EPOCH)
assert _RED_AT_EPOCH is not None


# ── Fixtures: the plane-change element sets, bound, and a hypothesis from red's state ──

def _elset(
    side: str, *, age: float | None = 0.0, limit: float | None = 24.0, epoch: datetime = EPOCH,
) -> BoundElset:
    tle = PLANE_CHANGE.red_tle if side == "red" else PLANE_CHANGE.blue_tle
    return BoundElset(
        side=side,  # type: ignore[arg-type]
        name=f"{side.upper()}_PC", stk_name=f"{side.upper()}_PC", satno=90002 if side == "red" else 90001,
        tle=tle, data_mode="REAL",
        epoch=None if age is None else epoch, age_hours=age, limit_hours=None if age is None else limit,
    )


def _binding(
    red_age: float | None = 0.0, blue_age: float | None = 0.0, *, red: bool = True, blue: bool = True,
) -> ScenarioBinding:
    """Both element sets current unless an age past the 24 h limit, or None for unknown, is given."""
    return ScenarioBinding(
        red=_elset("red", age=red_age) if red else None,
        blue=_elset("blue", age=blue_age) if blue else None,
    )


def _evasive(n_samples: int = 50, *, offset_km: float = 0.0, dv_offset_km_s: float = 0.0) -> AdversaryHypothesis:
    """The Evasive archetype burning at EPOCH from red's state there, moved *offset_km* and *dv_offset_km_s* along x."""
    state = _RED_AT_EPOCH.state_eci_km.copy()
    state[0] += offset_km
    state[3] += dv_offset_km_s
    return AdversaryHypothesis.from_archetype("evasive", PreManoeuvreState(EPOCH, tuple(state)), n_samples=n_samples)


def _red_at(at: datetime) -> BlueTrack:
    red = elset_state(PLANE_CHANGE.red_tle, at)
    assert red is not None
    return red


def _steady(n_samples: int, *, at: datetime = EPOCH) -> AdversaryHypothesis:
    """A 1 m/s in-track burn at *at* with no timing spread: in the window, it integrates (n + 2) x horizon."""
    h = ManoeuvreHypothesis(
        epoch_utc=at, delta_v_magnitude_km_s=0.001,
        delta_v_radial=0.0, delta_v_in_track=0.001, delta_v_cross_track=0.0,
        pre_manoeuvre_state_eci_km=_red_at(at).state_eci_km.copy(),
        epoch_1sigma_seconds=0.0, n_samples=n_samples, direction_basis="entered by the operator",
    )
    return AdversaryHypothesis(h, HypothesisSource.ENTERED)


def _scenario(
    hypotheses: dict[int, AdversaryHypothesis] | None = None, *, binding: ScenarioBinding | None = None,
    horizon_hours: float = 1.0,
) -> Scenario:
    """One adversary row and one friendly row per action type: 16 cells; *hypotheses* by row."""
    carried = hypotheses or {}
    adversaries = [
        AdversaryAction(
            id=f"A{i}", name=t.value, action_type=t, probability=(5 + 2 * i) / 32, confidence=0.7,
            hypothesis=carried.get(i),
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
        name="What if", epoch_utc=EPOCH, adversary_actions=adversaries, friendly_responses=friendlies,
        horizon_hours=horizon_hours, binding=binding,
    )


def _bound(hypotheses: dict[int, AdversaryHypothesis] | None = None, **kwargs: Any) -> Scenario:
    return _scenario({0: _evasive()} if hypotheses is None else hypotheses, binding=_binding(), **kwargs)


# ── A fake sampler: P5 3 km, P50 8 km, P95 20 km over 50 samples ──

#: Three samples at or below P5, the earliest of them 1,200 s into the window; one above P5 is earlier still.
_LOW = ((2.0, 1800.0), (2.5, 1200.0), (3.0, 2400.0))
_REST = tuple((8.0 + 17.0 * k / 46.0, 600.0 if k == 0 else 3000.0) for k in range(47))


class _Edges(NamedTuple):
    """How many samples are closest at a window edge: the last *end* at its end, the first *start* above P5 at its start."""

    end:   int = 0
    start: int = 0


def _approach(k: int, pair: tuple[float, float], n: int, span_s: float, edges: _Edges) -> ClosestApproach:
    """Sample *k* of *n*, its miss and TCA from *pair* unless *edges* puts it at a window edge."""
    miss, tca = pair
    if k >= n - edges.end:
        return ClosestApproach(miss, span_s, True)
    if len(_LOW) <= k < len(_LOW) + edges.start:
        return ClosestApproach(miss, 0.0, True)
    return ClosestApproach(miss, tca, False)


def _series(
    window: SeparationWindow, *, n_failed: int = 0, half_width: float = 0.4, converged: bool = True,
    edges: _Edges = _Edges(),
) -> SeparationSeries:
    pairs = (*_LOW, *_REST)[: 50 - n_failed]
    approaches = tuple(_approach(k, pair, len(pairs), window.span_s, edges) for k, pair in enumerate(pairs))
    return SeparationSeries(
        window=window, approaches=approaches, n_samples_run=50, n_failed=n_failed, n_reentered=0,
        miss_km_p5=3.0, miss_km_p50=8.0, miss_km_p95=20.0, miss_km_std=5.0,
        percentile_half_width_km=half_width, converged=converged, random_seed=42,
        integration_s=0.0, wall_time_seconds=0.0,
    )


class _Fake:
    """A sampler that records each call and returns the fake series over the window it is given."""

    def __init__(self, **series: Any) -> None:
        self.calls: list[tuple[ManoeuvreHypothesis, BlueTrack, SeparationWindow]] = []
        self.series = series

    def __call__(self, hypothesis: ManoeuvreHypothesis, blue: BlueTrack, window: SeparationWindow) -> SeparationSeries:
        self.calls.append((hypothesis, blue, window))
        series = dict(self.series)
        reentered = series.pop("n_reentered", 0)
        return dataclasses.replace(_series(window, **series), n_reentered=reentered)


def _never(*_: Any) -> NoReturn:
    raise AssertionError("the sampler ran")


def _lookup(scenario: Scenario) -> ScenarioResult:
    """The same scenario evaluated with no hypothesis and no binding: every cell a lookup.

    Unbound, since a bound row without a hypothesis is now computed or refused (SPC-120).
    """
    plain = dataclasses.replace(
        scenario, adversary_actions=[dataclasses.replace(a, hypothesis=None) for a in scenario.adversary_actions],
        binding=None,
    )
    return evaluate_scenario(plain)


def _cells(result: ScenarioResult, row: int) -> list[OutcomeMetrics]:
    return result.outcome_matrix[row]


# ── D1 to D7: which cells are sampled, and what a sampled cell holds ──

class TestOnlyABoundRowWithAHypothesisIsSampled:
    def test_only_the_bound_row_with_a_hypothesis_is_sampled(self) -> None:
        """D1: one sample run for the row, shared by its four cells; every other row is computed (SPC-120).

        Before SPC-120 every other row was today's lookup; the three rows whose action does not move red now
        share the pair's computed closest approach, and RK45 runs for the sampled row alone.
        """
        fake = _Fake()
        scenario = _bound()
        result = evaluate_scenario(scenario, sampler=fake)
        assert len(fake.calls) == 1
        hypothesis, blue, window = fake.calls[0]
        assert hypothesis is scenario.adversary_actions[0].hypothesis.hypothesis  # type: ignore[union-attr]
        assert window == SeparationWindow(start_utc=EPOCH, span_s=3600.0)
        assert blue.epoch_utc == EPOCH
        assert np.array_equal(blue.state_eci_km, elset_state(PLANE_CHANGE.blue_tle, EPOCH).state_eci_km)  # type: ignore[union-attr]
        for cell in _cells(result, 0):
            assert cell.figure_bases.closest_approach_km.kind is Basis.SAMPLED
            assert cell.figure_bases.time_to_closest_hours.kind is Basis.SAMPLED
        for row in (1, 2, 3):
            assert all(cell.figure_bases.closest_approach_km.kind is Basis.COMPUTED for cell in _cells(result, row))
            assert all(cell.ca_percentiles is None for cell in _cells(result, row))

    @pytest.mark.parametrize(
        "binding",
        [_binding(blue=False), _binding(red=False), None],
        ids=["red only", "blue only", "unbound"],
    )
    def test_a_partly_bound_or_unbound_row_stays_a_lookup_and_says_why(self, binding: ScenarioBinding | None) -> None:
        """D2."""
        fake = _Fake()
        scenario = _scenario({0: _evasive()}, binding=binding)
        result = evaluate_scenario(scenario, sampler=fake)
        assert fake.calls == []
        assert result.outcome_matrix == _lookup(scenario).outcome_matrix
        assert result.row_notes == (
            "Hypothesis carried, not sampled: bind a red track and a blue asset to sample its closest approach.",
            None, None, None,
        )

    def test_a_scenario_without_a_hypothesis_has_no_row_note(self) -> None:
        result = evaluate_scenario(_scenario(binding=_binding()), sampler=_never)
        assert result.row_notes == (None, None, None, None)


@pytest.fixture(scope="module")
def sampled() -> ScenarioResult:
    return evaluate_scenario(_bound(), sampler=_Fake())


class TestASampledCell:
    def test_the_score_is_on_p5(self) -> None:
        """D3: the score moves by the weight times the change in the closest-approach term (SPC-191).

        At the default 10 km keep-out, P5 (3 km) and P50 (8 km) both score the full penalty, so this tells them apart
        at a 1 km keep-out, where the term is ln(50,000 / miss) / ln 50,000: 0.898463 at 3 km, 0.807811 at 8 km and
        0.723124 at 20 km.
        """
        scenario = dataclasses.replace(_bound(), keep_out_km=1.0)
        sampled = evaluate_scenario(scenario, sampler=_Fake())
        lookup = _lookup(scenario)
        w = scenario.w_closest_approach

        def term(miss_km: float) -> float:
            return math.log(50_000.0 / miss_km) / math.log(50_000.0)

        assert [round(term(p), 6) for p in (3.0, 8.0, 20.0)] == [0.898463, 0.807811, 0.723124]
        for cell, plain in zip(_cells(sampled, 0), _cells(lookup, 0), strict=True):
            on = {p: plain.composite_score + w * (term(p) - term(plain.closest_approach_km)) for p in (3.0, 8.0, 20.0)}
            assert cell.composite_score == pytest.approx(on[3.0], abs=2e-6)
            assert cell.composite_score != pytest.approx(on[20.0], abs=2e-6)
            assert cell.composite_score != pytest.approx(on[8.0], abs=2e-6)

    def test_the_band_and_spread_are_carried(self, sampled: ScenarioResult) -> None:
        """D4."""
        for cell in _cells(sampled, 0):
            assert cell.closest_approach_km == 3.0
            assert cell.ca_percentiles == {5: 3.0, 50: 8.0, 95: 20.0}
            assert cell.ca_std_km == 5.0
            assert cell.ca_samples == 50
            assert cell.ca_band == (
                "Sampled: P5 3.0 km to P95 20.0 km, median 8.0 km, each known to within 0.4 km, 50 samples."
            )
            assert cell.ca_refusal is None
            assert cell.ca_caveat == "1 in 20 samples came closer than P5; the closest of 50 was 2.0 km."

    def test_the_sampled_note_names_samples_horizon_and_propagator(self, sampled: ScenarioResult) -> None:
        """D5."""
        bases = _cells(sampled, 0)[0].figure_bases
        assert bases.closest_approach_km == FigureBasis(
            Basis.SAMPLED,
            "P5 of 50 sampled misses, known to within 0.40 km (95 % bootstrap): 1 in 20 samples came closer. "
            "Each sample is the hypothesis's burn drawn from its delta-V, pointing, timing and drag spreads, "
            "propagated with the blue asset over 1.0 h of the 1 h horizon from the scenario epoch, while both element "
            "sets are within their limits, by RK45 with J2 and exponential drag; the element sets' own errors are not "
            "sampled, and our response is not applied to the blue orbit",
        )
        assert bases.time_to_closest_hours == FigureBasis(
            Basis.SAMPLED,
            "earliest time of closest approach among the samples at or below P5, of 50 samples over 1.0 h of the 1 h "
            "horizon from the scenario epoch; RK45 with J2 and exponential drag",
        )
        for name in ("custody_maintained", "custody_gap_hours"):
            assert getattr(bases, name) == getattr(LOOKUP_BASES, name), name
        # A manoeuvre response with no target separation keeps the lookup and says how to size it (SPC-121).
        assert bases.delta_v_cost_km_s == FigureBasis(
            Basis.LOOKUP, f"{LOOKUP_BASES.delta_v_cost_km_s.note}. Enter a target separation to size this burn.",
        )
        # A response that does not burn spends 0 m/s against the no-burn blue orbit, not the lookup's rule (SPC-125).
        still = _cells(sampled, 0)[1].figure_bases.delta_v_cost_km_s
        assert still.kind is Basis.COMPUTED and still.note.startswith("this response does not burn")

    def test_the_score_basis_stays_lookup(self, sampled: ScenarioResult) -> None:
        """D6."""
        for cell in _cells(sampled, 0):
            assert cell.figure_bases.composite_score.kind is Basis.LOOKUP
            assert cell.modelled is True

    def test_the_time_is_the_earliest_tca_at_or_below_p5(self, sampled: ScenarioResult) -> None:
        """D7: 1,200 s is 0.33 h, though a sample above P5 came at 600 s; the lookup says 0.4 of the 1 h horizon."""
        for cell, plain in zip(_cells(sampled, 0), _cells(_lookup(sampled.scenario), 0), strict=True):
            assert cell.time_to_closest_hours == 0.33
            assert plain.time_to_closest_hours == 0.4

    def test_lookup_figures_of_a_sampled_cell_are_unchanged(self, sampled: ScenarioResult) -> None:
        for cell, plain in zip(_cells(sampled, 0), _cells(_lookup(sampled.scenario), 0), strict=True):
            assert (cell.custody_maintained, cell.custody_gap_hours, cell.delta_v_cost_km_s) == (
                plain.custody_maintained, plain.custody_gap_hours, plain.delta_v_cost_km_s,
            )

    def test_samples_still_closing_at_the_window_end_are_named(self) -> None:
        result = evaluate_scenario(_bound(), sampler=_Fake(edges=_Edges(end=2)))
        assert _cells(result, 0)[0].ca_caveat == (
            "1 in 20 samples came closer than P5; the closest of 50 was 2.0 km. In 2 of 50 samples the objects "
            "were still closing when the window ended, so the closest approach may come after it."
        )

    def test_samples_closest_at_the_window_start_are_not_called_closing(self) -> None:
        """Their nearest point is the window's first instant: they were opening, not still closing at its end.

        SPC-117 names them too, since a burn already made, now sampled, is often closest at the window start.
        """
        result = evaluate_scenario(_bound(), sampler=_Fake(edges=_Edges(start=2)))
        assert _cells(result, 0)[0].ca_caveat == (
            "1 in 20 samples came closer than P5; the closest of 50 was 2.0 km. In 2 of 50 samples the objects "
            "were already opening when the window began, so the closest approach was before it."
        )


# ── D8: the invariants ──

def _sampled_bases() -> Any:
    return outcome_bases(**{
        name: FigureBasis(Basis.SAMPLED if name == "closest_approach_km" else Basis.LOOKUP, "n")
        for name in ("custody_maintained", "custody_gap_hours", "closest_approach_km", "time_to_closest_hours",
                     "delta_v_cost_km_s")
    })


def _metrics(**changes: Any) -> OutcomeMetrics:
    values: dict[str, Any] = {
        "custody_maintained": True, "custody_gap_hours": 0.0, "closest_approach_km": 3.0,
        "time_to_closest_hours": 0.33, "delta_v_cost_km_s": 0.0, "composite_score": 0.2,
        "figure_bases": _sampled_bases(), "ca_percentiles": {5: 3.0, 50: 8.0, 95: 20.0}, "ca_std_km": 5.0,
        "ca_samples": 50, "ca_half_width_km": 0.4, "score_percentiles": {5: 0.19, 50: 0.2, 95: 0.2},
        "score_std": 0.00003,
    }
    return OutcomeMetrics(**{**values, **changes})


class TestTheInvariantsHold:
    def test_a_well_formed_sampled_cell_is_accepted(self) -> None:
        assert _metrics().ca_percentiles == {5: 3.0, 50: 8.0, 95: 20.0}

    @pytest.mark.parametrize(
        ("changes", "match"),
        [
            ({"figure_bases": LOOKUP_BASES}, "sampled"),
            (
                {"ca_percentiles": None, "ca_std_km": None, "ca_samples": None, "ca_half_width_km": None,
                 "score_percentiles": None, "score_std": None},
                "sampled",
            ),
            ({"ca_std_km": None}, "sampled"),
            ({"ca_samples": None}, "sampled"),
            ({"closest_approach_km": 8.0}, "P5"),
            ({"closest_approach_km": 3.04, "ca_percentiles": {5: 3.04, 50: 8.0, 95: 20.0}}, "P5"),
            ({"ca_percentiles": {5: 3.0, 50: 8.0}}, "5, 50 and 95"),
            ({"ca_percentiles": {5: 3.0, 50: 2.0, 95: 20.0}}, "P5 <= P50 <= P95"),
            ({"ca_percentiles": {5: 3.0, 50: 8.0, 95: math.nan}}, "finite"),
            ({"ca_percentiles": {5: -1.0, 50: 8.0, 95: 20.0}, "closest_approach_km": -1.0}, "must not be negative"),
            ({"ca_std_km": math.inf}, "finite"),
            ({"ca_refusal": "Not sampled: no."}, "refused"),
            (
                {"figure_bases": LOOKUP_BASES, "ca_percentiles": None, "ca_std_km": None, "ca_samples": None,
                 "ca_half_width_km": None, "score_percentiles": None, "score_std": None, "ca_caveat": "c"},
                "caveat",
            ),
        ],
        ids=[
            "band with lookup basis", "sampled basis without band", "band without std", "band without count",
            "closest approach not P5",
            "closest approach P5 unrounded", "missing key", "out of order", "NaN", "negative", "infinite std",
            "refused and sampled", "caveat without band",
        ],
    )
    def test_a_cell_that_breaks_an_invariant_is_refused(self, changes: dict[str, Any], match: str) -> None:
        """D8."""
        with pytest.raises(ValueError, match=match):
            _metrics(**changes)

    def test_a_refused_lookup_cell_is_accepted(self) -> None:
        cell = _metrics(
            figure_bases=LOOKUP_BASES, ca_percentiles=None, ca_std_km=None, ca_samples=None, ca_refusal="Not sampled.",
            ca_half_width_km=None, score_percentiles=None, score_std=None,
        )
        assert cell.ca_refusal == "Not sampled."
        assert cell.ca_band is None


# ── D9 to D17: the cap and the refusals ──

def _without_state(side_tle: str) -> Callable[[pytest.MonkeyPatch], tuple[Scenario, Any]]:
    """A bound scenario in which *side_tle* cannot be propagated: elset_state gives None for it."""

    def make(monkeypatch: pytest.MonkeyPatch) -> tuple[Scenario, Any]:
        real = decision.elset_state

        def patched(tle: str, at: datetime) -> BlueTrack | None:
            return None if tle == side_tle else real(tle, at)

        monkeypatch.setattr(decision, "elset_state", patched)
        return _bound(), _never

    return make


#: Each refusal: how to make it, and the sentence its cells carry.
_REFUSALS: dict[str, tuple[Callable[[pytest.MonkeyPatch], tuple[Scenario, Any]], str]] = {
    "over the cap": (
        # The floor, 2 x 500 x (11.9 h + 9 min) = 12,050, is over the cap, so it is the figure; at 11.8 h the exact
        # cost is 2 x ((500 + 2) x 11.8 h + 500 x 9 min) = 11,997.2, which fits.
        lambda _mp: (_bound({0: _steady(500), 1: _steady(500)}, horizon_hours=11.9), _never),
        "Not sampled: this scenario needs at least 12,050 sample-hours (samples times the hours each is propagated, "
        "counting any burn before the window, plus 9 minutes of set-up for each sample, across 2 hypotheses), "
        "above the 12,000 one evaluation may run within its 300 s budget. At these sample counts the longest "
        "horizon that fits is 11.8 h.",
    ),
    "too few samples": (
        lambda _mp: (_bound({0: _evasive(49)}), _never),
        "Not sampled: 49 samples are fewer than the 50 the convergence check needs.",
    ),
    "blue out of date": (
        lambda _mp: (_scenario({0: _evasive()}, binding=_binding(blue_age=30.0)), _never),
        "Not sampled: the blue orbit is out of date, at its limit already or of unknown age, so a miss sampled from "
        "it would not be earned.",
    ),
    "red element set after the burn": (
        lambda _mp: (_bound({0: _steady(50, at=EPOCH - timedelta(hours=1))}), _never),
        "Not sampled: the red element set dates from 2026-10-17 12:00 UTC, after the burn at 2026-10-17 11:00 "
        "UTC, so it may already include the burn, and sampling would apply it twice.",
    ),
    "red age unknown": (
        lambda _mp: (_scenario({0: _evasive()}, binding=_binding(red_age=None)), _never),
        "Not sampled: the red orbit is out of date, at its limit already or of unknown age, so a miss sampled from "
        "it would not be earned.",
    ),
    "no blue state": (
        _without_state(PLANE_CHANGE.blue_tle),
        "Not sampled: the blue element set cannot be propagated to 2026-10-17 12:00 UTC.",
    ),
    "no red state": (
        _without_state(PLANE_CHANGE.red_tle),
        "Not sampled: the red element set cannot be propagated to 2026-10-17 12:00 UTC.",
    ),
    "start mismatch": (
        lambda _mp: (_bound({0: _evasive(offset_km=50.0)}), _never),
        "Not sampled: the hypothesis starts 50.0 km from the bound red track at its burn time, more than 10 km, "
        "so it was built from another element set, time or frame.",
    ),
    "velocity mismatch": (
        lambda _mp: (_bound({0: _evasive(dv_offset_km_s=0.15)}), _never),
        "Not sampled: the hypothesis starts 150.0 m/s from the bound red track's velocity at its burn time, more "
        "than 100 m/s, so its velocity is in other units or from another object.",
    ),
    "failed samples": (
        lambda _mp: (_bound(), _Fake(n_failed=1)),
        "Not sampled: 1 of 50 samples failed to propagate, and a P5 without them could hide the closest.",
    ),
    "re-entered samples": (
        lambda _mp: (_bound(), _Fake(n_failed=2, n_reentered=2)),
        "Not sampled: 2 of 50 samples failed to propagate, 2 of them by re-entering below 100 km, and a P5 without "
        "them could hide the closest.",
    ),
    "not converged": (
        lambda _mp: (_bound(), _Fake(half_width=2.3, converged=False)),
        "Not sampled: P5, P50 and P95 are known only to within 2.3 km, wider than the 1.0 km this miss needs (1 km, "
        "or 5 % of P5 where that is larger). Take more samples, with a shorter horizon if that goes over the 12,000 "
        "sample-hour cap.",
    ),
}


def _refused(name: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Scenario, ScenarioResult]:
    make, _sentence = _REFUSALS[name]
    scenario, sampler = make(monkeypatch)
    return scenario, evaluate_scenario(scenario, sampler=sampler)


class TestTheCapAndTheRefusals:
    @pytest.mark.parametrize("name", list(_REFUSALS))
    def test_each_refusal_is_named_in_every_cell_of_its_row_and_keeps_the_lookups(
        self, name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """D9 and D11 to D16."""
        scenario, result = _refused(name, monkeypatch)
        sentence = _REFUSALS[name][1] + _LOOKUPS
        lookup = _lookup(scenario)
        rows = [i for i, a in enumerate(scenario.adversary_actions) if a.hypothesis is not None]
        for i in rows:
            for cell, plain in zip(_cells(result, i), _cells(lookup, i), strict=True):
                assert cell.ca_refusal == sentence
                assert cell.ca_percentiles is None and cell.ca_std_km is None and cell.ca_samples is None
                assert cell.figure_bases.closest_approach_km == FigureBasis(
                    Basis.LOOKUP, f"{LOOKUP_BASES.closest_approach_km.note}. {sentence}",
                )
                assert dataclasses.replace(cell, ca_refusal=None, figure_bases=LOOKUP_BASES) == plain
        assert [result.ranked_per_adversary[i] for i in rows] == [lookup.ranked_per_adversary[i] for i in rows]
        assert result.row_notes == (None, None, None, None)

    def test_the_cap_is_12000_sample_hours_from_a_300_s_budget_with_9_minutes_of_set_up_a_sample(self) -> None:
        """B1: 300 s at 40 sample-hours a second, about a fifth under the slowest rate measured, 51 (SPC-113). The
        owner ruled on 2026-11-05 to raise the budget from 120 s to 300 s (SPC-178), so the cap is 12,000."""
        assert MAX_SAMPLE_HOURS == 12_000.0
        assert EVALUATION_BUDGET_S == 300.0
        assert SET_UP_S_PER_SAMPLE == 540.0

    def test_over_the_cap_nothing_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D9: the sampler fails the test if it is called, so the cap is checked before anything runs."""
        _scenario_over, result = _refused("over the cap", monkeypatch)
        assert [c.ca_refusal is not None for c in _cells(result, 0) + _cells(result, 1)] == [True] * 8

    def test_under_the_cap_it_runs(self) -> None:
        """B2: 11,997.2 sample-hours, (500 + 2) x 11.8 h and 500 x 9 min for each of two rows."""
        fake = _Fake()
        result = evaluate_scenario(_bound({0: _steady(500), 1: _steady(500)}, horizon_hours=11.8), sampler=fake)
        assert len(fake.calls) == 2
        assert all(c.ca_percentiles is not None for c in _cells(result, 0) + _cells(result, 1))

    def test_a_row_refused_before_the_run_is_not_counted_against_the_cap(self) -> None:
        fake = _Fake()
        rows = {0: _steady(500), 1: _steady(500), 2: _evasive(49)}
        result = evaluate_scenario(_bound(rows, horizon_hours=11.8), sampler=fake)
        assert len(fake.calls) == 2
        assert _cells(result, 2)[0].ca_refusal is not None
        assert "fewer than the 50" in str(_cells(result, 2)[0].ca_refusal)

    def test_a_burn_before_the_window_counts_its_look_back(self) -> None:
        """A burn 12 h before a 1 h window integrates about 13 h a sample: 1,000 samples is over the cap at any horizon.

        Counted as samples times the horizon, the same row would be 1,000 sample-hours and would run. The red
        element set predates the burn, so it cannot already include it.
        """
        early = EPOCH - timedelta(hours=12)
        h = AdversaryHypothesis.from_archetype(
            "evasive", PreManoeuvreState(early, tuple(_red_at(early).state_eci_km)), n_samples=1000,
        )
        binding = ScenarioBinding(red=_elset("red", age=13.0, epoch=early - timedelta(hours=1)), blue=_elset("blue"))
        result = evaluate_scenario(_scenario({0: h}, binding=binding), sampler=_never)
        refusal = str(_cells(result, 0)[0].ca_refusal)
        assert refusal.startswith("Not sampled: this scenario needs at least ")
        needs = float(re.search(r"needs at least ([\d,]+) sample-hours", refusal).group(1).replace(",", ""))  # type: ignore[union-attr]
        assert needs > 1000 * 12
        assert refusal.endswith(
            "No horizon of 0.1 h or more fits at these sample counts: take fewer samples, at least 50, or start "
            "the scenario nearer the burn." + _LOOKUPS
        )

    def test_a_burn_after_the_window_counts_its_search(self) -> None:
        """A burn 13 h in, after a 12 h window: 1,000 samples searched over 12 h is 12,000 h, though only 25 h integrate.

        1,000 x 12 h and 1,000 x 9 min is 12,150. Counted as integrated hours alone it would be 175 and would run.
        """
        scenario = _bound({0: _steady(1000, at=EPOCH + timedelta(hours=13))}, horizon_hours=12.0)
        refusal = str(_cells(evaluate_scenario(scenario, sampler=_never), 0)[0].ca_refusal)
        assert refusal.startswith("Not sampled: this scenario needs at least 12,150 sample-hours")

    def test_a_burn_after_the_window_is_costed_by_its_search_beside_a_look_back(self) -> None:
        """Under the floor, so costed exactly: a burn after a 4 h window and one 5 h before it, red fitted at -6 h.

        Row 0, 1,275 samples, burn at +5 h: searched 1,275 x 4 = 5,100 h, integrated only 4 + 5 = 9 h; with set-up
        5,291.25. Row 1, 1,250 samples, burn at -5 h: 4 + 9 + 1,250 x 9 = 11,263 h, with set-up 11,450.5. Together
        16,741.75, so 16,742; counting row 0 by what it integrates, 11,650.75 would run. The floor, 1,275 x 4.15 and
        1,250 x 4.15, is 10,478.75, under the cap. At 2.1 h, 2,527 x 2.1 + 6,633.75 = 11,940.45, and at 2.2 h
        12,193.15.
        """
        binding = ScenarioBinding(red=_elset("red", age=6.0, epoch=EPOCH - timedelta(hours=6)), blue=_elset("blue"))
        rows = {0: _steady(1275, at=EPOCH + timedelta(hours=5)), 1: _steady(1250, at=EPOCH - timedelta(hours=5))}
        scenario = _scenario(rows, binding=binding, horizon_hours=4.0)
        refusal = str(_cells(evaluate_scenario(scenario, sampler=_never), 0)[0].ca_refusal)
        assert refusal.startswith("Not sampled: this scenario needs at least 16,742 sample-hours")
        assert refusal.endswith("across 2 hypotheses), above the 12,000 one evaluation may run within its 300 s "
                                "budget. At these sample counts the longest horizon that fits is 2.1 h." + _LOOKUPS)

    def test_one_hypothesis_is_named_in_the_singular_with_its_longest_horizon(self) -> None:
        """1,450 x (12 h + 9 min) is 17,617.5, the floor, so 17,618 without drawing a sample; at 8.1 h the cost is
        (1,450 + 2) x 8.1 h + 1,450 x 9 min = 11,978.7, and at 8.2 h 12,123.9."""
        scenario = _bound({0: _steady(1450)}, horizon_hours=12.0)
        assert _cells(evaluate_scenario(scenario, sampler=_never), 0)[0].ca_refusal == (
            "Not sampled: this scenario needs at least 17,618 sample-hours (samples times the hours each is "
            "propagated, counting any burn before the window, plus 9 minutes of set-up for each sample, across 1 "
            "hypothesis), above the 12,000 one evaluation may run within its 300 s budget. At these sample counts the "
            "longest horizon that fits is 8.1 h." + _LOOKUPS
        )

    def test_many_samples_over_a_short_window_count_their_set_up(self) -> None:
        """50,000 samples over 0.1 h: 5,000 sample-hours propagated, but 7,500 more of set-up, so 12,500 and refused.

        Each sample costs a solve_ivp set-up and a closest-approach search whatever its window; without that,
        20,000 samples over 0.028 h counted 560 and ran for 49 s.
        """
        refusal = str(_cells(evaluate_scenario(_bound({0: _steady(50_000)}, horizon_hours=0.1), sampler=_never), 0)[0]
                      .ca_refusal)
        assert refusal.startswith("Not sampled: this scenario needs at least 12,500 sample-hours")
        assert refusal.endswith(
            "No horizon of 0.1 h or more fits at these sample counts: take fewer samples, at least 50, or start "
            "the scenario nearer the burn." + _LOOKUPS
        )

    def test_a_row_far_over_the_cap_is_refused_without_drawing_its_samples(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A million samples over 1 h is at least 1,150,000 sample-hours before any sample is drawn to cost it."""

        def drawn(*_: Any) -> NoReturn:
            raise AssertionError("samples were drawn to cost the row")

        monkeypatch.setattr(decision, "separation_integration_s", drawn)
        refusal = str(_cells(evaluate_scenario(_bound({0: _steady(1_000_000)}), sampler=_never), 0)[0].ca_refusal)
        assert refusal.startswith("Not sampled: this scenario needs at least 1,150,000 sample-hours")

    def test_the_red_no_state_sentence_names_the_burn_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Red is propagated to the burn, an hour after the window starts, not to the window start."""
        scenario = _bound({0: _steady(50, at=EPOCH + timedelta(hours=1))})
        real = decision.elset_state
        monkeypatch.setattr(
            decision, "elset_state", lambda tle, at: None if tle == PLANE_CHANGE.red_tle else real(tle, at),
        )
        assert _cells(evaluate_scenario(scenario, sampler=_never), 0)[0].ca_refusal == (
            "Not sampled: the red element set cannot be propagated to 2026-10-17 13:00 UTC." + _LOOKUPS
        )

    def test_a_start_off_in_velocity_by_element_set_error_is_sampled(self) -> None:
        """A start 0.005 km/s off in velocity is within what the element set's own error allows, so it is sampled.

        An included burn cannot be seen this way (position is continuous across an impulsive burn); the red
        element set's epoch is checked against the burn instead.
        """
        state = _RED_AT_EPOCH.state_eci_km.copy()
        state[4] += 0.005
        carried = AdversaryHypothesis.from_archetype("evasive", PreManoeuvreState(EPOCH, tuple(state)), n_samples=50)
        cell = _cells(evaluate_scenario(_bound({0: carried}), sampler=_Fake()), 0)[0]
        assert cell.ca_refusal is None and cell.ca_percentiles is not None

    def test_the_velocity_tolerance_is_100_m_s_and_just_inside_it_is_sampled(self) -> None:
        """V2: a start 99.9 m/s off in velocity is sampled; the check is coarse on purpose (SPC-116)."""
        assert decision.START_VELOCITY_TOLERANCE_KM_S == 0.1
        fake = _Fake()
        cell = _cells(evaluate_scenario(_bound({0: _evasive(dv_offset_km_s=0.0999)}), sampler=fake), 0)[0]
        assert len(fake.calls) == 1
        assert cell.ca_refusal is None and cell.ca_percentiles is not None

    def test_a_start_just_over_the_velocity_tolerance_is_refused(self) -> None:
        """V3: to a tenth of a m/s, so the figure never reads as the tolerance it is over."""
        cell = _cells(evaluate_scenario(_bound({0: _evasive(dv_offset_km_s=0.1001)}), sampler=_never), 0)[0]
        assert str(cell.ca_refusal).startswith(
            "Not sampled: the hypothesis starts 100.1 m/s from the bound red track's velocity at its burn time, more "
            "than 100 m/s,"
        )

    @pytest.mark.parametrize(("nudge", "sampled"), [(0.0, True), (-1.0, False)])
    def test_a_start_exactly_at_the_velocity_tolerance_is_accepted(
        self, nudge: float, sampled: bool, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The velocity tolerance is set to the hypothesis's own velocity difference, then to just below it."""
        carried = _evasive(dv_offset_km_s=0.07)
        dv = float(np.linalg.norm(
            np.asarray(carried.hypothesis.pre_manoeuvre_state_eci_km, dtype=float)[3:] - _RED_AT_EPOCH.state_eci_km[3:],
        ))
        monkeypatch.setattr(decision, "START_VELOCITY_TOLERANCE_KM_S", dv if nudge == 0.0 else math.nextafter(dv, 0.0))
        cell = _cells(evaluate_scenario(_bound({0: carried}), sampler=_Fake()), 0)[0]
        assert (cell.ca_percentiles is not None) is sampled

    def test_a_velocity_in_metres_per_second_is_refused(self) -> None:
        """V4: the velocity entered in m/s, not km/s, is a thousand times too large and caught here."""
        state = _RED_AT_EPOCH.state_eci_km.copy()
        state[3:] *= 1000.0
        carried = AdversaryHypothesis.from_archetype("evasive", PreManoeuvreState(EPOCH, tuple(state)), n_samples=50)
        cell = _cells(evaluate_scenario(_bound({0: carried}), sampler=_never), 0)[0]
        assert "so its velocity is in other units or from another object." in str(cell.ca_refusal)

    def test_position_is_reported_before_velocity(self) -> None:
        """Both off: the position sentence is the one given, since _start_mismatch runs first."""
        cell = _cells(
            evaluate_scenario(_bound({0: _evasive(offset_km=50.0, dv_offset_km_s=0.5)}), sampler=_never), 0,
        )[0]
        assert str(cell.ca_refusal).startswith("Not sampled: the hypothesis starts 50.0 km from")

    @pytest.mark.parametrize(("nudge", "sampled"), [(0.0, True), (-1.0, False)])
    def test_a_start_exactly_at_the_tolerance_is_accepted(
        self, nudge: float, sampled: bool, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The tolerance is set to the hypothesis's own distance from the track, then to just below it."""
        carried = _evasive(offset_km=7.0)
        d = float(np.linalg.norm(
            np.asarray(carried.hypothesis.pre_manoeuvre_state_eci_km, dtype=float)[:3] - _RED_AT_EPOCH.state_eci_km[:3],
        ))
        monkeypatch.setattr(decision, "START_TOLERANCE_KM", d if nudge == 0.0 else math.nextafter(d, 0.0))
        cell = _cells(evaluate_scenario(_bound({0: carried}), sampler=_Fake()), 0)[0]
        assert (cell.ca_percentiles is not None) is sampled

    def test_an_unknown_blue_age_is_refused_too(self) -> None:
        """D12, the other side and the other cause."""
        result = evaluate_scenario(_scenario({0: _evasive()}, binding=_binding(blue_age=None)), sampler=_never)
        assert str(_cells(result, 0)[0].ca_refusal).startswith("Not sampled: the blue orbit is out of date")

    def test_every_refusal_ends_saying_the_cell_is_lookups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D17."""
        for name in _REFUSALS:
            _scenario_refused, result = _refused(name, monkeypatch)
            monkeypatch.undo()
            refusal = _cells(result, 0)[0].ca_refusal
            assert refusal is not None and refusal.endswith(_LOOKUPS), name
            assert refusal.startswith("Not sampled: "), name

    def test_the_least_samples_is_the_convergence_checks(self) -> None:
        assert percentile_half_width_km([1.0] * 49) == math.inf
        assert math.isfinite(percentile_half_width_km([1.0] * 50))


class TestPlanSampling:
    def test_a_row_without_a_hypothesis_is_not_eligible(self) -> None:
        plan = plan_sampling(_bound(), _Fake())
        assert plan[1:] == (None, None, None)
        assert isinstance(plan[0], RowSampling)
        assert plan[0].refusal is None and plan[0].series is not None

    def test_a_refused_row_has_no_series(self) -> None:
        plan = plan_sampling(_bound({0: _evasive(49)}), _never)
        assert plan[0] is not None and plan[0].series is None
        assert str(plan[0].refusal).startswith("Not sampled: 49 samples")


# ── D18: the real series, end to end ──

class TestEndToEnd:
    def test_a_bound_plane_change_with_an_evasive_hypothesis_is_sampled(self) -> None:
        """D18: the plane-change element sets bound, the Evasive archetype from red's state at EPOCH, 50 samples."""
        scenario = _bound()
        result = evaluate_scenario(scenario)
        hypothesis = scenario.adversary_actions[0].hypothesis
        assert hypothesis is not None
        blue = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        series = run_separation_series(hypothesis.hypothesis, blue, SeparationWindow(EPOCH, 3600.0))
        assert series.converged and series.n_failed == 0
        for cell in _cells(result, 0):
            assert cell.ca_refusal is None
            assert cell.ca_percentiles == series.percentiles
            assert cell.closest_approach_km == round(series.miss_km_p5, 1)
            assert cell.ca_std_km == series.miss_km_std
            assert cell.time_to_closest_hours == round(series.earliest_tca_at_or_below_p5_s / 3600.0, 2)
        p = _cells(result, 0)[0].ca_percentiles
        assert p is not None
        # A 2 m/s evasive burn at the reference crossing: misses of about 10 to 14 km near 1,411 s.
        assert 9.0 < p[5] <= p[50] <= p[95] < 15.0
        assert abs(_cells(result, 0)[0].time_to_closest_hours - 1411.0 / 3600.0) < 0.02


# ── D19: the binding and the hypothesis are read only on this path ──

class _Tripwire:
    """An object that fails the test the moment anything looks inside it."""

    def __getattr__(self, name: str) -> NoReturn:
        raise AssertionError(f"read .{name}")

    def __bool__(self) -> NoReturn:
        raise AssertionError("tested for truth")


class TestTheBindingIsReadOnlyWithAHypothesis:
    def test_without_a_hypothesis_the_binding_is_never_read(self) -> None:
        scenario = _scenario()
        scenario.binding = _Tripwire()  # type: ignore[assignment]
        assert plan_sampling(scenario, _never) == (None, None, None, None)

    def test_with_a_hypothesis_the_binding_is_read(self) -> None:
        scenario = _scenario({0: _evasive()})
        scenario.binding = _Tripwire()  # type: ignore[assignment]
        with pytest.raises(AssertionError, match="read .red"):
            plan_sampling(scenario, _never)


# ── D21 and D22: what the result says about its sampled cells ──

class TestTheResultCountsItsSampledCells:
    def test_the_basis_lines_count_sampled_cells(self, sampled: ScenarioResult) -> None:
        """D21: the other 12 cells were lookups before SPC-120; their rows do not move red, so they are computed."""
        assert "Closest approach: sampled in 4 of 16 cells, computed in 12." in sampled.basis_lines
        assert "Time to closest approach: sampled in 4 of 16 cells, computed in 12." in sampled.basis_lines
        assert "Score: lookup in every cell." in sampled.basis_lines
        assert sampled.n_sampled_cells == 4

    def test_the_caveat_appears_only_with_a_sampled_cell(self, sampled: ScenarioResult) -> None:
        """D22: P5 3 km is inside the 10 km keep-out, so its term is 1; P95 20 km's is ln 2,500 / ln 5,000 = 0.918618;
        delta is 0.25 x (1 - 0.918618) = 0.0203 (SPC-191). It was 0.25 x (20 - 3) / 50,000 = 0.000085."""
        assert sampled.sampled_caveat == (
            "Sampled cells score on P5, the miss that 1 in 20 samples beat, not the median. The spread covers only "
            "the hypothesis: its delta-V, pointing, timing and drag. Element-set errors, and the hypothesis being "
            "wrong, are not in it. Our response is not applied to the blue orbit yet, so every response in a "
            "sampled row has the same closest approach. The score values closest approach in orders of magnitude "
            "from the 10 km keep-out distance to 50,000 km, so the sampled spread moves it by at most 0.0203 here."
        )
        plain = evaluate_scenario(_scenario())
        assert plain.sampled_caveat is None
        assert plain.n_sampled_cells == 0

    def test_the_caveat_delta_is_the_largest_over_the_sampled_cells(self) -> None:
        """D22 at weight 1: 1 - 0.918618 = 0.0814."""
        scenario = _bound()
        scenario.w_closest_approach = 1.0
        result = evaluate_scenario(scenario, sampler=_Fake())
        assert str(result.sampled_caveat).endswith("moves it by at most 0.0814 here.")

    def test_the_caveat_delta_is_the_widest_band_not_the_first(self) -> None:
        """Row 0 spans 3 to 20 km (1 - 0.918618 = 0.0814), row 1 3 to 103 km (1 - ln(50,000 / 103) / ln 5,000 =
        1 - 0.726184 = 0.2738): the caveat states the larger."""
        runs: list[SeparationSeries] = []

        def two_bands(_h: ManoeuvreHypothesis, _b: BlueTrack, window: SeparationWindow) -> SeparationSeries:
            series = _series(window)
            runs.append(series)
            return dataclasses.replace(series, miss_km_p95=103.0) if len(runs) == 2 else series

        scenario = _bound({0: _evasive(), 1: _evasive()})
        scenario.w_closest_approach = 1.0
        result = evaluate_scenario(scenario, sampler=two_bands)
        assert len(runs) == 2
        assert str(result.sampled_caveat).endswith("moves it by at most 0.2738 here.")

    def test_a_refused_result_has_no_caveat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _scenario_refused, result = _refused("too few samples", monkeypatch)
        assert result.sampled_caveat is None


# ── P1 to P5: the page ──

def _page(result: ScenarioResult) -> str:
    """The rendered page as the operator reads it: tags dropped, entities decoded, whitespace collapsed."""
    return html.unescape(_text(_render(result)))


class TestThePage:
    def test_a_sampled_cell_says_sampled_and_shows_its_band(self, sampled: ScenarioResult) -> None:
        """P1."""
        text = _page(sampled)
        assert text.count("3.0 km (sampled)") == 4
        assert text.count(
            "Sampled: P5 3.0 km to P95 20.0 km, median 8.0 km, each known to within 0.4 km, 50 samples."
        ) == 4
        assert text.count("1 in 20 samples came closer than P5; the closest of 50 was 2.0 km.") == 4
        assert "Phase 3 · computed closest approach in 12 cells · sampled in 4 cells" in text
        assert "Phase 1" not in text and "Phase 2" not in text

    def test_a_refused_cell_shows_its_sentence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """P2."""
        _scenario_refused, result = _refused("too few samples", monkeypatch)
        text = _page(result)
        sentence = _REFUSALS["too few samples"][1] + _LOOKUPS
        assert text.count(sentence) == 4

    def test_a_plain_result_says_nothing_of_sampling(self) -> None:
        """P3."""
        text = _page(evaluate_scenario(_scenario()))
        assert "Sampled" not in text and "Not sampled" not in text and "sampled closest approach" not in text
        assert "Phase 1 · What if" in text and "Phase 2" not in text

    def test_the_caveat_is_on_screen_when_any_cell_is_sampled(self, sampled: ScenarioResult) -> None:
        """P4."""
        assert str(sampled.sampled_caveat) in _page(sampled)

    def test_the_row_header_shows_the_hypothesis_or_the_row_note(self) -> None:
        """P5."""
        carried = _evasive()
        text = _page(evaluate_scenario(_bound({0: carried}), sampler=_Fake()))
        assert carried.sentence in text
        unbound = _page(evaluate_scenario(_scenario({0: carried})))
        assert carried.sentence in unbound
        assert "Hypothesis carried, not sampled: bind a red track and a blue asset" in unbound
