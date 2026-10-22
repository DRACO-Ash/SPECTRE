# Dependency Scanning: closed

**For the platform team.** Paste-ready. Twelve submissions failed this stage
with an identical signature. It is root-caused, fixed on our side, and
reproduced outside the platform. Nothing is outstanding from you to unblock us.
Two improvements below would have saved all twelve cycles and are worth making
for the next team.

## What it was

The analyser runs **Python 3.11**. Our lock file was compiled for 3.12 and
pinned two packages that refuse 3.11, so dependency resolution failed before
any advisory was looked up.

`dependency-scan-python` is GitLab's `gemnasium-python`, public source at
`gitlab.com/gitlab-org/security-products/analyzers/gemnasium`, tag `v6.6.3`,
the exact version in the job log.

● `build/gemnasium-python/debian/Dockerfile` line 1: `ARG DS_PYTHON_VERSION=3.11`.
● `builder/pip/pip.go` runs `pip download --disable-pip-version-check --dest
  ./dist -r requirements.txt` as the first action on any pip project, and logs
  pip's output with `log.Debugf`.

`numpy==2.5.2` and `scipy==1.18.1` both declare `Requires-Python >= 3.12`, so
pip exited 1. Because the output is DEBUG-level, the job showed a bare
`exit status 1` and nothing else.

## Reproduced

```
$ pip download --disable-pip-version-check --python-version 3.11 \
      --only-binary=:all: --dest ./dist -r requirements.txt
ERROR: Could not find a version that satisfies the requirement numpy==2.5.2
ERROR: No matching distribution found for numpy==2.5.2
real    0m3.423s
```

The failing job ran 3.5 seconds, 06:39:23.7 to 06:39:27.2. The recompiled lock
exits 0 in 13 seconds.

## Fixed on our side

All lock files are now compiled with `uv pip compile --python-version 3.11`.
The application still targets 3.12; a set resolved for 3.11 installs cleanly on
a newer interpreter and the generated hashes cover every wheel. Three guards
keep it there: the lock script, a floor measurement that now fails above 3.11,
and a contract test on the lock header.

## Two things worth changing, for the next team

1. **The verdict text.** "Vulnerable dependencies found. Update the flagged
   dependencies to versions without known vulnerabilities" is shown when the
   analyser exits non-zero, including when it produced no SBOM and no report
   and therefore flagged nothing. It sent this submission hunting a
   non-existent CVE across twelve cycles. "Dependency scan failed to complete"
   would have been accurate, and would have cost us one.
2. **`SECURE_LOG_LEVEL: debug`.** One variable on the deployment repository's
   pipeline. pip's own error is written at DEBUG and discarded at the default
   level, so a resolution failure is indistinguishable from a silent crash.
   Setting it by default on a FAILED dependency-scan job would surface the
   cause on the first run.

A third, optional: the analyser's interpreter is not stated anywhere a
submitting team can see. Publishing "Dependency Scanning resolves on Python
3.11" in the App Store documentation would let any Python app check its own
manifest in one command before uploading.
