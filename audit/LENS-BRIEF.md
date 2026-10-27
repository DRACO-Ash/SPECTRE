# Lens brief: return shape for slice reviewers (phases 4 and 5)

Each reviewer audits one bounded slice of the SPECTRE repository at `/home/user/SPECTRE`. Read-only on the repository: use Read, Grep and Glob, and never edit, create or delete a file in the repository. Your single output file is the scratch path given in your task. UK English, no em-dashes, plain language.

Context you may read: `audit/ARCHITECTURE.md` (entry points, trust boundaries, credential scope), `audit/TOOLS.md` and `audit/tools-raw/` (deterministic tool output, including per-site ruff, vulture, radon and coverage in `pytest.txt`). Do not read `audit/PRIORS.md`, and do not read `bluestaq-foundations-v1.99.0.zip`.

## Rules

1. Evidence or silence. Every claim row and every finding cites `path:line` and quotes up to 3 lines copied **exactly**, character for character, from the file. The quote is checked by script later; a paraphrased quote counts as a reviewer error.
2. A negative claim ("unused", "never called", "no test", "not validated") must carry the Grep pattern you ran and its result, in one line.
3. Mark every analytical statement as fact, inference or speculation.
4. Unknown means "TBC, re-verify" and names the check that would settle it. Never invent a line number, field, constant source or behaviour.
5. Do not fix anything. Do not soften. Do not pad: if a file is genuinely sound, mark it CLEAN with a specific one-line reason ("pure dataclass definitions, no logic"; "all three branches tested at tests/unit/x.py:40-88"). "Nothing of note" is not a reason.

## Lenses (apply all that are relevant to the slice)

L1 correctness and edge cases · L2 error handling and failure modes · L3 security · L4 contracts and data · L5 resource lifecycle and concurrency · L6 performance and complexity (cognitive complexity above 15 is a finding; see `audit/tools-raw/cogcx_run.txt`) · L7 design and structure (dead code, duplicated constants) · L8 clarity and comments (a comment or docstring that does not match its code is a defect) · L9 observability (anything sensitive reaching logs) · L10 build, config and deploy · L11 numerical and scientific correctness, mandatory for any physics, astrodynamics, statistics or signal processing:
● Check every solver and closed-form routine against an independent reference case with a stated tolerance, and name the reference (textbook, example number). Where you can, compute the reference yourself by hand in your reasoning and compare it with what the code would return.
● Check unit consistency across every boundary: km/m, deg/rad, s/min/day, TEME/J2000/GCRF.
● Convergence: iteration caps, divergence handling, what is returned on non-convergence, and whether the caller can tell.
● Physical plausibility guards: does the code refuse an impossible result?
● Computed-versus-modelled boundary: is every heuristic, tuned constant or uncalibrated score distinguishable as such in the code, in the response payload and in the template the operator sees? A heuristic presented with the authority of validated physics is High.
● Trace every magic constant to a source, and flag duplicates across the repository (Grep for the value).
● Check that any docstring attributing an algorithm to a source matches what the code actually implements.

For tests covering the slice: does a test pin each solver to an independent reference with a tolerance, or only check that it runs? Flag tests with no assertion, tests that assert only on a mock, and duplicate tests.

## Output file shape (Markdown, exactly these four sections)

```
# Slice <ID>: <name>

## A. Ledger
| Path | Status | Reason |
|---|---|---|
| spectre/x.py | REVIEWED | findings F-<ID>-01, F-<ID>-03 |
| spectre/y.py | CLEAN | <specific reason> |

## B. Claims
| # | Claim (quoted) | Source path:line | Implementing path:line or ABSENT | Proving test path:line or NONE | Status |
|---|---|---|---|---|---|
Status is one of PROVEN | IMPLEMENTED-UNTESTED | DRIFTED | ABSENT | UNDOCUMENTED-BEHAVIOUR.
Extract every material behavioural claim: module and function docstrings, inline comments that assert behaviour, error messages, and type hints that promise a contract. Skip trivial claims ("returns a list" on a function that obviously does).

## C. Candidate findings
One block per candidate, in this schema, exactly:

ID:          F-<ID>-01
Lens:        L<n> <name>
Severity:    Blocker | High | Medium | Low
Confidence:  High | Medium | Low
Epistemics:  fact | inference | speculation
Location:    path/to/file.py:120-124
Evidence:
    <line 120 copied exactly, indented four spaces>
    <up to two more lines>
Issue:       one sentence
Impact:      worst realistic case
Fix:         the change, concretely
Gate:        the test, lint rule, type constraint or CI check that prevents recurrence
Negative-check: <grep pattern and result, or n/a>

## D. Notes
Anything you could not examine, could not verify, or that a human must decide.
```

Severity: Blocker means an exploitable security flaw, data loss or corruption, numerically incorrect output presented as correct, or a deployment-gate failure. High means wrong behaviour under realistic conditions, missing authz, a false claim in documentation, an uncalibrated heuristic presented as computed, or an untested risk-bearing path. Medium means a latent defect, complexity above the cap, a weak or absent test, a misleading comment or name, or a fix with no regression gate. Low means style, polish or consistency.

Return to the orchestrator only a summary of at most 15 lines: file counts by status, the number of claims by status, the number of candidates by severity, and the three most serious candidates in one line each.
