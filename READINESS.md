# SPECTRE — Bluestaq App Store readiness report

**Band: Likely after fixes** · Weighted score **88%** (15 of 17 applicable dimensions pass)
Archetype: server (container) · Template: **docker-only** · Version **0.4.0**
Assessed 21 August 2026 against branch `claude/app-store-readiness-09re0q`.

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
| 1 | **Verification loop red.** 37 integration tests failed. Commit `d88cb69` added a global CSRF dependency but never updated the suite, so every authenticated POST returned 403. | `tests/integration/test_web_routes.py:150` — `assert 403 == 200` | `csrf_headers()` helper in `tests/conftest.py:34`; every non-safe request now mints a real token. The control is exercised, not disabled. |
| 2 | **CI red on `master` since 5 May 2026.** Run 43 (`b5621c2`): Tests and Lint both failed. Scored from the actual run conclusion, not the workflow file. | [run 29294546046](https://github.com/DRACO-Ash/SPECTRE/actions/runs/29294546046) | Blocker 1 fixes Tests. Lint failed on CI/local drift: the job installed a partial dependency set, so mypy disagreed with the local loop. It now runs `pip install -e ".[dev]"`. |
| 3 | **`GET /` returned 302.** The platform router probes the root and treats a redirect as a failed deploy. | `spectre/web/routes/operator.py:43` — `Depends(require_login)` raised `302` | New `optional_login` dependency (`spectre/web/auth.py:121`); anonymous callers get the login page at **200**. A test asserts console state still never leaks. |
| 4 | **No health or readiness endpoint.** The platform had no way to tell a live pod from a dead one. | no `/healthz` or `/readyz` anywhere in `spectre/web/routes/` | `spectre/web/health.py`. `/healthz` is liveness only; `/readyz` proves storage with a **real write**, races a 2 s timeout (shorter than the platform probe, so a stalled mount is a loud 503 rather than a silent liveness kill), and returns the resolved directory and exact errno in its 503 body. |
| 5 | **Wrong port, hard-coded.** Listened on 8000; the platform sets `containerPort: 8080`. | `spectre/web/_entrypoint.py:12` — `port=8000` | Resolves `PORT` in code, defaulting to 8080 (`spectre/config/settings.py:74`). No `ENV PORT=` anywhere: a baked ENV always beats a code fallback and breaks the readiness probe. |
| 6 | **Container ran as root**, shipped `gcc`, `apt` and `pip`, and carried the base image's setuid bits. The policy scan **stops** on `suid_or_guid_set`. | old `Dockerfile` — no `USER`, `apt-get install gcc` | Three-stage build. Runs `USER 10001:0`. Package managers and toolchain removed. The suid sweep is the **last** mutation of the prep stage and **fails the build closed** if anything remains. |
| 7 | **Layer history would have failed the scan.** An in-place `chmod` leaves path-less (`N/A`) findings from earlier base layers. | n/a — absent by construction | Runtime flattened: `FROM scratch` with a single `COPY --from=prep / /`, all metadata (including `PATH`) re-declared. |
| 8 | **Unpinned, unverifiable install.** The Dockerfile ran `pip install ".[standard]" \|\| pip install <hand-typed list>` — a fallback that silently installed a *different* dependency set. | old `Dockerfile` lines 16-20 | `requirements.lock`: 43 packages pinned with SHA-256 hashes, installed `--require-hashes --only-binary=:all:`. `pip-audit` over that exact file reports **no known vulnerabilities**. |
| 9 | **Baked `ENV DATABASE_URL` pointing into the image.** Writes would have landed on the ephemeral layer and vanished on redeploy. | old `Dockerfile` — `ENV DATABASE_URL="sqlite+aiosqlite:////app/data/spectre.db"` | Removed. Resolution is in code: explicit variable, then the injected `STORAGE_MOUNT_PATH`, then a local default. Validated at boot. |
| 10 | **No secret validation.** An empty or placeholder `SECRET_KEY` would boot and issue forgeable session and CSRF tokens. | `spectre/config/settings.py` — `secret_key` defaulted to `""` | `validate_secret_key` fails the boot closed on missing, placeholder or short keys. |

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
medium-and-above clean · **774 passed, 2 skipped**, coverage **70.10%**.

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
| Verification loop green | blocker | **PASS** | 774 passed, 2 skipped |
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
| Coverage at least 80% | heavy | **FAIL** | 70.10% — see gap 1 |
| Coverage report at the gate's path | heavy | **PASS** | `coverage.xml` emitted; unread under docker-only |
| Version stamp and audit row, generic client errors | medium | **PASS** | Single-sourced 0.4.0; boot logs its storage verdict |
| Surgical structure, documented architecture | medium | **PASS** | Changes confined to config, auth, health, entrypoint and packaging |
| Accessibility to WCAG AA | medium | **UNKNOWN** | Not assessed — see gap 3 |
| House voice in user-facing copy | light | **PASS** | UK English throughout the new copy |

SonarQube dimensions are **not applicable**: the docker-only template skips the
quality gate.

## Remaining gaps

**1. Coverage is 70.10%, the standard is 80%.** *(heavy, not a blocker here)*
Owner: `testing-standards`. Under docker-only the SonarQube gate is skipped, so
this does not fail the pipeline, but it is below the Foundations standard and it
is the one thing that would block a later move to the python template. The
shortfall is concentrated in the route layer: `threat.py` 29%, `udl.py` 27%,
`pol.py` 21%, `training.py` 30%, `maneuver.py` 52% — roughly 1,400 uncovered
statements, nearly all of it HTMX partial handlers. *Fix:* extend the pattern in
`tests/integration/test_plan_export.py` route by route, heaviest first. *Raises
the band to Ready when combined with gap 2.*

**2. The OS patch step could not be exercised here.** *(medium)*
Owner: `security-hardening`, `deploy-recipes`. `deb.debian.org` is blocked by
this network's egress policy, so `apt-get upgrade` reported **SKIPPED**, loudly,
naming its compensating control (the base image pinned by digest
`sha256:a116514e…`). It is written to distinguish "applied" from "skipped" and
never to report patched when nothing was checked. *Fix:* run
`scripts/verify-container.sh` once from a network that can reach the Debian
security repository and confirm the log reads `OS PATCH: applied`. If the
platform runner also cannot reach it, bump the pinned digest instead — that is
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

1. Run `scripts/verify-container.sh` — it must end **all checks passed**.
2. Confirm the App Store Environment Variables tab holds exactly `SECRET_KEY`,
   `SPECTRE_ADMIN_USER`, `SPECTRE_ADMIN_PASS`, saved as the complete set, then
   applied. **Never type `PORT`** — the platform injects it and any value in the
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
