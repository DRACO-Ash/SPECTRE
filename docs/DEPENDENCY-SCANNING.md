# Dependency Scanning: elimination record and escalation

**There are no vulnerable dependencies.** The analyser crashes before it
produces a report. Six submissions have now failed with six different root
layouts and the same three-line log.

## What the platform shows, every time

```
[INFO] [dependency-scan-python] analyzer v6.6.1
[INFO] [dependency-scan-python] Detected supported dependency files in '.'.
exit status 1
WARNING: **/gl-sbom-*.cdx.json: no matching files.
WARNING: gl-dependency-scanning-report.json: no matching files.
```

Three to seven seconds, no error text, no report, no Software Bill of
Materials (SBOM). A scan that finds vulnerabilities writes a report naming
them. The platform maps a non-zero exit to "Vulnerable dependencies found", so
a crashed scan is presented to the submitter as a finding.

## Eliminated, with evidence

| # | Hypothesis | How it was ruled out |
|---|---|---|
| 1 | Vulnerable package | `gemnasium-db`, the scanner's own advisory database, cloned and matched offline against every pinned version: 54 runtime and test packages (94 advisories) and 43 development-only packages (54 advisories), **0 affected**. `pip-audit` clean against every manifest and against full `pyproject.toml` resolution. |
| 2 | Vendored JavaScript | htmx 1.9.12, Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.js 2.0.7 fingerprinted by hand. Only advisory on file is CVE-2020-7746 against Chart.js `<2.9.4`; we ship 4.4.7. |
| 3 | Stray manifest in a subdirectory | `spectre/app_logging/setup.py` removed in 0.4.2. Detection moved to `.`; the stage still failed. |
| 4 | `requirements.txt` not a pip-compile lockfile | Fixed in 0.4.5. The upstream analyser, built from source, goes from exit 1 to exit 0 and a 54-component SBOM on exactly this change. The platform still failed. |
| 5 | Analyser on an older Python | Disproven by the platform's own Test log: Python 3.12.14, every wheel resolved. The scan job also exits in three seconds, far too fast to have attempted a download. |
| 6 | `pyproject.toml` at the root | Removed from the package in 0.4.7. Still failed. |
| 7 | `requirements.lock` at the root | Removed in 0.4.8. The package now contains exactly one manifest-shaped file at any depth. Still failed. |
| 8 | Analyser needs network | Upstream builds the SBOM with all egress blocked. Not required. |

## What the evidence points at

The first failure was on `spectre/app_logging`, a directory whose only file was
`setup.py`, with no requirements file and no pyproject in it. Every layout
since has failed too, including one with a single, hash-pinned, correctly
headed `requirements.txt` and nothing else.

Six distinct inputs, one outcome. That is the signature of a failure that does
not depend on our content.

The analyser is also a fork. Its line `Dependency files detected in this
directory will be processed. Dependency files in other directories will be
skipped.` appears in no public GitLab analyser, and no public analyser image
carries a v6 tag. `registry.gitlab.com/security-products/dependency-scan-python`
returns 403 to an anonymous pull that succeeds for public control images. So it
cannot be reproduced outside the platform.

## The ask

One of these ends it:

1. **Re-run the job with `SECURE_LOG_LEVEL=debug`.** GitLab secure analysers
   honour it and upstream prints the failing step, the file, and the reason.
2. **Send the raw job stderr.** The analyser writes a fatal message on failure;
   the interface is replacing it with "Vulnerable dependencies found".
3. **Share the analyser image**, or confirm whether it can scan any Python
   project on this instance today.

## Separately, worth fixing on the platform

Mapping "analyser exited non-zero" to "Vulnerable dependencies found" is
actively misleading. It has sent this submission hunting a CVE that provably
does not exist across six cycles. "Dependency scan failed to complete" would
have been accurate and would have saved all of them.

## Verification available locally

`scripts/verify-dependency-scan.sh` builds the upstream analyser and runs it
against a built package. On the current package it exits 0 and writes
`gl-sbom-pypi-pip.cdx.json` with 54 components and a 22-entry dependency graph.
The packager runs it on every build and refuses to ship a package it rejects.
