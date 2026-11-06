# 03. Conceptual scrutiny, framework sections 1a to 1h

**Subject:** commit `ddba577`. Each check from framework section 1 is put as a question and answered from the code. Tags: Fact (read in code or seen in output), Inference (reasoned from facts; the reasoning is given), Speculation (unverified; what would confirm it is named). Findings raised here are numbered F-10 onward; F-01 to F-09 are the gate gaps in `02-gate-assessment.md`. Every finding below is re-tested by the Phase 4 probe named against it.

## 1a. Payoff matrix construction

● **Are adversary courses of action exhaustive, with a residual row, and mutually exclusive?** No. Fact: rows are whatever the operator enters or the sweep pre-fills (`decision.py:787-825`; `decision_from_sweep.py`); no residual "other" row is created and no check requires the rows to exclude each other or P to sum to 1. Wherever P is read it is divided by the sum over the rows entered (`decision.py:3635-3642`; `tree_selectors.py:155-157`). See F-12.
● **Are "do nothing" and "collect more information" explicit responses?** Not enforced. Fact: NO_ACTION and SENSOR_RETASK exist as response types (`decision.py:208-212`) but the response set is the operator's; a scenario can omit both. Collections from the threat picture are listed beside the ranking and never scored (`decision.py:1636-1645`), a deliberate design choice recorded as owner ruling (`.board/README.md`, 2026-11-05).
● **Does every cell trace to a propagated figure or a labelled lookup?** Yes for the figures, no for the judgement inputs. Fact: each figure carries computed, sampled or lookup (`provenance.py:55-75`). Response cost, reversibility and time to execute are operator judgements (`decision.py:854-857`) that enter the score (`decision.py:2049-2069`) with no judgement tag. Gate G5, finding F-05.
● **Is minimax presented as a prediction or an equilibrium?** Mostly not; one document overstates it. Fact: the panel labels minimax "cautious, best worst case" (`decision_panel.html:296`); the tree text says "Red is taken to choose each move against us" (`tree_selectors.py:33-37`); the result banner reads "Heuristic ranking" (`decision_results.html:80`). The operator guide calls it "game-theoretic scenario evaluation" (`docs/generate_guide.py:399`). Mixed strategies are not considered anywhere and the limitation is not documented. See F-15.

## 1b. Multi-criteria weighted scoring

● **How were the weights elicited?** They were not. Fact: defaults 0.35, 0.25, 0.20, 0.10, 0.10 (`decision.py:1465-1470`), described in code as uncited (`decision.py:264-265`, `:293-297`; backlog SPC-151). No swing-weighting record exists in the repository. See F-16.
● **Does normalisation depend on the current set of alternatives (rank-reversal exposure)?** Not for responses; yes for adversary rows. Fact: criteria use fixed scales: closest approach over 0 to 50,000 km, delta-V over 0 to 0.1 km/s, time over the horizon (`decision.py:1919-1921`, `:2044-2069`). Weights are rescaled to sum to 1 (`routes/decision.py:589-594`), which is scale-invariant. But expected value divides each row's P by the sum of P over the rows entered (`decision.py:3635-3642`), so adding an adversary row changes every row's weight. Framework 1b's mechanism does not apply to responses (deviation); an adversary-side analogue does. Probe 3 and probe 3b test both. See F-12.
● **Are the fixed scales fit for the decision?** No. Fact: the closest-approach term is linear over 0 to 50,000 km (`decision.py:2044-2046`), so a 1 km and a 100 km miss differ by 99 / 50,000 × 0.25 = 0.000495 in score at the default weight; a 1 m/s burn adds 0.001 / 0.1 × 0.20 = 0.002. Inference: at operational miss distances the score is nearly blind to closest approach, the quantity behind the operator's first question ("can it reach one of mine"), and a response that spends 1 m/s to move a miss from 1 km to 100 km scores worse than doing nothing on that criterion pair. The delta-V term saturates at 100 m/s (`decision.py:2059`), so burns above it cost the same. See F-10. Probe 17 demonstrates it.
● **Is additive independence plausible?** Inference: no. The score adds custody loss and closest approach independently (`decision.py:2057-2068`); a close approach while custody is lost is operationally worse than the sum of the two, and the model cannot express that. See F-20.
● **Are hard constraints applied before aggregation?** No constraint mechanism exists. Gate G4, finding F-04.
● **Is weight sensitivity shown?** No. Fact: sensitivity is computed only for P, under expected value (`decision.py:3712-3752`, `:3801-3816`). See F-16.

## 1c. Decision rules

● **Is each rule applied with the right orientation?** Yes in code. Fact: scores are costs, higher worse (`decision.py:2050`); minimax minimises the per-response maximum, minimin the per-response minimum (`decision.py:3615-3626`). The earlier mislabelling of minimin as "maximin" was fixed under audit F-S05-01 (`decision.py:217-219`). Probe 1 confirms against hand-computed answers.
● **Are ties handled neutrally?** No. Fact: `min` over response indices returns the first response on a tie (`decision.py:3618`, `:3626`, `:3643`); the tree does the same (`tree_selectors.py:164`). Inference: the recommendation can depend on the order the operator typed the responses; probe 5 tests it. See F-13.
● **Can the rule be changed after results are seen, and are all rules shown?** Yes, and no. Gate G3, finding F-03.
● **Are minimax regret, info-gap or other robustness measures offered?** No. Fact: not present in `decision.py` or `tree_selectors.py`. Recorded under L1; no separate finding, since the framework treats it as a level 4 descriptor.
● **Is expected value guarded when P is not credible?** Partly. Fact: when a row's P is untouched at 0.5, or no current threat picture backs it, the result says so and names minimax's pick, without switching rule (`decision.py:1507-1511`, `:1704-1712`).

## 1d. Game tree

● **How are leaves valued, and is the horizon stated?** Fact: each path's closest approach runs to the end of the span searched "as if no one moves again", and its score is the one-turn weighted sum on the path figures, labelled lookup (`decision_tree.py:9-14`). The span and turn count are stated in every rule sentence (`tree_selectors.py:33-48`). Inference: the static continuation after turn 3 is the horizon effect the framework names; with at most 3 turns and figures carried to the span's end, it is bounded and disclosed. See F-21 (Low).
● **What adversary model is used?** Fact: worst case under minimax, P-weighted under expected value, best case under minimin (`tree_selectors.py:184-193`). No backward induction of a rational red; no bounded-rational model. Stated in the rule sentences.
● **Does depth 1 reproduce the matrix?** By design: Fact, turn 1 is the matrix (`decision_tree.py:1-4`; D1 in `docs/decision_engine_phases.md`). Probe 7 tests it.
● **Is pruning used?** No. Fact: full enumeration under a 1,000-branch cap (`decision_tree.py:121`, `:499-507`). Pruned and unpruned are the same search; probe 7 records this.

## 1e. Bayesian updating

● **Are priors recorded with a source?** Partly. Fact: a row's P is the operator's (labelled "your own", `decision.py:1514`) or an applied NOTSO suggestion with its basis line and a Garwood 95 in 100 interval (`notso_prior.py:185-207`; `decision.py:1517-1527`). The default 0.5 is flagged as untouched (`decision.py:1507-1511`).
● **Is the likelihood specified and justified?** Specified, not calibrated. Fact: a 0 or 1 likelihood from the custody rule, stated on screen as "the custody rule, not calibrated against any outcome, so the update is a lookup" (`turn_update.py:1-17`, `:47-55`). See F-22.
● **Are correlated observations treated as independent?** Not applicable. Fact: one observation, stated by the operator for turn 1, enters the update (`turn_update.py:190-212`). Framework 1e's double-counting concern cannot arise as built (deviation). Probe 9 confirms a repeated observation cannot be entered.
● **Numerics and calibration?** Fact: the posterior is a ratio of at most 5 shares; no calibration evidence (Brier score or reliability) exists in the repository. See F-22. Probe 8 checks the arithmetic.

## 1f. Value of information and collect first

● **EVPI or EVSI?** Neither. Fact: a cue's value is the band steps of the Threat range it would remove on a benign and a hostile hypothetical outcome, per hour of collection (`threat_understanding.py:1909-1926`). No probability is placed on the outcomes, so there is no expectation (deviation: framework 1f and probe 10's EVSI ≤ EVPI test do not apply as written; probe 10 is recast).
● **Is the advice tied to the decision it informs?** No. Fact: the advice tests whether the Threat range straddles a fixed action line, `Band.HIGH`, "tuned, not sourced" (`threat_understanding.py:1943-1945`, `:2009-2041`), and the sentence calls that line the band "where your response changes" (`threat_understanding.py:2021`). Nothing derives the line from the outcome matrix or checks that the engine's recommended response differs on the two outcomes (`ThreatPicture.advice`, `decision.py:1418-1420`). Inference: the engine can advise collecting when no outcome would change its own recommendation, or act on the ceiling when one would. See F-14.
● **Are delay cost and closing manoeuvre windows modelled?** As a hard deadline only. Fact: a cue counts only if it lands by decide-by (`threat_understanding.py:1981-1994`); decide-by is the fastest credible arrival minus a response time (`decide_by.py:117-148`) whose default of 12 h is "Claude's choice, not a ruling ... Tuned, not sourced" (`decide_by.py:10-16`, `:47`). No continuous loss from delay. See F-23 for the response time.

## 1g. Physics inputs

● **Does SGP4 output feed a collision-related payoff?** Yes. Fact: a computed cell's closest approach is the SGP4 miss for both orbits with no burn, unrounded, as a point value (`decision.py:3383`). No collision probability is computed anywhere in the engine (deviation: probe 11 is recast to the P5 miss estimate).
● **Does element-set age drive an error model on that payoff?** No. Fact: the age model (1 km plus 2 km a day in LEO, 2 km plus 1 km a day at GEO, `along_track.py:28-36`) reaches only the time-of-closest-approach uncertainty (`elset_approach.py:46-52`, `:147-148`; `decision_figures.py:36-41`) and the staleness refusal. The Monte Carlo samples burn magnitude, pointing, timing and B* only (`monte_carlo.py:124-210`, `:244-253`), never the initial state (`decision.py:1875`: "element-set error is not in it"). Inference: a 3-day-old LEO element set carries about 7 km of along-track error by the model the code itself uses, which can exceed the sampled P5 to P95 spread and is absent from the payoff. See F-11.
● **RK45 tolerances and force model?** Fact: rtol 1e-8, atol 1e-10 (`monte_carlo.py:516-517`); two-body, J2 and exponential drag only (`monte_carlo.py:357-395`). The module claims "At 48 h, the MC uncertainty envelope from ΔV variation dominates over force-model error, so high-fidelity ephemeris is unnecessary" (`monte_carlo.py:24-26`); no test or document supports the claim. Speculation: true for large burns, false for small ones; probe 13 measures integrator error, and a force-model comparison is out of reach without a higher-fidelity propagator installed. See F-19.
● **Are Monte Carlo intervals reported, and how is a zero-hit result reported?** Fact: P5, P50 and P95 with a 95 % bootstrap half-width, and "converged" only when the half-width is within 1 km or 5 % of P5 (`monte_carlo.py:601-651`; `decision.py:1156`). There is no hit count, since no Pc is estimated. Probe 11 measures P5 spread across seeds and N.
● **Are propagated and lookup figures mixed?** Within a cell, yes and labelled: a computed cell keeps lookup custody and delta-V unless sized (`decision.py:3380-3383`). Across a matrix, no cell mixes propagators (`_require_one_propagator`, `decision.py:1140-1145`).

## 1h. End-to-end uncertainty propagation

● **Is there an outer loop over inputs, weights and priors?** No. Fact: no code perturbs weights or payoff inputs and re-ranks. The one propagation is P across its NOTSO interval under expected value (`decision.py:3712-3752`). No probability that each response ranks first is computed. See F-16 and F-11.
● **Does any input uncertainty reach the operator?** Burn dispersion does (sampled bands), element-set age does for TCA only, P interval does under expected value. Weight uncertainty and element-set error in the miss do not.

## Findings raised in this phase

```
F-10 | Critical | Fact (code) and Inference (decision impact) | §1b, L1, L2
Location: spectre/domain/decision.py:1919-1921, :2044-2069; probe P-17
Observation: closest approach enters the score linearly over 0 to 50,000 km at weight 0.25, so a 1 km and a 100 km miss differ by 0.000495; one m/s of our delta-V adds 0.002. Delta-V saturates at 100 m/s.
Decision impact: at the miss distances that matter, the ranking is driven by delta-V, custody and the response's own cost terms, so a response that buys a large increase in miss distance for a small burn can be ranked below doing nothing; burns above 100 m/s are indistinguishable.
Remediation: replace the linear term in _norm_ca with a threshold-anchored value function (for example piecewise or logarithmic, anchored at an operator-set keep-out distance), and re-anchor the delta-V scale; both in spectre/domain/decision.py, with the reference cases in tests/unit/test_decision_reference_cases.py re-derived.
Closing evidence: probe P-17 inverted (a 1 m/s burn that moves the miss from 1 km to 100 km ranks first), plus a written rationale for each scale signed by the technical authority.

F-11 | High | Fact | §1g, §1h, L2, L3
Location: spectre/domain/decision.py:3383, :1875; spectre/astro/monte_carlo.py:124-253; spectre/astro/along_track.py:28-36
Observation: the closest-approach payoff is an SGP4 point miss (computed cells) or a P5 over burn dispersions only (sampled cells); element-set error, which the code's own model puts at 1 km plus 2 km a day in LEO, never enters it.
Decision impact: the payoff and its band read tighter than the inputs justify; for element sets more than a day or two old the omitted error can exceed the displayed spread and change which response is safest.
Remediation: sample the initial state from the along_track error model in run_separation_series (spectre/astro/monte_carlo.py), or add the model's position error in quadrature to computed misses in _computed_cell (spectre/domain/decision.py), and state it on screen.
Closing evidence: a test showing the sampled band widens with element-set age at the model's rate, and the cell text naming the element-set error included.

F-12 | High | Fact | §1a, §1b, L1
Location: spectre/domain/decision.py:3631-3644; spectre/domain/tree_selectors.py:155-157; probe P-03b
Observation: expected value divides each row's P by the sum of P over the rows entered; there is no residual row and no check that rows are mutually exclusive or that P sums to 1.
Decision impact: adding an unrelated adversary row reweights every other row and can flip the expected-value pick; overlapping rows double-count.
Remediation: require P to sum to at most 1 with an explicit residual "other or unmodelled" row carrying the remainder, scored at its worst case, in spectre/web/routes/decision.py and Scenario.__post_init__ (spectre/domain/decision.py).
Closing evidence: probe P-03b showing the pick unchanged when a row with P 0 is added, and a refusal when P sums above 1.

F-13 | Medium | Fact | §1c, L1
Location: spectre/domain/decision.py:3618, :3626, :3643; spectre/domain/tree_selectors.py:164; probe P-05
Observation: ties go to the first response in entry order.
Decision impact: two responses that score the same are reported as one recommendation chosen by typing order, with no tie shown.
Remediation: detect ties (within a stated tolerance) in find_robust_response and _Selector.value and show every tied response.
Closing evidence: probe P-05 passing with a permuted tie, and the tie stated on screen.

F-14 | High | Fact (code) and Inference (decision impact) | §1f, L1, L3
Location: spectre/domain/threat_understanding.py:1909-1926, :1943-1945, :2009-2041; spectre/domain/decision.py:1418-1420
Observation: collect-first advice measures band steps of Threat range per hour against a fixed action line (HIGH, tuned, not sourced) that the sentence calls the band "where your response changes"; it never consults the outcome matrix.
Decision impact: the advice can recommend collecting when no outcome would change the engine's own recommendation, or say act now when one would; the operator is told a line is decision-relevant without evidence.
Remediation: derive decision relevance from the matrix: evaluate the recommended response under each cue outcome's threat assumption, in spectre/domain/decision.py, and drop the asserted "where your response changes" wording in threat_understanding.py until it does.
Closing evidence: a test where a cue that cannot change the pick yields no collect-first advice, and one that can, does.

F-15 | Low | Fact | §1a, L1, L5
Location: docs/generate_guide.py:399
Observation: the operator guide describes the engine as "game-theoretic scenario evaluation"; mixed strategies are not computed and the limitation is not stated.
Decision impact: a reader may take the recommendation for a game solution rather than a guaranteed-floor heuristic.
Remediation: reword docs/generate_guide.py:399 and the Decision Engine section to "decision analysis: worst-case floor, best case and expected value over operator-entered rows", and state that randomised responses are not considered.
Closing evidence: the regenerated guide with the new wording.

F-16 | High | Fact | §1b, §1h, L1, L3
Location: spectre/domain/decision.py:1465-1470, :264-265, :3712-3752
Observation: default weights are uncited direct ratings; no weight-stability interval or rank-first probability is computed; sensitivity exists for P only.
Decision impact: the operator cannot see how close the recommendation is to changing under a plausible weight change.
Remediation: compute, per recommendation, the smallest single-weight change that changes the pick (the weights are linear, so it is exact) in spectre/domain/decision.py, and show it beside the recommendation; record a swing-weight elicitation (SPC-151).
Closing evidence: the stability line on screen and probe P-16 matching it.

F-19 | Medium | Speculation | §1g, L2
Location: spectre/astro/monte_carlo.py:24-26, :357-395, :516-517; probe P-13
Observation: the force model is two-body, J2 and exponential drag; the module asserts that burn dispersion dominates force-model error at 48 h without evidence.
Decision impact: for small hypothesised burns the omitted forces could dominate the spread and bias the miss.
Remediation: test the claim against a higher-fidelity propagator for representative LEO and GEO cases and state the regime in which it holds, in tests/ and the module docstring.
Closing evidence: a comparison table by regime and burn size.

F-20 | Low | Inference | §1b, L1
Location: spectre/domain/decision.py:2057-2068
Observation: custody loss and closest approach are added independently.
Decision impact: a close approach during lost custody scores as the sum of two moderate penalties, not as the compound risk it is.
Remediation: document the independence assumption; if the analyst session (SPC-080) confirms an interaction, add an interaction term.
Closing evidence: the documented assumption, or an elicited interaction term with its test.

F-21 | Low | Fact | §1d, L1
Location: spectre/domain/decision_tree.py:9-14
Observation: leaves are valued as if no one moves after the last turn; at most 3 turns.
Decision impact: a response that sets up a poor position after turn 3 is not penalised; the limit is stated on screen.
Remediation: none required beyond keeping the statement; record it in the limitations of the guide.
Closing evidence: the guide's limitations section naming it.

F-22 | Medium | Fact | §1e, L3, L4
Location: spectre/domain/turn_update.py:1-17, :47-55
Observation: the update's likelihood is a deterministic custody rule, stated as uncalibrated; no calibration evidence exists.
Decision impact: the posterior shares shown under expected value have no demonstrated reliability.
Remediation: back-test the custody likelihood on historic manoeuvre detections (NOTSO cache and element-set histories already held) and report a Brier score.
Closing evidence: a calibration report in docs/ with its data and code.

F-23 | Medium | Fact | §1f, L1
Location: spectre/domain/decide_by.py:10-16, :47
Observation: decide-by uses a 12 h default response time chosen by the developer, "tuned, not sourced".
Decision impact: every decide-by and every collect-first deadline shifts with this unsourced figure until the operator sets their own.
Remediation: require the operator to set a response time before decide-by is shown, or source the default from the customer's own timelines.
Closing evidence: a cited default, or a test that no decide-by renders without an operator-set response time.
```
