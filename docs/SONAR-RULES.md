# SonarQube rules the App Store gate has raised on SPECTRE

The App Store's Code Quality gate is SonarQube scoring new and changed code
only. Every failed submission from 0.6.0 to 0.6.3 was a rule in the table
below. Each one is a check in `scripts/sonar_rules.py` (SPC-233), which runs
in `scripts/check-quality.sh` (and so in CI's Quality Gate job) and in
`scripts/package-appstore.sh`, so a package cannot be built with a known rule
broken on changed code.

`tests/unit/test_sonar_rules.py` holds this table and the checker to the same
list of rule ids: a row without a check, or a check without a row, fails the
suite. Each rule also has a test that reproduces the gate's line.

This page is the rule ledger. How the gate scopes new code in general, the
cognitive complexity meter (S3776) and the fix pattern for each rule class are
in `docs/CODE-QUALITY-GATE.md`, and are not repeated here.

## Where the new-code window starts

The platform measures new code from master, and master has stood at 0.6.4
(`77a1088`) since that release was merged for the App Store. Every line
changed since then is new to the gate, not only the latest release's lines.
So there are two useful bases:

● `python3 scripts/sonar_rules.py` (base master, the default): what the next
  submission will be scored on. Pass the same to the packager as
  `SONAR_BASE`, or leave it to default.
● `sh scripts/check-quality.sh <previous release commit>`: what one release
  adds, which is how each ledger entry is measured.

Owner ruling, 12 November 2026: latent issues are converted as their lines are
touched, and the checker gates new code only. A latent issue on a line nobody
has edited since master is not reported.

## How the gate scopes, which matters as much as the rules

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
  differently, so a finding can appear on a line the edit did not touch. Each
  one seen so far was a real change since master (the Time to execute fields'
  `step`, changed on 10 November 2026), so treat it as real. A blame-based
  cross-check against master agreed with the diff-based count after SPC-233.

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
| `Web:S6819` | 0.6.0, 0.6.3 | `role="button"` and `role="heading"` on spans, `role="status"` on a static banner | A native element (`<button>`, `<h3>`), `role="note"` for a static banner, `aria-live="polite"` for a live region | A role with a native element equivalent, `role="img"` on `<svg>` and `<img>` aside | `role="note"` and `aria-live` have passed every scan (0.6.4 shipped `aria-live` in place of `role="status"`). `aria-atomic="true"` keeps what `role="status"` implied. FACT: the gate raises `role="img"` on a `<canvas>` (PR 35, against master); see below. |
| `Web:JinjaCommentInTag` | 0.6.0 (3) | `{# #}` comments inside `<tr>` tags mentioning `role="button"`, `aria-controls`, `aria-label` | Comment moved above the tag | A `{# #}` inside a tag: blocking when it holds `=`, `role` or `aria-`, a warning otherwise | FACT: Sonar's HTML parser read the comment's words as attributes and raised S6819 and S6793 on them. A comment without such words inside a `<button>` passed 0.6.3. |

Rules raised once and fixed by restructuring rather than by a pattern, so not
encoded: `javascript:S3776` (cognitive complexity in `aiSort`, 0.6.0; the
Python scorer does not read JavaScript) and `Web:S6793` (an artefact of the
Jinja comments above). A JavaScript function grown past 15 is the one known
way to fail the gate that no script here catches.

Vendored, minified libraries (`spectre/web/static/*.min.js`) are out of the
checker's scope. They are never edited here, their versions are pinned in
`spectre/web/static/vendored.json`, and they enter the window only when an
upgrade replaces one whole.

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

## Where the tree stands (12 November 2026)

Against master (`77a1088`), the window the next submission is scored in, the
checker found 99 blocking findings before SPC-233: 34 S7761, 19 S1244, 16 S7632,
13 S7773, 6 S3358, 4 labels, 3 S6819, 3 S6353 and 1 S1192. SPC-233 cleared 98
of them, and the clearing brought 2 more labels into the window (the Time to
execute fields above), which it also cleared. One remains:

● `Web:S6819` on `<canvas id="tca-hist-chart" role="img" aria-label="...">` in
  `partials/decision_results.html`. FACT: the gate raised it on PR 35, scored
  against master on 13 November 2026. Fixed there the way this ledger set out,
  a call Claude made for the owner to confirm: the canvas sits in a `<figure>`
  whose visually hidden caption names the chart and points to the table below,
  and the canvas is hidden from assistive technology, so a screen reader reads
  the caption and the table's exact counts rather than an image.

`python3 scripts/sonar_rules.py --all` checks every line, not just changed
ones. On 12 November 2026 it found 124 blocking issues: the canvas above, and
123 on lines nobody has touched since master (S8410 85, S1192 14,
InputWithoutLabelCheck 13, S7632 8, S1244 2, S3358 1). None of the 123 counts
today, and each fires the day its line is edited, so fix it in the same
change.

## When the gate raises something new

1. Add a row to the table above: the rule, the release, the line the gate
   named, and what passed.
2. Add a check to `scripts/sonar_rules.py` and its id to `RULES`.
3. Add a test to `tests/unit/test_sonar_rules.py` that reproduces the gate's
   line as a failure and the fix that passed as a pass, and see it fail
   before the check exists.
4. Replay the failed release with the checker and confirm it reports the
   gate's lines and no others, then fix the code.
