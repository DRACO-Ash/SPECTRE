# 06. Rubric self-test

Command: `python evaluation/score.py --sensitivity` (output: `evidence/score-sensitivity.txt`). Runs: the weights as written; equal weights (11.1 each); each lens weight raised and lowered by 50 %, the others rescaled to keep 100.

## Weight sensitivity

● **Verdict:** Fail in all 20 runs. The gate decides it (9 Red), so no weight setting can change it. This is the gate working as designed, not evidence that the weights are right.
● **Score band (ignoring the gate):** Not ready in all 20 runs. Scores range from 1.62 (L5 × 1.5) to 1.74 (L5 × 0.5); equal weights give 1.67. **No run changes the band; the result is not weight-sensitive.**
● The lens that moves the score most is L5 (human-in-the-loop, level 1, weight 15): it drives the extremes in both directions.
● Distance to the next band edge: the score needs 0.82 more (82 weighted level points) to reach Conditional at 2.5. No single lens can supply that: the largest single-lens gain, L1, L4 or L5 raised from its level to 5, is 45 to 60 points.

## Level sensitivity (a proxy for assessor disagreement)

● One level higher on every lens gives 2.68, **Conditional**; one level lower is impossible on the four lenses already at 1. So a uniformly more lenient assessor would move the score band, though not the verdict (the gate still fails).
● Inference: the score band is robust to weights but not to a systematic one-level shift in judgement, which is what a second assessor would test.

## Inter-assessor reliability

Not tested: there is one assessor. The assessor also built or directed much of the code under assessment earlier in the same session (see `02-gate-assessment.md` section 4). A second, independent scoring with quadratic-weighted Cohen's kappa on the lens levels (framework 5.5) is recommended before this verdict is relied on, with moderation of any lens on which the two differ by 2 levels or more.
