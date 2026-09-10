# Change ledger

Every version that goes to the App Store gets an entry here BEFORE it is built.
`scripts/package-appstore.sh` refuses to build a version that has no entry.

The point is to stop shipping changes that teach nothing when they fail. Each
entry must answer three questions, and the classification is the honest part:

● **EVIDENCED** - something in a job log, a source file, or a reproduced run
  names this as the cause. Name it. A failure after an EVIDENCED fix means the
  evidence was misread, which is itself informative.
● **PROBE** - a reasoned guess. Allowed, but only ONE per submission, and only
  when the row below says what a failure would rule out. A submission carrying
  two probes cannot tell you which one mattered.
● **HYGIENE** - unrelated to any gate. Must not change what the gate sees.

If a gate has no evidence and no useful probe, the correct entry is "no change,
no hypothesis". Say that instead of inventing one.

---

## 0.5.2

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **EVIDENCED** | Stop shipping `scripts/` and `.github/` | The job log names `scripts/preflight-gate.py:213` (hotspot), `:34`, `:50`, `:234` and `scripts/package-appstore.sh:246`. All five findings are in files that are build tooling, not application code. `sonar-project.properties` declares `sonar.sources=spectre,tle_clustering`, so the platform is analysing the whole archive and ignoring our declaration. | Then the platform analyses files we do not ship, or `sonar-project.properties` is being honoured after all and the findings came from somewhere else. Either is a real, narrow answer. |
| Dependency Scanning | **NO HYPOTHESIS** | None | Seven failures. The contract from the gate skill is satisfied and its preflight reports 0 blocking. Every content hypothesis I have held has been wrong: header form, pyproject presence, `requirements.lock`, manifest count, lock generator. | n/a. I am not shipping a change for this gate without evidence. The analyser image is not public and its error text has never been read. |

### 0.5.2 outcome

● **Dependency Scanning: failed, as recorded.** Commit `a8accac1`, MR 20. Same
  signature: two INFO lines, `exit status 1` after seven seconds, no SBOM, no
  report, no error text. No new information. The ledger predicted this before
  the build, because no change shipped for this gate. Eight failures now, across
  eight distinct package shapes.
● **Code Quality: outcome not yet seen.** This is the one thing that would tell
  us whether the evidenced fix in 0.5.2 landed. Needed before the next entry.

## 0.5.3

| Gate / defect | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime: login crash | **EVIDENCED** | `pool_pre_ping`, `pool_recycle` and bounded sizing on the async engine | The pod traceback names it: `asyncpg...InterfaceError: connection is closed` on `SELECT users... WHERE users.username = $1`. Reproduced against a real PostgreSQL 16 by terminating the backend server-side, then fixed and re-verified using the app's own engine and the real login query. | Then the connection is being closed mid-statement rather than while idle in the pool, which pre-ping cannot see. The next step would be a retry at the session boundary, not more pool tuning. |
| Code Quality | **CONFIRMED FIXED** | None needed | 0.5.2 passed. The evidenced fix in that version (not shipping `scripts/`) landed. | n/a |
| Dependency Scanning | **NO HYPOTHESIS** | None | Nine failures. 8 of 9 stages now pass. Still no SBOM, no report, no error text. | n/a. Unchanged position: nothing ships for this gate without the analyser's error text, the `.pre` resolution job's log, or a diff against a passing package. |

### 0.5.3 outcome

● **Dependency Scanning: failed, as recorded.** Commit `35ede5b5`, MR 21. Tenth
  identical failure. No change shipped for this gate, so no information gained,
  which is the expected and correct outcome of holding the line.
● **The runtime login fix cannot be observed from this log.** It needs a
  successful deploy, which this gate is blocking.

## 0.5.4

The standing note below was satisfied: a file listing arrived from PSIRENS, an
application that clears this gate. This is the first entry in ten submissions
with evidence for the Dependency Scanning gate.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Dependency Scanning | **EVIDENCED** | Stop shipping `requirements.in` and `requirements-runtime.in` | A root diff against PSIRENS. `requirements.in` is a recognised Python manifest, so our root offered the analyser **three** (`pyproject.toml`, `requirements.in`, `requirements.txt`) where PSIRENS offers **two**, leaving one lockfile paired with two candidate requirements sources. Our root is now identical to theirs, file for file. | Then manifest count at the root is not the discriminator, and the remaining differences are the `src/` layout and our second top-level package, `tle_clustering`. That would be the next diff to run, and it is a much larger change. |
| Code Quality | **HYGIENE** | Stop shipping seven internal documents and local configs; move pytest and coverage config into `pyproject.toml` | PSIRENS ships seven root files; we shipped eighteen. Every file in the archive is analysed as application code, which already cost us five findings in 0.5.1. | Cannot fail the gate on its own: none of the removed files is a recognised manifest. |

**Only one EVIDENCED change is being tested here.** The hygiene removals cannot
affect the analyser, because none of those filenames is one it reads. So a
failure still isolates cleanly to the manifest hypothesis.

## 0.5.5

0.5.4 failed with the root identical to PSIRENS, which rules out manifest count
at the root. The ledger's recorded next step was the layout difference, and
examining it produced a reproduced, named error.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Dependency Scanning | **EVIDENCED** | Declare `[build-system]` and `[tool.setuptools.packages.find]` in `pyproject.toml` | Our package could not be built by any standard tool. `pip install --dry-run --no-deps .` against the package root fails in seconds with `error: Multiple top-level packages discovered in a flat-layout: ['spectre', 'tle_clustering']`. With no `[build-system]`, PEP 517 defaults to setuptools, and its auto-discovery refuses an ambiguous flat layout. Any resolver that reads pyproject.toml calls that hook. Now builds cleanly, and `pip-compile pyproject.toml` resolves with zero errors. | Then the analyser does not call the build hook, and the fault is in how it parses the two manifests rather than in resolving them. The next evidence needed would be PSIRENS's `pyproject.toml` contents, 424 bytes and non-sensitive, to compare structure directly. |

**Honest limit on the classification.** The error is reproduced and the fix is
verified in both directions. What is *inferred* is that the analyser calls the
PEP 517 build hook. It fits the signature exactly - a hard failure in seconds
with the message on stderr - and it is consistent with PSIRENS passing, since a
single package under `src/` auto-discovers unambiguously. But it is not proven
against the platform's binary.

This is worth shipping regardless of the gate: a package that no standard
Python tool can build is a real defect.

**Standing note on Dependency Scanning.** Do not add a change for this gate to a
future entry unless one of these arrives: the analyser's real error text, the
`.pre` resolution job's log, or a file-level diff against a package that passes.
Anything else is a guess dressed as work.

## 0.5.6

0.5.5 declared `[build-system]` and fixed a package that no standard Python
tool could build. The gate still failed, with the same signature it has shown
twelve times: two INFO lines, `exit status 1` in under ten seconds, no SBOM,
no report, no error text. That outcome discharges the 0.5.5 hypothesis exactly
as the ledger predicted it would: the analyser does not call the PEP 517 build
hook, and the fault is not in resolving our manifests.

None of the three pieces of evidence the standing note asks for has arrived.
The user has instead made a scoping decision: submit the docker-only template
and stop paying for a gate we cannot see inside. That decision is recorded
here as the reason for the change, and the classification below is honest
about what it is.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Dependency Scanning | **PROBE** | Submit the docker-only package. No recognised Python manifest ships at any depth: no `pyproject.toml`, no `requirements.txt`, no `setup.py`, no lockfile the analyser reads. `requirements-runtime.txt` stays for the image build, under `--require-hashes`, and is not a name the analyser selects. | Partial and second-hand. The locally built upstream analyser exits 0 against this archive with "No compatible file found", and the same binary was shown miscalibrated on two of three control samples, so it is not proof. What is solid is the platform's own behaviour: the Dependencies stage runs only for the python template, and a docker-only app has no such stage. This is a guess about the platform's template detection, not about our code. | Then the analyser is selected by something other than a manifest at any depth - an archive-level or account-level template setting the package cannot influence - and no change to the contents of a zip will clear this gate. The next step would stop being a code change and become the escalation already drafted at `docs/ESCALATION-DEPENDENCY-SCANNING.md`. |

**One probe, and it is the only change.** Nothing else in this release alters
application behaviour. The docker-only artefact carries the same `spectre/`
tree, the same hash-locked runtime lock and the same 0.5.3 connection-pool fix
as 0.5.5.

**The cost, stated plainly.** docker-only ships no `tests/`, no
`sonar-project.properties` and no `requirements.txt`. The Test and Code
Quality stages will have nothing to run against. Those two stages passed on
0.5.4 and 0.5.5, so this trades two known passes for one unknown. That trade
is the user's call and it has been made.

**Standing note, still in force.** Do not add a further Dependency Scanning
change to a future entry unless the analyser's real error text, the `.pre`
resolution job's log, or a file-level diff against a passing package arrives.

### Outcome: PASSED

Recorded 28 August 2026. Version 0.5.6 cleared every stage and deployed. The
app is Active.

The probe is discharged, and the shape of the result matters more than the
pass. The pipeline ran **six stages, not nine**: Secret Detection, SAST Scan,
Dockerfile Lint, Container Build, Container Scan, Deploy. Dependencies,
Dependency Scanning, Test and Code Quality did not run at all.

So the mechanism is now established rather than guessed. Template selection
follows manifest detection inside the archive. Removing every recognised
manifest did not satisfy the Dependency Scanning stage; it removed the entire
python-template branch of the pipeline. That also closes the alternative the
entry raised: selection is not archive-level or account-level configuration
beyond our reach, because the contents of the zip changed which stages exist.

**What this does not establish.** Nothing about why the analyser crashed. That
question is untouched and the evidence still points at a platform defect: a
non-zero exit with no `gl-sbom-*.cdx.json` and no
`gl-dependency-scanning-report.json`, now confirmed from the platform side.
The escalation at `docs/ESCALATION-DEPENDENCY-SCANNING.md` remains worth
sending on its own merits.

**What we are running without, stated plainly.** Four gates no longer exercise
this submission:

● **Test.** The suite does not ship, so the platform never runs it. It still
  runs in this repository and in `scripts/check-quality.sh`, and the packager
  still runs it in-package when building the python template.
● **Code Quality.** No `sonar-project.properties` ships. Local reproduction of
  all six quality-gate conditions stays in `scripts/check-quality.sh`.
● **Dependencies and Dependency Scanning.** No manifest ships, so the platform
  performs no dependency analysis of any kind. Our own coverage is
  `scripts/audit-dependencies.sh`: `pip-audit` across all three hash-locked
  files, a CycloneDX SBOM, and the offline `gemnasium-db` match.

That is four platform gates traded for four local ones. The local checks are
real and they run, but they are ours, not the platform's, and nobody outside
this repository sees their output. Any future submission that restores the
python template restores all four.

**Standing note, revised.** The python template remains buildable from this
repository with `scripts/package-appstore.sh`. Rebuild and resubmit under it
if any of these arrive: the analyser's real error text, the `.pre` resolution
job's log, PSIRENS's `pyproject.toml`, or word that the analyser defect is
fixed. Until then, do not spend another submission guessing at it.

## 0.5.7

Phase 1 of restoring what docker-only gave up. The 0.5.6 result drew a hard
line through the remaining work: template selection follows manifest detection,
so files that are not recognised manifests can be restored at no risk, and the
manifests themselves cannot be restored at all without re-enabling the broken
stage. This entry does everything on the safe side of that line.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Ship `tle_clustering/` and `COPY` it in both Dockerfiles | `spectre/astro/tle_preprocessing.py:150` imports it inside `try/except ImportError`, logs a warning and returns an empty result. Neither `Dockerfile` nor `Dockerfile.docker-only` ever carried a `COPY` for it, and the docker-only packager dropped the directory outright. So the deployed image has performed no TLE clustering in any build to date, and nothing failed, because the guard is doing its job. Pinned by three tests, including one that performs the app's own import rather than checking for files. | Not a gate hypothesis. This is a defect fix and its correctness does not depend on the pipeline's verdict. |
| Test, Code Quality | **PROBE** | Ship `tests/`, `sonar-project.properties`, a generated `pytest.ini` and `.coveragerc`, and a `coverage.xml` produced by running the suite against the staged tree | None of those five filenames is one the analyser selects on, so the template cannot flip. 0.5.6 ran six stages with none of them present, which is consistent with the stages being template-gated but does not establish it: we shipped no suite and no Sonar config, so the observation cannot separate "the stage does not exist" from "the stage had no input". | Two readings, both useful. If Test and Code Quality stay absent, they are template-gated, the question closes permanently, and the only cost is archive size. If they appear and pass, two platform gates come back for nothing. If they appear and fail, we learn what they need, which is more than we know now. |

**One probe, and the evidenced change is independent of it.** The clustering
fix ships regardless of what the pipeline decides, and its verification is
local: the import resolves and the Dockerfiles copy the package.

**Why `coverage.xml` ships, and why that is not gaming the metric.**
`sonar-project.properties` points at `coverage.xml`, which the platform's Test
stage generates on the python template. A docker-only archive has no Test
stage, so a Code Quality stage that did run would read a missing file and score
zero, failing the gate on an absence rather than on the code. The report shipped
here is generated inside this build by running the suite against the exact tree
being zipped. It is not the working copy's file, and the packager fails the
build if the suite does not pass or the report is not produced.

**Configuration is derived, not duplicated.** `pytest.ini` and `.coveragerc`
are written from `pyproject.toml` at package time. Copying the values by hand
would let the shipped configuration drift from the one the repository tests
under, which is how the suite silently stops testing what it claims to.

**Contract tests now know which template they are in.** The suite travels
inside both archives. Assertions about `requirements.txt` and `pyproject.toml`
skip under docker-only, detected from both manifests being absent rather than
one, so a python package that lost a manifest to a packaging bug still fails
rather than skipping. `TestDockerOnlyContract` asserts the inverse property
there, so the skip is not a hole.

**Standing note, unchanged.** Phase 2, restoring the manifests, is atomic: any
one of them flips the template and brings Dependency Scanning back with it.
Do not attempt it until the analyser's real error text, the `.pre` resolution
job's log, PSIRENS's `pyproject.toml`, or a fix arrives.

### Outcome: FAILED at Container Build, and the probe answered

Recorded 28 August 2026, merge request 25, commit 0108dc3.

**The probe is discharged, and the answer is clean.** Test and Code Quality are
template-gated. Neither ran, despite the archive carrying `tests/`,
`sonar-project.properties`, `pytest.ini`, `.coveragerc` and a real
`coverage.xml`. Dockerfile Lint passed in the same pipeline, and on the python
template both stages run before it, so they were not merely pending. Code
Quality is the decisive case: it needs no dependency install and it had every
input it reads, and it still did not run.

So the four gates docker-only gives up cannot be bought back by shipping their
inputs. Only restoring a manifest brings them back, and that brings Dependency
Scanning with it. The trade is fixed, and the question is closed.

**The evidenced change failed the build, and the fault is mine.** Container
Build stopped at the `COPY` I added:

```
Error: building at STEP "COPY tle_clustering/ /app/tle_clustering/":
no items matching glob ".../spectre/tle_clustering" copied
(1 filtered out using .../.dockerignore): no such file or directory
```

`.dockerignore` line 13 excluded `tle_clustering/`, listed under "Tests, docs
and development tooling never ship in the runtime image". I added the `COPY`
without reading the file that governs the build context.

That exclusion is also the true root cause of the original defect, one layer
below where I placed it. The package was not missing a `COPY`; it was being
stripped from the build context, and the missing `COPY` merely made the
stripping invisible. Classifying it as tooling was wrong: the application
imports it.

Container Scan skipped and Deploy never ran, so 0.5.6 remains the deployed
version and the live app is unaffected.

## 0.5.8

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Container Build | **EVIDENCED** | Remove `tle_clustering/` from `.dockerignore` | The build log names the file, the line and the effect: the path was filtered out of the build context by `.dockerignore`, so the `COPY` had nothing to match. Guarded by `TestBuildContextContract`, which reads both Dockerfiles and asserts no local `COPY` source is excluded or absent. Verified in both directions: re-adding the exclusion fails the test with exactly the two offending lines, removing it passes. | The failure would have to be a different `COPY`, and the test now names which one. |
| - | **HYGIENE** | Stop shipping `tests/`, `sonar-project.properties`, `pytest.ini`, `.coveragerc` and `coverage.xml` in the docker-only archive; remove the packager machinery that generated them | The probe above answered. No stage reads any of them under this template, and files no stage reads do not belong in a submission archive. | Cannot fail a gate: none is a recognised manifest and none is read. |

**No probe in this release.** The one open question was answered by 0.5.7 and
the remaining change is a named, reproduced build failure.

**Standing note, unchanged.** Phase 2, restoring the manifests, is atomic and
stays parked until the analyser's real error text, the `.pre` resolution job's
log, PSIRENS's `pyproject.toml`, or a fix arrives. The 0.5.7 result sharpens
what it would buy: all four gates return together, or none does.

## 0.5.9

Three defects reported from the live console. Two are fixed here and both were
reproduced in a real browser against a running instance before a line was
changed. The third, self-service password reset, is a feature and is not in
this release.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Root every flash-carrying admin response at a `<div>`/`<table>` instead of a bare `<tr>` | Reproduced in Chromium: the create POST returned 200 with the new row and the flash in the body, and htmx threw `htmx:swapError` / `TypeError: e.querySelectorAll is not a function`, abandoning the swap. htmx 1.9.12 picks its parsing path from the first tag; a `<tr>`-rooted response is wrapped in `<table><tbody>`, and the parser then foster-parents the sibling flash `<div>` out of the table. Measured blast radius: create, save-edit and delete all failed; open-edit and cancel, which carry no flash, were clean. After the fix all three swap live with zero console errors. | The defect would have to be elsewhere in the swap, and the console now reports it directly. |
| Runtime correctness | **EVIDENCED** | Add the `csrf_token` field to the two plain POST forms that lacked it | The reported symptom was `{"detail":"CSRF validation failed."}` from the sidebar Return to Operations button. A template-wide audit found the same omission on Sign Out in `admin/users.html`, which nobody had reported yet. Both now submit cleanly in the browser; the third form without a field is `/login`, which is in `_EXEMPT_PATHS`. | Not applicable: verified end to end in a browser, and guarded by a test that fails with the exact filename and line when the field is removed. |

**Why not the one-line fix.** htmx 1.9.12 has `htmx.config.useTemplateFragments`,
which parses every response inside a `<template>` and sidesteps table
foster-parenting entirely. It is the documented remedy and htmx 2 makes it the
default. It was rejected here because it changes fragment parsing for every
swap in the application, and this session could not smoke-test all of them. The
structural fix touches only the user management page and cannot regress
anything else. The flag remains available if a wider pass is ever run.

**Both guards were tested in both directions.** Reinstating the removed
`csrf_token` field makes the audit fail naming `training.html:131
action=/training/leave`; restoring it passes. The response-shape tests assert
on the wire rather than the template, because the defect is a property of the
bytes htmx receives, not of the markup that produced them.

## 0.5.10

No application behaviour changes. This is the first batch of the approved
improvement plan (`IMPROVEMENT-PLAN.md`), which closed the retrospective's
headline finding: nothing written in the previous window had a committed case
proving it could go red.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | A browser smoke probe, `scripts/smoke-browser.py`, that boots a throwaway instance and drives login, admin create and delete, training exit and sign out, failing on any uncaught exception or same-origin console error | Watched to fail and to pass. With the 0.5.9 fixes reverted it exits 1 naming `[admin-create] uncaught exception: e.querySelectorAll is not a function`, `the new row never appeared without a reload (1 -> 1)` and `[training-leave] leaving training mode was rejected by the CSRF guard`. With them restored it exits 0. Both defects returned HTTP 200 and were invisible to 850 server-side tests. | Not applicable: verified in both directions against a real browser. |
| Build integrity | **HYGIENE** | `tests/integration/test_packager_gates.py`, eleven cases that break one thing in a throwaway tree and assert the packager refuses, naming the reason | The packaging script had no test at all: five fail-closed branches deciding whether an artefact ships, with zero coverage. The harness immediately caught two defects in the gates added alongside it. | Cannot fail a submission: the harness runs locally and in the suite, not on the platform. |

**A guard is unproved until watched.** Two new packager gates ship with this
batch and both have a committed red case: a gate may not read a file git does
not track (the ledger lives in gitignored `docs/`, so that gate ran on one
machine only), and non-application material may not reach the archive (the
platform ignores `sonar.sources` and grades every file as application code).

**The harness caught its own author.** Its first version built the fixture from
`git archive HEAD`, so it exercised the previously committed packager and
reported every new gate as broken when it was simply absent from the code under
test. Fixed to copy the working tree. Recorded because it is the same class of
mistake as a guard that never runs.

**Coverage now reports the truth.** `fail_under` was 70 against a house standard
of 80 while actual coverage was 74.3, so the loop passed from underneath its own
bar. The floor is now a ratchet at 74 and `scripts/check-quality.sh` prints the
5.7-point gap on every run. The gap is real and open; nothing here closes it.

## 0.5.11

A correctness defect in the orbital mechanics, found by validating the Lambert
solver against a published reference rather than by any gate. Every gate was
green while this was live.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Correct the Lambert time-of-flight residual, replace divergent Newton with bracketed bisection, raise on non-convergence, and key the degeneracy guard to the transfer angle | Curtis Example 5.2: departure velocity error was **1,970 m/s**, now **0.05 m/s**; the round trip missed by **6,268 km**, now **0.14 m**. The GEO 180-degree phasing case missed by **74,790 km** and is now refused as ill-posed. Six geometries validated by propagating the computed departure state forward and measuring the arrival miss. | Not applicable: validated numerically against a published answer and by an independent propagator. |

**Two independent defects, either one sufficient.** The residual substituted the
gravitational parameter for the Stumpff function C(z) - Curtis defines
`chi = sqrt(y/C)`, the code wrote `sqrt(y/mu)` - so the iteration was not
solving the time-of-flight equation at all, never converged, and the routine
returned its unconverged value without complaint. Separately the degeneracy
guard tested the chord term A rather than the transfer angle, and `sin(pi)` in
floating point is 1.2e-16 rather than zero, so at exactly 180 degrees A stayed
at 3.7e-12 and the guard never fired.

**Why no test caught it.** The tests that existed asserted the shape of the
answer: a velocity magnitude within 15 per cent of circular, a delta-V greater
than zero, a burn count of two. A transfer that misses by 6,268 km satisfies all
three. The new file asserts the answer instead, and includes a sensitivity case
proving the residual is tight enough to matter: a 10 m/s perturbation must move
the arrival point by more than 10 km, or the check is void.

**Blast radius.** `solve_lambert` feeds `lambert_intercept`, which is called
from the threat sweep at two sites in `spectre/web/routes/threat.py` and from
the manoeuvre planner. Every Lambert-derived delta-V, transfer cost and sweep
entry produced before this release was wrong.

## 0.5.12

Second half of the orbital calculation audit. Two more defects that produced
confidently wrong numbers, both invisible to every existing test and to every
pipeline gate.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Remove twelve double conversions of angles already in degrees in `maneuvers.py` | Plane-change cost at GEO measured against the closed form 2v.sin(di/2): a 0.5 degree change costs 27 m/s and was reported as 1,521 m/s, a 57x overstatement. The same corruption fed the J2 drift planner a 2,956 degree inclination and made the manoeuvre-direction classifier answer "normal" for almost any burn. | Not applicable: measured against a closed form. |
| Runtime correctness | **EVIDENCED** | Substitute the defined element when a classical element is undefined in `state_to_keplerian` | A state converted to elements and back moved 8,000 km for a circular inclined orbit, 17,074 km for an equatorial elliptical one and 78,460 km for circular equatorial, which is GEO. All six round-trip cases now return the same state. Latent rather than live: nothing currently reads `.ta` or `.argp`. | Not applicable: verified by round trip. |

**Findings recorded, not fixed.** `docs/ORBITAL-CALCULATION-AUDIT.md` lists
five open items: transfer functions with no input validation, a regime-blind CW
validity threshold (4.2 per cent error at 500 km in GEO against 23.9 per cent
in LEO), a GEO radius constant inconsistent with the sidereal day in the same
file, TEME and ECI conflated across the propagator boundary, and
`propagate_range` swallowing propagation failures.

**Eight of fifteen modules were not audited**, including `tactical.py`, the
largest in the package. Given that all three modules examined closely contained
a defect, the remainder should not be assumed clean.

**The tooling failed too.** `scripts/sonar_scope.py` crashed with a TypeError
whenever two findings shared a line, sorting tuples that end in a dict. It took
the whole quality gate down with it, which is how a gate stops being a gate.
