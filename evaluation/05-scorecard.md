# 05. Lens scorecard

**Rule:** framework 5.4 descriptors; a level is awarded only when every element of its descriptor is evidenced, and partial evidence takes the lower level. Weights are the framework's (5.3). Source of truth: `evaluation/scorecard.json`; reproduce with `python evaluation/score.py` (output saved in `evidence/score.txt`).

| Lens | Weight | Level | Why this level and not the next | Evidence |
|:-|:-|:-|:-|:-|
| L1 Decision-model soundness | 15 | 2 | Assumptions listed (D1 to D15, concept section 9), action types documented, weights recorded without method. Not 3: no vetoes, rules not shown together, weights not swing-weighted, closest approach nearly inert in the score | `decision.py:1465-1470`, `:2044-2069`; P-01, P-06, P-17; F-10, F-12 to F-14, F-16, F-17 |
| L2 Input fidelity and provenance | 12 | 2 | Basis tags exist but incomplete. Not 3: judgement inputs untagged, SGP4 and RK45 checks not in the suite, element-set error absent from the miss, UDL sets unchecked | `provenance.py:55-75`; P-11 to P-14; F-05, F-06, F-11, F-25 to F-27, F-29 |
| L3 Uncertainty | 13 | 2 | Intervals shown (sampled bands, TCA ±, P intervals). Not 3: element-set error not propagated; weight stability not shown though a 0.089 weight change flips the pick | `decision.py:1156`, `:3712-3752`; P-16, P-18; F-11, F-16 |
| L4 V&V and test evidence | 15 | 2 | Large developer suite, reference cases, coverage floors, mutation run. Not 3: no metamorphic or published-vector suite in the repository; no Aqua Book V&V record | `evidence/baseline-tests.log`; `.github/workflows/ci.yml`; `docs/MUTATION-REPORT.md`; F-06, F-22 |
| L5 Human-in-the-loop | 15 | 1 | One rule's answer shown, no decision record. Rich rationale text, but level 2 needs the operator's decision logged | `decision_results.html:76-160`; `decision_job.py:240-248`; F-01, F-03, F-13, F-18 |
| L6 Safety | 10 | 1 | No hazard analysis visible (provisional) | `audit/GAPS.md:12`; F-07 |
| L7 Security | 8 | 2 | Application trust-boundary inventory and a remediated security audit. Not 3: no ISN 2023/09 application, no record integrity, permissive Content Security Policy, unchecked UDL ingest | `audit/ARCHITECTURE.md:56-66`; `app.py:298`; F-08, F-25 |
| L8 AI governance | 7 | 1 | No AI scoping decision recorded (provisional) | search for JSP 936: no match; F-24 |
| L9 Efficiency | 5 | 2 | Runtime measured and used to set the budget. Not 3: no decision window stated | `decision.py:2088-2106` |

**Overall score:** Σ(weight × level) / 100 = (30 + 24 + 26 + 30 + 15 + 10 + 16 + 7 + 10) / 100 = **1.68**.
**Score band:** Not ready (below 2.5). **Gate result:** Fail (9 Red). **Verdict: Fail.**
