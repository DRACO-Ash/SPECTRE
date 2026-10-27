# SPECTRE audit: deterministic sweep (phase 2)

**Commit:** `a34e273f5673ea46a23ee2cff93b6ca9137a76d3` · **Run:** 23 October 2026 · **Scope:** phases 1 and 2 only.
Raw, verbatim output for every command is in `audit/tools-raw/`, one file per run. This file quotes it and summarises it. It does not triage: no output here is yet a finding (G2, G6).

## 2.1 Summary by tool and severity

| # | Tool and scope | Exit | Result | Severity split |
|---|---|---|---|---|
| 0a | Declared install `pip install -e ".[dev]"` | 0 with warning | Installs `spectre` only; no `dev` extra | n/a |
| 0b | Combined locked install | 1 | `tomli` pin conflict between lockfiles | n/a |
| 1a | ruff, CI scope `spectre/ tests/` | 0 | 0 issues | n/a |
| 1b | ruff, whole tree, project config | 1 | 3 issues, all `query_UDL_Data.py` | style/import |
| 1c | ruff, house Sonar-approximating rule set, `spectre tle_clustering` | 1 | 432 issues across 26 rules | top: PLR2004 203, PLR0913 40, PLR0917 40, BLE001 32, N806 23 |
| 2 | black `--check .` | 1 | 133 of 165 files would be reformatted | style (black is not a declared project tool) |
| 3a | mypy, CI invocation | 0 | 0 errors in 66 files | n/a |
| 3b | `mypy --strict`, bare | 2 | no target configured | n/a |
| 3c | `mypy --strict spectre tle_clustering` | 0 | 0 errors in 72 files | n/a |
| 3d | `mypy --strict tests` | 1 | 536 errors in 31 of 84 files | ungated |
| 3e | `mypy --strict` scripts, root script, docs generators | 1 | 86 errors in 5 of 9 files | ungated |
| 4a | pyright, `spectre tle_clustering` | 1 | 5 errors in 4 files | type errors mypy does not report |
| 4b | pyright, whole Python surface | 1 | 94 errors | ungated |
| 5a | bandit, CI invocation `-ll` on `spectre/` | 0 | 0 issues; 1 nosec honoured | n/a |
| 5b | bandit, all severities, whole Python surface | 1 | 20 issues | High 1, Medium 3, Low 16; product code Low 3 only |
| 6a | pip-audit `requirements.txt` | 0 | 0 known vulnerabilities | n/a |
| 6b | pip-audit `requirements-runtime.txt` | 0 | 0 known vulnerabilities | n/a |
| 6c | pip-audit `requirements-dev.txt` | 1 | 3 advisories, urllib3 2.7.0 | dev-only, fix 2.8.0 |
| 7 | safety | 1 | **UNAVAILABLE**: no network route to the safety database | not simulated |
| 8a | gitleaks, history (96 commits) | 0 | no leaks | n/a |
| 8b | gitleaks, working tree | 0 | no leaks | n/a |
| 9 | pytest, branch coverage | 0 | 1,898 collected, 1,896 passed, 2 skipped, 0 failed | statements 84.35 %, branches 70.96 %, combined 81.84 % |
| 10a | radon cc | 0 | 23 blocks with cyclomatic complexity above 15; max F (48) | n/a |
| 10b | radon mi | 0 | 3 modules below A: `udl.py` B, `threat.py` C, `tactical.py` C | n/a |
| 10c | cognitive complexity meter, cap 15 | 1 | 22 of 625 functions over the cap; max 51 | n/a |
| 11 | vulture, confidence 60 % and above | 3 | 328 candidates, 6 at 100 % | candidates only (G4) |
| 12 | jscpd | 0 | 17 clones, 211 lines, 0.93 % | under 3 % ceiling |
| 13a | `scripts/check-quality.sh master` | 0 | "Nothing to check": no changed Python | vacuous pass |
| 13b | `scripts/preflight-gate.py` and `--self-test` | 0, 0 | 0 blocking, 1 advisory (false positive, see 13b); self-test 10 assertions pass | n/a |

Interpretation is deliberately withheld here. Some facts bear directly on later phases and are recorded so they are not lost:

● Every gate that passes is scoped. CI ruff covers `spectre/ tests/`, CI bandit covers `spectre/` at medium and above, mypy strict covers product code only, and the quality gate covers changed lines only. Every tool that fails does so outside those scopes (fact, from the table).
● The suite is large and green, and branch coverage (70.96 %) is 13 points below statement coverage. Pass count is not evidence of correctness; phase 6 owns that question.
● Two tools that should agree do not. mypy strict passes `spectre/` while pyright reports 5 errors on the same files (section 4).

## 2.2 Suppressions, ignores and skips

Search, verbatim:

```
git grep -nE "noqa|type: *ignore|nosec|pyright: *ignore|pragma: *no ?cover|NOSONAR|pylint: *disable|ruff: *noqa|@pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(|pytest\.importorskip|unittest\.skip|filterwarnings" -- '*.py' '*.toml' '*.cfg' '*.properties'
```

354 matching lines, then 2 module-level `pytestmark` skips the pattern missed (found by a follow-up grep), then 6 configuration-level exclusions. Every site, with path:line, kind, the justification found, and whether the suppressed rule is enabled, is in `audit/tools-raw/suppressions.md`. Classification was by script (`audit/tools-raw/suppressions.md` header). "Justification" is a heuristic: text after the directive on the same line, or a comment on the line directly above. Its accuracy is TBC, re-verify by sample in phase 5.

### Counts

| Kind | Product (`spectre/`, `tle_clustering/`) | Tests | Scripts | Total |
|---|---|---|---|---|
| `# type: ignore[...]` | 63 | 195 | 5 | 263 |
| `# noqa` | 29 | 21 | 10 | 60 |
| `pytest.skip` / `skipif` | 0 | 26 | 0 | 26 |
| `# pragma: no cover` | 1 | 4 | 0 | 5 |
| `# nosec` | 1 | 0 | 0 | 1 |
| `# ruff: noqa` (file level) | 1 | 0 | 0 | 1 |
| Configuration-level | 6 entries | | | 6 |

● Sites with no justification found: 271 of 354 overall, 66 of 95 in product code.
● 53 of the 63 product `type: ignore` sites are `[attr-defined]` on attributes of the per-session `state` object. 44 of those are in `spectre/web/routes/threat.py`, including every read of `state.udl_username` and `state.udl_password`. Fact: mypy strict passes, and strict enables `warn_unused_ignores`, so each of these ignores is load-bearing. The type of `state` does not declare the attributes the routes use.
● **Inert suppressions.** 52 `noqa` sites name a rule that the project's ruff configuration does not enable (`pyproject.toml:84` selects `E, F, I, UP, B, SIM` only). That includes 14 product-code `noqa: BLE001` on `except Exception` clauses, plus `PLR0913/PLR0917` (7), `PLC0415` (4) and `PLW0603` (1). Fact: those directives suppress nothing under the CI lint. Broad exception handlers are not checked by any CI-run ruff rule. Under the house rule set (section 1c), 32 further `BLE001` sites are unsuppressed.
● **Skips** are all conditional on what the tree contains (no git, no `scripts/`, no `docs/`, a docker-only template), and each carries a reason string. In this run 2 skipped: `tests/unit/test_deployment_contract.py:796` and `:813`.
● **Coverage exclusion.** `spectre/app_logging/config.py` is omitted from coverage in both `pyproject.toml:69` and `sonar-project.properties:41`.
● **Security suppression.** `spectre/web/_entrypoint.py:15` `# ruff: noqa: S104` (file level) and `:41` `host="0.0.0.0",  # nosec B104`, with a justification comment above (Keycloak gateway in front of the service). Bandit honoured it in 5a.
● `spectre/web/routes/training.py:253` and `:350`: `ChallengeResult.scored == True,  # noqa: E712`. The rule is enabled, no justification was found, and this is the SQLAlchemy column-comparison idiom (inference).

## 0. Environment and install reproducibility

Interpreter: CPython 3.12.3 in a fresh virtualenv, matching `ci.yml` (`python-version: "3.12"`) and the image base. All tools ran against a local clone of HEAD `a34e273` so the audited tree stayed unmodified; caches went to scratch. Path substitution: the scratch clone path is shown as `<clone>`, the virtualenv as `<venv>`. ANSI colour codes stripped. Nothing else is altered.

**0a. Declared install**, `pip install -e ".[dev]"` (README.md:41, ci.yml:31,48,185), reproduced with uv:

```
warning: The `UV_NATIVE_TLS` environment variable is deprecated and will be removed in a future release. Use `UV_SYSTEM_CERTS` instead.
Using Python 3.12.3 environment at: <venv>-declared
Resolved 1 package in 3ms
   Building spectre @ file:///home/user/SPECTRE
      Built spectre @ file:///home/user/SPECTRE
Prepared 1 package in 520ms
Installed 1 package in 0.43ms
 + spectre==0.5.24 (from file:///home/user/SPECTRE)
warning: The package `spectre @ file:///home/user/SPECTRE` does not have an extra named `dev`
rc=0
```

Fact: no extra named `dev` exists, and the command installs the `spectre` package with no runtime or tool dependencies. On a clean runner, the CI steps that follow it (`ruff`, `mypy`, `pytest`) would have no executable unless the runner image supplies one. Inference: the GitHub `ci.yml` cannot pass as written on a stock `ubuntu-latest` runner. TBC, re-verify against the CI run history for `master`.

**0b. Combined locked install**, `uv pip install --require-hashes -r requirements.txt -r requirements-dev.txt`:

```
warning: The `UV_NATIVE_TLS` environment variable is deprecated and will be removed in a future release. Use `UV_SYSTEM_CERTS` instead.
Using Python 3.12.3 environment at: <venv>
  × No solution found when resolving dependencies:
  ╰─▶ Because you require tomli==2.5.0 and tomli==2.4.1, we can conclude that
      your requirements are unsatisfiable.
locked exit=1
```

Fact: `requirements.txt:1370` pins `tomli==2.5.0` and `requirements-dev.txt:1025` pins `tomli==2.4.1`. The audit environment was built by installing `requirements.txt` with hashes, then `requirements-dev.txt` with hashes over it (which replaced tomli), then `pip install --no-deps -e .`. Audit-only tools not in any lockfile, installed unpinned at latest: black, pyright, radon, vulture, safety, mutmut. gitleaks 8.18.4 (the CI pin) from the GitHub release; jscpd 4.0.5 from npm.

### Tool versions

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

## 1. ruff

**1a. As CI runs it** (`ci.yml:33`), project config:

```
$ ruff check spectre/ tests/ --no-cache
All checks passed!
[exit 0]
```

**1b. Whole tree** (`ruff check .`, the audit spec), project config:

```
$ ruff check . --no-cache --output-format=concise
query_UDL_Data.py:5:1: E401 [*] Multiple imports on one line
query_UDL_Data.py:5:1: I001 [*] Import block is un-sorted or un-formatted
query_UDL_Data.py:12:41: UP012 [*] Unnecessary call to `encode` as UTF-8
Found 3 errors.
[*] 3 fixable with the `--fix` option.
[exit 1]
```

Fact: the 3 findings are all in `query_UDL_Data.py`, which CI does not lint because CI scopes to `spectre/ tests/`.

**1c. House rule set from `scripts/check-quality.sh:38-39`, applied to the whole of `spectre/` and `tle_clustering/`** rather than to changed lines only:

```
$ ruff check --no-cache --isolated --line-length 120 --target-version py312 --select F,E,W,B,SIM,C90,N,S,BLE,A,C4,DTZ,T20,PIE,RET,SLF,ERA,PL,TRY400,PERF,LOG,G,RUF100 --ignore E501,B008,PTH123,TRY003,EM101,EM102,PLC0415,ARG --statistics spectre tle_clustering
203	PLR2004	[ ] magic-value-comparison
 40	PLR0913	[ ] too-many-arguments
 40	PLR0917	[ ] too-many-positional-arguments
 32	BLE001 	[ ] blind-except
 23	N806   	[ ] non-lowercase-variable-in-function
 13	SIM108 	[ ] if-else-block-instead-of-if-exp
 12	C901   	[ ] complex-structure
 11	PLW0603	[ ] global-statement
  8	PLR0912	[ ] too-many-branches
  7	PLR0915	[ ] too-many-statements
  6	TRY400 	[ ] error-instead-of-exception
  5	PERF401	[ ] manual-list-comprehension
  5	PLR0911	[ ] too-many-return-statements
  4	SLF001 	[ ] private-member-access
  4	RUF100 	[*] unused-noqa
  3	ERA001 	[ ] commented-out-code
  2	W293   	[*] blank-line-with-whitespace
  2	PLR1730	[*] if-stmt-min-max
  2	N802   	[ ] invalid-function-name
  2	PLW3301	[ ] nested-min-max
  2	RET505 	[*] superfluous-else-return
  2	RET504 	[ ] unnecessary-assign
  1	DTZ007 	[ ] call-datetime-strptime-without-zone
  1	PLR5501	[*] collapsible-else-if
  1	PLW2901	[ ] redefined-loop-name
  1	S110   	[ ] try-except-pass
Found 432 errors.
[*] 11 fixable with the `--fix` option (18 hidden fixes can be enabled with the `--unsafe-fixes` option).
[exit 1]
```

Per-site list: `audit/tools-raw/ruff_house.txt`. Fact: the quality gate applies this rule set only to lines changed against the base branch (`check-quality.sh` `changed_in`), so the 432 existing findings are invisible to it by design.

## 2. black

`black --check .`. The project does not declare black; ruff is its declared formatter-adjacent linter. Recorded because the audit spec requires it.

Output is 138 lines; full verbatim text in `audit/tools-raw/black.txt`. First 5 and last 5 lines:

```
$ black --check .
would reformat <clone>/query_UDL_Data.py
would reformat <clone>/scripts/build-hrr-default.py
would reformat <clone>/docs/build_gcat_workbook_1.py
would reformat <clone>/scripts/cognitive_complexity.py
...
would reformat <clone>/tle_clustering/parser.py

Oh no! 💥 💔 💥
133 files would be reformatted, 32 files would be left unchanged.
[exit 1]
```

## 3. mypy

**3a. As CI runs it** (`ci.yml:35`):

```
$ mypy spectre/ --ignore-missing-imports
Success: no issues found in 66 source files
[exit 0]
```

**3b. `mypy --strict`, bare, as the audit spec words it:**

```
$ mypy --strict
usage: mypy [-h] [-v] [-V] [more options; see below]
            [-m MODULE] [-p PACKAGE] [-c PROGRAM_TEXT] [files ...]
mypy: error: Missing target module, package, files, or command.
[exit 2]
```

Fact: `pyproject.toml [tool.mypy]` sets no `files`, so the bare command has no target.

**3c. `mypy --strict spectre tle_clustering`:**

```
$ mypy --strict spectre tle_clustering
Success: no issues found in 72 source files
[exit 0]
```

**3d. `mypy --strict tests`** (not gated anywhere):

Output is 883 lines; full verbatim text in `audit/tools-raw/mypy_strict_tests.txt`. First 6 and last 5 lines:

```
$ mypy --strict tests
tests/unit/test_quality_gate_scope.py:107: error: Function is missing a return type annotation  [no-untyped-def]
tests/unit/test_quality_gate_scope.py:115: error: Argument 1 to "module_from_spec" has incompatible type "ModuleSpec | None"; expected "ModuleSpec"  [arg-type]
tests/unit/test_quality_gate_scope.py:117: error: Item "None" of "ModuleSpec | None" has no attribute "loader"  [union-attr]
tests/unit/test_quality_gate_scope.py:117: error: Item "None" of "Loader | Any | None" has no attribute "exec_module"  [union-attr]
tests/unit/test_quality_gate_scope.py:142: error: Missing type arguments for generic type "dict"  [type-arg]
...
tests/integration/test_login_hardening.py:368: error: Argument 1 to "Path" has incompatible type "str | None"; expected "str | PathLike[str]"  [arg-type]
tests/integration/test_login_hardening.py:369: error: Argument 1 to "Path" has incompatible type "str | None"; expected "str | PathLike[str]"  [arg-type]
tests/integration/test_login_hardening.py:408: error: Returning Any from function declared to return "int"  [no-any-return]
Found 536 errors in 31 files (checked 84 source files)
[exit 1]
```

By error code: 355 `no-untyped-def`, 71 `no-untyped-call`, 42 `attr-defined`, 13 `arg-type`, 12 `type-arg`, 10 `operator`, remainder in the raw file.

**3e. `mypy --strict` over `scripts/`, `query_UDL_Data.py`, `docs/*.py`** (not gated):

Output is 124 lines; full verbatim text in `audit/tools-raw/mypy_strict_scripts.txt`. First 6 and last 5 lines:

```
$ mypy --strict scripts query_UDL_Data.py docs/generate_guide.py docs/build_gcat_workbook_1.py
scripts/preflight-gate.py:89: error: Missing type arguments for generic type "list"  [type-arg]
scripts/preflight-gate.py:130: error: Missing type arguments for generic type "list"  [type-arg]
scripts/preflight-gate.py:152: error: Missing type arguments for generic type "list"  [type-arg]
scripts/preflight-gate.py:174: error: Missing type arguments for generic type "list"  [type-arg]
scripts/preflight-gate.py:195: error: Missing type arguments for generic type "list"  [type-arg]
...
docs/generate_guide.py:2040: error: Function "docx.api.Document" is not valid as a type  [valid-type]
docs/generate_guide.py:2040: note: Perhaps you need "Callable[...]" or a callback protocol?
docs/generate_guide.py:2165: error: Document? has no attribute "save"  [attr-defined]
Found 86 errors in 5 files (checked 9 source files)
[exit 1]
```


## 4. pyright

**4a. Product code**, `pyright spectre tle_clustering`, default (basic) mode, no project config:

```
$ pyright spectre tle_clustering
<clone>/spectre/astro/pattern_of_life.py
  <clone>/spectre/astro/pattern_of_life.py:1030:26 - error: Argument of type "list[Any | int]" cannot be assigned to parameter "chart_longitudes" of type "list[float]" in function "__init__"
    "list[Any | int]" is not assignable to "list[float]"
      Type parameter "_T@list" is invariant, but "Any | int" is not the same as "float"
      Consider switching from "list" to "Sequence" which is covariant (reportArgumentType)
  <clone>/spectre/astro/pattern_of_life.py:1030:56 - error: Argument of type "list[Any | int]" cannot be assigned to parameter "chart_drift_rates" of type "list[float]" in function "__init__"
    "list[Any | int]" is not assignable to "list[float]"
      Type parameter "_T@list" is invariant, but "Any | int" is not the same as "float"
      Consider switching from "list" to "Sequence" which is covariant (reportArgumentType)
<clone>/spectre/data/intel.py
  <clone>/spectre/data/intel.py:23:12 - error: Type "dict[str, dict[str, Any]] | None" is not assignable to return type "dict[str, dict[str, Any]]"
    Type "dict[str, dict[str, Any]] | None" is not assignable to type "dict[str, dict[str, Any]]"
      "None" is not assignable to "dict[str, dict[str, Any]]" (reportReturnType)
<clone>/spectre/web/routes/gcat.py
  <clone>/spectre/web/routes/gcat.py:476:14 - error: Type "Series | Unknown | Self@DataFrame" is not assignable to declared type "DataFrame"
    Type "Series | Unknown | DataFrame*" is not assignable to type "DataFrame"
      "Series" is not assignable to "DataFrame" (reportAssignmentType)
<clone>/spectre/web/routes/training.py
  <clone>/spectre/web/routes/training.py:168:24 - error: Operator "-" not supported for "None" (reportOptionalOperand)
5 errors, 0 warnings, 0 informations
[exit 1]
```

Fact: mypy strict passes on the same files while pyright reports 5 errors. Per G2, the gap is recorded and not explained away: mypy runs with `ignore_missing_imports = true` (`pyproject.toml:101`), which turns pandas and sgp4 types into `Any`, and pyright does not. That explains the `gcat.py:476` DataFrame case (inference). It does not obviously explain `training.py:168` ("Operator - not supported for None") or `intel.py:23` (an Optional return where a non-Optional is declared). Both are for phase 5 to reopen.

**4b. Whole Python surface** (`spectre tle_clustering scripts tests query_UDL_Data.py`): 94 errors. Spread by top-level directory of the reporting file: 4 in spectre, 1 in scripts, 14 in tests (files, not errors). By rule: 41 reportAttributeAccessIssue, 30 reportArgumentType, 5 reportOptionalMemberAccess, 4 reportOperatorIssue, 4 reportAssignmentType, 3 reportIndexIssue, 2 reportOptionalOperand, 2 reportCallIssue, 1 each reportReturnType, reportRedeclaration, reportPossiblyUnboundVariable. Full text: `audit/tools-raw/pyright_all.txt`.

## 5. bandit

**5a. As CI runs it** (`ci.yml:76`, `-ll`, scope `spectre/`):

```
$ bandit -r spectre/ -ll -c pyproject.toml -q
[tester]	WARNING	nosec encountered (B104), but no failed test on file spectre/web/_entrypoint.py:34
[exit 0]
```

**5b. All severities, whole Python surface** (`spectre tle_clustering scripts query_UDL_Data.py docs`):

Output is 255 lines; full verbatim text in `audit/tools-raw/bandit_all.txt`. First 4 and last 5 lines:

```
$ bandit -r spectre tle_clustering scripts query_UDL_Data.py docs -c pyproject.toml -f txt
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
...
		Low: 1
		Medium: 4
		High: 15
Files skipped (0):
[exit 1]
```

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

Fact: the CI gate at `-ll` on `spectre/` is clean. The only High and Medium findings fall outside CI's scope. `query_UDL_Data.py` is excluded from the image by `.dockerignore`, but it is tracked at the repository root.

## 6. pip-audit

**6a. As CI runs it, `requirements.txt`** (with `--no-deps --disable-pip`, because the file is fully hash-pinned):

```
$ pip-audit --desc on --requirement requirements.txt --no-deps --disable-pip
WARNING:pip_audit._cli:--no-deps is supported, but users are encouraged to fully hash their pinned dependencies
WARNING:pip_audit._cli:Consider using a tool like `pip-compile`: https://pip-tools.readthedocs.io/en/latest/#using-hashes
No known vulnerabilities found
[exit 0]
```

**6b. `requirements-runtime.txt`:**

```
$ pip-audit --desc on --requirement requirements-runtime.txt --no-deps --disable-pip
WARNING:pip_audit._cli:--no-deps is supported, but users are encouraged to fully hash their pinned dependencies
WARNING:pip_audit._cli:Consider using a tool like `pip-compile`: https://pip-tools.readthedocs.io/en/latest/#using-hashes
No known vulnerabilities found
[exit 0]
```

**6c. `requirements-dev.txt`** (not audited by CI):

Output is 10 lines; full verbatim text in `audit/tools-raw/pip_audit_dev.txt`. First 4 and last 5 lines:

```
$ pip-audit --desc on --requirement requirements-dev.txt --no-deps --disable-pip
WARNING:pip_audit._cli:--no-deps is supported, but users are encouraged to fully hash their pinned dependencies
WARNING:pip_audit._cli:Consider using a tool like `pip-compile`: https://pip-tools.readthedocs.io/en/latest/#using-hashes
Found 3 known vulnerabilities in 1 package
...
------- ------- --------------- ------------ -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
urllib3 2.7.0   PYSEC-2026-4177 2.8.0        ## Impact  urllib3's [streaming API](https://urllib3.readthedocs.io/en/2.7.0/advanced-usage.html#streaming-and-i-o) is designed for efficiently handling large HTTP responses by reading the content in chunks, rather than loading the entire response body into memory at once. When decoding a [chunked-transfer-encoded response](https://httpwg.org/specs/rfc9112.html#chunked.encoding), this API reads each chunk's size field by buffering until it sees `\n` or EOF.  A malicious HTTP server can return `Transfer-Encoding: chunked` and then send a very long run of bytes without any newline, causing the streaming client to buffer that entire run before urllib3 can reject the chunk size as invalid and allocate more memory than intended.  To fix the issue, we'll reject chunk-size fields larger than 65536 bytes, as already done in the non-streaming case, which is currently handled by the Python standard library. Note that this only applies to reading the chunk-size field, not the chunk data, which is already handled correctly. Thus, there shouldn't be any impact for non-malicious servers.  ## Affected usages  Applications and libraries using urllib3 versions earlier than 2.8.0 may be affected when streaming a chunked response from untrusted sources. Specifically, this affects the [read_chunked()](https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html#urllib3.response.BaseHTTPResponse.read_chunked) and [stream()](https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html#urllib3.response.BaseHTTPResponse.stream) methods of the HTTPResponse object.  This also affects requests streaming API, which uses urllib3 under the hood.  ## Remediation  Upgrade to urllib3 version 2.8.0 or later, where chunk-size fields larger than 65536 will be rejected. If upgrading is not immediately possible, consider reading the response at once using the [read()](https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html#urllib3.response.BaseHTTPResponse.read) method.
urllib3 2.7.0   PYSEC-2026-4176 2.8.0        ### Impact  urllib3's streaming API is designed for the efficient handling of large HTTP responses by reading content in chunks instead of loading the entire response body into memory at once.  urllib3 can decompress response bodies according to the HTTP `Content-Encoding` header. When streaming a compressed, chunked response, urllib3 first consumes data already buffered by the decoder before reading the next HTTP chunk.  However, urllib3 versions from 2.6.2 through 2.7.0 could enter an infinite loop when a chunked response contained bytes after the end of the Deflate stream. If the decompressed body exceeded the requested streaming chunk size, Python's zlib implementation could retain the trailing bytes as unconsumed input after reaching the end of the compressed stream. urllib3 would repeatedly attempt to decode those same bytes without making progress or reading more data from the network.  A malicious server could exploit this behavior to cause excessive CPU usage and prevent the affected request from completing on the client. Network read timeouts would not interrupt the loop because no further socket operation was required.  ### Affected usages  Applications and libraries using urllib3 versions 2.6.2 through 2.7.0 may be affected when all of the following conditions are met:  1. Compressed responses from an untrusted source are streamed using `HTTPResponse.stream(amt=N)` or `HTTPResponse.read_chunked(amt=N)` with a positive, finite chunk size. 2. Content decoding is enabled. 3. The response uses both `Transfer-Encoding: chunked` and `Content-Encoding: deflate`. 4. The decoded body exceeds the requested chunk size and the encoded body contains bytes after the end of the Deflate stream.  `HTTPResponse.stream()` uses a finite chunk size by default and is therefore affected when the other conditions are met.  ### Remediation  Upgrade to urllib3 2.8.0, in which the Deflate decoder stops accepting input after reaching the end of the compressed stream and no longer reports trailing bytes as data that can produce more decoded output.  If upgrading is not immediately possible, disable automatic content decoding for responses from untrusted sources by setting `decode_content=False`, or reject streamed responses using the Deflate content encoding. Applications that disable automatic decoding must handle the compressed response safely at another layer.
urllib3 2.7.0   PYSEC-2026-4175 2.8.0        ## Impact  urllib3 supports configuring TLS independently for an HTTPS proxy and the target server.  `proxy_ssl_context`, `proxy_assert_hostname`, and `proxy_assert_fingerprint` configure the TLS connection to the proxy. `ssl_context` and the other target-specific TLS parameters configure the connection to the target server.  In urllib3 versions 1.26.0 through 2.7.0, these configurations were not consistently separated. Depending on the proxy mode, urllib3 could:  1. Ignore `proxy_ssl_context` and use the target server's SSL context for the TLS connection to an HTTPS forwarding proxy. 2. Override the HTTPS proxy's certificate-verification policy with the target server's certificate-verification policy. 3. Apply target-specific SNI, hostname assertions, certificate fingerprint assertions, or TLS client credentials to the TLS connection to an HTTPS forwarding proxy.  In particular, configuring `cert_reqs="CERT_NONE"` for a target server could overwrite the `verify_mode` of the SSL context configured for the HTTPS proxy. This modification occurred in place and persisted on the context object, potentially disabling proxy certificate verification for later connections that reused the same context.  An attacker able to intercept the connection to an HTTPS proxy may be able to impersonate the proxy when the effective proxy TLS configuration disables certificate verification or otherwise accepts the attacker's certificate. This may occur, for example, when the target server's trust or identity policy is incorrectly applied to the proxy connection.  When HTTPS forwarding is enabled, an impersonated proxy can observe or modify forwarded requests and responses, potentially exposing credentials, authentication tokens, request bodies, response data, and other sensitive information.  A TLS client certificate intended for the target server may also be presented to the proxy or to an attacker impersonating it. This can disclose the client's identity and provide proof of possession of the corresponding private key. The private key itself is not transmitted during the TLS handshake.  In CONNECT tunneling mode, impersonating the HTTPS proxy does not by itself defeat the separate end-to-end TLS connection between the client and the target server.  ## Affected Usages  Code using urllib3 versions 1.26.0 through 2.7.0 may be affected in any of the following cases.  ### 1. The target SSL context is used for an HTTPS forwarding proxy  HTTPS requests are forwarded through an HTTPS proxy with `use_forwarding_for_https=True`, and `proxy_ssl_context` is configured for the proxy.  urllib3 may ignore `proxy_ssl_context` and use the target server's `ssl_context` for the proxy TLS handshake. The proxy may therefore be verified using the target server's trust and certificate policy instead of the policy explicitly configured for the proxy.  ### 2. The target verification policy overrides the proxy policy  An HTTPS proxy is configured with `proxy_ssl_context`, while the target server uses a different certificate-verification policy.  urllib3 may apply the target server's `cert_reqs` value to the proxy SSL context. For example, setting `cert_reqs="CERT_NONE"` for the target server may also disable certificate verification for the HTTPS proxy, even when `proxy_ssl_context` was configured to require verification.  This issue can affect the TLS connection to an HTTPS proxy in both forwarding and CONNECT tunneling configurations.  ### 3. A mutated proxy SSL context is reused  The same SSL context is reused as `proxy_ssl_context` across multiple connections, and certificate verification is disabled for one target server.  urllib3 may modify the proxy SSL context's `verify_mode` in place. Later connections that reuse the same context may therefore connect to the HTTPS proxy without certificate verification.  ### 4. Target-specific TLS identity or credentials are applied to the proxy  HTTPS requests are forwarded through an HTTPS proxy with `use_forwarding_for_https=True`, and target-specific SNI, hostname assertions, certificate fingerprint assertions, or TLS client credentials are configured.  urllib3 may apply these target-specific settings to the proxy TLS handshake. This may cause urllib3 to:  - send SNI intended for the target server to the proxy; - verify the proxy using a hostname or certificate fingerprint intended for the target server; or - present a TLS client certificate intended for the target server to the proxy.  Code connecting through a plain HTTP proxy does not establish a TLS connection to the proxy and is not affected by this issue.  ## Remediation  Upgrade to urllib3 2.8.0 or later.  urllib3 2.8.0 independently applies the explicitly configured `proxy_ssl_context` and proxy-specific certificate assertions to the HTTPS proxy connection. Target-specific SNI, certificate assertions, and TLS client certificate parameters are no longer applied to the HTTPS proxy handshake.  For backward compatibility, when an HTTPS proxy is used with `use_forwarding_for_https=True` and `proxy_ssl_context` is not provided, urllib3 2.8.0 continues to use `ssl_context` for the TLS connection to the proxy. This configuration emits a `FutureWarning`. In urllib3 3.0, passing `ssl_context` with `use_forwarding_for_https=True` for an HTTPS proxy will raise an error. Applications should use `proxy_ssl_context` to configure TLS for an HTTPS forwarding proxy.  The fixes were implemented in commits b6447295fff7b38fdffc67e0df9712d60cef3cc3 and 07408cec79d1856d81bb42c74a904a24fdb9e465.
[exit 1]
```

Fact: urllib3 2.7.0 at `requirements-dev.txt:1094`, with 3 advisories (PYSEC-2026-4175, PYSEC-2026-4176, PYSEC-2026-4177), fixed in 2.8.0. It is reached only through `requests` in the dev set. It is absent from `requirements.txt` and `requirements-runtime.txt`, so it does not ship in the image (fact, grep). Vendored JavaScript (Chart.js 4.4.7, chartjs-plugin-zoom 2.0.1, Hammer.JS 2.0.7, htmx 1.9.12) is not covered by any SCA tool in this repository.

## 7. safety

`safety check -r requirements.txt --full-report`:

Output is 97 lines; full verbatim text in `audit/tools-raw/safety.txt`. First 6 and last 5 lines:

```
$ safety check -r requirements.txt --full-report
<venv>/lib/python3.12/site-packages/safety/auth/main.py:5: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
It will be compatible before version 2.0.0.
  from authlib.jose.errors import ExpiredTokenError
<venv>/lib/python3.12/site-packages/authlib/integrations/httpx_client/assertion_client.py:5: AuthlibDeprecationWarning: The httpx module is deprecated; please use httpx2 instead.
  from ._compat import httpx2
...
    self.gen.throw(value)
  File "<venv>/lib/python3.12/site-packages/httpx/_transports/default.py", line 118, in map_httpcore_exceptions
    raise mapped_exc(message) from exc
httpx.ConnectError: [Errno -2] Name or service not known
[exit 1]
```

**Unavailable.** Fact: safety needs its online vulnerability database. DNS resolution failed through this environment's network policy (`httpx.ConnectError: [Errno -2] Name or service not known`). Not simulated. pip-audit (section 6) is the SCA evidence for this run.

## 8. gitleaks

**8a. History**, as CI runs it (`ci.yml:109`), 96 commits:

```
$ gitleaks detect --source . --redact -v --no-banner
9:28PM INF 96 commits scanned.
9:28PM INF scan completed in 7.77s
9:28PM INF no leaks found
[exit 0]
```

**8b. Working tree, `--no-git`** (README.md:286):

```
$ gitleaks detect --source . --no-git --redact -v --no-banner
9:28PM INF scan completed in 1.31s
9:28PM INF no leaks found
[exit 0]
```

Fact: neither scan reports a leak. Gitleaks does not open the binary archive `bluestaq-foundations-v1.99.0.zip` or `docs/SPECTRE_Operator_Guide.docx`, so their contents are unscanned (gap).

## 9. pytest with branch coverage

Command, as CI (`ci.yml:53-55`) plus `--cov=tle_clustering --cov-branch` and the project `addopts = "-ra -q"`. `SECRET_KEY` set to the CI value. The integration marker was not deselected, matching CI.

Output is 150 lines; full verbatim text in `audit/tools-raw/pytest.txt`. First 30 and last 5 lines:

```
$ SECRET_KEY=<ci value> pytest tests/ -q -p no:cacheprovider --cov=spectre --cov=tle_clustering --cov-branch --cov-report=term-missing --cov-report=xml:<scratch>/cache/coverage.xml --cov-report=json:<scratch>/cache/coverage.json --durations=15
........................................................................ [  3%]
........................................................................ [  7%]
........................................................................ [ 11%]
........................................................................ [ 15%]
........................................................................ [ 18%]
........................................................................ [ 22%]
........................................................................ [ 26%]
........................................................................ [ 30%]
....................................ss.................................. [ 34%]
........................................................................ [ 37%]
........................................................................ [ 41%]
........................................................................ [ 45%]
........................................................................ [ 49%]
........................................................................ [ 53%]
........................................................................ [ 56%]
........................................................................ [ 60%]
........................................................................ [ 64%]
........................................................................ [ 68%]
........................................................................ [ 72%]
........................................................................ [ 75%]
........................................................................ [ 79%]
........................................................................ [ 83%]
........................................................................ [ 87%]
........................................................................ [ 91%]
........................................................................ [ 94%]
........................................................................ [ 98%]
..........................                                               [100%]
=============================== warnings summary ===============================
../venv/lib/python3.12/site-packages/fastapi/testclient.py:1
...
0.99s call     tests/integration/test_login_hardening.py::TestRevocationDoesNotRefuseTheNextSession::test_a_password_change_does_not_refuse_the_session_that_follows_it
=========================== short test summary info ============================
SKIPPED [1] tests/unit/test_deployment_contract.py:796: python template: manifests ship by design
SKIPPED [1] tests/unit/test_deployment_contract.py:813: python template: manifests ship by design
[exit 0]
```

### Result

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

Fact: the unit and integration suites were not split in this run. Whether any test reaches the live network was not established (the `integration` marker is declared in `pyproject.toml:58`, and `git grep -n "mark.integration" -- tests` returns nothing, so no test carries it. Fact: README.md:254 "opt-in network tests" therefore has no marker mechanism behind it. Routed to phase 4.)

## 10. Complexity

**10a. radon cyclomatic complexity, grade C and worse:**

Output is 96 lines; full verbatim text in `audit/tools-raw/radon_cc.txt`. First 8 and last 5 lines:

```
$ radon cc -s -n C spectre tle_clustering
spectre/config/settings.py
    F 201:0 split_database_url - C (12)
spectre/training/gamification.py
    F 198:0 check_level_up - C (14)
spectre/web/database.py
    F 186:0 _bootstrap_admin - C (13)
spectre/web/app.py
...
    F 452:0 _assess_propellant - C (11)
    F 905:0 _mission_profile - C (11)
tle_clustering/clustering.py
    F 77:0 cluster_records - C (14)
[exit 0]
```

Fact: 23 functions or methods have cyclomatic complexity above 15 (counted from the raw output). The highest is `spectre/astro/notso.py:319 _parse_single_notso` at F (48). Average across 755 blocks: A (4.11), from `radon_cc_all.txt`.

**10b. radon maintainability index, B and worse:**

```
$ radon mi -s -n B spectre tle_clustering
spectre/web/routes/udl.py - B (12.59)
spectre/web/routes/threat.py - C (7.58)
spectre/astro/tactical.py - C (8.41)
[exit 0]
```

**10c. Cognitive complexity, project meter (`scripts/cognitive_complexity.py --max 15`), whole tree:**

```
$ python scripts/cognitive_complexity.py --max 15
  OVER   51  spectre/astro/tactical.py:1135  optimal_evasion
  OVER   44  spectre/web/routes/decision.py:56  decision_evaluate
  OVER   40  spectre/web/routes/training.py:364  training_scenario_submit
  OVER   31  spectre/astro/tactical.py:791  classify_manoeuvre
  OVER   31  spectre/astro/tactical.py:1617  fingerprint_manoeuvre
  OVER   30  spectre/astro/events.py:38  find_orbital_events
  OVER   27  spectre/astro/photometry.py:664  parse_photometry_csv
  OVER   27  spectre/domain/scenario.py:40  plan
  OVER   27  spectre/web/routes/udl.py:1071  udl_notso_sync
  OVER   26  spectre/astro/tactical.py:1839  orbital_terrain
  OVER   23  spectre/astro/notso.py:319  _parse_single_notso
  OVER   23  spectre/astro/tle_preprocessing.py:106  cluster_and_reduce_tle_cache
  OVER   22  spectre/astro/tactical.py:1293  assess_intercept_intent
  OVER   21  spectre/web/routes/pol.py:53  _parse_udl_elset_response
  OVER   20  spectre/domain/decision.py:155  compute_outcome_metrics
  OVER   19  spectre/astro/pattern_of_life.py:648  _compute_drift_phases
  OVER   19  spectre/astro/photometry.py:208  _fit_least_squares_quadratic
  OVER   19  spectre/astro/photometry.py:271  fit_baseline
  OVER   17  spectre/web/routes/threat.py:208  _objects_for_group
  OVER   17  spectre/web/routes/training.py:215  _start_scenario
  OVER   17  spectre/web/routes/udl.py:970  search_catalog
  OVER   17  spectre/web/routes/udl.py:1008  udl_notso

  625 function(s) measured, 22 over the limit of 15.
[exit 1]
```

Calibration self-check (`--calibrate`):

Output is 23 lines; full verbatim text in `audit/tools-raw/cogcx_cal.txt`. First 3 and last 5 lines:

```
$ python scripts/cognitive_complexity.py --calibrate
Calibration against SonarQube's report for 0.5.23, at 047a9eb

...
     21     21     +0  spectre/domain/pol_assessment.py:524  _assess_anomaly
     16     16     +0  spectre/domain/threat_assessment.py:359  assess_threat

  PASS: all 16 cases reproduce SonarQube's score exactly.
[exit 0]
```

Fact: 22 of 625 functions exceed the cognitive complexity cap of 15. The meter reproduces SonarQube on its own 16 calibration cases. The quality gate checks only changed functions (`--changed BASE`), so these 22 are not gated.

## 11. Dead code, vulture

`vulture spectre tle_clustering --min-confidence 60`:

Output is 330 lines; full verbatim text in `audit/tools-raw/vulture.txt`. First 10 and last 5 lines:

```
$ vulture spectre tle_clustering --min-confidence 60
spectre/app_logging/config.py:12: unused function 'configure_logging' (60% confidence)
spectre/astro/cw_geometry.py:150: unused variable 'dv_total_ms' (60% confidence)
spectre/astro/dv_estimation.py:326: unused variable 'floor_is_measured' (60% confidence)
spectre/astro/dv_estimation.py:334: unused property 'median_m_s' (60% confidence)
spectre/astro/dv_estimation.py:338: unused property 'mad_m_s' (60% confidence)
spectre/astro/dv_estimation.py:402: unused property 'believable' (60% confidence)
spectre/astro/lambert.py:38: unused variable 'delta_v1_mag' (60% confidence)
spectre/astro/lambert.py:39: unused variable 'delta_v2_mag' (60% confidence)
spectre/astro/maneuvers.py:68: unused variable 'departure_epoch' (60% confidence)
...
tle_clustering/models.py:83: unused variable 'cluster_id' (60% confidence)
tle_clustering/models.py:86: unused variable 'centroid_inclination_deg' (60% confidence)
tle_clustering/models.py:88: unused variable 'centroid_eccentricity' (60% confidence)
tle_clustering/models.py:95: unused property 'member_epochs' (60% confidence)
[exit 3]
```

By kind: 212 unused variable, 86 unused function, 14 unused property, 6 unused class, 6 unused attribute, 4 unused method. 6 at 100 % confidence, all unused local variables:

```
spectre/astro/monte_carlo.py:424: unused variable 'pre_epoch' (100% confidence)
spectre/astro/monte_carlo.py:645: unused variable 'tle_record' (100% confidence)
spectre/astro/tactical.py:1758: unused variable 'r_threat' (100% confidence)
spectre/domain/decision.py:277: unused variable 'adversary_idx' (100% confidence)
spectre/web/routes/maneuver.py:792: unused variable 'number_of_burns' (100% confidence)
spectre/web/routes/maneuver.py:794: unused variable 'minimize_delta_v' (100% confidence)
```

Per G4, the 60 % entries are candidates only. FastAPI route functions, Pydantic fields and Jinja-referenced attributes are known vulture false positives, so none is a negative claim until phase 7 greps it.

## 12. Duplication, jscpd

`jscpd spectre tle_clustering --min-lines 6`, Python, JavaScript, CSS and markup, minified vendor files ignored:

```
$ jscpd spectre tle_clustering --min-lines 6 --reporters console --silent --format python,javascript,css,markup --ignore **/*.min.js --output <scratch>/cache/jscpd
Duplications detection: Found 17 exact clones with 211(0.93%) duplicated lines in 150 (3 formats) files.
[exit 0]
```

Fact: 0.93 % duplicated lines, under the gate's 3 % ceiling (`check-quality.sh:19`). Clone locations were not captured with the console reporter. TBC, re-verify with `--reporters json` in phase 5 (L7). The byte-identical root and static SVGs (LEDGER O8) fall outside this scope.

## 13. Project gate scripts

**13a. `sh scripts/check-quality.sh master`** (`ci.yml:196`):

```
$ sh scripts/check-quality.sh master

No analysed Python files changed against master. Nothing to check.

[exit 0]
```

Fact: the gate scopes to Python files changed against the merge base. On this branch none have changed, so it passes vacuously. It cannot be used as evidence of whole-repository quality. Section 1c is the whole-tree equivalent.

**13b. `python3 scripts/preflight-gate.py .` and `--self-test`:**

```
$ python3 scripts/preflight-gate.py .
App Store gate pre-flight: <clone>
========================================================================
[WARN ] INFERENCE Base image pinned by tag, not digest: ${BASE_IMAGE}.
                   fix: A moving tag means two builds of the identical archive can produce different images and different Container Scan results. Pin the digest and schedule a refresh job.
[GOOD ] FACT      pyproject.toml present with a [project] table.
[GOOD ] FACT      Scannable file(s) at root: requirements.txt.
[GOOD ] FACT      No resolver hazards in any dependency file.
[GOOD ] FACT      requirements.txt is exactly pinned throughout.
[GOOD ] FACT      Every pinned entry carries a hash.
[GOOD ] FACT      requirements.txt is compiled for python 3.11, the scanner's interpreter.
[GOOD ] FACT      requirements-runtime.txt is compiled for python 3.11, the scanner's interpreter.
[GOOD ] INFERENCE Runtime lock file is a version-identical subset of requirements.txt.
[GOOD ] FACT      Dockerfile at the package root.
========================================================================
0 blocking, 1 advisory.
Contract satisfied. This predicts nothing about the gate's verdict;
it removes the failure modes that are visible from here.
The analyser's silence is explained: gemnasium-python logs pip's output
at DEBUG only, so a resolution failure shows as a bare exit 1.
[exit 0]

$ python3 scripts/preflight-gate.py --self-test
SELF-TEST PASSED: 10 assertions.
[exit 0]
```

Gap between tool and file (G2): the script WARNs "Base image pinned by tag, not digest: ${BASE_IMAGE}", but `Dockerfile:20` carries a digest in the `ARG` default. Inference: the script does not expand `ARG` defaults, so the WARN is a false positive of the meter, not of the Dockerfile. The script also confirms both lockfiles are compiled for Python 3.11 while the image runs 3.12 (LEDGER O1).

**13c. Not run:** `scripts/verify-container.sh`, `scripts/simulate-pipeline.sh`, `scripts/verify-dependency-scan.sh` (need Docker or a package zip, and there is no Docker daemon here). `scripts/package-appstore.sh`, `scripts/bump-version.sh` and `scripts/lock.sh` mutate the tree. `scripts/smoke-browser.py` needs a live server and a browser session. `scripts/verify-db-resilience.py` was deferred to phase 3, pending a check that it is read-only.

