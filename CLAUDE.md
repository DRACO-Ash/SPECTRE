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
● **Editing any line brings what is already on it into scope.** Before
  touching a template element or a function signature, fix what is wrong on
  it. `python3 scripts/sonar_rules.py --all <file>` shows what is latent.

## Before an App Store package

Run `/release-preflight`. At minimum:

```
python3 scripts/sonar_rules.py master
sh scripts/check-quality.sh master
```

`scripts/package-appstore.sh` refuses to build on a `sonar_rules.py` failure.
Never submit to the App Store; that is the owner's step.

## When the gate raises something new

Follow the four steps at the end of `docs/SONAR-RULES.md`: row, check, test,
replay, and only then the fix.
