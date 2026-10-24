"""Assemble audit/TOOLS.md from audit/tools-raw. Usage: tools_md.py <repo>"""
import sys, os
repo = sys.argv[1]; R = os.path.join(repo, "audit/tools-raw")
def raw(name, limit=45, head=25):
    t = open(os.path.join(R, name), encoding="utf-8", errors="replace").read().rstrip("\n").splitlines()
    if len(t) <= limit:
        return "```\n" + "\n".join(t) + "\n```\n"
    return (f"Output is {len(t)} lines; full verbatim text in `audit/tools-raw/{name}`. First {head} and last 5 lines:\n\n```\n"
            + "\n".join(t[:head]) + "\n...\n" + "\n".join(t[-5:]) + "\n```\n")
S = []
def sec(title, cmd_note, files, extra=""):
    S.append(f"## {title}\n\n{cmd_note}\n\n" + "".join(raw(f) if isinstance(f, str) else raw(*f) for f in files) + (("\n" + extra + "\n") if extra else "") + "\n")
sec("0. Environment and install reproducibility",
    "Interpreter: CPython 3.12.3 in a fresh virtualenv, matching `ci.yml` (`python-version: \"3.12\"`) and the image base. All tools ran against a local clone of HEAD `a34e273` so the audited tree stayed unmodified; caches went to scratch. Path substitution: the scratch clone path is shown as `<clone>`, the virtualenv as `<venv>`. ANSI colour codes stripped. Nothing else is altered.\n\n**0a. Declared install**, `pip install -e \".[dev]\"` (README.md:41, ci.yml:31,48,185), reproduced with uv:",
    ["install_declared.txt"],
    "Fact: no extra named `dev` exists, and the command installs the `spectre` package with no runtime or tool dependencies. On a clean runner, the CI steps that follow it (`ruff`, `mypy`, `pytest`) would have no executable unless the runner image supplies one. Inference: the GitHub `ci.yml` cannot pass as written on a stock `ubuntu-latest` runner. TBC, re-verify against the CI run history for `master`.\n\n**0b. Combined locked install**, `uv pip install --require-hashes -r requirements.txt -r requirements-dev.txt`:")
S.append(raw("install_locked_combined.txt") + "\nFact: `requirements.txt:1370` pins `tomli==2.5.0` and `requirements-dev.txt:1025` pins `tomli==2.4.1`. The audit environment was built by installing `requirements.txt` with hashes, then `requirements-dev.txt` with hashes over it (which replaced tomli), then `pip install --no-deps -e .`. Audit-only tools not in any lockfile, installed unpinned at latest: black, pyright, radon, vulture, safety, mutmut. gitleaks 8.18.4 (the CI pin) from the GitHub release; jscpd 4.0.5 from npm.\n\n")
S.append("""### Tool versions

| Tool | Version | Source |
|---|---|---|
| Python | 3.12.3 | system |
| ruff | 0.16.5 | requirements-dev.txt |
| mypy | 2.3.1 | requirements-dev.txt |
| bandit | 1.9.4 | requirements-dev.txt |
| pip-audit | 2.10.1 | requirements-dev.txt |
| pytest | 9.1.1 | requirements.txt |
| coverage | 7.15.4 | requirements.txt |
| black | 26.10.1 | audit-only, unpinned |
| pyright | 1.1.414 | audit-only, unpinned |
| radon | 6.0.1 | audit-only, unpinned |
| vulture | 2.16 | audit-only, unpinned |
| safety | installed, version not printed (see section 7) | audit-only, unpinned |
| gitleaks | 8.18.4 | CI pin |
| jscpd | 4.0.5 | npm |
| cognitive complexity | `scripts/cognitive_complexity.py` (project script, SonarSource S3776 reimplementation) | in-repo |

""")
sec("1. ruff", "**1a. As CI runs it** (`ci.yml:33`), project config:", ["ruff_ci.txt"],
    "**1b. Whole tree** (`ruff check .`, the audit spec), project config:\n\n" + raw("ruff_dot.txt") +
    "\nFact: the 3 findings are all in `query_UDL_Data.py`, which CI does not lint because CI scopes to `spectre/ tests/`.\n\n**1c. House rule set from `scripts/check-quality.sh:27-28`, applied to the whole of `spectre/` and `tle_clustering/`** rather than to changed lines only:\n\n" + raw("ruff_house_stats.txt") +
    "\nPer-site list: `audit/tools-raw/ruff_house.txt`. Fact: the quality gate applies this rule set only to lines changed against the base branch (`check-quality.sh` `changed_in`), so the 432 existing findings are invisible to it by design.")
sec("2. black", "`black --check .`. The project does not declare black; ruff is its declared formatter-adjacent linter. Recorded because the audit spec requires it.", [("black.txt", 10, 5)])
sec("3. mypy", "**3a. As CI runs it** (`ci.yml:35`):", ["mypy_ci.txt"],
    "**3b. `mypy --strict`, bare, as the audit spec words it:**\n\n" + raw("mypy_strict_bare.txt") +
    "\nFact: `pyproject.toml [tool.mypy]` sets no `files`, so the bare command has no target.\n\n**3c. `mypy --strict spectre tle_clustering`:**\n\n" + raw("mypy_strict.txt") +
    "\n**3d. `mypy --strict tests`** (not gated anywhere):\n\n" + raw("mypy_strict_tests.txt", 10, 6) +
    "\nBy error code: 355 `no-untyped-def`, 71 `no-untyped-call`, 42 `attr-defined`, 13 `arg-type`, 12 `type-arg`, 10 `operator`, remainder in the raw file.\n\n**3e. `mypy --strict` over `scripts/`, `query_UDL_Data.py`, `docs/*.py`** (not gated):\n\n" + raw("mypy_strict_scripts.txt", 10, 6))
sec("4. pyright", "**4a. Product code**, `pyright spectre tle_clustering`, default (basic) mode, no project config:", ["pyright.txt"],
    "Fact: mypy strict passes on the same files while pyright reports 5 errors. Per G2, the gap is recorded and not explained away: mypy runs with `ignore_missing_imports = true` (`pyproject.toml:101`), which turns pandas and sgp4 types into `Any`, and pyright does not. That explains the `gcat.py:476` DataFrame case (inference). It does not obviously explain `training.py:168` (\"Operator - not supported for None\") or `intel.py:23` (an Optional return where a non-Optional is declared). Both are for phase 5 to reopen.\n\n**4b. Whole Python surface** (`spectre tle_clustering scripts tests query_UDL_Data.py`): 94 errors. Spread by top-level directory of the reporting file: 4 in spectre, 1 in scripts, 14 in tests (files, not errors). By rule: 41 reportAttributeAccessIssue, 30 reportArgumentType, 5 reportOptionalMemberAccess, 4 reportOperatorIssue, 4 reportAssignmentType, 3 reportIndexIssue, 2 reportOptionalOperand, 2 reportCallIssue, 1 each reportReturnType, reportRedeclaration, reportPossiblyUnboundVariable. Full text: `audit/tools-raw/pyright_all.txt`.")
sec("5. bandit", "**5a. As CI runs it** (`ci.yml:76`, `-ll`, scope `spectre/`):", ["bandit_ci.txt"],
    "**5b. All severities, whole Python surface** (`spectre tle_clustering scripts query_UDL_Data.py docs`):\n\n" + raw("bandit_all.txt", 10, 4) + """
Every issue, verbatim location, test id and severity:

| Location | Test | Severity |
|---|---|---|
| `query_UDL_Data.py:22:9` | B501 request_with_no_cert_validation | **High** |
| `query_UDL_Data.py:22:9` | B113 request_without_timeout | Medium |
| `docs/build_gcat_workbook_1.py:105:13` | B310 urlopen scheme | Medium |
| `scripts/smoke-browser.py:140:21` | B310 urlopen scheme | Medium |
| `docs/build_gcat_workbook_1.py:193:8` | B112 try_except_continue | Low |
| `scripts/cognitive_complexity.py:68,354,360,390,457` | B404, B603 x4 | Low |
| `scripts/smoke-browser.py:42,52,53,124` | B404, B105 x2, B603 | Low |
| `scripts/sonar_scope.py:17,26` | B404, B607, B603 | Low |
| `spectre/domain/decision.py:231:8` | B110 try_except_pass | Low |
| `spectre/web/csrf.py:91:24` | B105 hardcoded_password_string (`''`) | Low |
| `spectre/web/database.py:213:29` | B106 hardcoded_password_funcarg (`''`) | Low |

Fact: the CI gate at `-ll` on `spectre/` is clean. The only High and Medium findings fall outside CI's scope. `query_UDL_Data.py` is excluded from the image by `.dockerignore`, but it is tracked at the repository root.""")
sec("6. pip-audit", "**6a. As CI runs it, `requirements.txt`** (with `--no-deps --disable-pip`, because the file is fully hash-pinned):", ["pip_audit_req.txt"],
    "**6b. `requirements-runtime.txt`:**\n\n" + raw("pip_audit_runtime.txt") + "\n**6c. `requirements-dev.txt`** (not audited by CI):\n\n" + raw("pip_audit_dev.txt", 8, 4) +
    "\nFact: urllib3 2.7.0 at `requirements-dev.txt:1094`, with 3 advisories (PYSEC-2026-4175, PYSEC-2026-4176, PYSEC-2026-4177), fixed in 2.8.0. It is reached only through `requests` in the dev set. It is absent from `requirements.txt` and `requirements-runtime.txt`, so it does not ship in the image (fact, grep). Vendored JavaScript (Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.JS 2.0.7, htmx 1.9.12) is not covered by any SCA tool in this repository.")
sec("7. safety", "`safety check -r requirements.txt --full-report`:", [("safety.txt", 10, 6)],
    "**Unavailable.** Fact: safety needs its online vulnerability database. DNS resolution failed through this environment's network policy (`httpx.ConnectError: [Errno -2] Name or service not known`). Not simulated. pip-audit (section 6) is the SCA evidence for this run.")
sec("8. gitleaks", "**8a. History**, as CI runs it (`ci.yml:109`), 96 commits:", ["gitleaks_hist.txt"], "**8b. Working tree, `--no-git`** (README.md:286):\n\n" + raw("gitleaks_tree.txt") + "\nFact: neither scan reports a leak. Gitleaks does not open the binary archive `bluestaq-foundations-v1.99.0.zip` or `docs/SPECTRE_Operator_Guide.docx`, so their contents are unscanned (gap).")
sec("9. pytest with branch coverage", "Command, as CI (`ci.yml:53-55`) plus `--cov=tle_clustering --cov-branch` and the project `addopts = \"-ra -q\"`. `SECRET_KEY` set to the CI value. The integration marker was not deselected, matching CI.", [("pytest.txt", 45, 30)],
    """### Result

| Measure | Value | Evidence |
|---|---|---|
| Collected | 1,898 | `audit/tools-raw/collect.txt`, summed per file |
| Passed | 1,896 | progress dots in `pytest.txt` |
| Failed | 0 | as above |
| Skipped | 2 | `tests/unit/test_deployment_contract.py:796`, `:813` "python template: manifests ship by design" |
| Errors | 0 | as above |
| Exit | 0 | `pytest.txt` last line |
| Statements | 9,341, 7,879 covered, **84.35 %** | coverage JSON totals |
| Branches | 2,156, 1,530 covered, **70.96 %**, 304 partial | coverage JSON totals |
| Combined (coverage.py "TOTAL") | **81.84 %**, floor 74 met | `pytest.txt:127,130` |
| Warnings | 1 StarletteDeprecationWarning and 181 cookie DeprecationWarnings in integration tests | `pytest.txt` warnings summary |
| Wall time, slowest | 8.94 s, `test_monte_carlo.py::TestRunMonteCarlo::test_leo_stays_in_leo` | durations block |

Lowest-covered modules (combined line and branch percentage, from the term-missing table): `spectre/web/routes/udl.py` 37 %, `routes/pol.py` 38 %, `routes/threat.py` 48 %, `routes/gcat.py` 56 %, `domain/scenario.py` 64 %, `routes/training.py` 70 %, `tle_clustering/config.py` 71 %. The full table is in `audit/tools-raw/pytest.txt`.

Fact: the unit and integration suites were not split in this run. Whether any test reaches the live network was not established (the `integration` marker is declared in `pyproject.toml:58`, but no test was found carrying it by grep of `pytest.mark.integration`; TBC, re-verify by running with `-m integration --collect-only`).""")
sec("10. Complexity", "**10a. radon cyclomatic complexity, grade C and worse:**", [("radon_cc.txt", 10, 8)],
    "Fact: 23 functions or methods have cyclomatic complexity above 15 (counted from the raw output). The highest is `spectre/astro/notso.py:319 _parse_single_notso` at F (48). Average across 755 blocks: A (4.11), from `radon_cc_all.txt`.\n\n**10b. radon maintainability index, B and worse:**\n\n" + raw("radon_mi.txt") +
    "\n**10c. Cognitive complexity, project meter (`scripts/cognitive_complexity.py --max 15`), whole tree:**\n\n" + raw("cogcx_run.txt", 30, 30) + "\nCalibration self-check (`--calibrate`):\n\n" + raw("cogcx_cal.txt", 8, 3) +
    "\nFact: 22 of 625 functions exceed the cognitive complexity cap of 15. The meter reproduces SonarQube on its own 16 calibration cases. The quality gate checks only changed functions (`--changed BASE`), so these 22 are not gated.")
sec("11. Dead code, vulture", "`vulture spectre tle_clustering --min-confidence 60`:", [("vulture.txt", 10, 10)],
    "By kind: 212 unused variable, 86 unused function, 14 unused property, 6 unused class, 6 unused attribute, 4 unused method. 6 at 100 % confidence, all unused local variables:\n\n```\nspectre/astro/monte_carlo.py:424: unused variable 'pre_epoch' (100% confidence)\nspectre/astro/monte_carlo.py:645: unused variable 'tle_record' (100% confidence)\nspectre/astro/tactical.py:1758: unused variable 'r_threat' (100% confidence)\nspectre/domain/decision.py:277: unused variable 'adversary_idx' (100% confidence)\nspectre/web/routes/maneuver.py:792: unused variable 'number_of_burns' (100% confidence)\nspectre/web/routes/maneuver.py:794: unused variable 'minimize_delta_v' (100% confidence)\n```\n\nPer G4, the 60 % entries are candidates only. FastAPI route functions, Pydantic fields and Jinja-referenced attributes are known vulture false positives, so none is a negative claim until phase 7 greps it.")
sec("12. Duplication, jscpd", "`jscpd spectre tle_clustering --min-lines 6`, Python, JavaScript, CSS and markup, minified vendor files ignored:", ["jscpd.txt"],
    "Fact: 0.93 % duplicated lines, under the gate's 3 % ceiling (`check-quality.sh:19`). Clone locations were not captured with the console reporter. TBC, re-verify with `--reporters json` in phase 5 (L7). The byte-identical root and static SVGs (LEDGER O8) fall outside this scope.")
sec("13. Project gate scripts", "**13a. `sh scripts/check-quality.sh master`** (`ci.yml:196`):", ["check_quality.txt"],
    "Fact: the gate scopes to Python files changed against the merge base. On this branch none have changed, so it passes vacuously. It cannot be used as evidence of whole-repository quality. Section 1c is the whole-tree equivalent.\n\n**13b. `python3 scripts/preflight-gate.py .` and `--self-test`:**\n\n" + raw("preflight.txt") +
    "\nGap between tool and file (G2): the script WARNs \"Base image pinned by tag, not digest: ${BASE_IMAGE}\", but `Dockerfile:20` carries a digest in the `ARG` default. Inference: the script does not expand `ARG` defaults, so the WARN is a false positive of the meter, not of the Dockerfile. The script also confirms both lockfiles are compiled for Python 3.11 while the image runs 3.12 (LEDGER O1).\n\n**13c. Not run:** `scripts/verify-container.sh`, `scripts/simulate-pipeline.sh`, `scripts/verify-dependency-scan.sh` (need Docker or a package zip, and there is no Docker daemon here). `scripts/package-appstore.sh`, `scripts/bump-version.sh` and `scripts/lock.sh` mutate the tree. `scripts/smoke-browser.py` needs a live server and a browser session. `scripts/verify-db-resilience.py` was deferred to phase 3, pending a check that it is read-only.")
open(os.path.join(repo, "audit/TOOLS.md.body"), "w").write("".join(S))
