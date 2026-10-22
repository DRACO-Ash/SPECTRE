# Code Quality: the SonarQube gate

**The gate scopes to NEW CODE.** That single fact explains the shape of every
report it has produced, and it is the first thing to understand before fixing
anything.

## What the report is, and is not

SonarQube reported 57 findings against release 0.5.23. The tree contains far
more than 57 instances of those same rules. Examples measured directly:

| Rule | Reported | Actually in the tree |
|---|---|---|
| python:S3776 cognitive complexity over 15 | 16 | 43 |
| python:S8410 FastAPI dependency injection without `Annotated` | 4 | 108 |
| python:S7632 malformed suppression comment | 5 | 21 |
| Web:MouseEventWithoutKeyboardEquivalentCheck | 7 | 50 |

The difference is not an oversight by the scanner. Sonar reports a rule against
a function or a line only when that code is inside the new-code window, which
for this project tracks the diff against the default branch. Every file in the
report had changed; no unchanged file appeared, and `udl.py:fetch_tle` scores 67
without being reported because nobody has touched its lines.

Two consequences follow, and they pull in opposite directions.

● **A fix is cheaper than it looks.** You do not have to clear the whole tree
  to clear the gate.
● **A refactor is more expensive than it looks.** Every line you touch enters
  the window. A function you edit for one rule is then scanned against ALL of
  them, so a refactor that clears S3776 and introduces a duplicated literal has
  cost a submission rather than saved one.

The second is why `scripts/check-quality.sh` now runs a complexity check scoped
the same way, and why the refactors in 0.5.24 were each reviewed by a second
pass before they were kept.

## Measuring cognitive complexity locally

`scripts/cognitive_complexity.py` implements SonarSource's Cognitive Complexity
algorithm (python:S3776) so the number can be known before the upload rather
than after it.

**Ruff's C901 is not a substitute.** C901 is cyclomatic complexity: it counts
decision points. S3776 adds a NESTING PENALTY, so one deeply nested branch can
cost more than five flat ones, and the two measures diverge by a factor of three
on real code. A function at C901 8 can be at S3776 38.

### Calibration

The implementation is checked against sixteen functions whose exact Sonar scores
are known from the 0.5.23 scan report:

```
scripts/cognitive_complexity.py --calibrate
```

All sixteen reproduce exactly. The calibration reads those functions at the
revision Sonar scanned rather than from the working tree, because the point of
the report was to go and change them; the revision is pinned in the script.

One case needed a real correction rather than a tuning fudge, and it is worth
recording because it is not obvious. An `else:` whose body is a single `if` is
the SAME AST node as an `elif`, and only the column offset distinguishes them.
Scoring both as "else if" under-counted `solve_lambert` by exactly 2. Fifteen
cases agreed before that fix and sixteen after, which is the difference between
a tool you can trust and one that is usually right.

### Usage

```
scripts/cognitive_complexity.py                      whole tree, over the limit
scripts/cognitive_complexity.py --all <file>         every function in one file
scripts/cognitive_complexity.py --changed master     only what this branch touched
scripts/cognitive_complexity.py --calibrate          check against Sonar's own scores
scripts/cognitive_complexity.py --json               machine-readable
```

`--changed` is the one that mirrors the gate, and it is the one wired into
`scripts/check-quality.sh`. It is scoped to `sonar.sources`, so a complex
function in `scripts/` does not fail a loop over code the gate never sees.

## How each rule class was cleared

● **S3776** cognitive complexity over 15. Extract the deepest nested block whole
  into a module-private helper that takes exactly what it needs. Guard clauses
  and early returns. An if/elif ladder over a value becomes a module-level dict
  lookup. Splitting a function into halves that each need the other's locals
  scores no better and reads worse.
● **S1192** a literal repeated three or more times in one file. A module-level
  constant named for what the string MEANS, not for its text, used at every
  occurrence including the ones not flagged.
● **S3358** nested conditional expression. An if/elif/else statement, or a small
  helper. Not a reformatted ternary.
● **S1172** unused parameter. Check every call site first: a positional caller
  silently shifts its arguments when a parameter is removed. Where the parameter
  exists to satisfy a shared signature, keep it and prefix it with an underscore.
● **S125** commented-out code. Delete it, or rewrite it as prose that does not
  look like code.
● **S7632** malformed suppression comment. Ruff's grammar is
  `# noqa: CODE[, CODE]` and nothing else on the line. The rationale moves to a
  comment above; it is never dropped, because it is the only record of why the
  suppression is correct.
● **S8410** FastAPI dependency injection. `Annotated[User, Depends(...)]` rather
  than `User = Depends(...)`. The converted parameter has no default, so it must
  precede any parameter that does.
● **S8517** sorting to find an extreme. `min()` and `max()`.
● **S5145** logging user-controlled data. `spectre/web/log_safety.log_safe()`
  strips line breaks and control characters so a newline in a username cannot
  forge an audit record.
● **Web:MouseEventWithoutKeyboardEquivalentCheck** and friends. A shared
  `spectreActivate(event)` handler in `base.html`; elements opt in with
  `tabindex="0" onkeydown="spectreActivate(event)"`. A console that answers only
  to a mouse is unusable from a keyboard, which in an operations room is a real
  barrier and not a formality.
● **css:S7924** contrast. The caution amber `#EF9F27` is 9.00:1 on the dark
  theme and 1.98:1 on the light one, which fails WCAG AA outright. A theme-aware
  `--spectre-color-caution-amber-text` token resolves to `#8A5600` on light
  surfaces (5.59:1 on `#F3F4F6`, 6.16:1 on `#FFFFFF`).

## What is deliberately not fixed

● **The out-of-scope population**, measured above. Clearing all 43 complex
  functions in one release would mean restructuring code the report never
  touched, with every one of those refactors carrying behaviour risk, to clear
  findings the gate is not raising. They are measurable at any time with
  `scripts/cognitive_complexity.py`, and the worst of them,
  `udl.py:fetch_tle` at 67, is a landmine: the next person to edit that function
  for any reason puts it in scope.
● **`_entrypoint.py:27` and `gcat.py:274`.** Both need two suppression
  directives on one line, one for ruff and one for bandit, and Python allows one
  comment per line. The alternative is moving a narrow, justified, per-line
  suppression into a project-wide bandit skip, which is worse security hygiene
  than a comment Sonar dislikes. Neither line is currently in scope; if one ever
  is, the honest answer is the project-wide skip with the rationale recorded
  here, not a silent deletion of the bandit directive.
● **The remaining 104 `Depends(...)` defaults.** Converting them is mechanical
  but not free: `Annotated` removes the default, which forces parameter
  reordering across a hundred route signatures, and a mistake there is a 500 on
  a live route rather than a scanner finding. They convert file by file as those
  files are touched for other reasons.

## Before you upload

```
scripts/check-quality.sh                       includes the scoped complexity leg
scripts/cognitive_complexity.py --calibrate    the meter still agrees with Sonar
scripts/preflight-gate.py .                    the package contract
```

A green local loop is necessary and never sufficient: the Sonar ruleset is
server-side and reveals rule classes progressively. Expect the next scan to
surface something these three checks cannot see, and read the report as a sample
of a population rather than as the work list.
