# Evaluation progress

**Subject:** the decision-analysis engine at commit `ddba577829b6de0a924d76c82077931cd2ba69f8` (version 0.24.2).
**Yardstick:** `evaluation/framework/decision-engine-evaluation-framework.md`. The brief named `docs/evaluation/decision-engine-evaluation-framework.md`, which does not exist; the owner chose (2026-11-05) to copy the uploaded framework into `evaluation/framework/`, byte-identical (sha256 `a0f1e18b3bc1f163de77cc0dfe479c187461099709f8fddd3f3f509489d3f99a`).
**Write scope:** `evaluation/` only. No engine file is changed.
**Held back:** a separate V0.25 build is running in git worktrees under `.claude/worktrees/` (ignored by git). It will not be merged into the working tree until this evaluation ends, so the evaluated code stays at `ddba577`.

## Phase 0: Orient (complete)

● Framework read in full.
● Inventory: Python 3.13.17; 559 Python files tracked; engine and supporting modules listed in `01-architecture-map.md` section 1. Pins in `requirements-runtime.txt` match installed versions (sgp4 2.27, scipy 1.17.1, numpy 2.4.6, FastAPI 0.162.0). Tests: `tests/unit` (271 files), `tests/integration` (74 files), `tests/reference`. Data: `spectre/data/hrr_default.json` (bundled element sets), `notso_cache.json`, `adversary_intel.json`. Configuration: weights and rule are per-evaluation form inputs; constants in `decision.py`.
● Baseline: `PYTHONPATH=. python -m pytest -p no:cacheprovider -q -rfEs tests`, serial (no pytest-xdist installed). Log: `evidence/baseline-tests.log`. Result: 8,351 passed, 0 failed, 15 skipped (3 PostgreSQL-only, 12 training slots with no longitude), exit 0. A clean baseline: no finding.

## Phase 1: Architecture map (complete; confirmed by the owner, 2026-11-06)

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

## Phase 2: Gate assessment (complete)

● Written: `02-gate-assessment.md`.
● Result: 9 Red, 0 Amber, 1 Green (G6, provisional). Gate result: **Fail**.
● Rating rule: "substantially met, no dated and owned plan" is rated Red and labelled, since the framework leaves that case undefined and the repository holds no dated, owned plan (deviation, to record in the report).
● Re-check in Phase 4: G2 (probe 15), G6 (probe 14 and a rendered page), G7 (probes 12 and 13), G10 (probe 14), G9 (UDL element-set checksum, probe 14).
● Open: whether operators can record a decision anywhere outside the engine (none found in code).

## Phase 3: Conceptual scrutiny (complete)

● Written: `03-conceptual-scrutiny.md`, sections 1a to 1h as evidenced questions; findings F-10 to F-23 (F-17 and F-18 reserved for Phase 4 and L5 findings).
● Most material: F-10 (Critical), the closest-approach term is nearly flat at operational ranges; F-11 (High), element-set error never reaches the miss payoff; F-12 (High), expected-value shares renormalise over the rows entered; F-14 (High), collect-first is not tied to the matrix; F-16 (High), no weight sensitivity.
● Deviations: rank reversal does not apply to responses (fixed scales) but an adversary-side analogue does; no Pc anywhere (probe 11 recast); no EVPI or EVSI (probe 10 recast); single-observation update (framework 1e double-counting not applicable).
● Probes added beyond the brief's list: P-03b (adding a row with P 0 under expected value) and P-17 (closest-approach insensitivity).

## Phase 4: Probe testing (complete)

● Probes: `probes/test_p01_p05_rules.py`, `test_p06_p10_model.py`, `test_p15_p18_reproducibility_sensitivity.py` (lead assessor; 38 passed, of which 6 assert a confirmed weakness), `test_p11_*.py` to `test_p14_*.py` (delegated; 8 passed, 8 failed). Raw output: `evidence/probes.log`; physics detail: `evidence/physics/`.
● Summary table: `04-test-evidence.md`. Gate file revised with probe results; no rating changed.
● New from the physics probes: F-25 (UDL element sets never checksum-checked; a one-digit corruption moved a computed miss from 10.4 to 13.4 km), F-26 (half-width labelled as P5's is the widest of three), F-27 (unstated RK45 error up to 0.65 km at 72 h), F-29 (deep-space objects silently take LEO limits), F-30 (decayed object can yield a computed miss), F-31 (zero weights or zero P give a pick by row order), F-32 to F-36 (Low).
