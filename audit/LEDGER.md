# SPECTRE audit ledger

**Commit audited:** `a34e273f5673ea46a23ee2cff93b6ca9137a76d3`, branch `claude/charming-dirac-qcrnpv`, working tree clean at pre-flight.
**Run scope:** phases 1 and 2 only, as instructed (`/audit-repo phases 1 to 2 only`). Phases 3 to 8 are not started.
**Audit date:** 23 October 2026.

Status legend: PENDING (not yet reviewed, phase 5 work), REVIEWED, CLEAN (with reason), EXCLUDED (reason in section 1.4).

## Pre-flight record

```
$ git rev-parse HEAD
a34e273f5673ea46a23ee2cff93b6ca9137a76d3
$ git status --short
(empty)
$ git branch --show-current
claude/charming-dirac-qcrnpv
```

Fact: HEAD `a34e273` is `origin/master` (`e87783a`) plus a single commit adding `.claude/commands/audit-repo.md` and `audit/PRIORS.md`. No source file differs from `master`.

## 1.1 Inventory

### Reconciliation (phase 1 exit)

| Measure | Count | Command |
|---|---|---|
| Tracked entries in git index | 345 | `git ls-files \| wc -l` |
| Regular files on disk, excluding `.git/` | 344 | `find . -type f -not -path './.git/*' \| wc -l` |
| Untracked, not ignored | 0 | `git ls-files --others --exclude-standard \| wc -l` |
| Ledger rows | 345 | this table |

Resolution (fact): the difference of one is `SPECTRE-1`, a gitlink (index mode `160000`, commit `7a63ce58215520d41336e372e5f18d86a6a49845`) that appears on disk as an empty directory. The repository has no `.gitmodules`, so the submodule cannot be initialised. 344 regular files plus 1 gitlink equals 345. **Reconciled.**

### Counts by role

| Role | Files |
|---|---|
| source (Python, shell, Jinja2 templates) | 153 |
| test (Python under `tests/`) | 84 |
| asset (SVG, CSS, HTML splash, binary documents, archive) | 48 |
| docs | 29 |
| config | 17 |
| vendored | 4 |
| generated | 4 |
| data (JSON under `spectre/data/`) | 3 |
| audit-tooling (this audit's own inputs) | 2 |
| gitlink | 1 |
| **Total** | **345** |

Python volume (fact, `wc -l`): 52,252 lines across all tracked `.py`; 26,376 in `spectre/` and `tle_clustering/`; 21,410 in `tests/`.

### Inventory observations, fact, routed to later phases without triage

| ID | Observation | Evidence | Routed to |
|---|---|---|---|
| O1 | Declared Python floor disagrees across four sources | `README.md:28` "Python \| 3.14"; `pyproject.toml:46` `requires-python = ">=3.12"`; `Dockerfile:20` base `python:3.12-slim-bookworm`; `requirements-dev.txt:2` compiled `--python-version 3.11` | Phase 4, L10 |
| O2 | The declared install command installs no dependencies | `README.md:41` and `.github/workflows/ci.yml:31,48,185` `pip install -e ".[dev]"`; reproduced: uv warns "does not have an extra named `dev`", installs `spectre` only, no ruff, mypy or pytest (TOOLS.md section 0) | Phase 4, L10 |
| O3 | README advertises a console script that no install creates | `README.md:49` `spectre-serve`; `spectre/web/_entrypoint.py:1` "Console script entry point: ``spectre-serve``"; `pyproject.toml` has no `[project.scripts]`; after `pip install -e .` no `spectre-serve` exists in the venv `bin/` | Phase 4 |
| O4 | README port disagrees with the code and image | `README.md:54` "http://localhost:8000"; `spectre/config/settings.py:36` `DEFAULT_PORT = 8080`; `Dockerfile:185` `EXPOSE 8080` | Phase 4 |
| O5 | Lockfiles cannot be installed together | `requirements.txt:1370` `tomli==2.5.0`; `requirements-dev.txt:1025` `tomli==2.4.1`; uv: "your requirements are unsatisfiable" | Phase 5, L10 |
| O6 | Three coverage floors | `pyproject.toml:76` `fail_under = 74`; `.github/workflows/ci.yml:55` `--cov-fail-under=70`; `scripts/check-quality.sh:18` `COVERAGE_FLOOR=80` | Phase 5, L10 |
| O7 | Orphan gitlink | `SPECTRE-1`, mode 160000, no `.gitmodules` | Phase 5, L10 |
| O8 | Byte-identical SVGs at repo root and in `spectre/web/static/` | `spectre_icon_mark.svg`, `spectre_icon_family.svg`, `spectre_logo_primary.svg`, equal SHA-1 in both places | Phase 5, L7 |
| O9 | Two Dockerfiles that differ | `diff -q Dockerfile Dockerfile.docker-only` reports they differ; which one is the platform build input is TBC, re-verify against `scripts/package-appstore.sh` | Phase 3, L10 |
| O10 | A binary archive committed at the root contains an `AUDIT.md` (55,431 bytes) | `unzip -l bluestaq-foundations-v1.99.0.zip`; added in `137ea49` "Add files via upload" on 22 October 2026 | Phase 4b: inference, this may be the original audit artefact the PRIORS provenance caveat asks to reconcile against. Not opened in this run. |
| O11 | README describes environment defaults that the shipped example contradicts | `README.md:98` `DATABASE_URL` default `sqlite+aiosqlite:///./spectre.db`; `.env.example` "Leave unset to use SQLite inside the resolved data directory"; README table omits `SPECTRE_ADMIN_RESET`, `SPECTRE_DATA_DIR`, `STORAGE_MOUNT_PATH`, `PORT` | Phase 3.5, Phase 4 |

## 1.2 Declared purpose, quoted verbatim

| Source | Quote |
|---|---|
| `README.md:1` | "SPECTRE — Space Planning, Evaluation & Counter-Threat Response Engine" |
| `README.md:3-4` | "Real-time orbital manoeuvre planning console for space defence operators. Accessed through a browser-based operator interface built on FastAPI + HTMX." |
| `README.md:13` | "**Intercept Engine** (23 methods) — Lambert, Hohmann, bi-elliptic, rendezvous, proximity; tactical manoeuvres ..." |
| `README.md:16` | "**Decision Engine (Phase 1)** — deterministic what-if analysis: build a grid of adversary actions × friendly responses; compute an outcome matrix ..." |
| `README.md:20` | "All orbital mechanics computations use the pure-Python `spectre.astro` package — no external astrodynamics software required." |
| `README.md:466-467` | "All times are UTC. Distances in km, speeds in km/s, angles in degrees. Coordinate frame: ICRF/J2000." |
| `pyproject.toml:45` | "Space Planning, Evaluation and Counter-Threat Response Engine: orbital mechanics, threat assessment, and manoeuvre planning." |
| `docs/architecture.md:5-7` | "SPECTRE is a **pure-Python** orbital analysis console. All astrodynamics computations are performed by the `spectre.astro` package — no external tools, COM interfaces, or licensed astrodynamics software are required." |
| `READINESS.md:8-11` | "This is a pre-flight estimate, not the binding App Store decision. The platform's own pipeline, its container policy scan, its continuous Authority to Operate (cATO) score and human review are the real gate." |
| `spectre/web/_entrypoint.py:1` | "Console script entry point: ``spectre-serve``." |

Purpose claims for features (README lines 12 to 18) are the input to the phase 4 claims ledger and are not restated here. CLI help for the scripts under `scripts/` is recorded per script in phase 3.

## 1.3 Declared run, build, test and deploy commands

Reproduction status is fact where tested in phase 2, otherwise "not run in phase 1 to 2".

| Purpose | Source | Command | Reproduces |
|---|---|---|---|
| Install | `README.md:41`; `ci.yml:31,48,185` | `pip install -e ".[dev]"` | No. No `dev` extra exists; installs `spectre` with no dependencies (TOOLS.md section 0) |
| Install, locked | `Dockerfile` build stage; `scripts/lock.sh:30` | hash-locked `requirements.txt` | Yes, alone. Fails when combined with `requirements-dev.txt` (O5) |
| Run, local | `README.md:49` | `spectre-serve` | No. Console script not created (O3) |
| Run, local | `README.md:51` | `uvicorn spectre.web.app:app --reload` | Not run in phase 1 to 2 |
| Run, container | `Dockerfile:196` | `/opt/venv/bin/python -m spectre.web._entrypoint` | Not run; no Docker daemon in this environment (TBC, re-verify with `docker build`) |
| Run, container | `README.md:68-78` | `docker build -t spectre:latest .`; `docker run -p 8000:8000 ...` | Not run; port in README disagrees with `EXPOSE 8080` (O4) |
| Test | `README.md:225-234` | `pytest tests/unit/`; `pytest tests/integration/test_web_routes.py`; `pytest` | Run in phase 2, section 9 |
| Test, CI | `ci.yml:53-55` | `pytest tests/ -q --cov=spectre --cov-report=term-missing --cov-report=xml --cov-fail-under=70` | Run in phase 2 with branch coverage added |
| Lint | `ci.yml:33` | `ruff check spectre/ tests/` | Run in phase 2 |
| Type check | `ci.yml:35` | `mypy spectre/ --ignore-missing-imports` | Run in phase 2, plus `--strict` per audit spec |
| SAST | `ci.yml:76`; `README.md:280` | `bandit -r spectre/ -ll -c pyproject.toml -q` | Run in phase 2 |
| SCA | `ci.yml:93`; `README.md:283` | `pip-audit --desc on --requirement requirements.txt` | Run in phase 2 |
| Secrets | `ci.yml:109`; `README.md:286` | `gitleaks detect --source . --redact -v` | Run in phase 2 (v8.18.4, as CI pins) |
| Quality gate | `ci.yml:196`; `scripts/check-quality.sh:12` | `sh scripts/check-quality.sh master` | Run in phase 2 |
| Pre-commit | `.pre-commit-config.yaml` | gitleaks, ruff `--fix`, bandit `-ll`, mypy, hygiene hooks | Not run; covered tool by tool |
| Docs | `README.md:294` | `python docs/generate_guide.py` | Not run in phase 1 to 2 (writes a file into `docs/`, which this run must not do) |
| Version bump | `pyproject.toml:14`; `scripts/bump-version.sh:14` | `scripts/bump-version.sh` | Not run (mutating) |
| Deploy package | `scripts/package-appstore.sh:19` | `scripts/package-appstore.sh` | Not run (writes a package) |
| Pipeline rehearsal | `scripts/simulate-pipeline.sh:14`; `scripts/preflight-gate.py:18` | as named | `preflight-gate.py` run in phase 2 if read-only; see TOOLS.md |

## 1.4 Excluded from line-by-line audit, with reasons

| Path | Reason | Residual coverage |
|---|---|---|
| `spectre/web/static/chart.umd.min.js` | Vendored, Chart.js 4.4.7 (banner) | Version recorded for SCA; not covered by pip-audit. TBC, re-verify against a JS advisory database |
| `spectre/web/static/chartjs-plugin-zoom.min.js` | Vendored, chartjs-plugin-zoom 2.0.1 | As above |
| `spectre/web/static/hammer.min.js` | Vendored, Hammer.JS 2.0.7 (2016) | As above |
| `spectre/web/static/htmx.min.js` | Vendored, htmx 1.9.12 (`version:"1.9.12"` in file) | As above |
| `requirements.txt`, `requirements-runtime.txt`, `requirements-dev.txt` | Generated by pip-compile / uv from the `.in` files | pip-audit and safety in phase 2; the `.in` files are PENDING |
| `docs/openapi.json` (287,166 lines) | Generated API schema | Phase 4 compares it with the live routes; not read line by line |
| `docs/SPECTRE_Operator_Guide.docx` | Binary, generated by `docs/generate_guide.py` | The generator is PENDING; the binary's claims are a phase 4 gap |
| `bluestaq-foundations-v1.99.0.zip` | Binary archive of 74 files, third party to this codebase | Contents not audited. See O10 |
| `SPECTRE-1` | Orphan gitlink, no content resolvable | Structural observation O7 only |
| `.claude/commands/audit-repo.md`, `audit/PRIORS.md` | Inputs to this audit, not the system under audit | None needed |

Excluded rows: 13. Rows carried to phase 5 as PENDING: 332.

### Ledger table

| # | Path | Language | Lines | Role | Entry point | Status |
|---|------|----------|-------|------|-------------|--------|
| 1 | `.claude/commands/audit-repo.md` | Markdown | 306 | audit-tooling | no | EXCLUDED |
| 2 | `.dockerignore` | text | 52 | config | no | PENDING |
| 3 | `.env.example` | text | 39 | config | no | PENDING |
| 4 | `.github/dependabot.yml` | YAML | 35 | config | no | PENDING |
| 5 | `.github/workflows/ci.yml` | YAML | 196 | config | CI pipeline | PENDING |
| 6 | `.gitignore` | text | 132 | config | no | PENDING |
| 7 | `.pre-commit-config.yaml` | YAML | 47 | config | no | PENDING |
| 8 | `CHANGELOG.md` | Markdown | 1942 | docs | no | PENDING |
| 9 | `CODEOWNERS` | text | 21 | config | no | PENDING |
| 10 | `Dockerfile` | Dockerfile | 196 | config | image build | PENDING |
| 11 | `Dockerfile.docker-only` | Dockerfile | 206 | config | image build | PENDING |
| 12 | `IMPROVEMENT-PLAN.md` | Markdown | 220 | docs | no | PENDING |
| 13 | `READINESS.md` | Markdown | 370 | docs | no | PENDING |
| 14 | `README.md` | Markdown | 477 | docs | no | PENDING |
| 15 | `RETROSPECTIVE.md` | Markdown | 233 | docs | no | PENDING |
| 16 | `SECURITY.md` | Markdown | 72 | docs | no | PENDING |
| 17 | `SPECTRE-1` | gitlink | - | gitlink (orphan submodule) | no | EXCLUDED |
| 18 | `SPECTRE_logo.svg` | SVG | 276 | asset | no | PENDING |
| 19 | `audit/PRIORS.md` | Markdown | 195 | audit-tooling | no | EXCLUDED |
| 20 | `bluestaq-foundations-v1.99.0.zip` | ZIP archive | binary | asset | no | EXCLUDED |
| 21 | `docs/BUILD-STATE-AND-ROADMAP.md` | Markdown | 215 | docs | no | PENDING |
| 22 | `docs/CHANGE-LEDGER.md` | Markdown | 868 | docs | no | PENDING |
| 23 | `docs/CODE-QUALITY-GATE.md` | Markdown | 182 | docs | no | PENDING |
| 24 | `docs/DELTA-V-RESEARCH-ASSIMILATION.md` | Markdown | 334 | docs | no | PENDING |
| 25 | `docs/DEPENDENCY-SCANNING.md` | Markdown | 173 | docs | no | PENDING |
| 26 | `docs/ESCALATION-DEPENDENCY-SCANNING.md` | Markdown | 66 | docs | no | PENDING |
| 27 | `docs/ORBITAL-CALCULATION-AUDIT.md` | Markdown | 301 | docs | no | PENDING |
| 28 | `docs/RED-TEAM-THREAT-SWEEP.md` | Markdown | 212 | docs | no | PENDING |
| 29 | `docs/SECURITY.md` | Markdown | 274 | docs | no | PENDING |
| 30 | `docs/SPECTRE-OpenAPI-Container-Plan.md` | Markdown | 656 | docs | no | PENDING |
| 31 | `docs/SPECTRE_Gamification_Prompt.md` | Markdown | 199 | docs | no | PENDING |
| 32 | `docs/SPECTRE_Operator_Guide.docx` | Word (binary) | binary | asset | no | EXCLUDED |
| 33 | `docs/SPECTRE_Training_Specialist_Persona.md` | Markdown | 718 | docs | no | PENDING |
| 34 | `docs/TODO list.txt` | Text | 122 | docs | no | PENDING |
| 35 | `docs/UK_Principal_Engineer_Persona.md` | Markdown | 1114 | docs | no | PENDING |
| 36 | `docs/architecture.md` | Markdown | 229 | docs | no | PENDING |
| 37 | `docs/astrogator_notes.md` | Markdown | 261 | docs | no | PENDING |
| 38 | `docs/build_gcat_workbook_1.py` | Python | 359 | source | __main__ CLI | PENDING |
| 39 | `docs/claude-persona-solution-architect.md` | Markdown | 607 | docs | no | PENDING |
| 40 | `docs/decision_engine_phases.md` | Markdown | 178 | docs | no | PENDING |
| 41 | `docs/generate_guide.py` | Python | 2171 | source | __main__ CLI | PENDING |
| 42 | `docs/intercept_engine.md` | Markdown | 140 | docs | no | PENDING |
| 43 | `docs/openapi.json` | JSON | 287166 | generated | no | EXCLUDED |
| 44 | `docs/phased_plan.md` | Markdown | 131 | docs | no | PENDING |
| 45 | `docs/spectre_deep_dive.md` | Markdown | 1417 | docs | no | PENDING |
| 46 | `docs/stk_object_model_notes.md` | Markdown | 137 | docs | no | PENDING |
| 47 | `pyproject.toml` | TOML | 112 | config | no | PENDING |
| 48 | `query_UDL_Data.py` | Python | 45 | source | top-level script (no __main__ guard) | PENDING |
| 49 | `requirements-dev.in` | pip-compile input | 19 | config | no | PENDING |
| 50 | `requirements-dev.txt` | Text | 1101 | generated | no | EXCLUDED |
| 51 | `requirements-runtime.in` | pip-compile input | 24 | config | no | PENDING |
| 52 | `requirements-runtime.txt` | Text | 1418 | generated | no | EXCLUDED |
| 53 | `requirements.in` | pip-compile input | 10 | config | no | PENDING |
| 54 | `requirements.txt` | Text | 1729 | generated | no | EXCLUDED |
| 55 | `scripts/audit-dependencies.sh` | Shell | 96 | source | shell CLI | PENDING |
| 56 | `scripts/build-hrr-default.py` | Python | 256 | source | __main__ CLI | PENDING |
| 57 | `scripts/bump-version.sh` | Shell | 85 | source | shell CLI | PENDING |
| 58 | `scripts/check-quality.sh` | Shell | 188 | source | shell CLI | PENDING |
| 59 | `scripts/cognitive_complexity.py` | Python | 555 | source | __main__ CLI | PENDING |
| 60 | `scripts/lock.sh` | Shell | 69 | source | shell CLI | PENDING |
| 61 | `scripts/package-appstore.sh` | Shell | 336 | source | shell CLI | PENDING |
| 62 | `scripts/preflight-gate.py` | Python | 516 | source | __main__ CLI | PENDING |
| 63 | `scripts/simulate-pipeline.sh` | Shell | 146 | source | shell CLI | PENDING |
| 64 | `scripts/smoke-browser.py` | Python | 394 | source | __main__ CLI | PENDING |
| 65 | `scripts/sonar_scope.py` | Python | 122 | source | __main__ CLI | PENDING |
| 66 | `scripts/verify-container.sh` | Shell | 157 | source | shell CLI | PENDING |
| 67 | `scripts/verify-db-resilience.py` | Python | 48 | source | no | PENDING |
| 68 | `scripts/verify-dependency-scan.sh` | Shell | 83 | source | shell CLI | PENDING |
| 69 | `sonar-project.properties` | Properties | 46 | config | no | PENDING |
| 70 | `spectre/__init__.py` | Python | 4 | source | no | PENDING |
| 71 | `spectre/app_logging/__init__.py` | Python | 1 | source | no | PENDING |
| 72 | `spectre/app_logging/config.py` | Python | 76 | source | no | PENDING |
| 73 | `spectre/astro/__init__.py` | Python | 6 | source | no | PENDING |
| 74 | `spectre/astro/constants.py` | Python | 85 | source | no | PENDING |
| 75 | `spectre/astro/cw_geometry.py` | Python | 536 | source | no | PENDING |
| 76 | `spectre/astro/dv_estimation.py` | Python | 1158 | source | no | PENDING |
| 77 | `spectre/astro/events.py` | Python | 145 | source | no | PENDING |
| 78 | `spectre/astro/lambert.py` | Python | 321 | source | no | PENDING |
| 79 | `spectre/astro/maneuvers.py` | Python | 1532 | source | no | PENDING |
| 80 | `spectre/astro/monte_carlo.py` | Python | 679 | source | no | PENDING |
| 81 | `spectre/astro/notso.py` | Python | 679 | source | no | PENDING |
| 82 | `spectre/astro/pattern_of_life.py` | Python | 1053 | source | no | PENDING |
| 83 | `spectre/astro/photometry.py` | Python | 739 | source | no | PENDING |
| 84 | `spectre/astro/propagator.py` | Python | 320 | source | no | PENDING |
| 85 | `spectre/astro/tactical.py` | Python | 2176 | source | no | PENDING |
| 86 | `spectre/astro/tle_filter.py` | Python | 258 | source | no | PENDING |
| 87 | `spectre/astro/tle_preprocessing.py` | Python | 300 | source | no | PENDING |
| 88 | `spectre/astro/transfers.py` | Python | 102 | source | no | PENDING |
| 89 | `spectre/config/__init__.py` | Python | 1 | source | no | PENDING |
| 90 | `spectre/config/constants.py` | Python | 69 | source | no | PENDING |
| 91 | `spectre/config/settings.py` | Python | 461 | source | no | PENDING |
| 92 | `spectre/data/__init__.py` | Python | 1 | source | no | PENDING |
| 93 | `spectre/data/adversary_intel.json` | JSON | 442 | data | no | PENDING |
| 94 | `spectre/data/hrr_default.json` | JSON | 390 | data | no | PENDING |
| 95 | `spectre/data/intel.py` | Python | 46 | source | no | PENDING |
| 96 | `spectre/data/notso_cache.json` | JSON | 18731 | data | no | PENDING |
| 97 | `spectre/data/notso_cache.py` | Python | 165 | source | no | PENDING |
| 98 | `spectre/domain/__init__.py` | Python | 1 | source | no | PENDING |
| 99 | `spectre/domain/decision.py` | Python | 403 | source | no | PENDING |
| 100 | `spectre/domain/exceptions.py` | Python | 19 | source | no | PENDING |
| 101 | `spectre/domain/geometry.py` | Python | 132 | source | no | PENDING |
| 102 | `spectre/domain/maneuver_planner.py` | Python | 40 | source | no | PENDING |
| 103 | `spectre/domain/manoeuvre_calibration.py` | Python | 728 | source | no | PENDING |
| 104 | `spectre/domain/models.py` | Python | 441 | source | no | PENDING |
| 105 | `spectre/domain/pol_assessment.py` | Python | 1093 | source | no | PENDING |
| 106 | `spectre/domain/scenario.py` | Python | 120 | source | no | PENDING |
| 107 | `spectre/domain/threat_assessment.py` | Python | 580 | source | no | PENDING |
| 108 | `spectre/training/__init__.py` | Python | 8 | source | no | PENDING |
| 109 | `spectre/training/config/gamification.yaml` | YAML | 202 | config | no | PENDING |
| 110 | `spectre/training/config/scenarios.yaml` | YAML | 919 | config | no | PENDING |
| 111 | `spectre/training/config/tutorials.yaml` | YAML | 218 | config | no | PENDING |
| 112 | `spectre/training/gamification.py` | Python | 311 | source | no | PENDING |
| 113 | `spectre/training/models.py` | Python | 176 | source | no | PENDING |
| 114 | `spectre/training/scenarios.py` | Python | 192 | source | no | PENDING |
| 115 | `spectre/training/tutorials.py` | Python | 66 | source | no | PENDING |
| 116 | `spectre/web/__init__.py` | Python | 1 | source | no | PENDING |
| 117 | `spectre/web/_entrypoint.py` | Python | 49 | source | container CMD / console script | PENDING |
| 118 | `spectre/web/app.py` | Python | 359 | source | ASGI app | PENDING |
| 119 | `spectre/web/auth.py` | Python | 197 | source | no | PENDING |
| 120 | `spectre/web/csrf.py` | Python | 98 | source | no | PENDING |
| 121 | `spectre/web/database.py` | Python | 250 | source | no | PENDING |
| 122 | `spectre/web/deps.py` | Python | 50 | source | no | PENDING |
| 123 | `spectre/web/format_units.py` | Python | 93 | source | no | PENDING |
| 124 | `spectre/web/health.py` | Python | 137 | source | HTTP routes | PENDING |
| 125 | `spectre/web/log_safety.py` | Python | 58 | source | no | PENDING |
| 126 | `spectre/web/models.py` | Python | 81 | source | no | PENDING |
| 127 | `spectre/web/planning_state.py` | Python | 223 | source | no | PENDING |
| 128 | `spectre/web/rate_limit.py` | Python | 151 | source | no | PENDING |
| 129 | `spectre/web/routes/__init__.py` | Python | 1 | source | no | PENDING |
| 130 | `spectre/web/routes/admin.py` | Python | 292 | source | HTTP routes | PENDING |
| 131 | `spectre/web/routes/decision.py` | Python | 188 | source | HTTP routes | PENDING |
| 132 | `spectre/web/routes/gcat.py` | Python | 617 | source | HTTP routes | PENDING |
| 133 | `spectre/web/routes/geometry.py` | Python | 215 | source | HTTP routes | PENDING |
| 134 | `spectre/web/routes/login.py` | Python | 217 | source | HTTP routes | PENDING |
| 135 | `spectre/web/routes/maneuver.py` | Python | 1505 | source | HTTP routes | PENDING |
| 136 | `spectre/web/routes/operator.py` | Python | 347 | source | HTTP routes | PENDING |
| 137 | `spectre/web/routes/plan.py` | Python | 245 | source | HTTP routes | PENDING |
| 138 | `spectre/web/routes/pol.py` | Python | 1160 | source | HTTP routes | PENDING |
| 139 | `spectre/web/routes/threat.py` | Python | 1806 | source | HTTP routes | PENDING |
| 140 | `spectre/web/routes/training.py` | Python | 649 | source | HTTP routes | PENDING |
| 141 | `spectre/web/routes/udl.py` | Python | 1196 | source | HTTP routes | PENDING |
| 142 | `spectre/web/static/chart.umd.min.js` | JavaScript | 20 | vendored | no | EXCLUDED |
| 143 | `spectre/web/static/chartjs-plugin-zoom.min.js` | JavaScript | 7 | vendored | no | EXCLUDED |
| 144 | `spectre/web/static/favicon.svg` | SVG | 34 | asset | no | PENDING |
| 145 | `spectre/web/static/hammer.min.js` | JavaScript | 6 | vendored | no | EXCLUDED |
| 146 | `spectre/web/static/htmx.min.js` | JavaScript | 0 | vendored | no | EXCLUDED |
| 147 | `spectre/web/static/spectre-theme.css` | CSS | 1155 | asset | no | PENDING |
| 148 | `spectre/web/static/spectre-theme/README.md` | Markdown | 292 | docs | no | PENDING |
| 149 | `spectre/web/static/spectre-theme/assets/app-icon-512.svg` | SVG | 38 | asset | no | PENDING |
| 150 | `spectre/web/static/spectre-theme/assets/icon-mark.svg` | SVG | 27 | asset | no | PENDING |
| 151 | `spectre/web/static/spectre-theme/assets/logo-horizontal.svg` | SVG | 31 | asset | no | PENDING |
| 152 | `spectre/web/static/spectre-theme/assets/logo-primary.svg` | SVG | 67 | asset | no | PENDING |
| 153 | `spectre/web/static/spectre-theme/assets/splash.html` | HTML/Jinja2 | 298 | asset | no | PENDING |
| 154 | `spectre/web/static/spectre-theme/css/spectre-icons.css` | CSS | 168 | asset | no | PENDING |
| 155 | `spectre/web/static/spectre-theme/css/spectre-theme.css` | CSS | 900 | asset | no | PENDING |
| 156 | `spectre/web/static/spectre-theme/icons/icon-alert.svg` | SVG | 5 | asset | no | PENDING |
| 157 | `spectre/web/static/spectre-theme/icons/icon-chevron-down.svg` | SVG | 3 | asset | no | PENDING |
| 158 | `spectre/web/static/spectre-theme/icons/icon-chevron-right.svg` | SVG | 3 | asset | no | PENDING |
| 159 | `spectre/web/static/spectre-theme/icons/icon-clock.svg` | SVG | 4 | asset | no | PENDING |
| 160 | `spectre/web/static/spectre-theme/icons/icon-close.svg` | SVG | 4 | asset | no | PENDING |
| 161 | `spectre/web/static/spectre-theme/icons/icon-custody.svg` | SVG | 6 | asset | no | PENDING |
| 162 | `spectre/web/static/spectre-theme/icons/icon-dashboard.svg` | SVG | 7 | asset | no | PENDING |
| 163 | `spectre/web/static/spectre-theme/icons/icon-decision.svg` | SVG | 5 | asset | no | PENDING |
| 164 | `spectre/web/static/spectre-theme/icons/icon-export.svg` | SVG | 6 | asset | no | PENDING |
| 165 | `spectre/web/static/spectre-theme/icons/icon-filter.svg` | SVG | 3 | asset | no | PENDING |
| 166 | `spectre/web/static/spectre-theme/icons/icon-import.svg` | SVG | 6 | asset | no | PENDING |
| 167 | `spectre/web/static/spectre-theme/icons/icon-intercept.svg` | SVG | 7 | asset | no | PENDING |
| 168 | `spectre/web/static/spectre-theme/icons/icon-manoeuvre.svg` | SVG | 8 | asset | no | PENDING |
| 169 | `spectre/web/static/spectre-theme/icons/icon-menu.svg` | SVG | 5 | asset | no | PENDING |
| 170 | `spectre/web/static/spectre-theme/icons/icon-monte-carlo.svg` | SVG | 13 | asset | no | PENDING |
| 171 | `spectre/web/static/spectre-theme/icons/icon-notso.svg` | SVG | 6 | asset | no | PENDING |
| 172 | `spectre/web/static/spectre-theme/icons/icon-operator.svg` | SVG | 5 | asset | no | PENDING |
| 173 | `spectre/web/static/spectre-theme/icons/icon-orbit.svg` | SVG | 5 | asset | no | PENDING |
| 174 | `spectre/web/static/spectre-theme/icons/icon-pattern-of-life.svg` | SVG | 5 | asset | no | PENDING |
| 175 | `spectre/web/static/spectre-theme/icons/icon-photometry.svg` | SVG | 12 | asset | no | PENDING |
| 176 | `spectre/web/static/spectre-theme/icons/icon-report.svg` | SVG | 5 | asset | no | PENDING |
| 177 | `spectre/web/static/spectre-theme/icons/icon-search.svg` | SVG | 4 | asset | no | PENDING |
| 178 | `spectre/web/static/spectre-theme/icons/icon-sensor.svg` | SVG | 10 | asset | no | PENDING |
| 179 | `spectre/web/static/spectre-theme/icons/icon-settings.svg` | SVG | 5 | asset | no | PENDING |
| 180 | `spectre/web/static/spectre-theme/icons/icon-threat.svg` | SVG | 8 | asset | no | PENDING |
| 181 | `spectre/web/static/spectre-theme/icons/icon-tle.svg` | SVG | 8 | asset | no | PENDING |
| 182 | `spectre/web/static/spectre-theme/icons/icon-track.svg` | SVG | 7 | asset | no | PENDING |
| 183 | `spectre/web/static/spectre_icon_family.svg` | SVG | 109 | asset | no | PENDING |
| 184 | `spectre/web/static/spectre_icon_mark.svg` | SVG | 47 | asset | no | PENDING |
| 185 | `spectre/web/static/spectre_logo_primary.svg` | SVG | 46 | asset | no | PENDING |
| 186 | `spectre/web/static/style.css` | CSS | 2352 | asset | no | PENDING |
| 187 | `spectre/web/static/themes.css` | CSS | 261 | asset | no | PENDING |
| 188 | `spectre/web/templates/admin/users.html` | HTML/Jinja2 | 88 | source | no | PENDING |
| 189 | `spectre/web/templates/base.html` | HTML/Jinja2 | 76 | source | no | PENDING |
| 190 | `spectre/web/templates/login.html` | HTML/Jinja2 | 52 | source | no | PENDING |
| 191 | `spectre/web/templates/operator.html` | HTML/Jinja2 | 1343 | source | no | PENDING |
| 192 | `spectre/web/templates/partials/_posture_bands.html` | HTML/Jinja2 | 18 | source | no | PENDING |
| 193 | `spectre/web/templates/partials/admin_flash.html` | HTML/Jinja2 | 11 | source | no | PENDING |
| 194 | `spectre/web/templates/partials/admin_user_edit_row.html` | HTML/Jinja2 | 48 | source | no | PENDING |
| 195 | `spectre/web/templates/partials/admin_user_row.html` | HTML/Jinja2 | 41 | source | no | PENDING |
| 196 | `spectre/web/templates/partials/admin_user_table.html` | HTML/Jinja2 | 10 | source | no | PENDING |
| 197 | `spectre/web/templates/partials/admin_user_table_region.html` | HTML/Jinja2 | 28 | source | no | PENDING |
| 198 | `spectre/web/templates/partials/all_intercepts_result.html` | HTML/Jinja2 | 465 | source | no | PENDING |
| 199 | `spectre/web/templates/partials/blue_list.html` | HTML/Jinja2 | 20 | source | no | PENDING |
| 200 | `spectre/web/templates/partials/blue_options.html` | HTML/Jinja2 | 5 | source | no | PENDING |
| 201 | `spectre/web/templates/partials/catalog_results.html` | HTML/Jinja2 | 54 | source | no | PENDING |
| 202 | `spectre/web/templates/partials/clustering_summary.html` | HTML/Jinja2 | 91 | source | no | PENDING |
| 203 | `spectre/web/templates/partials/data_mode_status.html` | HTML/Jinja2 | 1 | source | no | PENDING |
| 204 | `spectre/web/templates/partials/decision_panel.html` | HTML/Jinja2 | 209 | source | no | PENDING |
| 205 | `spectre/web/templates/partials/decision_results.html` | HTML/Jinja2 | 142 | source | no | PENDING |
| 206 | `spectre/web/templates/partials/gcat_panel.html` | HTML/Jinja2 | 196 | source | no | PENDING |
| 207 | `spectre/web/templates/partials/gcat_table.html` | HTML/Jinja2 | 230 | source | no | PENDING |
| 208 | `spectre/web/templates/partials/gcat_welcome.html` | HTML/Jinja2 | 45 | source | no | PENDING |
| 209 | `spectre/web/templates/partials/hrr_panel.html` | HTML/Jinja2 | 137 | source | no | PENDING |
| 210 | `spectre/web/templates/partials/intercept_geometry.html` | HTML/Jinja2 | 400 | source | no | PENDING |
| 211 | `spectre/web/templates/partials/intercept_result.html` | HTML/Jinja2 | 446 | source | no | PENDING |
| 212 | `spectre/web/templates/partials/maneuver_status.html` | HTML/Jinja2 | 15 | source | no | PENDING |
| 213 | `spectre/web/templates/partials/notso_panel.html` | HTML/Jinja2 | 135 | source | no | PENDING |
| 214 | `spectre/web/templates/partials/notso_results.html` | HTML/Jinja2 | 228 | source | no | PENDING |
| 215 | `spectre/web/templates/partials/orbital_events.html` | HTML/Jinja2 | 49 | source | no | PENDING |
| 216 | `spectre/web/templates/partials/osint_card.html` | HTML/Jinja2 | 73 | source | no | PENDING |
| 217 | `spectre/web/templates/partials/pair_card.html` | HTML/Jinja2 | 73 | source | no | PENDING |
| 218 | `spectre/web/templates/partials/photometry_panel.html` | HTML/Jinja2 | 84 | source | no | PENDING |
| 219 | `spectre/web/templates/partials/photometry_results.html` | HTML/Jinja2 | 140 | source | no | PENDING |
| 220 | `spectre/web/templates/partials/pol_manoeuvre_detail.html` | HTML/Jinja2 | 290 | source | no | PENDING |
| 221 | `spectre/web/templates/partials/pol_mc_results.html` | HTML/Jinja2 | 106 | source | no | PENDING |
| 222 | `spectre/web/templates/partials/pol_panel.html` | HTML/Jinja2 | 122 | source | no | PENDING |
| 223 | `spectre/web/templates/partials/pol_results.html` | HTML/Jinja2 | 1251 | source | no | PENDING |
| 224 | `spectre/web/templates/partials/red_list.html` | HTML/Jinja2 | 20 | source | no | PENDING |
| 225 | `spectre/web/templates/partials/red_options.html` | HTML/Jinja2 | 5 | source | no | PENDING |
| 226 | `spectre/web/templates/partials/red_orbit_info.html` | HTML/Jinja2 | 13 | source | no | PENDING |
| 227 | `spectre/web/templates/partials/results_table.html` | HTML/Jinja2 | 30 | source | no | PENDING |
| 228 | `spectre/web/templates/partials/run_log.html` | HTML/Jinja2 | 7 | source | no | PENDING |
| 229 | `spectre/web/templates/partials/sat_select_oob.html` | HTML/Jinja2 | 12 | source | no | PENDING |
| 230 | `spectre/web/templates/partials/screen_config.html` | HTML/Jinja2 | 52 | source | no | PENDING |
| 231 | `spectre/web/templates/partials/splash_overlay.html` | HTML/Jinja2 | 135 | source | no | PENDING |
| 232 | `spectre/web/templates/partials/statevector_fields.html` | HTML/Jinja2 | 28 | source | no | PENDING |
| 233 | `spectre/web/templates/partials/sweep_fetch_status.html` | HTML/Jinja2 | 12 | source | no | PENDING |
| 234 | `spectre/web/templates/partials/sweep_manual_tles.html` | HTML/Jinja2 | 63 | source | no | PENDING |
| 235 | `spectre/web/templates/partials/sweep_target_config.html` | HTML/Jinja2 | 129 | source | no | PENDING |
| 236 | `spectre/web/templates/partials/threat_screen.html` | HTML/Jinja2 | 191 | source | no | PENDING |
| 237 | `spectre/web/templates/partials/threat_sweep.html` | HTML/Jinja2 | 574 | source | no | PENDING |
| 238 | `spectre/web/templates/partials/threat_sweep_row.html` | HTML/Jinja2 | 58 | source | no | PENDING |
| 239 | `spectre/web/templates/partials/tle_fields.html` | HTML/Jinja2 | 21 | source | no | PENDING |
| 240 | `spectre/web/templates/partials/tle_source_panel.html` | HTML/Jinja2 | 16 | source | no | PENDING |
| 241 | `spectre/web/templates/partials/tle_source_status.html` | HTML/Jinja2 | 5 | source | no | PENDING |
| 242 | `spectre/web/templates/partials/trade_space_chart.html` | HTML/Jinja2 | 149 | source | no | PENDING |
| 243 | `spectre/web/templates/partials/training_dashboard.html` | HTML/Jinja2 | 216 | source | no | PENDING |
| 244 | `spectre/web/templates/partials/training_debrief.html` | HTML/Jinja2 | 145 | source | no | PENDING |
| 245 | `spectre/web/templates/partials/training_scenario_active.html` | HTML/Jinja2 | 224 | source | no | PENDING |
| 246 | `spectre/web/templates/partials/training_scenario_detail.html` | HTML/Jinja2 | 121 | source | no | PENDING |
| 247 | `spectre/web/templates/partials/training_scenario_list.html` | HTML/Jinja2 | 76 | source | no | PENDING |
| 248 | `spectre/web/templates/partials/training_tutorial.html` | HTML/Jinja2 | 46 | source | no | PENDING |
| 249 | `spectre/web/templates/partials/training_tutorial_complete.html` | HTML/Jinja2 | 58 | source | no | PENDING |
| 250 | `spectre/web/templates/partials/udl_status.html` | HTML/Jinja2 | 89 | source | no | PENDING |
| 251 | `spectre/web/templates/training.html` | HTML/Jinja2 | 308 | source | no | PENDING |
| 252 | `spectre_icon_family.svg` | SVG | 109 | asset | no | PENDING |
| 253 | `spectre_icon_mark.svg` | SVG | 47 | asset | no | PENDING |
| 254 | `spectre_logo_primary.svg` | SVG | 46 | asset | no | PENDING |
| 255 | `spectre_splash_screen.html` | HTML/Jinja2 | 85 | asset | no | PENDING |
| 256 | `tests/__init__.py` | Python | 0 | test | no | PENDING |
| 257 | `tests/conftest.py` | Python | 45 | test | no | PENDING |
| 258 | `tests/integration/__init__.py` | Python | 0 | test | no | PENDING |
| 259 | `tests/integration/conftest.py` | Python | 67 | test | no | PENDING |
| 260 | `tests/integration/test_admin_bootstrap.py` | Python | 176 | test | no | PENDING |
| 261 | `tests/integration/test_admin_routes.py` | Python | 357 | test | no | PENDING |
| 262 | `tests/integration/test_all_intercepts_ranking.py` | Python | 208 | test | no | PENDING |
| 263 | `tests/integration/test_audit_log_integrity.py` | Python | 194 | test | no | PENDING |
| 264 | `tests/integration/test_login_hardening.py` | Python | 470 | test | no | PENDING |
| 265 | `tests/integration/test_packager_gates.py` | Python | 249 | test | no | PENDING |
| 266 | `tests/integration/test_plan_export.py` | Python | 415 | test | no | PENDING |
| 267 | `tests/integration/test_root_contract.py` | Python | 105 | test | no | PENDING |
| 268 | `tests/integration/test_security_headers.py` | Python | 277 | test | no | PENDING |
| 269 | `tests/integration/test_threat_screen_route.py` | Python | 169 | test | no | PENDING |
| 270 | `tests/integration/test_tle_clustering_pipeline.py` | Python | 322 | test | no | PENDING |
| 271 | `tests/integration/test_web_routes.py` | Python | 197 | test | no | PENDING |
| 272 | `tests/integration/test_web_routes_extended.py` | Python | 640 | test | no | PENDING |
| 273 | `tests/integration/test_xss_escaping.py` | Python | 236 | test | no | PENDING |
| 274 | `tests/unit/__init__.py` | Python | 0 | test | no | PENDING |
| 275 | `tests/unit/conftest.py` | Python | 27 | test | no | PENDING |
| 276 | `tests/unit/test_actor_screening.py` | Python | 203 | test | no | PENDING |
| 277 | `tests/unit/test_astro.py` | Python | 233 | test | no | PENDING |
| 278 | `tests/unit/test_auth.py` | Python | 49 | test | no | PENDING |
| 279 | `tests/unit/test_cognitive_complexity_meter.py` | Python | 256 | test | no | PENDING |
| 280 | `tests/unit/test_config_settings.py` | Python | 467 | test | no | PENDING |
| 281 | `tests/unit/test_contrast_floors.py` | Python | 728 | test | no | PENDING |
| 282 | `tests/unit/test_csrf.py` | Python | 229 | test | no | PENDING |
| 283 | `tests/unit/test_cw_geometry.py` | Python | 528 | test | no | PENDING |
| 284 | `tests/unit/test_dark_surfaces_in_steel.py` | Python | 410 | test | no | PENDING |
| 285 | `tests/unit/test_db_pool_contract.py` | Python | 140 | test | no | PENDING |
| 286 | `tests/unit/test_decision.py` | Python | 304 | test | no | PENDING |
| 287 | `tests/unit/test_deployment_contract.py` | Python | 1591 | test | no | PENDING |
| 288 | `tests/unit/test_docs_are_committable.py` | Python | 134 | test | no | PENDING |
| 289 | `tests/unit/test_domain_models.py` | Python | 97 | test | no | PENDING |
| 290 | `tests/unit/test_dv_estimation.py` | Python | 725 | test | no | PENDING |
| 291 | `tests/unit/test_entrypoint.py` | Python | 66 | test | no | PENDING |
| 292 | `tests/unit/test_exceptions.py` | Python | 32 | test | no | PENDING |
| 293 | `tests/unit/test_focus_visible_indicator.py` | Python | 353 | test | no | PENDING |
| 294 | `tests/unit/test_geometry.py` | Python | 200 | test | no | PENDING |
| 295 | `tests/unit/test_health.py` | Python | 166 | test | no | PENDING |
| 296 | `tests/unit/test_hrr_bootstrap.py` | Python | 253 | test | no | PENDING |
| 297 | `tests/unit/test_hrr_dropdown_is_text.py` | Python | 116 | test | no | PENDING |
| 298 | `tests/unit/test_hrr_preload.py` | Python | 82 | test | no | PENDING |
| 299 | `tests/unit/test_intercept_envelope.py` | Python | 467 | test | no | PENDING |
| 300 | `tests/unit/test_intercept_intel_characterisation.py` | Python | 173 | test | no | PENDING |
| 301 | `tests/unit/test_lambert_validation.py` | Python | 218 | test | no | PENDING |
| 302 | `tests/unit/test_log_safety.py` | Python | 86 | test | no | PENDING |
| 303 | `tests/unit/test_maneuver_planner.py` | Python | 82 | test | no | PENDING |
| 304 | `tests/unit/test_manoeuvre_calibration.py` | Python | 223 | test | no | PENDING |
| 305 | `tests/unit/test_monte_carlo.py` | Python | 188 | test | no | PENDING |
| 306 | `tests/unit/test_notso.py` | Python | 467 | test | no | PENDING |
| 307 | `tests/unit/test_notso_cache.py` | Python | 156 | test | no | PENDING |
| 308 | `tests/unit/test_operator_sees_metres_per_second.py` | Python | 550 | test | no | PENDING |
| 309 | `tests/unit/test_orbital_units_and_degeneracies.py` | Python | 356 | test | no | PENDING |
| 310 | `tests/unit/test_outbound_and_ddl_guards.py` | Python | 304 | test | no | PENDING |
| 311 | `tests/unit/test_pattern_of_life.py` | Python | 402 | test | no | PENDING |
| 312 | `tests/unit/test_photometry.py` | Python | 394 | test | no | PENDING |
| 313 | `tests/unit/test_planning_state.py` | Python | 62 | test | no | PENDING |
| 314 | `tests/unit/test_pol_assessment.py` | Python | 577 | test | no | PENDING |
| 315 | `tests/unit/test_pol_status_ladder.py` | Python | 91 | test | no | PENDING |
| 316 | `tests/unit/test_quality_gate_scope.py` | Python | 358 | test | no | PENDING |
| 317 | `tests/unit/test_rate_limit_memory.py` | Python | 239 | test | no | PENDING |
| 318 | `tests/unit/test_scenario.py` | Python | 24 | test | no | PENDING |
| 319 | `tests/unit/test_settings.py` | Python | 37 | test | no | PENDING |
| 320 | `tests/unit/test_sort_state_and_panel_exit.py` | Python | 199 | test | no | PENDING |
| 321 | `tests/unit/test_tactical.py` | Python | 612 | test | no | PENDING |
| 322 | `tests/unit/test_tactical_validation.py` | Python | 180 | test | no | PENDING |
| 323 | `tests/unit/test_template_markup_is_well_formed.py` | Python | 154 | test | no | PENDING |
| 324 | `tests/unit/test_threat_assessment.py` | Python | 199 | test | no | PENDING |
| 325 | `tests/unit/test_threat_screen_template.py` | Python | 230 | test | no | PENDING |
| 326 | `tests/unit/test_threat_sweep.py` | Python | 390 | test | no | PENDING |
| 327 | `tests/unit/test_threat_sweep_row_styles.py` | Python | 227 | test | no | PENDING |
| 328 | `tests/unit/test_threat_sweep_template.py` | Python | 199 | test | no | PENDING |
| 329 | `tests/unit/test_tle_filter.py` | Python | 258 | test | no | PENDING |
| 330 | `tests/unit/test_tle_line_truncation.py` | Python | 47 | test | no | PENDING |
| 331 | `tests/unit/test_token_channels_match.py` | Python | 159 | test | no | PENDING |
| 332 | `tests/unit/test_training_gamification.py` | Python | 387 | test | no | PENDING |
| 333 | `tests/unit/test_udl_tle_fetch.py` | Python | 495 | test | no | PENDING |
| 334 | `tests/unit/tle_clustering/__init__.py` | Python | 0 | test | no | PENDING |
| 335 | `tests/unit/tle_clustering/conftest.py` | Python | 184 | test | no | PENDING |
| 336 | `tests/unit/tle_clustering/test_clustering.py` | Python | 215 | test | no | PENDING |
| 337 | `tests/unit/tle_clustering/test_integration.py` | Python | 113 | test | no | PENDING |
| 338 | `tests/unit/tle_clustering/test_parser.py` | Python | 110 | test | no | PENDING |
| 339 | `tests/unit/tle_clustering/test_selection.py` | Python | 82 | test | no | PENDING |
| 340 | `tle_clustering/__init__.py` | Python | 111 | source | no | PENDING |
| 341 | `tle_clustering/clustering.py` | Python | 243 | source | no | PENDING |
| 342 | `tle_clustering/config.py` | Python | 135 | source | no | PENDING |
| 343 | `tle_clustering/models.py` | Python | 174 | source | no | PENDING |
| 344 | `tle_clustering/parser.py` | Python | 169 | source | no | PENDING |
| 345 | `tle_clustering/selection.py` | Python | 136 | source | no | PENDING |

## Phase markers

| Phase | Status | Completed | Artefact | Exit check |
|---|---|---|---|---|
| Pre-flight | DONE | 2026-10-23 | this file | tree clean, HEAD `a34e273` |
| 1 Inventory and charter | DONE | 2026-10-23 | `audit/LEDGER.md` | 345 ledger rows = 345 index entries = 344 files on disk + 1 gitlink |
| 2 Deterministic sweep | DONE | 2026-10-23 | `audit/TOOLS.md`, `audit/tools-raw/` (36 files) | every tool produced output or is recorded unavailable: safety UNAVAILABLE (no network route to its database); Docker-dependent gate scripts not run (no daemon) |
| 3 Architecture and flow | DONE | 2026-10-23 | `audit/ARCHITECTURE.md` | 9 entry-point classes, 74 HTTP handlers traced by router group to sinks; 10 documented-versus-code divergences (A1 to A10) |
| 4 Claims reconciliation | IN PROGRESS | | slice reviews S01 to S10 | |
| 4b Prior-audit verification | DONE | 2026-10-23 | `audit/PRIORS-STATUS.md` | 10 of 10 priors carry a verdict and citation; gates tested by mutation (P1 fires, P3 does not) |
| 5 to 8 | IN PROGRESS | | `audit/LENS-BRIEF.md`, slice outputs | resume with `/audit-repo resume from phase 5` if interrupted |
