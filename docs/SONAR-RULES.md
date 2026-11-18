# SonarQube rules: the gate and the fast pre-check

## The policy (owner's instruction, 18 November 2026)

**Zero open SonarQube issues and zero unreviewed security hotspots, across the
whole codebase, measured by SonarQube itself at check time.** Not new code, not
changed lines: every file in the App Store package, every rule in the profile.

This supersedes the owner's ruling of 12 November 2026, under which latent
issues were converted as their lines were touched and the checker gated new
code only. That approach let 0.48.5 ship with 174 platform findings (165 code
smells, 9 bugs) while `scripts/sonar_rules.py`, which checks 14 rules on
changed lines, reported it clean. A replica of a few rules cannot see what the
analyser sees, so the gate now runs the analyser.

● **The gate** is `scripts/sonar-gate.sh`. It runs a pinned SonarQube
  Community Build in docker against the package tree with the profile in
  `scripts/sonar-profile.json`, and fails on one issue or one hotspot to
  review. The packager, `scripts/check-quality.sh` and CI's `sonarqube` job
  all run it. How it works, how to run it and what the profile holds are in
  `docs/CODE-QUALITY-GATE.md`.
● **The fast pre-check** is `scripts/sonar_rules.py`, the subject of the rest
  of this page. It still runs first in the packager and in
  `scripts/check-quality.sh`, because it answers in seconds where the gate
  takes minutes, and it names the rules the platform has failed a submission
  on. It is never the verdict: a clean pre-check with a failing gate is a
  failure.

## The pre-check and its ledger

The rules below are the ones the platform failed submissions on from 0.6.0 to
0.6.3. Each is a check in `scripts/sonar_rules.py` (SPC-233).
`tests/unit/test_sonar_rules.py` holds this table and the checker to the same
list of rule ids: a row without a check, or a check without a row, fails the
suite. Each rule also has a test that reproduces the gate's line.

The pre-check still scopes the way the platform's new-code window did, to lines
changed since a base (`master` by default, `SONAR_BASE` in the packager), and
`python3 scripts/sonar_rules.py --all` checks every line. Under the zero policy
a finding `--all` reports is a real issue whether or not its line changed, and
the gate will report it too.

## How the platform scoped new code (historical)

These observations explain the pre-check's design and its calibration. They
no longer limit what must be fixed.

● **An edit to a line brings what is already on it into scope.** 0.6.3 rewrote
  `title` attributes on 9 fields that had never had a label, and the 9 missing
  labels were counted as new issues. The same release corrected the training
  banner's `aria-label`, and its old `role="status"` was counted too. So the
  checker runs every rule on every changed line, or every element with a
  changed line, whatever the edit was for.
● **For an element, any changed line counts, and the issue is reported on the
  element's first line.** A rewritten title two lines below `<input` put the
  input in scope at the `<input` line.
● **Threshold rules fire when the threshold is crossed.** A literal used twice
  on the base and three times now is a new issue, even though the edit added
  only one use. One already over the threshold on the base is an existing
  issue, and further uses do not create a new one.
● **Which lines count as changed depends on how the diff aligns.** Adding a
  label line above an input can make git pair a later, already-changed line
  differently, so a finding can appear on a line the edit did not touch.

## The rules

| Rule | First raised | What triggered it here | The fix that passed | Check | Limits (FACT, INFERENCE, UNKNOWN) |
|---|---|---|---|---|---|
| `python:S1192` | 0.6.0 (11) | Template paths, `"/login"`, `"Hop Type"`, `"Close-Proximity Operation"` used three or more times in a file | One module constant per literal | Literals of 5 or more characters at 3 or more uses with one on a changed line, new when the base had fewer than 3; f-string fragments warn | INFERENCE: identifier-like literals (`\w+` only) are not counted. Every literal the gate flagged held a space, slash, hyphen or dot, and `"fields_side"`, new at 3 uses in 0.6.4, passed. INFERENCE: under 5 characters is not counted. UNKNOWN: whether f-string fragments count, so they warn rather than block. |
| `python:S1244` | 0.6.0 (5 bugs) | `ecc == 0.0` and similar exact zero tests | Named tolerances (`_CIRCULAR_ECC` and others) where noise should count as zero; `not x` where an exact zero is a sentinel | `==` or `!=` with a float literal on either side | FACT: the 0.6.0 sites were bugs, not smells; one named the wrong node on rounding noise. FACT: `not x` is true for `0.0` and `-0.0` and false for NaN, exactly as `x == 0.0`, so SPC-233 used it wherever behaviour had to stay identical. A tolerance changes behaviour and needs its own test. |
| `python:S3358` | 0.6.0 | A conditional expression nested in another | Statements | Any `x if c else (y if d else z)` shape, including one inside an f-string or a call argument | |
| `python:S107` | 0.6.0 (2) | `apply_intercept` and `decision_evaluate` with dozens of `Form()` parameters | Pydantic form models | More than 13 parameters, `self` and `cls` aside, when the signature changed | INFERENCE: 13 is the sonar-python default. Ruff's PLR0913 in `check-quality.sh` fires earlier. |
| `python:S8410` | 0.6.0 (3) | `user: User = Depends(require_login)` in route signatures | `Annotated[User, Depends(require_login)]` | A route parameter whose default is `Depends`, `Form`, `Query`, `Body`, `Header`, `Cookie`, `File`, `Path` or `Security`, on a changed line | FACT: 85 route parameters still use the default style (12 November 2026); each fires the day its line is edited. `tests/unit/test_routes_use_annotated_depends.py` is the file-wide ratchet beside this line-scoped check. |
| `python:S5713` | 0.6.0 | `except (SignatureExpired, BadSignature)` | Drop the subclass | An except tuple naming a class and its subclass, resolved through builtins and third-party imports | Classes defined in SPECTRE are not resolved, because resolving them would import application code. |
| `python:S7504` | 0.6.0 | `for task in list(tasks)` | Iterate directly (`cancel()` only schedules the set edit) | `list(x)` as the iterable of a `for` or comprehension | If the loop mutates what it walks, copy with `.copy()` or `[*x]` rather than dropping the copy. UNKNOWN: whether `tuple()` is flagged the same way. |
| `python:S6353` | 0.6.0 | `[a-zA-Z0-9_]` in the DDL identifier allow-list | `\w` with `re.ASCII`, so the allow-list is no wider | The common spelled-out classes in a literal passed to `re.*` | Without `re.ASCII`, `\d` and `\w` accept other scripts' digits and letters: always add the flag. |
| `python:S7632` | 0.6.0 | `# noqa: BLE001 - any unreadable body has no token` | The rationale on the line above, `# noqa: BLE001` alone | Any text after a noqa comment's codes, on a changed line | FACT: 8 such comments remain on lines unchanged since master (12 November 2026). |
| `javascript:S7773` | 0.6.1 (2) | `parseFloat` and `isNaN` in the intercept sort, added by the 0.6.1 fix itself | `Number.parseFloat`, `Number.isNaN` | Bare `parseFloat`, `parseInt`, `isNaN`, `isFinite` in `spectre/web/static/js/` and templates | `Number.isNaN` does not coerce, so it is equivalent only on a number: every site SPC-233 changed tests the result of `Number.parseFloat`. |
| `javascript:S7761` | 0.6.0 | `item.setAttribute('data-idx', ...)` | `item.dataset.idx = ...` | `get/set/remove/hasAttribute` with a whole literal `data-*` name | FACT: `getAttribute('data-sort-' + col)` passed; a built name is not flagged. An absent attribute reads `undefined` through `dataset`, not `null`, so a test for presence becomes `=== undefined`. |
| `Web:InputWithoutLabelCheck` | 0.6.3 (9) | Fields whose `title` was rewritten, which had a placeholder and no label | An `id` and a `<label for>`, visually hidden where the layout shows the purpose | An `input`, `select` or `textarea` (not hidden, submit, button, reset or image) with no wrapping `<label>`, no `<label for>` matching its `id`, and no non-blank `aria-label` or `aria-labelledby` | FACT: a wrapping label passes (the Max ΔV inputs, touched in 0.6.3, were not flagged). FACT: markup inside a `<script>` string is not parsed. INFERENCE, not yet scored: `aria-label` passes, as it gives the field its accessible name. SPC-233 uses it only on the Decision Engine's adversary and friendly rows: `decision.js` clones a `<template>` row, so an `id` could not be unique, and `tests/unit/test_decision_row_templates.py` holds the template and the server row to the same text, which a visually hidden label would break. Everywhere else a field gets an `id` and a `<label for>`. If the gate raises an `aria-label` field, `decisionAddRow` must number ids as it numbers values. |
| `Web:S6819` | 0.6.0, 0.6.3 | `role="button"` and `role="heading"` on spans, `role="status"` on a static banner | A native element (`<button>`, `<h3>`), `role="note"` for a static banner, `aria-live="polite"` for a live region | A role with a native element equivalent, `role="img"` on `<svg>` and `<img>` aside | `role="note"` and `aria-live` have passed every scan (0.6.4 shipped `aria-live` in place of `role="status"`). `aria-atomic="true"` keeps what `role="status"` implied. FACT: the gate raises `role="img"` on a `<canvas>` (PR 35, against master); fixed there with a `<figure>` whose visually hidden caption names the chart, and the canvas hidden from assistive technology. |
| `Web:JinjaCommentInTag` | 0.6.0 (3) | `{# #}` comments inside `<tr>` tags mentioning `role="button"`, `aria-controls`, `aria-label` | Comment moved above the tag | A `{# #}` inside a tag: blocking when it holds `=`, `role` or `aria-`, a warning otherwise | FACT: Sonar's HTML parser read the comment's words as attributes and raised S6819 and S6793 on them. A comment without such words inside a `<button>` passed 0.6.3. |

Rules raised once and fixed by restructuring rather than by a pattern, so not
encoded: `javascript:S3776` (cognitive complexity in `aiSort`, 0.6.0; the
Python scorer does not read JavaScript) and `Web:S6793` (an artefact of the
Jinja comments above). The pre-check cannot see a JavaScript function grown
past 15; the gate can, because `javascript:S3776` is in the profile.

Vendored, minified libraries (`spectre/web/static/*.min.js`) are out of the
pre-check's scope. They are never edited here and their versions are pinned in
`spectre/web/static/vendored.json`. The scanner's bundle detection skips files
that look generated, and neither the platform's scan nor the gate's raised an
issue on one in 0.48.5.

## The calibration

The checker was run on each release against the one before it, and compared
with what the gate reported (28 October 2026, on the charming-dirac line, before
the port):

| Release | Gate reported | Checker reported |
|---|---|---|
| 0.6.1 against 0.6.0 | 2 (S7773) | the same 2, same lines |
| 0.6.2 against 0.6.1 | passed | 0 |
| 0.6.3 against 0.6.2 | 10 (9 labels, 1 S6819) | the same 10, same lines |
| 0.6.4 against 0.6.3 | passed | 0 |
| 0.6.5 before its literal fix | not submitted | 1 (the timestamp format, found by hand that day) |
| 0.6.5 as shipped | passed | 0 |

0.6.0 cannot be replayed: its 36 issues were scored against a baseline this
repository does not record. The port's one change to a verdict is the
`aria-label` acceptance, and no field in 0.6.1 to 0.6.5 carried one, so the
table stands.

## Where the tree stood

On 12 November 2026 `python3 scripts/sonar_rules.py --all` found 124 blocking
issues, 123 of them on lines nobody had touched since master. Under the ruling
of that day none counted. Under the policy of 18 November every one counts, and
the gate measured the 0.48.5 package at 206 open issues with the profile in
`scripts/sonar-profile.json` (the platform's own scan listed 174 of them).
Release 0.48.6 clears them; the gate holds the count at zero from then on.

## When the platform raises something new

1. Add the rule key to its language in `scripts/sonar-profile.json`. If the
   Community Build cannot run it (as with `pythonbugs:S6466`), list it under
   `not_in_community_build` with the reason and how it is held instead.
2. Add it to `_PLATFORM_RAISED` in `tests/unit/test_sonar_gate.py`, so the
   profile cannot lose it.
3. Run `sh scripts/sonar-gate.sh` and fix what it reports.
4. If the rule is cheap to approximate and has failed a submission, it may also
   join the pre-check: add a row to the table above, a check to
   `scripts/sonar_rules.py` and its id to `RULES`, and a test to
   `tests/unit/test_sonar_rules.py` that reproduces the platform's line as a
   failure and the fix that passed as a pass.
