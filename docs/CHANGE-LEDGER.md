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
