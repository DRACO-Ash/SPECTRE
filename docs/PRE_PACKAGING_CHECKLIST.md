# Pre-Packaging Checklist — App Store Deploy Contract and Intercept Fixes

**Status:** ACTIVE — work down in order. Nothing is zipped until every item below its gate is green.
**Scope:** all SPECTRE-derived artefacts (shell and apps). Items 12 to 14 are Intercept-specific code fixes.
**Sources:** `deploy-recipes` (Python recipe and Node template shape), `security-hardening` (server-side-only secrets), `appstore-gate-compliance`, `app-store-readiness`. Evidence column cites the current repo state as verified on 2026-07-18.

**How to read each item:** what to do, the platform gate that enforces it, the current state in this repo, and the owner. The five platform pipeline stages run strictly in sequence: Install and Test → Code Quality (SonarQube) → Container Build → Image Policy Scan → Deploy. An item's gate is the earliest stage that fails without it.

## Phase 1 — Test and coverage contract (gate: Install and Test, Code Quality)

**1. Raise the coverage floor from 70% to 80% everywhere it is declared.**
The platform SonarQube gate requires at least 80% line coverage; the repo currently gates at 70% in two places.
● Gate: Code Quality (SonarQube, hard server-side gate).
● Evidence: `pyproject.toml` `[tool.coverage.report] fail_under = 70`; `.github/workflows/ci.yml:48` `--cov-fail-under=70`.
● Fix: set both to 80, then close the actual coverage gap until the suite passes at 80. The platform gate wins over any local preference.
● Owner: Ash.

**2. Emit Cobertura coverage XML from the test run.**
SonarQube for Python reads `coverage.xml` (Cobertura). The current CI emits `term-missing` only, which the platform cannot read; the gate would report 0% regardless of real coverage.
● Gate: Code Quality.
● Evidence: `ci.yml:48` has no `--cov-report=xml`.
● Fix: test command becomes `pytest tests/ -m "not integration" --cov=spectre --cov-report=xml --cov-report=term-missing --cov-fail-under=80`. Add a post-step that fails if `coverage.xml` is missing or empty.
● Owner: Ash.

**3. Commit `sonar-project.properties` at the repo root.**
● Gate: Code Quality.
● Evidence: no `sonar-project.properties` exists in the repo.
● Fix: declare `sonar.sources=spectre`, `sonar.tests=tests`, `sonar.python.coverage.reportPaths=coverage.xml`, plus honest coverage-only exclusions each with a one-line written rationale (candidates: `spectre/app_logging/setup.py`, already omitted in `[tool.coverage.run]`). Adapt from `deploy-recipes/templates/sonar-project.properties` (Node shape, same fields).
● Owner: Ash.

**4. Make the offline-runner test posture explicit.**
The platform runner may have no route to UDL or any public endpoint. The `integration` pytest marker already exists for exactly this; the packaged test command must deselect it, and any skip must be loud.
● Gate: Install and Test.
● Evidence: `pyproject.toml` `[tool.pytest.ini_options]` defines the `integration` marker; `ci.yml:48` currently runs `pytest tests/` with no deselection.
● Fix: the packaged and simulated test command runs `-m "not integration"`. Audit every test for un-marked network reach (httpx calls not mocked) and either mock or mark. Any skip-when-offline prints a visible SKIPPED reason, never passes silently.
● Owner: Ash.

**5. Gate or remove environment-dependent negative assertions.**
The platform's checkout contains platform-committed extra files (its own `.gitlab-ci.yml` among them). Any "this file must not exist" assertion that is false only on the platform runner is a self-inflicted outage.
● Gate: Install and Test.
● Evidence: initial grep of `tests/` found no such assertions; re-verify at packaging time after any test additions.
● Fix: if any are added, gate them on `GITLAB_CI` or enforce them everywhere.
● Owner: Ash.

**6. Wire the per-commit static-analysis pass to zero, by rule class.**
SonarQube requires zero open violations and all security hotspots resolved or reviewed, and it reveals rules progressively across scans. A findings report is a sample, not the work list: fix by rule class and grep the whole codebase to zero across every spelling.
● Gate: Code Quality.
● Evidence: ruff configured in `pyproject.toml` with `E, F, I, UP, B, SIM`; no complexity limit selected.
● Fix: add `C90` (mccabe) with `max-complexity` set to a defensible ceiling, run ruff plus bandit per commit, and drive both to zero before packaging so violations never arrive 600 at once.
● Owner: Ash.

## Phase 2 — Container contract (gate: Container Build, Image Policy Scan, Deploy)

**7. Replace the Dockerfile with the hardened multi-stage flattened build.**
The current Dockerfile fails the image policy scan and the deploy contract on at least eight counts.
● Gate: Container Build and Image Policy Scan.
● Evidence (`Dockerfile`, root): single stage; `python:3.12-slim` with no pinned digest; `gcc` and `libffi-dev` installed into the runtime image; pip present at runtime; no `USER` (runs as root); no suid/sgid sweep and no flatten (scanner reads layer history); `EXPOSE 8000` not 8080; port hardcoded in `CMD`.
● Fix: rebuild from the Python recipe in `deploy-recipes` — build stage creates a venv and installs with hashes; prep stage copies the venv and app, creates numeric user `10001`, strips pip from the runtime, patches OS packages (fail-open step in its own `RUN`), then runs the suid/sgid sweep over files AND directories as the LAST mutation (fail closed); final stage is `FROM scratch` with a single `COPY --from=prep / /` and re-declared metadata including explicit `PATH`. `EXPOSE 8080`. `CMD` uses `exec` and binds `0.0.0.0:${PORT:-8080}`. Dockerfile stays at the package root.
● Owner: Ash.

**8. Remove baked ENV defaults; resolve config in code with boot validation.**
Anything in the operator environment tab overrides the platform's injected values, and a Dockerfile `ENV` for a contract variable is the same own-goal one layer earlier.
● Gate: Deploy.
● Evidence: `Dockerfile:23-24` bakes `ENV DATABASE_URL=` and `ENV SPECTRE_LOG_LEVEL=`; `spectre/config/settings.py` already reads the environment (good pattern, extend it).
● Fix: delete both `ENV` lines. In code, resolve each path-or-port setting as explicit var → platform-injected var → code default, validate at boot, and read injected add-on variables at request or startup time, never at module import. No `ENV PORT=` or `ENV DATA_DIR=` ever. Strip quotes and control characters from any env value used as a path or secret.
● Owner: Ash.

**9. Add a real-write health probe at `/healthz` and an unauthenticated 200 at `GET /`.**
A probe that hangs is silently killed; an existence check proves nothing about a read-only volume.
● Gate: Deploy.
● Evidence: no health route exists anywhere in `spectre/web/` (grep for `healthz`/`health` returns nothing in app or routes).
● Fix: `/healthz` performs a real write to the resolved data dir, races a timeout shorter than the platform's probe timeout (see item 15), and on failure returns 503 with the resolved directory and errno in the body so a screenshot is a full diagnosis. `GET /` and `/healthz` return 200 unauthenticated with no redirect in the path (check FastAPI trailing-slash behaviour). Log one decisive line at boot recording whether storage accepted a write.
● Owner: Ash.

**10. Deploy-time operational settings.**
● Gate: Deploy (runtime).
● Fix: leave the operator environment tab EMPTY for a code-defaults app; if the file-storage volume add-on is used, raise the ops request for `securityContext.fsGroup` before first deploy or every write from the non-root user is EACCES.
● Owner: Ash at deploy time; fsGroup request to the platform team.

## Phase 3 — Intercept-specific code fixes (gate: security review, before any zip)

**11. UDL credential: move from the module-global dict into the signed session, encrypted in memory.**
● Gate: security review (`security-hardening` server-side-only secrets assertions); prerequisite to packaging.
● Evidence: `spectre/web/planning_state.py:112` `_store: dict[str, SessionState] = {}` module-global keyed by username; `planning_state.py:55-56` holds `udl_username` and `udl_password` in plaintext; consumed across `routes/udl.py`, `threat.py`, `pol.py`, `operator.py`, `maneuver.py`. The `__repr__` guard at `planning_state.py:92-98` exists and must be kept.
● Fix, in order: tie the UDL credential to the operator's signed session record, scoped per operator, dying with the session — not a process-global (the global dict also breaks under multiple workers). Encrypt it in memory with a key derived from `SECRET_KEY` (already mandatory at boot, `spectre/web/auth.py:29`) so a memory dump yields no plaintext; decrypt only at the point of use in the httpx `auth=` tuple. Never persist, never log, never surface in a client error, never in coverage-instrumented test output. Verify gitleaks stays clean and add a test asserting the credential appears in no response body and no log line.
● Owner: Ash.

**12. Lambert fix.**
● Gate: prerequisite to packaging Intercept, alongside item 11 in the extract-and-fix step.
● Evidence: the defect reference lives in the earlier Intercept review, not in this repo — `spectre/astro/lambert.py` carries no TODO/FIXME marker for it. Attach the specific defect reference to this item before starting.
● Fix: per the earlier review; add a regression test (the `hypothesis` dev dependency is already installed and `docs/TODO list.txt` SEC-05 already asks for property-based tests on `lambert.py`).
● Owner: Ash.

**13. Package hygiene.**
● Gate: Install and Test, plus the secret scan.
● Fix: the zip is a self-sufficient testable source tree — `spectre/`, `tests/`, `pyproject.toml`, `sonar-project.properties`, `Dockerfile` at the package root. Exclude: `.env`, `bluestaq-foundations-server-python-tailored.zip`, `SPECTRE-1/`, `tle_clustering/` scratch, any `.venv` or `__pycache__`. gitleaks clean on the packaged tree, not just the repo.
● Owner: Ash.

## Phase 4 — Pre-flight (gate: every stage, before every upload)

**14. Simulate the platform pipeline against the actual artefact.**
Not the repo — the zip, unzipped fresh into a clean directory.
● Gate: all five stages; this is the control that catches everything above before an upload is burned.
● Fix: adapt `deploy-recipes/templates/simulate-pipeline.sh` (Node shape) to Python: unzip fresh, add a `.gitlab-ci.yml`, set `GITLAB_CI=true`, install from the packaged tree, run the packaged test command with coverage, assert `coverage.xml` exists and is non-empty, then `docker build` the packaged Dockerfile and confirm non-root UID, 200 at `/` and `/healthz` on 8080. Run `app-store-readiness` as the scoring pre-flight. Green simulation before every upload, no exceptions.
● Owner: Ash.

**15. Confirm the TBC platform facts against the live reference — a human answer, not a guess.**
● Gate: items 1 and 9 depend on these values.
● Open questions: the platform's exact health-probe timeout; the precise current coverage threshold; whether the Python container template's stage list differs in detail from the Node reference.
● Fix: confirm against the live `app-store-deployment` platform reference before packaging; record the answers in this file.
● Owner: Ash, or the platform team.

## Sequencing summary

Phase 1 and 2 are scaffold-time work that applies to every artefact and starts now, so none of it is retrofit. Phase 3 is the extract-and-fix step specific to Intercept, before it is ever zipped. Phase 4 runs before every single upload. Item 15 is the only item blocked on an external answer; everything else is actionable today.
