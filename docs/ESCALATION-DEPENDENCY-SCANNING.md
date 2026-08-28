# Dependency Scanning: escalation

**For the platform team.** Paste-ready. Ten submissions, ten identical failures.

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
3. **A file listing of a package that passes this gate** (PSIRENS or
   Enlightenment). Filenames only, no contents needed. A root-level diff is the
   single highest-value diagnostic available and needs nothing confidential.

## If the analyser cannot be made to resolve

We can supply a CycloneDX 1.4 SBOM, generated from our hash-locked
`requirements.txt` and shipped with the submission, for upload as
`artifacts:reports:cyclonedx`. It is attached. That removes the resolver from
the critical path entirely; we own its accuracy.

Alternatively, `DS_ENABLE_MANIFEST_FALLBACK` would let the stage proceed from
the manifest. That reduces accuracy to direct dependencies only, so we would
want it recorded as a deliberate decision rather than a default.

## A platform defect worth raising separately

Mapping "analyser exited non-zero" to **"Vulnerable dependencies found. Update
the flagged dependencies to versions without known vulnerabilities"** is
misleading when no dependency was flagged and no report exists. It has sent
this submission hunting a non-existent CVE across ten cycles. "Dependency scan
failed to complete" would have been accurate and would have saved all of them.
