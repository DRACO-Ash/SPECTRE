# SPECTRE remediation log

Running record of fixes made against `audit/FINDINGS.md`, in the sequence set by `audit/REMEDIATION.md`. The audit artefacts themselves describe the tree at `a34e273` and are not rewritten. This log is the delta.

**Method, for every row.** Every row followed the same five steps:
1. A test reproducing the defect was written first and seen to fail.
2. The fix was applied.
3. The new test passed.
4. ruff and mypy strict on `spectre/` were clean, and the full suite was green.
5. The change was committed on its own.

The "Gate" column names the test that now fails if the defect returns.

## Step 1: Blockers (8 of 8 closed)

| Finding | Origin | Commit | Defect, as reproduced before the fix | Gate |
|---|---|---|---|---|
| F-008 | F-S08-01 | `36c93ae` | 10 wrong passwords, then the correct one: 302 with a session cookie | `tests/integration/test_login_hardening.py::TestFailedLoginRateLimit::test_a_locked_account_refuses_even_the_correct_password` |
| F-007 | F-S06-01 | `c369ee9` | a 48 h coast produced a 48-day GEO drift | `tests/unit/test_maneuver_route_units.py` (3 tests) |
| F-005 | F-S02-03 | `bbc9722` | drift +18.85 km/orbit where the CW solution gives -37.70 | `tests/unit/test_relative_motion_stability.py::TestSecularDrift` (4 cases, rel 1e-9 against `_cw_propagate`) |
| F-006 | F-S02-04 | `bbc9722` | a bounded 2:1 relative orbit scored below 100 | `tests/unit/test_relative_motion_stability.py::TestStabilityInterceptFrame` |
| F-001 | F-S01-01 | `e361b93` | a 0.1 deg trim priced at 754.3 m/s instead of 13.2 m/s | `tests/unit/test_manoeuvre_detect_units.py`; the static guard in `tests/unit/test_orbital_units_and_degeneracies.py` now matches any `<alias>.degrees(` across `spectre/` and was shown to fail on the original lines |
| F-002 | F-S01-02 | `42d42a6` | 0.0000 km/s to align planes 8 deg apart; the burn was 866 km off the target plane | `tests/unit/test_plane_change_intercept.py` (2 tests) |
| F-003 | F-S01-03 | `5398c10` | 14.64 km/s departure for a 10 deg hop at 98 deg and 135 deg inclination | `tests/unit/test_lambert_direction.py` (4 tests); the Curtis Ex. 5.2 suite is unchanged and passes |
| F-004 | F-S02-01 | `2e5cbda` | cheaper than Hohmann; the arc missed the target by 5,157 km; an impossible budget was answered | `tests/unit/test_min_time_intercept.py` (4 tests) |

Also closed in passing, because the fix touched the same lines:
● **F-S01-13** (Medium): the `solve_lambert` docstring no longer credits Izzo, in `5398c10`.
● The `prograde (short-way)` docstring error cited inside F-003, in `5398c10`.

**Behaviour changes an operator will see, inference:**
● Plane-change plans now depart at the next crossing of the target plane, not immediately.
● Minimum-time intercepts are two-burn Lambert plans, and are refused rather than answered when no single-revolution transfer fits the budget.
● Retrograde-orbit Lambert costs drop from about 15 km/s to realistic values.
● Manoeuvre detection stops classifying TLE noise as plane changes.

Suite after step 1: 1,913 passed, 2 skipped, 0 failed (from 1,896 and 2 at audit).

## Step 2: make CI execute its checks

| Finding | Origin | Change | Proof |
|---|---|---|---|
| F-S00-01 (High) | orchestrator | Lint, test and quality jobs install the hash-locked sets (`requirements.txt`, `requirements-dev.txt`, then `-e .` without deps) instead of the undefined `.[dev]` extra, and confirm `ruff`, `mypy` and `pytest` are present before any gated step | In a fresh Python 3.12 environment built exactly as the new steps do, every CI job except the Docker-only container job was run locally: lint clean; mypy clean; bandit `-ll` clean; tests 1,917 passed with coverage 84.43 % against the floor of 74; `check-quality.sh master` passed all five legs (changed-line coverage 97 %); gitleaks clean on history and tree |
| F-S00-08 (Medium) | orchestrator | `requirements-dev.in` is constrained with `-c requirements.txt`; the dev lock was recompiled with uv for Python 3.11, keeping existing pins as preferences. Four dev pins moved: tomli 2.4.1 to 2.5.0, urllib3 2.7.0 to 2.8.0, filelock 3.32.4 to 4.2.4, setuptools 84.0.0 to 84.2.1 | The combined `--require-hashes` install succeeds; `pip-audit` reports no known vulnerabilities in any of the three locks |
| F-S00-10 (Low) | orchestrator | CI no longer passes `--cov-fail-under=70`; `pyproject.toml`'s ratchet (74) governs | contract test below |
| F-S00-11 (Low) | orchestrator | The orphan `SPECTRE-1` gitlink is removed from the index. It pointed at this repository's own commit `7a63ce5`, so nothing is lost | contract test below |
| F-S10-25 (Low) | F-S10-25 | The SCA job now audits `requirements-dev.txt` as well as `requirements.txt` | the advisories it would have shown are the ones lifted above |

**Gate.** `tests/unit/test_deployment_contract.py::TestContinuousIntegrationCanRun`, 4 tests:
● CI installs locked sets, never an undeclared extra;
● the two locks agree on every shared package;
● CI does not override the coverage ratchet;
● no gitlink is tracked.
Each was shown to fail against the original `master` file it guards.

**Also in this step, from my own step 1 work:**
● The full-history gitleaks scan found the throwaway key I committed in the audit probe (`e31b72e`). It is fingerprinted in a new `.gitleaksignore` with its reason. History is not rewritten on a pushed branch.
● The quality gate's complexity leg flagged `solve_lambert` at 17 after the F-003 change. The arc decision now sits in `_takes_long_way`.
● The house rules flagged three unnamed tolerances in the new plane-crossing helpers. They are now named constants.

**Not done here, and why:**
● **Branch protection on `master`.** Requiring all seven jobs is a GitHub repository setting, and a human must enable it. Without it, a red CI still does not block a merge.
● **Enabling ruff `BLE`/`RUF100` (F-S00-12).** That would turn CI red on 32 existing broad exception handlers, each of which needs a decision. It is scheduled with the step 3 error-handling findings.
● **The container job.** It was not run, because there is no Docker daemon in this environment. Nothing the image installs changed.

**Status on GitHub.** CI runs only on pushes and pull requests to `master` (`ci.yml:6-10`), so this branch's push does not exercise it. The proof above is the local reproduction. The first real run will be the pull request or merge into `master`.

## Step 3: single-location fixes and the rulings

### Decision Engine relabelled (ruling: relabel)

| Finding | Origin | Change | Gate |
|---|---|---|---|
| F-034 (High) | F-S05-02 | `OutcomeMetrics.modelled` and `ScenarioResult.modelled` and `.basis` mark every Phase 1 figure as a lookup estimate; the results banner reads "Modelled Recommendation" with "Modelled estimate, not a computed solution." and the basis text; each matrix cell marks its closest approach "(model)"; the session log says "Modelled recommendation" | `tests/unit/test_decision_labelling.py::TestTheResultSaysItIsModelled`, `::TestTheOperatorIsTold` |
| F-110 (Medium) | F-S05-01 | The selector labelled "Maximin" computed minimin, the optimistic rule. It is renamed `MINIMIN`, value `minimin`, and offered as "Minimin: optimistic, best best case (not robust)"; Minimax is offered as "cautious, best worst case" | `::TestTheSelectorsDoWhatTheirNamesSay` (a 2x2 matrix on which the three rules choose differently); the three type-only selector tests are removed (F-S00-14) |
| F-S09-13 (complexity part) | F-S09-13 | `decision_evaluate` (cognitive complexity 44) is decomposed into row builders, strategy and weight helpers. Proof of no behaviour change: the rendered result for five forms (short rows, a bad type, unnormalised and all-zero weights, every strategy and an unknown one) is byte-identical before and after, computation time masked | the quality gate's complexity leg; new route test `test_decision_evaluate_fills_short_rows_and_labels_the_result` |

**Prior P2 status after this change:** the July 2026 agreed remediation, a "modelled estimate, not a computed solution" banner, is now implemented in all three layers: code, payload and rendered page. The constants themselves remain uncited; F-S05-03, where custody loss is scaled by reversibility, is still open in step 3.

### Rulings recorded

● **NOTSO marking (`U//DS-JCO-NOTIF`):** acceptable to hold, and the ruling expressly covers a public repository. Ruled by the Technical Director, 24 October 2026. No change made.
● **UDL-sourced object names (F-038):** the reply restated the question rather than choosing, so the names are treated as **untrusted**, the safer reading. The fix is identical under either ruling; only the priority would differ. Open for correction.

### Solver and screening fixes

| Finding | Origin | Commit | Defect, as reproduced before the fix | Gate |
|---|---|---|---|---|
| F-011 (High) | F-S01-05 | `5141687` | Hohmann reported a 0 km miss for a pair arriving 20,771 km apart | `tests/unit/test_transfer_intercept_burns.py::TestHohmannIntercept` (5 tests, incl. lead-angle phasing meets the target) |
| F-013 (High) | F-S01-07 | `5141687` | both Hohmann burns prograde for a lowering transfer | `::test_lowering_burns_are_retrograde`, `::test_the_second_burn_circularises_at_the_target_radius` |
| F-012 (High) | F-S01-06 | `5141687` | bi-elliptic burn 2 pointed along the departure velocity, burn 3 prograde; the arc did not end on the target circle | `::TestBiellipticIntercept` (4 tests) |
| F-014 (High) | F-S01-09 | `0b2ef36` | evasion reported 10.0 km against two different threats, whose achieved misses were 10.29 and 14.21 km | `tests/unit/test_evasion_against_threat.py` (5 tests) |
| F-015 (High) | F-S01-10 | `45add79` | combined plane change: fixed 36.9 deg tilt on burn 1; the arc did not end in the target plane | `tests/unit/test_combined_plane_change.py` (6 tests) |
| F-016 (High) | F-S01-12 | `ea7e6ba` | Molniya classified GTO and Tundra MEO, so Tundra was dropped from GEO screening | `tests/unit/test_orbit_regime_reference.py` (8 tests) |
| F-038 (High) | F-S06-03 | `ae46457`, `570f364` | a name `x');alert(1);//` reached onclick source in three Load buttons | `tests/unit/test_handler_attribute_injection.py` (template-wide gate and a render test); Chromium check: the handler receives the exact name and no script runs |

**Notes, fact unless marked:**
● `spectre/astro/kepler.py` is new: a universal-variable two-body propagator (Curtis Algorithms 3.3 and 3.4), checked against scipy integration to 1 m. The Hohmann, bi-elliptic, combined plane change and evasion fixes all use it.
● Evasion now flies each `optimal_evasion` candidate and its reverse against the threat. The burn's displacement comes from two two-body coasts from the same state, so propagator model error cancels. The candidate sizing itself is still the Clohessy-Wiltshire heuristic (F-S06-07, step 4).
● Regenerating `spectre/data/hrr_default.json` with its build script moved two synthetic Molniya-type entries from GTO to HEO. Both labels are trans-belt, so screening of those two is unchanged.
● F-038 converted nine handler sites in total, so the gate covers the whole template tree without an allowlist. Three carried names; six carried server-generated keys and dates.
● **Behaviour changes an operator will see (inference):** Hohmann and bi-elliptic plans now show a real, often large, miss when the pair is not phased; combined plane changes depart at the next crossing of the target plane, not immediately; evasion burns may point the other way to the old ones.
