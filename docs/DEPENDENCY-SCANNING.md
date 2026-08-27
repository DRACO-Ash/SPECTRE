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

## Still unknown

The analyser's real error text. Nobody has seen it. `dependency-scan-python`
v6.6.1 is not a public image, so it cannot be reproduced outside the platform.
Until someone reads that text, every explanation here is reasoning from the
outside.

Ask for `SECURE_LOG_LEVEL: debug` on the deployment repository's pipeline, or
the raw job stderr. On the current analyser lineage the `.pre` resolution job
runs with `allow_failure: true`, so a resolution failure is silent unless
someone opens that job's log specifically.

If you are the person who finally sees the error, put it in this file. That one
paragraph would be worth more than the rest of it.
