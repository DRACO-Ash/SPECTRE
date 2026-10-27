# Security Policy

> **Project:** Space Planning, Evaluation & Counter-Threat Response Engine
> **Owner:** Ashley Higgins
> **Last reviewed:** 2026-10-24 (rewritten against the repository, audit F-057)
> **Next review due:** 2027-04-24

This policy says what the repository actually does. Each control listed as in
place names the file or CI job that implements it, and a test
(`tests/unit/test_security_policy_is_evidenced.py`) fails if a cited file or
job disappears. Controls that are not in place are listed as open items, not
implied. The previous version was a generic template that claimed several
controls this repository does not have.

It is written with the [UK NCSC Secure Development and Deployment Guidance](https://www.ncsc.gov.uk/collection/developers-collection),
the [UK Software Security Code of Practice](https://www.gov.uk/government/publications/software-security-code-of-practice)
and [Cyber Essentials](https://www.ncsc.gov.uk/cyberessentials/overview) in mind.
Alignment with them is the owner's assessment, not something the code proves.

## Reporting a vulnerability

Do not open a public GitHub issue for a security vulnerability. Report it
through GitHub Private Vulnerability Reporting, on the repository's Security
tab. Whether that feature is switched on is a repository setting; see the open
items.

Include a description and its impact, steps to reproduce, the affected commit
or version, and any suggested fix.

The owner's response commitments:

| Stage | Target |
|-------|--------|
| Acknowledge the report | 3 working days |
| Triage and severity assessment | 5 working days |
| Remediation plan to the reporter | 10 working days |
| Fix released, Critical or High | 30 calendar days from confirmed triage |
| Fix released, Medium or Low | 90 calendar days from confirmed triage |

Reporters are credited unless they ask not to be. No legal action is taken
against good-faith research that follows this policy.

## Supported versions

The latest commit on `master` is supported. The version in `pyproject.toml`
is 0.5.x; there are no release branches and no backports.

## Scope

In scope: the application source, the CI workflow, the dependency lock files,
the container image built from the `Dockerfile`, and documentation that
affects how a deployment is secured. Out of scope: the hosting platform and
upstream data services (UDL, GCAT), which their operators secure.

## Controls in place

| Control | What it does | Evidence |
|---------|--------------|----------|
| Least-privilege CI token | Workflow token is `contents: read`; no job escalates | `.github/workflows/ci.yml` (top-level `permissions`) |
| Actions pinned to commits | Each action is a 40-character commit, its release in a comment | `.github/workflows/ci.yml` |
| Secret scanning | gitleaks over full history on every push and pull request; the binary is checked against its published SHA-256 first | CI job `secrets` in `.github/workflows/ci.yml`; hook in `.pre-commit-config.yaml` |
| Static analysis | bandit, medium severity and above, fails the build | CI job `sast` in `.github/workflows/ci.yml` |
| Code scanning | CodeQL (Python, security-extended queries) on every push and pull request to `master` and weekly; the `master` ruleset blocks a merge on a high or higher security alert or an error alert | `.github/workflows/codeql.yml` |
| Software bill of materials | A CycloneDX SBOM of the image's Python packages, checked to list every pin and kept as the `sbom-cyclonedx` artifact; base-image OS packages and the vendored JavaScript are not in it | CI job `sca` in `.github/workflows/ci.yml`; `scripts/check-sbom.py` |
| Dependency vulnerabilities | pip-audit over the committed lock files; weekly Dependabot updates for pip and Actions | CI job `sca` in `.github/workflows/ci.yml`; `.github/dependabot.yml` |
| Hash-locked dependencies | Every install, in CI and in the image, uses `--require-hashes` | `requirements.txt`, `requirements-runtime.txt`, `Dockerfile` |
| Lint and strict typing | ruff; mypy in strict mode | CI job `lint` in `.github/workflows/ci.yml`; `pyproject.toml` (`strict = true`) |
| Tests and coverage | pytest with coverage floors | CI job `test` in `.github/workflows/ci.yml` |
| Quality gate on changed code | No new findings, complexity limit, changed-line coverage, duplication | CI job `quality` in `.github/workflows/ci.yml`; `scripts/check-quality.sh` |
| Container contract | Non-root numeric user, no setuid or setgid files, no package manager, refuses to boot without a real `SECRET_KEY` | CI job `container` in `.github/workflows/ci.yml`; `Dockerfile` |
| Code owners | Review by the owner on CI, authentication and configuration paths | `CODEOWNERS` |
| Pre-commit hooks | gitleaks, ruff, bandit, mypy, large files, no direct commit to `master` | `.pre-commit-config.yaml` |
| Fail-closed signing key | Refuses to boot with a missing, short or example `SECRET_KEY` | `spectre/config/settings.py` |
| Password storage | bcrypt; sign-in verification runs off the event loop, against a dummy hash for unknown users; a password over bcrypt's 72 bytes is refused at create and reset and counted as a failed sign-in | `spectre/web/auth.py`, `spectre/web/routes/login.py`, `spectre/web/routes/admin.py` |
| Sessions | Signed cookie bound to the account (id and a per-account random nonce), 8 hour expiry, revoked server-side on logout and password change; only a live session can log out or receive a CSRF token | `spectre/web/auth.py`, `spectre/web/routes/login.py` |
| Cookie attributes | Secure (unless explicitly disabled for local HTTP), HttpOnly, SameSite=Lax | `spectre/web/routes/login.py` |
| CSRF | Token on every state-changing request; a pre-session token on sign-in | `spectre/web/csrf.py` |
| Sign-in throttling | Limits per client address and per username | `spectre/web/routes/login.py`, `spectre/web/rate_limit.py` |
| UDL call throttling | Limits on UDL authentication, data and sync calls | `spectre/web/rate_limit.py` |
| Compute bounds | Monte Carlo horizon at most 720 hours, photometry CSV at most 512 KiB, and a per-operator limit shared by both | `spectre/web/routes/pol.py`, `spectre/web/rate_limit.py` |
| Security headers | Content Security Policy with no third-party hosts, nosniff, frame restrictions, HSTS over HTTPS | `spectre/web/app.py` |
| Log injection | Operator-supplied values are neutralised before logging | `spectre/web/log_safety.py` |
| Administration | Admin-only routes; the last admin cannot be removed, even by concurrent changes | `spectre/web/routes/admin.py` |

`spectre/web/app.py` records, beside the policy, what the Content Security
Policy does not stop: `script-src` still allows inline script.

## Network exposure

SPECTRE is a web server. It listens on all interfaces on port 8080, or on the
port the platform injects through `PORT`. It is meant to sit behind the
hosting platform's TLS-terminating router; it does not terminate TLS itself.

## Data handling

● The repository holds UDL TACREP_NOTSO notifications marked `U//DS-JCO-NOTIF`
(`spectre/data/notso_cache.json`), held by the owner's ruling of
24 October 2026, which covers a public repository. The application serves the
cache only to operators with their own UDL session.

● The adversary satellite records (`spectre/data/adversary_intel.json`) are
marked `UNCLASS // PAIR` in the file, by the owner's ruling of 24 October 2026.

● The application holds personal data: operator accounts (username, bcrypt
password hash, role) and log lines recording usernames and client addresses on
sign-in attempts. That brings it within UK GDPR; see the open items.

● UDL credentials are held in memory for one sign-in only, never shared with
another sign-in of the same account, cleared on logout, password change and
account deletion, dropped when the session cookie expires, and never written
to disk.

## Open items

Owner for all items: Ashley Higgins, unless reassigned.

| Item | State |
|------|-------|
| Private Vulnerability Reporting | A repository setting; confirm it is switched on |
| Disclosure email | The template's placeholder address was removed; add a monitored address if one is wanted |
| Branch protection on `master` | A repository setting, not visible from the code; recommended settings were given on 23 October 2026 |
| Signed commits | Not required by any setting the code can show |
| Release signing and provenance | Not in place; there is no release pipeline |
| Container image vulnerability scan in CI | Not in CI; the hosting platform scans the image, which this repository cannot verify |
| Licence audit | Not in place |
| Property-based tests | None; `hypothesis` is not used |
| Structured JSON logging | `spectre/app_logging/config.py` defines it, but the web application never calls it |
| CONTRIBUTING.md | Absent |
| Data protection | Operator accounts and sign-in logs are personal data; a DPIA screening and a retention period for logs are due |

## Incident response

1. Contain: revoke compromised credentials; disable affected deployments if needed.
2. Assess: establish scope and impact from the GitHub audit log, CI logs and application logs.
3. Remediate: fix, rotate secrets, update dependencies, release.
4. Communicate: notify affected users through a GitHub Security Advisory.
5. Review: a post-incident review within 10 working days, and an update to this policy.

A personal data breach also follows the owner's UK GDPR breach procedure.

## Exceptions

A deviation from this policy is recorded with its rationale and risk
assessment, approved by the owner, given an end date and a remediation plan,
and entered in the risk register.

## References

● [UK NCSC Secure Development and Deployment Guidance](https://www.ncsc.gov.uk/collection/developers-collection)
● [UK Software Security Code of Practice (DSIT, May 2025)](https://www.gov.uk/government/publications/software-security-code-of-practice)
● [Cyber Essentials](https://www.ncsc.gov.uk/cyberessentials/overview)
● [OWASP Top 10](https://owasp.org/www-project-top-ten/)
