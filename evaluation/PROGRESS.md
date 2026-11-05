# Evaluation progress

**Subject:** the decision-analysis engine at commit `ddba577829b6de0a924d76c82077931cd2ba69f8` (version 0.24.2).
**Yardstick:** `evaluation/framework/decision-engine-evaluation-framework.md`. The brief named `docs/evaluation/decision-engine-evaluation-framework.md`, which does not exist; the owner chose (2026-11-05) to copy the uploaded framework into `evaluation/framework/`, byte-identical (sha256 `a0f1e18b3bc1f163de77cc0dfe479c187461099709f8fddd3f3f509489d3f99a`).
**Write scope:** `evaluation/` only. No engine file is changed.
**Held back:** a separate V0.25 build is running in git worktrees under `.claude/worktrees/` (ignored by git). It will not be merged into the working tree until this evaluation ends, so the evaluated code stays at `ddba577`.

## Phase 0: Orient (complete)

● Framework read in full.
● Inventory: Python 3.13.17; 559 Python files tracked; engine and supporting modules listed in `01-architecture-map.md` section 1. Pins in `requirements-runtime.txt` match installed versions (sgp4 2.27, scipy 1.17.1, numpy 2.4.6, FastAPI 0.162.0). Tests: `tests/unit` (271 files), `tests/integration` (74 files), `tests/reference`. Data: `spectre/data/hrr_default.json` (bundled element sets), `notso_cache.json`, `adversary_intel.json`. Configuration: weights and rule are per-evaluation form inputs; constants in `decision.py`.
● Baseline: `PYTHONPATH=. python -m pytest -p no:cacheprovider -q -rfEs tests`, serial (no pytest-xdist installed). Log: `evidence/baseline-tests.log`. Result: 8,351 passed, 0 failed, 15 skipped (3 PostgreSQL-only, 12 training slots with no longitude), exit 0. A clean baseline: no finding.

## Phase 1: Architecture map (checkpoint, awaiting confirmation)

● Written: `01-architecture-map.md`.
● Key facts established:
  ■ Additive weighted cost on fixed reference scales; three rules (minimax, minimin, expected value), one chosen by the operator per evaluation.
  ■ No vetoes or hard constraints; no durable decision record; no record of the operator's decision.
  ■ No collision probability computed; payoffs use miss distance (P5 where sampled).
  ■ Value of information is band steps per hour on two hypothetical outcomes, not EVPI or EVSI; decide-by is a hard cut-off.
  ■ Bayesian update: one observation, a 0 or 1 likelihood from the custody rule.
  ■ Monte Carlo samples burn dispersions only; element-set error is not sampled.
  ■ SGP4 verification vectors are installed locally with the sgp4 library.

## Open questions for the checkpoint

● Confirm the map before Phase 2.
● Framework deviations already visible: probe 11 (Pc) recast to the P5 miss estimate; framework 1f (EVPI and EVSI) assessed against the range-narrowing measure actually built; framework 1e's correlated-observation concern is out of scope by construction.
