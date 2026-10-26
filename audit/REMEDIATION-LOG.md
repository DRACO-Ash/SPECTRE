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
● **Intelligence data marking (F-146):** keep `UNCLASS // PAIR`. Ruled by the Technical Director, 24 October 2026. Recorded in the file's `_meta` block.
● **UDL-sourced object names (F-038):** the reply restated the question rather than choosing, so the names are treated as **untrusted**, the safer reading. The fix is identical under either ruling; only the priority would differ. Open for correction.
● **Test naming (F-188):** drop the `test_should_` convention. Ruled by the Technical Director, 26 October 2026. Recorded under the Low findings.

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

### Web routes and operator UI, first batch

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-037 | | `4a4d4ca` | EVASION gets the operator's ΔV budget; the coast time in hours had been read as km/s |
| F-049 | | `df14686` | a training attempt is claimed with a conditional UPDATE and scored once; resubmission returns 409 |
| F-045 | | `427210f` | PoL analysis held to the UDL data and auth rate limits |
| F-051 | | `396f2fc` | training scenario objects are tagged and removed from the operational lists on leaving training |
| F-040 | | `eac0d7c` | orbital-event search bounded to 7 days with an early exit, and run off the event loop |
| F-042 | | `a428a84` | 16 route tests for the threat sweep; threat.py coverage 48% to 78%, with a CI per-file floor of 75. Found and fixed: refine looked manual targets up in the HRR cache |
| F-050 | | `3360824` | the training Reset button posts to /reset; a nested form had made it submit the score (Chromium-checked) |
| F-043 | | `d7ad98d` | Add TLE clears its fields after the request, not before (Chromium-checked) |
| F-039 | F-S06-04 | `0e838c6` | sweep and screen results carry a provenance banner and per-row badges for non-live element sets; the Data Mode filter offers SYNTHETIC |
| F-058 | F-S00-02 | `de00fa9` | regression gate for the sweep's refusal record. Writing it found that `_refusal_reason` cut figures at the decimal point ("transfer angle 179"); fixed |
| F-059 | F-S00-03 | `09635bf` | Secure and HttpOnly read off a real Set-Cookie without the opt-out |
| F-060 | F-S00-04 | `09635bf` | each DELETE route refused without a CSRF token |
| F-061 | F-S00-05 | `09635bf` | a captured cookie replayed on GET / after logout gets the login page |
| F-123 | F-S06-05 | `9501e78` | a refused refine shows its reason on the row and logs the refusal, not a Lambert result |
| F-127 | F-S06-13 | `9501e78` | refine flies the red set the sweep used (manual override included) and keeps the regime; dead "blue" branch removed |
| F-128 | F-S06-14 | `9501e78` | refine holds its assessment across the await, leaves a replaced sweep alone, and takes `ge=0` |
| F-124 | F-S06-09 | `c73d054` | an unreadable manual number is blank, not "None"; manual targets are not fetched; fetch failures are recorded, not a 500 |
| F-125 | F-S06-10 | `a440de4` | refusals are per target (and per actor) with the epoch, and a method that solved is never listed as refused |
| F-126 | F-S06-11 | `d464486` | manual targets lead, regime mismatches are skipped before the cap, and the cap names what it drops |
| F-135 | F-S06-25 | `26f2a94` | a failed actor refresh is noted in the screen's provenance banner |
| F-134 | F-S06-24 | `af97226` | manual targets capped (50 entries, 64-character names, 300-character sets, five confidence values); intercept history keeps the latest 200 |
| F-130 | F-S06-17 | `f0d86ff` | Hohmann, bi-elliptic and phasing show the computed miss |
| F-131 | F-S06-18 | `d6c320e` | trade space emits `score` for assessment methods and `miss_km` otherwise; tooltip and clipboard follow. The model-level split is step 4 |
| F-129 | F-S06-16 | `a83f502` | the unread Burns and Minimise ΔV controls removed; a test requires every intercept form input to be declared and read |
| F-132 | F-S06-20 | `aa3db11` | Revolutions, Hops and Drift (days) fields; the coast reaches those solvers as a coast |
| F-133 | F-S06-22 | `0f8ef06` | the Data Mode badge reports the element sets' actual mode, or UNVERIFIED |
| F-158 | F-S09-02 | `eff8280` | objective ids de-duplicated before scoring |
| F-160 | F-S09-04 | `eff8280` | challenge awards for challenge scenarios only; no free-play pass award added, as its value is a tuning decision |

`eff8280` also brings the functions this batch touched under the cognitive complexity limit: `training_scenario_submit` (41), `_start_scenario` (17) and `find_orbital_events` (33, output byte-identical across 15 cases). Each security gate (F-058 to F-061) was mutation-checked: it fails when its control is reverted.

### Web routes, second batch (step 3 web-route Medium findings now closed)

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-138 | F-S07-07 | `0e0f55a` | GCAT search is literal text (`regex=False`), capped at 100 characters, and runs in the executor |
| F-139 | F-S07-08 | `0e0f55a` | GCAT refresh is admin only (button hidden for operators), single-flight with a finally, swaps the new cache in with no await inside the swap, keeps a dataset's previous copy if its download fails; on-demand loads take a per-dataset lock. No separate rate limit: admin-only plus single-flight leaves nothing to throttle |
| F-140 | F-S07-11 | `4c85a40` | an elset with no element lines is an error; one list of field spellings serves selection, extraction and diagnostics |
| F-142 | F-S07-14 | `3936160` | catalogue search and the NOTSO cache path need the operator's own UDL session. Per-identity caching is left to the identity work in step 4 |
| F-143 | F-S07-15 | `e5b5ed2` | login tasks held until done; single-flight catalogue pull (two quick logins made two pulls against the old code, one now); refreshed after a day; cancelled on UDL logout |
| F-144 | F-S07-16 | `74d0f3e` | an archive at the record cap is flagged "History truncated at <epoch>" on the PoL panel. Paging is the fuller fix |
| F-155 | F-S08-12 | `ea48c24` | session expiry pinned at 28,799 s good and 28,801 s gone, by patching itsdangerous's clock; fails when `max_age` is dropped |
| F-151 | F-S08-07 | `1d60499`, `cd3d02f` | login CSRF: every rendering of the login page sets a random token as a Strict, HttpOnly cookie scoped to /login and as a hidden field, and a browser POST (Origin or Referer present) must return both. A same-origin Origin comparison was tried first and dropped before push: Chromium sends `Origin: null` from our own form under the app's no-referrer policy, so it would have refused every real sign-in, and a Host-rewriting proxy would have done the same. Checked in Chromium against a running server: sign-in from /login and from /, cross-site auto-post refused with no session |
| F-149 | F-S08-05 | `9aad51d` | demotion and delete of an admin are conditional statements requiring another admin at the moment of the write, with admin rows locked first where the database has row locks. The race is reproduced deterministically in the test. The PostgreSQL lock path is untested: the suite runs on SQLite |
| F-164 | F-S09-13 | `6c854af` | Decision Engine inputs range-checked (fractions and weights in [0, 1], times in [0, 720] h, horizon in (0, 720] h, 1 to 5 rows each), blanks and NaN refused, all as inline errors htmx swaps; the horizon has no default, so a cleared field is refused rather than read as 72 h |
| F-170 | F-S09-27 | `88ba568` | JetBrains Mono and IBM Plex Sans self-hosted (Latin and Latin Extended, OFL texts alongside); Google removed from style-src and font-src. Checked in Chromium: no external requests, no policy violations |
| F-174 | F-S10-02 | `b0f1b04` | Rendezvous and Proximity are a declared alias table; results under an alias name the solver they ran; README and the engine and architecture docs list the 23 solvers |

`d514f54` splits `search_catalog` and `pol_notso_correlate`, which the F-142 checks took over the complexity limit.

### Build, CI, config and data

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-046 | F-S07-03 | `917c043` | the NOTSO cache reads the real UDL record shape: keyed on `id`, indexed by every `msgBody.SatIds` entry, with JCO fields laid out as labelled text the existing grammar parses (event time from "Jday DDD HHMMz", type from `Event_Class`). All 461 bundled records that name a satellite now parse; 0 did. A route test shows the cache path correlating for 40258 |
| F-047 | F-S07-05 | ruling | closed by the Technical Director's ruling of 24 October 2026 that the `U//DS-JCO-NOTIF` data is acceptable to hold, including in a public repository. No removal. Since F-142 the cache path also needs the operator's own UDL session |
| F-062 | F-S00-06 | `917c043` | the cache lives in the configured data directory, seeded once from the bundled copy; the suite points the data directory at a scratch directory |
| F-141 | F-S07-13 | `917c043` | writes go to a temporary file swapped in with `os.replace`, sync pages write from a worker thread, and an unreadable file is moved aside, not reset |
| F-052 | F-S09-07 | `50ad782` | every optimal score is its objective total; planner_05 passes at 200 of 260 (it asked for 300). The 200 is a tuning choice |
| F-053 | F-S09-08 | `50ad782` | cadet_01 asks for the RAAN (answer unchanged at 45.0), explains it is not the longitude, states the real slot (128.5 West, from SGP4 and GMST) and calls the burn east-west |
| F-153 | F-S08-10 | `3649a5c` | only `require` means encrypt without verifying; any other unknown sslmode is a ConfigurationError; dropped client-certificate parameters are logged |
| F-182 | F-S10-19 | `e5c9998` | .env.example lists all five missing variables and says where SQLite really lives; a test requires every variable the settings read |
| F-176 | F-S10-10 | `f3f8df3` | the proxy-CA hook matches `COPY requirements-runtime.txt ./` and fails if nothing was inserted |
| F-177 | F-S10-11 | `215af86` | a boolean one call deep is charged once (`if a and g(b or c)` scores 3) |
| F-178 | F-S10-12 | `215af86` | the meter follows sonar-python's visitor, read on 24 October 2026: finally adds nothing and does not nest, match adds nothing, lambdas add no nesting. Each rule has a unit case; the calibration still matches all 16 SonarQube scores; the "computes exactly" wording is gone. 5 of 725 scores move, all down |
| F-183 | F-S10-21 | `051325b` | the analyser clone takes tag v2.5.18 and must be commit e175fc6; the packager runs it only with RUN_DS_VERIFY=1 |
| F-184 | F-S10-23 | `909fa8b` | the four comments name scripts/preflight-gate.py and TestPackaging.test_manifests_do_not_drift, which hold the subset check |
| F-175 | F-S10-08 | `0fed505` | actions pinned to commits (checkout v4.4.0, setup-python v5.6.0, upload-artifact v4.6.2, setup-node v4.4.0); the gitleaks tarball is checked against the release's SHA-256 before unpacking; jscpd pinned to 4.3.0 |
| F-146 | F-S07-20 | `bd4459b`, see below | the docstring names the records' real sources and the card labels threat level an analyst judgement; the file carries its marking and source list (next row) |

`f20291b` pins the NOTSO sync route with five characterisation tests and splits it (it scored 27 and F-141 brought it into scope).

### Documentation

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-146 | F-S07-20 | `cba7715` | completed: `adversary_intel.json` carries `UNCLASS // PAIR` (the Technical Director's ruling) and the union of its records' sources in a `_meta` block the loader skips |
| F-056 | F-S10-04 | `e45a1fa` | the guard refuses any `SECRET_KEY` containing "change me" in any spelling; both quick starts generate the key and prompt for the admin password |
| F-064 | F-S00-09 | `e45a1fa` | the quick start installs the locked sets, runs `python -m spectre.web._entrypoint`, maps 8080:8080 and states Python 3.12 |
| F-055 | F-S10-03 | `19f7378` | README states TEME, not converted to J2000/GCRF, and delta-V in m/s; a test refuses J2000/ICRF as the working frame while no transform exists |
| F-173 | F-S10-01 | `5eda791` | the three documents describe Curtis Algorithm 5.2 in `lambert.py` with multi-revolution solutions (true since F-010); `transfers.py` is the closed forms |
| F-161 | F-S09-09 | `1a48611` | README level and axis tables generated from the gamification configuration, with unlock conditions; a test compares them with `get_config()` |
| F-181 | F-S10-15 | `1faa09a` | intercept result, burn and route tables rebuilt from the dataclasses and the router; a test keeps them equal |
| F-180 | F-S10-14 | `508f8ab` | the unused `integration` marker removed; no count claims; all seven CI jobs listed; a test fails on an unused marker |
| F-057 | F-S10-05 | `54a1959` | SECURITY.md rewritten: 22 controls in place, each citing its file and CI job (a test checks they exist); 13 open items; both marking rulings; operator accounts and sign-in logs recorded as personal data |

Observed while generating the F-161 table, not an audit finding: level 5 (Operator) needs three challenges passed, but only one challenge (`analyst_gauntlet`) is available below level 5; the other two unlock at level 5. Level 5 is reachable today only because scenario levels are not enforced (finding at FINDINGS.md:2800). Enforcing them would make level 5 unreachable. Left for a design decision.

### Domain

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-111 | F-S05-04 | `ea29066` | the Decision Engine's TLE refinement removed rather than repaired: it swallowed every error, sampled one instant rather than closest approach, and could only lower the score. `compute_outcome_metrics` and `evaluate_scenario` no longer take element sets; the route no longer passes them |
| F-113 | F-S05-06 | `ea29066` | module and function docstrings describe the model as it is: an uncalibrated lookup over operator-entered fractions, with the custody and gap rules stated as the code applies them, and no claim that SGP4 drives it |
| F-112 | F-S05-05 | `b8fd0bf` | AdversaryAction, FriendlyResponse and Scenario refuse fractions outside [0, 1], NaN and a non-positive horizon at construction, so the domain holds without the route's checks (43 cases) |
| F-116 | F-S05-10 | `832c85e` | the GEO protected region ends at GEO plus 200 km (35,986 km), per the IADC guidelines, built from the shared GEO altitude constant rather than the regime band edge |
| F-118 | F-S05-12 | `572c0ba` | only manoeuvres not classified as routine station-keeping count against the discretionary reserve; five years of fortnightly 1.8 m/s GEO burns keep the full 200 m/s. Spend and rate still count every burn |
| F-119 | F-S05-13 | `de205bb` | an unrecognised solver maps to a new UNCLASSIFIED kind scored against the 75/300 m/s band, which is at least as wide as every (regime, kind) band. RENDEZVOUS, the old fallback, is not the widest anywhere. The test checks the unknown kind is never scored above any known kind, in every regime |
| F-065 | F-S00-12 | `1fa1f55` | CI ruff selects BLE, S110 and RUF100, with the quality gate's own codes (S, PLR, PLC, PLW) declared external so their directives are not reported dead; the one dead directive removed. Of 23 unmarked broad handlers, 16 now catch what their block raises (`TLE_ERRORS`, found by fuzzing the parser and SGP4: ValueError, RuntimeError and ZeroDivisionError) and 7 stay broad with a stated reason |

`1fa1f55` also splits `ScenarioPlanner.plan` (27), `_parse_udl_elset_response` (21) and `udl_notso` (17), which narrowing their handlers brought into scope; each gives byte-identical output against a snapshot taken before the change.

### Test-only findings

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-147 | F-S07-26 | `a4c23a8` | the TLE year pivot is one parametrised test over 00, 26, 56, 57 and 99; the NOTSO cache's `added >= 0` is replaced by what the cache does: a record with no id is kept every time |
| F-137 | F-S06-28 | `2d8ab36` | the `list.sort` test is deleted; the group test's docstring says warning time; the sweep's Hohmann is pinned to the vis-viva 110.69 m/s within 1 m/s; the screen route tests restore the shared cache. Tightening the whole-metres test found two real defects: the group row and the worst-case headline printed ΔV with three decimals. Both now use the `m_s` filter |
| F-122 | F-S05-18 | `41ae3d8` | the fixture's six composite scores and each selector's pick are pinned, the zero-probability branch and all four closest-approach rules run, and CI holds `decision.py` at 100 per cent line coverage. Five hand mutations of `find_robust_response`: four fail the suite, the fifth is equivalent |
| F-066 | F-S00-14 | `8d92e47` | 9 assertion-free tests, 20 type-only tests and 7 assertions true of every value now pin values; `tests/unit/test_every_test_asserts.py` fails on any of the three patterns (also the F-147 gate) |
| F-179 | F-S10-13 | `7b28d97` | the docker-only contract is asserted against the built archive in the packager gate module; the class that could never run is removed, and a contract test fails on a test gated to the docker-only archive. The suite's skips fall from 14 to 12 |

Observed while pinning F-137, not an audit finding: for coplanar circular orbits at 400 and 600 km the sweep prices a V-bar hop at 1.66 m/s, which cannot move an object 200 km in altitude. Left for the solver owner.

### Operator UI

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-104 | F-S04-12 | `0057e1c` | the Monte Carlo period row shows P5, median and P95 (it showed the minimum and maximum under percentile headers) and the altitude row gains its median; the panel states the archetype's assumed sigmas and the ΔV direction basis as "Modelled, not measured" |

With F-104, step 3's single-location findings are closed apart from those carried into step 4 (identity keyed on username, heuristic scores shown as computed physics).

## Step 4: structural

### Identity keyed on the account, not the username

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-048 | F-S08-02 | `8fb54f9` | tokens carry the account id and a random per-account nonce, and are accepted only when both match. A clock-seeded generation was tried first and dropped: the test caught it failing when a delete and re-create fell in the same second and SQLite reused the id. Pre-upgrade tokens carry no id and are refused, so each operator signs in once after the upgrade |
| F-148 | F-S08-03 | `c8a73b1` | planning state is cleared for every sign-in of an account on logout, password change and delete; a recreated namesake starts clean |
| F-044 | F-S07-01 | `c8a73b1` | planning state, and the UDL credentials on it, is filed per sign-in (account id and a random session id from the token) and dropped after the cookie's 8 hours; a second sign-in of the same account sees no UDL connection |
| F-152 | F-S08-08 | `dae9748` | logout revokes only for a live session, and render mints a CSRF token only for a session require_login or optional_login accepted. Checked in Chromium on a pre-upgrade database |

### Heuristic scores no longer presented as computed physics

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-072 | F-S02-12 | `813ae61` | InterceptSolution and InterceptResult gain `score`, `score_kind` and `provenance`; miss_distance_km and intercept_range_km hold a distance or nothing. Seven assessment scores and the J2 and GEO drift angles moved out of the miss field. An AST test fails if a solver writes a score, count or angle into it |
| F-041 | F-S06-07 | `813ae61` | assessment figures read "score", "/100 · heuristic", never probability, likelihood or confidence; the observability line claims no SSN detection probability; a heuristic result's note says it is uncalibrated, not "computed via a solver"; a shared `partials/_modelled.html` badge marks every heuristic result |
| F-018 | F-S02-07 | `813ae61`, `8414b03` | shown as "Intent indicator score (heuristic, uncalibrated)"; the field is `indicator_score`; its weights and thresholds are named constants marked uncited |
| F-019 | F-S02-08 | `813ae61`, `8414b03` | labelled heuristic; `detection_score`; the unsourced SSN attribution is gone; the regime is banded as the package bands it, so 35,780 and 35,790 km score alike |
| F-020 | F-S02-09 | `813ae61`, `8414b03` | `scores` and `match_score`, shown as a heuristic match score; a weak fingerprint reports its real top score instead of the constant 0.1; profiles are tables |
| F-021 | F-S02-10 | `813ae61`, `8414b03` | shown as a detection score fixed per classification branch; the field is `branch_score` |
| F-022 | F-S02-11 | `8414b03` | the docstring says the bands are indicative, uncited and unchecked against AE8/AP8, and names the slot-region inversion; the panel labels the score heuristic |
| F-034 | F-S05-02 | `ad8b937` | OutcomeMetrics carries its basis; the banner reads "Heuristic ranking" with the badge; every cell marks closest approach and custody "(model)" |
| F-036 | F-S05-09 | `ad8b937` | "heuristic anomaly index (uncalibrated)" with the badge and its basis, which states the tuned weights and normalisers; the 200 m/s/yr tooltip is gone; the module docstring carves out the anomaly weights |
| F-033 | F-S04-05 | `ad8b937` | the composite "confidence" is removed; the panel shows the Welch p-value and both window sizes, and the summary says "p < 0.01", not "99% confidence" |
| F-079 | F-S02-25 | `8414b03`, `8dda153` | the five tactical functions over complexity 15 are split, their thresholds named in tables; byte-identical over 28,816 and 420 snapshot cases |
| F-076 | F-S02-19 | `8dda153` | the discarded combined-burn allocation and unused cosine are removed and the docstring no longer claims combined burns; a zero fuel budget no longer divides by zero |

### Remaining High findings

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-023 | F-S02-13 | `ab70bc9` | the RAAN residual is signed and wrapped, so a node moved against precession is detected (+5 against -5 now reads 10, not 0). Fixing it exposed a second defect the magnitude arithmetic hid: manoeuvre detection compared both sets at one instant and still removed a day of J2 drift. It now removes none; a coasting object two days on is no longer charged for a node change |
| F-025 | F-S02-22 | `52f3b5e` | phasing refuses radii more than 10 km apart, naming the Hohmann or Lambert leg needed, and within that reports the radial gap it leaves as the miss instead of 0 |
| F-032 | F-S04-04 | `a652541` | one shared partial says where the detection floor came from; an unmeasured floor reads "the absolute floor (not measured)" with the reason. The too-few-samples path also marked its absolute floor as measured; it no longer does |
| F-035 | F-S05-03 | `d7531e4` | the custody gap is horizon x adversary confidence, not scaled by our reversibility; losing custody now costs. On the fixture the robust rules pick the sensor retask and minimin picks doing nothing |
| F-054 | F-S09-11 | `978a157` | each TLE's node is carried to the newest epoch at SGP4's own secular rate before clustering; three fits of one orbit six hours apart now form one cluster, and a 2 degree node change still separates |

Fixtures in three places held a node fixed for hours or a day, which is itself a node change against J2; they now drift at the J2 or SGP4 rate.

### Medium findings

All 31 open Medium findings are closed. Each fix was test-first: the gate test fails on the code before the change.

#### Web and authentication

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-150 | F-S08-06 | `e795712`, `1ca7696` | passwords are limited to 72 UTF-8 bytes, bcrypt's limit: sign-in counts an over-long one as a failed attempt charged to the limiter (it was an unmetered 500); create and update refuse it with a form error before anything changes; bootstrap logs and skips it rather than stopping the boot |
| F-145 | F-S07-19 | `dfa0bb9` | the Monte Carlo horizon must be 1 to 720 hours; the photometry CSV is capped at 512 KiB with a stated reason (under Starlette's own 1 MiB field limit, found while testing) and parsed off the event loop; both forms share a 10 per minute per-operator compute limit |
| F-154 | F-S08-11 | `578abf6` | the session log queue nothing read is removed; the log holds its 200 entries and nothing else |
| F-157 | F-S08-16 | `db3b8fe` | the structlog setup that was never called, `Settings.log_dir`, SPECTRE_LOG_DIR and the structlog dependency are removed; a test requires every Settings field to be read by the application |

#### Training

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-159 | F-S09-03 | `07c7904` | start, explore, submit and tutorial completion check the level or unlock; submit refuses a result row from another scenario |
| F-168 | F-S09-19 | `07c7904` | elapsed time is measured by the server from the attempt's start; objectives marked `time_limited` score nothing after the limit; a non-list objectives value scores nothing |
| F-167 | F-S09-18 | `07c7904` | exploration runs are left out of recent activity and of the attempt number |
| F-172 | F-S09-38 | `07c7904` | "Skill Points Earned" shows how far each axis total really moved; objective points are labelled as such |
| F-165 | F-S09-15 | `07c7904` | submit is built from tested helpers; tutorial completion shares the level-up loop; no function in the module is over 15 |
| F-166 | F-S09-16 | `07c7904` | the route tests assert progress, not just status; a test refuses status assertions that accept both success and failure |
| F-169 | F-S09-22 | `22183cf` | the six unused point actions, the speed multiplier and the efficiency threshold are removed; the unlock lists match each scenario's level and challenge flag, every scenario is announced once, and `unlock_problems()` checks this at load |

The F-159 level gate made two step 3 tests (F-158, F-160) invalid: they submitted a Level 3 scenario as a Level 1 admin. They now use a Level 3 operator.

#### Numerical correctness

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-100 | F-S04-07 | `6d76d3b` | the photometry baseline is fitted to the baseline window only; a 0.3 mag step across a season of drifting phase angle now reads 0.30, not 0.06. Held out, the fit extrapolates where the recent phases run past the baseline's, and a noise-fitted quadratic then manufactures a change, so past 1 degree of overhang the phase law is linear and the assessment says so |
| F-107 | F-S04-22 | `6d76d3b` | numpy lstsq on centred, scaled phase replaces normal equations on raw powers; the sigma-clip loop and CSV header lookup are split out, the parser byte-identical over 400 generated CSVs |
| F-103 | F-S04-11 | `c74c5ba` | results are aggregated in sample order, so a seed gives one answer on any thread count; converged means the 95 % bootstrap half-width of SMA P5, P50 and P95 is within 1 km, and the panel shows the half-width |
| F-115 | F-S05-08 | `bc0cb50` | the access search's step adapts to range and relative speed (1 to 60 s); each window's closest approach is refined by golden-section search; a failed propagation closes the window; the horizon is `RunConfig.horizon_hours`. The old search overstated misses by up to 2.8 km against SGP4 sampled at 0.1 s |
| F-117 | F-S05-11 | `bde3add` | longitude span is the shortest arc holding every value and predictions wrap into (-180, 180]; a slot at the antimeridian is no longer a belt roamer |
| F-120 | F-S05-15 | `9964e77` | the anomaly score maps through the PoL ladder, so both panels agree and a quiet score cannot raise an assessed LOW; a scarce reserve contributes LOW, not MEDIUM |
| F-162 | F-S09-10 | `01321b5` | DBSCAN runs on precomputed distances with RAAN compared the short way round; the centroid's node is taken within half a turn (unchanged to the last bit away from the seam); selection wraps too |
| F-163 | F-S09-12 | `01321b5` | each cluster records its end-to-end span in tolerances and preprocessing logs a chain over one; the README states the tolerance holds between neighbours |
| F-171 | F-S09-32 | `01321b5` | tests for the seam, chains, near-equatorial GEO and fits hours apart. Writing them found that fits of one equatorial orbit never clustered, its node being noise: below 0.1 degree of inclination two fits are no longer compared on RAAN |
| F-109 | F-S04-26 | `f964e9e` | the J2 equations against the secular node rate (1 %), the incomplete beta against scipy (1e-9), Welch against scipy on small samples and the t-table, and the all-diverged path |
| F-121 | F-S05-17 | `919c132` | ScenarioResult, ThreatAssessment and PolAssessment carry a Provenance: code version, calibration source (now the constant `CALIBRATION_SOURCE`), computed_at, and a SHA-256 of each input, TLEs with their epochs |

`01321b5` also makes the tolerance boundary inclusive on purpose: TLE elements are quantised, pairs exactly one tolerance apart are common, and float noise put them either side. Against 300 generated groups that is the only change in clustering output.

#### Structure and tests

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-069 | F-S01-19 | `eff8280`, `1fa1f55` | closed by step 3 work not logged against it: `find_orbital_events` split (33 to 12, byte-identical over 15 cases) and its handler narrowed to `TLE_ERRORS` |
| F-097 | F-S03-30 | `fd42da8` | closed by step 3 work: `_parse_single_notso` split (to 8) |
| F-098 | F-S03-32 | `39693ba` | closed by step 3 work: `cluster_and_reduce_tle_cache` split (to 9) |
| F-114 | F-S05-07 | `1fa1f55`, `bc0cb50`, `ea29066` | `plan` split (to 6); `compute_outcome_metrics` fell to 14 when the TLE refinement was removed; C901, PLR0912 and PLR0915 are clean |
| F-096 | F-S03-29 | `f28f4b1` | `_compute_drift_phases` split (19 to under 15), byte-identical over 2,000 generated histories |
| F-136 | F-S06-26 | `f28f4b1` | the HRR side, rank and regime rules are one set of helpers used by both functions, byte-identical over 26,000 calls |
| F-080 | F-S02-26 | `3816a8f` | the evasion test's `or True` is replaced by the CW closed forms at both warning times; the assertion checker refuses `or True` |
| F-082 | F-S02-28 | `5d73e39` | the CW solvers, collision avoidance and the V-bar hop are flown on two-body orbits; a checklist test requires every public solver in tactical.py to name its reference test or be a declared heuristic |
| F-156 | F-S08-14 | `3ecf0bb` | the admin tests find their row or fail and read back what they changed; the duplicate cookie tests are removed; a check refuses a search loop with nothing asserted after it |

With F-096 and F-136, no function in `spectre/` or `tle_clustering/` is over cognitive complexity 15, and a test now holds the whole tree to it; CI's gate held only changed functions.

Flying the V-bar hop (F-082) found that a custom hop time was priced as if it were half an orbit. A radial hop lands on V-bar only after an odd number of half orbits, so any other cadence is now refused, as the H-bar hop already did. The one caller uses the default.

Observed, not an audit finding: training progress, attempts and sessions are keyed by username, not account id. A deleted account's training history passes to a recreated namesake, the pattern F-048 and F-148 fixed for sessions and planning state. Left for a decision, since moving the key needs a migration of three tables. **Closed 26 October 2026 by the owner's decision; see "Training keyed on the account" below.**

`docs/SECURITY.md` lists the two new controls (password length, compute bounds). Observed, not an audit finding: the root `SECURITY.md` is stale. Its open items say there is no CSRF protection, no UDL rate limiting and no user-management UI; all three exist, and `docs/SECURITY.md` (rewritten for F-057) is the current policy. Left for the owner to replace with a pointer.

### Low findings

All 112 Low findings are closed or already were; F-188 was closed by the owner's ruling. Each change has a gate test that fails on the commit before it: `tests/unit/test_low_findings_astro.py`, `test_low_findings_batch1.py`, `test_low_findings_batch2.py` (54 of 54 new gates failed on the old code) and `test_low_findings_batch3.py` (70 of 72), plus additions to the route, health and bootstrap suites.

#### Astrodynamics, PoL and constants

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-191 | F-S01-17 | `4a986f3` | a retrograde circular equatorial orbit's true longitude runs with the motion |
| F-192 | F-S01-20 | `4a986f3` | bi-elliptic refuses an intermediate radius inside either orbit or inside the Earth |
| F-193 | F-S01-22 | `4a986f3` | seven unused unit and frame constants removed; a test refuses unused config constants |
| F-194, F-203 | F-S01-23, F-S02-33 | `4a986f3` | no Earth-radius literal outside constants.py; sidereal day 86164.0905 s (IERS); constants cite WGS-84, EGM-96 and Vallado; named phasing perigee floor |
| F-195 | F-S01-24 | `4a986f3` | GEO band edges built from its tolerance; regimes_compatible states it does not check apsis crossing |
| F-196 | F-S02-18 | `4a986f3` | each collision-avoidance strategy reports the separation it reaches, including an in-track burn's radial swing |
| F-189, F-198, F-204 | F-S01-14, F-S02-24, F-S02-34 | `4a986f3` | single-revolution Lambert limit named for what it is; envelope sketch is a lower bound; graveyard default cites the IADC formula |
| F-199, F-200 | F-S02-29, F-S02-30 | `4a986f3` | CW docstring says validity limits are flagged, not refused; every caveat is logged |
| F-201, F-202 | F-S02-31, F-S02-32 | `4a986f3` | spectre/domain/geometry.py, imported only by its own tests, removed with them |
| F-205, F-206 | F-S03-17, F-S03-18 | `c847a96` | duplicate epochs, bad provenance and other objects' element sets counted by reason and shown; Alpha-5 catalogue numbers read |
| F-207 | F-S03-19 | `c847a96` | sidereal time named and cited as GMST (Meeus 12.4) |
| F-208 | F-S03-20 | `c847a96` | semi-major axis labelled a Kozai mean element |
| F-210 | F-S03-22 | `c847a96` | the panel's station-keeping threshold is the module's 0.05 deg/day |
| F-211 | F-S03-23 | `c847a96` | node and perigee corrections use SGP4's own secular rates; duplicate closed forms removed |
| F-212 | F-S03-24 | `c847a96` | a missing longitude is a chart gap, not 0 degrees |
| F-187 | F-S00-13 | `2e33bfa` | vendored JavaScript recorded in vendored.json and scanned against OSV in the SCA job |

#### Clustering, NOTSO, Monte Carlo, delta-v and photometry

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-213, F-215 | F-S03-25, F-S03-28 | `d112615` | clustering failures and all-noise objects without a cache count as fallbacks |
| F-214, F-216 | F-S03-26, F-S03-31 | `d112615`, `e5ec0dd` | an ambiguous slash date is refused; date-time groups parse; NOTSO types match at word starts |
| F-217, F-218 | F-S03-33, F-S03-35 | `d112615` | three tests that could not fail pin exact values |
| F-219, F-220, F-221, F-222 | F-S04-10, F-S04-16, F-S04-17, F-S04-18 | `d112615` | the 3-sigma cloud is the 99.7th percentile distance; the uniform spread has the stated sigma; the GIL claim corrected (the ensemble still runs on threads); unused B* argument removed |
| F-223, F-225, F-226 | F-S04-19, F-S04-24, F-S04-25 | `d112615` | ternary search named; the probe catches only SGP4 failures and reports the sample count; MAD multiplier named; SNR bands taken from the module |
| F-224 | F-S04-21 | `d112615` | a photometry epoch with an offset is converted |

#### Domain

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-227 | F-S05-14 | `9920019` | each calibration band says whether it is a judgement; the assessment carries the caveat |
| F-228 | F-S05-16 | `9920019` | the discretionary reserve is listed as evidence |
| F-229 | F-S05-19 | `9920019` | each PoL ceiling flag has its own correct comment |
| F-230 | F-S05-20 | `9920019` | the detection narrative names the smallest event it would catch |
| F-231 | F-S05-21 | `9920019` | InterceptResult needs an arrival epoch rather than defaulting to now |
| F-232 | F-S05-22 | `9920019` | adversary_idx, summary_table, the domain exceptions and maneuver_planner.py removed; ScenarioPlanner kept |
| F-233 | F-S05-23 | `9920019` | a NaN, infinite or negative delta-v is refused |

#### Threat and manoeuvre routes

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-234 | F-S06-12 | `623a3a7` | a TLE SGP4 cannot propagate is refused or swept with a stated assumption, not assumed LEO |
| F-235 | F-S06-15 | `623a3a7` | clustering and epoch generation run off the event loop; at most two sweeps at once |
| F-236 | F-S06-19 | `623a3a7` | an intercept's budget share is of the operator's budget |
| F-237 | F-S06-21 | `623a3a7` | an unreadable manoeuvre start is refused; an offset is converted |
| F-238 | F-S06-29 | `623a3a7` | route docstrings describe every method |
| F-239 | F-S06-30 | `623a3a7` | the no-intercept refusal states the budget in m/s |
| F-241 | F-S06-32 | `6e25829` | one TLE lookup (SessionState.tle_of) and one dominant-axis rule (burn_view.py) |
| F-242 | F-S06-33 | `6e25829` | the Load button stages the first burn epoch |
| F-243 | F-S06-34 | `6e25829` | solver and clustering exception text goes through log_safe |
| F-244 | F-S06-35 | `6e25829` | three unreferenced partials deleted; /apply-intercept kept as the tested single-method API |
| F-245 | F-S06-36 | `6e25829` | an unknown interceptor regime says the list is unfiltered |
| F-246, F-256 | F-S06-37, F-S07-25 | `6e25829` | hx-vals built with tojson (hardening for satno, which was already valid JSON) |

#### UDL, GCAT and PoL routes

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-247 | F-S07-06 | `6e25829` | GCAT fetches pinned to planet4589.org at every hop |
| F-248 | F-S07-10 | `6e25829` | state vector query bounded to 7 days, newest picked, missing referenceFrame refused |
| F-249 | F-S07-12 | `6e25829` | NOTSO sync messages escaped |
| F-250 | F-S07-17 | `6e25829` | unreachable status handler removed |
| F-251 | F-S07-18 | `6e25829` | UDL password sent as typed; autocomplete off |
| F-252 | F-S07-21 | `6e25829` | UDL_BASE_URL defined once in settings |
| F-253 | F-S07-22 | `6e25829` | docstring names all four returns |
| F-254 | F-S07-23 | `6e25829` | GCAT body streamed under a 64 MiB cap; no per-page copy |
| F-255 | F-S07-24 | `6e25829` | createdAt always UTC-aware; day of year outside 1 to 366 refused |

#### Platform, identity and operator UI

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-257 | F-S08-09 | `6e25829` | /readyz probes the database |
| F-258 | F-S08-13 | `6e25829` | one access line per request, path only; Keycloak claim corrected |
| F-259 | F-S08-15 | `6e25829` | cookie age imported from auth |
| F-260 | F-S08-17 | `6e25829` | admin and rate_limit docstrings corrected |
| F-261 | F-S08-18 | `6e25829` | bootstrap username checked; break-glass promotion needs SPECTRE_ADMIN_RESET_PROMOTE |
| F-262 | F-S08-19 | `6e25829` | log_safe never exceeds its limit |
| F-263 | F-S08-20 | `6e25829` | revocation test docstring describes session_generation |
| F-264 | F-S09-20 | `6e25829` | local now; scored.is_(True) |
| F-266 | F-S09-24 | `6e25829` | scenario window converts offsets |
| F-267 | F-S09-26 | `6e25829` | asset add refuses an empty name and a non-TLE; delete URLs encoded |
| F-268 | F-S09-28 | `6e25829` | stale theme CSS and four orphan SVGs removed |
| F-269 | F-S09-29 | `56518ab` | marking from SPECTRE_CLASSIFICATION and version from the package on banner and splash |
| F-270 | F-S09-30 | `56518ab` | CSP comment counts corrected |

#### Training, clustering config and test helpers

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-271 | F-S09-31 | `56518ab` | from_constants takes defaults from the fields; docstring names real modules |
| F-272 | F-S09-33 | `56518ab` | 50 of 52 scenario checksums recomputed; tle_checksum_valid applied at manual entry |
| F-273 | F-S09-34 | `56518ab` | tutorial labels match the buttons; efficiency promise removed |
| F-274 | F-S09-35 | `56518ab` | shared colour maths in tests/unit/_css.py; the shadowed _rule_block renamed |
| F-275 | F-S09-36 | `56518ab` | objective colours from the axis lookup; empty-list copy corrected |
| F-276 | F-S09-37 | `56518ab` | the hub reuses the open session; a racing progress insert returns the existing row |

#### CI, scripts and ignore rules

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-277 | F-S10-06 | `88f7b42` | setuid sweep runs as root, prints paths, fails when find fails |
| F-278 | F-S10-07 | `88f7b42` | quality job on pull requests only; whole-repo coverage before the early exit; --include-untracked |
| F-279 | F-S10-09 | `88f7b42` | ruff, bandit and mypy hooks run the locked versions |
| F-287 | F-S10-26 | `88f7b42` | timeout-minutes on every job; boot check bounded |
| F-288 | F-S10-27 | `88f7b42` | private mktemp scratch |
| F-289 | F-S10-28 | `88f7b42` | a missing ledger fails packaging |
| F-290 | F-S10-29 | `88f7b42` | manifest search covers the whole stage and every recognised name |
| F-291 | F-S10-30 | `88f7b42` | root-only .gitignore rules anchored |
| F-292 | F-S10-31 | `88f7b42` | .dockerignore uses **/ |
| F-296 | F-S10-36 | `88f7b42` | the scanner's Python 3.11 must resolve |

#### Documentation, locks and repository hygiene

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-280 | F-S10-16 | `bb9cd73` | architecture.md: ThreadPoolExecutor, 200 entries, no missing logo |
| F-281 | F-S10-17 | `bb9cd73` | root SECURITY.md closes SEC-01 to SEC-03; SEC-04 (SBOM in CI) stays open |
| F-282 | F-S10-18 | `bb9cd73` | READINESS.md left out of version rewrites and marked a point-in-time record |
| F-283 | F-S10-20 | `bb9cd73` | python-docx moved to dev; hypothesis removed; relocked with no other pin moved |
| F-284 | F-S10-22 | `bb9cd73` | query_UDL_Data.py deleted (its literal token is a placeholder; it disabled TLS verification) |
| F-285 | F-S10-24 | `bb9cd73` | build comments describe the current flow |
| F-293 | F-S10-32 | `bb9cd73` | STK notes marked historical; root STK-branded logo removed |
| F-294 | F-S10-33 | `bb9cd73` | persona and prompt documents moved to prompts/ |
| F-295 | F-S10-34 | `bb9cd73` | root splash fragment and duplicate SVGs removed |

#### Already closed by earlier work

| Finding | Origin | Commit | Change |
|---|---|---|---|
| F-185 | F-S00-10 | `6bee4f2` | ci.yml no longer overrides the pyproject coverage ratchet |
| F-186 | F-S00-11 | `e285c68` | the SPECTRE-1 gitlink is gone |
| F-190 | F-S01-15 | `accb129` | the Lambert comment no longer claims Newton-Raphson |
| F-197 | F-S02-21 | `5d73e39` | hop times off the odd or whole half-orbit cadence are refused (with F-082) |
| F-209 | F-S03-21 | `f28f4b1` | the misleading wrap comment went with the F-096 split |
| F-240 | F-S06-31 | `2d8ab36` | the sweep headline shows whole m/s |
| F-265 | F-S09-21 | `22183cf` | the speed multiplier went with F-169 |
| F-286 | F-S10-25 | `6bee4f2` | pip-audit covers requirements-dev.txt |

Partly fixed at triage and completed above: F-189, F-194, F-203, F-217, F-222, F-232, F-254 and F-280.

#### Ruled by the owner

F-188 (origin F-S00-15): the `test_should_` naming convention is dropped, by the owner's ruling of 26 October 2026. It was stated in the engineering persona (now `prompts/UK_Principal_Engineer_Persona.md`) and followed by none of the suite's 1,946 tests. The persona now states the convention the suite does follow (a test named for the behaviour that holds, a class for the contract or defect it pins), its examples follow it, and `TestF188NoShouldPrefixConvention` holds both.

#### Notes

● F-244: `/apply-intercept` is unreferenced by the UI but kept. It is the single-method API, and about ten integration tests exercise its error paths; deleting it would delete that coverage.
● F-247: with the host pinned to planet4589.org, no redirect or configuration can point the fetch at a private, loopback or link-local address, so no separate resolved-address check was added.
● F-272: the route-test TLEs had a 68-column line 2 (the perigee field had lost a space) as well as wrong checksums. Both were repaired once manual entry began checking.
● F-274: the first of two `_rule_block` definitions was not dead. Module-level constants called it during import; every call made later silently reached the second. It is now `_sole_rule_block`.
● Observation, not a finding: the house rule that tests must skip when a non-application file is absent detects literal paths only. A helper taking the path as a variable passes it unseen. The new batch 3 helper skips correctly; the detector itself is unchanged.

### Training keyed on the account

Not an audit finding; the observation recorded under the Medium findings, closed by the owner's decision of 26 October 2026.

Reproduced first, on the commit before the change: an operator promoted to Level 4, deleted, and recreated under the same name signed in at Level 4 with the old attempt history.

● All three training tables carry `user_id` and every lookup uses it. The username stays as a label and is never a key; progress is unique on the account, not the name.
● Deleting an account deletes its training rows in the same transaction. Keying on the id alone would not be enough: SQLite reuses a freed id, and the rows would pass to the next account created.
● Existing databases are migrated at boot. Each legacy row takes the id of the account that holds its username now; rows whose username no account holds belong to a deleted account and are removed, with a count in the log. The unique index on `training_progress.username` becomes a plain index and uniqueness moves to `user_id`. Every step is a no-op on a second boot.
● One limit, stated plainly: a namesake recreated before this upgrade already sees the deleted account's history, and the migration cannot tell the two apart, so those rows stay with the namesake.

Gates: `tests/integration/test_training_keyed_on_account.py` (a recreated namesake starts at Level 1 with no attempts and the deleted account's rows are gone; a legacy database is backfilled, orphans removed, indexes moved, and a second run changes nothing).

### SBOM in CI (SEC-04)

Not an audit finding; the open item in the root `SECURITY.md`, closed at the owner's request of 26 October 2026.

● The SCA job writes a CycloneDX SBOM of `requirements-runtime.txt`, the lock the image installs, and keeps it as the `sbom-cyclonedx` build artifact. The upload fails the job if no file was written.
● `scripts/check-sbom.py` refuses an SBOM that leaves out any pinned package, matching names in their PEP 503 form. A partial SBOM is read as a complete one, so it is a failure rather than a warning. On the current lock it lists all 41 pins.
● Scope, stated in `docs/SECURITY.md`: the image's Python packages only. OS packages in the base image and the vendored JavaScript are not in it; the JavaScript is recorded in `spectre/web/static/vendored.json` and scanned separately.

Gates: `tests/unit/test_sbom_in_ci.py` (the checker passes a complete SBOM, names a missing pin and refuses a non-CycloneDX document; the SCA job writes, checks and uploads the SBOM; SEC-04 is closed in both policies).

### Code scanning (CodeQL)

Not an audit finding. The `master` ruleset requires CodeQL results before a pull request can merge, and the repository had no CodeQL workflow, so no pull request could satisfy it. The owner chose to keep the rule and add the scan, 26 October 2026.

● `.github/workflows/codeql.yml` runs CodeQL over the Python with the security-extended queries on every push and pull request to `master`, and weekly.
● The action is pinned to the v4.38.3 commit, 18 days old when pinned; v4.39.1 was 5 days old and so not taken.
● JavaScript is not analysed: the application's own script is inline in the Jinja templates, which CodeQL does not extract, and `spectre/web/static` holds vendored third-party builds already scanned against OSV.
● `docs/SECURITY.md` now lists code scanning and the SBOM under controls in place, each citing its file. The F-057 test that forbade both words, written against the old template's false claims, now requires the citation instead.

