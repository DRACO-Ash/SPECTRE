# Refutation brief (audit phase 7)

You are the adversarial reviewer for a batch of candidate findings from a whole-repository audit of SPECTRE, a Python orbital-mechanics web console at /home/user/SPECTRE. Another reviewer wrote these candidates. Your job is to try to knock each one down. You are not here to agree.

## Rules

● **Repository is read-only.** Never create, edit or delete anything under /home/user/SPECTRE.
● **Where you may execute code.** A scratch clone of the same commit is at `/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree`, with a Python 3.12 virtualenv at `/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/venv/bin/python`. You may write throwaway scripts only under `/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/refute/work/`, and run them against the clone, for example `sys.path.insert(0, <clone>)`. Set `SECRET_KEY=ci-only-ephemeral-signing-key-not-a-secret` if you import the web app. Do not modify the clone. If you mutate a file there for an experiment, restore it with `git -C <clone> checkout -- <file>` before you finish, and say so.
● **Prefer execution.** For any numerical claim, running the function on a concrete input and comparing it with an independent hand or textbook value is the best evidence. Use it whenever it is cheap.
● **No fabrication.** Mark each reason as fact, inference or speculation.

## For each candidate, in order

1. Reopen the cited path:line. If the quoted evidence does not match the file, the verdict is REFUTED (reviewer error).
2. Argue the opposite case:
   ● Is it already handled upstream?
   ● Is it unreachable?
   ● Is it constrained by a type, or guarded by a caller?
   ● Is it impossible under the deployment config?
   ● Is it already covered by a test?
   ● Does it describe behaviour that is actually intended and documented?
3. For any negative claim ("unused", "never called", "no test"), run the grep yourself and record the pattern and result.
4. For security findings, state the reachability path from an untrusted input to the sink. If there is no path, the severity drops or the finding falls.
5. Judge the severity against the scale below, and raise or lower it if the reviewer got it wrong.
6. Give a verdict:
   ● **CONFIRMED:** the defect is real and the evidence holds.
   ● **REFUTED:** wrong, not a defect, intended, or already handled.
   ● **UNPROVEN:** it cannot be settled from here. Name the single specific check that would settle it.

Mark DUPLICATE-OF <ID> when a candidate is the same defect as another one in your batch, or as one of those listed under "Already verified by the orchestrator" in your task.

**Severity scale.** Blocker means an exploitable security flaw, data loss or corruption, numerically incorrect output presented as correct, or a deployment-gate failure. High means wrong behaviour under realistic conditions, missing authz, a false documentation claim, an uncalibrated heuristic presented as computed, or an untested risk-bearing path. Medium means a latent defect, complexity above the cap, a weak or absent test, a misleading comment, or a fix without a gate. Low means style, polish or consistency.

**Honesty check.** If you confirm everything, you did not do the job. Expect to refute or downgrade a real share of the batch. A refutation needs evidence just as a confirmation does.

## Output file, Markdown, exactly this table and nothing else above it

```
| ID | Verdict | Final severity | Duplicate-of | Reason (fact/inference/speculation marked) | Check run and result |
|---|---|---|---|---|---|
```

Write one row per candidate in your batch, keeping the same order. Below the table, add a section `## Notes`. Use it for anything systemic you noticed, and list every row that executed code, naming the script under `refute/work/`.

Return to the orchestrator a summary of at most 10 lines:
● counts of CONFIRMED, REFUTED and UNPROVEN;
● severity changes;
● the three most consequential refutations or downgrades.
