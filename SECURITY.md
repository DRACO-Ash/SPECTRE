# Security Policy

SPECTRE is a restricted-access operational planning tool. This document sets out the supported version policy and the vulnerability reporting process.

For the full internal security policy (UK NCSC / SSCoP aligned), see [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Supported Versions

The supported-version policy is stated once, in [`docs/SECURITY.md`](docs/SECURITY.md#supported-versions): the latest commit on `master` is supported, and there are no release branches or backports.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately by one of the following methods:

1. **GitHub private advisory** — use the "Report a vulnerability" button on the Security tab of this repository
2. **Direct contact** — contact the repository owner (`@Higgy-843`) via a private channel

### What to include

- Description of the vulnerability and affected component(s)
- Steps to reproduce or proof-of-concept (if available)
- Potential impact assessment
- Any suggested remediation

### Response timeline

| Stage | Target |
|-------|--------|
| Acknowledgement | Within 2 business days |
| Triage and severity rating | Within 5 business days |
| Fix or mitigation | Dependent on severity — Critical: 7 days; High: 30 days; Medium/Low: next sprint |
| Disclosure | After fix is deployed; coordinated with reporter |

---

## Dependency Scanning

Dependencies are scanned automatically:

- `pip-audit` runs on every push via GitHub Actions (`sca` job) and reports CVEs in installed packages
- `gitleaks` runs on every push and every commit via pre-commit to prevent credential leakage
- Dependabot is configured to open weekly PRs for pip and GitHub Actions updates

To run dependency scanning locally:

```powershell
pip-audit
```

---

## Known Security Limitations (Open Items)

| ID | Description | Risk | Status |
|----|-------------|------|--------|
| SEC-01 | No CSRF middleware | Medium | Closed: `spectre/web/csrf.py`, a global dependency on every unsafe method |
| SEC-02 | No per-user rate limiting on `/udl/*` proxy routes | Medium | Closed: `spectre/web/rate_limit.py` (UDL auth, data and sync tiers, plus login) |
| SEC-03 | No user management web UI | Operational | Closed: `spectre/web/routes/admin.py` |
| SEC-04 | No SBOM (Software Bill of Materials) generation in CI | Low | Closed: the SCA job writes a CycloneDX SBOM of `requirements-runtime.txt`, checks it lists every pin (`scripts/check-sbom.py`) and keeps it as the `sbom-cyclonedx` artifact |

SEC-01 to SEC-03 were closed in code that has been present since commit d671abe; this table was not updated at the time (audit F-281).

See `docs/SECURITY.md` for the full security policy and control framework.
