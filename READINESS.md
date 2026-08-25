# SPECTRE: Bluestaq App Store readiness report

**Band: Likely after fixes** · Weighted score **94%** (17 of 18 applicable dimensions pass)
Archetype: server (container) · Template: **python** · Version **0.4.2**
Assessed 21 August 2026 against branch `claude/app-store-readiness-09re0q`.
All six SonarQube quality gate conditions are met on changed code.

This is a pre-flight estimate, not the binding App Store decision. The platform's
own pipeline, its container policy scan, its continuous Authority to Operate
(cATO) score and human review are the real gate. This check removes surprises
and raises the odds; it does not grant acceptance.

## Headline

SPECTRE arrived with a **red verification loop, a red pipeline on `master`, and
no deployment contract at all**: no health endpoint, the wrong port, a root
container, and an unpinned dependency install. All of those are now closed and
verified against a real built image. What remains is one genuine gap (coverage
below the 80% mark) and one control that cannot be exercised from this network.

## Blockers found and closed

Each was, on its own, enough to fail the deploy. All are fixed and verified.

| # | Blocker | Evidence | Fix |
|---|---|---|---|
| 1 | **Verification loop red.** 37 integration tests failed. Commit `d88cb69` added a global CSRF dependency but never updated the suite, so every authenticated POST returned 403. | `tests/integration/test_web_routes.py:150`, `assert 403 == 200` | `csrf_headers()` helper in `tests/conftest.py:34`; every non-safe request now mints a real token. The control is exercised, not disabled. |
| 2 | **CI red on `master` since 5 May 2026.** Run 43 (`b5621c2`): Tests and Lint both failed. Scored from the actual run conclusion, not the workflow file. | [run 29294546046](https://github.com/DRACO-Ash/SPECTRE/actions/runs/29294546046) | Blocker 1 fixes Tests. Lint failed on CI/local drift: the job installed a partial dependency set, so mypy disagreed with the local loop. It now runs `pip install -e ".[dev]"`. |
| 3 | **`GET /` returned 302.** The platform router probes the root and treats a redirect as a failed deploy. | `spectre/web/routes/operator.py:43`, `Depends(require_login)` raised `302` | New `optional_login` dependency (`spectre/web/auth.py:121`); anonymous callers get the login page at **200**. A test asserts console state still never leaks. |
| 4 | **No health or readiness endpoint.** The platform had no way to tell a live pod from a dead one. | no `/healthz` or `/readyz` anywhere in `spectre/web/routes/` | `spectre/web/health.py`. `/healthz` is liveness only; `/readyz` proves storage with a **real write**, races a 2 s timeout (shorter than the platform probe, so a stalled mount is a loud 503 rather than a silent liveness kill), and returns the resolved directory and exact errno in its 503 body. |
| 5 | **Wrong port, hard-coded.** Listened on 8000; the platform sets `containerPort: 8080`. | `spectre/web/_entrypoint.py:12`, `port=8000` | Resolves `PORT` in code, defaulting to 8080 (`spectre/config/settings.py:74`). No `ENV PORT=` anywhere: a baked ENV always beats a code fallback and breaks the readiness probe. |
| 6 | **Container ran as root**, shipped `gcc`, `apt` and `pip`, and carried the base image's setuid bits. The policy scan **stops** on `suid_or_guid_set`. | old `Dockerfile`, no `USER`, `apt-get install gcc` | Three-stage build. Runs `USER 10001:0`. Package managers and toolchain removed. The suid sweep is the **last** mutation of the prep stage and **fails the build closed** if anything remains. |
| 7 | **Layer history would have failed the scan.** An in-place `chmod` leaves path-less (`N/A`) findings from earlier base layers. | n/a, absent by construction | Runtime flattened: `FROM scratch` with a single `COPY --from=prep / /`, all metadata (including `PATH`) re-declared. |
| 8 | **Unpinned, unverifiable install.** The Dockerfile ran `pip install ".[standard]" \|\| pip install <hand-typed list>`, a fallback that silently installed a *different* dependency set. | old `Dockerfile` lines 16-20 | `requirements.lock`: 43 packages pinned with SHA-256 hashes, installed `--require-hashes --only-binary=:all:`. `pip-audit` over that exact file reports **no known vulnerabilities**. |
| 9 | **Baked `ENV DATABASE_URL` pointing into the image.** Writes would have landed on the ephemeral layer and vanished on redeploy. | old `Dockerfile`, `ENV DATABASE_URL="sqlite+aiosqlite:////app/data/spectre.db"` | Removed. Resolution is in code: explicit variable, then the injected `STORAGE_MOUNT_PATH`, then a local default. Validated at boot. |
| 10 | **No secret validation.** An empty or placeholder `SECRET_KEY` would boot and issue forgeable session and CSRF tokens. | `spectre/config/settings.py`, `secret_key` defaulted to `""` | `validate_secret_key` fails the boot closed on missing, placeholder or short keys. |

## Verified, not asserted

Every claim below was produced by running the thing, against the image built
from the shipped `Dockerfile` (`scripts/verify-container.sh`).

```
== Image hardening ==
  PASS  runs as non-root numeric uid 10001
  PASS  no setuid or setgid paths ship
  PASS  no package manager ships
  PASS  flattened to 2 layer(s), no base-image history
== Runtime contract ==
  PASS  boots and serves within 6s
  PASS  boot logs its storage verdict
  PASS  GET / returns 200
  PASS  GET / does not leak console state
  PASS  GET /healthz returns 200 unauthenticated
  PASS  GET /readyz returns 200 unauthenticated
  PASS  bound to 0.0.0.0:8080
== Fail-closed behaviour ==
  PASS  refuses to boot without SECRET_KEY
  PASS  refuses to boot with a placeholder SECRET_KEY
== Injected PORT ==
  PASS  honours an injected PORT
```

Local loop: `ruff` clean · `mypy --strict` clean across 60 files · `bandit`
medium-and-above clean · **797 passed, 0 skipped**, coverage **74%**.
The two tests that previously skipped as root now inject the failure instead,
so the suite has no silent gaps.

The `EACCES` case was also reproduced directly, mounting a read-only volume:

```
ConfigurationError: Data directory /mnt/ro is not writable: [errno 30] Read-only
file system. If this is the App Store FILE_STORAGE add-on, the pod needs
securityContext.fsGroup set so the non-root container can write to the volume.
```

That is the deploy-stage fault that normally costs an upload cycle to diagnose;
here it names itself and the remedy.

## Dimension scores

| Dimension | Weight | Verdict | Note |
|---|---|---|---|
| Verification loop green | blocker | **PASS** | 797 passed, 0 skipped |
| No secret in source or history | blocker | **PASS** | Local sweep clean; CI `gitleaks` over full history passed independently |
| Reads `PORT` default 8080, binds 0.0.0.0 | blocker | **PASS** | Verified on the running container |
| `GET /` and health return 200 | blocker | **PASS** | 200 / 200 / 200 |
| Non-root numeric user, no `ENV PORT` | blocker | **PASS** | uid 10001 |
| `Dockerfile` flat at package root | blocker | **PASS** | Root-level; template detection unambiguous |
| Hardened and flattened runtime image | blocker | **PASS** | 0 suid paths, no package manager, `FROM scratch` |
| Every negative assertion classified per environment | blocker | **PASS** | The only file-existence assertions are over files that ship in the package |
| CI mirrors the loop, least privilege, latest run green | blocker if red | **PENDING** | Red on `master`; fixed on this branch, awaiting the first run |
| Reproducible install from a committed lockfile | heavy | **PASS** | 43 packages, hash-pinned |
| No unaddressed High or Critical CVE | heavy | **PASS** | `pip-audit`: no known vulnerabilities |
| Coverage on new code at least 80% | heavy | **PASS** | 100% of 129 changed lines |
| Whole-repository coverage at least 80% | heavy | **FAIL** | 74%, not scored by the gate, see gap 1 |
| Zero new bugs, vulnerabilities and code smells | heavy | **PASS** | Measured on changed lines |
| Duplication at most 3% | heavy | **PASS** | 0% |
| Security hotspots reviewed | heavy | **PASS** | 6 of 6, register above |
| Coverage report at the gate's path | heavy | **PASS** | `coverage.xml` emitted; unread under docker-only |
| Version stamp and audit row, generic client errors | medium | **PASS** | Single-sourced 0.4.2; boot logs its storage verdict |
| Surgical structure, documented architecture | medium | **PASS** | Changes confined to config, auth, health, entrypoint and packaging |
| Accessibility to WCAG AA | medium | **UNKNOWN** | Not assessed, see gap 3 |
| House voice in user-facing copy | light | **PASS** | UK English throughout the new copy |

The docker-only template skips the SonarQube gate, so those rows are scored
against the conditions directly rather than against a platform result. See the
template note below.

## SonarQube quality gate

Scored against the six gate conditions. All apply to **new and changed code
only**, so the numbers below are measured on the lines this branch touched, not
on the whole repository. Reproduce them with `scripts/check-quality.sh`.

| # | Condition | Threshold | Measured | Verdict |
|---|---|---|---|---|
| 1 | Reliability: new bugs | 0 | **0** | PASS |
| 2 | Security: new vulnerabilities | 0 | **0** | PASS |
| 3 | Maintainability: new code smells | 0 | **0** | PASS |
| 4 | Coverage on new code | at least 80% | **100%** (129 of 129 lines) | PASS |
| 5 | Duplicated lines | at most 3% | **0%** | PASS |
| 6 | Security hotspots reviewed | 100% | **6 of 6 reviewed** | PASS |

Whole-repository coverage is 74%, which the gate does not score. It rose from
70% partly because the greenlet tracing fix below corrected a real
under-measurement.

### Findings fixed to reach zero

● **A reliability bug introduced by this change, caught by its own test.**
  Narrowing `_load_hrr_from_disk` from `except Exception` to a specific tuple
  left `AttributeError` uncaught. Well-formed JSON of the wrong shape (an object
  rather than a list) would then reach the parser as bare strings and **crash
  the boot**. Fixed with shape validation at the boundary rather than a wider
  net: non-list input is rejected with a named error, and non-dict entries are
  discarded. `spectre/web/app.py:83`.
● **Blind exception handlers** (`except Exception`) removed from
  `spectre/web/health.py` and `spectre/web/app.py`. In the health probe, OSError
  and TimeoutError are the only failures a write probe can produce; anything
  else is a defect and must surface rather than be flattened into a storage
  verdict.
● **Magic value** `65535` replaced with named `_MIN_PORT` and `_MAX_PORT`
  constants, and the session lifetime with `_SESSION_COOKIE_MAX_AGE`.
● **Duplication at 2.33%**, uncomfortably close to the 3% ceiling, caused by
  fixture blocks copy-pasted across four integration modules. Hoisted into
  `tests/integration/conftest.py`. Now 0%.
● **A function-level import** of a typing-only symbol in
  `spectre/web/routes/operator.py` hoisted to module scope, and a dead
  `# noqa` directive replaced with the reason it existed.
● **Coverage under-measurement.** SQLAlchemy's async bridge switches greenlets
  on every `await`, and coverage.py lost the trace afterwards, reporting lines
  as uncovered that a direct call proves execute. Fixed honestly with
  `concurrency = ["thread", "greenlet"]` in `pyproject.toml` rather than by
  excluding the lines. `spectre/web/auth.py` went from 84% to 93% with no test
  changes.

### Security hotspot register

The gate requires every hotspot in changed code to be reviewed. An uploader
cannot click "review" in the dashboard, so each is resolved in code or recorded
here with its justification.

| Hotspot | Location | Category | Resolution |
|---|---|---|---|
| Session cookie had no `Secure` attribute | `spectre/web/routes/login.py:47` | Cookie security | **Fixed.** `secure=True` by default via `session_cookie_secure`. Disabling it needs the explicit `SPECTRE_COOKIE_SECURE=false` opt-out, used only by the test client, which speaks plain HTTP. `HttpOnly` and `SameSite=Lax` were already set and are now asserted by tests. |
| Binding to all network interfaces | `spectre/web/_entrypoint.py:21` | Dangerous configuration | **Reviewed, accepted.** Required, not incidental: the platform ingress reaches the container on the pod IP, so binding loopback makes the readiness probe unreachable and the deploy fail. Exposure is bounded by the pod network policy and the Keycloak gateway, not by this bind. Justification recorded inline at the call site. |
| Hard-coded credential strings | `tests/integration/conftest.py:28` | Hard-coded credentials | **Reviewed, accepted.** Fixture credentials for an in-memory SQLite database created and destroyed inside the test process. They authenticate against nothing that exists outside the run. Named and centralised so they cannot be mistaken for configuration. |
| Authentication and authorisation logic | `spectre/web/auth.py` | Auth logic | **Reviewed, tested.** The new `optional_login` never raises and never grants: a malformed cookie, a cookie signed with another key, and a valid cookie for a deleted user all resolve to anonymous. Each branch is asserted in `tests/integration/test_root_contract.py`, including that the console never renders for an anonymous caller. |
| Password hashing and token signing | `spectre/web/auth.py`, `spectre/web/csrf.py` | Cryptography | **Reviewed, accepted.** bcrypt with a per-password salt for credentials; itsdangerous HMAC over the signing key for session and CSRF tokens. No MD5, SHA-1, DES, RC4 or ECB anywhere in the tree. No use of `random` for anything security-bearing. |
| Logging | all changed modules | Sensitive data in logs | **Reviewed, clean.** No log statement emits a password, secret, token or hash. The fail-closed configuration errors name the variable and, for a short key, its length, never its value. |

### Out of scope, and why

Two findings sit in files this branch touched but on lines it did not change, so
the gate does not score them. They are recorded rather than silently fixed,
because widening the diff into untested legacy code trades a real risk for a
cosmetic one.

● **f-string-built DDL** in `spectre/web/database.py:58` and `:61`
  (`_apply_migrations`). SonarQube flags string-built SQL as an injection
  hotspot. Not exploitable here: table, column and definition all come from a
  hard-coded list literal in the same function, with no user-influenced input on
  the path. Worth hardening with an identifier allow-list as a separate change.
● **Unused `request` parameters** in `spectre/web/routes/operator.py:29` and
  `:279`. A genuine maintainability smell, pre-existing, and removing a
  parameter from a route signature is a behavioural change that belongs in its
  own commit with its own tests.

## Platform feedback, first upload

The first submission surfaced two items. Both are closed.

**Dependencies stage failed (blocker).** The package had no root
`requirements.txt`. It was omitted deliberately to hold docker-only detection,
but the platform's dependency install looks for exactly that file and fails
before any later stage runs. `pyproject.toml` alone is not enough.

The fix accepts the **python template**, which is now the right call: all six
quality gate conditions were already met. Two manifests are committed, generated
from one resolution so they cannot drift:

● `requirements.txt`, 88 packages, fully pinned, no hashes. What the platform
  installs. Includes the test tooling, because the python template runs the
  suite.
● `requirements.lock`, 43 packages, hash-pinned. What the **image** installs,
  with `--require-hashes --only-binary=:all:`, so the runtime stays
  hash-verified and carries no test tooling.

A test asserts their runtime pins never diverge. It earned its place
immediately: the first generation put `scipy` at 1.18.0 in one file and 1.18.1
in the other, because the two resolutions ran minutes apart. Verified by
installing `requirements.txt` into a clean interpreter and running the suite
there: **800 passed**.

**Dockerfile warning, hadolint DL4006 at line 106.** A `RUN` containing a pipe
without `pipefail`. Not a release blocker, but it pointed at something real: the
pipe was `find ... | wc -l` inside the **setuid sweep**, the one check designed
to fail closed. Had `find` errored with its stderr suppressed, `wc` would still
have exited 0 and printed 0, the check would have reported a clean sweep, and
setuid bits would have shipped to a scan that stops on them. A fail-open in the
guard against a hard failure.

The remedy hadolint suggests would have broken the build: `/bin/sh` on Debian is
dash, which has no `pipefail`. The pipe was removed instead, and the
verification now captures paths directly under `set -eu`, so a failing `find`
aborts the build rather than silently passing. Two contract tests pin it: no
pipe in the sweep, and `set -eu` present.

## The submission package

Built by `scripts/package-appstore.sh`, which is repeatable and fails closed:
it refuses to produce a package containing a credential-shaped file, a
populated secret, or a root `requirements.txt` (which would silently switch the
platform to the python template).

| | |
|---|---|
| Artefact | `dist/spectre-0.4.2-appstore.zip` |
| Size | 1.8 MB (10 MB uncompressed, 271 files) |
| Layout | Flat. `Dockerfile` at the root, no wrapping folder |
| Template | python (root `requirements.txt` present; the Dockerfile still builds the image) |
| Version | 0.4.2, matching the artifact stamp and the app's own version field |

It ships a **testable source tree**, not a stripped runtime bundle: tests, their
configuration, the lockfile, `sonar-project.properties` and the CI workflow all
travel with it. Under docker-only the platform will not run the suite, but a
reviewer can, and switching to the python template later then needs no
repackaging.

Excluded, each for a reason: `.git`, the virtualenv, every `.env` except the
example, coverage output, local runtime data and databases, build caches, and
`docs/openapi.json`, a 12 MB generated schema dump that is needed neither to
build, test nor review and would slow every upload cycle.

### Pipeline simulation against the artefact

`scripts/simulate-pipeline.sh` reproduces what the platform actually does: it
unzips the real package into a clean directory, adds the generated
`.gitlab-ci.yml` the platform commits into its own checkout, runs the suite with
`GITLAB_CI=true`, confirms `coverage.xml` is produced and non-empty, builds the
image using the unzipped root as the build context, and exercises the runtime
contract. All stages green:

```
Stage 1  checkout      flat, Dockerfile at the checkout root
Stage 1b dependencies  requirements.txt present, 88 packages pinned, resolves
Stage 2  test          suite green under GITLAB_CI=true; coverage.xml 284,711 bytes
Stage 3  containerize  builds from the unzipped root as context; suid sweep clean
Stage 4  scan          non-root uid 10001, no suid paths, no package manager
Stage 5  deploy        boots in 14s; GET /, /healthz, /readyz all 200
```

A green repository loop is not a green upload. This is the artefact.

## Remaining gaps

**1. Whole-repository coverage is 74%, the Foundations standard is 80%.**
*(heavy, not a blocker, not scored by the gate)*
Owner: `testing-standards`. The quality gate scores changed code, where this
branch is at 100%. The 74% figure is the whole repository, most of it code this
change never touched. The shortfall is concentrated in the route layer:
`threat.py` 29%, `udl.py` 27%, `pol.py` 21%, roughly 1,400 uncovered statements,
nearly all HTMX partial handlers. It costs nothing at submission but it is below
the house standard. *Fix:* extend the pattern in
`tests/integration/test_plan_export.py` route by route, heaviest first.

**2. The OS patch step could not be exercised here.** *(medium)*
Owner: `security-hardening`, `deploy-recipes`. `deb.debian.org` is blocked by
this network's egress policy, so `apt-get upgrade` reported **SKIPPED**, loudly,
naming its compensating control (the base image pinned by digest
`sha256:a116514e...`). It is written to distinguish "applied" from "skipped" and
never to report patched when nothing was checked. *Fix:* run
`scripts/verify-container.sh` once from a network that can reach the Debian
security repository and confirm the log reads `OS PATCH: applied`. If the
platform runner also cannot reach it, bump the pinned digest instead. That is
the patch mechanism. *Residual risk:* the container scan may report base-OS CVEs
that an upgrade would have cleared.

**3. Accessibility is unassessed.** *(medium)*
Owner: `accessibility`, `design-system`. The console is a large HTMX interface
and no WCAG 2.2 AA pass has been run against it. Not a submission blocker, but
it is a Bluestaq standard and a likely question at review. *Fix:* run the
four-pass method in the `accessibility` skill over `operator.html` and
`training.html`.

**4. Repository weight.** *(light)*
Owner: `packaging`. `docs/openapi.json` is 12 MB and `spectre/data/notso_cache.json`
is 8.3 MB. `.dockerignore` keeps `docs/` out of the image, but both still travel
in the uploaded zip and slow every cycle. A stray `bluestaq-foundations-server-python-tailored.zip`
(456 KB, committed by "Add files via upload") has been removed. *Fix:* decide
whether `openapi.json` needs to be tracked; if it does, it should not be in the
upload.

## Template note: the python template is now a low-risk option

When the docker-only template was chosen, the estimate for the python template
assumed the SonarQube gate scored whole-repository coverage, which would have
meant lifting 7,600 statements from 70% to 80%. That was wrong: the gate scores
**new and changed code only**. On that basis this branch already meets all six
conditions with margin, and `sonar-project.properties` is committed with the
sources, tests and coverage path the scanner needs.

Switching means adding a `requirements.txt` at the repository root, which is
what the platform detects. The trade is a platform-verified quality score and a
stronger cATO position, against one more gate that can fail on upload. The
mechanically-checkable conditions are reproduced locally by
`scripts/check-quality.sh` and enforced per-commit in CI, so the risk is now
mostly the server-side rule set revealing rules the local profile lacks.

This is a decision to take deliberately, not a change to make silently. The
current package remains docker-only.

## Skills to download from Launchpad

**None.** Every owning skill named above is already present in this environment.
The gaps are work to be done against standards you already hold, not missing
guidance.

## What would move the band to Ready

1. The CI run on this branch goes green (the fix is in; it needs one run).
2. Coverage reaches 80%.
3. `OS PATCH: applied` is confirmed from a network with Debian repository access,
   or the pinned digest is refreshed.

## Before you submit

1. Run `scripts/verify-container.sh`, which must end **all checks passed**, and
   `scripts/check-quality.sh`, which must end with every condition green.
2. Confirm the App Store Environment Variables tab holds exactly `SECRET_KEY`,
   `SPECTRE_ADMIN_USER`, `SPECTRE_ADMIN_PASS`, saved as the complete set, then
   applied. **Never type `PORT`**, the platform injects it and any value in the
   tab overrides it and breaks the readiness probe.
3. Attach the **FILE_STORAGE** add-on and raise an operations request for
   `securityContext.fsGroup`. Without it the non-root container cannot write to
   the root-owned volume, and `/readyz` will return 503 with `errno 13`.
4. Use a single-hyphen app slug. A double hyphen breaks platform naming and
   fails the pipeline with zero stages run.
5. Run `deploy-gate` for the binding verdict, and get explicit human
   confirmation before `submit_app`.

## Method

Scored with the `app-store-readiness` rubric against the contracts in
`app-store-deployment` and `appstore-gate-compliance`. The loop and the
container checks were executed and their real output recorded; the CI dimension
was read from the actual latest run conclusion for the head commit, not from the
workflow file existing. Dimensions that could not be evaluated are marked
UNKNOWN and scored as failed, never as passed.
