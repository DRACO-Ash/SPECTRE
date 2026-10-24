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

### Solver fixes, second batch (all step 3 High solver findings now closed)

| Finding | Origin | Commit | Defect, as reproduced before the fix | Gate |
|---|---|---|---|---|
| F-010 (High) | F-S01-04 | `accb129` | a 30 deg GEO hop in 24 h priced at 7,820 m/s on the zero-revolution arc; once round costs 214 m/s. The envelope sweep found 11 of 24 one-degree arrivals feasible | `tests/unit/test_lambert_multi_revolution.py` (8 tests, incl. a root beside the band edge, mutation-checked); `tests/unit/test_intercept_envelope.py` re-derived: 23 of 24 feasible, cheapest 3.4 m/s at 46 h |
| F-017 (High) | F-S02-06 | `64016fd` | a radial burn from wherever red was, labelled with the along-track cost and a positive margin | `tests/unit/test_nmc_intercept_burn.py` (4 tests: the burn is flown through the CW solution and the margin is the closest approach) |
| F-024 (High) | F-S02-15 | `b190aff` | a fixed 50 km step by inclination alone; the cost was one Hohmann burn | `tests/unit/test_j2_drift_acceleration.py` (6 tests, both signs, two inclinations) |
| F-026 (High) | F-S03-01 | `7074ea0` | a burn 100 times its predecessors read NORMAL at n = 2 and 5, CAUTION at 10 | `tests/unit/test_pol_status_leave_one_out.py` (15 tests) |
| F-027 (High) | F-S03-02 | `4e43187` | a notified burn bracketed by element sets a day before and three days after was split into notso_only and manoeuvre_only | `tests/unit/test_notso_burn_epoch.py` (3 tests) |
| F-028 (High) | F-S03-06 | `658a097` | the earliest cluster's representative was written, so a just-manoeuvred object was cached with its pre-burn orbit; the existing multi-cluster test never formed a cluster | `tests/integration/test_tle_clustering_pipeline.py::test_the_newest_cluster_supplies_the_representative`, and the vacuous test made unconditional |
| F-029 (High) | F-S04-01 | `590312c` | with no ΔV dispersion, a 30 s timing sigma gave a 643 km three-sigma cloud; now 0.33 km | `tests/unit/test_monte_carlo_burn_timing.py` (2 tests) |
| F-030 (High) | F-S04-02 | `6ad566b` | a detected plane change simulated as an orbit raise | `tests/unit/test_monte_carlo_direction.py` (4 tests) |
| F-031 (High) | F-S04-03 | `226c90b` | drag 25.0 times too strong (B* to ballistic coefficient) | `tests/unit/test_monte_carlo_drag.py` (2 tests; 48 h decay at 450 km agrees with the analytic estimate to 0.5 per cent) |

**Tests changed because their expectations encoded a defect, each re-derived and stated in the test:**
● `test_intercept_envelope.py`: the feasible counts and cheapest arc were the zero-revolution figures (F-010).
● `test_orbital_units_and_degeneracies.py`: pinned the 14.4 m/s cost of the fixed 50 km step (F-024). For its pair no altitude halves the 46.8-day convergence, so the inclination-units guard now pins that time; mutation-checked (the mutant gives 181.3 days).
● `test_tle_clustering_pipeline.py`: the multi-cluster test's data formed no cluster, so its guarded assertions never ran (F-028).

**Density table (corrected below: this is audit F-105, not a new defect, and is now fixed in `e93c664`):** the Monte Carlo density table (`monte_carlo.py:_atmo_density_kg_m3`) is discontinuous at most band edges. Density jumps by 0.63 at 86 km, 24.9 at 150, 1.13 at 200, 2.22 at 300, 2.74 at 400, 1.40 at 500, 0.77 at 700 and 10.1 at 1,000 km. Inference: the (rho0, H) pairs are misaligned between rows; the scale heights look shifted against the base densities. A satellite near a band edge sees its drag change in steps as it crosses. Fixing it means re-sourcing the table, which I have not done from memory.

**Left from these findings for step 4:** comparing RAAN at a common epoch in `tle_clustering` (F-028's second half). `nmc_safety_ellipse` is no longer used by the wrapper and remains as a tested library function.

**Behaviour changes an operator will see (inference):**
● Long-flight Lambert intercepts are priced on the cheapest revolution count, often orders of magnitude cheaper.
● NMC refuses unless red already sits on the requested ellipse.
● J2 drift may offer no burn where none helps.
● PoL shows INSUFFICIENT until three earlier manoeuvres exist.
● Notified burns with late element sets now match.
● The Monte Carlo panel shows the ΔV direction basis, with much smaller drag-driven and timing-driven spreads.

### Medium solver findings

| Finding | Origin | Commit | Defect, as reproduced before the fix | Gate |
|---|---|---|---|---|
| F-067 | F-S01-11 | `42d42a6` (step 1) | closed by the F-002 rebuild: the plane-change burn is at the next crossing of the target plane and rotates the velocity into it | `tests/unit/test_plane_change_intercept.py::test_the_burn_is_at_the_line_of_nodes_and_lands_in_the_blue_plane` |
| F-071 | F-S02-05 | `c3ddedb` | an along-track kick from the origin, which reaches 4v/n radially, reported 0 | `tests/unit/test_relative_motion_radial_extent.py` (5 tests, against the CW solution) |
| F-073 | F-S02-14 | `102d501` | a RAAN-only change priced 1.28x high at 51.6 deg and 5.8x at 10 deg | `tests/unit/test_classify_raan_cost.py` |
| F-074 | F-S02-16 | `a5bc0d7` | circular speed at a used as the node speed; "apogee" offered for a circular orbit | `tests/unit/test_plane_change_nodes.py` (Curtis eq. 6.20 at each node) |
| F-075 | F-S02-17 | `0fa8ea9` | docstring claimed the plane change was split across both burns; the code makes it at one. Docstring corrected; the split is deliberately not implemented because the F-015 intercept flies the single-burn geometry | `tests/unit/test_combined_plane_change_split.py` |
| F-077 | F-S02-20 | `f0cb83a` | H-bar hops claimed n_hops x d of held advance at a time the satellite is back on the plane; now described and timed as a growing oscillation | `tests/unit/test_hbar_hop_oscillation.py` (flown through the CW solution) |
| F-078 | F-S02-23 | `06034a7` | slot displacement up to 4x short for a radial burn; unread r_threat removed | `tests/unit/test_formation_slot_displacement.py` |
| F-083 | F-S03-03 | `ace4090` | one corrupt epoch ("XX") ended the whole PoL parse; now dropped and counted on the panel | `tests/unit/test_pol_malformed_pair.py` |
| F-084 | F-S03-04 | `b21b410` | _LONG_GAP_WARN_DAYS never read; long-gap detections now flagged in the table | `tests/unit/test_pol_long_gap_flag.py` |
| F-085 | F-S03-05 | `88554c8` | twelve sets ten minutes apart chained into one 110-minute cluster, losing the pre-step orbit | `tests/unit/test_tle_filter_cluster_span.py` |
| F-086 | F-S03-07 | `4f8ee97` | "PREDICTED DV: 1.5 m/s" lost | `tests/unit/test_notso_delta_v_field.py` |
| F-087 | F-S03-08 | `02f8c67` | inferred dates replaced silently; fractional seconds and offsets rejected. Now flagged per field and shown | `tests/unit/test_notso_date_provenance.py` |
| F-088 | F-S03-09 | `17c1dbe` | SATNO above MSGID split one message in two and dropped the half with the window | `tests/unit/test_notso_msgid_split.py` |
| F-089 | F-S03-10 | `841751c` | a pasted message without a SATNO vanished without trace; "n of m parsed" and reasons now shown | `tests/integration/test_notso_rejects_shown.py` |
| F-090 | F-S03-11 | `0fb4ea1` | a stray five-digit number taken as the object; the existing fallback test asserted the defect and now asserts the refusal | `tests/unit/test_notso_norad_label.py` |
| F-091 | F-S03-12 | `34ae31a` | "lead time" was the window offset, negative for a timely notice; now burn minus issue date. The profile fixture's -2 h was the offset; it is now the 14 h lead | `tests/unit/test_notso_lead_time.py` |
| F-092 | F-S03-13 | `299c884` | an early wide notice claimed a burn a later notice fits exactly | `tests/unit/test_notso_assignment.py` |
| F-093 | F-S03-14 | `c79d336` | GEO drift from mean motion alone read 0.00004 deg/day for sets SGP4 moves 0.0107 east; now measured from SGP4 over one sidereal day | `tests/unit/test_geo_drift_rate.py` |
| F-094 | F-S03-15 | `05f3469` | next-burn band 2s from three intervals (t = 4.30); now a 95% prediction interval on burn epochs | `tests/unit/test_pol_next_manoeuvre.py` |
| F-095 | F-S03-16 | `85a4f3c` | module header advertised a replaced method and moved functions | `tests/unit/test_pol_module_header.py` |
| F-101 | F-S04-08 | `283066c` | Welch p = 0.14 where scipy gives 9e-6 for 3,000 per group at 0.05 mag | `tests/unit/test_photometry_statistics.py` |
| F-102 | F-S04-09 | `ba39a73` | "covariance" was res_var / diag(X^T X) | `tests/unit/test_photometry_fit_covariance.py` (against numpy) |
| F-105 | F-S04-13 | `e93c664` | density table misaligned, discontinuous at most band edges | `tests/unit/test_atmosphere_table.py` (Vallado Table 8-4; continuity at every edge) |
| F-108 | F-S04-23 | `8b7c127` | an empty window read as "no significant change" | `tests/unit/test_photometry_empty_window.py` |

**Supporting commits:** `fd42da8` and `60d065c` bring touched functions under the complexity limit (`_parse_single_notso` 19, `classify_manoeuvre` 31, `_fit_least_squares_quadratic` 19); `classify_manoeuvre`'s output is byte-identical over 1,440 inputs.

**Notes (fact unless marked):**
● F-093: no real station-kept GEO element set is in the repository, so the gate checks the field against the same SGP4 measurement taken through the propagator's public API. Inference: the bundled bootstrap GEO sets, generated at exactly sidereal mean motion without J2, really do drift about 0.011 deg/day east under SGP4.
● F-105: Table 8-4 was transcribed from Vallado. Two checks support it: it agrees with the audit's independent hand values at 550 and 700 km, and every band edge is continuous to within 0.1 per cent, as the published fit is.
● F-078: the formation wrapper never used the threat's state. Its docstring now says so; modelling the threat is left for step 4, alongside F-S06-07.
● Already in the audit and not touched here: the NOTSO cache reads keys the bundled UDL records do not carry (FINDINGS.md:829). I checked that F-090 caused no regression there: the cache path parses 0 of 500 records both before and after.
● **Process:** two commits were initially made with a test failing (`ae46457`, then the F-075 docstring commit before amendment), because the commit command was not gated on the test exit code. Neither was pushed in that state. Every commit since goes through a helper that runs ruff, mypy and the full suite and commits only on a clean exit.

### Test-only astro findings

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-070 | F-S01-21 | `adb7ee0` | Hohmann pinned to Vallado Ex. 6-1 at 1e-5; bi-elliptic to a vis-viva closed form; SGP4 to SGP4-VER 00005 at epoch (1 m); coplanar Lambert to the exact circular velocity; the reference propagator's Stumpff functions are its own. Vallado Ex. 6-2 not pinned: its inputs could not be confirmed (my recollection gave 3.907163 against the published 3.904057, so the inputs, not the code, are in doubt) |
| F-081 | F-S02-27 | `adb7ee0` | the CW test's false premise replaced by flying both solvers' burns through the CW solution at five times (1e-9 km) |
| F-099 | F-S03-34 | `adb7ee0` | GMST pinned to Vallado Ex. 3-5 and Meeus Ex. 12.a (1e-4 deg; the code omits the T^2 term, 6e-6 deg here); J2 RAAN rate to -5.00 deg/day; TLE epoch exact |
| F-106 | F-S04-15 | `c79adee` | claim-correction half: the docstring's 0.1% and 0.4% accuracy claims replaced by the 1% the tests pin, with the fixture's two-burn geometry stated. Single-impulse fixtures (a propagated state plus a ΔV vector, refitted to mean elements) are left for step 4 |

All new reference pins passed against the existing code; these findings were about the tests' power, not the code's correctness.

**Step 3 astro group: complete.** Every High and Medium finding whose blast radius was "astro solvers" or astro "tests only" is closed or, where noted, split with its remainder named for step 4.
