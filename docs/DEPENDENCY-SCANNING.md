# Dependency Scanning: the gate contract

**There are no vulnerable dependencies.** Every failed run crashed before it
produced a report. This file records what the package now does about that, and
corrects two things earlier revisions of it got wrong.

## The contract

Shipped shape, derived from applications that clear this gate:

| File | Role |
|---|---|
| `pyproject.toml` | **Required.** `[project]` table, and deliberately **no** `[project.dependencies]`. A non-Poetry pyproject is a resolution trigger; one carrying only `[build-system]` is skipped with a warning and buys nothing. |
| `requirements.in` | Input. Drives resolution; not itself scanned. |
| `requirements.txt` | The scanned lockfile, and what the platform Test stage installs. Runtime plus test, hash-locked. |
| `requirements-runtime.in` | Runtime-only input. |
| `requirements-runtime.txt` | What the image installs. **Not** a filename the analyser reads. |
| `requirements-dev.txt` | Lint and SAST tooling. Repository only; never shipped, never scanned. |
| `Dockerfile` | Root level. A nested one breaks template detection. |

All three `.txt` files are produced by `scripts/lock.sh`, which runs
`uv pip compile --python-version 3.12 --generate-hashes`. The interpreter
version is not optional: a lock compiled for a different one resolves a
different set. 3.12 matches `requires-python` in `pyproject.toml` and the
`python:3.12-slim-bookworm` base image, and a contract test asserts those two
agree.

`requirements-runtime.txt` being invisible to the scanner is deliberate and has
a consequence: the gate reads the **superset**, so it scans at least what the
image ships. That only stays safe while the runtime set is a strict,
version-identical subset. `scripts/check-quality.sh` and
`TestPipCompileLockContract` both assert it; the platform does not.

Collapsing the split would drag the whole test toolchain into the runtime image
and count it against Container Scan.

## Two corrections

**The lockfile header was not the cause.** An earlier revision of this document
concluded that `requirements.txt` had to carry the pip-compile header on line 2,
and 0.4.5 changed it on that basis. Three header forms are known across three
packages: a hand-written banner passes, a uv header passes, and a valid
pip-compile header failed. The diagnosis was read off a different codebase and
does not transfer. The header is still correct to have; it is not what the gate
decides on.

**Removing `pyproject.toml` was backwards.** 0.4.7 dropped it to reduce
ambiguity. It is in fact the single highest-value file to keep: the only root
file present in both known-passing packages and absent from the known failure.
It is restored, in the minimal form above.

**And the local analyser is not a pre-flight check.** `scripts/verify-dependency-scan.sh`
builds the open-source GitLab analyser. Calibrated against three control
samples it disagreed with the gate on two, including calling a passing package
a failure. It is kept for reading the parse warnings the platform swallows, it
can no longer fail a build, and its header carries the calibration table.
`scripts/preflight-gate.py` is the check that decides whether to ship.

## Evidence the tree is clean

● `gemnasium-db`, the scanner's own advisory database, cloned and matched
  offline against every pinned version: 97 packages, 148 advisories, **0
  affected**.
● `pip-audit` clean against `requirements.txt`, `requirements-runtime.txt` and
  `requirements-dev.txt`.
● Vendored JavaScript fingerprinted by hand, since it ships without a manifest:
  htmx 1.9.12, Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.js 2.0.7. The
  only advisory on file for any of them is CVE-2020-7746 against Chart.js
  `<2.9.4`; we ship 4.4.7.

## Root cause, found 22 October 2026

**The analyser runs Python 3.11. Our lock pinned packages that refuse it.**

`dependency-scan-python` is GitLab's `gemnasium-python`, and the source is
public at `gitlab.com/gitlab-org/security-products/analyzers/gemnasium`. Tag
`v6.6.3` is the exact version the gate reports. Two files decide everything.

`build/gemnasium-python/debian/Dockerfile`, line 1:

```
ARG DS_PYTHON_VERSION=3.11
```

`builder/pip/pip.go`, the first thing that happens to any pip project:

```go
cmd := exec.Command(pathPip, "download", "--disable-pip-version-check",
                    "--dest", b.CacheDir, "-r", file)
output, err := cmd.CombinedOutput()
log.Debugf("%s\n%s", cmd.String(), output)
if err != nil {
    return err
}
```

Two consequences, and together they are the whole twelve-cycle story.

1. The manifest has to RESOLVE on Python 3.11 before a single advisory is
   looked up. Our lock was compiled for 3.12 and pinned `numpy==2.5.2` and
   `scipy==1.18.1`. Both declare `Requires-Python >= 3.12`, so pip could not
   satisfy either and exited 1.
2. pip's output is written with `log.Debugf`. At the default log level the job
   therefore shows a bare `exit status 1` and nothing else. That is why nobody
   ever saw an error: there was never one to see without `SECURE_LOG_LEVEL`.

Reproduced against the 0.5.22 package:

```
$ pip download --disable-pip-version-check --python-version 3.11 \
      --only-binary=:all: --dest ./dist -r requirements.txt
ERROR: Could not find a version that satisfies the requirement numpy==2.5.2
ERROR: No matching distribution found for numpy==2.5.2
real    0m3.423s
```

The failing job ran for 3.5 seconds (06:39:23.7 to 06:39:27.2). The same
command against the recompiled lock exits 0 in 13 seconds.

## The fix

`scripts/lock.sh` now compiles for **3.11, the scanner's interpreter**, not for
3.12. The application still runs on 3.12: a set resolved for 3.11 installs
cleanly on a newer interpreter, and `--generate-hashes` emits every wheel's
hash for each pinned version, the cp312 ones included. Verified with the
image's own flags, `pip install --require-hashes --only-binary=:all:`, on 3.12.

The change is three pins:

| | was | now |
|---|---|---|
| numpy | 2.5.2 | 2.4.6 |
| scipy | 1.18.1 | 1.17.1 |
| certifi | 2026.7.22 | 2026.10.19 (Container Scan fix, unrelated) |

`requires-python` in `pyproject.toml` stays at **3.12** and the base image stays
`python:3.12-slim-bookworm`. Those describe where the application runs. The
lock describes what the scanner must be able to resolve, and the two are
allowed to differ as long as the lock's floor is the lower of the pair.

## What stops it recurring

● `scripts/lock.sh` defaults to 3.11 and says why.
● `scripts/audit-dependencies.sh` measures the real floor against the index and
  now FAILS when it lands above 3.11, instead of printing it.
● `scripts/preflight-gate.py` blocks when a shipped lock's header names a newer
  interpreter.
● `TestScannerInterpreterContract` asserts the header offline, and travels
  inside the package.

The exposure is now explicit: every dependency bump has to keep the whole set
installable on Python 3.11 until the platform moves its analyser. Three of the
four guards above are offline, so the cost is one line in a lock header.

## What was eliminated along the way, and was never the cause

Each of these cost a submission and is recorded so nobody pays for it twice:
the pip-compile header form, the presence or absence of `pyproject.toml`, the
manifest count at the package root, stray manifests at depth, vendored
JavaScript, vulnerable packages (`gemnasium-db` matched offline: 97 packages,
148 advisories, 0 affected), and a package no standard Python tool could build.
None of them mattered. The interpreter did.

## A platform defect still worth raising

Mapping "analyser exited non-zero" to **"Vulnerable dependencies found. Update
the flagged dependencies to versions without known vulnerabilities"** is
misleading when no dependency was flagged and no report exists. It sent this
submission hunting a non-existent CVE across twelve cycles. "Dependency scan
failed to complete" would have been accurate.

The second ask is cheaper still: `SECURE_LOG_LEVEL: debug` on the deployment
repository's pipeline would have surfaced pip's own error on the first run.
