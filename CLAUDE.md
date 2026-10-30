# SPECTRE: working notes for Claude Code

SPECTRE ships through the Bluestaq App Store, whose Code Quality gate
(SonarQube) scores new and changed code. Four submissions have failed it on
rules a script can see. Write code that passes the first time.

## While writing code

These rules are each one the gate has raised here; the detail and the
evidence are in `docs/SONAR-RULES.md`.

● A literal of 5 or more characters containing a space, slash, hyphen or dot
  goes in a module constant before its third use in a file.
● No float compared with `==` or `!=`: use a named tolerance.
● No nested conditional expressions; no `list(x)` around something being
  iterated; no spelled-out `[0-9]` or `[a-zA-Z0-9_]` in a regex (`\d`, or `\w`
  with `re.ASCII`); no except tuple naming a class and its subclass.
● Route parameters use `Annotated[T, Depends(...)]` (and `Form`, `Query` and
  the rest), never `= Depends(...)`. More than 13 parameters means a model.
● A `# noqa` carries codes only; its rationale goes on the line above.
● JavaScript uses `Number.parseFloat`, `Number.parseInt`, `Number.isNaN`,
  `Number.isFinite`, and `element.dataset` for `data-*` attributes. Keep each
  function at cognitive complexity 15 or under.
● Every form field has a `<label for>` matching its `id`, or sits inside a
  `<label>`. The red and blue forms share partials, so ids carry the side.
● No ARIA role with a native element (`button`, `heading`, `status` and the
  rest): use the element. `role="note"` is fine.
● No `{# #}` Jinja comment inside a tag: put it above.
● **Editing any line brings what is already on it into scope**, coverage
  included: a reworded line in an untested error branch needs a test.
  `python3 scripts/sonar_rules.py --all` must stay at 0 blocking; a test
  holds it there.

## While writing tests

● No test asserts on an orbital outcome (a solution, a ranking, a miss)
  computed from `datetime.now()`. Geometry changes with the hour: 0.6.8 failed
  the App Store's Test stage at 12:07 UTC on a test that only passed from
  20:00 to 04:00. Fix the epoch, or make the outcome hold at every hour (a
  budget nothing fits, a target nothing reaches). Ages relative to now are
  fine.

## Before an App Store package

Run `/release-preflight`. At minimum:

```
python3 scripts/sonar_rules.py <last release the gate scored>
sh scripts/check-quality.sh <last release the gate scored>
```

Master is the right base only when the last release is merged to it.

`scripts/verify-container.sh` fails on a High or Critical finding with a fix
(Grype), which is what the Container Scan stops on; a SKIPPED scan is not a
pass. Usually the fix is a base digest bump.

`scripts/package-appstore.sh` refuses to build on a `sonar_rules.py` failure.
Never submit to the App Store; that is the owner's step.

## When the gate raises something new

Follow the four steps at the end of `docs/SONAR-RULES.md`: row, check, test,
replay, and only then the fix.
