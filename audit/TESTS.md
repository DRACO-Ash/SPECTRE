# SPECTRE audit: test and assertion audit (phase 6)

**Source audited:** tree at `a34e273`. Evidence comes from AST analysis of every test file, the branch-coverage run (`audit/tools-raw/pytest.txt`), and a targeted mutation sample (`audit/tools-raw/mutation_sample.md`). Per-slice test judgements sit in section A of each slice review and are folded into `audit/FINDINGS.md`.

## Headline

The suite is large and green: 1,898 collected, 1,896 passed, 2 skipped. That is not evidence of correctness, and this run shows the gap directly:
● Branch coverage is 70.96 % against 84.35 % statement coverage. The 23 risk-bearing modules leave **457 branch arcs** unexecuted.
● **7 meaningful mutants out of 20 applied survived the relevant tests.** They include the removal of session expiry, the removal of revocation from `optional_login`, DELETE treated as CSRF-safe, and three bi-elliptic transfer errors (fact, executed).
● A full-suite run with the July 2026 threat-sweep defect reintroduced passed 1,896 tests (`audit/tools-raw/mut_p3_full_suite.txt`).
● Several Blocker-class numerical defects found in phases 5 and 7 ship under a green suite. Three of them are `min_time_intercept_analytical` returning 1 % of the Hohmann time, the CW drift at −0.5 times its true value, and the GEO drift taking hours as days (`audit/REFUTATION.md`).

A high pass rate here measures how much code is exercised. It does not measure whether the code is right.

## 6.1 Classification

Method: AST and content heuristics over all 76 `tests/**/test_*.py` files (script output in `audit/tools-raw/test_classification.md`). A file can carry several labels.

| Class | Files | Rule |
|---|---|---|
| unit | 56 | no other class, or regression/smoke only |
| integration | 14 | under `tests/integration/`, or drives `TestClient` / `AsyncClient` |
| regression | 18 | cites a fixed defect ("before the fix", "the defect", published-answer comparisons) |
| contract | 6 | deployment, packaging, quality-gate or committability contracts |
| smoke | 4 | self-described smoke tests |
| property | 2 | uses `hypothesis` |

There are 1,389 test functions, expanding to 1,898 collected cases through parametrisation. The 8 non-`test_*.py` support files (`conftest.py`, `__init__.py`) are classified as fixtures in the ledger.

## 6.2 Forbidden test patterns

Method: AST walk of every test function. A test passes the assertion check if it contains an `assert` statement, a `pytest.raises` or `warns` context, or a call to a helper whose name starts with `assert`, `expect`, `check`, `verify` or `require` (leading underscores ignored). Full list in `audit/tools-raw/test_flags.md`.

The first pass of the heuristic missed `_assert_*` helpers and flagged 20 tests. 13 of those were false positives (for example `tests/integration/test_packager_gates.py:107` `_assert_refused`). They were corrected before reporting: a reviewer-error rate of 13 in 20 on the first pass, recorded so the method can be judged.

**Assert only that no exception was raised (7, fact):**

| Location | Test | What it fails to check |
|---|---|---|
| `tests/unit/test_config_settings.py:96` | `test_accepts_a_real_secret` | only that `validate_secret_key("k" * 32)` does not raise |
| `tests/unit/test_config_settings.py:269` | `test_accepts_a_normal_filesystem` | no-raise only |
| `tests/unit/test_hrr_bootstrap.py:145` | `test_every_object_carries_a_usable_element_set` | `TLEOrbit(tle)  # raises if the element set is unusable`; a usable but wrong orbit passes |
| `tests/unit/test_hrr_preload.py:57` | `test_empty_notification_list_is_a_no_op` | no-op not asserted |
| `tests/unit/test_hrr_preload.py:79` | `test_non_dict_entries_are_discarded` | the name says "discarded", but only "must not raise" is checked |
| `tests/unit/test_maneuver_planner.py:36` | `test_valid_config_passes` | no-raise only |
| `tests/unit/test_planning_state.py:37` | `test_clear_nonexistent_is_noop` | `# should not raise` |

**Trivial assertions only (26, fact):** each asserts only `isinstance(...)` or `is not None`. Examples: `tests/unit/test_decision.py:194,199,204`, the three selector tests that would pass whichever response each selector picked. That is why the mislabelled Maximin selector (F-S05-01) survived. Further examples: `tests/unit/test_photometry.py:198`, `tests/unit/test_cw_geometry.py:167,371,495,511`, and seven in `tests/unit/test_training_gamification.py`. The full list is in `audit/tools-raw/test_flags.md`.

**Mock-only assertions:** none found by the AST check.

**Duplicate bodies:** none found among undecorated tests in the same file.

## 6.3 Coverage truth

Risk-bearing modules, with every missing branch arc named in `audit/tools-raw/uncovered_branches.md`:

| Module | Statement % | Branches | Note |
|---|---|---|---|
| `spectre/web/routes/udl.py` | 37.1 | 45/128 | holds the credential path and every UDL fetch |
| `spectre/web/routes/pol.py` | 40.5 | 24/88 | PoL analyse accepts UDL credentials directly (F-S07-02) |
| `spectre/web/routes/threat.py` | 50.3 | 80/198 | sweep, refine and fetch routes have no direct tests (F-S06-08) |
| `spectre/astro/tactical.py` | 92.8 | 195/244 | high coverage over defective solvers: covered is not correct |
| `spectre/astro/maneuvers.py` | 96.7 | 32/52 | 96.7 % statements over the double-degrees and RAAN-blind defects |
| `spectre/domain/decision.py` | 88.8 | 38/46 | |
| `spectre/web/routes/admin.py` | 90.2 | 30/40 | |
| `spectre/astro/transfers.py` | 100.0 | 1/2 | 100 % statements; 4 of 10 mutants survive |
| `spectre/web/auth.py` | 94.3 | 15/18 | 94 %; session expiry mutant survives |

**Covered but not asserted on (fact, by mutation).** These lines execute under test and can be changed without any test failing:
● `transfers.py:28` (bi-elliptic total);
● `transfers.py:55` (the Hohmann second burn, to within 4 %);
● `transfers.py:93-94`;
● `auth.py:22` (session lifetime);
● `auth.py:195` (revocation in `optional_login`);
● `csrf.py:24` (the safe-method set).
The tactical solver defects confirmed in phase 7 are the same pattern at larger scale: `min_time_intercept_analytical` is covered and its tests assert `feasible_count >= 0`-style bounds (F-S02-26).

## 6.4 Mutation sample

Harness: `scratch/tools/mutate.py`. Each mutant replaces one exact substring on one line, runs the test files mapped to that module with `-x`, and restores the file with `git checkout`. Modules chosen as highest risk: `spectre/astro/transfers.py` (critical path of the threat sweep, weak gate per PRIORS-STATUS P9), `spectre/web/csrf.py` and `spectre/web/auth.py` (the security boundary). `lambert.py` and `threat.py` were mutated separately during phase 4b (`audit/PRIORS-STATUS.md` P1 and P3).

| Module | Applied | Killed | Survived | Equivalent survivors |
|---|---|---|---|---|
| transfers.py | 10 | 6 | 4 | 0 |
| csrf.py | 5 (1 not applied, line mismatch) | 3 | 2 | 1 (`csrf.py:91`: the fallback token `"x"` still fails verification) |
| auth.py | 5 | 3 | 2 | 0 |
| lambert.py (phase 4b) | 1 | 1 | 0 | 0 |
| threat.py (phase 4b) | 1 | 0 | 1 | 0 |
| **Total** | **22** | **13** | **9** | **1** |

There are 8 meaningful surviving mutants. Each is a finding (`audit/FINDINGS.md`, IDs prefixed `F-T`):

| Mutant | Location | What no test pins |
|---|---|---|
| Hohmann second burn × 1.04 | `transfers.py:55` | ΔV₂ to better than about 5 % |
| bi-elliptic third burn × 2 | `transfers.py:93` | any bi-elliptic burn magnitude |
| bi-elliptic second leg uses `a1` | `transfers.py:94` | bi-elliptic transfer time |
| total omits the third burn | `transfers.py:28` | the bi-elliptic total |
| DELETE treated as safe | `csrf.py:24` | CSRF on `DELETE /admin/users/{id}`, `/assets/blue/{name}`, `/assets/red/{name}` |
| session lifetime × 1000 | `auth.py:22` | that a session expires at all |
| `optional_login` ignores revocation | `auth.py:195` | that `GET /` reads a revoked session as anonymous (claimed at `auth.py:192-194`) |
| sweep refusal recording replaced by `pass` | `threat.py:682` | that a method failure reaches `method_refusals` |

## 6.5 Naming

Convention required: `test_should_<expected>_when_<condition>`. **0 of 1,389 test functions conform** (fact, regex `^test_should_\w+_when_\w+$`). The suite uses descriptive sentence names instead (for example `test_a_password_change_ends_a_live_session`). These are readable, and many state the expected behaviour. Inference: the convention was never adopted, so this is one consistent decision rather than 1,389 defects. It is recorded as a single Low finding.

## Exit check

● Every test file is classified: 76 of 76 in `audit/tools-raw/test_classification.md`, and the 8 support files appear in the ledger.
● Every risk-bearing uncovered branch is named: 457 arcs across 23 modules in `audit/tools-raw/uncovered_branches.md`.
