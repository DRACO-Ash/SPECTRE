# Evaluating Bluestaq's Decision-Analysis Engine: Scrutiny, Remediation and a Gated Scoring Rubric

Evaluate this engine as a model-based analytical product used for defence decisions, not as "non-AI software": JSP 936 explicitly lists decision support toolsets for course of action (COA) development as in scope, ISO/IEC 22989 classes rule-based and expert systems as AI systems, and the real risks sit in the decision theory and uncertainty handling rather than in machine learning. The evaluation should therefore apply a must-have gate (any Red fails), then score nine weighted lenses at 1 to 5, with the heaviest weight on decision-model soundness, verification and validation (V&V) evidence, and human-in-the-loop explainability.

## TL;DR

- **Scope:** Treat the engine as in scope for JSP 936 (Dependable AI in Defence), ISO/IEC 42001 and the NIST AI Risk Management Framework (AI RMF), because all three define AI broadly enough to include deterministic decision support that produces recommendations; JSP 939 (modelling and simulation) and the Aqua Book apply in any case because it is a model informing decisions.
- **Biggest conceptual risks (inference from the decision-science literature):** a minimax payoff matrix that implies a game-theoretic equilibrium it does not compute, compensatory weighted scoring that can hide an unacceptable outcome, rule-shopping between minimax, minimin and expected value, myopic "collect first" advice that ignores the cost of delay, and SGP4/two-line element (TLE) inputs whose kilometre-scale error is not carried through to the recommendation.
- **Rubric:** ten gate criteria (any Red fails regardless of score), then nine lenses scored 1 to 5 with stated weights (decision-model soundness 15, V&V 15, human-in-the-loop and explainability 15, uncertainty 13, input fidelity 12, safety 10, security 8, governance 7, efficiency 5), with the rubric itself tested for weight sensitivity and inter-assessor agreement.

## Key Findings

1. **The engine is in scope for MOD AI assurance, despite having no machine learning (ML). Fact (sourced) with inference.** JSP 936 Part 1 (V1.1, November 2024) characterises AI as "Machines that perform tasks normally requiring human intelligence, especially when the machines learn from data how to do those tasks", and its indicative Figure 1 lists expert systems, knowledge-based systems, Markov decision processes and dynamic programming. Its in-scope examples include "AI utilised within decision support toolsets or applications. For example: Course of Action (COA) development; task allocation...; mission tactics engines". It also notes that AI and non-AI approaches are increasingly blended and that "Some level of judgement is required when deciding which software components are within scope."\[1\] A payoff-matrix and game-tree engine that recommends responses to adversary actions sits squarely in this territory. Inference: the defensible position is to declare it in scope and apply JSP 936 proportionately (JSP 936 para 16 requires application "proportionate to the maturity and nature of the AI application"), rather than argue it out of scope and be wrong-footed at assurance review.\[1\]

2. **ISO/IEC 42001 and NIST AI RMF also reach it. Fact (sourced).** ISO/IEC 22989:2022 clause 3.1.4 defines an AI system as an "engineered system that generates outputs such as content, forecasts, recommendations or decisions for a given set of human-defined objectives", and clause 3.1.13 defines an expert system as an "AI system (3.1.4) that accumulates, combines and encapsulates knowledge... provided by a human expert or experts in a specific domain to infer solutions to problems". Clause 3.1.33 defines symbolic AI as AI "based on techniques and models that manipulate symbols and structures according to explicitly defined rules to obtain inferences".\[2\] ISO/IEC 42001:2023 takes its terms from ISO/IEC 22989 and applies to "any organization, regardless of size, type and nature, that provides or uses products or services that utilize AI systems".\[3\] NIST AI 100-1 (AI RMF 1.0, January 2023) refers to an AI system as "an engineered or machine-based system that can, for a given set of objectives, generate outputs such as predictions, recommendations, or decisions influencing real or virtual environments".\[4\] Inference: the engine's labelled lookups and decision rules are encoded human knowledge producing recommendations, so it meets all three definitions. What changes for a non-ML system is emphasis: training-data controls fall away; validity, uncertainty, explainability, human oversight and lifecycle documentation remain fully relevant.

3. **The principal weaknesses are likely to be conceptual, not computational. Inference.** The design combines four layers (payoff matrix, multi-criteria aggregation, selectable decision rule, shallow game tree with Bayesian updating and value of information) whose assumptions interact. Each layer is individually standard; the risk is that the combination produces a single confident-looking recommendation whose dependence on contestable judgements (weights, priors, rule choice, horizon) is invisible to the operator. The remediation theme throughout is the same: show the operator where the recommendation is fragile.

4. **Physics inputs carry errors large enough to change the decision. Fact (sourced) with inference.** Vallado, Crawford, Hujsak and Kelso ("Revisiting Spacetrack Report #3", AIAA 2006-6753, presented at the AIAA Astrodynamics Specialist Conference in August 2006) state that "TLE accuracy is coarse", giving "in general ~1 km accuracy at epoch ~1-3 km per day error growth", and note that TLE data is "no better than a few kilometers". Levit and Marshall (NASA Ames, arXiv 1002.2277) checked SGP4 predictions for four geodetic satellites against precise laser-ranging ephemerides and found "typical growth of 1,500 m/day for TLE's propagated with SGP4 for these objects", on top of an "instantaneous range bias from truth of 0.8 ± 0.3 km". NASA's Conjunction Assessment Risk Analysis (CARA) team states that "Covariance realism [is] critical for accurate calculation of Pc" (probability of collision).\[5\] Inference: if payoffs depend on miss distance or Pc, an unquantified multi-kilometre input error can flip the recommended response, so it must reach the payoff and the operator display.

5. **Standards status matters and parts are not public. Fact (sourced).** JSP 936 Part 2 (guidance) has not been publicly issued; JSP 936 Part 1 says preliminary guidance (model card template, AI ethics risk management framework, assurance question sets) was "made available internally".\[1\] Def Stan 00-055 Part 1 is at Issue 5 (28 July 2021) per the GlobalSpec catalogue; Def Stan 00-056 Part 01 Issue 8 and Part 02 Issue 6 are dated 14 October 2023.\[6\]\[7\]\[8\] JSP 936 itself says "Def Stan 00-055 currently only addresses ML and may therefore require additional considerations to be developed and applied for non-ML AI safety-related software", alongside non-AI software.\[1\] Inference: for this engine, Def Stan 00-055 applies as conventional programmable-element software if the engine is judged safety-related, and Def Stan 00-056 governs the safety case for the wider system.

## Details

### 1. Scrutiny of the concepts and decisions in the plan

Each subsection gives the issue, what the literature says, and what the evaluator should look for. Unless marked as fact with a named source, the decision-theoretic critique below is inference from standard decision theory and operations research.

#### 1a. Payoff matrix construction

- **Adversary COA enumeration.** The matrix is only as good as its rows. Check that adversary COAs are (i) collectively exhaustive for the operating envelope, with an explicit residual "other or unmodelled" row, and (ii) mutually exclusive, or else the probabilities used for expected value will double-count. Look for a documented COA-generation method (doctrine, intelligence assessment, red team) and a record of who signed it off.
- **Friendly response set.** Check that "do nothing" and "collect more information" are explicit responses, and that compound responses (manoeuvre and notify) are not silently excluded.
- **Payoff derivation.** Every cell should trace to either a propagated figure or a labelled lookup with source, date and owner. Cells filled by analyst judgement must be identified as such. JSP 936 para 42 states that where AI provides advice to an operator, "alternate sources, and their provenance, of information should be identified".\[1\]
- **Zero-sum assumption and implied equilibrium.** A single friendly-payoff matrix with minimax treats the adversary as wanting to minimise friendly value. That is a security (maximin) strategy, not a Nash equilibrium, unless the game is genuinely zero-sum. In space and counter-unmanned aircraft systems (C-UAS) contexts the adversary's objectives (signalling, deniability, cost imposition) are rarely the exact negative of friendly value, so the engine should (i) state that minimax gives a guaranteed floor rather than a prediction of adversary behaviour, and (ii) not describe its output as a "game-theoretic solution". A further subtlety: maximin over pure strategies can be strictly worse than the mixed-strategy value of the same zero-sum game; if the engine never considers randomised responses, document that as a deliberate limitation.

#### 1b. Multi-criteria weighted scoring

- **Weight elicitation.** Weights in an additive value model are only meaningful relative to the ranges of the criteria scales. Check whether weights were elicited by swing weighting (asking how much the swing from worst to best on each criterion matters) or by direct "importance" ratings; the latter are vulnerable to range insensitivity. Inference.
- **Normalisation and rank reversal.** Fact (sourced): Belton and Gear (1983) showed that in the Analytic Hierarchy Process (AHP) adding a copy or near copy of an existing alternative can reverse the ranking of the original alternatives, and later work established that rank reversal "is not unique to AHP but to all additive models" when normalisation depends on the current set of alternatives (Triantaphyllou 2001, cited in a University of Portsmouth AHP review).\[9\]\[10\] Inference: if the engine normalises scores by the maximum or sum across the current friendly responses, adding an irrelevant response can change the recommendation. Use fixed, pre-defined reference scales per criterion.
- **Additive independence.** Additive aggregation assumes preferences on one criterion do not depend on the level of another. Check for interactions such as "collision risk only matters if the asset is mission-critical"; if present, the additive model is misspecified.
- **Compensatory aggregation.** A weighted sum lets a strong score on one criterion offset an unacceptable score on another (for example an escalatory or unlawful response that scores well on mission effect). Hard constraints (legal, rules of engagement, safety thresholds) must be applied as non-compensatory vetoes before aggregation. This is a gate criterion below.
- **Sensitivity.** The engine should compute and display, for each recommendation, how far each weight would need to move before the top-ranked response changes (a weight-stability interval), not only a tornado chart of value swings.

#### 1c. Decision rules

- **Clarify sign conventions.** "Minimin" is optimistic only if payoffs are losses (minimise the minimum loss); with gains, the optimistic rule is maximax. The evaluator should confirm the code applies each rule with the correct orientation; this is a common implementation defect. Inference.
- **When each rule is appropriate.** Expected value requires credible probabilities and a risk-neutral decision maker. Minimax (worst-case) suits situations where a bad outcome is catastrophic or irreversible and probabilities are not trusted. Optimistic rules are rarely defensible as a primary rule in defence advice and should be shown only as a bound.
- **Rule-shopping.** If the operator or analyst can switch rule after seeing the results, the engine becomes a tool for rationalising a preferred answer. The rule should be pre-committed by doctrine or the commander's stated risk appetite, with all rules' results shown side by side and disagreement flagged.
- **Alternatives to consider. Fact (sourced) with inference.** Minimax regret (Savage) minimises the worst gap between the chosen action and the best action in hindsight; RAND's Robust Decision Making (RDM) seeks strategies that perform acceptably across many plausible futures and typically combines a regret measure with a satisficing criterion (Lempert, in Marchau et al., "Decision Making under Deep Uncertainty", 2019); info-gap theory (Ben-Haim) asks how much uncertainty a decision can tolerate before failing a performance requirement.\[11\]\[12\] A teaching comparison from Rice University's robustness course shows "Six metrics, same payoff matrix, three different winners".\[13\] Inference: the Hurwicz criterion (a weighted blend of best and worst) adds little beyond showing minimax and optimistic results together; minimax regret and an info-gap style "how wrong can the probabilities be before the recommendation changes" are the most useful additions for this engine.

#### 1d. Two to three turn game tree

- **Horizon effect.** A two to three ply tree truncates consequences; responses that look good at ply three may set up a poor position at ply four. Check how leaf nodes are valued (static payoff, heuristic or propagated state) and whether the operator is told the horizon.
- **Adversary model.** A tree solved by backward induction assumes a rational adversary optimising the same payoffs. Check whether the engine allows a bounded-rational or probabilistic adversary (for example a quantal-response style distribution over adversary moves) and whether that choice is visible. Inference.
- **Consistency with the matrix.** The first ply of the tree must reproduce the matrix result when the tree depth is one. This is a straightforward verification test.
- **Branching and pruning.** If alpha-beta or similar pruning is used, verify that pruned results equal unpruned results on reference cases; if heuristic pruning is used, record what was cut.

#### 1e. Bayesian updating

- **Priors.** Every prior over adversary intent or COA must have a recorded source (intelligence assessment, base rate from historical behaviour, expert elicitation) and date. Undocumented "uniform" priors are a judgement, not neutrality.
- **Likelihood models.** The probability of each observation given each COA must be specified and justified. Check whether observations are treated as independent when they are correlated (for example several sensors seeing the same manoeuvre), which produces overconfident posteriors. Inference.
- **Conjugacy and approximation.** Discrete COA spaces allow exact updating; verify the arithmetic against hand-computed cases and check numerical underflow handling for long observation sequences.
- **Calibration.** Over exercises or historical cases, posterior probabilities should be checked for calibration (for example with a Brier score and reliability diagram). An engine that says "80%" should be right about 80% of the time in like cases.

#### 1f. Value of information and "collect first" advice

- **EVPI versus EVSI.** Fact (sourced): the expected value of perfect information (EVPI) is an upper bound on the value of any collection; realistic sensors provide sample information, and the nesting EVSI ≤ EVPPI ≤ EVPI holds (expected value of sample information, partial perfect information and perfect information respectively; arXiv 2607.06570).\[14\] Inference: "collect first" advice must be based on EVSI for the actual sensor tasking, not EVPI.
- **Myopia.** Fact (sourced): Heckerman, Horvitz and Middleton describe myopic value-of-information analysis as "based on the assumption that only one additional test will be performed, even when there is an opportunity to make a large number of observations".\[15\] Myopic analysis can undervalue sequences of observations that are only informative together.\[16\]
- **Cost and timeliness.** Fact (sourced): NASA CARA's January 2025 briefing on density-model sensitivity (NTRS 20250000813) states that a conjunction is "usually first discovered 7 days before time of closest approach (TCA)", with covariance shrinking as TCA approaches; a separate CARA paper (NTRS 20220004118) puts the decision point "in the neighborhood of 2 days to TCA". Inference: in fast-moving space events the main cost of collecting is the shrinking set of feasible responses (manoeuvre windows close). The net value must subtract the expected loss from delay, and the display should show the latest time by which the operator must act regardless of collection.

#### 1g. Physics inputs

- **SGP4 limits. Fact (sourced).** Vallado et al. (AIAA 2006-6753) give "in general ~1 km accuracy at epoch ~1-3 km per day error growth" for TLEs, and warn that different SGP4 versions can produce materially different ephemerides. TLEs carry no covariance. Inference: SGP4 is appropriate for screening and situational awareness, not for final collision-risk payoffs; any payoff driven by close-approach geometry should either use higher-fidelity ephemerides with covariance or carry an explicit, age-dependent error model derived from TLE epoch age.
- **Monte Carlo over RK45.** Check: integrator tolerances (relative and absolute) and their effect against a reference propagator; force model content (geopotential degree and order, drag and atmospheric density model, solar radiation pressure, third bodies); how initial-state samples are generated (from what covariance, and how that covariance was validated); and sample size. Fact (sourced): in NASA CARA's validation paper "Time Dependence of Collision Probabilities During Satellite Conjunctions" (NTRS 20170001477), CARA's Pc estimates were checked against Monte Carlo runs of 30 million samples ("Alfano's Monte Carlo simulation using 30 million samples yields Pc = 0.10034"), and one test case was checked against Alfano's 1-billion-sample benchmark ("Monte Carlo simulation using 1 billion samples yields a benchmark Pc = 0.36300"). Inference: for a Bernoulli estimate the standard error is sqrt(p(1 − p)/N); estimating a Pc of 1 × 10^-4 to 10% relative standard error needs about 10^6 samples, so small Monte Carlo runs can report zero or wildly unstable Pc values. The engine should report the Monte Carlo confidence interval on every Pc.
- **Covariance realism. Fact (sourced):** NASA CARA publishes covariance realism assessment tools and states covariance realism is critical.\[5\]\[17\] Inference: Monte Carlo output is only as realistic as the input covariance; test covariance realism against post-fit ephemerides.
- **Mixing propagated and lookup figures.** Each payoff input should carry a provenance tag (propagated, lookup, analyst judgement), a source and version, an age, and an uncertainty representation. Lookups without uncertainty should be flagged as such, not silently treated as exact.

#### 1h. End-to-end uncertainty propagation

The test is simple: perturb inputs within their stated uncertainty and see whether the recommendation changes. Inference: the engine should run an outer sampling loop (or at minimum a one-at-a-time sweep) over payoff inputs, weights and priors, and report the proportion of samples in which each response is ranked first. If the top response wins in 55% of samples, the operator must see that, not a single crisp answer. JSP 936 para 6 requires that where there is considerable uncertainty "owners of resultant risk must understand that uncertainty and communicate associated risks to all stakeholders".\[1\] The Synoptix analysis of JSP 936 (Cockburn and Farrow, arXiv 2606.09414) quotes JSP 936 para 167: "All models should provide measures of uncertainty that are understandable to the various stakeholders".\[18\]

### 2. Verification, validation and accreditation methods

**Governing guidance. Fact (sourced).**
- **JSP 939** (Defence Policy for Modelling and Simulation, Part 1 V3.1, January 2025) applies; JSP 936 para 9 says where AI is used within a model, JSP 939 "must be applied in combination with this JSP".\[1\] JSP 939 also states that for Defence experimentation and operational analysis, HM Treasury policy (the Aqua Book) "holds higher authority than this JSP".\[19\]
- **The Aqua Book** sets four principles: proportionality of response, assurance throughout development, verification and validation, and analysis with RIGOUR (repeatable, independent, grounded in reality, objective, uncertainty understood and managed, robust).\[20\] Its 2025 revision added sections on uncertainty and "black box" models (Government Actuary's Department blog, October 2025).\[21\] Verification checks the analysis meets its specification; validation checks it is fit for purpose.\[22\]
- **Def Stan 03-44** (a generic process for V&V of modelling and simulation) and the **SISO/NATO Generic Methodology for Verification and Validation (GM-VV)** are listed in the Defence M&S standards profile and NATO AMSP-01.\[23\]\[24\]\[25\] GM-VV frames V&V as collecting "a body of evidence in support of the V&V Users/Sponsors acceptance decision-making process".\[26\]
- **US DoD Instruction 5000.61** (reissued 17 September 2024) defines accreditation as the official certification that a model and its data are acceptable for a specific intended use, and requires documentation of version, intended use and V&V activities.\[27\]\[28\]\[29\]

**Recommended test programme. Inference, built on the above.**

| Test type | What it shows for this engine | Example |
|---|---|---|
| Reference-case (analytic) | Arithmetic and rule implementation correct | Textbook matrices with known maximin, minimax regret and expected-value answers; matching-pennies to show pure-strategy maximin differs from mixed value |
| Propagator verification | SGP4 and RK45 implemented correctly | Vallado verification TLE set and published outputs; RK45 against a high-order reference integrator at tight tolerance |
| Metamorphic and property tests | Invariances that must hold | Adding a dominated response must not change the top choice; scaling all payoffs by a positive constant must not change choices; permuting row order must not change results |
| Sensitivity and robustness | Fragility of each recommendation | Weight-stability intervals, prior sweeps, input perturbation within stated uncertainty |
| Monte Carlo convergence | Stable Pc and payoff estimates | Report estimate and interval versus N; confirm interval shrinks as 1/sqrt(N) |
| Adversarial and edge cases | Graceful failure | Stale TLEs, NaN or missing lookups, decayed objects, deep-space SDP4 branch, contradictory observations, extreme priors |
| Back-testing | Validity against reality | Replay historic space domain awareness (SDA) events with data available at the time and compare advice with what was later known |
| Calibration | Bayesian outputs mean what they say | Brier score and reliability diagrams over exercise and historic sets |
| Red teaming | Robustness to deliberate manipulation | Spoofed observations designed to drive the posterior; payoff tables engineered to induce escalation |
| Operator-in-the-loop trials | Human-machine team performance | Seeded incorrect recommendations to measure commission and omission errors; time to decision; trust ratings versus actual reliability |

### 3. Assurance framework applicability and mapping

| Framework | Status and access | Applies? | What it demands of this engine |
|---|---|---|---|
| JSP 936 Part 1 (V1.1, Nov 2024) | Public. Part 2 not public; interim products internal to MOD | Yes (decision support for COA is a listed in-scope example) | Ethical principles; ethical risk assessment at outset (para 86); system identified as AI-based (para 39); provenance of alternative information sources (para 42); articulation of human involvement and accountability (para 58); hazard analysis; Secure by Design |
| ISO/IEC 42001:2023 | Paywalled; free preview covers clauses 1 to 4.4 | Yes, at organisational level | AI management system; role determination per ISO/IEC 22989; Annex A controls. Annex A control titles below are from secondary sources, not verified against the standard: A.6 AI system lifecycle including A.6.2.4 verification and validation and A.6.2.8 recording of event logs; A.8 information for interested parties; A.9 use of AI systems |
| NIST AI RMF 1.0 | Public, voluntary | Yes by definition; voluntary in the UK | Govern, Map, Measure, Manage; trustworthiness characteristics including valid and reliable, safe, secure and resilient, accountable and transparent, explainable and interpretable |
| MOD Secure by Design (ISN 2023/09) | Public | Yes (applies to "information-based capabilities for MOD") | Seven principles listed below |
| Def Stan 00-056 (Pt 01 Iss 8, Pt 02 Iss 6, Oct 2023) | Available via UK Defence Standardization; full text not reviewed here | Yes if outputs can contribute to harm | Goal-based safety management, safety case, hazard log |
| Def Stan 00-055 Pt 1 (Iss 5, July 2021) | As above; full text not reviewed here | Yes as conventional software if safety-related | Design integrity requirements for programmable elements |
| JSP 912 and Def Stan 00-251 (Iss 2, Dec 2021) | JSP 912 public; Def Stan via DStan | Yes (human element present) | JSP 912 mandates human factors integration (HFI) for all acquisition projects; Def Stan 00-251 is the contracting standard\[30\]\[31\] |
| JSP 939 and Aqua Book | Public | Yes (model informing decisions) | Proportionate V&V, documentation, uncertainty |

**Secure by Design. Fact (sourced).** ISN 2023/09 (21 July 2023) sets seven principles: Understand and Define Context; Plan the Security Activities; Implement Continuous Risk Management; Define Security Controls; Engage and Manage the Supply Chain; Assure, Verify and Test; Enable Through Life Management. It applies to "networks, applications, services, information technology, operational technology, platforms and weapons systems".\[32\] Inference on engine-specific threats: integrity of TLE and lookup inputs (poisoned or spoofed data driving a recommendation), tampering with weights or priors, integrity and non-repudiation of decision records, and confidentiality of payoff tables, which reveal friendly priorities.

**Human factors and explainability. Fact (sourced) with inference.** Parasuraman and Manzey (Human Factors, 2010) found that automation bias produces both omission and commission errors when decision aids are involved, and that complacency arises under multiple-task load.\[33\]\[34\] In a laboratory process-control study (International Journal of Human-Computer Studies 66(9), 24 participants), Bahner, Hüper and Manzey (2008) found "clear evidence for complacency", with commission errors associated with high levels of complacency, and found that exposing operators to automation failures during training significantly decreased complacency. MOD's Joint Concept Note (JCN) 1/18 Human-Machine Teaming addresses trust and confidence in machines.\[35\] MITRE's Human-Machine Teaming Systems Engineering Guide defines directability (humans can "stop processes, change course... or override") and calibrated trust as requirements.\[36\] Inference: "it recommends, the operator decides" is necessary but not sufficient for meaningful human control. The engine must make disagreement, fragility and uncertainty visible, and trials must measure whether operators actually catch seeded errors.

**Explanation content for each recommendation (inference, drawing on JSP 936 paras 59 to 63 and para 167 as quoted by Cockburn and Farrow):** the recommended response and its rank under every rule; the adversary COA driving the result (for minimax, the worst-case row); the top three contributing criteria and their weights; weight-stability and prior-stability intervals; input provenance and age; Monte Carlo intervals; the VOI calculation with delay cost; the horizon of the game tree; and known limitations.

### 4. Remediation patterns

| Weakness | Remediation | Evidence the evaluator should see |
|---|---|---|
| Single rule shown | Display results under all rules side by side; flag disagreement; pre-commit primary rule to stated risk appetite | Screenshots; configuration record of who set the primary rule and when |
| Minimax described as equilibrium | Relabel as "guaranteed floor"; document zero-sum assumption; optionally add mixed-strategy solve for zero-sum cases | Updated user documentation and interface wording |
| Compensatory aggregation hides unacceptable outcomes | Non-compensatory vetoes applied before scoring; vetoed responses shown greyed out with reason | Test cases showing a high-scoring vetoed response is never recommended |
| Weights unjustified | Swing-weight elicitation with recorded participants and rationale; fixed reference scales | Elicitation record; scale definitions |
| Rank reversal | Fixed scales; metamorphic test that adding a dominated response leaves ranking unchanged | Passing test log |
| Weight fragility hidden | Weight-stability intervals and tornado charts per recommendation | Interface; test outputs |
| Undocumented priors and likelihoods | Prior register with source, owner, date; likelihood tables justified; correlation handling | Register; review minutes |
| Myopic or delay-blind VOI | EVSI for actual collection options; explicit delay cost; "act-by" time shown | Worked examples; back-test cases |
| TLE error ignored | Age-dependent error model for SGP4 inputs; higher-fidelity ephemerides for close-approach payoffs | Comparison against precise ephemerides |
| Monte Carlo under-sampled | Report estimate with confidence interval; adaptive N until interval target met | Convergence plots |
| Lookups without uncertainty | Provenance tag on every figure; "uncertainty not quantified" flag | Data dictionary; interface |
| No audit trail | Immutable decision record: inputs, versions, rule, weights, priors, recommendation, operator decision and rationale, timestamps | Log samples; integrity controls; replay test |
| Automation bias untested | Operator trials with seeded errors; training on limitations; forced consideration of alternatives before acceptance | Trial report with commission and omission error rates |

### 5. The scoring rubric

#### 5.1 Design principles (inference, grounded in sourced practice)

- **Gate before score.** The gate is non-compensatory for the same reason the engine's hard constraints must be: a high weighted score must not hide an unacceptable failure. This mirrors staged gateway reviews, where a red rating on a critical issue stops progression.
- **Maturity levels.** Levels follow a capability-maturity pattern: 1 absent or ad hoc, 2 defined, 3 implemented and verified, 4 validated for intended use with independent evidence, 5 monitored and improved through life. This aligns with the Aqua Book distinction between verification and validation and with DoDI 5000.61's accreditation for "a specific intended use".\[37\]
- **Weights are judgements and are stated as such.** Each weight reflects the lens's contribution to the risk of a wrong or misunderstood recommendation reaching an operator. Weights are set on the swing principle: how much would moving this lens from level 1 to level 5 reduce decision risk, relative to the other lenses.

#### 5.2 Gate criteria (must-haves; any Red fails regardless of score)

Ratings: **Green** met with objective evidence; **Amber** substantially met with a dated, owned remediation plan; **Red** not met or no evidence. More than three Ambers caps the overall verdict at "Conditional".

| ID | Must-have | Why it is a gate | Dimension |
|---|---|---|---|
| G1 | Advisory only: no path from engine output to effect without an explicit operator decision, and the operator decision is recorded | Meaningful human control (JSP 936 paras 49 and 58) | Effectiveness |
| G2 | Every recommendation is reproducible from a stored decision record (inputs, versions, rule, weights, priors) | Accountability; V&V impossible without replay | Completeness |
| G3 | Results under all implemented decision rules are available to the operator, and disagreement is flagged | Prevents rule-shopping and hidden judgement | Effectiveness |
| G4 | Hard constraints (legal, rules of engagement, safety thresholds) are enforced as vetoes before aggregation | Compensatory scoring must not override unacceptable outcomes | Accuracy |
| G5 | Every payoff input carries a provenance tag (propagated, lookup or judgement), source, version and age | JSP 936 para 42; Aqua Book traceability | Completeness |
| G6 | No point estimate is presented without an uncertainty indication or an explicit "not quantified" flag | JSP 936 para 6 and para 167 | Accuracy |
| G7 | SGP4 implementation passes published verification cases; RK45 propagation verified against a reference | Basic correctness of physics inputs | Accuracy |
| G8 | Hazard analysis completed and the engine's safety-related status determined under Def Stan 00-056 | JSP 936 requires hazard analysis for AI | Completeness |
| G9 | Threat model and integrity controls for inputs, configuration and decision records, consistent with ISN 2023/09 | Poisoned inputs produce confident wrong advice | Effectiveness |
| G10 | Operating envelope defined, with out-of-envelope inputs detected and flagged to the operator | JSP 936 para 38 on the operational design domain (ODD) | Accuracy |

#### 5.3 Lenses, weights and rationale

| Lens | Weight | Rationale for the weight |
|---|---|---|
| L1 Decision-model soundness (matrix, MCDA, rules, tree, Bayes, VOI) | 15 | The core logic; a conceptual flaw corrupts every output, and testing cannot catch a wrong concept that is correctly coded |
| L2 Input fidelity and provenance (SGP4, Monte Carlo, lookups) | 12 | Kilometre-scale TLE errors can flip recommendations; slightly lower than L1 because some input risk is gated by G5 and G7 |
| L3 Uncertainty propagation and presentation | 13 | The main defence against overconfidence; separate from L2 because good inputs are wasted if their uncertainty never reaches the operator |
| L4 V&V and test evidence | 15 | Without evidence no other score can be trusted; JSP 936 para 6 makes confidence commensurate with reliance |
| L5 Human-in-the-loop and explainability | 15 | The operator is the final safeguard; automation bias research shows advisory status alone does not prevent error |
| L6 Safety management (Def Stan 00-056, 00-055) | 10 | Material because outputs can inform manoeuvre or engagement decisions; lower than L5 because the human decision step and G8 already bound direct harm |
| L7 Security (Secure by Design) | 8 | Integrity threats are real but the minimum is gated by G9; the score rewards maturity above the floor |
| L8 AI governance alignment (JSP 936, ISO/IEC 42001, NIST AI RMF) | 7 | Organisational process matters for through-life assurance but contributes less directly to a single recommendation's correctness |
| L9 Efficiency and timeliness | 5 | Space events can be time-critical, but the minimum is set by acceptance criteria; extra speed above the threshold adds little decision value |
| **Total** | **100** | |

**Mapping to the four required dimensions.** Completeness: L1, L4, L8 and gates G2, G5, G8. Effectiveness: L5, L6, L7 and gates G1, G3, G9. Efficiency: L9, plus the efficiency of V&V effort under L4 (proportionality). Accuracy: L2, L3 and gates G4, G6, G7, G10. Approximate weight by dimension: accuracy 25, completeness 37, effectiveness 33, efficiency 5. Inference: the low efficiency share is deliberate; if Bluestaq's customer places a hard timeliness requirement on the engine, add a gate (for example "recommendation available within the stated decision window for 95% of reference cases") rather than raising L9's weight.

#### 5.4 Level descriptors

| Lens | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| L1 Decision model | Assumptions undocumented; single rule; weights ad hoc | Assumptions listed; COA and response sets documented; weights recorded without method | Swing-weighted on fixed scales; vetoes before aggregation; all rules shown; zero-sum and horizon limits stated | Independent decision-analyst review; minimax regret or robustness measure added; adversary model alternatives tested | Assumptions reviewed through life against exercise and operational feedback |
| L2 Input fidelity | Inputs untagged; SGP4 used for all payoffs | Provenance tags exist but incomplete | All inputs tagged; SGP4 verified; RK45 tolerances and force models documented; Monte Carlo intervals reported | TLE-age error model validated against precise ephemerides; covariance realism tested; lookups reviewed by owners | Automated data-quality monitoring; inputs refreshed and revalidated on schedule |
| L3 Uncertainty | Point estimates only | Some intervals shown, not propagated | Input uncertainty propagated to payoffs; weight and prior stability shown per recommendation | Full outer-loop sampling; probability each response ranks first; info-gap style robustness reported | Uncertainty displays validated with operators; calibration tracked over time |
| L4 V&V | Developer testing only | Test plan exists; partial unit tests | Reference, metamorphic and edge-case suites pass; V&V documented per Aqua Book | Independent V&V; back-testing on historic SDA events; red team; calibration evidence; accreditation for intended use | Continuous regression and revalidation on every change; V&V evidence feeds the safety case |
| L5 Human-in-the-loop | Single answer shown; no decision record | Rationale text shown; operator decision logged | Full explanation pack per recommendation; directability (override, re-run with changed assumptions) | Operator trials with seeded errors show acceptable commission and omission rates; training delivered | Trust calibration monitored in service; interface iterated on evidence |
| L6 Safety | No hazard analysis | Hazard identification only | Hazard log and safety-related determination; mitigations traced to design | Safety case argued to Def Stan 00-056 and independently reviewed | Safety case maintained through life with in-service data |
| L7 Security | No threat model | Threat model drafted | ISN 2023/09 principles applied; input and record integrity controls implemented | Penetration and data-poisoning tests; supply chain assessed | Continuous monitoring; through-life assurance per Principle 7 |
| L8 Governance | No AI scoping decision | In-scope decision recorded | JSP 936 ethical risk assessment, accountabilities and model card style documentation | Aligned to ISO/IEC 42001 and NIST AI RMF; external or customer audit | Management system reviewed and improved on a fixed cycle |
| L9 Efficiency | Runtime unknown | Runtime measured informally | Meets stated decision window on reference cases | Meets window under realistic load and degraded data | Performance monitored and optimised in service |

**Scoring.** Overall score = sum of (weight × level) / 100, giving a value from 1 to 5. Suggested verdicts: any gate Red = **Fail**; score below 2.5 = **Not ready**; 2.5 to 3.49 = **Conditional** (trial use with named controls); 3.5 or above with no more than three gate Ambers = **Ready for operational trial**; 4.0 or above with all gates Green = **Ready for accreditation submission**. These thresholds are proposals for Bluestaq to ratify, not sourced standards.

#### 5.5 Holding the rubric to its own standard

- **Weight sensitivity.** Recompute the verdict under (i) equal weights (about 11.1 each), and (ii) each weight raised and lowered by 50% with the rest renormalised. If the verdict band changes in any run, record the result as "weight-sensitive" and report which lens drives it. This is the same weight-stability test the rubric demands of the engine.
- **Inter-assessor reliability.** Two assessors score independently before moderation. Compute quadratic-weighted Cohen's kappa on the lens levels; a commonly used convention (Landis and Koch, 1977) treats 0.61 to 0.80 as substantial agreement. Any lens where assessors differ by two or more levels goes to moderation with the evidence re-examined. Low agreement indicates the descriptors need sharpening, not that one assessor is wrong.
- **Evidence rule.** A level is awarded only on objective evidence (document, test log, trial report), following the Aqua Book's emphasis on documented, proportionate assurance.
- **Version control.** The rubric, its weights and their rationale are placed under configuration control, so that changes after seeing results are visible, which prevents rubric-shopping in the same way G3 prevents rule-shopping.

## Recommendations

1. **Declare the engine in scope for JSP 936 now** and record the rationale, citing para 11a(4). Complete the AI ethical risk assessment (para 86) and request the internal JSP 936 Part 2 interim products from the customer's Responsible AI Senior Officer (RAISO) or delivery team.\[1\]
2. **Run the gate first.** In my judgement G3 (all rules shown), G4 (vetoes before aggregation), G6 (uncertainty visible) and G7 (propagator verification) are the gates most likely to be Red in a first implementation; fix those before scoring.
3. **Reframe minimax output** as a guaranteed floor, not an adversary prediction, and add minimax regret and a weight and prior stability display.
4. **Replace EVPI-style or delay-blind "collect first" logic** with EVSI net of delay cost and show an "act-by" time.
5. **Restrict SGP4 to screening**; drive collision-related payoffs from higher-fidelity ephemerides with validated covariance, and report Monte Carlo intervals on every Pc.
6. **Commission an independent V&V** to the Aqua Book and JSP 939, including back-testing on historic SDA events and operator trials with seeded errors, and package the results as accreditation evidence in the DoDI 5000.61 style for Five Eyes customers.
7. **Score with two assessors**, publish the weight-sensitivity result alongside the verdict, and repeat the assessment at each major release.

## Caveats

- **Restricted or paywalled sources.** JSP 936 Part 2 is not public, and its interim products are internal to MOD. ISO/IEC 42001 and ISO/IEC 22989 are paywalled; quotations come from official previews, and the 42001 Annex A control titles come from secondary sources and need checking against the purchased standard. Def Stan 00-055, 00-056 and 00-251 full texts were not reviewed; only their issue status and JSP 936's description of them are reported. Do not rely on this report for their detailed clauses.
- **Fact versus inference.** Statements marked fact are from named sources. The decision-theoretic critique, the rubric weights, the verdict thresholds and the test programme are my reasoned inference and should be ratified by Bluestaq's technical authority and, ideally, an independent decision analyst.
- **Recency.** The Synoptix analysis of JSP 936 (arXiv 2606.09414) is a recent preprint and not peer reviewed. JSP 936 says it will be reviewed at least every two years, so a revision may be due; check for an update before submission.\[1\]
- **Unknowns about the implementation.** This evaluation framework is built from the system description supplied, not from the code or documentation. Some findings may already be addressed; the rubric is designed to show that with evidence.

## Sources

1. [JSP 936 V1.1 Dependable Artificial Intelligence (AI) in Defence](https://assets.publishing.service.gov.uk/media/6735fc89f6920bfb5abc7b62/JSP936_Part1.pdf)
2. <https://cdn.standards.iteh.ai/samples/74296/c4efbadbf1a146d4af6d62fcad09438f/ISO-IEC-22989-2022.pdf>
3. <https://cdn.standards.iteh.ai/samples/81230/4c1911ebc9a641fcb6ee21aa09c28ad3/ISO-IEC-42001-2023.pdf>
4. [NIST AI Risk Management Framework 1.0 (NIST AI RMF) — Complete Guide](https://docs.modulos.ai/frameworks/nist-ai-rmf)
5. [Conjunction Assessment Risk Analysis NASA CARA](https://ntrs.nasa.gov/api/citations/20250000813/downloads/NASA_CARA_DensityModelSensitivity_250121.pdf)
6. [Defence Standard 00-056 Part 02 Issue 6 Date: 14 October 2023](https://www.contractsfinder.service.gov.uk/Notice/Attachment/f5da1812-be3e-4a2e-b52c-2e5400c6d3ca)
7. [Defence Standard 00-056 Part 01 Issue 8 Date: 14 October 2023](https://www.contractsfinder.service.gov.uk/Notice/Attachment/02f13f3e-57ae-4b0d-88e0-b20cc7dbe81b)
8. [MODUK - DEF STAN 00-055: PART 01 - Requirements for Safety of Programmable Elements (PE) in Defence Systems Part: 01 : Requirements and Guidance](https://standards.globalspec.com/std/14461525/def-stan-00-055-part-01)
9. [Review of the main developments of the Analytic Hierarchy ...](https://pure.port.ac.uk/ws/files/94447/AHP_review_Preprint.pdf)
10. [USING THE ANALYTIC HIERARCHY PROCESS FOR ...](https://bit.csc.lsu.edu/trianta/Journal_PAPERS1/AHPapls1.pdf)
11. [(PDF) Robust Decision Making (RDM)](https://www.researchgate.net/publication/345464296_Robust_Decision_Making_RDM)
12. [Decision Making under Deep Uncertainty Vincent A. W. J. Marchau](https://www.hydrology.nl/images/docs/alg/DecisionMakingUnderDeepUncertainty.pdf)
13. [Robustness & Deep Uncertainty](https://ceve-421-521.github.io/lectures/week-08/index.html)
14. [Value of Information under Imprecise Probabilities: Decision-Rule-Specific Values and Fixed-Measure Envelopes on a Credal Set](https://arxiv.org/pdf/2607.06570)
15. [An Approximate Nonmyopic Computation for Value of Information](https://arxiv.org/pdf/1303.5720)
16. [Non-Myopic Sequential Information Gathering — Lacuna](https://lacuna.tiptreesystems.com/direction/non-myopic-sequential-information-gathering/txn_1725e3f7668a499fa2808f9a63135bde)
17. [Suggested Searches](https://www.nasa.gov/cara/publicly-available-cara-software/)
18. [AI Assurance in UK Defence:Challenges in Operationalising JSP 936](https://arxiv.org/html/2606.09414)
19. [JSP 939 Defence Policy for Modelling & Simulation (M&S) Part 1: Directive](https://assets.publishing.service.gov.uk/media/6787cd9d2cca34bdaf58a294/JSP939_Part1.pdf)
20. [The Aqua Book: Guidance on producing quality analysis for government](https://www.highstreetstaskforce.org.uk/resources/details/?id=df62c990-ad26-4784-89ac-cae8492b0874)
21. [How we wrote the AQuA Book ….](https://actuaries.blog.gov.uk/2025/10/09/how-we-wrote-the-aqua-book/)
22. [Quality assuring analysis](https://docs.data-community.publishing.service.gov.uk/analysis/best-practice/analytical-quality-assurance)
23. [AMSP-01 NATO MODELLING AND SIMULATION STANDARDS PROFILE Edition (B) Version 1](https://publications.tno.nl/publication/102742/taAPXg/huiskamp-2012-nato.pdf)
24. [NATO STANDARD AMSP-01 NATO MODELLING AND SIMULATION STANDARDS PROFILE](https://www.mscoe.org/content/uploads/2017/12/AMSP-01C.pdf)
25. [Defence modelling and simulation standards profile](https://assets.publishing.service.gov.uk/media/651fd31a79fc58000d639720/Defence_modelling_and_simulation_standards_profile.pdf)
26. [SISO-GUIDE-001.1-2012 Guide for Generic Methodology for](https://cdn.ymaws.com/www.sisostandards.org/resource/resmgr/guidance_products_/2012_siso-guide-001.1-2012_g.pdf)
27. [DOD INSTRUCTION 5000.61 DOD MODELING AND SIMULATION VERIFICATION,](https://www.esd.whs.mil/Portals/54/Documents/DD/issuances/dodi/500061p.pdf)
28. [BY ORDER OF THE SECRETARY OF THE AIR FORCE AIR FORCE INSTRUCTION 16-1001](https://static.e-publishing.af.mil/production/1/saf_sa/publication/afi16-1001/afi16-1001.pdf)
29. [Enhancing Credibility in DoD Modeling and Simulation: Revised DoD Instruction 5000.61 — Fed Contract Pros™](https://www.fedcontractpros.com/blog/t21vkdtzwe1094zdnp833x9pgcsf18)
30. [MODUK DEF STAN 00-251 \[ Active \]](https://store.accuristech.com/standards/moduk-def-stan-00-251?product_id=2917212)
31. [JSP 912 Human Factors Integration for Defence Systems Part 1: Directive](https://assets.publishing.service.gov.uk/media/6634dc9ccf3b5081b14f314b/JSP_912_Part_1_V3.0.pdf)
32. <https://assets.publishing.service.gov.uk/media/64bfb929d4051a00145a9289/ISN_2023-09_Secure_by_Design_Requirements.pdf>
33. [Complacency and Bias in Human Use of Automation: An Attentional Integration](https://depositonce.tu-berlin.de/items/0c787d91-6021-480b-a333-009e0d1d0092)
34. [http://hfs.sagepub.com/ Ergonomics Society of the Human Factors and](https://www.researchgate.net/profile/Raja-Parasuraman/publication/47792928_Complacency_and_Bias_in_Human_Use_of_Automation_An_Attentional_Integration/links/09e4150c09890db4c6000000/Complacency-and-Bias-in-Human-Use-of-Automation-An-Attentional-Integration.pdf)
35. [Joint Concept Note 1/18 - Human-Machine Teaming](https://assets.publishing.service.gov.uk/media/5b02f398e5274a0d7fa9a7c0/20180517-concepts_uk_human_machine_teaming_jcn_1_18.pdf)
36. [The views, opinions, and/or findings contained in this report are those of The](https://www.mitre.org/sites/default/files/2021-11/prs-17-4208-human-machine-teaming-systems-engineering-guide.pdf)
37. [M&S for Test and Evaluation - Guidance](https://www.dote.osd.mil/Portals/97/docs/TEMPGuide/MandS_for_TandE_Guidance_3.0.pdf?ver=2019-08-26-165233-933)
