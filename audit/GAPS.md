# SPECTRE audit: gaps (phase 8.5)

What this audit did not examine, what it could not verify, and what a human has to decide. Nothing on this list was declared clean.

## 1. Decisions only a human can make

1. **Committed operational data, `spectre/data/notso_cache.json` (F-S07-05, High).** Fact: 500 records, every one `dataMode` REAL and every one marked `U//DS-JCO-NOTIF`. The file has been tracked since at least commit `d43e3d2` (8 April 2026). It ships in the container image (`Dockerfile:77` copies all of `spectre/`) and any logged-in operator can read it. Refuter R4a also found 6 records in the committed intel data citing "JCO Threat List". The audit does not interpret the dissemination control. Someone with handling authority must decide:
   ● whether that marking permits this data in a source repository, on the GitHub remote, in CI logs and artefacts, and in an App Store image;
   ● whether the git history needs a purge;
   ● whether the event is reportable under the organisation's information-security process.
   No record contents were copied into any audit artefact.
2. **The Decision Engine.** The "Robust Recommendation" is built on hard-coded constants (F-S05-02). Its selectors are mislabelled (F-S05-01) or recommend NO_ACTION against a manoeuvre that loses custody (F-S05-03). Whether to label it as a modelled estimate, restrict it to training, or withdraw it from operational use is a product and safety call. It is not a code fix.
3. **The threat model for UDL- and HRR-sourced names.** These names reach inline `onclick` JavaScript (F-S06-03, High). If a hostile or compromised upstream feed is in scope, this is Blocker class. The audit graded it High on the evidence available.
4. **Credential scope design.** UDL credentials are held per SPECTRE username, process-wide (F-S07-01). Whether the target is per browser session, encrypted in memory, or delegated to a platform secret is an architecture decision. The July 2026 audit agreed a target that has not been built.
5. **Heuristic scores in operational views.** At least ten confirmed findings are tuned-constant scores displayed as probabilities or confidences. Deciding which belong in an operator view at all, as against an analyst sandbox, is a decision for the mission owner.
6. **Standards the repository does not follow.** The required test naming convention is followed by 0 of 1,389 test functions (F-S00-15). Four LLM persona and prompt documents sit in `docs/` (F-S10-33). Each needs either adopting or a recorded waiver.

## 2. Not examined

● **Vendored JavaScript**: Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.JS 2.0.7, htmx 1.9.12. Not read line by line, and no JavaScript advisory database was reachable to check them (F-S00-13).
● **`bluestaq-foundations-v1.99.0.zip`**: only `AUDIT.md` was extracted, to settle the PRIORS provenance question. The other 73 files are unaudited.
● **`docs/SPECTRE_Operator_Guide.docx`**: a binary operator guide. Its claims about the methods were not reconciled. The generator, `docs/generate_guide.py`, was reviewed.
● **`docs/openapi.json`** (287,166 lines): not compared route by route with the live application.
● **Binary and graphic assets**: SVGs were checked for scripts and external references by slice S09, not visually.
● **The container image**: there is no Docker daemon in this environment. `Dockerfile` builds, the suid sweep, the non-root runtime and the probe contract were reviewed as text. CI's container job is green on master and is the only execution evidence (run 40020299345).
● **PostgreSQL**: the suite runs on SQLite. The asyncpg path, `sslmode` handling and pool recycling were reviewed in code only.
● **Concurrency under load**: no load test. The thread-safety findings on the shared `SessionState` and the executor rest on code reading.
● **The browser UI**: one headless Chromium check was run, by refuter R3 for F-S06-27. Everything else about rendered behaviour is inferred from templates.
● **Live UDL behaviour**: there was no network access to UDL. Pagination, ordering and response shapes were checked against the committed cache and the code only.

## 3. Not verified

● **Four candidates are UNPROVEN**, plus one raised by a refuter outside its batch. Each settling check is named in the appendix of `audit/REFUTATION.md`. Two depend on live UDL behaviour (F-S07-04 offset paging, F-S07-09 element-set ordering). One needs a real single-impulse SGP4 fixture (F-S04-14), and one is a design-intent question (F-S09-23).
● **The 15 orchestrator findings (batch R0) were not independently refuted.** Each was verified at discovery by a CI log, a mutation run, a grep or the resolver, and the opposite case was argued (one fell). A second-opinion pass is still owed.
● **The `safety` tool was unavailable** (no network route to its database). `pip-audit` is the only SCA evidence.
● **The calibration report cited by `spectre/domain/manoeuvre_calibration.py` is not in the repository.** Slice S05 checked every figure it could by hand (all within 2 %), but the table-level provenance is unverifiable here.
● **Textbook values in reviewer and refuter reasoning were partly from recall.** The quantitative Blockers were confirmed by execution, either against an independent integration or against a derived relation such as the B* factor. Other hand cases are marked as hand cases in their findings.
● **The mutation sample is small**: 22 mutants across 5 modules. It establishes that gaps exist. It does not measure them across the codebase. A full mutation run on `spectre/astro/` and the web security core is the next step.
● **Several measures are mechanical heuristics**: test classification, the "trivial assertion" flag, effort estimates and blast radius. The assertion heuristic's first pass mis-flagged 13 of 20 tests before it was corrected (`audit/TESTS.md`).
● **Platform controls are claimed but not visible in code.** These include the Keycloak single-sign-on gateway (cited at `spectre/web/_entrypoint.py:40` and `READINESS.md:167`) and the pod network policy. They are outside the repository and were not verified.
● **Two of ten slice reviewers broke the read-only tool rule** by using read-only shell commands (S08, and S10 for quote checking). Nothing was modified. This is recorded for completeness.

## 4. Scope caveats

● **Source pinned at `a34e273`.** Audit commits after that touch only `audit/`.
● **PRIORS.md is a reconstruction.** No original July 2026 audit document exists in the tree (`audit/PRIORS-STATUS.md`), so the prior verdicts are against reconstructed claims.
