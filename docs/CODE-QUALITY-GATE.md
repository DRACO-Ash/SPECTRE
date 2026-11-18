# Code Quality: the SonarQube gate

**Zero open SonarQube issues and zero unreviewed security hotspots, across the
whole codebase, measured by SonarQube itself at check time.** That is the
owner's instruction of 18 November 2026, and it is the whole policy.

It supersedes the owner's ruling of 12 November 2026 (latent issues converted
as their lines are touched, new code only). Under that ruling 0.48.5 reached
the App Store with 174 findings on the platform's SonarQube, 165 code smells
and 9 bugs, while our own checks passed it: `scripts/sonar_rules.py` checked 14
rules on changed lines, and the platform's analyser checks hundreds on every
line. Approximating the analyser is over. The gate runs it.

## What the gate is

`scripts/sonar-gate.sh`, with its HTTP half in `scripts/sonar_gate.py`. Given a
directory (by default the App Store package tree, staged by
`scripts/package-appstore.sh --stage-only`), it:

1. **Finds or starts a server.** It reuses a SonarQube that answers at
   `SONAR_HOST_URL` (default `http://127.0.0.1:9000`). If none answers and the
   host is local, it starts SonarQube Community Build 26.11 in docker, pinned
   by digest, with its data on tmpfs (Elasticsearch refuses a disk under 10%
   free) and the Elasticsearch bootstrap checks off, and waits for status UP.
2. **Secures it.** On a server it started, it replaces `admin`/`admin` with a
   random password and mints a token. On a server it reuses, it reads the
   credentials given and mints a temporary token, revoked on exit. Either way
   the secrets live only in a 0600 file in a private temporary folder, deleted
   on exit, and are never printed. No secret is in the repository.
3. **Builds the profile** from `scripts/sonar-profile.json` (below) and sets it
   as the default on a server it started. On a reused server it binds the
   project to the profile and leaves the server's defaults alone.
4. **Recreates the project** (`spectre-gate` unless `SONAR_PROJECT_KEY` says
   otherwise). A resolution made by hand in the UI on an earlier analysis
   (won't fix, false positive, safe) therefore cannot carry over and pass the
   gate. The code is the only place a finding can be settled.
5. **Scans the whole tree** with the SonarScanner CLI, pinned by digest. The
   platform analyses every file in the archive and does not honour
   `sonar.sources`, so the gate does the same: sources are the whole tree, and
   `tests/` is analysed as test code. These settings override any
   `sonar-project.properties` in the tree, so a package cannot narrow its own
   analysis. It then waits for the server to finish processing.
6. **Reads the verdict:** every open issue and every security hotspot not yet
   reviewed. Each is printed as `file:line rule message`, with a count by rule,
   and written to a JSON report (`dist/sonar-gate-report.json` by default;
   `SONAR_REPORT` moves it). The report also lists every `NOSONAR` marker in
   the tree, so a suppression is never invisible. **One finding fails the gate.**
7. **Cleans up:** removes the container it started and its volumes, unless
   `SONAR_KEEP=1`.

Exit status: 0 pass; 1 issues or hotspots found; 2 the gate could not reach a
verdict (a server that will not start, a scan that fails); 3 docker is not
available. Only 0 is a pass. There is no fallback that counts as one.

## Where it runs

● **The packager.** `scripts/package-appstore.sh` runs the gate on the staged
  tree, which is exactly what the zip will hold, after the fast pre-check and
  before the zip is written. A failure stops the build. So does a missing
  docker, with a message saying so. `SKIP_SONAR_GATE=1` is the only override:
  it prints a loud warning and writes `SONAR GATE SKIPPED` into the package's
  `.sha256` record, so a skipped package is visibly unverified and must not be
  submitted. A gated build leaves its report beside the zip as
  `<package>.sonar-gate.json`.
● **`scripts/check-quality.sh`**, as the leg before the changed-code legs. It
  does not depend on a diff, so it runs even when no Python changed.
● **CI.** The `sonarqube` job in `.github/workflows/ci.yml` runs on every push
  and every pull request (the gate is the whole codebase, so master is
  measured too). It runs the gate's own tests, the live SonarQube test
  included, then `sh scripts/sonar-gate.sh` on the package tree, and keeps the
  report as an artefact. GitHub-hosted Ubuntu runners have docker.

## Run it locally

You need docker, `python3` and about 4 GB of free memory. The first run pulls
the two pinned images (about 3.5 GB on disk).

```
sh scripts/sonar-gate.sh                       stage the package tree and gate it
sh scripts/sonar-gate.sh <directory>           gate any tree, an unzipped package for example
SONAR_HOST_URL=http://127.0.0.1:9100 \
  sh scripts/sonar-gate.sh                     start the throwaway server on another port
SONAR_KEEP=1 sh scripts/sonar-gate.sh          keep the server to browse the findings; the
                                               credentials file's path is printed (never its
                                               contents); delete it when done
SONAR_HOST_URL=http://127.0.0.1:9000 \
  SONAR_AUTH_FILE=<file> sh scripts/sonar-gate.sh
                                               reuse a running server; the file holds
                                               user:password, a token, or what a kept run left
```

If something already answers at `SONAR_HOST_URL` and no credentials are given,
the gate stops and says so rather than guessing: give `SONAR_AUTH_FILE` or
`SONAR_TOKEN`, or point `SONAR_HOST_URL` at a free port. A full run on the
package takes about five minutes, most of it the server starting.

## The profile

`scripts/sonar-profile.json` defines one profile, **SPECTRE gate**, for the four
languages SPECTRE is written in. For each, the base is the built-in **Sonar way
extended** profile, and an explicit list of rule keys is activated on top: every
rule the platform's SonarQube has raised on SPECTRE (its own list, and every
rule in the full 0.48.5 issue export).

| Language | Base | Named rules | Active on 26.11 |
|---|---|---|---|
| Python (`py`) | Sonar way extended | 17 | 272 |
| JavaScript (`js`) | Sonar way extended | 11 | 260 |
| CSS (`css`) | Sonar way extended | 1 | 30 |
| HTML and templates (`web`) | Sonar way extended | 9 | 52 |

Why Sonar way extended: Community Build 26.11 ships "Sonar way core", "Sonar
way extended" and "Sonar way comprehensive" for these languages, and no
profile called plain "Sonar way". Extended is the closest to what the platform
raises: of the 38 named rules, 23 are already in it and the other 15 are the
additions. Comprehensive would add over a hundred rules each for Python and
JavaScript that the platform has never raised on SPECTRE.

Every other language the scanner finds in the package (Dockerfile, YAML, JSON,
secrets detection and the rest) is analysed with the server's built-in default
profile, and any issue there fails the gate too.

One rule the platform raised cannot run here: `pythonbugs:S6466` (an index
that may raise `IndexError`, raised at `spectre/web/routes/missions.py:924` on
0.48.5) ships only in the commercial editions. It is listed under
`not_in_community_build` with that reason, and the gate prints it as NOT RUN on
every run so the gap stays visible. It is held by hand review and by the tests
on that route.

The profile cannot lose a rule silently: `tests/unit/test_sonar_gate.py` holds
it to every rule the platform has raised, and the gate refuses to run if the
server does not know a named rule (unless it is listed, with a reason, as not
in the Community Build) or if any named or base rule fails to activate. To add
a rule, follow the steps at the end of `docs/SONAR-RULES.md`.

## Suppressions

Fix for real. `# NOSONAR` (or the JavaScript and HTML equivalent) is allowed
only where the rule is wrong for this code or the fix would break the product,
with the reason on the line above, and each one goes to the owner (the
Information Security Manager) for review. A VULNERABILITY or a BUG is never
suppressed silently. The gate's report lists every `NOSONAR` marker in the
tree. Marking an issue resolved in the SonarQube UI does nothing, because the
gate recreates the project on every run.

## What the gate does not measure

● `pythonbugs:S6466`, above.
● **Coverage and duplication.** The platform's gate also asks for 80% coverage
  and at most 3% duplication on new code. The SonarQube gate reads issues and
  hotspots only; `scripts/check-quality.sh` keeps its changed-code coverage
  and duplication legs for those conditions.
● **Rules the platform's profile holds and has never raised here.** The
  platform's profile is not published. When it raises a rule this profile
  lacks, the rule joins the profile the same day.

## The fast pre-check

`scripts/sonar_rules.py` still runs first in the packager and in
`scripts/check-quality.sh`. It encodes 14 rules the platform has failed a
submission on and answers in seconds. It is a convenience, not the verdict:
`docs/SONAR-RULES.md` is its ledger.

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

`--changed` is the leg wired into `scripts/check-quality.sh`, a fast warning
on the functions a branch touched. The whole-tree run (no flag) is the one
that matches the zero policy: the gate fails on any function over 15, touched
or not. It is scoped to `sonar.sources`, so a complex function in `scripts/`
is not counted.

## How each rule class is fixed

What follows is how to fix each rule class once the gate's report names it.
Fourteen of these rules are also checks in the fast pre-check, whose ledger is
`docs/SONAR-RULES.md`.

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
  keydown listener in `spectre/web/static/js/core.js`; elements opt in with
  `tabindex="0" data-activate` beside the `data-action` that names their click
  (SPC-199: the policy allows no inline handler). A console that answers only
  to a mouse is unusable from a keyboard, which in an operations room is a real
  barrier and not a formality.
● **css:S7924** contrast. The caution amber `#EF9F27` is 9.00:1 on the dark
  theme and 1.98:1 on the light one, which fails WCAG AA outright. A theme-aware
  `--spectre-color-caution-amber-text` token resolves to `#8A5600` on light
  surfaces (5.59:1 on `#F3F4F6`, 6.16:1 on `#FFFFFF`).


## What the new-code years taught (history)

From 0.5.23 to 0.48.5 the platform scored new code only, and these pages
explained how to live inside that window: fix what the report names, and
budget a second pass because every touched line enters the window. Clearing
sixteen reported functions in 0.5.24 pulled three more into it
(`udl.py:fetch_tle` at 67 among them), and lifting helpers moved old findings
onto added lines. The lesson that survives the change of policy is the one
about evidence: a local check that reports clean while the artefact is not is
the most expensive thing a gate can do. That is why the verdict now comes from
SonarQube itself, run on the staged package, and why no docker means no
package rather than a pass.

There is no longer a population of known issues left alone on purpose. The
remaining `Depends(...)` defaults, the complex functions nobody had touched and
the two lines that needed both a ruff and a bandit directive are issues like
any other, and the gate counts them.

## Before you upload

```
sh scripts/package-appstore.sh                 builds only if the SonarQube gate passes
sh scripts/sonar-gate.sh                       the gate on its own, on the package tree
sh scripts/check-quality.sh                    the gate, then the changed-code legs
python3 scripts/sonar_rules.py                 the fast pre-check
python3 scripts/cognitive_complexity.py --calibrate   the meter still agrees with Sonar
python3 scripts/preflight-gate.py .            the package contract
```

The packager's `.sha256` record must hold one line, the checksum. A record that
says `SONAR GATE SKIPPED` belongs to a package that was never checked: do not
submit it.
