# Dependency Scanning: escalation

**For the platform team.** Paste-ready. Twelve submissions, twelve identical
failures. Confirmed from the platform side on 28 August 2026: the scanner
exits non-zero without producing `gl-dependency-scanning-report.json`, which
the platform's own assistant characterises as a scanner bug rather than a
finding against the submitted code.

## What happens

```
[INFO] [dependency-scan-python] analyzer v6.6.1
[INFO] [dependency-scan-python] Detected supported dependency files in '.'.
exit status 1
WARNING: **/gl-sbom-*.cdx.json: no matching files.
WARNING: gl-dependency-scanning-report.json: no matching files.
```

Three to eight seconds. No error text. **No SBOM and no report**, so nothing was
ever flagged: SBOM generation precedes the vulnerability lookup. The interface
renders the non-zero exit as "Vulnerable dependencies found", which is not what
happened.

Every other stage passes. 8 of 9 green on 0.5.2 and 0.5.3, including Container
Scan, which examines the built image.

## The dependency set is clean, independently established

● `gemnasium-db`, the scanner's own advisory database, cloned and matched
  offline against every pinned version: 97 packages, 148 advisories, **0
  affected**.
● `pip-audit` clean against all three lock files.
● Vendored JavaScript fingerprinted by hand: htmx 1.9.12, Chart.js 4.4.7,
  chartjs-plugin-zoom 2.0.1, Hammer.js 2.0.7. All outside every advisory on
  file.

## What we need, in order of value

1. **Re-run the job with `SECURE_LOG_LEVEL: debug`.** One variable in the
   deployment repository's pipeline file. The analyser writes a fatal message
   on failure and the interface is discarding it.
2. **The `.pre` resolution job's log.** On this analyser lineage the Python
   resolution job runs with `allow_failure: true`, so if resolution is what
   dies, the error is in that job and never appears on the Dependency Scanning
   job. Please confirm whether such a job exists in the pipeline and send its
   log. `CI_DEBUG_SERVICES: "true"` captures service container output.
3. **The `pyproject.toml` of a package that passes this gate.** A file listing
   from PSIRENS has already been supplied and acted on: submission 0.5.4 made
   our package root file-for-file identical to theirs and failed unchanged, so
   manifest count and filenames at the root are eliminated. The remaining
   structural differences are their `src/` layout and our second top-level
   package. Their `pyproject.toml` is 424 bytes and contains nothing
   confidential; it is the last cheap diagnostic left.

## If the analyser cannot be made to resolve

We can supply a CycloneDX 1.4 SBOM, generated from our hash-locked
`requirements.txt` and shipped with the submission, for upload as
`artifacts:reports:cyclonedx`. It is attached. That removes the resolver from
the critical path entirely; we own its accuracy.

Alternatively, `DS_ENABLE_MANIFEST_FALLBACK` would let the stage proceed from
the manifest. That reduces accuracy to direct dependencies only, so we would
want it recorded as a deliberate decision rather than a default.

## Eliminated, with method

Each of these was tested by a distinct submission and failed with the identical
signature, so each is ruled out rather than merely doubted:

● Vulnerable packages, by the offline `gemnasium-db` match above.
● Vendored JavaScript, fingerprinted by hand.
● Stray manifests in subdirectories, at every depth the analyser reads.
● The `pip-compile` lockfile header form, which `common.IsPipCompileLock`
  checks positionally on lines one and two.
● The analyser's Python version, and network egress from the job.
● `pyproject.toml` presence, and manifest count at the package root: 0.5.4
  matched PSIRENS exactly.
● A package no standard Python tool could build. 0.5.5 declared
  `[build-system]` and `[tool.setuptools.packages.find]`, fixing a genuine
  defect - `pip install --dry-run --no-deps .` had failed with `Multiple
  top-level packages discovered in a flat-layout` - and the gate failed
  unchanged. So the analyser does not call the PEP 517 build hook.

## A platform defect worth raising separately

Mapping "analyser exited non-zero" to **"Vulnerable dependencies found. Update
the flagged dependencies to versions without known vulnerabilities"** is
misleading when no dependency was flagged and no report exists. It has sent
this submission hunting a non-existent CVE across twelve cycles. "Dependency scan
failed to complete" would have been accurate and would have saved all of them.
