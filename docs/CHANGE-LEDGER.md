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

## 0.5.13

`tactical.py` audited, 2,129 lines. Three more defects, one of them a safety
function certifying a collision trajectory.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Correct the NMC establishing burn in `nmc_safety_ellipse` | The prescribed initial condition (radial burn from co-located) gives a trajectory through the origin once per orbit. Flown closest approach for a reported 5.000 km margin was **zero**. Now a radial offset plus an along-track burn of 2nA; flown closest approach 5.0000 km. | Not applicable: flown and measured. |
| Runtime correctness | **EVIDENCED** | Correct the `phasing_orbit` closure condition | It solved for a non-integer revolution count, so the chaser reached the target's angle at the wrong altitude. Semi-major axis error 5 km at a 5 degree gap, 5,615 km at 180 degrees. Now exactly 1.000000 revolutions against the closed form. | Not applicable: closed form. |
| Runtime correctness | **EVIDENCED** | Make `intercept_envelope_intercept` run the Lambert sweep its description always claimed | It discarded the state vectors it held and passed two radii to a phase-blind estimate, which measured 1.3x to 121x optimistic against true Lambert. It also took its delta-V budget from a parameter named `target_distance_km`. | Not applicable: measured against Lambert. |

**Three pre-existing tests were asserting an impossible manoeuvre.** Closing a
30 degree gap in one revolution from a 400 km LEO needs a phasing orbit with
its far apsis 275 km below the surface. The old code returned a number for it.
Those tests now use GEO, and a new case asserts the LEO refusal.

**Checked and found correct:** `geo_drift`, `graveyard_transfer`,
`j2_raan_rate`, `cw_radial_separation` and `cw_along_track_drift`, all against
independent relations or the validated CW propagator.

**Not audited:** fourteen heuristic and classification functions inside
`tactical.py`, plus seven whole modules. These encode judgement rather than
physics and need a doctrine review, not a numerical one, but note that
`fingerprint_manoeuvre` and `orbital_terrain` were both being fed angles
corrupted by the 0.5.12 units defect.

**Recorded, not fixed:** the threat sweep wraps every method in
`except Exception: pass`, so an infeasible method drops out silently and so
does a genuine bug.

## 0.5.14

Phase 1 of the roadmap: connect the evidence the application already holds to
the verdict it already shows. No new science, no new data source. The red-team
assessment found that `threat.py` computed an "adversary capability assessment"
from four thresholds on a delta-V number and consulted none of the three risk
verdicts the application computes elsewhere.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Compose the sweep verdict from geometric access AND assessed capability, in a new `spectre/domain/threat_assessment.py` | The shipped `adversary_intel.json` records Kowsar and Kowsar-1.5 as `LOW` / `Degraded`. Both have a cheap co-orbital geometric path, so the sweep scored them `CRITICAL` while the intelligence panel on the same screen said the opposite, with nothing reconciling the two. Reproduced and asserted: the same inputs now return verdict `MINIMAL`, access `CRITICAL`, capability `MINIMAL`. | Then the weaker-side rule is wrong for some class of object, which the separately-visible access and capability bands would make obvious rather than hiding inside one word. |
| Runtime correctness | **EVIDENCED** | Rank sweep entries and the worst course of action on warning time, with delta-V as the feasibility filter | `entries.sort(key=lambda e: e.delta_v_km_s)` ranked a 0.05 km/s intercept arriving in 3 hours above a 0.40 km/s intercept arriving in 30 minutes, and called the first the greater threat. Measured on the same entry set, the ranking now inverts and the headline reports 0.5 hours of warning. | Then delta-V is the operational quantity after all, which would be a real finding about the doctrine rather than the code. |
| Runtime correctness | **EVIDENCED** | Record why each transfer method produced nothing, and show it | Eight `except Exception: pass` blocks. A method that threw was indistinguishable from one never tried. The refusals are not evenly distributed: a degenerate Lambert geometry is the near-180-degree GEO phasing case and an unflyable phasing orbit is the short-notice one, so silence biased the sweep towards under-reporting the fastest approaches. It is also how the Lambert `sqrt(y/mu)` defect survived. | Not applicable: the refusal strings come from the solvers' own messages. |
| Runtime correctness | **EVIDENCED** | Bind the refusals panel to the context key the route actually passes | **A defect in this release, found before it shipped.** The panel was bound to `assessment.method_refusals`; the route passes `method_refusals` at the top level. Jinja's default undefined is falsy and silent, so the panel never rendered, the page returned 200, the browser probe passed with no console error, and all 956 tests stayed green. Caught by writing the guard, not by running the code. | Not applicable: watched to fail against the original binding and to pass against the fix. |

**The fix could have introduced a worse failure than the one it removed.** If
an object with no capability record were scored as incapable, the sweep would
quietly stop reporting exactly the objects nobody has assessed yet. `band()`
returns `None` rather than `MINIMAL` for absent evidence, the verdict falls
back to geometry alone with `LOW` confidence, and the rationale says in words
that it may overstate the threat. Two committed cases pin that behaviour.

**What is deliberately still missing.** Behavioural capability - propellant
budget, anomaly score, observed manoeuvre count - needs an element-set history.
The sweep holds one current TLE per object, so those three fields stay `None`
and the interface reports "3 input(s) unavailable" rather than assuming either
way. Connecting them is a data-fetch change, not a scoring change.

**Roadmap item 3 is only partly delivered, and is recorded as such.** The
verdict rationale is now written from real evidence, but `_sweep_intents`, the
static dictionary mapping solver name to prose, is still in place. Replacing it
needs the manoeuvre classifier, which needs the same absent history.

**A new class of guard.** `tests/unit/test_threat_sweep_template.py` renders
the real template under `StrictUndefined`, with the `worst_coa` fixture built
by calling the real `_compute_worst_coa` rather than typed out, so it cannot
drift from what the route passes. Every server-side test in this repository
asserts what a handler returns; none asserted that the page showed it. That was
the gap the binding defect fell through.

## 0.5.15

Two changes that belong together. Everything the operator reads is now metres
per second, and a delta-v figure is no longer shown bare: it is read against
what satellites actually do, in three postures, per manoeuvre kind, per regime.

Reference throughout: "Satellite Manoeuvre Delta-v: Feasibility Above 0.5 km/s
and Budgets by Regime" (Bluestaq Limited Space Watch, v1.0, 13 October 2026).

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Replace the four global access thresholds with posture bands per (regime, manoeuvre kind) in a new `spectre/domain/manoeuvre_calibration.py` | The old bands were 200, 500 and 1,000 m/s. EVERY counterspace manoeuvre on open record sits below the lowest: Luch/Olymp-K 2 relocated 62 degrees for 11 m/s, SJ-21 towed Beidou-2 G2 for about 60 m/s, Cosmos 2576 shadowed USA 314 for 25-30 m/s, and the most aggressive GEO repositioning measured about 170 m/s. The band returned CRITICAL for all of them, so it was saturated. The nine documented cases now return three different postures, asserted. | Then the band boundaries are wrong, which the committed cases make visible one at a time rather than hiding behind a single verdict. |
| Runtime correctness | **EVIDENCED** | Reject a transfer no flown platform could deliver in the time of flight | An all-electric GEO bus holds up to 1,500 m/s but thrusts at about 0.27 N on roughly 3,000 kg, so it accelerates at 9e-5 m/s^2 and needs about 64 days to deliver 500 m/s. The sweep ranks on warning time, so it actively PREFERRED short flight times, which is exactly where the impulsive approximation fails. Measured: 450 m/s arriving in 0.6 h was scored CRITICAL and is unflyable by anything; the fastest class, a storable-chemical OTV, needs 2.5 h. | Then a platform class is mis-specified. The thrust and mass behind each figure are cited at the entry, so the wrong one can be found and corrected without touching the rule. |
| Runtime correctness | **EVIDENCED** | Default budget 3,000 m/s to 500 m/s | 3,000 m/s exceeds the discretionary reserve of every flown platform class except a hybrid servicer at its upper bound, so the sweep accepted as feasible intercepts nothing could fly. The assessment's bottom line is that 500 m/s by an on-station object is a strong anomaly flag, which makes it the right outer edge. | Then real behaviour above 500 m/s exists that the assessment did not find, which would be a genuine finding about the sources rather than about this code. |
| Runtime correctness | **EVIDENCED** | Convert the operator-facing layer to m/s, keeping the astro package in km/s | `MU_EARTH` is 398600.4418 km^3/s^2 and SGP4 returns km and km/s, so the physics layer's unit is not ours to choose. Conversion happens once, in `from_km_s`, at three named route boundaries. | Not applicable: a guard asserts the astro package keeps its km/s names and that no line outside it scales by 1,000 without naming the km side. |
| Runtime correctness | **EVIDENCED** | MIN_TIME took its delta-v budget from the target DISTANCE | `max_dv = target_km if target_km > 0 else 3.0` at `maneuver.py`, where `target_km` is `target_distance_m / 1000.0` and is used as a separation everywhere else. An operator asking for a 500 m standoff set the solver's budget to 0.5 km/s. This is the SECOND site of a defect recorded in 0.5.13 for `intercept_envelope_intercept`. | Not applicable: the two quantities are now separate parameters with their units in their names. |
| Runtime correctness | **EVIDENCED** | Convert the Hill-frame burn vector round trip | The intercept panel posts `b0.dv_prograde` into `/plan/geometry`, which clamped at +/-20 and passed the value to the Clohessy-Wiltshire propagator as km/s. Once the panel emitted m/s, a 380 m/s burn either failed the clamp or reached the propagator a thousand times too large. | Not applicable: the form carries m/s, the clamp is +/-20,000 m/s, and the handler divides once. |

**A defect I introduced and did not catch myself.** Converting
`intercept_geometry.html` with a blanket relabel changed three Hill-frame
velocities from `km/s` to `m/s` **without scaling them**, printing a number a
thousand times too small. The string-based guard went green precisely because
the relabel removed the string it searches for. An adversarial completeness
pass over the change found it. There is now a second guard that pairs known
km/s attributes with their labels and requires a scaling, watched to fail
against the broken line and to pass against the fix.

**Four more sites were silently wrong after the rename and before the audit:**
the delta-v budget bar divided by a hardcoded 3.0 and captioned itself "% of 3
km/s"; the sweep's row colouring banded at 0.5 and 1.0, which against m/s
shades every row above 1 m/s the same; the intercept panel banded CRITICAL at
2.0, making almost every intercept critical; and the trade-space chart labelled
its axis km/s while plotting m/s. None raised. All four put a wrong number in
front of an operator.

**Corrected, not just relabelled:** the `evasive` Monte Carlo archetype was
30 m/s. Table 4 puts a collision avoidance manoeuvre at centimetres per second
to about 1 m/s and notes that the screening threshold drives how OFTEN one is
flown, not how large it is. Now 2 m/s with a wide dispersion. The other six
archetypes already matched the published figures and now cite them.

**Also converted:** the operator guide generator, which is the only written
description of the units, and the training scenarios, whose GRADED answers
carried km/s values and tolerances. A unit changed without its answer marks a
correct response wrong.

**Deliberately left in km/s, and stated rather than hidden:** the orbital state
vector panel. Orbital speed is about 7.6 km/s in LEO and 3.07 km/s at GEO, and
the assessment this calibration comes from writes orbital speed in km/s and
manoeuvre cost in m/s throughout. The guard carries this as its single
allow-list entry, with a test that fails if the entry stops applying.

**Not addressed:** `pol_results.html` converts km/s to m/s in twelve places
inside the template while `pol.py` converts at the route boundary. Both are
currently correct and self-consistent, but the moment anyone converts
`PatternOfLifeResult` at the boundary the chart series goes to 1,000,000x while
the table goes to 1,000x, in the same panel. Recorded, not fixed.

## 0.5.16

The pattern-of-life double-conversion trap recorded in 0.5.15, closed. No
template performs unit arithmetic anywhere in the application.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Move every km/s to m/s conversion out of the templates and into the route boundary | Four templates scaled inline in eighteen places: `pol_results.html` twelve, `intercept_geometry.html` three, `notso_results.html` two, `pol_mc_results.html` one. Each was correct; together they were a trap, because the route layer converts at its boundary too. Converting `PatternOfLifeResult` at the boundary, the obvious next step, would have left the template scaling an already-converted value: charts at 1,000,000x and the table at 1,000x in the same panel, neither raising. | Not applicable: the invariant is now enforced. A template containing `* 1000` fails the guard, and the three routes were watched failing it. |
| Runtime correctness | **EVIDENCED** | Decompose `_compute_intercept_intel`, 163 statements across 56 branches | Past the point where a reader can hold it or a reviewer can check it, at roughly half coverage, so a refactor would silently change one branch in forty. 47 characterisation tests were written FIRST, pinning its output across every method, every delta-v band and the time-of-flight labels, then four pure helpers were extracted and the same 47 tests re-run. | Not applicable: behaviour is pinned by the characterisation suite, which asserts what the code does rather than what it should do. |
| Runtime correctness | **HYGIENE** | One flight-time label, used by both panels | The sweep and the intercept panel each carried an identical if/elif chain. Two copies of a format is two places to drift, and an operator comparing the screens would see the same duration written two ways with no way to tell which to trust. | Cannot fail a gate; it is a duplication removal with both call sites covered. |

**Three ways to reach the failure, each watched failing.** A template that
scales; the conversion running twice in Python, caught by value with the
message "482000.0, expected 482.0"; and a template going back to reading a
km/s field, which would make a future boundary conversion double up again.

**A second class of guard, from the 0.5.14 lesson.** Moving twelve conversions
out of a template means the route must now supply twelve names, and Jinja's
default undefined is falsy and silent, so a typo renders a blank panel and
nothing raises. A contract test parses each panel for the names it reads and
asserts the route passes every one. Watched failing against a deliberately
misspelled key.

**Dead code removed in passing:** the Monte Carlo route accepted a `dv_km_s`
form parameter it never read, and the template posted it. Both gone.

**Confirmed and unchanged, at the operator's direction:** the orbital state
vector panel stays in km/s, and the astro package keeps km/s internally. Both
remain the guard's documented exceptions, each with a test that fails if the
exception stops applying.

## 0.5.17

Blue asset screening: the sweep inverted. Select a blue HRR object and every
red object that could reach it is screened, assessed and ranked.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime capability | **EVIDENCED** | Screen one blue asset against every compatible red HRR object, ranked on composite verdict with warning time as the tie-break | The sweep answered "what can this object reach", which requires the analyst to already know which object to ask about. Screening answers "who threatens this asset", which is the question they actually hold. It is also the first time the composite verdict discriminates: in the red-out sweep capability is one constant across every entry, because there is one red object. | Then the ranking rule is wrong, which the separately-named earliest arrival makes visible rather than hiding inside one ordering. |
| Runtime correctness | **EVIDENCED** | Name the earliest possible arrival separately, and state the disagreement when it is a different object from the most dangerous one | Ranking on verdict alone buries a fast approach behind a capability assessment that may be out of date. Ranking on warning time alone puts a derelict top and undoes the composite verdict. Both are computed; where they differ the panel says what it costs to be wrong about the capability call. | Not applicable: both orderings are asserted, including the case where they agree and no disagreement is reported. |
| Performance | **EVIDENCED** | No feasibility pre-screen built | Measured before any feature code, as the plan required: 53.8 ms per actor, of which 81 per cent is the 24-hour event scan at 30-second steps. 10 actors 0.54 s, 25 actors 1.35 s, 50 actors 2.69 s. The gate was "build the pre-screen if 25 actors exceeds about 4 s". It does not, so it was not built: an optimisation with nothing to optimise is a place for a defect to hide. | Then the measurement was taken against an unrepresentative element set. The figure and the conditions are recorded here so a slower case can be compared against them rather than guessed at. |

**Capped at 60 actors**, about 3.2 s by the measurement above, and truncation
is always reported rather than silently applied.

**Every empty answer carries a reason.** No watchlist, no compatible red
object, no transfer inside the budget, and an asset with no cached element set
each produce a different sentence saying what was actually checked. "Nothing
listed" and "nothing can reach you" must not look the same, which is why the
no-candidates panel states how many red objects were screened and excluded.

**`_find_tle` could not have served this.** It searches the operator's own blue
assets and red tracks, which is right for the red-out sweep. Screening works
entirely from the HRR watchlist, where both ends live in `hrr_tle_cache` keyed
by satno, so a second resolver was needed rather than a parameter.

**Regime filter is `regimes_compatible`, not equality.** A GTO or HEO object
crosses both the LEO and GEO belts, so excluding it on a strict match would be
a false negative on exactly the case worth catching.

**Debt cleared to get the gate green**, all of it pre-existing and surfaced by
line shift: `_compute_intercept_intel` fell from 163 statements to 96 and then
to 31 branches by extracting the method-insight and summary blocks, and the
twenty-way method chain became a dispatch table. The 47 characterisation tests
written in 0.5.16 passed unchanged at every step, which is the only reason a
refactor of that size was safe to make alongside a feature.

**Not built, and not needed:** `_group_entries` was to gain an actor key. The
screen renders its own ranked actor table with expandable profiles instead, so
the sweep's grouping is untouched.

## 0.5.18

The HRR watchlist, delivered. Both the threat sweep and the asset screen now
run on a fresh instance with no UDL connection.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime capability | **EVIDENCED** | Anchor the `data/` rule in `.gitignore` to the repository root | It was unanchored, and gitignore matches at any depth, so it silently swallowed `spectre/data/` as well. The JSON already there survives only because it predates the rule. `git check-ignore -v spectre/data/hrr_default.json` named `.gitignore:102:data/` as the match: a file added there could never be committed and could never ship. This is the delivery failure that kept the watchlist missing, and it was invisible because nothing ever errored. | Then something else is excluding it. `git check-ignore -v` names the exact rule and line, and a guard now runs it on a probe file under `spectre/data/`. |
| Runtime capability | **EVIDENCED** | Ship a bundled bootstrap watchlist at `spectre/data/hrr_default.json`, last in the candidate path | The operator's `HRR_List.json` is gitignored and dockerignored on purpose: it is operational data. The result was that a deployed instance had no watchlist at all. `COPY spectre/ /app/spectre/` already ships package data, so this is the one place a default can reach a container. An operator-supplied file still wins. | Then the loader is not reaching it; the startup log now names the path it loaded from. |
| Runtime capability | **EVIDENCED** | Carry optional element sets through the HRR parser, and seed new sessions with them | An object list alone is not enough. Both capabilities need an element set per object, so seeding the list by itself populates a dropdown that then refuses to run with "No element set cached". A real JCO notification carries no element sets, so the live path is unchanged. | Not applicable: the screen was driven end to end with no UDL and ranked 14 candidate actors in 0.7 s. |
| Runtime correctness | **EVIDENCED** | Gate the asset and target selectors on having objects, not on a UDL session | Both templates opened with `{% if not has_udl %}` and refused to render. With a bundled list present that hid a usable watchlist behind a login it does not need, which is what made the capability look broken on a clean deployment. Measured: the selector rendered 0 assets before, 18 after. | Then the objects are not reaching session state, which the preload test asserts separately. |
| Runtime correctness | **EVIDENCED** | A UDL fetch now replaces a SYNTHETIC element set | All three fetch sites skipped anything already cached. Bundled element sets would therefore have survived every refresh, so connecting to UDL would have changed nothing and the operator would have kept reading generated orbits believing they were tracked. | Not applicable: `_needs_live_tle` is asserted for all three states (absent, synthetic, real). |

**The element sets are SYNTHETIC and nothing is allowed to imply otherwise.**
Catalogue numbers and names are real and public, and every red object joins to
an existing assessment in `adversary_intel.json` so the intelligence join is
genuinely exercised. The orbits are generated by
`scripts/build-hrr-default.py` to be physically consistent at a stated epoch.
They are tagged `SYNTHETIC`, the startup log says so at WARNING, the asset
selector carries a banner, and a UDL fetch replaces them. Four tests assert
each of those.

**The regime label is derived, not asserted.** The generator reads the
regime back out of each element set it produced, so the label and the orbit
cannot disagree. The screen filters candidates on that label, so a mismatch
would mean filtering an object on a description of an orbit it does not have.

**Recorded, not fixed:** the classifier calls a Molniya orbit GTO. It keys on
eccentricity above 0.5 with a low perigee and does not separate a transfer
orbit from an operational highly elliptical one. Both are trans-belt for
compatibility, so nothing is filtered wrongly, but the label reads oddly
against a Cosmos in a Molniya.

**A behaviour change worth stating:** "no watchlist" is no longer the default
state, so the integration test that asserted it had to clear the list
explicitly. That branch still has to say something, which is why it was kept
rather than deleted.

**Still needs UDL:** the sweep's RED INTERCEPTOR dropdown reads
`state.red_tracks`, which are operator-added tracks, not HRR objects. The
sweep's target side now works from the bundled list; its interceptor side
still needs a Red Track or a pasted TLE. Unchanged by this release, and not
something the watchlist can supply.

## 0.5.19

The Pattern of Life ΔV figures were measuring the gap between element sets, not
the manoeuvre between them. Every number downstream of them was wrong by up to
three orders of magnitude.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Stop estimating ΔV by differencing two propagated velocity vectors | The method propagated the before-element-set to the after-epoch and differenced velocities. That measures how far two trajectories have drifted, which is dominated by along-track phase and carries no ΔV information. Measured on a 550 km orbit: two fits of the SAME orbit at the SAME epoch differing only in mean anomaly by 0.1° (1.6 seconds of along-track timing) reported 13.3 m/s; at 30° of phase, 3,936 m/s. True ΔV is zero in both. The error also compounds with the gap: a real 6.95 m/s burn read as 395 m/s across 0.2 days and 1,971 m/s across one day. | Then the replacement shares the defect, which `test_dv_estimation.py::TestPhaseIsNotDeltaV` would catch: it pins the six measured phase offsets above and asserts each reads under 0.01 m/s. |
| Runtime correctness | **EVIDENCED** | Headline ΔV from epoch-swept propagation | Velocity differencing is exact at the instant of the burn and only then. Rather than abandon it, the gap is searched for the epoch at which the two trajectories are actually closest and the velocities differenced there. Measured against synthetic burns of known magnitude at known instants: better than 0.2% at every gap from 0.2 to 15 days, where the old method's error grew from 395 to 14,110 m/s on the same 6.95 m/s burn. | Then the error returns with the gap. Twelve parametrised cases assert the same burn reads the same at four gaps. |
| Runtime correctness | **EVIDENCED** | Per-variable decomposition from mean element differencing | This is what the operator asked for and what the drill-down renders: along-track from Δa, radial from the eccentricity vector, cross-track from Δi and ΔΩ, each carrying every input number and the relation applied, so a figure can be recomputed by hand. Mean anomaly is never read, so it is structurally immune to the defect above. | Then a channel is mis-inverted. Each is asserted against its analytic relation, and one test recomputes the along-track term from its own published inputs. |
| Runtime correctness | **EVIDENCED** | Take secular drift rates from SGP4 rather than the closed-form J2 relation | The two differ by enough to matter. On a 15-day gap the mismatch put 39 m/s of phantom plane change on a real 7 m/s burn, because natural node precession was only partly removed before differencing. The rates are read off SGP4's own initialised `Satrec`, which is the drift the catalogue's fits were produced against, and weighted by the measured burn instant because the orbit precesses at one rate before the burn and another after. | Then the residual returns at long gaps. The coasting case asserts under 0.1 m/s across 68° of natural node drift. |
| Runtime correctness | **EVIDENCED** | Measure the detection floor per object instead of assuming 2 m/s | A fixed threshold cannot know that one object's catalogue is one fit a day from one sensor while another's is nine a day from several providers that disagree. The floor is now the median plus five median absolute deviations of every consecutive-pair ΔV for that object. Both statistics are robust, so an object's own burns cannot inflate the threshold meant to find them: injecting 1% of samples at 5 km/s moves the floor by under 1%. | Then the floor is being set by the signal. That exact contamination case is asserted. |
| Runtime correctness | **EVIDENCED** | Difference each fit only against the previous fit from the same source | Differencing one organisation's orbit determination against another's measures the disagreement between them. On a simulated catalogue with two providers 6.3 km apart in semi-major axis, cross-provider pairing put a standing 3.5 m/s on every provider switch and raised the measured floor from 2.8 to 9.1 m/s, burying every real station-keeping burn beneath it. | Then pairing is crossing sources. Asserted directly: every pair produced from a two-provider catalogue has matching sources. |
| Runtime correctness | **EVIDENCED** | Two tiers, and only confirmed events carry the headline statistics | A detection is confirmed only where two independent estimators agree within 1.5×, it stands ten times above the object's own measured fit scatter, and nothing about the element sets' provenance objects. Measured over four simulated catalogues of known truth, that combination returned no false confirmations on three of them and two on the sparsest; relaxing the signal requirement to five admitted twelve to sixteen. A statistical confirmation level was tried first and removed: at the 99.9th percentile it was set by the object's own largest burn on a sparse catalogue and missed all six known manoeuvres. | Then unconfirmed detections are reaching the propellant budget. `test_only_confirmed_events_carry_the_headline_statistics` asserts the cumulative ΔV equals the confirmed sum exactly. |
| Runtime capability | **EVIDENCED** | A drill-down panel behind every ΔV figure | Both element sets side by side with their provenance and fit residuals, all three estimators with their readings, every channel with the numbers that produced it, the measured detection floor, and why the result was or was not believed. Mean anomaly is shown and explicitly marked "not used", because it is the variable that caused the original defect. | Then a panel ships blank. Both branches are rendered under `StrictUndefined` in unit and integration tests. |
| Runtime correctness | **EVIDENCED** | The element set table renders at most 400 rows | Each row carries the full element set text, so the table ran about 2 kB per record with no cap. On a 3,676-set catalogue the panel rendered 7.3 MB of HTML into a 340 px scroll box. Capped to the newest 400, with the omission stated in the page rather than left silent. Measured: 7,321,947 characters before, 905,528 after. | Then something else is unbounded. The figure is the test. |
| Runtime correctness | **EVIDENCED** | The drill-down view returns every key in both branches | The first render under `StrictUndefined` failed on `confidence`, which the panel header read before the no-breakdown guard. A partial context is how a dead panel ships: the same class of defect as the refusals panel in 0.5.14. The view now builds a complete default dict and updates it. | Then a name was added to the template and not to the default. One test asserts the two branches have identical key sets. |

### What this costs

**The new figures under-report, and that is the right direction.** Across four
simulated catalogues the cumulative ΔV came out at 0.69 to 0.91 of truth,
because burns below the measured floor are genuinely indistinguishable from the
disagreement between successive fits. The old estimator over-reported by 5,581×
on the same data. Under-claiming a platform's expended propellant is
recoverable; over-claiming it by three orders of magnitude into a capability
assessment is not.

**The candidates tier exists so nothing is hidden.** Detections above the floor
that fail the forensic checks are kept, shown, and labelled with the reason,
but excluded from the cumulative ΔV, the propellant budget and the anomaly
score. An unconfirmed detection is not evidence of expended fuel.

### What it means for SATNO 62902

The reported 36,686.4 m/s of cumulative ΔV and 100% propellant consumed were
never a propellant measurement. The research basis puts a LEO smallsat's entire
lifetime budget at 500 to 2,500 m/s, so the figure was 15 to 70× anything the
platform could hold. The equal-and-opposite ±12.66 km altitude pairs on single
dates, and the rows at a 0.0-day gap, are the signature of two providers' fits
being differenced against each other, which the source-matched pairing now
prevents. On a catalogue built to match it (3,676 element sets, 385 days, two
providers, six known burns totalling 29.9 m/s) the detector went from 3,304
manoeuvres and 166,666 m/s to two manoeuvres and 20.5 m/s, with propellant
consumed falling from 100% to 0.9%.

**Recorded, not fixed:** the classification thresholds in `_SK_DV_LIMIT` were
never derived from anything, and the station-keeping limits they encode are
plausible rather than cited. They matter less now that the ΔV feeding them is
correct, but a 20 m/s station-keeping ceiling for all of LEO is an assertion,
not a measurement.

## 0.5.20

The open-source delta-V assessment, assimilated. Pattern of Life now reads the
same cited figures the threat sweep has used since 0.5.15, and the four of the
assessment's own named counterspace events that it called routine no longer are.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Derive the per-event station-keeping ceiling instead of asserting it | `_SK_DV_LIMIT` applied Table 3's ANNUAL budgets as PER-EVENT limits. Its GEO and HEO values matched the assessment's annual figures exactly, which is how the confusion was visible rather than merely suspected. Running the real classifier on the assessment's own named events returned "station keeping" for the GEO graveyard raise (11 m/s), both Luch/Olymp-K moves (11 and 15 m/s) and a 180 degree relocation (34 m/s). The ceiling is now the annual budget spread over the object's own observed cadence: 1.84 m/s for GEO at a fortnightly cycle. | Then the ceiling is wrong, not absent. Seven parametrised tests assert no named counterspace event classifies as routine, and two assert that collision avoidance and a real north-south burn still do. |
| Runtime correctness | **EVIDENCED** | Report the fraction of the PROPELLANT LOAD, not of total spacecraft mass | `_compute_propellant_budget` computed `1 - exp(-dv/ve)`, the fraction of total mass that had to be propellant, under a label naming the fraction of the tank. They differ by the propellant mass fraction: a LEO smallsat reading 0.9 per cent had spent about 9.2 per cent. It also applied 900 kg on a 3-tonne platform to every object in every regime, and computed `dv_remaining` with a `prop + prop` denominator returning a constant 1,495 m/s whatever the object. | Then the division is in the wrong place. One test asserts the reported figure equals the total-mass fraction divided by the propellant fraction; another asserts the remaining reserve is not that constant. |
| Runtime correctness | **EVIDENCED** | Re-derive the incapacity threshold so it can fire at all | `threat_assessment` grades an object MINIMAL, cannot act, at 95 per cent consumed, and that band dominates every other signal. With the old estimator reporting tens of km/s it fired on every object, so SATNO 62902 would have read as unable to act while actively manoeuvring. Correcting the delta-V did not fix it: 95 per cent of TOTAL MASS needs 9.40 km/s for bipropellant against a practical ceiling of 2.5, so it could then never fire. Reading the tank instead needs 1.57 km/s for a LEO smallsat and 0.85 for a chemical GEO comsat, both inside Table 2. A discretionary-reserve signal was added alongside, because most of a comsat's remaining tank is committed to station-keeping. | Then the band is unreachable again. The arithmetic for both regimes is pinned. |
| Runtime correctness | **EVIDENCED** | Score the anomaly budget term against the object's own regime | A full score was awarded at 200 m/s/yr for every regime: 4 times routine in GEO, 8 in LEO, 200 in MEO. A navigation satellite burning twice its regime's entire annual budget scored one point out of a hundred. | Then the per-regime figure is not reaching the score. The basis string names the regime and its cited budget, and a test asserts it. |
| Runtime capability | **EVIDENCED** | Say what the detection floor excludes | Table 4 puts collision avoidance at centimetres per second to about 1 m/s, and Starlink flew 207,152 of them between December 2025 and May 2026. The measured floor is 0.68 m/s on a clean catalogue and 2.80 m/s where two providers contribute, so routine traffic management is below it and always will be. "No manoeuvres detected" on such an object is materially misleading, and the panel asserted the object was passive. | Then a quiet object still reads as passive. A test asserts the word does not appear in the narrative and that the named events above and below the floor are both listed. |
| Runtime capability | **EVIDENCED** | Escalate an on-station delta-V at or above 500 m/s | The assessment's second watchlist recommendation. Nothing escalated on it. The measured decomposition distinguishes the plane-change explanation from the others, so the panel names which one the orbit change supports rather than listing four and leaving the operator to choose. | Then the escalation names the wrong cause. Two tests assert a cross-track burn leads with the plane change and an along-track one with the tug. |
| Runtime capability | **EVIDENCED** | Carry the rate constraint into Pattern of Life | The assessment's third recommendation: characterise electric platforms by rate, not reserve. `PLATFORM_CLASSES.minimum_burn_hours` existed but only the threat sweep used it. A 170 m/s relocation on an all-electric GEO bus is 21.9 days of continuous thrust, which rules out any scenario needing it at short notice. The figure uses the object's own assumed platform, not the fastest one that could afford it: a LEO smallsat is not an orbital transfer vehicle. | Then the wrong platform is being used. One test asserts the burn platform matches the regime's assumed class and exceeds the fastest available. |
| Runtime capability | **EVIDENCED** | Represent refuelling | The assessment's fourth recommendation. Cumulative delta-V is monotonic, so a refuelled object reads as progressively more exhausted exactly as it becomes more capable: 200 m/s gave 9.9 years remaining, 1,200 m/s gave 1.1. SJ-21 was refuelled by SJ-25 in 2025 and its spend since 2022 kept counting against it. An operator-settable reserve reset date now carries the count, with the earlier total retained and shown separately. | Then the reset is not reaching the figure. A test asserts the spend since the reset falls while the total is unchanged. |
| Runtime correctness | **EVIDENCED** | Move every calibrated judgement into the domain layer | Two sets of numbers for the same physics is worse than one set that is wrong, because only one gets updated. `manoeuvre_calibration.py` held the cited figures; `pattern_of_life.py` imported none of it and carried uncited duplicates. The astro package also works in km/s while every operator-facing figure is m/s, so the interpretation was on the wrong side of the unit boundary as well. Classification, propellant, anomaly scoring and the narrative now live in `spectre/domain/pol_assessment.py`. | Then a constant has come back. A test asserts the astro module no longer defines `_SK_DV_LIMIT`, `_GEO_SK_BASELINE`, `_ISP_MONO`, `_ISP_BI` or any of the three compute functions. |
| Runtime correctness | **NO CHANGE** | `DEFAULT_SWEEP_BUDGET_M_S` stays at 500 m/s | The assessment says "set the GEO alert threshold at about 0.1 km/s, not 0.5 km/s". This is the nearest 500 in the codebase and is not that threshold: it is the delta-V an interceptor is assumed able to spend. Lowering it would shrink the set of intercepts the sweep considers, which is the opposite of what the recommendation intends. The watch floor it is actually about is already at 100 m/s in the GEO posture bands. | Not applicable. Three tests pin the figure and the reasoning, so it is not "fixed" later by someone matching on the number. |

### What the assessment validates

SPECTRE reproduces eleven of its published worked values to within rounding,
having been built independently of them: both plane-change-per-degree figures
(53.66 against 54, 132.86 against 133), the GEO graveyard raise (10.94 against
11), three relocation cases, and the semi-major axis offset at 30 degrees a day
(2,342 km against 2,300). The estimator replaced in 0.5.19 reproduced none of
them. Four of those are now pinned as tests so a change to either side shows up.

### What it still cannot do

● Military and Chinese or Russian figures are lower bounds. The assessment rates
  its own confidence low: they are inferred from tracked orbit changes using
  impulsive two-body approximations, which is exactly what SPECTRE does.
● Platform ceilings are rocket-equation estimates, not published budgets. The
  assessment rates them moderate confidence, and every verdict turning on one
  inherits that.
● The MEO station-keeping figure has no authoritative source. A verdict leaning
  hard on 1 m/s/yr is leaning on the weakest row in the assessment.
● Both estimators assume an impulse. A months-long electric transfer is not a
  burn with a date, and where the platform is all-electric the burn epoch is the
  midpoint of a campaign. The panel now says how long the burn must have taken,
  which is the honest form of that caveat, but does not model the campaign.

**Recorded, not fixed:** the platform class is guessed from the orbit regime
alone. It is stated as a guess wherever it is shown, and it is strictly better
than one 3-tonne GEO assumption for every object, but an object's intel record
often knows better and is not consulted.

## 0.5.21

What an adversarial review of 0.5.19 and 0.5.20 found. Four defects confirmed
by measurement, one reported backwards and pinned the right way round.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | A single large manoeuvre no longer reads MINIMAL risk | The anomaly score needs two manoeuvres to say anything, so an object with exactly one fell through to MINIMAL. Measured: a catalogue with one 450.7 m/s AGGRESSIVE relocation reported risk level MINIMAL, because it happened only once. The worst observed posture is now a floor under the score: BEYOND PLATFORM gives CRITICAL, AGGRESSIVE gives HIGH, ANNOYANCE gives MEDIUM. It is a floor and never a ceiling, so a single BENIGN burn still reads MINIMAL. | Then the floor has become a ratchet. Both directions are asserted: 450 m/s gives HIGH, 13.7 m/s gives MINIMAL. |
| Runtime correctness | **EVIDENCED** | The duplicate merge is bounded at both ends | Each detection was compared only against the previous cluster member, so clustering chained without limit. Measured: ten genuinely distinct burns spaced nine-tenths of a merge window apart collapsed into one event, which is exactly the shape of a low-thrust electric campaign. A cluster may now span at most two windows end to end. | Then the cap is too tight or too loose. Two tests: ten spaced burns stay several events, and two providers reporting one burn 0.2 days apart still merge to one. |
| Runtime correctness | **EVIDENCED** | A Table 2 total standing in for a discretionary figure says so | Table 2 publishes a discretionary or margin figure for two of the six platform classes. The other four carried their TOTAL lifetime budget in a field named discretionary, so the propellant panel credited a LEO smallsat with 2,500 m/s of reserve available for manoeuvring against another object when that total is mostly drag make-up, collision avoidance and deorbit. The field now carries `discretionary_is_published`, and the panel says when it is standing in. | Then the flag is not reaching the caveats. Asserted for both a published class (GEO) and an unpublished one (LEO). |
| Runtime correctness | **EVIDENCED** | The intercept panel's ΔV budget label names its own denominator | The percentage moved to the realistic 500 m/s budget in 0.5.15, with a comment in the route saying so. The template's hardcoded "% of 3.0 m/s" did not move with it, so the panel reported a figure against a number 167 times smaller than the one it was computed with. The denominator now travels with the percentage. | Then another label has drifted from its computation. A test asserts the literal is gone and the context key is present. |
| Runtime correctness | **EVIDENCED** | `maneuver.py` stops calling a year's budget a station-keeping burn | A fourth copy of the same Table 3 figure. `_ANNUAL_STATION_KEEPING_M_S = 50.0` is named honestly but was used as a per-event boundary, so everything from 1 m/s to a whole year's budget was labelled "Station-keeping scale". That band covers the Luch/Olymp-K relocations, the graveyard raise and a 180 degree repositioning. A band for one real burn was inserted below it, derived from the calibration module rather than asserted, and the band above renamed to what it means. | Then the boundary is wrong, not the label. The characterisation test pins both: 1.5 m/s is station-keeping scale, 11 m/s is within a year's budget. |

### The finding that was reported backwards

A reviewer reported that the epoch-swept estimator under-reports a large
manoeuvre and should be replaced by the element decomposition. Measured against
the exact two-burn Hohmann cost, the opposite is true:

| Δa | Δa/a | Hohmann (truth) | element n·Δa/2 | epoch-swept |
|---|---|---|---|---|
| 100 km | 0.015 | 54.74 m/s | +1.1% | +0.00% |
| 500 km | 0.073 | 262.39 m/s | +5.5% | +0.03% |
| 1,000 km | 0.145 | 498.96 m/s | +10.9% | +0.12% |
| 2,000 km | 0.291 | 908.40 m/s | +21.8% | +0.41% |

The swept figure is accurate; the element figure over-reports. The headline
selection was already right.

**The review was reading a defect in this project's own test harness.** The
synthetic truth value in `test_dv_estimation.py` used `0.5·v·Δa/a`, which is
the same first-order relation the element estimator uses, so the harness agreed
with the estimator precisely where the estimator was wrong. A harness that
shares an estimator's approximation cannot detect that approximation failing.
It now computes the exact two-burn cost, the per-channel note says when Δa is
large enough for the first-order relation to matter, and three parametrised
cases pin the overshoot at 100, 500 and 1,000 km.

**Recorded, not fixed:** the sweep drops solutions between 500 and 3,000 m/s,
so orbital transfer vehicle and tug activity never reaches a posture;
`breakdowns_truncated` is computed from the already-merged candidate list and
so can never fire; and the detection provenance block claims a measurement it
did not make when there are no usable pairs. All three were reported, none is
operator-facing in the way the five above are, and none is fixed here.

## 0.5.22

An operator correction, and the adversarial physics review of 0.5.19 to 0.5.21.

### The operator correction, and why it mattered most

A NOTSO is issued only after human-in-the-loop analysis, and notices are
deliberately WITHHELD for small routine manoeuvres so the channel is not
flooded with inconsequential traffic. A routine station-keeping burn therefore
carries no notice, and its absence says nothing about the operator.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime correctness | **EVIDENCED** | Measure the notification rate over REPORTABLE manoeuvres only | `notification_rate = manoeuvres_with_notso / total_manoeuvres` counted every detected burn, including the routine ones nobody files a notice for. It was therefore measuring how much station-keeping an object does rather than how forthcoming its operator is. The bands below it ran `stealth_operator` at under 30 per cent, so a fully compliant operator whose manoeuvres are all routine scored zero and was labelled stealthy on the panel, in red. The denominator is now manoeuvres above the regime's routine per-burn ceiling, which the calibration module derives from Table 3. | Then the threshold is wrong, not the denominator. A test takes ten burns at 1 m/s with no notices and asserts the profile reports none of them reportable, the behaviour unassessable, and no low-rate flag. |
| Runtime correctness | **EVIDENCED** | Withhold a behavioural band on too small a sample | One unreported burn out of one is not a pattern. A band is now offered only above three reportable manoeuvres, and `behaviour_unassessable` says so otherwise. | Then the minimum is too low. Asserted at one reportable manoeuvre. |
| Runtime correctness | **EVIDENCED** | Stop calling a NOTSO with no detection a phantom | `phantom_notso_count` put the blame on the operator for filing a notice for a burn that never happened. A NOTSO follows human analysis, so the likelier reading by far is that the burn sat below OUR measured detection floor, which on most LEO catalogues is above routine station-keeping. Renamed `notso_without_detection_count`, and the panel says which reading is likelier. | Then the vocabulary has come back. The template is asserted free of both "stealth" and "phantom". |
| Runtime correctness | **EVIDENCED** | Stop colouring a detection with no notice as suspicious | The panel rendered "manoeuvre-only" in red. That is the EXPECTED case for a routine burn. | Then the colour is back. |

### What the physics review found

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Runtime capability | **EVIDENCED** | GET /pol/panel no longer returns 500 once an analysis exists | `pol_panel.html` includes `pol_results.html` whenever an analysis is in session state, and the panel route supplied none of that template's context. The include fired, the first name it read was undefined, and StrictUndefined raised. A hard 500 on every reload of the panel after running an analysis. | Then another name is missing. An integration test reloads the panel with a real analysis in state and asserts two sections render. |
| Runtime correctness | **EVIDENCED** | The J2 perigee rate is no longer the exact negative of itself | `1.5·(2.5sin²i − 2) = 3.75sin²i − 3` against the correct `0.75·(5cos²i − 1) = 3 − 3.75sin²i`. The correction added the natural perigee rotation instead of removing it, and doubled it. Present in both `dv_estimation` and `pattern_of_life`. On a 550 km, 53° orbit the rate is +3.10°/day, not −3.10. | Then the sign is wrong again. Asserted against the closed form at three inclinations including the critical one. |
| Runtime correctness | **EVIDENCED** | The energy channel holds on eccentric orbits | `n·Δa/2` assumes a circular orbit. An eccentric orbit is cheapest to raise at perigee, where the speed is highest, so the circular form over-reported by 36 per cent at e = 0.3 and 139 per cent at e = 0.7 — squarely where GTO and Molniya objects sit. Now `Δv = μ·Δa / (2·a²·v_perigee)`, which collapses to the familiar form when the orbit is circular. Measured error after: 0.21 to 0.26 per cent across e = 0 to 0.7. | Then the perigee speed is wrong. Five eccentricities are pinned against the vis-viva truth, and the circular case against `n·Δa/2`. |
| Runtime correctness | **EVIDENCED** | A radial burn can be confirmed at all | The expected position mismatch accounted for Δa and the plane angle but not the eccentricity change, which separates the orbits at apsis by about a·\|Δe⃗\|. Every radial burn was therefore set aside, the headline fell back to element differencing, and the confidence dropped to LOW, so an eccentricity change could never be confirmed and never reached the cumulative ΔV. Measured: a 3.8 m/s radial burn missed by 3.46 km against a 2.07 km allowance. | Then the term is wrong. Four eccentricity changes are pinned as HIGH confidence with the swept headline. |
| Runtime correctness | **EVIDENCED** | The duplicate merge is source-aware, not time-only | Two detections can only be one burn if they came from DIFFERENT sources: within a source each record is differenced against the previous record from that same source, so one burn gives exactly one detection. The previous version clustered on time and chained off the most recently added member. Measured: six real 10 m/s burns 0.9 days apart in a one-fit-per-day SINGLE-provider catalogue produced five correct detections totalling 62.2 m/s, which the merge reduced to two totalling 31.8 m/s, attributing three real burns to a provider that was not in the input. The bounded span shipped in 0.5.21 narrowed that loss; it did not stop it. The sources that corroborated a surviving detection are now recorded on it. | Then the source key is not reaching the merge. Three cases: ten single-provider burns all survive, two providers reporting one burn merge to one with the corroborating source recorded, and two providers reporting two burns keep both. |
| Runtime correctness | **EVIDENCED** | One named provider now separates from unattributed fits | Source matching required two NAMED providers, so a catalogue of one named provider interleaved with unattributed fits fell back to plain consecutive pairing. Measured: 5 of 5 pairs crossed the attribution boundary, which is the cross-provider differencing the function exists to prevent, and it defeated the `cross_source` warning too because one side had no source to compare. | Then the guard is inverted. Asserted for the interleaved case and for a wholly unattributed catalogue. |
| Runtime correctness | **EVIDENCED** | A floor above any plausible fit scatter is not reported as measured | Median and MAD are robust only while manoeuvres are a minority. At 50 per cent contamination with 50 m/s burns the floor came out at 149 m/s, above the very events it exists to find; at 60 per cent and beyond it sat exactly on them. Two good fits of one object agree to about a kilometre in semi-major axis, well under a metre per second, so a floor of 50 m/s cannot be scatter. It now falls back to the absolute floor and says why. | Then the ceiling is wrong. Four contamination fractions are pinned. |
| Runtime correctness | **EVIDENCED** | An unmeasurable noise floor cannot confirm | With a degenerate MAD the signal-to-noise is None, and `_judge` treated that as passing, awarding HIGH on estimator agreement alone. Agreement says the arithmetic is consistent; it says nothing about whether the figure stands above a scatter that could not be measured. | Then the branch is back. Asserted on a flat sample set. |
| Runtime correctness | **EVIDENCED** | NOTSO and photometry correlate against all detections | Both were fed the HIGH-only list, so a declared manoeuvre we detected at candidate confidence had nothing beside it. A NOTSO matching a candidate is the strongest corroboration available for that candidate. | Then the tier filter is back on the evidence path. |
| Runtime correctness | **EVIDENCED** | `breakdowns_truncated` reads the right list | It was computed after `candidates` had been rebound from the pair-candidate list to the candidate-TIER manoeuvre list, so it reported zero however many detections were truncated. | Then the name is rebound again. |

**Recorded, not fixed:** luni-solar inclination drift on GEO is not removed
before differencing, so up to about 1.8 m/s of natural plane drift reads as
cross-track ΔV on a 15 day gap; the sweep drops solutions between 500 and
3,000 m/s, so tug activity never reaches a posture; and the measured burn
epoch is wired into merging and the drill-down but not into the other
consumers, which still date events at the after-epoch.

## 0.5.23

Four failing gates, four root causes, and for the first time in thirteen
submissions the Dependency Scanning row is EVIDENCED rather than NO HYPOTHESIS.
The evidence is the analyser's own source: `dependency-scan-python` is GitLab's
`gemnasium-python`, which is public at
`gitlab.com/gitlab-org/security-products/analyzers/gemnasium`, tag `v6.6.3`,
the exact version the job log reports. Earlier entries recorded that the image
was not public. The IMAGE is not; the SOURCE is, and it answers everything.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Dependency Scanning | **EVIDENCED** | Compile all three lock files for Python 3.11 instead of 3.12 | Two lines of analyser source. `build/gemnasium-python/debian/Dockerfile` line 1 is `ARG DS_PYTHON_VERSION=3.11`, so the analyser image is built `FROM python:3.11-slim`. `builder/pip/pip.go` runs `pip download --disable-pip-version-check --dest ./dist -r requirements.txt` as the FIRST action on any pip project, and logs pip's output with `log.Debugf`, which the platform discards at its default log level. Our lock pinned `numpy==2.5.2` and `scipy==1.18.1`, both of which declare `Requires-Python >= 3.12`, so pip could not resolve and exited 1. Reproduced outside the platform: the same command with `--python-version 3.11` fails in 3.42 seconds on `No matching distribution found for numpy==2.5.2`; the job ran 3.5 seconds, 06:39:23.7 to 06:39:27.2. With the recompiled lock the same command exits 0 in 13 seconds. | Then the analyser is not running the interpreter its own Dockerfile declares, or the runner's index cannot serve the pins at all. Both are narrow and both are now answerable with one line from `SECURE_LOG_LEVEL: debug`. The next structural move, if needed, is a `uv.lock`: `finder/detect.go` elects a lock-file-bearing package manager over pip for the whole pypi package type, and `buildProjects` skips lock-file projects entirely, so pip never runs. |
| Tests | **EVIDENCED** | Guard on the git EXECUTABLE, not the `.git` directory | The job log names four tests and one error: `FileNotFoundError: [Errno 2] No such file or directory: 'git'`. The same run SKIPPED `test_docs_are_committable.py` with "docs/ is excluded", which proves the `.git` directory was present: that module checks for `.git` first. So the platform's checkout has the directory and its job image has no executable. | Then the image has git after all and the failure is something else in the same four tests. The skip reason distinguishes the two cases by name. |
| DAST Scan | **EVIDENCED** | Mint a throwaway signing key when `APPSTORE_DAST_SCAN` is set and `SECRET_KEY` is not | The job log states the mechanism and the remedy in the same place: `no_report: the scanner got no answer from http://dast-target:8080 within 300 seconds`, then "The scan gives your container none of your environment variables or secrets... If your app must refuse to start without one (a signing key, say), generate a throwaway value when APPSTORE_DAST_SCAN=true." Reproduced locally: with `env -i` the boot dies on `ConfigurationError: SECRET_KEY is not set`; with `env -i APPSTORE_DAST_SCAN=true` it serves 200 on `/healthz` and `/` on port 8080. | Then the platform does not set that variable, and the next step is to ask what it does set, because no other startup input is missing: the data directory, database URL and port all have code defaults, and a missing admin password logs an error without stopping the boot. |
| Container Scan | **EVIDENCED** | Remove pip, setuptools and wheel `.dist-info` with the packages themselves | Six `pip-25.0.1` findings against an image whose prep stage already removed `/usr/local/lib/python3.12/site-packages/pip` and `/opt/venv/bin/pip`. The scan reads the dist-info, not the code, so the metadata was the whole finding. | Then the scan reads something else that names pip. The removal now verifies itself and fails the build closed, so a partial sweep cannot ship silently. |
| Container Scan | **EVIDENCED** | Bump the base image digest and certifi | The scan names both with a fix: `python-3.12.14` to 3.12.15 or later, `certifi-2026.7.22` to 2026.10.19 or later. The current `python:3.12-slim-bookworm` index digest carries Python 3.12.15, confirmed by reading the image config from the registry. | Then the platform's registry mirror served a different digest than the one pinned, which the build log would show. |
| Container Scan: Debian base CVEs | **NO HYPOTHESIS** | None | The remaining findings are Debian 12 packages with no fix available upstream (`util-linux`, `libc6`, `openssl`, `libsqlite3-0`, `krb5`, `perl-base`). Nothing we can do inside this base image clears them, and removing the dpkg database to hide them would be suppressing an unmitigated finding rather than mitigating it. | n/a. If these are what fails the gate rather than the three fixable items, the answer is a base image change (Debian 13 or distroless), which is a larger move and should be made on evidence that it is needed. |

**One EVIDENCED change per gate, and each is independently falsifiable.** The
dependency fix is the only one that changes what any other gate sees, and it
changes it in one direction: three pins move down or forward, and the full
suite, the hash-locked install under the image's own flags, and the in-package
run were all re-run against the new set.

## 0.5.24

The Code Quality gate. This is the first entry where the gate's own scoping is
the governing fact rather than a detail: SonarQube reports a rule only when the
code is inside the new-code window, so the 57 findings are a sample of a much
larger population, and every line a fix touches joins that window.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality: S3776 | **EVIDENCED** | Sixteen functions brought to 15 or below, measured with a calibrated implementation of SonarSource's algorithm | The report gives the exact score for sixteen functions. `scripts/cognitive_complexity.py` reproduces all sixteen EXACTLY, so its number is the gate's number rather than an estimate. Fifteen matched on the first attempt; the sixteenth, `solve_lambert` at 15 against Sonar's 17, exposed a real defect in the implementation: an `else:` whose body is a single `if` is the same AST node as an `elif`, and only the column offset separates them. Ruff's C901 was not usable as a proxy: it counts decision points where S3776 adds a nesting penalty, and the two differ by a factor of three on this codebase. | Then the gate's limit is not 15, or its profile scores a construct differently from the published specification. The calibration replays the exact commit Sonar scanned, so a disagreement would localise immediately to the rule that moved. |
| Code Quality: S3776 on code we touched | **EVIDENCED** | `fetch_tle` 67 to 12, `_run_intercept` 38 to 2, `apply_all_intercepts` 27 to 12 | None of the three was in the report. They entered the window because the fixes for OTHER findings added one line inside each. `fetch_tle` at 67 is the worst function in the repository and was invisible only because nobody had touched its lines since the scanned release; the `log_safe()` wrapper added for the S5145 fix put it in scope. This was caught by the scoped check, which had to be corrected first: it compared commits rather than the working tree, so it reported the tree clean while the artefact that would be uploaded was not. | Then Sonar's new-code window is narrower than the branch diff, these three were never going to be reported, and the work was insurance rather than necessity. That is an acceptable outcome; the reverse, discovering the window is wider, costs a submission. |
| Code Quality: S1192, S3358, S1172, S125, S8410, S8517 | **EVIDENCED** | Nine literals to module constants, five nested ternaries to statements, three unused parameters removed, one commented-out block deleted, four dependencies to `Annotated`, one sort-to-find-minimum to `min()` | Each is named with a file and line in the report. Each was re-counted across the tree afterwards rather than taken from the agent that fixed it: the nine literals now occur exactly once each, and no nested conditional expression remains in either reported file. | Then the rule reads something other than what was counted. For S1192 the likeliest cause is the occurrence threshold applying to a literal shorter than the shortest one reported, which was "Lambert arc" at eleven characters. |
| Code Quality: S7632 | **EVIDENCED** | Eighteen malformed suppression comments normalised; two deliberately left | Ruff's grammar is `# noqa: CODE` and nothing else on the line, so trailing prose makes the directive malformed. The rationale moved to the line above in every case; none was dropped. `_entrypoint.py:27` and `gcat.py:274` each need a ruff directive AND a bandit directive, and Python allows one comment per line. Bandit genuinely runs here: `.pre-commit-config.yaml` and `.github/workflows/ci.yml` both invoke it, and B104 and B310 are medium severity so `-ll` reports them. | Then one of the two left lines is in the window after all. The remedy is a project-wide bandit skip with the rationale recorded in `docs/CODE-QUALITY-GATE.md`, which is worse security hygiene and should be a deliberate decision rather than a default. |
| Vulnerability: S5145 | **EVIDENCED** | `log_safe()` at every site in `spectre/web/`, not only the reported one | The report names one line in `maneuver.py`. The sharpest instance in the application was never flagged: `login.py` logs a form field on the UNAUTHENTICATED path, so an attacker chooses the value outright. The review then found the first fix had wrapped the wrong argument in the UDL route, and proved it against the live route: `name_override` is only `.strip()`ed, so an interior newline survives and one record renders as two lines, the second indistinguishable from a genuine `Successful login: root`. | Then the rule's taint model does not treat these as sources, and the change is defence rather than remediation. It costs nothing either way: `log_safe` is the identity function for every legitimate value. |
| Bugs: accessibility | **EVIDENCED** | All fifty clickable rows and sortable headers given keyboard equivalents, plus `scope`, label association and row headers | Seven were reported; there were fifty across five templates, the rest invisible only because their lines had not changed. A shared `spectreActivate` handler in `base.html` rather than fifty inline copies of the same logic. A contract test pins the whole population. | Then the rule wants the handler on a different attribute, or wants a role as well. The contract test makes re-targeting a one-line change rather than a fifty-line one. |
| Bugs: css:S7924 contrast | **EVIDENCED** | A theme-aware caution text token | The computed ratios, not a judgement: `#EF9F27` is 9.00:1 on console black and **1.98:1** on the light theme's `#F3F4F6`, failing WCAG AA outright, and the light theme never overrode the token. `#8A5600` gives 5.59:1 on `#F3F4F6` and 6.16:1 on `#FFFFFF`. | Then the rule composites the translucent background differently, or cannot resolve a CSS custom property and has stopped analysing the declaration. The second would be silence rather than a pass, which is worth knowing. |

**What the review of the fixes found, and why it is in the ledger.** Six real
problems in work the first pass reported clean, the worst of them a keyboard
regression introduced by the fix for a keyboard finding: adding the activation
handler to a row made the button inside that row unreachable, because `keydown`
bubbles and the row's handler cancelled the button's own activation. A review
pass that only confirmed would have been worth nothing; this one changed the
release. It was also wrong five times, each rejected with evidence, which is
the other half of the same point.

**Recorded, not fixed:** 23 functions tree-wide remain over the cap, none in
the window; 104 `Depends(...)` defaults remain unconverted; 33 ruff findings
land on changed lines, all magic-value and argument-count debt from 0.5.19 to
0.5.22 and none corresponding to a rule in the Sonar report.

## 0.6.0

The audit release: Blockers through Low remediated since 0.5.24, plus the
dependency updates of 27 October. No change in this entry was made for a gate.
The audit fixes are what change what the gates see, and they are large: 65 of
the 70 Python files in `spectre/` and `tle_clustering/` changed, 9924 lines in
and 5497 out. No outcome was recorded for 0.5.24, so there is no prior verdict
on this base image or on the Code Quality window to build on. No probe ships.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Dependency Scanning | **EVIDENCED** | All three locks recompiled for Python 3.11 with asyncpg 0.32.0, fastapi 0.162.0, anyio 4.15.1, sqlalchemy 2.1.6 and scikit-learn 1.9.1; fastapi adds opentelemetry-api 1.45.1 | `scripts/preflight-gate.py` against the built package: 0 blocking, both shipped locks compiled for 3.11, every pin hashed, runtime lock a version-identical subset. `pip-audit` on 28 October: no known vulnerabilities in `requirements.txt`, `requirements-runtime.txt` or `requirements-dev.txt`. The msgpack fix for CVE-2026-114613 is in the developer lock only, which does not ship. | Then the analyser's advisory database carries an advisory the PyPI and OSV feeds behind pip-audit do not, and the report names the package. A bare `exit status 1` would instead mean a resolution failure under 3.11, which the preflight checks for and the 3.11 compile rules out. |
| Code Quality | **NO HYPOTHESIS** | None made for this gate | Local proxies, all clean on the release commit: ruff, mypy, bandit medium and above, CodeQL (security-extended, zero open alerts), and `scripts/cognitive_complexity.py` reporting 825 functions measured and 0 over 15 tree-wide (0.5.24 recorded 23 over). Line coverage 92% over the Sonar scope, `coverage.xml` produced inside the unzipped package. | Then the findings sit in remediation code, and the report names file and line. This release also settles an open question: the App Store guidance says the gate scores overall code, this ledger has assumed the new-code window. A finding on a line untouched since 0.5.24 would mean overall. |
| Container Scan: OpenSSL CVE-2026-84782 | **NO HYPOTHESIS** | None | Trivy 0.67.2 on the image built from this package: `libssl3` and `openssl` 3.0.22-1~deb12u1, fixed in deb12u2. The prep stage's `apt-get upgrade` takes it when the Debian security repository is reachable; the local build logged `OS PATCH: applied`. | Then the platform builder could not reach the repository, and its build log will say `OS PATCH: SKIPPED`. The remedy is a base digest that already carries deb12u2. |
| Container Scan: Debian base CVEs | **NO HYPOTHESIS** | None. Owner decision, 28 October: ship as is | Base digest unchanged since 0.5.23. Trivy reports 61 High or Critical findings with no Debian 12 fix: util-linux and its libraries, ncurses, perl-base, gzip, libsqlite3-0, zlib1g and the systemd libraries. Debian 13 (`python:3.12-slim-trixie`) was measured at 44, the same families, so it is not a remedy on its own. | Then the policy stops on unfixable Highs, not only fixable ones. The evidenced remedy is to remove the packages the runtime never uses (util-linux, mount, ncurses, perl-base, gzip, login, the systemd libraries) from the prep stage with dpkg, keeping sqlite and zlib, which Python needs. |
| Secret Detection, SAST | **HYGIENE** | CodeQL workflow and SBOM generation in `.github/` | Neither file ships: `scripts/` and `.github/` are excluded from the package since 0.5.2. gitleaks clean on every commit of the release. | n/a. |

### 0.6.0 outcome

● **Ten of eleven gates passed**: Dependencies, SAST Scan, SAST Findings,
  Dependency Scanning, Test, Dockerfile Lint, Container Build, DAST Scan and
  Container Scan.
● **Container Scan passed with the Debian base CVEs present.** Trivy counted
  61 High or Critical findings with no Debian 12 fix in this image. The policy
  therefore does not stop on unfixable Highs. The 0.6.0 row's "if it still
  fails" branch is closed, and no base image change is needed.
● **Code Quality failed: "New issues: 36 (max allowed: 0)"**, 31 code smells
  and 5 bugs, listed in full by the gate. This settles the question the 0.6.0
  entry left open: the gate counts new issues, not the overall code.
● **What "new" means here, measured rather than assumed.** 21 of the 34
  flagged lines were last changed after 0.5.24. Of the other 13, ten carry
  threshold rules (seven S1192 literal counts, two S107 parameter counts, one
  S3776 score), where the flagged line is the first occurrence and a later
  occurrence or parameter crossed the threshold. Two are multi-line tags with
  lines changed on 22 and 23 October inside them. One, the S1244 at
  `maneuver.py:253`, is not explained from here.

## 0.6.1

All 36 issues the 0.6.0 gate reported, and nothing else. Every edit is the
smallest that clears its rule, because each changed line joins the window.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality: S1244 (5 bugs) | **EVIDENCED** | Exact `== 0.0` guards become named tolerances (`_CIRCULAR_ECC`, `_RAAN_CLOSED_DEG`, `_ZERO_SPAN_S`, `_ZERO_DV_KM_S`); the burn split's guard becomes a `max()` floor | Each site named by the gate. Test-first: three of six new tests failed before the fix, including a real defect: an eccentricity of 1e-15 was named "descending node" on rounding noise. | Then the rule also reads `<` against a small constant as an equality check, which its documentation does not describe. |
| Code Quality: S1192 (11) | **EVIDENCED** | One module constant per literal; every occurrence replaced, each literal now appears once per file | Counted after the change, file by file. | Then a literal occurs elsewhere under a different quoting the count missed. |
| Code Quality: S107 (2) | **EVIDENCED** | `apply_intercept` and `decision_evaluate` bind their fields through Pydantic form models | Probed on the pinned FastAPI 0.162 before the refactor: aliased lists, blank-as-absent, 422 on a bad or out-of-range value and extra fields all behave identically to separate `Form()` parameters. New tests pin the form contract of both routes. | Then the rule counts the model's fields, which it does not for a single parameter. |
| Code Quality: S3358, S7632, S5713, S8410, S7504, S6353 (9) | **EVIDENCED** | Nested conditionals to statements; the noqa rationale moved above its line; `SignatureExpired` dropped as a subclass of `BadSignature`; three dependency pairs to `Annotated`; a redundant `list()` removed (`cancel()` only schedules the set edit); `\w` with `re.ASCII` | The `\w` change is the one that could have widened a control: without `re.ASCII` it accepts `usér_id`. A test proves the ASCII form refuses it, and the old and new patterns agree on every edge case tried. | Then the rule wants `\w` without the flag, which would be the wrong fix; the answer is a recorded exception, not a weaker allow-list. |
| Code Quality: Web S6819, S6793 (7) | **EVIDENCED** | Jinja comments moved out of two `<tr>` tags; the sweep chevron an SVG rotated by CSS; the geometry panel a `<section>` and its heading an `<h3>` | Three of the seven were artefacts: Sonar's HTML parser read words inside `{# #}` comments within a tag (`role="button"`, `aria-controls`, `aria-label`) as attributes. The `<h3>` renders identically to the span it replaces, measured in Chromium against the shipped stylesheets: same box and font, and the method line beside it stays at x=212.61. | Then the parser also reads a Jinja comment between tags, and the remaining comments need moving out of the template body. |
| Code Quality: JS S3776, S7761 (2) | **EVIDENCED** | `aiSort` split into four helpers; `setAttribute('data-idx')` to `dataset.idx` | Old and new `aiSort` run side by side in Chromium over seven clicks on the same table: row order, `aria-sort` and indicators identical at every step. | Then a helper scores above 15, which none can: the largest has one loop and two conditions. |

**Recorded, not changed:** one more `<button>` in `all_intercepts_result.html`
holds a Jinja comment inside its tag. It was not flagged, because its comment
contains no attribute-like words, and moving it would put its lines in the
window for nothing.

### 0.6.1 outcome

● **Code Quality reported two issues, both javascript:S7773**, at
  `all_intercepts_result.html:460` and `:461`: `parseFloat` and `isNaN`
  where the rule wants `Number.parseFloat` and `Number.isNaN`. None of the
  36 from 0.6.0 was listed again.
● **Both are lines 0.6.1 added**, in the `_aiSortKey` helper split out of
  `aiSort`. The window caught the fix, as the entry warned it could. The
  local proxies have no JavaScript rule set, so this class of finding is
  only visible to the gate.

## 0.6.2

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality: javascript:S7773 (2) | **EVIDENCED** | `Number.parseFloat` and `Number.isNaN` in `_aiSortKey` | Both lines named by the gate. `Number.isNaN` does not coerce where `isNaN` does, but the value is always the number `parseFloat` returned, so the two agree. Re-proved in Chromium: the original `aiSort` and this one, seven clicks on the same table, identical row order, `aria-sort` and indicators. Every other line 0.6.1 added to a template was checked for `parseFloat`, `parseInt`, `isNaN` and `isFinite`; these were the only two. | Then the rule also wants `Number.POSITIVE_INFINITY` for `Infinity`, which it does not describe. |

### 0.6.2 outcome

● **Every gate passed, Code Quality included, and the app deployed.** The
  two S7773 issues were the last, and nothing new was raised on the lines
  0.6.2 changed.

## 0.6.3

The first release after deployment, from operator use. With UDL connected and
the HRR list refreshed, the threat sweep's red card showed SY-12 02 at an
epoch of 15 October on 28 October, with no sign of its age.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **HYGIENE** | None made for the gate. New code: the newest-epoch fetch, the connect-time refresh (`spectre/web/elsets.py`), element set ages on the red card and in the sweep, and corrected tooltips and comments | Written against what the gate reported in 0.6.0 to 0.6.2: no nested conditionals, `Annotated` dependencies on every route touched, no new literal repeated three times in a file, complexity 840 functions and 0 over 15, no Jinja comment inside a tag, and `aria-live` rather than `role="status"`, which has a native element (`<output>`) and so is the kind of role S6819 refuses. | Then the window caught a rule the local proxies cannot run, as S7773 did at 0.6.1, and the report names the line. |
| Other gates | **HYGIENE** | None | No dependency, Dockerfile or image change. | n/a. |

**The defect, measured.** `fetch_tle_for_satno` asked `/elset/current`, which
answers with one current element set per source and in no order, and kept the
first record. Reproduced: offered a 28 October set behind a lagging 15 October
one, it returned 15 October. `_select_latest_elset` existed for exactly this,
with a comment saying so, and only the TLE panel used it. Every red track
added with "→ Red", every sweep target fetch and every screen went through the
other path. Nothing refreshed a held set either: once a session held a REAL
set it was never fetched again.

**The tooltip and comment audit.** 180 tooltips across 38 templates and every
comment in `spectre/` and `tle_clustering/` were checked against the code and
`docs/DELTA-V-RESEARCH-ASSIMILATION.md`. About 60 corrections, chief among
them: 170 m/s is Table 4's worked example of a 90° GEO relocation in 3 days,
not the largest manoeuvre on record (the largest observed is the SJ-21 tow,
about 120 m/s round trip); the Max ΔV field is a sweep budget, not an alert
threshold (R7); and the detection-floor narrative's "355,000 collision
avoidance manoeuvres in twelve months", which the source does not support, is
its 207,152 in six months. The 300 km graveyard raise reference event carried
9 m/s against the cited 11. Not verified: the "62 degree GEO relocation over
30 days, about 11 m/s" attributed to Table 4 in `monte_carlo.py`, which the
assimilation doc gives only as the observed Luch/Olymp-K 2 move; it needs the
Space Watch report itself.

### 0.6.3 outcome

● **Code Quality failed on 10 new issues, all on lines 0.6.3 touched and
  none in its new logic.** 9 were Web:InputWithoutLabelCheck: the tooltip
  corrections rewrote `title` attributes on fields that had a placeholder
  and no label, which put them in the new-code window. The tenth was
  Web:S6819 on the training banner's `role="status"`, which predates 0.6.3;
  correcting its `aria-label` brought it in. The 0.6.3 entry checked the
  lines it added for `role="status"` and not the attributes beside the
  lines it edited.

## 0.6.4

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality: Web:InputWithoutLabelCheck (9) | **EVIDENCED** | Each field named gets an `id` and a `<label for>`, hidden on screen (`.visually-hidden`) where the layout already shows its purpose: the red and blue SATNO boxes, the HRR search, the data mode and TLE source selects, both UDL login forms, and the TLE name and text fields | All 9 lines named by the gate. The TLE fields are included in the red and the blue form, so their ids carry the side (`red-tle-name`, `blue-tle-name`), set by the include and, on a fetch, from the `HX-Target` header. The 0.6.3 report did not flag the Max ΔV inputs it also touched, which sit inside a `<label>`, so a wrapping label passes too. The two remaining unwrapped fields on the page, the theme picker and the catalog search, are labelled as well. `tests/integration/test_form_labels.py` renders the page before and after UDL connects and finds no field without a label and no id twice. | Then the rule wants the label visible, which it does not describe; the fix is the same markup without the class. |
| Code Quality: Web:S6819 (1) | **EVIDENCED** | The training banner's `role="status"` becomes `role="note"` | The line named by the gate. The banner is rendered once with the page and never updates, so it is not a live region; `role="note"` passed the 0.6.0 to 0.6.3 scans elsewhere. | Then the rule refuses `note` too, and the banner drops the role and keeps its `aria-label`. |
| Other gates | **HYGIENE** | None | Templates, one CSS class and one route helper. No dependency, Dockerfile or image change. | n/a. |

**Found on the way.** On a full page load with UDL connected, the status
partial also rendered its out-of-band TLE source panel, so the page held
`#tle-source-panel` twice and a stray source dropdown inside the UDL menu.
It now renders only on the login response that needs it.

### 0.6.4 outcome

● **Every gate passed, Code Quality included, and the app deployed.** The
  10 issues from 0.6.3 cleared and none were raised on the lines 0.6.4
  changed.

## 0.6.5

From operator use of 0.6.4. With UDL connected and the refresh run, the
threat sweep's red card showed TJS-3 (43874) with a set from 25 October, 3
days old and flagged STALE, while commercial providers had filed sets for it
that day.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **HYGIENE** | None made for the gate. New code: the archive-first newest-set fetch with an SGP4-only filter, the provider on the red card and in the sweep, source discovery from the archive, and the SGP4-XP roadmap section | Written against what the gate reported in 0.6.0 to 0.6.4: no form field without a label, no `role="status"`, no Jinja comment inside a tag, no new literal repeated three times in a file (the epoch filter is one helper), `Annotated` form parameters, and no touched function over complexity 15. | Then the report names the line. |
| Other gates | **HYGIENE** | None | No dependency, Dockerfile or image change. | n/a. |

**The defect, measured against the spec.** UDL's own description of
`/elset/current` (in `docs/openapi.json`): "Current elsets are tracked by
source ... If source is not provided, it will be defaulted to '18th SPCS'."
Every "latest" fetch asked it without a source, so every red track, target,
screen, manoeuvre and refresh received the 18th SPCS set and nothing newer
from any other provider. The archive (`/elset`) was used only for clustering.

**0.6.3 was wrong about this, in part.** Its entry said `/elset/current`
answers with one current set per source in no order, and its fix chose the
newest of the records returned. Without a source there is one record, so
that fix had nothing to choose between; its test offered two sources, which
the live endpoint does not. The connect-time refresh did work, and is why
the card showed 3 days rather than 13.

**What changed.** The archive over the last 72 hours (the longest staleness
limit, so anything older is STALE in every regime) is asked first, across
every provider or the one chosen in TLE Source, and the newest usable set
wins; the current catalogue answers only when the window is empty. Usable
means both lines, not uncorrelated (`uct`), and ephemType 0: the `sgp4`
package reads an SGP4-XP set (type 4) without complaint and propagates it
wrongly. Each skipped set is logged by type and provider, which is the
measurement the SGP4-XP roadmap item starts from. The owner's UDL element
set chart for the day confirms the shape of the defect: 18th SPCS filed
heavily until about midnight and almost nothing after, while EXO, KBR, KRTL,
LeoLabs and NorthStar filed throughout, and it confirms "18th SPCS" as the
source name. Not verified against live UDL from here: which of those file
for TJS-3, and in which ephemType.

**Gate preparation.** Two literals this change took to three or more uses in
`udl.py` (the UDL timestamp format and the `/elset` path) are now module
constants. `'epoch'` was already at 12 uses on master and through five
gates, so its two new uses add to an existing issue rather than create one.
Coverage of the changed executable lines: 107 of 113 (94.7%).

**Gate tooling added with 0.6.5.** Every Code Quality rule the gate has
raised here is now a check in `scripts/sonar_rules.py`, run by
`scripts/check-quality.sh` (so in CI) and by the packager, which refuses to
build on a failure. Replayed on each release against its predecessor, it
reports exactly the lines the gate reported for 0.6.1 (2) and 0.6.3 (10),
nothing for 0.6.2, 0.6.4 and 0.6.5 as shipped, and the one issue fixed by
hand before 0.6.5 shipped. The rules, their evidence and that table are in
`docs/SONAR-RULES.md`. Run over every line, it finds 209 latent issues that
count the day their line is edited. The `code-quality-preflight` agent and
the `/release-preflight` command cover what a script cannot judge, and
`CLAUDE.md` carries the rules to the point where code is written. Both
`scripts/check-quality.sh` and the checker now use `origin/master` when the
local master is behind it: a stale local base turned 0 findings into 14.

### 0.6.5 outcome

● **Every gate passed first time, Code Quality included, and the app
  deployed.** The two literals hoisted before submission were the only
  findings the local checks raised.

## 0.6.6

A cleanup release, at the owner's direction: clear every latent issue
`scripts/sonar_rules.py --all` reported, so that no future edit inherits one.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **HYGIENE** | 153 latent issues cleared, of 14 rules the gate has raised here; 56 more in vendored minified libraries left untouched and taken out of scope | The checker reports 0 blocking over every line of `spectre/` and `tle_clustering/`, and a test now holds that. The 94 `Annotated` conversions changed no binding: the OpenAPI schema and every route's dependency tree were dumped before and after and are identical. The JavaScript changes are exact equivalents (each `isNaN` takes a `parseFloat` result; each `dataset` read is used only with `||` or `getElementById`), and a Chromium probe drove the out-of-band select swap, the theme switch and the panel tabs. | Then the gate raised a rule on a touched line that no check covers: this release touched several hundred old lines, the widest window yet. The `code-quality-preflight` agent reviewed them; its findings are recorded below. |
| Other gates | **HYGIENE** | None | No dependency, Dockerfile or image change. | n/a. |

**Not cleared, by decision.** 11 f-string fragments used three or more times
in a file still warn. Whether the gate counts fragments is UNKNOWN, and
restructuring messages on a guess would widen the window further.

**Coverage, found before submission.** The local gate measured changed-line
coverage against master and read 82%. Against 0.6.5, the release the gate
will score this one against, it was 68%, under the floor of 80: moving noqa
rationales and hoisting literals had marked 18 never-tested error branches as
changed code. `tests/integration/test_untested_failure_paths.py` covers each
(an admin acting on a deleted user, UDL failing mid-fetch, a mistyped
refuelling date, an empty sweep group), and coverage against 0.6.5 is now
100%. The release command, the agent and `CLAUDE.md` now name the last
scored release as the base rather than master.

**The review agent's findings.** The `code-quality-preflight` agent read
every touched line against the gate's wider rule set, with ESLint and
eslint-plugin-sonarjs calibrated by replaying 0.6.1 (it reproduced the gate's
2 lines exactly). One finding: the `dataset` change to `base.html` line 13
brought its `indexOf(t)!==-1` into scope, which SonarJS's S7765 would raise if
the gate runs it (UNKNOWN). It is now `includes(t)`, an exact equivalent for
the string it tests. Nothing else on a touched line would be raised: unused
`_rl` parameters passed in 0.6.1 on the same shape, and no hotspot is new.
`childSort` sits at cognitive complexity 15, the limit; both are on the watch
list in `docs/SONAR-RULES.md`.

### 0.6.6 outcome

● Not yet known when 0.6.7 was built: 0.6.6 had not been reported back
  from the App Store. If 0.6.6 is not submitted, 0.6.7 carries it, and the
  gate scores both against 0.6.5.

## 0.6.7

From operator review of the 0.6.6 threat sweep, which listed plane changes
"at perigee", "at apogee" and "now", each about 89 m/s and graded ANNOYANCE.
The owner's objection, that no satellite would fly a plane change at an
apsis for that effect, was right, for a reason deeper than the labels.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **HYGIENE** | None made for the gate. New code: the sweep's close-approach rule, real burn times and places, honest miss distances for plane change, phasing and the hops | `scripts/sonar_rules.py` reports nothing on the changed lines, against 0.6.6 or 0.6.5; changed-line coverage is 100% against either. | Then the report names the line. |
| Other gates | **HYGIENE** | None | No dependency, Dockerfile or image change. | n/a. |

**What was wrong, measured.** The GEO pair from the test suite, with the
target tilted 1.66 degrees (the angle 89 m/s buys at 3.074 km/s):

● The plane change waited, correctly, for the next crossing of the target's
  plane, the only place a single burn can rotate one plane into another, but
  the row kept the search point's name and time: "now 22:00" for a burn at
  09:54 the next morning. "now" and "perigee" were the same burn, listed twice.
● Its miss was hard-coded to 0 km. Coplanar, the red object stayed 610 km
  from the target, because aligning planes does nothing to the along-track gap.
● No method's result was checked for arrival. A 0 m/s Hohmann ending 607 km
  away was ranked a benign approach. Phasing reported only the radial gap
  (0.3 km against a real 18 km). The H-bar and V-bar hops reported their total
  travel as their miss, so an H-bar sequence read 3 km from a target it left
  600 km away along-track. The Intercept Engine showed the same figures as
  "Miss Dist".

**What changed.** A result is listed only if it ends within 50 km of the
target (an ASSUMPTION stated on the page for the analyst to confirm);
anything further is listed among the methods that produced no approach, with
the distance. Rows give the burn's real time, and `rel_node` where a plane
change has to wait for the node; one row per distinct burn. The plane change
reports its closest approach over the next revolution, phasing its simulated
arrival miss, and the hops what their own axis leaves uncovered.

**Not fixed, recorded.** The hop solvers record 2 burns for a sequence of
n hops (2 per hop), so their burn list cannot be replayed; their miss now
comes from their own linear model (INFERENCE, reasonable while the separation
is small against the orbit radius, about 1.4% at 600 km in GEO). Pricing a
plane change together with the phasing that closes the gap is not done: a
plane change on its own is now refused, with the distance it leaves.

**The review agent's findings.** Two, both acted on before packaging. The
NaN-safe test `if not miss <= limit` is the shape `python:S1940` raises; it
is now `math.isnan(miss) or miss > limit`. A tooltip added to the sweep's
Location header put the whole `<th onclick tabindex onkeydown>` in the
window, a shape not scored since 0.6.0; the tooltip is gone and its text is in
the sweep note instead. The local gate also caught a moved line carrying a
bare `1e-10`; it uses `_DEGENERATE_ANGULAR_MOMENTUM` now. Both rules are on
the watch list in `docs/SONAR-RULES.md`.

### 0.6.7 outcome

● Not yet known when 0.6.8 was built.

## 0.6.8

From operator use of asset screening. An AEHF-1 screen named a CZ-3B rocket
body its most dangerous actor, with a Fengyun 2C apogee kick motor and
payloads launched twenty years ago ranked beside it. The owner: keep the list
to payloads with capability, which means dropping the really old ones too.

| Gate | Class | Change | Evidence | If it still fails |
|---|---|---|---|---|
| Code Quality | **HYGIENE** | None made for the gate. New code: `spectre/domain/actor_eligibility.py` and the screen's candidate filter | `scripts/sonar_rules.py` reports nothing on the changed lines; changed-line coverage measured below. | Then the report names the line. |
| Other gates | **HYGIENE** | None | No dependency, Dockerfile or image change. | n/a. |

**What changed.** Candidates were every red-country object on the HRR
watchlist in a compatible regime. Now only payloads that can act are
screened. Rocket bodies, debris and decayed objects are left out, by the UDL
on-orbit catalogue's `objectType` and `category` (already downloaded at
login, never read by the screen) or, before it loads, by name (R/B, AKM, PKM,
DEB). Payloads launched more than 15 years ago are left out as past their
working life, by the catalogue's launch date or the TLE's international
designator; 15 years is an ASSUMPTION stated on the page, the design life of a
GEO communications satellite. An intelligence record holding an object as
Operational or Degraded keeps it whatever the catalogue or its age says. The
screen names everything it left out and why.

**Deliberately kept.** A young payload nothing has assessed, such as "Object
A (possible TJS-26A)", is still screened: an unknown new object is the one
most worth looking at. Screening ranks those by geometry and delta-V, with
capability shown as UNASSESSED, as before.
