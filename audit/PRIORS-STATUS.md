# SPECTRE audit: prior-audit verification (phase 4b)

**Source audited:** tree at `a34e273` (HEAD differs only under `audit/`). **Input:** `audit/PRIORS.md`, ten claims reconstructed from the July 2026 session.

**Provenance check, done first as PRIORS.md asks.** The only candidate original artefact in the tree is `AUDIT.md` inside `bluestaq-foundations-v1.99.0.zip` (LEDGER O10). I extracted it to an isolated scratch directory and read it as data. It is the parameter and source map of a generic engineering baseline ("Bluestaq Foundations"). `grep -i -c "spectre\|lambert"` returns 0. Fact: it is not the July SPECTRE audit. The inference recorded at O10 is refuted. No original artefact exists in the tree, so every prior below was reopened against code. None is reconciled against an original document, and the reconstruction caveat stands.

**Method.** Each verdict cites the current code. Wherever a gate is claimed, I tested it: the original defect was reintroduced in a scratch clone and the suite run against it. A gate that does not fail is not a gate.

## Summary

| Prior | Subject | Verdict | Finding raised |
|---|---|---|---|
| P1 | Lambert universal-variable error | **FIXED-WITH-GATE** (maths); docstring attribution **STILL-PRESENT** at function level | P-F1 (Medium) |
| P2 | Heuristics presented as physics (Decision Engine) | **STILL-PRESENT** | P-F2 (High) |
| P3 | Silent failure sinks in the threat sweep | **FIXED-WITHOUT-GATE**; residual silent-assumption sinks STILL-PRESENT | P-F3 (Medium), P-F4 (Medium) |
| P4 | Session cookie Secure flag | **FIXED-WITHOUT-GATE** at the call site (resolver gated, wiring not) | P-F5 (Medium) |
| P5 | UDL credentials in a process-global dict | **STILL-PRESENT** | P-F6 (High) |
| P6 | No provenance stamping | **STILL-PRESENT** | P-F7 (Medium) |
| P7 | Duplicated Earth radius | **STILL-PRESENT**, values disagree | P-F8 (Medium) |
| P8 | STK dependency question | Code: **FIXED** (pure Python). Docs: **STILL-PRESENT** | P-F9 (Medium) |
| P9 | Physics regression coverage | **Partly FIXED-WITH-GATE**; Hohmann weakly gated, bi-elliptic and vis-viva ungated | P-F10 (High) |
| P10 | Static baseline | Re-established, see table below | none (baseline) |

Totals: 10 priors. STILL-PRESENT in whole or part: P1 (attribution), P2, P3 (residual), P5, P6, P7, P8 (docs), P9 (part), which is 8 priors. Wholly STILL-PRESENT: P2, P5, P6, P7, which is 4. FIXED-WITHOUT-GATE: P3, P4, which is 2. FIXED-WITH-GATE in its principal claim: P1.

## P1 (D1) Lambert solver universal-variable error

● **χ relation uses C(z): fixed, fact.** `spectre/astro/lambert.py:246` reads `chi = math.sqrt(y / _stumpff_C(z))`.
● **dF/dz derivative: NOT-APPLICABLE, fact.** Newton iteration was replaced by bracketed bisection (`lambert.py:257-321`), so no derivative remains. Non-convergence raises `LambertConvergenceError` (`lambert.py:318-321`); it is never returned silently.
● **Docstring attribution: partly fixed, fact.** The module docstring is corrected (`lambert.py:6`, "Method: Curtis ... Algorithm 5.2", and `lambert.py:11-13`, which records the former false Izzo claim). The public function docstring still makes it: `lambert.py:53` `"""Solve Lambert's problem using Izzo's algorithm.`. Also `lambert.py:60` documents `prograde: If True, assume prograde (short-way) transfer.`, while the code treats `prograde` as orbit direction and takes the long way whenever the orbit normal disagrees with it (`lambert.py:95`). Prograde and short-way are not synonyms. Both are claims-ledger defects.
● **Gate: exists and fires, fact.** `tests/unit/test_lambert_validation.py:89-110` pins Curtis Example 5.2 departure and arrival velocities to within 1 m/s (1e-3 km/s), matching the agreed remediation. Mutation test: line 246 reverted to `chi = math.sqrt(y / mu)` in a scratch clone gives 4 failures in that module (round-trip residual for three cases, and the near-guard geometry). The gate is real.
● **Location note, fact.** README places the solver in `transfers.py` (`README.md:309` "transfers.py ← Lambert solver (universal variable method)"). `transfers.py` contains only Hohmann and bi-elliptic. The solver is in `lambert.py`.

**Verdict: FIXED-WITH-GATE** for the numerical defect. **STILL-PRESENT** for the function-level misattribution: candidate P-F1, Medium (misleading comment, L8). It is not a Blocker, because the maths is gated.

## P2 (D2, D5) Heuristics presented with the authority of physics

All three layers checked, as PRIORS.md requires.
● **Code, fact.** `compute_outcome_metrics` (`spectre/domain/decision.py:155-260`) is built from unsourced constants: `base_ca_km = 5000.0`, `200.0`, `10000.0`, `3000.0` (`decision.py:195-201`); `friendly.cost * 5.0` and `* 2.0` (`:205,207`); `time_to_ca = scenario.horizon_hours * 0.4   # Phase 1: simplified` (`:234`); `dv_km_s = friendly.cost * 0.05` (`:238`); normalisation spans of 50,000 km and 100 m/s (`:251-252`). The "TLE-based refinement" mixes a real SGP4 separation with the analytic constant using `friendly.reversibility` as the weight (`:230`). Reversibility is a dimensionless operator input with no physical relation to separation.
● **API payload, fact.** `OutcomeMetrics` (`decision.py:81-89`) and `ScenarioResult` (`decision.py:119-130`) carry no field marking the values as modelled, and no provenance.
● **Rendered interface, fact.** `partials/decision_results.html` leads with a "Robust Recommendation" banner (`:7-35`). The only qualifier is a 0.6 rem dim footer, `Phase 1 · deterministic analytic model` (`:136-139`). No "modelled estimate, not a computed solution" banner exists anywhere: `git grep -n -i "modelled estimate\|not a computed" -- spectre` returns nothing.
● **Silent fallback, fact.** `decision.py:231-232` `except Exception:` / `pass   # Fall back to analytic estimate`. A propagation failure silently replaces the TLE-based figure with the analytic one, and the operator sees the same display either way.

**Verdict: STILL-PRESENT.** Candidate P-F2, High: an uncalibrated heuristic presented as computed, under a "Robust Recommendation" banner. The agreed remediation was not implemented.

## P3 (D3) Silent failure sinks in the threat sweep

Tree-wide grep as required:
```
$ git grep -nE "except\s*:" -- '*.py'                       -> (no output)
$ git grep -nE -A2 "except (Exception|BaseException)\b" -- 'spectre/*.py' 'tle_clustering/*.py' | grep -E "^\S+-[0-9]+-\s+(pass|continue)\b"
spectre/domain/decision.py-232-            pass   # Fall back to analytic estimate
spectre/domain/scenario.py-88-                        continue
$ git grep -n "suppress(" -- 'spectre/*.py' 'tle_clustering/*.py' 'scripts/*.py'
spectre/config/settings.py:241, :460 · spectre/domain/threat_assessment.py:274 · spectre/web/planning_state.py:108 · spectre/web/routes/maneuver.py:816, :1068
```
● **The July sink is fixed, fact.** `_sweep_all_methods` now records the reason per method: `threat.py:681-682`, `except Exception as exc:  # noqa: BLE001` / `notes.setdefault(name, _refusal_reason(exc))`. The refusals panel is rendered and template-tested (`tests/unit/test_threat_sweep_template.py`).
● **No gate, fact by mutation.** With `threat.py:682` replaced by `pass` in a scratch clone, the whole suite still passes: `1896 passed, 2 skipped` (`audit/tools-raw/mut_p3_full_suite.txt`). The template test pins the panel, not the route's duty to fill it.
● **Residual silent sinks in threat.py, fact.** These do not drop a target but silently substitute an assumption the operator is never told about:
  ■ `threat.py:1342-1343`: `except Exception:  # noqa: BLE001` / `red_regime = "LEO"  # assume LEO on parse failure; sweep proceeds`.
  ■ `threat.py:1219-1220`: `except Exception:  # noqa: BLE001` / `tgt_regime = red_regime  # assume compatible if TLE can't be parsed`.
  ■ `threat.py:1179-1180`: clustering failure logged server-side only (`logger.warning`), not shown to the operator.
  ■ `threat.py:943-944`: `return ""`.
  The `noqa: BLE001` directives are inert because ruff does not select BLE (`audit/TOOLS.md` 2.2), so no CI lint checks these handlers.
● **Other remaining sinks, fact.** `decision.py:231-232` (see P2). For `scenario.py:88` `continue` and `threat_assessment.py:274`, operator visibility is TBC, re-verify in slice S05 output.

**Verdict: FIXED-WITHOUT-GATE** for the July sink. Candidate P-F3, Medium, by the rule in PRIORS.md. Residual silent-assumption sinks: candidate P-F4, Medium. A wrong regime silently assumed for a red object biases which transfer methods apply.

## P4 (D6) Session cookie without the secure flag

● **Call site, fact.** `spectre/web/routes/login.py:167-174`: `httponly=True`, `secure=get_settings().session_cookie_secure`, `samesite="lax"`, `max_age=_SESSION_COOKIE_MAX_AGE` (28,800 s). No `domain` (host-only cookie); `path` defaults to `/`.
● **Environment branch, fact.** `spectre/config/settings.py:263-265`: Secure unless `SPECTRE_COOKIE_SECURE` is one of `false`, `0`, `no`, `off`. There is no implicit development or production inference, so an opt-out has to be deliberate. The integration suite sets it to false (`tests/integration/conftest.py:22`).
● **Logout, fact.** `login.py:216` `response.delete_cookie(key=_COOKIE_NAME)` passes neither `secure` nor `samesite`. Harmless for deletion (inference).
● **Gate, fact.** `tests/integration/test_root_contract.py:60-71` asserts `_resolve_cookie_secure() is True` by default. `:50-58` asserts that a real `Set-Cookie` header carries `httponly` and `samesite=lax`, but no test asserts `secure` on a real header. `grep -rn "secure" tests/ | grep -i "set-cookie\|header"` finds only the opt-out comment. Reverting the call site to `secure=False` would go undetected (inference from the grep: the suite runs with the opt-out, so no header in any test carries `Secure`).

**Verdict: FIXED-WITHOUT-GATE** for the regression that actually occurred, a call site without Secure. Candidate P-F5, Medium.

## P5 (D-unnumbered) UDL credentials in a process-global in-memory dict

● **Holder and scope, fact.** `spectre/web/planning_state.py:56-57` `udl_username: str | None = None` / `udl_password: str | None = None` live on `SessionState`, stored in `_store: dict[str, SessionState] = {}` (`:113`). Scope: **process**, keyed by SPECTRE username. Every browser session of that user shares the same holder. Plaintext, not encrypted.
● **Lifetime, fact.** Cleared only at `login.py:212` (logout) and `udl.py:385` (UDL logout): `git grep -n "clear_session_state\|udl_password *=" -- spectre`. Cookie expiry after 8 h, and a server-side revocation through the generation counter (`auth.py:86-102`), do not clear it (inference from the absence of any other clearing call site).
● **Outbound and background, fact.** It is sent as HTTP Basic on 11 call sites (`audit/ARCHITECTURE.md` 3.2) and passed as plain arguments into `asyncio.create_task` background tasks whose handles are discarded (`udl.py:316-317`).
● **Leak paths, fact unless marked.** The password is not logged (grep of logger calls). `__repr__` is overridden to omit it (`planning_state.py:93-99`). The UDL username is written to the operator's session log (`udl.py:312`). Error text echoes UDL response bodies up to 300 characters to the operator (`udl.py:279-280,291-292`): not the credential (inference). A crash dump or a debugger frame would expose it, as would any plaintext attribute (speculation).
● **App Store injection, fact.** No UDL credential environment variable exists. `git grep -nE "os\.environ|getenv" -- spectre` lists none (`audit/ARCHITECTURE.md` 3.5). The in-process path is the only path.

**Verdict: STILL-PRESENT.** Candidate P-F6, High, flagged separately in the summary as a security boundary. The agreed target (session-scoped, encrypted in memory, never process-global) was not implemented.

## P6 (D7) No provenance stamping at module boundaries

● **Fact.** `InterceptResult` (`spectre/domain/models.py:343-351`) carries names, method, burns, total ΔV, arrival epoch, range, notes and an option id. It carries no code version, no input TLE epochs and no input identity.
● **Fact.** The CSV export header (`spectre/web/routes/plan.py:176-177`) records time, operator and run count, not the SPECTRE version or the input element sets.
● **Fact.** `RunConfig`, the "Provenance metadata for a single planning run" (`models.py:425-441`), is consumed only by `ScenarioPlanner` (`domain/scenario.py:37`). The web layer never constructs either: `git grep -n "RunConfig\|ScenarioPlanner" -- 'spectre/*.py'` shows definitions and `scenario.py` only.
● **Partial counter-evidence, fact.** Element-set provenance does exist in the PoL ΔV path (`spectre/astro/dv_estimation.py:229-237` `provenance_label`, rendered at `pol_manoeuvre_detail.html:260-264`), and UDL `dataMode` is carried through the threat sweep (`threat.py:1244,1374`). That is per-input data provenance, not per-product version and input stamping.

**Verdict: STILL-PRESENT.** Candidate P-F7, Medium. Rises to High for the CSV export, which is the artefact an analyst would cite downstream.

## P7 (D8) Duplicated Earth radius constant

```
$ git grep -nE "6378\.?[0-9]*|6371\.?[0-9]*" -- 'spectre/*.py' 'tle_clustering/*.py'
spectre/astro/constants.py:9:R_EARTH: float = 6378.137
spectre/astro/maneuvers.py:1031:    altitude = sv.r_mag - 6378.137
spectre/astro/photometry.py:38:_R_EARTH_KM = 6371.0
spectre/domain/decision.py:34:_R_EARTH_KM = 6371.0
$ grep -c "_R_EARTH_KM" spectre/domain/decision.py spectre/astro/photometry.py
spectre/domain/decision.py:1
spectre/astro/photometry.py:1
```
● **Fact.** Four definitions. The values do **not** agree: 6378.137 km (WGS-84 equatorial) in two places, 6371.0 km (mean radius) in two.
● **Fact.** Both 6371.0 constants are defined and never used (one occurrence each), so the divergence is currently latent. `maneuvers.py:1031` is a live literal duplicate of `constants.R_EARTH`.
● **Related, inference.** Tests also embed both values (`tests/unit/test_tle_filter.py:42` 6378.137; `tests/unit/test_geometry.py:43` 6371.0).
● **Single source:** `spectre.astro.constants.R_EARTH`. Other constants: `MU_EARTH`, `J2_EARTH`, `GEO_RADIUS` and `SIDEREAL_DAY` are each defined once (`constants.py:6,12,15,16`), and `monte_carlo.py:46` aliases `J2_EARTH` rather than redefining it (fact, grep).

**Verdict: STILL-PRESENT.** Candidate P-F8, Medium.

## P8 (D9) Unresolved STK dependency question

```
$ git grep -n -i -E "\bSTK\b|astrogator|win32com|comtypes" -- 'spectre/*' 'tle_clustering/*' 'tests/*' 'pyproject.toml' 'requirements*'
(no output)
```
● **Code, fact.** Pure Python. No STK imports, COM references or dependencies.
● **Docs, fact.** `docs/astrogator_notes.md:3-4` reads "Reference for implementing `StkComSession.compute_maneuver_options` and `StkComSession.apply_maneuver` against the STK 13 Astrogator Object Model." `docs/stk_object_model_notes.md:3` reads "Reference notes for implementing `StkComSession` against the STK 13 COM API.". Both are written as live implementation guides, carry no historical banner, and describe a class that does not exist: `git grep -n StkComSession -- spectre tests` returns nothing. By contrast, `docs/intercept_engine.md:5` and `docs/phased_plan.md:7` do carry historical notes.
● **Claims, fact.** `README.md:20` and `docs/architecture.md:5-7` state pure Python. The two notes contradict that by implication.

**Verdict:** code **FIXED** with no regression gate needed. Docs **STILL-PRESENT**: candidate P-F9, Medium, routed to the claims ledger.

## P9 (D10) Regression coverage on the critical physics path

| Solver | Test | Reference and tolerance | Gate quality |
|---|---|---|---|
| Lambert | `test_lambert_validation.py:89-110`, round-trip `:139-160` | Curtis Ex. 5.2, < 1 m/s; propagated miss < 1 km | **gated**; mutation-proven (P1) |
| Hohmann | `test_astro.py:33-45` | band only: `2.3 < dv1 < 2.6`, `3.7 < total < 4.1` (about ±5 %); no named reference value | **weak**: a 4 % error passes (inference from the band width) |
| Bi-elliptic | `test_astro.py:53-66` | none: `delta_v_3 > 0`, `total_delta_v > 0`, slower than Hohmann | **ungated** (exercised only) |
| Vis-viva | none directly; `_v_vis_viva` (`transfers.py:31`) reached through Hohmann bands | none | **ungated** beyond the Hohmann band |
| Plane change | `test_orbital_units_and_degeneracies.py:150-169` | closed form 2v·sin(Δi/2), rel 2 %, and tabulated 26.8, 107.3 and 268.2 m/s | **gated** |
| J2 RAAN rate | `test_tactical_validation.py:174-180` | sun-synchronous condition 0.9856 deg/day, abs 0.01 | **gated** |
| Clohessy-Wiltshire | `test_tactical_validation.py:106-122` | 2:1 along-track to radial ratio, rel 2 %; closure | **property-gated**, not a published worked example; slice S02 to confirm |
| Phasing, GEO drift, graveyard | `test_tactical_validation.py:42-60,150-172` | closed forms, abs 1 km or rel 1 % | **gated** |

**Verdict: partly FIXED-WITH-GATE.** Hand validation was captured for Lambert, plane change, J2, phasing and GEO drift. **STILL-PRESENT** for bi-elliptic (ungated) and Hohmann (band, not reference). Candidate P-F10, High for Hohmann and bi-elliptic, which sit on the critical path of the threat sweep (`ARCHITECTURE.md` 3.2: the sweep batch-evaluates Hohmann). The mutation sample in phase 6 tests the Hohmann band directly.

## P10 Static quality baseline

| Measure | July 2026 (prior) | October 2026 (this run, `audit/TOOLS.md`) |
|---|---|---|
| Tests | 601 passing | 1,898 collected, 1,896 passed, 2 skipped, 0 failed |
| ruff | clean | clean at CI scope (`spectre/ tests/`); 3 at whole tree; 432 under the house rule set |
| mypy strict | clean | clean on `spectre tle_clustering` (72 files); 536 errors in `tests/` (ungated) |
| bandit | no medium or high | none at CI scope; 1 High and 3 Medium outside `spectre/` |
| Branch coverage | not recorded | 70.96 % |

**Judgement note, as PRIORS.md asks.** The suite has tripled and every scoped gate is green. Measured against the three things PRIORS.md says to judge by:
● **Claims-ledger drift:** phase 4 count, see `audit/CLAIMS.md`.
● **Solvers without a reference-case gate:** at least 2 on the critical path (Hohmann weakly gated, bi-elliptic ungated), plus vis-viva. More may come from the S01 and S02 slices.
● **Mutation evidence:** a fully green suite of 1,896 tests did not notice a reintroduced July defect (P3).
Static cleanliness and correctness remain different properties.

## Final mapping after phase 7

Each provisional candidate (P-F1 to P-F10) raised above went through refutation, folded into the matching slice or orchestrator finding. Where refutation changed the severity this file proposed, the refuted severity governs and the change is shown.

| Prior | Provisional | Origin ID | Final ID | Verdict | Severity proposed here → final | Subject |
|---|---|---|---|---|---|---|
| P1 | P-F1 | F-S01-13 | F-068 | CONFIRMED | Medium → Medium | function docstring still credits Izzo |
| P1 | P-F1 | F-S10-01 | F-173 | CONFIRMED | Medium → Medium | docs place the Lambert solver in transfers.py |
| P2 | P-F2 | F-S05-02 | F-034 | CONFIRMED | High → High | Decision Engine constants presented as computed |
| P3 | P-F3 | F-S00-02 | F-058 | CONFIRMED | Medium → Medium | July fix ungated (mutation-proven) |
| P3 | P-F4 | F-S06-12 | F-234 | CONFIRMED | Medium → Low | silent regime assumptions in the sweep |
| P4 | P-F5 | F-S00-03 | F-059 | CONFIRMED | Medium → Medium | Secure flag ungated at the call site |
| P5 | P-F6 | F-S07-01 | F-044 | CONFIRMED | High → High | UDL password process-global, outlives the session |
| P5 | P-F6 | F-S08-03 | F-148 | CONFIRMED | High → Medium | delete, reset and expiry never clear SessionState |
| P6 | P-F7 | F-S05-17 | F-121 | CONFIRMED | Medium → Medium | no code version or input identity on outputs |
| P7 | P-F8 | F-S01-23 | F-194 | CONFIRMED | Medium → Low | R_EARTH literal duplicated |
| P7 | P-F8 | F-S05-22 | F-232 | CONFIRMED | Medium → Low | dead 6371.0 km constants |
| P8 | P-F9 | F-S10-32 | F-293 | CONFIRMED | Medium → Low | STK COM notes read as live guides |
| P9 | P-F10 | F-S01-21 | F-070 | CONFIRMED | High → Medium | only Lambert pinned to a reference; Hohmann banded, bi-elliptic unpinned |

Corrections to the provisional grading above, fact:
● P-F8 (Earth radius) was proposed as Medium. Both refuters graded the duplicates Low, because the two divergent 6371.0 km constants are dead (one occurrence each), so no live calculation diverges today. Low governs.
● P-F4 (silent regime assumptions) was proposed as Medium. Refuter R3 showed by execution that an unreadable red TLE also fails in every solver, so no entry is scored against a wrong regime. Only the misleading skip message remains. Low governs.
● P-F10 (solver gates) was proposed as High. The refuter graded the test gap Medium. The confirmed numerical Blockers in `audit/FINDINGS.md` are the consequence of that gap, and they are graded on their own.
● P-F9 (STK notes) was proposed as Medium. Refuter R5 confirmed it and graded it Low, without stating a reason for the grade. The orchestrator agrees with Low on its own evidence (fact): the notes sit in `docs/`, which the packaging script strips (`scripts/package-appstore.sh:171,215`), so no deployer or operator receives them. R5 also found `SPECTRE_logo.svg:226` reading "STK INTERCEPT". Low governs.
● P-F6 has two parts. The process-global credential holder (F-S07-01) stays High. Deleting a user without clearing their state (F-S08-03) was graded Medium by refuter R4b, against the other R4 pass's High; R4b's grading is adopted, with the reason in `audit/REFUTATION.md`.
