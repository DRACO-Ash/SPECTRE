# Dependency Scanning: diagnosis and evidence

**Status:** the SPECTRE dependency tree is clean. The App Store's Dependency
Scanning stage fails for a reason unrelated to any vulnerable package.

This note exists so the finding can be handed to the platform team without
re-deriving it.

## What the platform reports

The stage fails with **"Vulnerable dependencies found"** and no findings are
listed. The job log from the first such failure showed:

```
exit status 1
WARNING: gl-dependency-scanning-report.json: no matching files.
ERROR: No files to upload
```

A scan that finds vulnerabilities writes a report naming them. This job exits
non-zero and writes no report at all. The platform's user interface maps a
non-zero exit to "Vulnerable dependencies found", so a **crashed scan is
presented as a finding**. That mapping has already misled this submission
twice.

## Root cause

The Python analyser runs `pip download` against the manifest to build a
dependency graph before it can analyse anything. That step needs an interpreter
new enough to resolve the pinned versions.

SPECTRE targets Python 3.12 (`requires-python = ">=3.12"`,
`python:3.12-slim-bookworm` base image). Its pins resolve only on 3.12 and
above:

| Interpreter | `pip download -r requirements.txt` |
|---|---|
| 3.9  | fails - `annotated-types==0.8.0` unavailable |
| 3.10 | fails - `numpy==2.5.2` unavailable |
| 3.11 | fails - `numpy==2.5.2` unavailable |
| 3.12 | **resolves, 54 wheels** |
| 3.13 | **resolves, 54 wheels** |
| 3.14 | **resolves, 54 wheels** |

Reproduce with `scripts/audit-dependencies.sh`, step 3.

If the analyser image runs an interpreter older than 3.12, resolution fails,
the job exits 1, and no report is produced. That matches every symptom
observed, and it explains why the stage has never passed across four
submissions while every other stage, including Container Scan, passes.

## Evidence the tree is clean

Checked against the scanner's own advisory database, not just our own tooling:

● **GitLab `gemnasium-db`**, cloned directly and matched offline against every
  pinned version, with OR-aware range parsing.
  ● 54 packages in `requirements.txt`: 24 have advisory files, 94 advisories
    examined, **0 affected**.
  ● 43 further development-only packages: 54 advisories examined,
    **0 affected**.
● **pip-audit** against `requirements.txt`, `requirements.lock` and full
  `pyproject.toml` resolution: **no known vulnerabilities** in all three.
● **Vendored JavaScript** (no manifest, so fingerprinted by hand):
  htmx 1.9.12, Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.js 2.0.7.
  The only advisory on file for any of them is CVE-2020-7746 against
  Chart.js `<2.9.4`; we ship 4.4.7.
● A CycloneDX SBOM is produced by `scripts/audit-dependencies.sh` and shipped
  in the submission package.

## What the platform team can do

Run the Python dependency-scanning analyser on **Python 3.12 or newer**. On a
standard GitLab template that is the `DS_PYTHON_VERSION` variable, or the
correspondingly tagged analyser image.

## What we are deliberately not doing

Downgrading `numpy`, `pandas`, `scipy` and `scikit-learn` to versions an older
interpreter can resolve would make the stage pass. It is the wrong trade: it
ships knowingly older libraries, which increases vulnerability exposure over
time, to satisfy a scanner that exists to reduce it.

Pinning per-interpreter with environment markers would also make the stage
pass, and is worse: the scanner would then audit versions we do not ship and
report a clean result for a build that never runs. A visible failure beats a
silent false pass.
