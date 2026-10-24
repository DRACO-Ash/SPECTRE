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
| 2 | `.dockerignore` | text | 52 | config | no | REVIEWED (S10): F-S10-31 |
| 3 | `.env.example` | text | 39 | config | no | REVIEWED (S10): F-S10-19; extends O11 |
| 4 | `.github/dependabot.yml` | YAML | 35 | config | no | REVIEWED (S10): no defect found in the file itself; whether Dependabot regenerates uv-compiled hashed locks is TBC (section D) |
| 5 | `.github/workflows/ci.yml` | YAML | 196 | config | CI pipeline | REVIEWED (S10): F-S10-06, F-S10-07, F-S10-08, F-S10-25, F-S10-26; extends O2, O6 |
| 6 | `.gitignore` | text | 132 | config | no | REVIEWED (S10): F-S10-30 |
| 7 | `.pre-commit-config.yaml` | YAML | 47 | config | no | REVIEWED (S10): F-S10-09 |
| 8 | `CHANGELOG.md` | Markdown | 1942 | docs | no | REVIEWED (S10): four security and physics fix claims sampled and verified (B-40 to B-43); F-S10-35 |
| 9 | `CODEOWNERS` | text | 21 | config | no | REVIEWED (S10): covers every path README.md:272 names (lines 6, 12, 14, 17, 20); single owner; handle existence and branch-protection enforcement TBC (secti |
| 10 | `Dockerfile` | Dockerfile | 196 | config | image build | REVIEWED (S10): the platform input in the default (python) mode, `scripts/package-appstore.sh:69-80`; F-S10-06, F-S10-23, F-S10-24 |
| 11 | `Dockerfile.docker-only` | Dockerfile | 206 | config | image build | REVIEWED (S10): used only with `--docker-only` (`scripts/package-appstore.sh:175-177`); differs from Dockerfile in comments only; F-S10-24 |
| 12 | `IMPROVEMENT-PLAN.md` | Markdown | 220 | docs | no | REVIEWED (S10): process document (retrospective follow-up, "Proposal only"), not product documentation; no capability claim checked |
| 13 | `READINESS.md` | Markdown | 370 | docs | no | REVIEWED (S10): F-S10-18 |
| 14 | `README.md` | Markdown | 477 | docs | no | REVIEWED (S10): F-S10-01, F-S10-02, F-S10-03, F-S10-04, F-S10-14; extends O1 to O4, O11 |
| 15 | `RETROSPECTIVE.md` | Markdown | 233 | docs | no | REVIEWED (S10): process document (developer retrospective), not product documentation |
| 16 | `SECURITY.md` | Markdown | 72 | docs | no | REVIEWED (S10): F-S10-17 |
| 17 | `SPECTRE-1` | gitlink | - | gitlink (orphan submodule) | no | EXCLUDED |
| 18 | `SPECTRE_logo.svg` | SVG | 276 | asset | no | REVIEWED (S10): F-S10-32 |
| 19 | `audit/PRIORS.md` | Markdown | 195 | audit-tooling | no | EXCLUDED |
| 20 | `bluestaq-foundations-v1.99.0.zip` | ZIP archive | binary | asset | no | EXCLUDED |
| 21 | `docs/BUILD-STATE-AND-ROADMAP.md` | Markdown | 215 | docs | no | REVIEWED (S10): internal planning document; claims not verified line by line (section D) |
| 22 | `docs/CHANGE-LEDGER.md` | Markdown | 868 | docs | no | REVIEWED (S10): carries `## 0.5.24` at line 839, which the packager gate requires; F-S10-28 |
| 23 | `docs/CODE-QUALITY-GATE.md` | Markdown | 182 | docs | no | REVIEWED (S10): internal process note; not checked line by line (section D) |
| 24 | `docs/DELTA-V-RESEARCH-ASSIMILATION.md` | Markdown | 334 | docs | no | REVIEWED (S10): internal analysis note against 0.5.19; not checked line by line (section D) |
| 25 | `docs/DEPENDENCY-SCANNING.md` | Markdown | 173 | docs | no | REVIEWED (S10): repeats the misattributed subset assertion (line 31); F-S10-23 |
| 26 | `docs/ESCALATION-DEPENDENCY-SCANNING.md` | Markdown | 66 | docs | no | REVIEWED (S10): paste-ready note to a platform team; process material, not product documentation |
| 27 | `docs/ORBITAL-CALCULATION-AUDIT.md` | Markdown | 301 | docs | no | REVIEWED (S10): four "fixed" claims verified in code (B-36 to B-39); its own open findings (frames, GEO radius) corroborate F-S10-03 |
| 28 | `docs/RED-TEAM-THREAT-SWEEP.md` | Markdown | 212 | docs | no | REVIEWED (S10): internal analysis note; not checked line by line (section D) |
| 29 | `docs/SECURITY.md` | Markdown | 274 | docs | no | REVIEWED (S10): F-S10-05, F-S10-17 |
| 30 | `docs/SPECTRE-OpenAPI-Container-Plan.md` | Markdown | 656 | docs | no | REVIEWED (S10): self-declared "DRAFT" plan dated 2026-04-12; not a statement of current behaviour |
| 31 | `docs/SPECTRE_Gamification_Prompt.md` | Markdown | 199 | docs | no | REVIEWED (S10): F-S10-33 (LLM prompt, not product documentation) |
| 32 | `docs/SPECTRE_Operator_Guide.docx` | Word (binary) | binary | asset | no | EXCLUDED |
| 33 | `docs/SPECTRE_Training_Specialist_Persona.md` | Markdown | 718 | docs | no | REVIEWED (S10): F-S10-33 (persona charter) |
| 34 | `docs/TODO list.txt` | Text | 122 | docs | no | REVIEWED (S10): backlog file last updated 2026-05-05; not product documentation |
| 35 | `docs/UK_Principal_Engineer_Persona.md` | Markdown | 1114 | docs | no | REVIEWED (S10): F-S10-33 (system-prompt persona) |
| 36 | `docs/architecture.md` | Markdown | 229 | docs | no | REVIEWED (S10): F-S10-01, F-S10-14, F-S10-16 |
| 37 | `docs/astrogator_notes.md` | Markdown | 261 | docs | no | REVIEWED (S10): F-S10-32 |
| 38 | `docs/build_gcat_workbook_1.py` | Python | 359 | source | __main__ CLI | REVIEWED (S10): standalone generator; needs `openpyxl`, which no lockfile pins (section D) |
| 39 | `docs/claude-persona-solution-architect.md` | Markdown | 607 | docs | no | REVIEWED (S10): F-S10-33 |
| 40 | `docs/decision_engine_phases.md` | Markdown | 178 | docs | no | REVIEWED (S10): roadmap; not checked line by line |
| 41 | `docs/generate_guide.py` | Python | 2171 | source | __main__ CLI | REVIEWED (S10): sole importer of `docx`; F-S10-20; palette drift noted in section D |
| 42 | `docs/intercept_engine.md` | Markdown | 140 | docs | no | REVIEWED (S10): F-S10-01, F-S10-02, F-S10-15 |
| 43 | `docs/openapi.json` | JSON | 287166 | generated | no | EXCLUDED |
| 44 | `docs/phased_plan.md` | Markdown | 131 | docs | no | REVIEWED (S10): STK-era sections are bannered as historical (line 58); no finding |
| 45 | `docs/spectre_deep_dive.md` | Markdown | 1417 | docs | no | REVIEWED (S10): pre-implementation design note dated 2026-03-31; proposes `ProcessPoolExecutor` (line 421) and J2000 state (line 247), both since superseded |
| 46 | `docs/stk_object_model_notes.md` | Markdown | 137 | docs | no | REVIEWED (S10): F-S10-32 |
| 47 | `pyproject.toml` | TOML | 112 | config | no | REVIEWED (S10): F-S10-14 (unused `integration` marker); extends O2, O3, O6 |
| 48 | `query_UDL_Data.py` | Python | 45 | source | top-level script (no __main__ guard) | REVIEWED (S10): F-S10-22 |
| 49 | `requirements-dev.in` | pip-compile input | 19 | config | no | REVIEWED (S10): no `-r requirements.in`, so the dev set is resolved independently, which is the root of O5 |
| 50 | `requirements-dev.txt` | Text | 1101 | generated | no | EXCLUDED |
| 51 | `requirements-runtime.in` | pip-compile input | 24 | config | no | REVIEWED (S10): F-S10-20, F-S10-23 |
| 52 | `requirements-runtime.txt` | Text | 1418 | generated | no | EXCLUDED |
| 53 | `requirements.in` | pip-compile input | 10 | config | no | REVIEWED (S10): F-S10-20 (`hypothesis` pinned, used by no test) |
| 54 | `requirements.txt` | Text | 1729 | generated | no | EXCLUDED |
| 55 | `scripts/audit-dependencies.sh` | Shell | 96 | source | shell CLI | REVIEWED (S10): F-S10-36 |
| 56 | `scripts/build-hrr-default.py` | Python | 256 | source | __main__ CLI | REVIEWED (S10): header states the element sets are SYNTHETIC and tagged; tag propagation to the UI not traced (section D) |
| 57 | `scripts/bump-version.sh` | Shell | 85 | source | shell CLI | REVIEWED (S10): F-S10-18, F-S10-24 |
| 58 | `scripts/check-quality.sh` | Shell | 188 | source | shell CLI | REVIEWED (S10): F-S10-07, F-S10-23, F-S10-27, F-S10-35; extends O6 |
| 59 | `scripts/cognitive_complexity.py` | Python | 555 | source | __main__ CLI | REVIEWED (S10): F-S10-11, F-S10-12 |
| 60 | `scripts/lock.sh` | Shell | 69 | source | shell CLI | CLEAN (S10): `set -eu`, every expansion quoted, each `.in` compiled by `uv pip compile` redirected to its `.txt` (lines 43-57), no pipes or temp files |
| 61 | `scripts/package-appstore.sh` | Shell | 336 | source | shell CLI | REVIEWED (S10): F-S10-13, F-S10-21, F-S10-28, F-S10-29; F-S10-24 (header) |
| 62 | `scripts/preflight-gate.py` | Python | 516 | source | __main__ CLI | REVIEWED (S10): runtime-subset check at lines 286-309 is the real control F-S10-23 refers to; usage text names `preflight.py` (section D) |
| 63 | `scripts/simulate-pipeline.sh` | Shell | 146 | source | shell CLI | REVIEWED (S10): F-S10-06, F-S10-10, F-S10-27 |
| 64 | `scripts/smoke-browser.py` | Python | 394 | source | __main__ CLI | REVIEWED (S10): header and hazard grep only (no `verify=False`, no `shell=True`); not wired into CI; full read TBC (section D) |
| 65 | `scripts/sonar_scope.py` | Python | 122 | source | __main__ CLI | CLEAN (S10): merge-base anchored `git diff -U0` against the working tree plus untracked files (lines 52-80); behaviour pinned by tests/unit/test_quality_ |
| 66 | `scripts/verify-container.sh` | Shell | 157 | source | shell CLI | REVIEWED (S10): F-S10-06, F-S10-10 |
| 67 | `scripts/verify-db-resilience.py` | Python | 48 | source | no | REVIEWED (S10): diagnostic only, reads private pool attributes (`_pre_ping`, `_recycle`, lines 15-16); not wired into CI or tests |
| 68 | `scripts/verify-dependency-scan.sh` | Shell | 83 | source | shell CLI | REVIEWED (S10): F-S10-21 |
| 69 | `sonar-project.properties` | Properties | 46 | config | no | CLEAN (S10): sources, tests, coverage path and the single coverage exclusion each carry a stated reason; `projectVersion` matches `spectre/__init__.py:3` |
| 70 | `spectre/__init__.py` | Python | 4 | source | no | CLEAN (S08): two module constants (`__version__`, `__author__`), no logic |
| 71 | `spectre/app_logging/__init__.py` | Python | 1 | source | no | CLEAN (S08): docstring only |
| 72 | `spectre/app_logging/config.py` | Python | 76 | source | no | REVIEWED (S08): finding F-S08-16 (dead module, never called) |
| 73 | `spectre/astro/__init__.py` | Python | 6 | source | no | CLEAN (S01): package docstring only, no code; the one claim ("Lambert solvers" plural) is cosmetic |
| 74 | `spectre/astro/constants.py` | Python | 85 | source | no | REVIEWED (S01): findings F-S01-12, F-S01-23, F-S01-24 |
| 75 | `spectre/astro/cw_geometry.py` | Python | 536 | source | no | REVIEWED (S02): findings F-S02-29, F-S02-30; CW closed form and rotating-frame velocity checked by hand against Curtis eq. 7.53 and found correct |
| 76 | `spectre/astro/dv_estimation.py` | Python | 1158 | source | no | REVIEWED (S04): findings F-S04-04, F-S04-06, F-S04-14, F-S04-15, F-S04-19, F-S04-24, F-S04-25 |
| 77 | `spectre/astro/events.py` | Python | 145 | source | no | REVIEWED (S01): findings F-S01-18, F-S01-19 |
| 78 | `spectre/astro/lambert.py` | Python | 321 | source | no | REVIEWED (S01): findings F-S01-03, F-S01-04, F-S01-13, F-S01-14, F-S01-15 |
| 79 | `spectre/astro/maneuvers.py` | Python | 1532 | source | no | REVIEWED (S01): findings F-S01-01, F-S01-02, F-S01-03, F-S01-05, F-S01-06, F-S01-07, F-S01-08, F-S01-09, F-S01-10, F-S01-11, F-S01-16, F-S01-23, F-S01-26, F |
| 80 | `spectre/astro/monte_carlo.py` | Python | 679 | source | no | REVIEWED (S04): findings F-S04-01, F-S04-02, F-S04-03, F-S04-10, F-S04-11, F-S04-12, F-S04-13, F-S04-16, F-S04-17, F-S04-18 |
| 81 | `spectre/astro/notso.py` | Python | 679 | source | no | REVIEWED (S03): findings F-S03-02, F-S03-07, F-S03-08, F-S03-09, F-S03-10, F-S03-11, F-S03-12, F-S03-13, F-S03-26, F-S03-30, F-S03-31 |
| 82 | `spectre/astro/pattern_of_life.py` | Python | 1053 | source | no | REVIEWED (S03): findings F-S03-01, F-S03-03, F-S03-04, F-S03-14, F-S03-15, F-S03-16, F-S03-17, F-S03-18, F-S03-19, F-S03-20, F-S03-21, F-S03-22, F-S03-23, F |
| 83 | `spectre/astro/photometry.py` | Python | 739 | source | no | REVIEWED (S04): findings F-S04-05, F-S04-07, F-S04-08, F-S04-09, F-S04-18, F-S04-20, F-S04-21, F-S04-22, F-S04-23 |
| 84 | `spectre/astro/propagator.py` | Python | 320 | source | no | REVIEWED (S01): findings F-S01-17, F-S01-25 |
| 85 | `spectre/astro/tactical.py` | Python | 2176 | source | no | REVIEWED (S02): findings F-S02-01, F-S02-03, F-S02-05, F-S02-07 to F-S02-11, F-S02-13 to F-S02-28, F-S02-33, F-S02-34 |
| 86 | `spectre/astro/tle_filter.py` | Python | 258 | source | no | REVIEWED (S03): findings F-S03-05 |
| 87 | `spectre/astro/tle_preprocessing.py` | Python | 300 | source | no | REVIEWED (S03): findings F-S03-06, F-S03-25, F-S03-27, F-S03-28, F-S03-32 |
| 88 | `spectre/astro/transfers.py` | Python | 102 | source | no | REVIEWED (S01): finding F-S01-20; Hohmann and bi-elliptic formulae verified correct by hand (Vallado Example 6-1) |
| 89 | `spectre/config/__init__.py` | Python | 1 | source | no | CLEAN (S08): docstring only |
| 90 | `spectre/config/constants.py` | Python | 69 | source | no | REVIEWED (S01): finding F-S01-22 |
| 91 | `spectre/config/settings.py` | Python | 461 | source | no | REVIEWED (S08): findings F-S08-10, F-S08-16 |
| 92 | `spectre/data/__init__.py` | Python | 1 | source | no | CLEAN (S07): one-line package docstring, no code |
| 93 | `spectre/data/adversary_intel.json` | JSON | 442 | data | no | REVIEWED (S07): 44 records (CHN 29, IRN 10, RUS 5), fields name, country, orbit, status, threat_level, assessed_threat, significance, source; no classificat |
| 94 | `spectre/data/hrr_default.json` | JSON | 390 | data | no | CLEAN (S07): bootstrap watchlist, 38 entries; self-describes as "BOOTSTRAP DATA, NOT AN OPERATIONAL PRODUCT" with every element set tleDataMode SYNTHETIC |
| 95 | `spectre/data/intel.py` | Python | 46 | source | no | REVIEWED (S07): F-S07-20, F-S07-23 |
| 96 | `spectre/data/notso_cache.json` | JSON | 18731 | data | no | REVIEWED (S07): F-S07-03, F-S07-05 (500 REAL JCO records, marked U//DS-JCO-NOTIF, committed and shipped) |
| 97 | `spectre/data/notso_cache.py` | Python | 165 | source | no | REVIEWED (S07): F-S07-03, F-S07-13 |
| 98 | `spectre/domain/__init__.py` | Python | 1 | source | no | CLEAN (S05): one-line package docstring, no code |
| 99 | `spectre/domain/decision.py` | Python | 403 | source | no | REVIEWED (S05): findings F-S05-01, F-S05-02, F-S05-03, F-S05-04, F-S05-05, F-S05-06, F-S05-07, F-S05-17, F-S05-18, F-S05-22 |
| 100 | `spectre/domain/exceptions.py` | Python | 19 | source | no | REVIEWED (S05): finding F-S05-22 (four exception classes with no production raiser) |
| 101 | `spectre/domain/geometry.py` | Python | 132 | source | no | REVIEWED (S02): finding F-S02-31; SEZ matrix and azimuth convention match Vallado topocentric SEZ form and are pinned at tests/unit/test_geometry.py:45-165 |
| 102 | `spectre/domain/maneuver_planner.py` | Python | 40 | source | no | REVIEWED (S05): finding F-S05-22 (validator has no production caller); validation logic itself correct and fully tested at tests/unit/test_maneuver_planner. |
| 103 | `spectre/domain/manoeuvre_calibration.py` | Python | 728 | source | no | REVIEWED (S05): findings F-S05-13, F-S05-14, F-S05-17, F-S05-23 |
| 104 | `spectre/domain/models.py` | Python | 441 | source | no | REVIEWED (S05): finding F-S05-21 |
| 105 | `spectre/domain/pol_assessment.py` | Python | 1093 | source | no | REVIEWED (S05): findings F-S05-09, F-S05-10, F-S05-11, F-S05-12, F-S05-17, F-S05-19, F-S05-20 |
| 106 | `spectre/domain/scenario.py` | Python | 120 | source | no | REVIEWED (S05): findings F-S05-07, F-S05-08, F-S05-22 |
| 107 | `spectre/domain/threat_assessment.py` | Python | 580 | source | no | REVIEWED (S05): findings F-S05-12, F-S05-15, F-S05-16, F-S05-17 |
| 108 | `spectre/training/__init__.py` | Python | 8 | source | no | REVIEWED (S09): F-S09-06 (docstring isolation claim is false) |
| 109 | `spectre/training/config/gamification.yaml` | YAML | 202 | config | no | REVIEWED (S09): F-S09-09, F-S09-22, F-S09-23 |
| 110 | `spectre/training/config/scenarios.yaml` | YAML | 919 | config | no | REVIEWED (S09): F-S09-07, F-S09-08, F-S09-33; 13 scenario ids counted at :31, :92, :153, :242, :274, :346, :413, :478, :547, :612, :687, :760, :827 |
| 111 | `spectre/training/config/tutorials.yaml` | YAML | 218 | config | no | REVIEWED (S09): F-S09-06, F-S09-34 |
| 112 | `spectre/training/gamification.py` | Python | 311 | source | no | REVIEWED (S09): F-S09-21, F-S09-22; yaml.safe_load at :91 |
| 113 | `spectre/training/models.py` | Python | 176 | source | no | REVIEWED (S09): F-S09-06 (docstring), F-S09-20 (ended_at Optional typing) |
| 114 | `spectre/training/scenarios.py` | Python | 192 | source | no | REVIEWED (S09): F-S09-19, F-S09-22 (time_limit_minutes and challenge_scenarios parsed, never enforced); yaml.safe_load at :175 |
| 115 | `spectre/training/tutorials.py` | Python | 66 | source | no | CLEAN (S09): read-only loader, yaml.safe_load at :36, missing or malformed file degrades to empty list with a logged error at :51-56 |
| 116 | `spectre/web/__init__.py` | Python | 1 | source | no | CLEAN (S08): docstring only |
| 117 | `spectre/web/_entrypoint.py` | Python | 49 | source | container CMD / console script | REVIEWED (S08): finding F-S08-13 |
| 118 | `spectre/web/app.py` | Python | 359 | source | ASGI app | REVIEWED (S08): no finding of its own; CSP gaps are self-declared at app.py:229-269 and header behaviour is pinned at tests/integration/test_security_header |
| 119 | `spectre/web/auth.py` | Python | 197 | source | no | REVIEWED (S08): findings F-S08-02, F-S08-06, F-S08-12 |
| 120 | `spectre/web/csrf.py` | Python | 98 | source | no | REVIEWED (S08): findings F-S08-04, F-S08-07, F-S08-08 |
| 121 | `spectre/web/database.py` | Python | 250 | source | no | REVIEWED (S08): findings F-S08-06, F-S08-18 |
| 122 | `spectre/web/deps.py` | Python | 50 | source | no | REVIEWED (S08): contributes to F-S08-08 (CSRF token minted for any cookie value) |
| 123 | `spectre/web/format_units.py` | Python | 93 | source | no | CLEAN (S09): pure formatting; single km/s to m/s conversion delegated to from_km_s; template no-arithmetic invariant asserted in tests/unit/test_operator |
| 124 | `spectre/web/health.py` | Python | 137 | source | HTTP routes | REVIEWED (S08): finding F-S08-09 |
| 125 | `spectre/web/log_safety.py` | Python | 58 | source | no | REVIEWED (S08): finding F-S08-19 |
| 126 | `spectre/web/models.py` | Python | 81 | source | no | REVIEWED (S08): contributes to F-S08-02 (generation default 0 on a recreated row) |
| 127 | `spectre/web/planning_state.py` | Python | 223 | source | no | REVIEWED (S08): findings F-S08-03, F-S08-11 |
| 128 | `spectre/web/rate_limit.py` | Python | 151 | source | no | REVIEWED (S08): finding F-S08-17 (docstring scope); memory bound sound and pinned at tests/unit/test_rate_limit_memory.py:34-222 |
| 129 | `spectre/web/routes/__init__.py` | Python | 1 | source | no | CLEAN (S08): docstring only |
| 130 | `spectre/web/routes/admin.py` | Python | 292 | source | HTTP routes | REVIEWED (S08): findings F-S08-02, F-S08-03, F-S08-05, F-S08-17 |
| 131 | `spectre/web/routes/decision.py` | Python | 188 | source | HTTP routes | REVIEWED (S09): F-S09-13, F-S09-14 |
| 132 | `spectre/web/routes/gcat.py` | Python | 617 | source | HTTP routes | REVIEWED (S07): F-S07-06, F-S07-07, F-S07-08, F-S07-23 |
| 133 | `spectre/web/routes/geometry.py` | Python | 215 | source | HTTP routes | REVIEWED (S09): F-S09-25 |
| 134 | `spectre/web/routes/login.py` | Python | 217 | source | HTTP routes | REVIEWED (S08): findings F-S08-01, F-S08-06, F-S08-07, F-S08-08, F-S08-15 |
| 135 | `spectre/web/routes/maneuver.py` | Python | 1505 | source | HTTP routes | REVIEWED (S06): findings F-S06-01, 02, 06, 07, 12, 16, 17, 18, 19, 20, 21, 22, 24, 29, 32, 34, 35 |
| 136 | `spectre/web/routes/operator.py` | Python | 347 | source | HTTP routes | REVIEWED (S09): F-S09-24, F-S09-26 |
| 137 | `spectre/web/routes/plan.py` | Python | 245 | source | HTTP routes | CLEAN (S09): formula-lead guard pinned by tests/integration/test_plan_export.py:170-226, single writerow call pinned by AST test :254-290, CWE-113 run_id |
| 138 | `spectre/web/routes/pol.py` | Python | 1160 | source | HTTP routes | REVIEWED (S07): F-S07-02, F-S07-03, F-S07-14, F-S07-16, F-S07-18, F-S07-19, F-S07-22 |
| 139 | `spectre/web/routes/threat.py` | Python | 1806 | source | HTTP routes | REVIEWED (S06): findings F-S06-05, 08, 09, 10, 11, 12, 13, 14, 15, 23, 24, 25, 26, 32, 34 |
| 140 | `spectre/web/routes/training.py` | Python | 649 | source | HTTP routes | REVIEWED (S09): F-S09-01, -02, -03, -04, -06, -15, -18, -19, -20, -37 |
| 141 | `spectre/web/routes/udl.py` | Python | 1196 | source | HTTP routes | REVIEWED (S07): F-S07-01, F-S07-04, F-S07-09, F-S07-10, F-S07-11, F-S07-12, F-S07-14, F-S07-15, F-S07-17, F-S07-21, F-S07-22, F-S07-24 |
| 142 | `spectre/web/static/chart.umd.min.js` | JavaScript | 20 | vendored | no | EXCLUDED |
| 143 | `spectre/web/static/chartjs-plugin-zoom.min.js` | JavaScript | 7 | vendored | no | EXCLUDED |
| 144 | `spectre/web/static/favicon.svg` | SVG | 34 | asset | no | REVIEWED (S09): F-S09-28 (unreferenced); no script, handler or external href (grep `<script\/on[a-z]+=\/href=\/url\(` over static: 0 hits in SVGs) |
| 145 | `spectre/web/static/hammer.min.js` | JavaScript | 6 | vendored | no | EXCLUDED |
| 146 | `spectre/web/static/htmx.min.js` | JavaScript | 0 | vendored | no | EXCLUDED |
| 147 | `spectre/web/static/spectre-theme.css` | CSS | 1155 | asset | no | REVIEWED (S09): F-S09-27 (Google Fonts @import at :18-19) |
| 148 | `spectre/web/static/spectre-theme/README.md` | Markdown | 292 | docs | no | REVIEWED (S09): F-S09-28 (documents splash.html and app-icon-512.svg integration that the app never performs) |
| 149 | `spectre/web/static/spectre-theme/assets/app-icon-512.svg` | SVG | 38 | asset | no | REVIEWED (S09): F-S09-28 (referenced only by the theme README) |
| 150 | `spectre/web/static/spectre-theme/assets/icon-mark.svg` | SVG | 27 | asset | no | CLEAN (S09): static SVG, no script, handler or external href (grep 0 hits); referenced as favicon at templates/base.html:7 |
| 151 | `spectre/web/static/spectre-theme/assets/logo-horizontal.svg` | SVG | 31 | asset | no | CLEAN (S09): static SVG, no script, handler or external href (grep 0 hits); referenced at training.html:6 |
| 152 | `spectre/web/static/spectre-theme/assets/logo-primary.svg` | SVG | 67 | asset | no | CLEAN (S09): static SVG, no script, handler or external href (grep 0 hits); referenced at templates/login.html:9 |
| 153 | `spectre/web/static/spectre-theme/assets/splash.html` | HTML/Jinja2 | 298 | asset | no | REVIEWED (S09): F-S09-27 (Google Fonts @import at :8), F-S09-28 (unreferenced, served from /static with an inline script at :264) |
| 154 | `spectre/web/static/spectre-theme/css/spectre-icons.css` | CSS | 168 | asset | no | CLEAN (S09): no @import or url() to any host (grep 0 hits); `href` at :6 is inside a usage comment |
| 155 | `spectre/web/static/spectre-theme/css/spectre-theme.css` | CSS | 900 | asset | no | REVIEWED (S09): F-S09-27, F-S09-28 (stale divergent copy, 900 lines vs 1155 in the loaded copy, differs from line 41) |
| 156 | `spectre/web/static/spectre-theme/icons/icon-alert.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 157 | `spectre/web/static/spectre-theme/icons/icon-chevron-down.svg` | SVG | 3 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 158 | `spectre/web/static/spectre-theme/icons/icon-chevron-right.svg` | SVG | 3 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 159 | `spectre/web/static/spectre-theme/icons/icon-clock.svg` | SVG | 4 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 160 | `spectre/web/static/spectre-theme/icons/icon-close.svg` | SVG | 4 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 161 | `spectre/web/static/spectre-theme/icons/icon-custody.svg` | SVG | 6 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 162 | `spectre/web/static/spectre-theme/icons/icon-dashboard.svg` | SVG | 7 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 163 | `spectre/web/static/spectre-theme/icons/icon-decision.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 164 | `spectre/web/static/spectre-theme/icons/icon-export.svg` | SVG | 6 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 165 | `spectre/web/static/spectre-theme/icons/icon-filter.svg` | SVG | 3 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 166 | `spectre/web/static/spectre-theme/icons/icon-import.svg` | SVG | 6 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 167 | `spectre/web/static/spectre-theme/icons/icon-intercept.svg` | SVG | 7 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 168 | `spectre/web/static/spectre-theme/icons/icon-manoeuvre.svg` | SVG | 8 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 169 | `spectre/web/static/spectre-theme/icons/icon-menu.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 170 | `spectre/web/static/spectre-theme/icons/icon-monte-carlo.svg` | SVG | 13 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 171 | `spectre/web/static/spectre-theme/icons/icon-notso.svg` | SVG | 6 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 172 | `spectre/web/static/spectre-theme/icons/icon-operator.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 173 | `spectre/web/static/spectre-theme/icons/icon-orbit.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 174 | `spectre/web/static/spectre-theme/icons/icon-pattern-of-life.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 175 | `spectre/web/static/spectre-theme/icons/icon-photometry.svg` | SVG | 12 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 176 | `spectre/web/static/spectre-theme/icons/icon-report.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 177 | `spectre/web/static/spectre-theme/icons/icon-search.svg` | SVG | 4 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 178 | `spectre/web/static/spectre-theme/icons/icon-sensor.svg` | SVG | 10 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 179 | `spectre/web/static/spectre-theme/icons/icon-settings.svg` | SVG | 5 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 180 | `spectre/web/static/spectre-theme/icons/icon-threat.svg` | SVG | 8 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 181 | `spectre/web/static/spectre-theme/icons/icon-tle.svg` | SVG | 8 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 182 | `spectre/web/static/spectre-theme/icons/icon-track.svg` | SVG | 7 | asset | no | CLEAN (S09): static path-only SVG, no script, handler, foreignObject or external href (grep 0 hits) |
| 183 | `spectre/web/static/spectre_icon_family.svg` | SVG | 109 | asset | no | REVIEWED (S09): F-S09-28 (unreferenced: grep `spectre_icon_family` repo-wide outside audit/, 0 hits) |
| 184 | `spectre/web/static/spectre_icon_mark.svg` | SVG | 47 | asset | no | REVIEWED (S09): F-S09-28 (unreferenced: grep `spectre_icon_mark`, 0 hits) |
| 185 | `spectre/web/static/spectre_logo_primary.svg` | SVG | 46 | asset | no | REVIEWED (S09): F-S09-28 (unreferenced: grep `spectre_logo_primary`, 0 hits) |
| 186 | `spectre/web/static/style.css` | CSS | 2352 | asset | no | CLEAN (S09): no @import or url() to an external host (grep 0 hits); its contrast tokens are measured by tests/unit/test_contrast_floors.py:87-98 against  |
| 187 | `spectre/web/static/themes.css` | CSS | 261 | asset | no | CLEAN (S09): no @import or url() to an external host (grep 0 hits); theme-token file only, token channels checked by tests/unit/test_token_channels_match |
| 188 | `spectre/web/templates/admin/users.html` | HTML/Jinja2 | 88 | source | no | CLEAN (S08): every interpolation is autoescaped (`{{ current_user.username }}`, `{{ flash.message }}`, `{{ csrf_token }}`), no `/safe`; autoescape forced |
| 189 | `spectre/web/templates/base.html` | HTML/Jinja2 | 76 | source | no | CLEAN (S08): no `/safe`; CSRF token is an autoescaped itsdangerous value inside a single-quoted JSON attribute (base.html:60), token alphabet carries no  |
| 190 | `spectre/web/templates/login.html` | HTML/Jinja2 | 52 | source | no | CLEAN (S08): only `{{ error }}` interpolated (login.html:20), always a server literal from login.py:154 and :162 |
| 191 | `spectre/web/templates/operator.html` | HTML/Jinja2 | 1343 | source | no | REVIEWED (S09): F-S09-30 (23 inline handlers and 8 inline script blocks, needs 'unsafe-inline'); scripts that build DOM from HRR data use createTextNode at  |
| 192 | `spectre/web/templates/partials/_posture_bands.html` | HTML/Jinja2 | 18 | source | no | CLEAN (S06): one literal dict (lines 13-18), imported by both threat_sweep.html:5 and threat_sweep_row.html:4, so the two cannot diverge |
| 193 | `spectre/web/templates/partials/admin_flash.html` | HTML/Jinja2 | 11 | source | no | CLEAN (S08): `{{ flash.message }}` autoescaped, no `/safe` |
| 194 | `spectre/web/templates/partials/admin_user_edit_row.html` | HTML/Jinja2 | 48 | source | no | CLEAN (S08): ids are ints, username autoescaped |
| 195 | `spectre/web/templates/partials/admin_user_row.html` | HTML/Jinja2 | 41 | source | no | CLEAN (S08): username autoescaped in text and in `hx-confirm`; quotes excluded from usernames by admin.py:46 |
| 196 | `spectre/web/templates/partials/admin_user_table.html` | HTML/Jinja2 | 10 | source | no | CLEAN (S08): loop and include only |
| 197 | `spectre/web/templates/partials/admin_user_table_region.html` | HTML/Jinja2 | 28 | source | no | CLEAN (S08): static markup and include |
| 198 | `spectre/web/templates/partials/all_intercepts_result.html` | HTML/Jinja2 | 465 | source | no | REVIEWED (S06): findings F-S06-03, 07, 18, 19, 33 |
| 199 | `spectre/web/templates/partials/blue_list.html` | HTML/Jinja2 | 20 | source | no | REVIEWED (S09): F-S09-26 |
| 200 | `spectre/web/templates/partials/blue_options.html` | HTML/Jinja2 | 5 | source | no | CLEAN (S09): autoescaped `{{ }}` output only; no `/safe`, script or handler (grep 0 hits) |
| 201 | `spectre/web/templates/partials/catalog_results.html` | HTML/Jinja2 | 54 | source | no | REVIEWED (S07): F-S07-25 |
| 202 | `spectre/web/templates/partials/clustering_summary.html` | HTML/Jinja2 | 91 | source | no | CLEAN (S06): display of the clustering summary only; multi-cluster, noise and fallback states are each declared to the operator (lines 23-49); all values |
| 203 | `spectre/web/templates/partials/data_mode_status.html` | HTML/Jinja2 | 1 | source | no | CLEAN (S07): one line rendering a validated mode (udl.py:342-343 forces it into _VALID_DATA_MODES), autoescaped |
| 204 | `spectre/web/templates/partials/decision_panel.html` | HTML/Jinja2 | 209 | source | no | REVIEWED (S09): F-S09-13 (bounds exist only as HTML min/max hints), F-S09-30 |
| 205 | `spectre/web/templates/partials/decision_results.html` | HTML/Jinja2 | 142 | source | no | REVIEWED (S09): F-S09-14 |
| 206 | `spectre/web/templates/partials/gcat_panel.html` | HTML/Jinja2 | 196 | source | no | CLEAN (S07): autoescaped context only; fetch_errors rendered through `join` in an attribute, autoescaped (gcat_panel.html:63) |
| 207 | `spectre/web/templates/partials/gcat_table.html` | HTML/Jinja2 | 230 | source | no | CLEAN (S07): the only JS-context interpolation is `dataset_key` (gcat_table.html:209), which gcat.py:550 restricts to the static DATASETS keys before ren |
| 208 | `spectre/web/templates/partials/gcat_welcome.html` | HTML/Jinja2 | 45 | source | no | REVIEWED (S07): scanned for `/safe`, script-context interpolation and error rendering only; none found. Not read line by line (see D) |
| 209 | `spectre/web/templates/partials/hrr_panel.html` | HTML/Jinja2 | 137 | source | no | REVIEWED (S07): F-S07-25 (hx-vals satno); `name` correctly goes through `tojson` (hrr_panel.html:55) |
| 210 | `spectre/web/templates/partials/intercept_geometry.html` | HTML/Jinja2 | 400 | source | no | CLEAN (S06): chart data embedded via `tojson` inside `JSON.parse` (line 167); rates arrive pre-converted as `burn_*_m_s` (geometry.py:211-213); tab ids i |
| 211 | `spectre/web/templates/partials/intercept_result.html` | HTML/Jinja2 | 446 | source | no | REVIEWED (S06): findings F-S06-07, 17, 18, 19, 22 |
| 212 | `spectre/web/templates/partials/maneuver_status.html` | HTML/Jinja2 | 15 | source | no | REVIEWED (S06): finding F-S06-35 (no renderer) |
| 213 | `spectre/web/templates/partials/notso_panel.html` | HTML/Jinja2 | 135 | source | no | REVIEWED (S07): scanned only; no `/safe` or script interpolation. Not read line by line (see D) |
| 214 | `spectre/web/templates/partials/notso_results.html` | HTML/Jinja2 | 228 | source | no | REVIEWED (S07): scanned only; no `/safe` or script interpolation. Heuristic labelling not assessed (see D) |
| 215 | `spectre/web/templates/partials/orbital_events.html` | HTML/Jinja2 | 49 | source | no | CLEAN (S06): the only values in onclick (lines 16, 36) are server-formatted `strftime` epochs, not operator strings; names are in text context and autoes |
| 216 | `spectre/web/templates/partials/osint_card.html` | HTML/Jinja2 | 73 | source | no | REVIEWED (S06): finding F-S06-35 (no renderer; duplicate of pair_card.html) |
| 217 | `spectre/web/templates/partials/pair_card.html` | HTML/Jinja2 | 73 | source | no | CLEAN (S06): escaped display of the intel record, with its source footnote shown (line 69) |
| 218 | `spectre/web/templates/partials/photometry_panel.html` | HTML/Jinja2 | 84 | source | no | REVIEWED (S07): scanned only; no `/safe` or script interpolation (see D) |
| 219 | `spectre/web/templates/partials/photometry_results.html` | HTML/Jinja2 | 140 | source | no | REVIEWED (S07): scanned only; renders p and t statistics and a confidence percentage (photometry_results.html:40,92); calibration of that figure is outside  |
| 220 | `spectre/web/templates/partials/pol_manoeuvre_detail.html` | HTML/Jinja2 | 290 | source | no | REVIEWED (S07): scanned only; no `/safe` or script interpolation (see D) |
| 221 | `spectre/web/templates/partials/pol_mc_results.html` | HTML/Jinja2 | 106 | source | no | REVIEWED (S07): scanned only; no `/safe` or script interpolation (see D) |
| 222 | `spectre/web/templates/partials/pol_panel.html` | HTML/Jinja2 | 122 | source | no | REVIEWED (S07): F-S07-18 |
| 223 | `spectre/web/templates/partials/pol_results.html` | HTML/Jinja2 | 1251 | source | no | REVIEWED (S07): 1,251 lines; scanned only. Script block interpolates `pol.satno` (int) and a literal boolean (pol_results.html:958-959), safe. The 12 unit s |
| 224 | `spectre/web/templates/partials/red_list.html` | HTML/Jinja2 | 20 | source | no | REVIEWED (S09): F-S09-26 |
| 225 | `spectre/web/templates/partials/red_options.html` | HTML/Jinja2 | 5 | source | no | CLEAN (S09): autoescaped `{{ }}` output only; no `/safe`, script or handler (grep 0 hits) |
| 226 | `spectre/web/templates/partials/red_orbit_info.html` | HTML/Jinja2 | 13 | source | no | CLEAN (S06): escaped numeric formatting only; the GMST longitude it shows was hand-checked (D, note 1) |
| 227 | `spectre/web/templates/partials/results_table.html` | HTML/Jinja2 | 30 | source | no | CLEAN (S06): escaped access-window table with units in every heading; included at operator.html:536 |
| 228 | `spectre/web/templates/partials/run_log.html` | HTML/Jinja2 | 7 | source | no | CLEAN (S09): each log entry autoescaped at :3; no `/safe`, script or handler |
| 229 | `spectre/web/templates/partials/sat_select_oob.html` | HTML/Jinja2 | 12 | source | no | CLEAN (S09): OOB select wrappers that include the two option partials; no `/safe`, script or handler |
| 230 | `spectre/web/templates/partials/screen_config.html` | HTML/Jinja2 | 52 | source | no | CLEAN (S06): asset selector carrying the synthetic-provenance banner at lines 38-51; all values escaped |
| 231 | `spectre/web/templates/partials/splash_overlay.html` | HTML/Jinja2 | 135 | source | no | REVIEWED (S09): F-S09-29, F-S09-30 |
| 232 | `spectre/web/templates/partials/statevector_fields.html` | HTML/Jinja2 | 28 | source | no | CLEAN (S07): 28 lines, autoescaped `error` and `sv` fields only |
| 233 | `spectre/web/templates/partials/sweep_fetch_status.html` | HTML/Jinja2 | 12 | source | no | CLEAN (S06): three-state badge; failed count shown to the operator at lines 7-9 |
| 234 | `spectre/web/templates/partials/sweep_manual_tles.html` | HTML/Jinja2 | 63 | source | no | REVIEWED (S06): finding F-S06-37 |
| 235 | `spectre/web/templates/partials/sweep_target_config.html` | HTML/Jinja2 | 129 | source | no | REVIEWED (S06): findings F-S06-27, 36 |
| 236 | `spectre/web/templates/partials/threat_screen.html` | HTML/Jinja2 | 191 | source | no | REVIEWED (S06): findings F-S06-04, 10 |
| 237 | `spectre/web/templates/partials/threat_sweep.html` | HTML/Jinja2 | 574 | source | no | REVIEWED (S06): findings F-S06-03, 04, 10, 31 |
| 238 | `spectre/web/templates/partials/threat_sweep_row.html` | HTML/Jinja2 | 58 | source | no | REVIEWED (S06): finding F-S06-03 |
| 239 | `spectre/web/templates/partials/tle_fields.html` | HTML/Jinja2 | 21 | source | no | REVIEWED (S07): claim B10; 7-day STALE threshold literal duplicated from the udl.py docstring with no shared constant |
| 240 | `spectre/web/templates/partials/tle_source_panel.html` | HTML/Jinja2 | 16 | source | no | CLEAN (S07): autoescaped `<option>` list built from UDL source names |
| 241 | `spectre/web/templates/partials/tle_source_status.html` | HTML/Jinja2 | 5 | source | no | CLEAN (S07): 5 lines, autoescaped `tle_source` |
| 242 | `spectre/web/templates/partials/trade_space_chart.html` | HTML/Jinja2 | 149 | source | no | REVIEWED (S06): finding F-S06-35 (no renderer) |
| 243 | `spectre/web/templates/partials/training_dashboard.html` | HTML/Jinja2 | 216 | source | no | REVIEWED (S09): F-S09-18 |
| 244 | `spectre/web/templates/partials/training_debrief.html` | HTML/Jinja2 | 145 | source | no | REVIEWED (S09): F-S09-07 (optimal percentage unreachable), F-S09-38 |
| 245 | `spectre/web/templates/partials/training_scenario_active.html` | HTML/Jinja2 | 224 | source | no | REVIEWED (S09): F-S09-05, F-S09-19; `/safe` removed, comment at :48-54 matches `white-space:pre-line` sink at :55 |
| 246 | `spectre/web/templates/partials/training_scenario_detail.html` | HTML/Jinja2 | 121 | source | no | REVIEWED (S09): F-S09-36 |
| 247 | `spectre/web/templates/partials/training_scenario_list.html` | HTML/Jinja2 | 76 | source | no | REVIEWED (S09): F-S09-30 (hx-on needs 'unsafe-eval'), F-S09-36 |
| 248 | `spectre/web/templates/partials/training_tutorial.html` | HTML/Jinja2 | 46 | source | no | REVIEWED (S09): F-S09-03 (offers completion of any tutorial id the route accepts) |
| 249 | `spectre/web/templates/partials/training_tutorial_complete.html` | HTML/Jinja2 | 58 | source | no | REVIEWED (S09): F-S09-30 (inline onclick at :53); values autoescaped |
| 250 | `spectre/web/templates/partials/udl_status.html` | HTML/Jinja2 | 89 | source | no | REVIEWED (S07): never renders the password; only `udl_user` (username) and `error` (udl_status.html:3,35), both autoescaped; `autocomplete="off"` on the pas |
| 251 | `spectre/web/templates/training.html` | HTML/Jinja2 | 308 | source | no | REVIEWED (S09): F-S09-06, F-S09-30 |
| 252 | `spectre_icon_family.svg` | SVG | 109 | asset | no | REVIEWED (S10): F-S10-34 (byte-identical to static copy, O8) |
| 253 | `spectre_icon_mark.svg` | SVG | 47 | asset | no | REVIEWED (S10): F-S10-34 (O8) |
| 254 | `spectre_logo_primary.svg` | SVG | 46 | asset | no | REVIEWED (S10): F-S10-34 (O8) |
| 255 | `spectre_splash_screen.html` | HTML/Jinja2 | 85 | asset | no | REVIEWED (S10): F-S10-34 (unreferenced fragment) |
| 256 | `tests/__init__.py` | Python | 0 | test | no | CLEAN (S08): empty |
| 257 | `tests/conftest.py` | Python | 45 | test | no | CLEAN (S08): fixtures; `csrf_headers` mints a real token rather than disabling the control |
| 258 | `tests/integration/__init__.py` | Python | 0 | test | no | CLEAN (S08): empty |
| 259 | `tests/integration/conftest.py` | Python | 67 | test | no | CLEAN (S08): environment and client fixtures only |
| 260 | `tests/integration/test_admin_bootstrap.py` | Python | 176 | test | no | CLEAN (S08): every bootstrap branch asserted on users table and log text (lines 55-176) |
| 261 | `tests/integration/test_admin_routes.py` | Python | 357 | test | no | REVIEWED (S08): finding F-S08-14 |
| 262 | `tests/integration/test_all_intercepts_ranking.py` | Python | 208 | test | no | REVIEWED (S06): finding F-S06-30; otherwise strong: real route, vacuity guards at lines 69-72 and 185-198 |
| 263 | `tests/integration/test_audit_log_integrity.py` | Python | 194 | test | no | CLEAN (S08): asserts refusal content and single-line log records (lines 65-194) |
| 264 | `tests/integration/test_login_hardening.py` | Python | 470 | test | no | REVIEWED (S08): findings F-S08-01 (gap), F-S08-20 |
| 265 | `tests/integration/test_packager_gates.py` | Python | 249 | test | no | REVIEWED (S10): pins the packager's refusal paths behaviourally (ledger, two probes, untracked ledger, non-app material, stray Markdown, docker-only manifes |
| 266 | `tests/integration/test_plan_export.py` | Python | 415 | test | no | CLEAN (S09): behavioural assertions on cell text and header bytes, including self-checks that the seeded run reached the file (:183, :202, :224) |
| 267 | `tests/integration/test_root_contract.py` | Python | 105 | test | no | CLEAN (S08): asserts body content, not only status (lines 15-105) |
| 268 | `tests/integration/test_security_headers.py` | Python | 277 | test | no | CLEAN (S08): pins CSP character for character and HSTS branches (lines 144-273) |
| 269 | `tests/integration/test_threat_screen_route.py` | Python | 169 | test | no | REVIEWED (S06): finding F-S06-28 (clears the whole shared cache at lines 121, 141) |
| 270 | `tests/integration/test_tle_clustering_pipeline.py` | Python | 322 | test | no | REVIEWED (S09): F-S09-32 |
| 271 | `tests/integration/test_web_routes.py` | Python | 197 | test | no | REVIEWED (S09): F-S09-16 (scenario-time invalid case asserts `b"Invalid" ... or b"error"` at :140) |
| 272 | `tests/integration/test_web_routes_extended.py` | Python | 640 | test | no | REVIEWED (S09): F-S09-16 |
| 273 | `tests/integration/test_xss_escaping.py` | Python | 236 | test | no | CLEAN (S08): asserts escaped output for six injection points (lines 116-236) |
| 274 | `tests/unit/__init__.py` | Python | 0 | test | no | CLEAN (S08): empty |
| 275 | `tests/unit/conftest.py` | Python | 27 | test | no | CLEAN (S08): client fixture only |
| 276 | `tests/unit/test_actor_screening.py` | Python | 203 | test | no | CLEAN (S05): pins rank order (verdict, then warning time, then cost), the disagreement sentence and "nothing dropped" with exact assertions at tests/unit |
| 277 | `tests/unit/test_astro.py` | Python | 233 | test | no | REVIEWED (S01): finding F-S01-21 |
| 278 | `tests/unit/test_auth.py` | Python | 49 | test | no | REVIEWED (S08): findings F-S08-12, F-S08-14 (duplicate tests) |
| 279 | `tests/unit/test_cognitive_complexity_meter.py` | Python | 256 | test | no | REVIEWED (S10): pins 15 scoring rules by exact score and runs `--calibrate`; no case for `finally`, `try`/`else`, loop `else`, `match`, or a BoolOp nested i |
| 280 | `tests/unit/test_config_settings.py` | Python | 467 | test | no | CLEAN (S08): sslmode, DAST key and data-dir branches asserted (lines 42-467) |
| 281 | `tests/unit/test_contrast_floors.py` | Python | 728 | test | no | REVIEWED (S09): F-S09-35 (helpers duplicated); otherwise computes WCAG ratios from parsed tokens |
| 282 | `tests/unit/test_csrf.py` | Python | 229 | test | no | REVIEWED (S08): finding F-S08-14 (weak exempt assertion, duplicates) |
| 283 | `tests/unit/test_cw_geometry.py` | Python | 528 | test | no | REVIEWED (S02): finding F-S02-28 (rotating-frame velocity in `_initial_hill_state` only checked for finiteness); `_cw_propagate` pinned to closed form at li |
| 284 | `tests/unit/test_dark_surfaces_in_steel.py` | Python | 410 | test | no | CLEAN (S09): parses CSS rule blocks and asserts resolved token values per selector; 18 tests, 34 asserts; includes a cascade-model check at :171-205 |
| 285 | `tests/unit/test_db_pool_contract.py` | Python | 140 | test | no | CLEAN (S08): pool kwargs per dialect asserted including the engine actually built (line 125) |
| 286 | `tests/unit/test_decision.py` | Python | 304 | test | no | REVIEWED (S05): finding F-S05-18 (selectors asserted only by type; no composite value pinned; TLE path never run) |
| 287 | `tests/unit/test_deployment_contract.py` | Python | 1591 | test | no | REVIEWED (S10): 78 tests, almost all regex or substring checks on file text (Dockerfile, packager, lockfiles), not behaviour; F-S10-13 |
| 288 | `tests/unit/test_docs_are_committable.py` | Python | 134 | test | no | REVIEWED (S10): pins that a new docs file is not git-ignored and that docs are excluded from image, package and Sonar scope by string checks (lines 110-134) |
| 289 | `tests/unit/test_domain_models.py` | Python | 97 | test | no | CLEAN (S05): pins stk_name prefixing, duration arithmetic and run_id generation with exact equality; pure dataclass checks |
| 290 | `tests/unit/test_dv_estimation.py` | Python | 725 | test | no | REVIEWED (S04): finding F-S04-15; pins Hohmann exact total (rel 0.01 to 0.02), 2·v·sin(Δi/2) (rel 0.02), v·Δe (rel 0.05), J2 argp closed form (rel 1e-9), pe |
| 291 | `tests/unit/test_entrypoint.py` | Python | 66 | test | no | CLEAN (S08): asserts uvicorn arguments (lines 31-66) |
| 292 | `tests/unit/test_exceptions.py` | Python | 32 | test | no | CLEAN (S05): four inheritance and message checks on trivial classes; nothing more to pin |
| 293 | `tests/unit/test_focus_visible_indicator.py` | Python | 353 | test | no | REVIEWED (S09): F-S09-35 |
| 294 | `tests/unit/test_geometry.py` | Python | 200 | test | no | REVIEWED (S02): finding F-S02-32 |
| 295 | `tests/unit/test_health.py` | Python | 166 | test | no | CLEAN (S08): probe success, errno, timeout and body disclosure asserted (lines 19-166) |
| 296 | `tests/unit/test_hrr_bootstrap.py` | Python | 253 | test | no | REVIEWED (S07): sound provenance tests (:181-193). They create probe files inside the working tree (:87-88,105-107), a side effect on the repository. The po |
| 297 | `tests/unit/test_hrr_dropdown_is_text.py` | Python | 116 | test | no | CLEAN (S07): static assertions that the HRR dropdown builds DOM text nodes, not innerHTML (:53-116) |
| 298 | `tests/unit/test_hrr_preload.py` | Python | 82 | test | no | CLEAN (S07): covers present, absent, empty, malformed and wrong-shape HRR files with log assertions (:42-82) |
| 299 | `tests/unit/test_intercept_envelope.py` | Python | 467 | test | no | CLEAN (S02): pins `intercept_envelope_intercept` to an independently recomputed 24-step Lambert sweep (lines 89-118) with rel 1e-12, plus boundary and un |
| 300 | `tests/unit/test_intercept_intel_characterisation.py` | Python | 173 | test | no | CLEAN (S05): declared characterisation tests of spectre/web/routes/maneuver._compute_intercept_intel (outside this slice), asserting exact band strings p |
| 301 | `tests/unit/test_lambert_validation.py` | Python | 218 | test | no | REVIEWED (S01): findings F-S01-04 (no long-TOF case), F-S01-03 (no retrograde case), F-S01-21 |
| 302 | `tests/unit/test_log_safety.py` | Python | 86 | test | no | CLEAN (S08): line-break, control-char, truncation asserted (lines 30-86); limit below 3 not covered, see F-S08-19 |
| 303 | `tests/unit/test_maneuver_planner.py` | Python | 82 | test | no | CLEAN (S05): one test per validation branch of validate_search_config, all with pytest.raises or explicit pass |
| 304 | `tests/unit/test_manoeuvre_calibration.py` | Python | 223 | test | no | REVIEWED (S05): findings F-S05-13, F-S05-14 (provenance test checks only for the substring "Table"; "most permissive" test pins the mapping, not permissiven |
| 305 | `tests/unit/test_monte_carlo.py` | Python | 188 | test | no | REVIEWED (S04): finding F-S04-26; smoke and property tests only, no physics reference, hypothesis_from_tle_record untested |
| 306 | `tests/unit/test_notso.py` | Python | 467 | test | no | REVIEWED (S03): findings F-S03-33; no test for the field-borne ΔV path (F-S03-07), mid-message MSGID (F-S03-09), date fallbacks (F-S03-08), midpoint tie-bre |
| 307 | `tests/unit/test_notso_cache.py` | Python | 156 | test | no | REVIEWED (S07): F-S07-03 (the fixtures pin a record shape the real data does not have), F-S07-26 (vacuous assertion) |
| 308 | `tests/unit/test_operator_sees_metres_per_second.py` | Python | 550 | test | no | REVIEWED (S06): finding F-S06-30 (static guard cannot see runtime solver text) |
| 309 | `tests/unit/test_orbital_units_and_degeneracies.py` | Python | 356 | test | no | REVIEWED (S01): findings F-S01-01 (static guard blind to `_m.degrees`), F-S01-17 (no retrograde equatorial case) |
| 310 | `tests/unit/test_outbound_and_ddl_guards.py` | Python | 304 | test | no | CLEAN (S08): DDL guard asserted on every real migration and injected fragments (lines 232-304) |
| 311 | `tests/unit/test_pattern_of_life.py` | Python | 402 | test | no | REVIEWED (S03): findings F-S03-34; no detection pinned to a known reference burn |
| 312 | `tests/unit/test_photometry.py` | Python | 394 | test | no | REVIEWED (S04): finding F-S04-26; t-test and incomplete Beta checked only for bounds and gross separation, no reference p-value |
| 313 | `tests/unit/test_planning_state.py` | Python | 62 | test | no | CLEAN (S08): isolation, clear and deque eviction asserted (lines 18-62) |
| 314 | `tests/unit/test_pol_assessment.py` | Python | 577 | test | no | REVIEWED (S05): finding F-S05-10 (graveyard fixture uses an altitude inconsistent with its own "300 km" label); physics reference cases at :399-421 are good |
| 315 | `tests/unit/test_pol_status_ladder.py` | Python | 91 | test | no | REVIEWED (S03): boundaries pinned at tests/unit/test_pol_status_ladder.py:69-91, but on a PolStats that a real history cannot produce (F-S03-01) |
| 316 | `tests/unit/test_quality_gate_scope.py` | Python | 358 | test | no | REVIEWED (S10): pins merge-base anchoring, untracked-file inclusion and working-tree diffing for `check-quality.sh` text and `sonar_scope.py`; does not cove |
| 317 | `tests/unit/test_rate_limit_memory.py` | Python | 239 | test | no | CLEAN (S08): key count, key length and budget recovery asserted (lines 34-239) |
| 318 | `tests/unit/test_scenario.py` | Python | 24 | test | no | REVIEWED (S05): finding F-S05-08 (only empty and invalid-TLE cases; range detection never exercised) |
| 319 | `tests/unit/test_settings.py` | Python | 37 | test | no | CLEAN (S08): defaults and env override asserted (lines 13-37) |
| 320 | `tests/unit/test_sort_state_and_panel_exit.py` | Python | 199 | test | no | CLEAN (S09): template-source assertions on aria-sort, Escape scoping and focus handling; 15 tests, 21 asserts |
| 321 | `tests/unit/test_tactical.py` | Python | 612 | test | no | REVIEWED (S02): findings F-S02-26, F-S02-27, F-S02-28 |
| 322 | `tests/unit/test_tactical_validation.py` | Python | 180 | test | no | CLEAN (S02): phasing (lines 41-60, abs 1 km), NMC flown through `_cw_propagate` (86-122, rel 2%), GEO drift (156-163, rel 1%), graveyard (165-172, rel 1e |
| 323 | `tests/unit/test_template_markup_is_well_formed.py` | Python | 154 | test | no | REVIEWED (S09): F-S09-05 (gate checks table tags only, not nested `<form>`) |
| 324 | `tests/unit/test_threat_assessment.py` | Python | 199 | test | no | CLEAN (S05): pins weaker-side-governs, degraded and spent overrides, unassessed fallback and confidence counting with exact Band equality at tests/unit/t |
| 325 | `tests/unit/test_threat_screen_template.py` | Python | 230 | test | no | REVIEWED (S06): finding F-S06-28 |
| 326 | `tests/unit/test_threat_sweep.py` | Python | 390 | test | no | REVIEWED (S06): finding F-S06-28 |
| 327 | `tests/unit/test_threat_sweep_row_styles.py` | Python | 227 | test | no | CLEAN (S06): contract tests read the real stylesheet and both templates; every assertion is on real files (lines 112-151), none on mocks |
| 328 | `tests/unit/test_threat_sweep_template.py` | Python | 199 | test | no | REVIEWED (S06): finding F-S06-28 |
| 329 | `tests/unit/test_tle_filter.py` | Python | 258 | test | no | REVIEWED (S03): finding F-S03-35; no test of a chained cluster spanning a burn (F-S03-05) |
| 330 | `tests/unit/test_tle_line_truncation.py` | Python | 47 | test | no | CLEAN (S01): three real assertions on pattern_of_life.parse_tle_history truncation at tests/unit/test_tle_line_truncation.py:25-47, including value equal |
| 331 | `tests/unit/test_token_channels_match.py` | Python | 159 | test | no | CLEAN (S09): compares rgb triples to their hex tokens and self-tests that the comparison can fail (:155) |
| 332 | `tests/unit/test_training_gamification.py` | Python | 387 | test | no | REVIEWED (S09): F-S09-07, F-S09-17 |
| 333 | `tests/unit/test_udl_tle_fetch.py` | Python | 495 | test | no | REVIEWED (S07): F-S07-26 (contradictory test names); epoch selection helpers well pinned (:393-458) |
| 334 | `tests/unit/tle_clustering/__init__.py` | Python | 0 | test | no | CLEAN (S09): empty package marker (0 lines) |
| 335 | `tests/unit/tle_clustering/conftest.py` | Python | 184 | test | no | REVIEWED (S09): F-S09-32 |
| 336 | `tests/unit/tle_clustering/test_clustering.py` | Python | 215 | test | no | REVIEWED (S09): F-S09-32 |
| 337 | `tests/unit/tle_clustering/test_integration.py` | Python | 113 | test | no | REVIEWED (S09): F-S09-32 |
| 338 | `tests/unit/tle_clustering/test_parser.py` | Python | 110 | test | no | CLEAN (S09): pins extracted inclination, RAAN and eccentricity to literal TLE values with stated tolerances (:17-30) |
| 339 | `tests/unit/tle_clustering/test_selection.py` | Python | 82 | test | no | CLEAN (S09): asserts identity of the selected member, including the recency tie-break (:40-68) |
| 340 | `tle_clustering/__init__.py` | Python | 111 | source | no | CLEAN (S09): thin composition of parse, group and cluster; behaviour pinned by tests/unit/tle_clustering/test_integration.py:15-113 |
| 341 | `tle_clustering/clustering.py` | Python | 243 | source | no | REVIEWED (S09): F-S09-10, F-S09-11, F-S09-12 |
| 342 | `tle_clustering/config.py` | Python | 135 | source | no | REVIEWED (S09): F-S09-31 |
| 343 | `tle_clustering/models.py` | Python | 174 | source | no | CLEAN (S09): frozen dataclasses; derived counts computed from members so they cannot drift (:141-174) |
| 344 | `tle_clustering/parser.py` | Python | 169 | source | no | REVIEWED (S09): F-S09-11 (elements taken at each TLE's own epoch) |
| 345 | `tle_clustering/selection.py` | Python | 136 | source | no | REVIEWED (S09): F-S09-10 (RAAN difference not wrapped) |

## Phase markers

| Phase | Status | Completed | Artefact | Exit check |
|---|---|---|---|---|
| Pre-flight | DONE | 2026-10-23 | this file | tree clean, HEAD `a34e273` |
| 1 Inventory and charter | DONE | 2026-10-23 | `audit/LEDGER.md` | 345 ledger rows = 345 index entries = 344 files on disk + 1 gitlink |
| 2 Deterministic sweep | DONE | 2026-10-23 | `audit/TOOLS.md`, `audit/tools-raw/` (36 files) | every tool produced output or is recorded unavailable: safety UNAVAILABLE (no network route to its database); Docker-dependent gate scripts not run (no daemon) |
| 3 Architecture and flow | DONE | 2026-10-23 | `audit/ARCHITECTURE.md` | 9 entry-point classes, 74 HTTP handlers traced by router group to sinks; 10 documented-versus-code divergences (A1 to A10) |
| 4 Claims reconciliation | DONE | 2026-10-23 | `audit/CLAIMS.md` | 316 claims, none blank: 94 PROVEN, 126 DRIFTED, 72 IMPLEMENTED-UNTESTED, 13 ABSENT, 11 UNDOCUMENTED-BEHAVIOUR |
| 4b Prior-audit verification | DONE | 2026-10-23 | `audit/PRIORS-STATUS.md` | 10 of 10 priors carry a verdict and citation; gates tested by mutation (P1 fires, P3 does not) |
| 5 Lens review | DONE | 2026-10-23 | slice reviews S01 to S10 under `audit/LENS-BRIEF.md` | no PENDING rows: 216 REVIEWED, 116 CLEAN, 13 EXCLUDED with reasons |
| 6 Test and assertion audit | DONE | 2026-10-23 | `audit/TESTS.md` | 76 of 76 test files classified; 457 risk-bearing branch arcs named; 22 mutants, 8 meaningful survivors |
| 7 Refutation | DONE | 2026-10-23 | `audit/REFUTATION.md` | 317 candidates: 296 CONFIRMED, 14 REFUTED, 4 UNPROVEN, 3 DUPLICATE; quote mismatch 0 of 317 |
| 8 Synthesis | DONE | 2026-10-23 | `audit/FINDINGS.md`, `audit/REMEDIATION.md`, `audit/MANIFEST.json`, `audit/GAPS.md` | 8 Blocker, 49 High, 127 Medium, 112 Low; every finding gated |
