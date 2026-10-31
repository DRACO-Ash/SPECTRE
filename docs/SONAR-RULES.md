# SonarQube rules the App Store gate has raised on SPECTRE

The App Store's Code Quality gate is SonarQube scoring new and changed code
only. Every failed submission from 0.6.0 to 0.6.3 was a rule in this table.
Each one is now a check in `scripts/sonar_rules.py`, which runs in
`scripts/check-quality.sh` (and so in CI's Quality Gate job) and in
`scripts/package-appstore.sh`, so a package cannot be built with a known
rule broken on changed code.

`tests/unit/test_sonar_rules.py` holds this table and the checker to the same
list of rule ids: a row without a check, or a check without a row, fails the
suite.

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
● **Coverage has the same window.** Every changed executable line needs
  coverage, 80% across the change. Moving a noqa rationale or hoisting a
  literal marks a never-tested error branch as changed code. 0.6.6 measured
  82% against master and 68% against 0.6.5, the release the gate would score
  it against; 18 failure-path tests brought it to 100%.
● **The baseline is the last release the gate scored, not master.** Until a
  release is merged, master is behind it, and measuring against master
  scores the previous release's well-tested lines as part of this one. Pass
  that release's commit to `scripts/check-quality.sh` and, as `SONAR_BASE`,
  to the packager.
● **Threshold rules fire when the threshold is crossed.** A literal used twice
  on the base and three times now is a new issue, even though the edit added
  only one use. One already over the threshold on the base is an existing
  issue, and further uses do not create a new one.

## The rules

| Rule | First raised | What triggered it here | The fix that passed | Check | Limits (FACT, INFERENCE, UNKNOWN) |
|---|---|---|---|---|---|
| `python:S1192` | 0.6.0 (11) | Template paths, `"/login"`, `"Hop Type"`, `"Close-Proximity Operation"` used three or more times in a file | One module constant per literal | Literals of 5 or more characters at 3 or more uses with one on a changed line, new when the base had fewer than 3; f-string fragments warn | INFERENCE: identifier-like literals (`\w+` only) are not counted. Every literal the gate flagged held a space, slash, hyphen or dot, and `"fields_side"`, new at 3 uses in 0.6.4, passed. INFERENCE: under 5 characters is not counted. UNKNOWN: whether f-string fragments count, so they warn rather than block. |
| `python:S1244` | 0.6.0 (5 bugs) | `ecc == 0.0` and similar exact zero tests | Named tolerances (`_CIRCULAR_ECC` and others) | `==` or `!=` with a float literal on either side | FACT: these were bugs, not smells; one named the wrong node on rounding noise. |
| `python:S3358` | 0.6.0 | A conditional expression nested in another | Statements | Any `x if c else (y if d else z)` shape | |
| `python:S107` | 0.6.0 (2) | `apply_intercept` and `decision_evaluate` with dozens of `Form()` parameters | Pydantic form models | More than 13 parameters, `self` and `cls` aside, when the signature changed | INFERENCE: 13 is the sonar-python default. |
| `python:S8410` | 0.6.0 (3) | `user: User = Depends(require_login)` in route signatures | `Annotated[User, Depends(require_login)]` | A route parameter whose default is `Depends`, `Form`, `Query`, `Body`, `Header`, `Cookie`, `File`, `Path` or `Security`, and a `Depends` or `Security` default in any function (dependencies included), on a changed line | FACT: all 94 converted in 0.6.6, with the OpenAPI schema and every route's dependency tree compared before and after and found identical. Where a parameter without a default would follow one with, the rest became keyword-only, which FastAPI binds the same way. |
| `python:S5713` | 0.6.0 | `except (SignatureExpired, BadSignature)` | Drop the subclass | An except tuple naming a class and its subclass, resolved through builtins and third-party imports | Classes defined in SPECTRE are not resolved, because resolving them would import application code. |
| `python:S7504` | 0.6.0 | `for task in list(tasks)` | Iterate directly (`cancel()` only schedules the set edit) | `list(x)` as the iterable of a `for` or comprehension | If the loop mutates what it walks, copy with `.copy()` or `[*x]` rather than dropping the copy. UNKNOWN: whether `tuple()` is flagged the same way. |
| `python:S6353` | 0.6.0 | `[a-zA-Z0-9_]` in the DDL identifier allow-list | `\w` with `re.ASCII`, so the allow-list is no wider | The common spelled-out classes in a literal passed to `re.*` | Without `re.ASCII`, `\w` accepts non-ASCII letters: always add the flag. |
| `python:S7632` | 0.6.0 | `# noqa: BLE001 - any unreadable body has no token` | The rationale on the line above, `# noqa: BLE001` alone | Any text after a noqa comment's codes, on a changed line | FACT: 9 such comments remain and fire when touched. |
| `javascript:S7773` | 0.6.1 (2) | `parseFloat` and `isNaN` in the intercept sort, added by the 0.6.1 fix itself | `Number.parseFloat`, `Number.isNaN` | Bare `parseFloat`, `parseInt`, `isNaN`, `isFinite` in templates and `.js` | FACT: 68 remain in templates. |
| `javascript:S7761` | 0.6.0 | `item.setAttribute('data-idx', ...)` | `item.dataset.idx = ...` | `get/set/remove/hasAttribute` with a whole literal `data-*` name | FACT: `getAttribute('data-sort-' + col)` passed; a built name is not flagged. |
| `Web:InputWithoutLabelCheck` | 0.6.3 (9) | Fields whose `title` was rewritten, which had a placeholder and no label | An `id` and a `<label for>`, visually hidden where the layout shows the purpose | An `input`, `select` or `textarea` (not hidden, submit, button, reset or image) with neither a wrapping `<label>` nor a `<label for>` matching its `id` | FACT: a wrapping label passes (the Max ΔV inputs, touched in 0.6.3, were not flagged). FACT: markup inside a `<script>` string is not parsed (decision_panel's row builders passed). |
| `Web:S6819` | 0.6.0, 0.6.3 | `role="button"` and `role="heading"` on spans, `role="status"` on a static banner | A native element (`<button>`, `<h3>`), or `role="note"` for the banner | A role with a native element equivalent, `role="img"` on `<svg>` and `<img>` aside | `role="note"` has passed every scan. |
| `Web:JinjaCommentInTag` | 0.6.0 (3) | `{# #}` comments inside `<tr>` tags mentioning `role="button"`, `aria-controls`, `aria-label` | Comment moved above the tag | A `{# #}` inside a tag: blocking when it holds `=`, `role` or `aria-`, a warning otherwise | FACT: Sonar's HTML parser read the comment's words as attributes and raised S6819 and S6793 on them. A comment without such words inside a `<button>` passed 0.6.3. |

Rules raised once and fixed by restructuring rather than by a pattern, so not
encoded: `javascript:S3776` (cognitive complexity in `aiSort`, 0.6.0; the
Python scorer does not read JavaScript) and `Web:S6793` (an artefact of the
Jinja comments above). A JavaScript function grown past 15 is the one known
way to fail the gate that no script here catches; the review agent checks it.

## The calibration

The checker was run on each release against the one before it, and compared
with what the gate reported (28 October 2026):

| Release | Gate reported | Checker reported |
|---|---|---|
| 0.6.1 against 0.6.0 | 2 (S7773) | the same 2, same lines |
| 0.6.2 against 0.6.1 | passed | 0 |
| 0.6.3 against 0.6.2 | 10 (9 labels, 1 S6819) | the same 10, same lines |
| 0.6.4 against 0.6.3 | passed | 0 |
| 0.6.5 before its literal fix | not submitted | 1 (the timestamp format, found by hand that day) |
| 0.6.5 as shipped | passed | 0 |

0.6.0 cannot be replayed: its 36 issues were scored against a baseline this
repository does not record.

## Watch list: rules suspected, never raised

| Rule | Why it is suspected | Where it would fire | Status |
|---|---|---|---|
| `javascript:S7765` (`includes` over `indexOf(...) !== -1`) | The 0.6.6 review ran ESLint's `unicorn/prefer-includes`, which SonarJS ports, on every touched line; the same replay reproduces the gate's 0.6.1 verdict exactly. No passing release has touched an `indexOf` existence test, so whether the gate runs it is UNKNOWN. | Fixed where 0.6.6 touched it (`base.html` 13). Untouched: `operator.html` (3) and `threat_sweep.html` (1). | If the gate raises it, encode it by the four steps below and clear the rest. |
| `python:S1940` (inverted boolean check) | The 0.6.7 review: `if not x <= limit` is the shape it targets, and the gate has never scored one. | None left: 0.6.7 wrote the NaN-safe test as `math.isnan(x) or x > limit`. | Encode it if raised. |
| `Web:S6847`, `Web:S6845` (handlers and `tabindex` on non-interactive elements) | The sortable `<th onclick tabindex onkeydown>` headers have not been in the window since 0.6.0, whose baseline is not recorded. | Every sortable header in the sweep, HRR and all-intercepts tables. | Before editing one, move the handler onto a `<button>` inside the `<th>`. |
| `python:S5843` (regular expression too complicated, limit 20) | The 0.7.0 review scored the new launch-phase pattern at 23 with SonarJS's `regex-complexity`, the same algorithm. No scored release has had one over 20 in its window, so whether the gate's profile runs it is UNKNOWN. | Fixed before it shipped: split into three patterns (7, 5, 2). Untouched: `spectre/astro/notso.py:325` scores 21. | Split a pattern before editing its line. Encode by the four steps below if raised. |
| `javascript:S3776` headroom | `childSort` in `threat_sweep.html` scores exactly 15 (eslint-plugin-sonarjs 4.2.2); the rule fires above 15. | Any added branch in `childSort`. | Split it before adding to it. |

## Latent issues

`python3 scripts/sonar_rules.py --all` checks every line, not just changed
ones. On 28 October 2026 it found 209 issues that counted nowhere yet and
would each fail the gate the day its line was edited. 56 of them were in the
vendored, minified libraries (`chart.umd.min.js`, `chartjs-plugin-zoom.min.js`,
`htmx.min.js`), which are now out of the checker's scope: they are never
edited here, their versions are pinned in `spectre/web/static/vendored.json`,
SonarJS skips minified files (INFERENCE), and they enter the new-code window
only when replaced whole by an upgrade. 0.6.6 cleared the other 153: S8410
88, InputWithoutLabelCheck 17, S1192 14, S7773 13, S7632 9, S7761 9, S1244 2
and S3358 1, plus 6 S8410 in dependency functions that the widened check now
covers and one Jinja comment in a tag. `tests/unit/test_sonar_rules.py` now fails on any blocking finding
anywhere in `spectre/` and `tle_clustering/`, so none can accumulate again.

What remains are 11 advisories: f-string fragments used three or more times
in a file. Whether the gate counts f-string fragments is UNKNOWN (no release
has added a third use of one), so they warn rather than block. If the gate
ever raises one, that settles it: make them block and clear them.

## When the gate raises something new

1. Add a row to the table above: the rule, the release, the line the gate
   named, and what passed.
2. Add a check to `scripts/sonar_rules.py` and its id to `RULES`.
3. Add a test to `tests/unit/test_sonar_rules.py` that reproduces the gate's
   line as a failure and the fix that passed as a pass.
4. Replay the failed release with the checker and confirm it reports the
   gate's lines and no others, then fix the code.
