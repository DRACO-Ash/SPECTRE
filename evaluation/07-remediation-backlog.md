# 07. Remediation backlog

One row per finding, grouped by what it unlocks, then ordered by severity and effort within each group (S under a day, M up to a week, L more than a week; estimates are the assessor's judgement). Full finding text: `EVALUATION.md`, section 5. Finding IDs F-28 and F-37 are unused (merged into F-19 and F-06).

## Group A. Must fix to pass the gate

| Finding | Severity | Rubric | Remediation (files) | Evidence that closes it | Effort | Unlocks |
|:-|:-|:-|:-|:-|:-|:-|
| F-06 | Critical | G7, L2, L4 | Adopt probes P-12 and P-13 into `tests/unit/` with fixed thresholds; run in `.github/workflows/ci.yml` | Both tests green in CI | S | G7 to Green |
| F-25 | Critical | G9, L2, L7 | Call `tle_checksum_valid` and range-check element-set fields in `spectre/web/elsets.py` on every ingest path (`routes/udl.py:184-225`, `routes/operator.py:178-190`, `:239-251`); on failure refuse and keep the held set | Probe P-14 UDL case inverted; unit test per path | S | G9 (part), L2 to 3 (part) |
| F-05 | Critical | G5, L2 | Add `Basis.JUDGEMENT` (`spectre/domain/provenance.py`) for operator-entered cost, reversibility, time, P and weights; a lookup register in `docs/` naming source, owner and date for each constant in `decision.py:1912-1921`, `:2007-2041`; show the code version on the results page | Every figure tagged one of four on the page; the register | M | G5 to Green |
| F-09 | Critical | G10, L2 | Write an operating design domain in `docs/` (regimes, element-set ages, horizons, scenario sizes) and check it at evaluation entry in `spectre/domain/decision.py`, flagging each breach (with F-29, F-30, F-31) | ODD document; a test per breach that the flag renders | M | G10 to Green |
| F-03 | Critical | G3, L1, L5 | Compute all three rules' picks in every `ScenarioResult` (`decision.py:3849-3948`); show them side by side with a disagreement line in `decision_results.html`; record a primary rule per deployment, set before use | Page showing three picks; disagreement test; configuration record | M | G3 to Green, L1 and L5 (part) |
| F-04 | Critical | G4, L1 | Add a veto with a stated reason to `FriendlyResponse` and scenario-level constraints; remove vetoed responses before `find_robust_response` (`decision.py:3584-3628`) and the tree selectors (`tree_selectors.py:152-205`); show them greyed with the reason | Probe P-06 written as specified and passing | M | G4 to Green, L1 to 3 (part) |
| F-01 | Critical | G1, L5 | A durable decision record (new table in `spectre/web/models.py`), written by `spectre/web/routes/decision.py`: recommendation, all rules' picks, weights, input hashes, and the operator's decision and rationale captured on the results page | A stored record per evaluation, retrievable after sign-out, with the operator's decision; test | M | G1 to Green, L5 to 2 |
| F-02 | Critical | G2, L4 | Store the canonical inputs (element sets as fetched, rows, responses, weights, rule, seeds, code version) with the record; add a replay command | Replay test reproducing a stored recommendation exactly from the record alone | M | G2 to Green |
| F-08 | Critical | G9, L7 | Engine threat model against ISN 2023/09 (poisoned element sets, tampered weights or priors, record integrity); nonce-based Content Security Policy in `spectre/web/app.py:298` with the inline scripts in `decision_results.html:311-327`, `:408-442` moved to static files | Threat model document; CSP without `unsafe-inline` and `unsafe-eval`; tests | L | G9 to Green, L7 to 3 |
| F-07 | Critical | G8, L6 | Hazard identification, hazard log and a safety-related determination under Def Stan 00-056, owned by the safety lead (outside the code) | Hazard log and signed determination | L | G8 to Green, L6 to 3 |

## Group B. Fix before operational trial

| Finding | Severity | Rubric | Remediation (files) | Evidence that closes it | Effort | Unlocks |
|:-|:-|:-|:-|:-|:-|:-|
| F-10 | Critical | §1b, L1, L2 | Replace the linear closest-approach term in `_norm_ca` (`decision.py:2044-2046`) with a threshold-anchored value function, anchored at an operator-set keep-out distance; re-anchor the delta-V scale (`decision.py:1921`); re-derive the reference cases | Probe P-17 inverted; scale rationale signed by the technical authority | M | L1 to 3 (part) |
| F-12 | High | §1a, §1b, L1 | Require P to sum to at most 1 with a residual "none of these" row (`routes/decision.py`; `Scenario.__post_init__`); show the shares used beside each P | Probe P-03b inverted; refusal above 1 | M | L1 to 3 (part) |
| F-14 | High | §1f, L1, L3 | Tie collect-first to the matrix: evaluate the pick under each cue outcome (`decision.py`); drop "where your response changes" in `threat_understanding.py:2021` until it does | Test: a cue that cannot change the pick yields no collect-first advice | M | L1, L3 (part) |
| F-16 | High | §1b, §1h, L1, L3 | Compute the smallest single-weight change that flips the pick (linear, so exact) and show it beside the recommendation (`decision.py`; `decision_results.html`); swing-weight elicitation (SPC-151) | Stability line on the page matching probe P-16 | M | L3 to 3 (part) |
| F-11 | High | §1g, §1h, L2, L3 | Sample the initial state from the `along_track` error model in `run_separation_series`, or add it in quadrature to computed misses in `_computed_cell` (`decision.py:3376-3394`); state it on screen | Test: band widens with element-set age at the model's rate | L | L2, L3 to 3 (part) |
| F-31 | Medium | G10, L1 | Refuse an all-zero weight total (`routes/decision.py:589-594`) and expected value with zero total P (`decision.py:3631-3643`), as the tree already does (`turn_update.py:196-197`) | Tests for both refusals | S | G10 (part) |
| F-30 | Medium | G10 | Altitude floor on the SGP4 path in `spectre/astro/elset_approach.py:77-122`, as `monte_carlo.py:900` has | Probe P-14 decayed case refused | S | G10 (part) |
| F-26 | Medium | L2, L3 | Compute P5's own bootstrap half-width for the label (`monte_carlo.py:1170-1179`; `decision.py:2169-2170`); keep the widest for convergence and name it | Label equals P5's half-width; test | S | L3 (part) |
| F-13 | Medium | §1c, L1 | Detect ties within a stated tolerance in `find_robust_response` and `_Selector.value`; show every tied response | Probe P-05 tie case shows both | S | L1 (part) |
| F-18 | Medium | L5 | Remove the green, amber and red score colours (`decision_results.html:231-236`, `:470`) or tie them to sourced thresholds | Page without unsourced colour bands | S | L5 (part) |
| F-27 | Medium | L2, L3 | Tighten RK45 tolerances or state integrator error in the sampled basis note (`monte_carlo.py:516-517`; `decision.py:2169-2175`) | P-13 under 0.1 km at 72 h, or the error stated | S | L2 (part) |
| F-23 | Medium | §1f, L1 | Require an operator-set response time before decide-by is shown, or source the default (`spectre/domain/decide_by.py:47`) | Test; or a cited default | S | L1 (part) |
| F-29 | Medium | G10, L2 | Regime-specific staleness limits and error rates for HEO and deep space (`spectre/web/elsets.py:77-80`; `spectre/astro/along_track.py:28-36`); flag SDP4 cells | Test per regime | M | G10 (part), L2 (part) |
| F-17 | Medium | L1, L2 | Restrict lookup-only results to training, or source the rules of thumb (`decision.py:1912-1917`, `:2007-2041`) through the F-05 register | Register entries; or a training-only label enforced | M | L2 (part) |

## Group C. Fix before accreditation

| Finding | Severity | Rubric | Remediation (files) | Evidence that closes it | Effort | Unlocks |
|:-|:-|:-|:-|:-|:-|:-|
| F-24 | Medium | L8 | Record the JSP 936 in-scope decision and an ethical risk assessment (framework recommendation 1) | The recorded decision and assessment | S | L8 to 2 or 3 |
| F-22 | Medium | §1e, L3, L4 | Back-test the custody likelihood on held histories (NOTSO cache, element-set histories); report a Brier score | Calibration report with data and code | M | L3, L4 to 4 (part) |
| F-19 | Medium | §1g, L2 | Compare the J2 and drag model with a higher-fidelity propagator by regime and burn size; state where `monte_carlo.py:24-26` holds (P-13: 11 to 18 km against SDP4 at GEO) | Comparison table by regime | L | L2 to 4 (part) |
| F-36 | Low | L2 | State, or remove, the WGS-72 to WGS-84 constant change at the SGP4 to RK45 handover (`propagator.py:112`; `constants.py:12-18`) and quantify it | Note and a measured figure | S | L2 (hygiene) |
| F-35 | Low | L2, L4 | Show the seed; check convergence on two seeds (`monte_carlo.py:253`) | Test | S | L4 (hygiene) |
| F-34 | Low | L2 | Range-check element-set fields at ingest (with F-25) | Test with inclination 597.4° refused | S | L2 (hygiene) |
| F-33 | Low | L5 | Refuse missing form values rather than defaulting (`routes/decision.py:233-275`, `:774-778`) | Test | S | L5 (hygiene) |
| F-32 | Low | L1 | Refuse a non-finite score in `find_robust_response` (`decision.py:3584-3643`) | Test with an injected NaN | S | L1 (hygiene) |
| F-38 | Low | L2 | Probe and, if confirmed, refuse a future-dated element set (`spectre/web/elsets.py:95-98`) | Probe result; test | S | L2 (hygiene) |
| F-15 | Low | §1a, L1, L5 | Reword "game-theoretic scenario evaluation" in `docs/generate_guide.py:399`; state that randomised responses are not considered | Regenerated guide | S | L1 (hygiene) |
| F-20 | Low | §1b, L1 | Document the additive independence of custody and closest approach; add an interaction term if the analyst session (SPC-080) supports one | Documented assumption | S | L1 (hygiene) |
| F-21 | Low | §1d, L1 | Name the static continuation after the last turn in the guide's limitations | Guide text | S | L1 (hygiene) |
