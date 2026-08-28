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
