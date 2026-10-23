# Teach Bob retrospective

- Developer: Ashley Higgins
- Project: SPECTRE (Space Planning, Evaluation and Counter-Threat Response Engine)
- Date: 2026-09-09
- Scope: Bluestaq App Store readiness campaign, releases 0.4.0 to 0.5.9, 25 August to 1 September 2026
- Stack: Python 3.12, FastAPI, SQLAlchemy async, Jinja2, HTMX 1.9.12; PostgreSQL with a SQLite fallback
- Archetype: container service (operator web console)
- Duration: 8 days, 20 commits, 20 releases
- Baseline: Bluestaq Foundations bundle, with the `appstore-python-gate` skill adopted mid-window (version TBC, re-verify)

Filed under the account running the session; correct the name and re-file if that is wrong.

## Summary

Eight days took SPECTRE from a failing submission to a deployed, running App Store
application, at a cost of twenty releases. The single most important lesson is that
the campaign spent roughly twelve of those submissions chasing a vulnerability that
never existed: the Dependency Scanning analyser was crashing before it looked at
anything, and the evidence for that (no SBOM artefact, no report artefact, a three
to eight second runtime) was present in the very first failure log and was misread
as a finding for eleven more. The thing that went most wrong is that the pipeline
turned green while the software was quietly broken - the deployed image had TLE
clustering switched off in every build ever shipped, and the user management page
could not display a user it had just created. Nine passing gates found neither,
because nobody opened the application until a human did.

## What went well

● **Reproducing the failure before writing the fix, once that became the habit.**
  The database connection crash was reproduced against a real PostgreSQL instance
  by terminating the connection server-side (`scripts/verify-db-resilience.py`);
  the HTMX swap failure was reproduced in Chromium against a running instance
  before a line changed; the CSRF rejection was reproduced and then re-verified in
  the browser. Every fix that followed this pattern held first time.
● **Proving the dependency set clean by an independent route.** Cloning the
  scanner's own advisory database and matching it offline against every pinned
  version - 97 packages, 148 advisories, zero affected - converted "we think it is
  fine" into a fact, and was what made it defensible to stop looking for a CVE
  (`scripts/audit-dependencies.sh`, `docs/ESCALATION-DEPENDENCY-SCANNING.md`).
● **The change ledger.** Introduced at release 0.5.2 after the user objected to
  repeated unforced errors, it forces every change to be classified EVIDENCED,
  PROBE or HYGIENE before the packager will build, caps a submission at one probe,
  and requires each entry to state what a failure would rule out. Eight entries,
  nine evidenced changes, three probes, two recorded outcomes
  (`docs/CHANGE-LEDGER.md`, gate at `scripts/package-appstore.sh`). Both probes
  that were closed produced a definite answer rather than a shrug.
● **Deliberately measuring blast radius rather than assuming it.** When the HTMX
  swap broke, testing every path established an exact rule - every admin response
  carrying a flash message failed, every response without one worked - which made
  the fix obvious and the regression test precise.

## What did not

● **Twelve submissions on a platform defect, read as an application defect.** The
  signature never varied: two informational lines, exit status 1 in under ten
  seconds, no CycloneDX SBOM, no report. SBOM generation precedes vulnerability
  lookup, so the absence of both means the analyser never got as far as looking.
  That inference was available on day one. Instead the interface's wording,
  "Vulnerable dependencies found", was taken at face value and drove eleven
  further cycles of manifest surgery.
● **A shipped capability was dead and nothing noticed.** `.dockerignore` excluded
  `tle_clustering/` under the heading "Tests, docs and development tooling never
  ship in the runtime image", but the application imports that package at
  `spectre/astro/tle_preprocessing.py:150` inside a `try/except ImportError` that
  logs a warning and returns an empty result. Every image ever built therefore
  performed no TLE clustering, and every pipeline stage stayed green, because the
  guard was doing exactly what it was written to do (release 0.5.7 and 0.5.8).
● **Three iterations on that one defect.** It was first diagnosed as a docker-only
  packaging omission, then found to affect the python template equally, then the
  fix broke Container Build because the `COPY` was added without reading the file
  that governs the build context. Each step was published as a release.
● **The user management page was broken in a live submission.** Creating a user
  returned 200, committed the row, and then threw
  `TypeError: e.querySelectorAll is not a function` in the browser, abandoning the
  swap. It reached production because no browser was opened against this build at
  any point before a human reported it.
● **Repeated self-correction eroded trust faster than the fixes rebuilt it.** The
  user's intervention was explicit and fair: too many messages were a correction of
  the previous message. The ledger was the response, and it helped, but the pattern
  had already cost several days of goodwill.

## Improvements

● **Read the failure mode before the failure message.** For any gate failure, ask
  first what artefacts a successful run would have produced, and treat their
  absence as the primary signal. A missing report is a crash, not a finding.
● **Open the application before declaring a release ready.** A browser-driven
  smoke test of login, the operator console, the admin page and the training exit
  would have caught three of this window's four runtime defects, and takes minutes.
  Playwright and Chromium were available in the environment the whole time and
  were not used until day eight.
● **Treat any pair of files that must agree as a contract, and test it.**
  `Dockerfile` and `.dockerignore` are the instance that cost a release; the same
  applies to `pyproject.toml` against the generated `pytest.ini`, and the runtime
  lock against the scanned lock.
● **Cap the guess budget explicitly.** After two consecutive unevidenced failures
  against the same gate, stop changing code and escalate. The ledger's standing
  note now encodes this, but it arrived at submission ten rather than submission
  two.

## Optimisations

● **The offline advisory-database match should have been the first move, not the
  eighth.** It took roughly an hour and definitively cleared the entire dependency
  set. Running it on day one would have made "this is not our packages" provable
  immediately and reframed the whole investigation.
● **Building the open-source analyser locally was expensive and misleading.** It
  cost significant time, and its verdicts disagreed with the real gate on two of
  three control samples - including calling a passing package a failure. It was
  correctly demoted to advisory, but the demotion came after it had already been
  trusted.
● **Twenty releases for eight days of work is a poor ratio.** Several existed only
  to test a single guess. Batching hygiene with an evidenced change, which the
  ledger permits, would have compressed this materially without losing the
  isolation that makes a failure informative.

## Waste

● **Eleven of twelve Dependency Scanning submissions produced no information.**
  Each cost a full pipeline run and a review cycle. The earlier signal was the
  missing report artefact, visible in the first log.
● **Release 0.5.7 shipped `tests/`, `sonar-project.properties`, a generated
  `pytest.ini` and `.coveragerc`, and a `coverage.xml`, and 0.5.8 removed them
  all.** This one is defensible waste: it was a designed probe and it returned a
  clean answer (those stages are gated by template, not by input), which closed the
  question permanently. It is listed here because the cost was real and because
  the answer could not have been obtained any other way.
● **A false lead chased on a nine-line diff** in a deployment values file, flagged
  as suspicious in a log that turned out to be routine tool reformatting. Cheap,
  but it sent the user looking in the wrong repository.
● **Effort spent making the local test suite reproduce a gate that was never going
  to run.** Considerable work went into satisfying Test and Code Quality under a
  template that, as later proved, does not execute either stage.

## Missed detail

● **No interaction testing of any kind for an interface built entirely on HTMX.**
  850 test functions across 40 files, and not one of them drove a browser. The two
  UI defects found by the user were both invisible to every one of them, because
  both were failures of what the browser did with a correct 200 response.
● **Usernames are matched with exact SQL equality and never normalised.** `admin`
  and `Admin` are different accounts. Combined with a bootstrap log line that
  prints the *configured* username rather than the *existing* one, this cost the
  user an hour of lockout on a system where the credentials were correct.
● **No self-service password reset, no password policy, and no forced change on
  first login.** Acceptable for a handful of operators, but it is a gap that will
  be asked about the moment this faces a wider user base.
● **The local coverage floor is set below the standard it claims to reproduce.**
  `fail_under = 70` in `pyproject.toml` against a house standard of 80, with actual
  whole-repository coverage at 74.3 per cent (`coverage.xml`).
● **`HRR_List.json` is absent from the deployed data volume**, so the threat sweep
  silently falls back to requiring an interactive login. Logged at every boot and
  not yet actioned.

## Guards seen to fail

● **CSRF template audit** (`tests/unit/test_csrf.py::TestTemplateFormsCarryTheToken`):
  **not proved** - watched to go red by hand during the session (reinstating the
  missing field produced `training.html:131 action=/training/leave`), but that
  mutation was reverted and never committed, so nobody can re-run it. A companion
  case, `test_the_guard_can_actually_see_forms`, proves only that the scanner has
  input, not that it rejects a bad form.
● **Build-context contract** (`test_deployment_contract.py::TestBuildContextContract`):
  **not proved** - same pattern. Re-adding the exclusion was watched to fail naming
  both Dockerfiles; the failing state is not in the tree.
● **Admin response-shape tests** (`test_admin_routes.py::TestFlashResponseShape`):
  **not proved** - written after the fix and never observed red. They would have
  failed against the previous shape, but no committed case demonstrates it.
● **Clustering-travels tests** (`test_deployment_contract.py::TestClusteringPackageTravels`):
  **not proved** by a committed case, though `test_clustering_is_not_silently_disabled`
  genuinely did go red against the pre-fix Dockerfiles when written.
● **Database pool contract** (`tests/unit/test_db_pool_contract.py`): **not proved**
  by the suite. The strongest evidence in the repository is
  `scripts/verify-db-resilience.py`, which did reproduce the real crash against a
  live PostgreSQL instance - but nothing runs it, so it is documentation rather
  than a guard.
● **Change-ledger gate, manifest guards, credential-leak check and in-package suite
  run** (`scripts/package-appstore.sh`, five fail-closed branches): **not proved** -
  no test executes the packager at all. These are the guards that decide whether an
  artefact ships, and they are the least covered code in the project.
● **Preflight gate** (`scripts/preflight-gate.py`): **not proved** - runs only in
  python-template builds and is never invoked by the suite.
● **Docker-only contract** (`test_deployment_contract.py::TestDockerOnlyContract`):
  **inert in normal runs** - both cases skip unless executed from inside the
  docker-only archive, which no automated run does. Two permanent skips.

The honest summary of this section: **nothing written in this window has a
committed failing case.** Several guards were watched to fail by hand, which is
better than nothing and worse than a test. The pattern to fix is that the
mutation used to prove a guard was always reverted rather than committed as a
case.

## Where the tooling or the standard cost us

● **The platform's failure message.** Rendering "analyser exited non-zero" as
  "Vulnerable dependencies found. Update the flagged dependencies to versions
  without known vulnerabilities" when no dependency was flagged and no report
  exists is the single most expensive thing in this window. "Dependency scan failed
  to complete" would have saved eleven submissions. Raised with the platform team
  in `docs/ESCALATION-DEPENDENCY-SCANNING.md`; worth pursuing as a defect in its own
  right.
● **`sonar.sources` is not honoured by the platform's Code Quality stage.** The
  declaration scoped analysis to the application packages; the platform analysed
  every file in the archive, so build tooling was graded as application code and
  produced five findings. The workaround was to stop shipping `scripts/`, which is
  right for other reasons but was forced rather than chosen.
● **Locally reproducing a proprietary gate is a trap.** The forked analyser used by
  the platform is not publicly available, and the open-source equivalent that was
  built instead disagreed with it on two of three control samples. Confidence in a
  local reproduction of a gate you cannot obtain should start at zero.
● **Two project rules interacted badly.** `docs/` is gitignored, and the change
  ledger lives in `docs/`. The build gate that depends on the ledger therefore
  passed on one machine and would have failed everywhere else until the file was
  force-added. A gate whose input is untracked is not a gate.
● **The local quality loop is calibrated below the house standard** it exists to
  reproduce (`fail_under = 70` against 80). It reports green while sitting under
  the bar.

## Top three to carry forward

1. **Ask what a successful run would have produced, before believing what a failed
   run says it found.** A missing report artefact is a crash. This one inference,
   made on day one instead of day eight, would have removed roughly half the
   releases in this window.
2. **A green pipeline is not working software.** Nine passing gates shipped a
   capability that was switched off and an admin page that could not show a user it
   had just created. Drive the real application in a real browser before calling a
   release ready; the tooling to do it was present and unused.
3. **A guard nobody has watched fail is not a guard.** Every check written this
   window is unproved by a committed case. When a guard is written, commit the
   failing case alongside it - the mutation that proves it goes red belongs in the
   repository, not in a terminal that gets closed.
