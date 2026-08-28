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
