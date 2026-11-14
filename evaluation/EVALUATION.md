# Independent evaluation of the SPECTRE decision-analysis engine

**Subject:** commit `ddba577829b6de0a924d76c82077931cd2ba69f8`, version 0.24.2. **Yardstick:** `evaluation/framework/decision-engine-evaluation-framework.md`. **Date:** 6 November 2026.

## 1. Bottom line up front

**Verdict: Fail.** 9 of 10 gates are Red and none Amber. The overall score is **1.68** out of 5, in the Not ready band. Neither result moves under any weight variation tested.

The five findings that matter most:
● **F-10 (Critical).** The score is nearly blind to miss distance: 1 m/s of our delta-V weighs the same as 400 km of closest approach (probe P-17).
● **F-04 (Critical).** No veto exists, so a response that is unacceptable on legal, rules-of-engagement or safety grounds is still recommended if it scores best.
● **F-01 and F-02 (Critical).** Nothing records the operator's decision, and no stored record exists to replay a recommendation from.
● **F-25 (Critical).** Element sets from the Unified Data Library (UDL) are never checksum-checked. A one-digit corruption moved a computed miss from 10.4 to 13.4 km with no flag.
● **F-14 (High).** Collect-first advice cannot change the recommendation, because the threat picture moves no figure (probe P-10). The operator is still told their response "changes" at HIGH.

The engine computes correctly what it sets out to compute. The rules, posterior arithmetic and SGP4 all match independent references (P-01, P-08, P-12). Its weakness is what it is asked to compute, and what it fails to record.

**Single most important action:** replace the closest-approach value function (F-10). Every recommendation rests on it, and no other fix makes the ranking trustworthy.

## 2. Scope and method

● **Method:** Phases 0 to 8 of the brief.
  ■ Phase 0: orient, with a baseline suite run (8,351 passed, 0 failed).
  ■ Phase 1: architecture map, confirmed by the owner.
  ■ Phase 2: gates.
  ■ Phase 3: conceptual scrutiny.
  ■ Phase 4: 18 probes, 54 probe tests.
  ■ Phases 5 and 6: scoring and a rubric self-test.
  ■ Phase 7: remediation backlog.
● **Phase files:** `01-architecture-map.md`, `02-gate-assessment.md`, `03-conceptual-scrutiny.md`, `04-test-evidence.md`, `05-scorecard.md`, `06-rubric-sensitivity.md`, `07-remediation-backlog.md`. Raw evidence is in `evidence/`.
● **Delegated work:** the physics probes (P-11 to P-14) were run by a separate assessor with a bounded deliverable. The lead assessor re-checked their decisive claims against the code and the raw output (`evidence/physics/SUMMARY.md`).
● **Not visible in this repository.** Each gate or lens below is scored on the evidence rule but labelled provisional, and the named artefact would change it:
  ■ hazard log and safety-related determination (G8, L6);
  ■ an engine threat model to ISN 2023/09 (G9, L7);
  ■ the JSP 936 scoping decision and ethical risk assessment (L8);
  ■ any weight-elicitation record (L1, F-16).
● **Not done:**
  ■ a 72 h, N 400 run of P-11 (cost);
  ■ force-model truth, because no third-body propagator is installed;
  ■ inter-assessor scoring.

## 3. Gate table

| Gate | Rating | Basis (detail in `02-gate-assessment.md`) |
|:-|:-|:-|
| G1 Advisory, decision recorded | Red | Advisory: every outbound call is a UDL GET. Record: none (F-01) |
| G2 Reproducible from a stored record | Red | Repeatable (P-15) but nothing stored (F-02) |
| G3 All rules shown, disagreement flagged | Red | One rule, chosen after results (F-03) |
| G4 Vetoes before aggregation | Red | No veto input exists (P-06, F-04) |
| G5 Provenance tags | Red | Basis tags on every figure; no judgement tag; lookups unsourced; no dated plan (F-05) |
| G6 Uncertainty or "not quantified" flag | Green | Every figure carries a basis or "no distribution" (P-18) |
| G7 SGP4 and RK45 verified | Red | P-12 passes and P-13 measures the RK45 error, but neither is in the repository's suite (F-06) |
| G8 Hazard analysis | Red | Not visible (F-07, provisional) |
| G9 Threat model and integrity | Red | No engine threat model; UDL sets unchecked; permissive CSP (F-08, F-25) |
| G10 Operating envelope | Red | Detection present; no stated envelope; deep-space and decayed objects pass silently (F-09) |

Rule applied: the framework leaves "substantially met, no dated and owned plan" undefined. Such gates (G5, G7, G10) are rated Red, and labelled with their distance to Amber (deviation 3).

## 4. Lens scorecard

| Lens | Weight | Level | One-line justification | Evidence |
|:-|:-|:-|:-|:-|
| L1 Decision model | 15 | 2 | Assumptions and sets documented, weights recorded without method; no vetoes, one rule shown, closest approach inert | `decision.py:2044-2069`; P-06, P-17 |
| L2 Input fidelity | 12 | 2 | Tags exist but incomplete; checks outside the suite; element-set error absent; UDL unchecked | `provenance.py:55-75`; P-12, P-14 |
| L3 Uncertainty | 13 | 2 | Intervals shown; element-set error and weight stability not propagated or shown | `decision.py:1156`, `:3712-3752`; P-16 |
| L4 V&V | 15 | 2 | Large developer suite, reference cases, mutation run; no metamorphic or vector suite, no Aqua Book record | `evidence/baseline-tests.log` |
| L5 Human-in-the-loop | 15 | 1 | One rule's answer; no decision record | `decision_job.py:240-248` |
| L6 Safety | 10 | 1 | No hazard analysis visible (provisional) | `audit/GAPS.md:12` |
| L7 Security | 8 | 2 | Trust-boundary inventory and remediated audit; no ISN 2023/09, permissive CSP | `audit/ARCHITECTURE.md:56-66`; `app.py:298` |
| L8 Governance | 7 | 1 | No AI scoping decision recorded (provisional) | search for JSP 936: no match |
| L9 Efficiency | 5 | 2 | Runtime measured and used to set the budget; no decision window stated | `decision.py:2088-2106` |

**Score:** 1.68, reproduced by `python evaluation/score.py`. **Band:** Not ready. **Verdict:** Fail.

**Sensitivity (`06-rubric-sensitivity.md`):** the verdict and the band held in all 20 weight runs, which scored 1.62 to 1.74. A uniform one-level shift in judgement would move the band to Conditional (2.68).

## 5. Findings register

Ordered Critical, High, Medium, Low. IDs F-28 and F-37 are unused: they were merged into F-19 and F-06.

```
F-01 | Critical | Fact | G1, L5
Location: spectre/web/decision_job.py:240-248; spectre/web/planning_state.py:31, :163; spectre/web/models.py:51
Observation: a finished evaluation is held in session memory and logged as one line naming the recommendation; nothing records what the operator decided or why.
Decision impact: after a decision no one can show what the operator saw, chose or rejected; accountability rests on memory.
Remediation: a durable decision record (new table in spectre/web/models.py) written by spectre/web/routes/decision.py, capturing the operator's decision and rationale on the results page.
Closing evidence: a stored record per evaluation, retrievable after sign-out, holding the operator's decision; a test.

F-02 | Critical | Fact | G2, L4
Location: spectre/domain/decision.py:3939-3942; spectre/domain/provenance.py:84-122; spectre/web/planning_state.py:231; probe P-15
Observation: provenance hashes the inputs but stores none; the result lives at most the 8 h sign-in. Identical inputs repeat exactly (P-15), but there is nothing to replay from.
Decision impact: a recommendation cannot be reproduced for review, incident analysis or V&V once the session ends.
Remediation: store canonical inputs (element sets as fetched, rows, responses, weights, rule, seeds, code version) with the record; add a replay command.
Closing evidence: a replay test reproducing a stored recommendation exactly from the record alone.

F-03 | Critical | Fact | G3, L1, L5
Location: spectre/domain/decision.py:3584-3628, :1704-1712; spectre/web/routes/decision.py:581-586; spectre/web/templates/partials/decision_panel.html:293-296
Observation: one rule per evaluation, chosen on the panel and changeable after a result is seen; minimax's pick is named only when expected value is judged unearned; no disagreement flag.
Decision impact: an operator can choose the rule that gives the answer they prefer, and is not told when the cautious and probability-weighted picks differ.
Remediation: compute all three picks in every ScenarioResult and show them side by side with a disagreement line in decision_results.html; set a primary rule per deployment before use.
Closing evidence: the page showing three picks; a disagreement test; the configuration record.

F-04 | Critical | Fact | G4, L1
Location: spectre/domain/decision.py:849-874, :2049-2069, :3584-3628; spectre/domain/tree_selectors.py:184-193; probe P-06
Observation: no field can mark a response unacceptable; every response enters a compensatory weighted sum.
Decision impact: a response that breaks a legal, rules-of-engagement or safety constraint is recommended whenever it scores best.
Remediation: a veto with a stated reason on FriendlyResponse and scenario-level constraints, applied before find_robust_response and the tree selectors; vetoed responses shown greyed with the reason.
Closing evidence: probe P-06 written as specified and passing.

F-05 | Critical | Fact | G5, L2
Location: spectre/domain/provenance.py:55-75; spectre/domain/decision.py:854-857, :1912-1921; spectre/web/templates/partials/decision_results.html:240-253
Observation: every figure is tagged computed, sampled or lookup, but operator judgements (cost, reversibility, time to execute, P, weights) carry no judgement tag, lookup constants carry no source, owner or date, and the code version is never shown.
Decision impact: an operator cannot tell physics from opinion in the inputs to a recommendation.
Remediation: Basis.JUDGEMENT for operator-entered values; a lookup register in docs/ with source, owner and date; the code version on the results page.
Closing evidence: every figure on the page tagged one of four; the register.

F-06 | Critical | Fact | G7, L2, L4
Location: tests/ (no use of SGP4-VER.TLE, tcppver.out or RK45_RTOL); spectre/astro/monte_carlo.py:516-517; probes P-12, P-13
Observation: no repository test pins SGP4 to the published vectors or the production RK45 to a reference. The evaluation's probes show SGP4 within 9.8e-6 km of the vectors and RK45 up to 0.652 km from a tight reference at 72 h in LEO.
Decision impact: a propagation regression would pass CI unnoticed.
Remediation: adopt P-12 and P-13 into tests/unit with fixed thresholds, run in CI.
Closing evidence: both tests green in CI.

F-07 | Critical | Fact (absence); provisional | G8, L6
Location: not visible in repository (docs/, audit/ and root documents searched); audit/GAPS.md:12
Observation: no hazard analysis or safety-related determination; the audit left the operational status of the engine as "a product and safety call".
Decision impact: outputs that can inform a manoeuvre decision have no recorded judgement of the harm wrong advice could cause.
Remediation: hazard identification, a hazard log and a safety-related determination under Def Stan 00-056, owned by the safety lead.
Closing evidence: the hazard log and the signed determination.

F-08 | Critical | Fact | G9, L7
Location: audit/ARCHITECTURE.md:56-66; spectre/web/app.py:280-298; spectre/web/templates/partials/decision_results.html:311-327, :408-442
Observation: a trust-boundary inventory exists, not an engine threat model; no ISN 2023/09 artefacts; the Content Security Policy allows 'unsafe-inline' and 'unsafe-eval'; weights and rule are per-request values protected only by CSRF.
Decision impact: tampered inputs or configuration would produce confident wrong advice with no control designed to catch it.
Remediation: an engine threat model against ISN 2023/09; a nonce-based policy with the inline scripts moved to static files.
Closing evidence: the threat model; a policy without 'unsafe-inline' and 'unsafe-eval'; tests.

F-09 | Critical | Fact | G10, L2
Location: spectre/domain/decision.py:1245-1330, :2262-2347; spectre/web/elsets.py:27, :77-80; probe P-14
Observation: many out-of-envelope inputs are detected and refused in sentences, but no operating design domain is stated, and deep-space and decayed objects pass silently.
Decision impact: the operator is not told when the engine is outside the conditions it is fit for.
Remediation: an operating design domain in docs/, checked at evaluation entry with a flag per breach (with F-29 to F-31).
Closing evidence: the document and a test per breach.

F-10 | Critical | Fact (code and probe) | §1b, L1, L2
Location: spectre/domain/decision.py:1919-1921, :2044-2069; probe P-17
Observation: closest approach enters the score linearly over 0 to 50,000 km at weight 0.25; 1 m/s of our delta-V weighs the same as 400 km of miss. Delta-V saturates at 100 m/s: 100 and 500 m/s score the same.
Decision impact: a 1 m/s burn that moves a miss from 1 km to 100 km ranks below doing nothing (P-17); the ranking ignores the quantity behind the operator's first question.
Remediation: a threshold-anchored value function in _norm_ca, anchored at an operator-set keep-out distance; a re-anchored delta-V scale; reference cases re-derived.
Closing evidence: P-17 inverted; a scale rationale signed by the technical authority.

F-25 | Critical | Fact (code and probe) | G9, L2, L7
Location: spectre/web/routes/udl.py:184-225; spectre/web/routes/operator.py:178-190, :239-251; spectre/web/elsets.py:147-167; probe P-14
Observation: element sets from UDL reach the engine with no checksum or range check (tle_checksum_valid is called only at operator.py:104). A one-digit corruption reached BoundElset and moved a computed miss from 10.4 to 13.4 km unflagged; the background refresh replaced a good held set with it.
Decision impact: a corrupted or tampered element set silently changes figures and can change the recommendation.
Remediation: checksum and field range checks in spectre/web/elsets.py on every ingest path; on failure refuse and keep the held set.
Closing evidence: P-14's UDL case inverted; a test per path.

F-11 | High | Fact | §1g, §1h, L2, L3
Location: spectre/domain/decision.py:3383, :1875; spectre/astro/monte_carlo.py:124-253; spectre/astro/along_track.py:28-36
Observation: the miss payoff is an SGP4 point miss or a P5 over burn dispersions only; element-set error, 1 km plus 2 km a day in LEO by the code's own model, never enters it.
Decision impact: bands read tighter than the inputs allow; for element sets a day or more old the omitted error can exceed the displayed spread and change which response is safest.
Remediation: sample the initial state from the along_track model in run_separation_series, or add it in quadrature in _computed_cell; state it on screen.
Closing evidence: a test showing the band widen with element-set age at the model's rate.

F-12 | High | Fact (code and probe) | §1a, §1b, L1
Location: spectre/domain/decision.py:3631-3644; spectre/domain/tree_selectors.py:155-157; probe P-03b
Observation: expected value divides each P by the sum over the rows entered; no residual row; no check that P sums to 1. A single row at P 0.1 is evaluated exactly as at P 1.0.
Decision impact: a 10 % likely manoeuvre is treated as certain, and the chance that none of the listed actions happens is never weighed.
Remediation: P summing to at most 1 with a residual "none of these" row; the shares used shown beside each P.
Closing evidence: P-03b inverted; a refusal when P sums above 1.

F-14 | High | Fact (code and probe) | §1f, L1, L3
Location: spectre/domain/threat_understanding.py:1909-1926, :1943-1945, :2009-2041; spectre/domain/decision.py:1394-1420; probe P-10
Observation: collect-first advice rests on Threat range band steps against a fixed, unsourced action line, and calls that line where "your response changes". The threat picture moves no figure in the matrix: opposite pictures give an identical matrix and pick (P-10).
Decision impact: the operator is told to delay for a collection that cannot change the engine's recommendation.
Remediation: derive decision relevance from the matrix (the pick under each cue outcome); drop the "where your response changes" wording until then.
Closing evidence: a test that a cue unable to change the pick yields no collect-first advice.

F-16 | High | Fact (code and probe) | §1b, §1h, L1, L3
Location: spectre/domain/decision.py:1465-1470, :264-265, :3712-3752; probe P-16
Observation: default weights are uncited direct ratings; no weight stability is computed or shown. In the bound scenarios a delta-V weight change of 0.089 (0.20 to 0.111), or a reversibility change of 0.082, flips the pick under minimax and expected value.
Decision impact: the operator cannot see that a small, defensible change of judgement reverses the recommendation.
Remediation: show the smallest single-weight change that flips the pick (exact, since the score is linear in the weights); swing-weight elicitation (SPC-151).
Closing evidence: the stability line on screen matching P-16.

F-13 | Medium | Fact (code and probe) | §1c, L1
Location: spectre/domain/decision.py:3618, :3626, :3643; spectre/domain/tree_selectors.py:164; probe P-05
Observation: a tie goes to the response entered first, and the tie is not shown.
Decision impact: two responses equal under the rule are reported as one recommendation chosen by typing order (P-05: X or Y by entry order).
Remediation: detect ties within a stated tolerance and show every tied response.
Closing evidence: P-05's tie case showing both.

F-17 | Medium | Fact | L1, L2
Location: spectre/domain/decision.py:1912-1917, :2007-2041
Observation: the lookup model's relations are unsourced: a sensor retask's custody gap is half its time to execute, a manoeuvre multiplies the closest approach by 1 plus 5 times its cost, delta-V is cost times 0.05 km/s. They are labelled lookup.
Decision impact: unbound recommendations, which P-16 shows can turn on these terms, rest on invented relations.
Remediation: restrict lookup-only results to training, or source each relation through the F-05 register.
Closing evidence: register entries, or an enforced training-only label.

F-18 | Medium | Fact | L5
Location: spectre/web/templates/partials/decision_results.html:231-236, :470
Observation: composite scores are coloured green below 0.25, amber below 0.50 and red above, with no source for the thresholds.
Decision impact: colour implies a safety judgement the score has not earned.
Remediation: remove the colours, or tie them to sourced thresholds.
Closing evidence: the page without unsourced colour bands.

F-19 | Medium | Inference (from probe P-13) | §1g, L2
Location: spectre/astro/monte_carlo.py:24-26, :357-395; probe P-13
Observation: the force model is two-body, J2 and exponential drag; the module asserts burn dispersion dominates force-model error at 48 h. At GEO, RK45 and SDP4 (which has lunisolar terms) part by 11 to 18 km over 48 to 72 h.
Decision impact: for small burns, especially at GEO, the omitted forces can exceed the sampled spread; the effect is largely common to both objects of a close pair.
Remediation: compare against a higher-fidelity propagator by regime and burn size, and state where the claim holds.
Closing evidence: a comparison table by regime.

F-22 | Medium | Fact | §1e, L3, L4
Location: spectre/domain/turn_update.py:1-17, :47-55
Observation: the update's likelihood is a deterministic custody rule, stated as uncalibrated; no calibration evidence exists.
Decision impact: posterior shares under expected value have no demonstrated reliability.
Remediation: back-test the custody likelihood on held histories and report a Brier score.
Closing evidence: a calibration report with its data and code.

F-23 | Medium | Fact | §1f, L1
Location: spectre/domain/decide_by.py:10-16, :47
Observation: decide-by uses a 12 h default response time chosen by the developer, "tuned, not sourced".
Decision impact: every decide-by and collect-first deadline moves with an unsourced figure until the operator sets their own.
Remediation: require an operator-set response time before decide-by shows, or source the default.
Closing evidence: a test, or a cited default.

F-24 | Medium | Fact (absence); provisional | L8
Location: not visible in repository (search of docs/, audit/ and root documents for JSP 936: no match)
Observation: no record of the JSP 936 in-scope decision or an ethical risk assessment.
Decision impact: none directly; weakens assurance at review.
Remediation: record the in-scope decision and complete the ethical risk assessment (framework recommendation 1).
Closing evidence: the recorded decision and assessment.

F-26 | Medium | Fact (code and probe) | L2, L3
Location: spectre/astro/monte_carlo.py:627-639, :1170-1179; spectre/domain/decision.py:1156, :2169-2170; probe P-11
Observation: the half-width shown as how closely P5 is known is the widest of the P5, P50 and P95 half-widths, and also decides convergence; in one case it overstates P5's uncertainty 18 to 45 times.
Decision impact: errs safe but misdescribes P5, and can refuse rows that P5 alone would pass.
Remediation: label P5 with its own half-width; name the convergence figure separately.
Closing evidence: the label equal to P5's half-width; a test.

F-27 | Medium | Fact (probe) | L2, L3
Location: spectre/astro/monte_carlo.py:516-517, :602; probe P-13
Observation: the production RK45 adds up to 0.652 km of position and 0.353 km of separation error at 72 h, unstated, against a 1 km convergence floor.
Decision impact: a band can claim 1 km convergence while integrator error contributes up to a third of it.
Remediation: tighten the tolerances or state the integrator error in the sampled basis note.
Closing evidence: P-13 under 0.1 km at 72 h, or the error stated.

F-29 | Medium | Fact (code and probe) | G10, L2
Location: spectre/web/elsets.py:27, :77-80; spectre/astro/along_track.py:25-36; probe P-14
Observation: deep-space orbits are evaluated with no regime statement; a Molniya-class orbit gets the LEO 24 h staleness limit and the LEO error model.
Decision impact: staleness and TCA uncertainty are misstated for HEO, and the operator is not told SDP4 is in use.
Remediation: regime-specific limits and error rates; flag SDP4 cells.
Closing evidence: a test per regime.

F-30 | Medium | Fact (code and probe) | G10
Location: spectre/astro/elset_approach.py:77-122; spectre/astro/monte_carlo.py:900; probe P-14
Observation: the SGP4 path has no altitude floor; a decayed object between perigee error intervals produced "Computed: 643.1 km ± under 1 s" at 5 to 320 km altitude, unflagged.
Decision impact: a computed miss is shown for an object no longer in orbit; narrow conditions (here a horizon under about 70 min).
Remediation: the RK45 path's altitude floor applied to the SGP4 path.
Closing evidence: P-14's decayed case refused.

F-31 | Medium | Fact (probe) | G10, L1
Location: spectre/web/routes/decision.py:589-594; spectre/domain/decision.py:3631-3643, :1679-1688; probe P-14
Observation: all five weights at 0 are accepted (every score 0); every P at 0 under expected value is accepted; in both the pick follows row order with no flag.
Decision impact: a recommendation with no basis is presented as one.
Remediation: refuse a zero weight total and expected value with zero total P, as the tree already does (turn_update.py:196-197).
Closing evidence: tests for both refusals.

F-15 | Low | Fact | §1a, L1, L5
Location: docs/generate_guide.py:399; probe P-02
Observation: the guide calls the engine "game-theoretic scenario evaluation"; it computes pure-strategy rules only (P-02: pure value 1.0 against a mixed value of 0.5) and does not say so.
Decision impact: a reader may take the output for a game solution.
Remediation: reword to decision analysis with a worst-case floor; state that randomised responses are not considered.
Closing evidence: the regenerated guide.

F-20 | Low | Inference | §1b, L1
Location: spectre/domain/decision.py:2057-2068
Observation: custody loss and closest approach are added independently.
Decision impact: a close approach during lost custody scores as two moderate penalties, not the compound risk it is.
Remediation: document the assumption; add an interaction term if the analyst session supports one.
Closing evidence: the documented assumption or a tested term.

F-21 | Low | Fact | §1d, L1
Location: spectre/domain/decision_tree.py:9-14
Observation: leaves are valued as if no one moves after the last turn (at most 3); stated on screen.
Decision impact: a position that turns bad after turn 3 is not penalised.
Remediation: name it in the guide's limitations.
Closing evidence: the guide text.

F-32 | Low | Fact (probe) | L1
Location: spectre/domain/decision.py:3584-3643; probe P-14
Observation: scores are not checked finite before selection; an injected NaN lookup printed "nan" and the pick followed row order.
Decision impact: needs a code fault to arise; then silent.
Remediation: refuse a non-finite score in find_robust_response.
Closing evidence: a test with an injected NaN.

F-33 | Low | Fact (probe) | L5
Location: spectre/web/routes/decision.py:233-275, :774-778; probe P-14
Observation: a missing row value silently becomes P 0.5, Conf 0.5 or gap 0.7; a missing weight takes its default.
Decision impact: a truncated form evaluates as if the defaults were chosen.
Remediation: refuse missing values.
Closing evidence: a test.

F-34 | Low | Fact (probe) | L2
Location: spectre/web/elsets.py:147-167; probe P-14
Observation: no range check on element-set fields; an inclination of 597.4° produced a computed miss of 356.0 km.
Decision impact: a malformed set yields a figure rather than a refusal.
Remediation: field range checks at ingest, with F-25.
Closing evidence: a test refusing 597.4°.

F-35 | Low | Fact (code and probe) | L2, L4
Location: spectre/astro/monte_carlo.py:253; probe P-11
Observation: the seed is fixed at 42; at N 50 whether a row converges is one draw (15 of 20 seeds in one case).
Decision impact: a row may be refused or sampled by the luck of one seed.
Remediation: show the seed; check convergence on two seeds.
Closing evidence: a test.

F-36 | Low | Fact (probe) | L2
Location: spectre/astro/propagator.py:112; spectre/astro/constants.py:12-18; probe P-12
Observation: SGP4 runs on WGS-72; the RK45 started from its states uses WGS-84 constants; nothing states this.
Decision impact: unquantified, likely small.
Remediation: state the handover and quantify it.
Closing evidence: a note with a measured figure.

F-38 | Low | Speculation | L2
Location: spectre/web/elsets.py:95-98
Observation: an element set dated in the future is given age 0, so it reads as current.
Decision impact: a mis-dated set would pass the staleness check.
Remediation: probe it; if confirmed, refuse future epochs.
Closing evidence: the probe result and a test.
```

## 6. Deviations from the framework

1. **Location of the yardstick.** The brief named `docs/evaluation/`, which does not exist. The owner chose to copy the framework, byte-identical, to `evaluation/framework/`.
2. **No collision probability is computed** (Fact). Probe 11 was recast to measure the stability of the P5 miss estimate, and framework 1g's Pc checks were applied to the miss distance instead.
3. **"Substantially met, no dated and owned plan"** is undefined in section 5.2. Such gates are rated Red, labelled with their distance to Amber.
4. **No EVPI or EVSI** (Fact). Value of information is band steps per hour on two hypothetical outcomes. Probe 10 tests its bound, its response to delay, and whether it can change the decision.
5. **Rank reversal** (framework 1b) does not arise. Scales are fixed, and probe P-03b shows the renormalisation of P is a monotone rescaling. The defect is what P comes to mean (F-12).
6. **One observation enters the update,** so framework 1e's double-counting of correlated observations cannot occur (probe P-09).
7. **Probes added beyond the brief:** P-03b, P-17 and P-18.
8. **Verdict with a failed gate:** the score band is also reported, so the sensitivity runs show more than a constant Fail.

## 7. Limitations of this evaluation

● **Independence:** one assessor, who also built or directed much of this code earlier in the same session. The evidence rule is the control against that, but it does not replace a second assessor. Inter-assessor reliability was not tested (`06-rubric-sensitivity.md`).
● **Provisional ratings:** G8, G9 (in part), L6 and L8 rest on artefacts not visible in this repository.
● **Physics coverage:**
  ■ force-model truth was not available;
  ■ P-11 used 1 h and 6 h windows, not 72 h;
  ■ the future-dated element set (F-38) was not probed.
● **Correction made during the evaluation:** finding F-12 was overstated in Phase 3 and was corrected after probe P-03b. The correction is recorded in `03-conceptual-scrutiny.md`.
● **No engine file was changed.** `git status --short` before the final commit:

```
M evaluation/PROGRESS.md
?? evaluation/07-remediation-backlog.md
?? evaluation/EVALUATION.md
```

Every path is under `evaluation/`.
