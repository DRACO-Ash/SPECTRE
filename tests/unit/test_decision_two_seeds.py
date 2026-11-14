"""A sampled row's seed is shown, and its convergence is checked on two seeds (SPC-224, evaluation F-35).

The evaluation found the seed fixed at 42 and never shown, and at 50 samples whether a row converged was one draw:
15 of 20 seeds converged in one case and 1 of 6 in another (probe P-11). Now every sampled row is drawn on its
hypothesis's own seed, whose figures are shown, and again on the second seed, monte_carlo.second_seed (the seed plus
one: 43 for 42), and is converged only when both draws are. When the two disagree the row is not converged and not
sampled, with a sentence naming both seeds and both half-widths. A row not converged on its own seed is refused as
before and not drawn again. Each sampled row is charged twice against the sample-hour cap, so the longest horizon that
fits halves. The seed is in each sampled cell's basis note and in the stored inputs, where every hypothesis has always
carried it; the rule is stored as version 7's convergence_rule, and a record 0.28.0 to 0.41.0 wrote replays on its
one seed (tests/unit/test_decision_replay_0_41_0.py).

Most tests inject a sampler that converges or not by seed, so none runs a propagator; one runs the real engine on the
case found at 602c963 where seed 42 converges and seed 43 does not.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.astro.elset_check import FUTURE_EPOCH_TOLERANCE
from spectre.astro.monte_carlo import (
    BlueBurn,
    BlueTrack,
    BurnSeries,
    ManoeuvreHypothesis,
    MissStats,
    SeedCheck,
    SeparationSeries,
    SeparationWindow,
    Tick,
    confirmed,
    second_seed,
)
from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    MAX_SAMPLE_HOURS,
    SECOND_SEED_STAGE,
    ConvergenceRule,
    RunControl,
    SamplingProgress,
    evaluate_scenario,
    longest_horizon_h,
    seed_words,
)
from spectre.domain.decision_inputs import VERSION, decode_scenario, encode_scenario, store_inputs
from spectre.web.decision_record import stored_of
from tests.unit.test_decision_figure_basis import _render
from tests.unit.test_decision_sampled import _LOOKUPS, _bound, _cells, _evasive, _never, _series, _steady

_HALF_WIDTHS = {42: 0.4, 43: 1.6}


class _BySeed:
    """A sampler whose series converges or not by its hypothesis's seed, as *half_widths* says: within the 1 km
    tolerance at or under 1 km. It records the seed of each call, and ticks once per sample when given a tick."""

    def __init__(self, half_widths: dict[int, float] | None = None) -> None:
        self.half_widths = _HALF_WIDTHS if half_widths is None else half_widths
        self.seeds: list[int] = []

    def __call__(
        self, hypothesis: ManoeuvreHypothesis, _blue: BlueTrack, window: SeparationWindow, /, *,
        tick: Tick | None = None, **_: Any,
    ) -> SeparationSeries:
        seed = hypothesis.random_seed
        self.seeds.append(seed)
        for k in range(1, 51):
            if tick is not None:
                tick(k, 50)
        hw = self.half_widths[seed]
        series = _series(window, half_width=hw, converged=hw <= 1.0)
        return dataclasses.replace(series, random_seed=seed, tolerance_km=1.0)


def _one_seed(**kwargs: Any) -> Any:
    return dataclasses.replace(_bound(**kwargs), convergence_rule=ConvergenceRule.ONE_SEED)


class TestTheSecondSeed:
    def test_it_is_the_seed_plus_one(self) -> None:
        assert (second_seed(42), second_seed(7)) == (43, 8)

    def test_a_new_scenario_checks_two_seeds(self) -> None:
        assert _bound().convergence_rule is ConvergenceRule.TWO_SEEDS


class TestBothSeedsConverge:
    def test_the_row_is_sampled_on_its_own_seeds_figures_and_says_both_seeds(self) -> None:
        sampler = _BySeed({42: 0.4, 43: 0.5})
        cell = _cells(evaluate_scenario(_bound(), sampler=sampler), 0)[0]
        assert sampler.seeds == [42, 43]
        assert cell.ca_refusal is None
        assert cell.ca_half_width_km == 0.4
        note = cell.figure_bases.closest_approach_km.note
        assert note.endswith("; drawn on seed 42, its convergence checked on seed 43 as well, which converged too")


class TestTheSeedsDisagree:
    def test_converged_on_its_own_seed_and_not_the_second_the_row_is_not_converged(self) -> None:
        sampler = _BySeed()
        cells = _cells(evaluate_scenario(_bound(), sampler=sampler), 0)
        assert sampler.seeds == [42, 43]
        assert {cell.ca_refusal for cell in cells} == {
            "Not sampled: the samples converged on seed 42, known to within 0.40 km against the 1.00 km this miss "
            "needs, but not on seed 43, the second its convergence is checked on, where they are known only to "
            "within 1.60 km against 1.00 km. The two seeds disagree, so the band would rest on the luck of one "
            f"draw, and the row is not converged. Take more samples, with a shorter horizon if that goes over the "
            f"{MAX_SAMPLE_HOURS:,.0f} sample-hour cap." + _LOOKUPS
        }
        assert all(cell.ca_percentiles is None for cell in cells)

    def test_under_one_seed_the_same_row_is_sampled_on_seed_42_alone(self) -> None:
        """The rule of 0.28.0 to 0.41.0, read only from a record those releases wrote."""
        sampler = _BySeed()
        cell = _cells(evaluate_scenario(_one_seed(), sampler=sampler), 0)[0]
        assert sampler.seeds == [42]
        assert cell.ca_refusal is None
        assert cell.figure_bases.closest_approach_km.note.endswith(
            "; drawn on seed 42, its convergence judged on that draw alone, as before 0.42.0",
        )


class TestNotConvergedOnItsOwnSeed:
    def test_it_is_refused_naming_its_seed_and_not_drawn_again(self) -> None:
        sampler = _BySeed({42: 1.6, 43: 0.4})
        cells = _cells(evaluate_scenario(_bound(), sampler=sampler), 0)
        assert sampler.seeds == [42]
        assert {cell.ca_refusal for cell in cells} == {
            "Not sampled: P5, P50 and P95 are known only to within 1.6 km, wider than the 1.0 km this miss needs "
            "(1 km, or 5 % of P5 where that is larger), drawn on seed 42. Take more samples, with a shorter horizon "
            f"if that goes over the {MAX_SAMPLE_HOURS:,.0f} sample-hour cap." + _LOOKUPS
        }


class TestUnderTheBudget:
    def test_the_second_draw_reports_its_own_stage(self) -> None:
        seen: list[SamplingProgress] = []
        run = RunControl(EVALUATION_BUDGET_S, stop=lambda: None, progress=seen.append, clock=lambda: 0.0)
        evaluate_scenario(_bound(), sampler=_BySeed({42: 0.4, 43: 0.4}), run=run)
        assert [p.stage for p in seen].count("sampling") == 50
        assert [p.stage for p in seen].count(SECOND_SEED_STAGE) == 50
        assert SECOND_SEED_STAGE == "second seed"

    def test_a_budget_spent_on_the_second_draw_refuses_the_row(self) -> None:
        """1 s a reading and a 70 s budget: the first draw's 50 ticks read 1 to 50 s, the second's 21st reads 71 s,
        past the budget, so 20 of its samples were done within it."""
        readings = iter(range(1000))
        run = RunControl(70.0, stop=lambda: None, clock=lambda: float(next(readings)))
        cells = _cells(evaluate_scenario(_bound(), sampler=_BySeed({42: 0.4, 43: 0.4}), run=run), 0)
        assert {cell.ca_refusal for cell in cells} == {
            "Not sampled: this evaluation's 70 s budget ran out after 20 of 50 samples of this hypothesis drawn on "
            "the second seed its convergence is checked on, so whether it converged is not known. Take fewer "
            "samples or a shorter horizon." + _LOOKUPS
        }


class TestTheCap:
    def test_each_sampled_row_is_charged_twice(self) -> None:
        """The longest horizon that fits at 500 samples falls from 23.7 h on one seed to 11.8 h on two."""
        assert longest_horizon_h(500, seeds=1) == 23.7
        assert longest_horizon_h(500) == 11.8
        assert longest_horizon_h(50) == 115.2

    def test_the_cap_refusal_says_each_hypothesis_is_drawn_on_two_seeds(self) -> None:
        cells = _cells(evaluate_scenario(_bound({0: _evasive(2000)}, horizon_hours=24.0), sampler=_never), 0)
        refusal = str(cells[0].ca_refusal)
        assert "across 1 hypothesis, each drawn on two seeds)" in refusal
        assert "At these sample counts the longest horizon that fits is" in refusal


class TestConfirmed:
    def test_every_figure_is_the_first_seeds_and_converged_is_both(self) -> None:
        window = SeparationWindow(_bound().epoch_utc, 3600.0)
        first, second = _series(window, half_width=0.4), _series(window, half_width=1.6, converged=False)
        found = confirmed(first, second, 43)
        assert found.converged is False
        assert found.check == SeedCheck(43, 1.6, second.tolerance_km, False)
        assert dataclasses.replace(found, converged=True, check=None) == first

    def test_each_of_our_burns_is_converged_only_when_both_draws_are(self) -> None:
        window = SeparationWindow(_bound().epoch_utc, 3600.0)

        def burnt(converged: bool) -> BurnSeries:
            stats = MissStats(3.0, 8.0, 20.0, 5.0, 0.4 if converged else 1.6, 1.0, converged, 0.2)
            return BurnSeries(BlueBurn(600.0, (0.0, 0.001, 0.0)), (), (), 0, stats)

        first = dataclasses.replace(_series(window), after_burns=(burnt(True), burnt(True)))
        second = dataclasses.replace(_series(window), after_burns=(burnt(True), burnt(False)))
        found = confirmed(first, second, 43)
        assert [b.stats.converged for b in found.after_burns] == [True, False]
        assert [b.stats.half_width_km for b in found.after_burns] == [0.4, 0.4]
        assert found.converged is True
        with pytest.raises(ValueError, match="a series and its second draw search the same burns"):
            confirmed(first, _series(window), 43)

    def test_the_seed_words(self) -> None:
        window = SeparationWindow(_bound().epoch_utc, 3600.0)
        series = _series(window)
        assert seed_words(series) == "drawn on seed 42, its convergence judged on that draw alone, as before 0.42.0"
        assert seed_words(confirmed(series, series, 43)) == (
            "drawn on seed 42, its convergence checked on seed 43 as well, which converged too"
        )


class TestTheStoredInputs:
    def test_version_7_stores_the_two_seed_rule_and_the_seed(self) -> None:
        result = evaluate_scenario(_bound(), sampler=_BySeed({42: 0.4, 43: 0.4}))
        text, _sha256 = store_inputs(result)
        document = json.loads(text)
        assert (VERSION, document["version"]) == (7, 7)
        assert document["scenario"]["convergence_rule"] == "two seeds"
        hypothesis = document["scenario"]["adversary_actions"][0]["hypothesis"]["hypothesis"]
        assert hypothesis["random_seed"] == 42

    def test_a_version_6_document_reads_as_one_seed(self) -> None:
        document = encode_scenario(_bound())
        del document["convergence_rule"]
        assert decode_scenario(document, version=6).convergence_rule is ConvergenceRule.ONE_SEED

    def test_a_version_7_document_on_one_seed_is_refused(self) -> None:
        document = {**encode_scenario(_bound()), "convergence_rule": "one seed"}
        with pytest.raises(ValueError, match="version 7 holds the two-seed convergence rule alone"):
            decode_scenario(document)

    def test_a_scenario_on_one_seed_is_never_stored_again(self) -> None:
        with pytest.raises(ValueError, match="is never stored again"):
            encode_scenario(_one_seed())


class TestOnScreen:
    def test_the_result_names_both_seeds_beside_what_converged_means(self) -> None:
        result = evaluate_scenario(_bound(), sampler=_BySeed({42: 0.4, 43: 0.4}))
        assert result.seed_line == (
            "Every sample in the outcome matrix is drawn on seed 42, and the figures shown are that draw's. Each row's "
            "convergence is checked on seed 43 as well, a second, independent draw, and a row is converged only when "
            "both draws are: a row whose two draws disagree is not sampled, and its cells say so. A game tree's later "
            "turns are drawn otherwise, and the tree says how."
        )
        assert result.tree_seed_line is None   # one turn: no tree to say it beside
        page = _render(result)
        assert f'<div class="seed-line" style="color:var(--gold)">{result.seed_line}</div>' in page.replace(
            "&#39;", "'",
        )

    def test_a_replay_on_one_seed_says_so(self) -> None:
        result = evaluate_scenario(_one_seed(), sampler=_BySeed({42: 0.4, 43: 0.4}))
        assert result.seed_line == (
            "Every sample in the outcome matrix is drawn on seed 42. This result is under the rule of 0.28.0 to "
            "0.41.0, which judged convergence on that one draw, as the record it replays was evaluated."
        )

    def test_nothing_sampled_says_nothing_of_seeds(self) -> None:
        assert evaluate_scenario(_bound(), sampler=_BySeed({42: 1.6, 43: 0.4})).seed_line is None


class TestAfterOurBurn:
    def test_a_burn_series_the_second_seed_did_not_converge_says_the_seeds_disagree(self) -> None:
        from spectre.domain.decision import _after_burn_refusal

        stats = MissStats(3.0, 8.0, 20.0, 5.0, 0.4, 1.0, False, 0.2)
        burn = BurnSeries(BlueBurn(600.0, (0.0, 0.001, 0.0)), (), (), 0, stats)
        assert _after_burn_refusal(burn, 50) == (
            "Not sampled after our burn: the samples converged on the hypothesis's own seed, known to within 0.40 km "
            "against the 1.00 km this miss needs, but not on the second seed its convergence is checked on. The two "
            "seeds disagree, so the row is not converged after our burn (SPC-224)." + _LOOKUPS
        )
        wide = burn._replace(stats=stats._replace(half_width_km=1.6))
        assert str(_after_burn_refusal(wide, 50)).startswith(
            "Not sampled after our burn: P5, P50 and P95 are known only to within 1.6 km",
        )


class TestBesideAGameTree:
    """V0.42 review: the seed line said every sample was drawn on seed 42 and checked on 43, which a tree's later
    turns are not: each draws on a seed derived from the row's, the turn and the branch, and is judged on that one
    draw. Beside a tree of more than one turn holding a sampled row, the tree says so."""

    def test_a_tree_says_its_later_turns_are_judged_on_one_draw(self) -> None:
        result = evaluate_scenario(dataclasses.replace(_bound(), turns=2), sampler=_BySeed({42: 0.4, 43: 0.4}))
        assert result.tree_seed_line == (
            "Turn 1's sampled rows are the matrix's, drawn on seed 42 and checked on seed 43 as well. Turns 2 and 3 "
            "draw each branch's samples afresh on a seed derived from the row's seed, the turn and the branch, and "
            "each sequence's closest approach is judged converged on that one draw, not checked on a second."
        )

    def test_a_replayed_tree_on_one_seed_says_every_turn_is_one_draw(self) -> None:
        result = evaluate_scenario(dataclasses.replace(_one_seed(), turns=2), sampler=_BySeed({42: 0.4, 43: 0.4}))
        assert result.tree_seed_line == (
            "Every turn's sampled figures are judged converged on one draw: turn 1 on seed 42, and turns 2 and 3 on a "
            "seed derived from it, the turn and the branch, as the record it replays was built."
        )

    def test_a_tree_with_no_sampled_row_says_nothing_of_seeds(self) -> None:
        scenario = dataclasses.replace(_bound(), turns=2)
        plain = dataclasses.replace(scenario, adversary_actions=[
            dataclasses.replace(a, hypothesis=None) for a in scenario.adversary_actions
        ])
        assert evaluate_scenario(plain, sampler=_never).tree_seed_line is None

    def test_the_tree_view_puts_it_beside_a_built_tree(self) -> None:
        """The 0.41.0 tree record's scenario, two sampled turns over plane_change at 50 samples, built now on two seeds:
        the line closes the tree's assumptions, after the two of SPC-219 and SPC-220."""
        from spectre.domain.decision_tree import evaluate_tree
        from spectre.web.tree_view import tree_view
        from tests.unit.test_decision_replay_0_41_0 import _record

        stored = stored_of(_record("tree"))
        result = evaluate_tree(dataclasses.replace(stored.scenario, convergence_rule=ConvergenceRule.TWO_SEEDS),
                               stored.rule)
        view = tree_view(result)
        assert view is not None and view.nodes
        assert len(view.assumptions) == 3
        assert view.assumptions[-1] == result.tree_seed_line
        assert view.assumptions[-1].startswith("Turn 1's sampled rows are the matrix's, drawn on seed 42")


class TestTheReviewsMutants:
    """V0.42 review: each test below fails on a mutation of the code that survived the first suite."""

    def test_the_floor_is_charged_twice_too(self) -> None:
        """M4: two rows of 500 over 11.9 h. Each row's floor, 500 x (11.9 h + 9 min) = 6,025, is charged twice, so
        24,100 over the cap is the figure; charged once, 12,050 would be."""
        cells = _cells(evaluate_scenario(_bound({0: _steady(500), 1: _steady(500)}, horizon_hours=11.9),
                                         sampler=_never), 0)
        assert str(cells[0].ca_refusal).startswith("Not sampled: this scenario needs at least 24,100 sample-hours")

    def test_the_second_draw_reseeds_every_later_burn_of_a_transfer(self) -> None:
        """M22: the second draw is independent of the first only if each later burn draws on its second seed too."""
        from tests.unit.test_decision_transfer import _Recorder, _transfer, _with

        sampler = _Recorder()
        evaluate_scenario(_with(_transfer()), sampler=sampler)
        assert [call[0].random_seed for call in sampler.calls] == [42, 43]
        first, second = ([h.random_seed for h in kw["red_then"]] for kw in sampler.keywords)
        assert len(first) == 2
        assert second == [second_seed(seed) for seed in first]

    @pytest.mark.parametrize(("ahead", "future"), [
        (FUTURE_EPOCH_TOLERANCE, False), (FUTURE_EPOCH_TOLERANCE + timedelta(microseconds=1), True),
    ], ids=["exactly 5 min", "a microsecond past"])
    def test_the_tolerance_boundary_exactly(self, ahead: timedelta, future: bool) -> None:
        """M8, M9: an epoch exactly 5 min after now reads as now, at ingest and in the age; a microsecond past is in
        the future. Exact datetimes, since an element set's epoch field cannot land on the boundary exactly."""
        from spectre.astro.elset_check import _ahead
        from spectre.web.elsets import ahead_hours

        now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
        assert (ahead_hours(now + ahead, now) > 0.0) is future
        assert bool(_ahead(now + ahead, now)) is future
        assert ahead_hours(now - timedelta(hours=1), now) == 0.0
        assert _ahead(now + ahead, None) == [] and _ahead(None, now) == []
