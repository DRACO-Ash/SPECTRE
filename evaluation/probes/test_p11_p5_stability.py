"""P-11 (recast): stability of the sampled P5 miss estimate across seeds and sample sizes.

Property tested: the engine computes no collision probability; a sampled cell scores the P5 of the separation series'
sampled misses (decision.py:2905-2935, closest_approach_km is P5). This probe measures how much that P5 moves from seed
to seed at N of 50, 100, 200 and 400, whether the spread falls roughly as 1/sqrt(N), and whether the engine's own
reported half-width (monte_carlo.py:627-639, percentile_half_width_km: the widest 95 % bootstrap half-width of P5, P50
and P95, 200 resamples, seeded with the hypothesis's seed) brackets the seed-to-seed spread actually observed.

It drives spectre.astro.monte_carlo.run_separation_series exactly as decision.py's _sample does (decision.py:2657-2671:
sampler(row.hypothesis, row.blue_track, row.window)), with the hypothesis built as the engine's own end-to-end test
builds it (tests/unit/test_decision_sampled.py:91-96 and :770-790, D18): AdversaryHypothesis.from_archetype from the
red track's SGP4 state at the scenario epoch, the blue track from elset_state at the window start. Only n_samples and
random_seed are varied, with dataclasses.replace, which the sealed hypothesis allows (decision.py:585-591).

Cases (all from tests/unit/_decision_reference.py, hand-checked reference element sets):
  A. plane_change, Evasive archetype (2 m/s), 1 h window: the engine's own D18 case. 20 seeds.
  B. plane_change, Orbit Raise archetype (50 m/s), 1 h window: a wider band near the 5 % convergence tolerance. 20 seeds.
  C. coplanar_leo, Evasive archetype, 6 h window. 6 seeds (cost).
Horizon reduction: the default decision horizon is 72 h (decision.py:1463); these windows are 1 h and 6 h so the run
stays within about 15 minutes (a 72 h series of 400 samples costs several minutes on its own). The P5 of cases A and B
is set by the first crossing at about 1,411 s, so a longer window would not change it.

Framework reference: decision-engine-evaluation-framework.md section 1g (Monte Carlo sample size and intervals) and
section 2, test programme row "Monte Carlo convergence" ("report estimate and interval versus N; confirm interval
shrinks as 1/sqrt(N)"); evaluation probe 11, recast because no Pc is computed anywhere (01-architecture-map.md
section 2.7). A Pc of zero cannot arise from this engine because no Pc is computed.

Expected result: the seed-to-seed standard deviation of P5 falls roughly as 1/sqrt(N) (log-log slope near -0.5), and
the engine's 95 % half-width is of the order of 1.96 times that standard deviation, so at least about 90 % of runs
fall within their own reported half-width of the pooled P5.

Measured numbers are printed and written to evaluation/evidence/physics/p11_p5_runs.csv (every run) and
p11_p5_summary.csv (per case and N) whether the assertions pass or fail.
"""

from __future__ import annotations

import csv
import dataclasses
import math
import time
from pathlib import Path
from typing import NamedTuple

import numpy as np

from spectre.astro.monte_carlo import (
    BlueTrack,
    ManoeuvreHypothesis,
    SeparationWindow,
    elset_state,
    run_separation_series,
)
from spectre.domain.decision import AdversaryHypothesis, PreManoeuvreState
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, PLANE_CHANGE, ReferenceCase

_EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "physics"
_SIZES = (50, 100, 200, 400)


class _Case(NamedTuple):
    label: str
    ref: ReferenceCase
    archetype: str
    span_s: float
    seeds: tuple[int, ...]


_CASES = (
    _Case("A plane_change Evasive 1 h (D18)", PLANE_CHANGE, "evasive", 3600.0, tuple(range(1, 21))),
    _Case("B plane_change Orbit Raise 1 h", PLANE_CHANGE, "orbit_raise", 3600.0, tuple(range(1, 21))),
    _Case("C coplanar_leo Evasive 6 h", COPLANAR_LEO, "evasive", 6 * 3600.0, tuple(range(1, 7))),
)


def _inputs(case: _Case) -> tuple[ManoeuvreHypothesis, BlueTrack, SeparationWindow]:
    red = elset_state(case.ref.red_tle, EPOCH)
    blue = elset_state(case.ref.blue_tle, EPOCH)
    assert red is not None and blue is not None
    carried = AdversaryHypothesis.from_archetype(case.archetype, PreManoeuvreState(EPOCH, tuple(red.state_eci_km)))
    return carried.hypothesis, blue, SeparationWindow(EPOCH, case.span_s)


def _run_case(case: _Case) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    base, blue, window = _inputs(case)
    runs: list[dict[str, object]] = []
    pooled: list[float] = []
    for n in _SIZES:
        for seed in case.seeds:
            hypothesis = dataclasses.replace(base, n_samples=n, random_seed=seed)
            t0 = time.monotonic()
            series = run_separation_series(hypothesis, blue, window)   # as decision._sample calls it
            runs.append({
                "case": case.label, "n": n, "seed": seed, "p5_km": series.miss_km_p5, "p50_km": series.miss_km_p50,
                "p95_km": series.miss_km_p95, "half_width_km": series.percentile_half_width_km,
                "tolerance_km": series.tolerance_km, "converged": series.converged, "n_failed": series.n_failed,
                "wall_s": round(time.monotonic() - t0, 2),
            })
            if n == max(_SIZES):
                pooled += [a.miss_km for a in series.approaches]
    reference_p5 = float(np.percentile(pooled, 5.0))
    summary = []
    for n in _SIZES:
        at = [r for r in runs if r["n"] == n]
        p5 = np.array([r["p5_km"] for r in at], dtype=float)
        hw = np.array([r["half_width_km"] for r in at], dtype=float)
        sd = float(np.std(p5, ddof=1))
        covered = sum(abs(r["p5_km"] - reference_p5) <= r["half_width_km"] for r in at)
        summary.append({
            "case": case.label, "n": n, "seeds": len(at), "mean_p5_km": float(np.mean(p5)), "sd_p5_km": sd,
            "min_p5_km": float(np.min(p5)), "max_p5_km": float(np.max(p5)),
            "mean_half_width_km": float(np.mean(hw)), "ratio_mean_hw_to_1.96sd": float(np.mean(hw)) / (1.96 * sd),
            "pooled_p5_km_at_n400": reference_p5, "pooled_samples": len(pooled),
            "runs_within_own_half_width_of_pooled": covered, "converged_runs": sum(bool(r["converged"]) for r in at),
        })
    sds = np.array([s["sd_p5_km"] for s in summary])
    slope = float(np.polyfit(np.log(_SIZES), np.log(sds), 1)[0])
    for s in summary:
        s["loglog_slope_sd_vs_n"] = slope
        s["sd_ratio_to_n50"] = s["sd_p5_km"] / summary[0]["sd_p5_km"]
        s["sqrt_rule_ratio"] = math.sqrt(_SIZES[0] / int(s["n"]))
    return runs, summary


def _write(name: str, rows: list[dict[str, object]]) -> None:
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (_EVIDENCE / name).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_p11_p5_stability_across_seeds_and_n() -> None:
    t0 = time.monotonic()
    all_runs: list[dict[str, object]] = []
    all_summary: list[dict[str, object]] = []
    for case in _CASES:
        runs, summary = _run_case(case)
        all_runs += runs
        all_summary += summary
        _write("p11_p5_runs.csv", all_runs)
        _write("p11_p5_summary.csv", all_summary)
    print(f"\nP-11 no collision probability is computed by the engine, so a Pc of zero cannot arise; P5 of sampled "
          f"misses is measured instead. Total wall time {time.monotonic() - t0:.0f} s.")
    for s in all_summary:
        print(
            f"P-11 {s['case']} N={s['n']}: seeds {s['seeds']}, P5 mean {s['mean_p5_km']:.3f} km, SD {s['sd_p5_km']:.3f} km "
            f"(range {s['min_p5_km']:.3f} to {s['max_p5_km']:.3f}); SD/SD(N=50) {s['sd_ratio_to_n50']:.2f} against "
            f"1/sqrt rule {s['sqrt_rule_ratio']:.2f}; log-log slope {s['loglog_slope_sd_vs_n']:.2f}; engine half-width "
            f"mean {s['mean_half_width_km']:.3f} km = {s['ratio_mean_hw_to_1.96sd']:.2f} x 1.96 SD; runs within own "
            f"half-width of pooled P5 ({s['pooled_p5_km_at_n400']:.3f} km from {s['pooled_samples']} samples) "
            f"{s['runs_within_own_half_width_of_pooled']}/{s['seeds']}; converged flag {s['converged_runs']}/{s['seeds']}"
        )
    problems = []
    for case in _CASES:
        rows = [s for s in all_summary if s["case"] == case.label]
        slope = float(rows[0]["loglog_slope_sd_vs_n"])
        if not -0.8 <= slope <= -0.3:
            problems.append(f"{case.label}: log-log slope {slope:.2f} outside -0.8 to -0.3")
        covered = sum(int(s["runs_within_own_half_width_of_pooled"]) for s in rows)
        total = sum(int(s["seeds"]) for s in rows)
        if covered < 0.9 * total:
            problems.append(f"{case.label}: only {covered}/{total} runs within their own half-width of the pooled P5")
    print("P-11 expectation violations: " + ("; ".join(problems) if problems else "none"))
    assert not problems, problems
