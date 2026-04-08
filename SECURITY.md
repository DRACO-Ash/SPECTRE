# Security Policy

SPECTRE is a restricted-access operational planning tool. This document sets out the supported version policy and the vulnerability reporting process.

For the full internal security policy (UK NCSC / SSCoP aligned), see [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| Current (`master`) | Yes |
| All prior releases | No — patch to latest |

SPECTRE follows a rolling-release model on `master`. There are no long-term support branches. All security fixes are applied to `master` only.

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

| ID | Description | Risk | Target sprint |
|----|-------------|------|---------------|
| SEC-01 | No CSRF middleware — form submissions are session-cookie authenticated only | Medium | P1 |
| SEC-02 | No per-user rate limiting on `/udl/*` proxy routes | Medium | P1 |
| SEC-03 | No user management web UI — new users require direct DB access | Operational | P1 |
| SEC-04 | No SBOM (Software Bill of Materials) generation in CI | Low | P2 |

See `docs/SECURITY.md` for the full security policy and control framework.
