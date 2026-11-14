"""The composite score values closest approach and our delta-V in orders of magnitude (SPC-191, evaluation F-10).

Before SPC-191 closest approach entered the score linearly over 0 to 50,000 km at weight 0.25, so 1 m/s of our
delta-V weighed the same as 400 km of miss, and our delta-V saturated at 100 m/s, so 100 and 500 m/s scored the same
(evaluation probe P-17). The scales now, each Claude's design choice and not a ruling, the technical authority not
yet having signed their rationale:

● closest approach: 1 at or inside the keep-out distance K (Scenario.keep_out_km, set on the panel, default 10 km,
  unsourced), 0 at or beyond 50,000 km, and ln(50,000 / miss) / ln(50,000 / K) between;
● our delta-V: ln(1 + dv) / ln(1 + 1,000) for dv in m/s, capped at 1 at the engine's per-burn limit, 1,000 m/s.

Every expected value below is worked by hand from those two formulas, with ln 5,000 = 8.517193, ln 500 = 6.214608
and ln 1,001 = 6.908755.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from spectre.domain.decision_transfer import MAX_BURN_M_S

EPOCH = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
#: Two responses equal in everything the score reads but closest approach and our delta-V: 1 h to execute, fully
#: reversible, so the time term is 0.10 x 1 / 72 and the reversibility term 0 for both.
_SAME: dict[str, Any] = {
    "action_type": ActionType.MANOEUVRE, "cost": 0.0, "reversibility": 1.0, "time_to_execute_hours": 1.0,
}
_SHARED = 0.10 * 1.0 / 72.0
_HOLD = FriendlyResponse("F0", "hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0)
_ALL_ON: dict[str, dict[str, float]] = {
    "ca": {"w_custody": 0.0, "w_closest_approach": 1.0, "w_dv_cost": 0.0, "w_time_to_exec": 0.0,
           "w_reversibility": 0.0},
    "dv": {"w_custody": 0.0, "w_closest_approach": 0.0, "w_dv_cost": 1.0, "w_time_to_exec": 0.0,
           "w_reversibility": 0.0},
}


def _scenario(responses: list[FriendlyResponse] | None = None, **fields: Any) -> Scenario:
    return Scenario(
        name="scales", epoch_utc=EPOCH,
        adversary_actions=[AdversaryAction("A0", "approach", ActionType.MANOEUVRE, 0.5, 0.5)],
        friendly_responses=responses or [_HOLD], **fields,
    )


def _held(miss_km: float, dv_m_s: float = 0.0) -> decision._Figures:
    """Custody held, no gap: only closest approach and our delta-V move the score."""
    return decision._Figures(True, 0.0, miss_km, dv_m_s / 1000.0)


def _ca_term(miss_km: float, **fields: Any) -> float:
    """The closest-approach term alone: every weight on it."""
    return decision._score(_scenario(**_ALL_ON["ca"], **fields), _HOLD, _held(miss_km))


def _dv_term(dv_m_s: float) -> float:
    """Our delta-V term alone: every weight on it, the miss far enough to score nothing anyway."""
    return decision._score(_scenario(**_ALL_ON["dv"]), _HOLD, _held(50_000.0, dv_m_s))


class TestTheInverseOfProbeP17:
    def test_a_1_m_s_burn_that_opens_the_miss_from_1_to_100_km_beats_doing_nothing(self) -> None:
        """X burns nothing and leaves 1 km; Y burns 1 m/s and leaves 100 km; custody held in both.

        At the defaults (K 10 km; weights 0.35, 0.25, 0.20, 0.10, 0.10):
        X = 0.25 x 1 (1 km is inside K) + 0.20 x 0 + shared = 0.250000 + shared.
        Y = 0.25 x ln 500 / ln 5,000 + 0.20 x ln 2 / ln 1,001 + shared
          = 0.25 x 0.729654 + 0.20 x 0.100329 + shared = 0.182414 + 0.020066 + shared = 0.202479 + shared.
        Before SPC-191, X was 0.25 x (1 - 1 / 50,000) and Y 0.25 x (1 - 100 / 50,000) + 0.20 x 0.01, so X won.
        """
        s = _scenario()
        x = FriendlyResponse(id="X", name="no burn, 1 km miss", **_SAME)
        y = FriendlyResponse(id="Y", name="1 m/s burn, 100 km miss", **_SAME)
        sx, sy = decision._score(s, x, _held(1.0)), decision._score(s, y, _held(100.0, 1.0))
        assert sx == pytest.approx(0.250000 + _SHARED, abs=1e-6)
        assert sy == pytest.approx(0.202479 + _SHARED, abs=1e-6)
        two = dataclasses.replace(s, friendly_responses=[x, y])
        cells = [[SimpleNamespace(composite_score=sx), SimpleNamespace(composite_score=sy)]]
        assert find_robust_response(two, cells, SelectorStrategy.MINIMAX).id == "Y"  # type: ignore[arg-type]

    def test_the_break_even_at_the_defaults_is_about_9_3_m_s(self) -> None:
        """Opening a miss from 1 km to 100 km lowers the score by 0.25 x (1 - 0.729654) = 0.067586. Our delta-V adds
        0.20 x ln(1 + b) / ln 1,001, equal to it when ln(1 + b) = 0.337932 x 6.908755 = 2.334652, so b = 9.326 m/s:
        any burn under about 9.3 m/s that buys that move scores better than doing nothing, any over it worse."""
        s = _scenario()
        x = FriendlyResponse(id="X", name="no burn", **_SAME)
        y = FriendlyResponse(id="Y", name="burn", **_SAME)
        nothing = decision._score(s, x, _held(1.0))
        assert decision._score(s, y, _held(100.0, 9.2)) < nothing < decision._score(s, y, _held(100.0, 9.5))
        assert decision._score(s, y, _held(100.0, 9.326)) == pytest.approx(nothing, abs=1e-5)

    def test_the_break_even_moves_with_the_keep_out_distance(self) -> None:
        """K 1 km: the move is 0.25 x (1 - ln 500 / ln 50,000) = 0.25 x (1 - 6.214608 / 10.819778) = 0.106406, so
        ln(1 + b) = 0.532031 x 6.908755 = 3.675671 and b = 38.48 m/s. K 100 km: 1 km and 100 km are both inside it,
        so no burn buys anything and any burn scores worse than doing nothing."""
        x = FriendlyResponse(id="X", name="no burn", **_SAME)
        y = FriendlyResponse(id="Y", name="burn", **_SAME)
        near = _scenario(keep_out_km=1.0)
        nothing = decision._score(near, x, _held(1.0))
        assert decision._score(near, y, _held(100.0, 38.48)) == pytest.approx(nothing, abs=1e-5)
        far = _scenario(keep_out_km=100.0)
        assert decision._score(far, y, _held(100.0, 0.1)) > decision._score(far, x, _held(1.0))


class TestOurDeltaV:
    def test_100_and_500_m_s_score_apart(self) -> None:
        """ln 101 / ln 1,001 = 4.615121 / 6.908755 = 0.668010; ln 501 / ln 1,001 = 6.216606 / 6.908755 = 0.899816."""
        assert _dv_term(100.0) == pytest.approx(0.668010, abs=1e-6)
        assert _dv_term(500.0) == pytest.approx(0.899816, abs=1e-6)

    @pytest.mark.parametrize("dv_m_s", [1000.0, 1000.5, 2500.0, 1e6])
    def test_the_per_burn_limit_and_above_score_the_same_as_the_limit(self, dv_m_s: float) -> None:
        assert MAX_BURN_M_S == 1000.0
        assert _dv_term(dv_m_s) == _dv_term(MAX_BURN_M_S) == 1.0

    def test_no_burn_costs_nothing_and_each_order_of_magnitude_costs_alike(self) -> None:
        """ln 2 / ln 1,001 = 0.100329 for 1 m/s; ln 11 / ln 1,001 = 0.347081 for 10 m/s."""
        assert _dv_term(0.0) == 0.0
        assert _dv_term(1.0) == pytest.approx(0.100329, abs=1e-6)
        assert _dv_term(10.0) == pytest.approx(0.347081, abs=1e-6)


class TestClosestApproach:
    @pytest.mark.parametrize("miss_km", [0.0, 0.5, 9.999, 10.0])
    def test_a_miss_at_or_inside_the_keep_out_distance_scores_the_full_penalty(self, miss_km: float) -> None:
        assert _ca_term(miss_km) == 1.0

    @pytest.mark.parametrize("miss_km", [50_000.0, 50_000.001, 1e6, math.inf])
    def test_a_miss_at_or_beyond_50000_km_scores_none(self, miss_km: float) -> None:
        assert _ca_term(miss_km) == 0.0

    def test_between_it_is_continuous_and_strictly_decreasing(self) -> None:
        misses = np.geomspace(10.0, 50_000.0, 2001)[1:-1]
        terms = [_ca_term(float(m)) for m in misses]
        assert all(a > b for a, b in zip(terms, terms[1:], strict=False))
        assert _ca_term(10.0 * (1.0 + 1e-9)) == pytest.approx(1.0, abs=1e-9)
        assert _ca_term(50_000.0 * (1.0 - 1e-9)) == pytest.approx(0.0, abs=1e-9)

    def test_each_order_of_magnitude_of_miss_is_worth_the_same(self) -> None:
        """ln 500 / ln 5,000 = 0.729654 at 100 km; each factor of 10 takes ln 10 / ln 5,000 = 0.270346 off."""
        assert _ca_term(100.0) == pytest.approx(0.729654, abs=1e-6)
        assert _ca_term(1000.0) == pytest.approx(0.729654 - 0.270346, abs=1e-6)

    def test_the_keep_out_distance_moves_the_full_penalty(self) -> None:
        """At K 1 km a 5 km miss is ln 10,000 / ln 50,000 = 9.210340 / 10.819778 = 0.851250; at K 100 km a 50 km
        miss is inside it."""
        assert _ca_term(5.0, keep_out_km=1.0) == pytest.approx(0.851250, abs=1e-6)
        assert _ca_term(1.0, keep_out_km=1.0) == 1.0
        assert _ca_term(50.0, keep_out_km=100.0) == 1.0


class TestTheKeepOutDistance:
    def test_the_default_is_10_km(self) -> None:
        assert decision.DEFAULT_KEEP_OUT_KM == 10.0
        assert _scenario().keep_out_km == decision.DEFAULT_KEEP_OUT_KM

    @pytest.mark.parametrize("keep_out_km", [0.0, 0.05, -1.0, 10_000.5, 50_000.0, math.nan, math.inf])
    def test_a_scenario_refuses_one_out_of_range_or_not_finite(self, keep_out_km: float) -> None:
        with pytest.raises(ValueError, match="keep_out_km"):
            _scenario(keep_out_km=keep_out_km)

    @pytest.mark.parametrize("keep_out_km", [0.1, 10_000.0])
    def test_it_takes_either_end_of_its_range(self, keep_out_km: float) -> None:
        assert _scenario(keep_out_km=keep_out_km).keep_out_km == keep_out_km

    def test_it_enters_the_scenarios_provenance_hash(self) -> None:
        def scenario_hash(**fields: Any) -> str:
            found = evaluate_scenario(_scenario(**fields)).provenance
            assert found is not None
            return next(i.sha256 for i in found.inputs if i.label == "scenario")

        assert scenario_hash(keep_out_km=20.0) != scenario_hash() == scenario_hash(keep_out_km=10.0)

    def test_the_result_states_it_with_its_basis(self) -> None:
        line = evaluate_scenario(_scenario(keep_out_km=25.0)).score_scales_line
        assert "25 km" in line
        assert "50,000 km" in line
        assert "1,000 m/s" in line
        assert "10 km, is Claude's choice and unsourced" in line

    def test_the_scores_basis_note_says_the_default_is_unsourced(self) -> None:
        note = decision.LOOKUP_BASES.composite_score.note
        assert "keep-out distance" in note
        assert "10 km" in note and "unsourced" in note
        assert "100 m/s" not in note


class TestTheDesignRecord:
    def test_the_phases_doc_records_the_scales_as_claudes_choices_with_the_break_even(self) -> None:
        """The scales are Claude's design choices, not rulings, and F-10's closing evidence needs the technical
        authority's signature, which it does not have; the break-even worked above is stated there too."""
        path = Path(__file__).resolve().parents[2] / "docs" / "decision_engine_phases.md"
        if not path.exists():
            pytest.skip("docs/decision_engine_phases.md is excluded from the submission package")
        doc = " ".join(path.read_text(encoding="utf-8").split())
        section = doc.split("## Score scales (SPC-191)", 1)[1].split(" ## ", 1)[0]
        assert "Claude's design choice, not a ruling" in section
        assert "The technical authority has not yet signed the scale rationale" in section
        assert "about 9.3 m/s" in section
        assert "Keep-out distance (km)" in section
        assert "unsourced" in section


# ── Review of SPC-191: every reader of the miss takes the scenario's keep-out distance, states it as scored, and
#    says what it reads ──

_CLOSE = (5.0, 60.0)        # inside a 10 km keep-out to 60 km
_FAR = (2_000.0, 6_000.0)   # 2,000 to 6,000 km: four times the kilometres, but under half an order of magnitude


def _burn_note(keep_out_km: float, **cells: tuple[float, float]) -> str | None:
    """The burn note on a result with one row per named cell, each carrying a 2 m/s burn moving its miss from
    the first figure to the second."""
    scenario = _scenario()
    scenario.adversary_actions = [AdversaryAction(f"A{i}", name.replace("_", " "), ActionType.MANOEUVRE, 0.5, 0.5)
                                  for i, name in enumerate(cells)]
    scenario.keep_out_km = keep_out_km
    rows = [
        (i, SimpleNamespace(
            delta_v_cost_km_s=0.002,
            ca_response=SimpleNamespace(sized=SimpleNamespace(burn=object()), misses_km=miss,
                                        buys_km=miss[1] - miss[0]),
        ))
        for i, miss in enumerate(cells.values())
    ]
    fake = SimpleNamespace(scenario=scenario, _responses=lambda: rows)
    fake._burn_moves = lambda: decision.ScenarioResult._burn_moves(fake)  # type: ignore[arg-type]
    return decision.ScenarioResult.burn_score_note.fget(fake)  # type: ignore[attr-defined]


class TestTheBurnScoreNote:
    def test_it_reports_the_burn_that_moves_its_score_most_not_the_most_kilometres(self) -> None:
        """K 10 km, weight 0.25. Close pass: 5 km is inside K, so 1; 60 km is ln 833.333 / ln 5,000 = 6.725634 /
        8.517193 = 0.789654; the move is 0.25 x 0.210346 = 0.0526. Far drift: ln 25 / ln 5,000 = 0.377927 and
        ln 8.333333 / ln 5,000 = 0.248939; 0.25 x 0.128988 = 0.0322, though it buys 4,000 km against 55. Either
        burn's 2 m/s adds 0.20 x ln 3 / ln 1,001 = 0.20 x 0.159018 = 0.0318."""
        note = str(_burn_note(10.0, Far_drift=_FAR, Close_pass=_CLOSE))
        assert "the 55.0 km our burn buys against Close pass moves its score by 0.0526" in note
        assert "its 2.00 m/s adds 0.0318" in note
        assert "4000.0 km" not in note

    def test_it_reads_the_scenarios_keep_out_distance(self) -> None:
        """K 1 km: 5 km is ln 10,000 / ln 50,000 = 9.210340 / 10.819778 = 0.851250, 60 km 6.725634 / 10.819778 =
        0.621606; 0.25 x 0.229644 = 0.0574. Far drift: 0.25 x (0.297500 - 0.195962) = 0.0254. At 10 km it was 0.0526."""
        note = str(_burn_note(1.0, Close_pass=_CLOSE, Far_drift=_FAR))
        assert note.startswith("The score values closest approach in orders of magnitude from the 1 km keep-out")
        assert "the 55.0 km our burn buys against Close pass moves its score by 0.0574" in note

    def test_it_states_the_keep_out_distance_as_scored(self) -> None:
        note = str(_burn_note(1234.5678, Close_pass=_CLOSE))
        assert "from the 1234.5678 km keep-out distance" in note


class TestTheSampledCaveat:
    def test_its_spread_reads_the_scenarios_keep_out_distance(self) -> None:
        """The fake band is P5 3 km, P95 20 km, at weight 0.25. K 1 km: ln(50,000 / 3) / ln 50,000 = 9.721166 /
        10.819778 = 0.898462 and ln 2,500 / ln 50,000 = 7.824046 / 10.819778 = 0.723124; 0.25 x 0.175338 =
        0.0438. At the default 10 km, 3 km is inside, so 0.25 x (1 - 0.918618) = 0.0203."""
        from tests.unit.test_decision_sampled import _bound, _Fake

        scenario = _bound()
        scenario.keep_out_km = 1.0
        caveat = str(evaluate_scenario(scenario, sampler=_Fake()).sampled_caveat)
        assert "from the 1 km keep-out distance to 50,000 km" in caveat
        assert caveat.endswith("moves it by at most 0.0438 here.")

    def test_it_and_the_scales_line_state_the_keep_out_distance_as_scored(self) -> None:
        from tests.unit.test_decision_sampled import _bound, _Fake

        scenario = _bound()
        scenario.keep_out_km = 1234.5678
        result = evaluate_scenario(scenario, sampler=_Fake())
        assert "from the 1234.5678 km keep-out distance" in str(result.sampled_caveat)
        assert "keep-out distance of 1234.5678 km" in result.score_scales_line


class TestTheScoreSpreadNote:
    def test_it_points_to_the_burn_note_only_when_one_is_shown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A response given a target separation that needs no burn: its cells are flown in every sample, but there
        is no burn note to point to."""
        from tests.unit.test_decision_response import _avoid, _hold, _sampled_scenario, _sized_stub, _WithBurns

        monkeypatch.setattr(decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(None, 25.0),))
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns())
        assert result.n_burn_cells > 0
        assert result.burn_score_note is None
        note = str(result.score_spread_note)
        assert "burn note" not in note
        assert "lookup figures" not in note
        assert "flown in every sample" in note

    def test_with_a_burn_it_names_both_terms_the_burn_moves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.astro.monte_carlo import BlueBurn
        from tests.unit.test_decision_response import _avoid, _hold, _sampled_scenario, _sized_stub, _WithBurns

        burn = BlueBurn(0.0, (0.00547, 0.0, 0.0))
        monkeypatch.setattr(decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(burn),))
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns())
        assert result.burn_score_note is not None
        note = str(result.score_spread_note)
        assert "delta-V term" in note
        assert "the burn note gives both for the cell whose score the burn moves most" in note


class TestWhatTheNotesSay:
    def test_the_scores_basis_note_reads_as_a_sentence(self) -> None:
        note = decision.LOOKUP_BASES.composite_score.note
        assert "keep-out distance set on the panel, whose default, 10 km, is Claude's choice and unsourced," in note

    def test_a_path_score_says_its_delta_v_is_the_sum_on_the_one_burn_scale(self) -> None:
        from spectre.domain import decision_tree

        note = decision_tree._PATH_SCORE_NOTE
        assert note.startswith("the one-turn score on this sequence's figures: weighted sum of custody")
        assert note.endswith(
            "; here our delta-V is this sequence's burns added up, so burns adding up to 1,000 m/s or more score the "
            "full delta-V term, as one burn at the per-burn limit does"
        )

    def test_the_guide_ties_its_break_even_to_the_default_keep_out_distance(self) -> None:
        path = Path(__file__).resolve().parents[2] / "docs" / "generate_guide.py"
        if not path.exists():
            pytest.skip("docs/generate_guide.py is excluded from the submission package")
        source = " ".join(path.read_text(encoding="utf-8").replace('"\n', "").replace('        "', "").split())
        assert "At the default weights and keep-out distance, a burn of up to about 9 m/s" in source
        assert "The break-even moves with the keep-out distance" in source
