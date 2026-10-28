---
description: Before an App Store package. Runs every gate check this repository can run locally, has the code-quality-preflight agent judge the rest, and builds and verifies the package only when both are clear.
allowed-tools: Read, Grep, Glob, Bash, Task
---

# RELEASE PREFLIGHT

Run this before building an App Store package. It does not submit anything:
submission is the owner's step. UK English, no em-dashes, lead with the
verdict, mark FACT, INFERENCE and UNKNOWN.

## Steps, in order; stop at the first failure and report it

1. **Version and ledger.** `spectre/__init__.py`, `pyproject.toml` and
   `sonar-project.properties` carry the same version, `CHANGELOG.md` has an
   entry for it, and `docs/CHANGE-LEDGER.md` has a `## <version>` section with
   the previous release's outcome recorded.
2. **Rules the gate has raised before.** `python3 scripts/sonar_rules.py
   <base>`, where `<base>` is the commit of the last release the gate scored
   (master once that release is merged; its branch head until then). Use the
   same base in every step below; master understates the change when the
   last release is not on it yet, and 0.6.6 read 82% coverage there against
   68% on the true base. Any FAIL stops the release; see `docs/SONAR-RULES.md` for the fix
   that passed last time.
3. **The rest of the gate, reproduced.** `pytest tests/ -q --cov
   --cov-report=xml:coverage.xml`, then `sh scripts/check-quality.sh <base>`.
4. **Judgement.** Launch the `code-quality-preflight` agent on the change. It
   reviews touched old lines, JavaScript complexity, rules not yet met here,
   security hotspots and coverage. FIX FIRST or NEW RULE SUSPECTED stops the
   release until the author has dealt with each finding.
5. **Package and verify.** `SONAR_BASE=<base> sh scripts/package-appstore.sh <out-dir>` (it
   runs step 2 again and refuses to build on a FAIL), then
   `sh scripts/simulate-pipeline.sh <zip>` and
   `sh scripts/verify-container.sh <zip>`. Behind a TLS-intercepting proxy,
   set `PROXY_CA_BUNDLE` for the last two.

## Report

The verdict (READY or BLOCKED and at which step), the zip path and SHA-256
when READY, and the agent's findings verbatim.

## After the gate answers

Record the outcome under the next version's ledger entry. If Code Quality
raised a rule `docs/SONAR-RULES.md` does not list, follow the four steps at
the end of that file before fixing the code, so the rule cannot cost a second
submission.
