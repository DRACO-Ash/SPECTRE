# Security Policy

> **Project:** Space Planning, Evaluation & Counter-Threat Response Engine  
> **Classification:** UNCLASSIFIED  
> **Policy Version:** 1.0  
> **Last Reviewed:** 2026-04-08  
> **Next Review Due:** 2026-10-08  
> **Owner:** Ashley Higgins

This policy aligns with the [UK NCSC Secure Development and Deployment Guidance](https://www.ncsc.gov.uk/collection/developers-collection), the [UK Software Security Code of Practice (May 2025)](https://www.gov.uk/government/publications/software-security-code-of-practice), and [Cyber Essentials](https://www.ncsc.gov.uk/cyberessentials/overview) baseline controls.

---

## Supported Versions

| Version | Supported | Notes |
|---------|-----------|-------|
| main (latest release) | ✅ Yes | Security patches applied promptly |
| Previous minor release | ✅ Yes | Critical and high severity patches only |
| Older releases | ❌ No | Upgrade to a supported version |

We follow [Semantic Versioning](https://semver.org/). Security fixes are backported to the current and immediately previous minor release only.

---

## Reporting a Vulnerability

**Do not open a public GitHub Issue for security vulnerabilities.**

### Preferred Method

Use [GitHub Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) via the **Security** tab of this repository.

### Alternative Method

Email: **[security@your-domain.example]** (replace with your actual security contact)

### What to Include

- Description of the vulnerability and its potential impact.
- Steps to reproduce (minimal proof of concept where possible).
- Affected version(s) and configuration.
- Any suggested remediation, if known.

### Our Commitment

| Stage | Target |
|-------|--------|
| Acknowledgement of report | Within 3 working days |
| Initial triage and severity assessment | Within 5 working days |
| Remediation plan communicated to reporter | Within 10 working days |
| Patch released (Critical/High severity) | Within 30 calendar days of confirmed triage |
| Patch released (Medium/Low severity) | Within 90 calendar days of confirmed triage |

We will credit reporters (unless anonymity is requested) in the release notes and any associated GitHub Security Advisory.

We will not take legal action against researchers who report vulnerabilities in good faith and in accordance with this policy.

---

## Scope

This policy covers:

- All application source code in this repository.
- CI/CD pipeline configurations (GitHub Actions workflows).
- Dependencies (direct and transitive) declared in `pyproject.toml`, `requirements*.txt`, or lockfiles.
- Container images and build artefacts produced by this repository.
- Documentation and configuration that affects the security posture of a deployment.

This policy does **not** cover:

- Third-party services or infrastructure not managed by this project (e.g. cloud provider controls, upstream TLE data feeds).
- Deployments operated by third parties unless they are using an officially supported release.

---

## Secure Development Practices

These practices are aligned to the four themes of the UK Software Security Code of Practice (SSCoP) and the NCSC's eight secure development principles.

### Theme 1 — Secure Design and Development

**SSCoP Principles 1–4: Secure development framework, software composition, testing, secure-by-design**

- **Threat modelling.** We maintain a threat model (STRIDE-based) for the application. It is reviewed when the architecture changes or new external interfaces are introduced.
- **Secure-by-default configuration.** The application ships with secure defaults. Sensitive configuration (API keys, data source credentials, file paths) is externalised to environment variables or TOML configuration files and is never hard-coded.
- **Input validation.** All external inputs (TLE data, observation files, user-supplied orbital parameters) are validated for format, range, and physical plausibility before processing. Prepared/parameterised queries are used where applicable.
- **Dependency management.** All direct dependencies are declared with pinned versions. We use Dependabot (or Renovate) for automated vulnerability scanning of dependencies. Transitive dependencies are audited periodically.
- **Software Bill of Materials (SBOM).** An SBOM in CycloneDX or SPDX format is generated as part of the release pipeline and published alongside each release artefact.
- **Licence compliance.** All dependencies are checked for licence compatibility (GPL contamination, export control relevance). This is documented in the dependency manifest.
- **Testing.** Security-relevant tests are part of the CI gate:
  - Unit tests covering input validation, authentication, and authorisation logic.
  - Property-based tests (via `hypothesis`) for coordinate frame round-trips and numerical invariants.
  - Static analysis and linting (see CI/CD section below).

### Theme 2 — Build Environment Security

**SSCoP Principles 5–6: Protect the build environment, control and log changes**

- **Branch protection.** The `main` branch requires:
  - At least one approved pull request review before merge.
  - All required status checks to pass (SAST, SCA, unit tests, secret scan).
  - Signed commits (GPG or SSH signature) for all contributors.
  - No force pushes; no deletion of protected branches.
  - Conversations must be resolved before merge.
- **CODEOWNERS.** A `CODEOWNERS` file enforces review by designated maintainers for security-sensitive paths (CI workflows, authentication modules, configuration schemas, Dockerfiles).
- **Least-privilege CI.** GitHub Actions workflows use minimal `GITHUB_TOKEN` permissions (`contents: read` by default). Elevated permissions are scoped per-job, not per-workflow.
- **Pinned Actions.** All third-party GitHub Actions are pinned by full commit SHA, not by mutable tag.
- **Ephemeral runners.** CI jobs run on GitHub-hosted (or ephemeral self-hosted) runners. No persistent state is retained between workflow runs.
- **Secrets management.** Repository and environment secrets are used for sensitive values. Long-lived credentials are avoided; OIDC federation is used for cloud authentication where possible.
- **Environment protection.** Production deployment environments require manual approval and are restricted to designated deployers.

### Theme 3 — Secure Deployment and Maintenance

**SSCoP Principles 7–11: Secure deployment, vulnerability management, update mechanism, data protection, resilience**

- **Automated vulnerability scanning.** Dependabot alerts and GitHub Code Scanning (CodeQL or Bandit-based SAST) are enabled on this repository.
- **Patch cadence.** Critical and high-severity dependency vulnerabilities are patched or mitigated within 14 calendar days of disclosure. Medium and low within 90 days.
- **Release signing.** Release artefacts (wheels, tarballs, container images) are signed. Provenance attestations are generated via GitHub Attestations or Sigstore where supported.
- **No secrets in artefacts.** The build pipeline includes a pre-release check to ensure no credentials, API keys, or sensitive configuration are embedded in distributable artefacts.
- **Rollback capability.** Deployment procedures support rollback to the previous known-good release within minutes.
- **Logging and monitoring.** The application uses structured logging (JSON format via `structlog` or equivalent). Security-relevant events (authentication attempts, configuration changes, data source access failures) are logged. Sensitive data (credentials, PII, raw observation data above a defined classification) is never logged.

### Theme 4 — Communication with Customers

**SSCoP Principles 12–14: Vulnerability disclosure, security guidance, end-of-life**

- **Vulnerability disclosure.** This SECURITY.md is the published disclosure policy. GitHub Security Advisories are used for coordinated disclosure.
- **Security guidance.** Deployment and hardening guidance is provided in the project documentation.
- **End of life.** When a version reaches end of support, this is communicated in the CHANGELOG, README, and via a GitHub discussion or announcement. A minimum of 90 days' notice is provided before removing security support.

---

## CI/CD Security Pipeline

### Minimum Viable Secure Pipeline (all PRs)

| Check | Tool | Gate |
|-------|------|------|
| Secret detection | `gitleaks` or `trufflehog` (pre-commit + CI) | Block merge on any finding |
| Dependency vulnerability scan | Dependabot / `pip-audit` / `safety` | Block merge on Critical/High CVEs |
| Static analysis (SAST) | `bandit` (Python) + CodeQL | Block merge on High+ findings |
| Linting | `ruff` / `flake8` with security plugins | Block merge on error-level findings |
| Unit and property-based tests | `pytest` + `hypothesis` | Block merge on failure |
| Type checking | `mypy --strict` | Block merge on error |

### Enhanced Pipeline (releases and protected branches)

All of the above, plus:

| Check | Tool | Notes |
|-------|------|-------|
| SBOM generation | `cyclonedx-bom` / `syft` | Attached to release artefacts |
| Container image scan | `trivy` / `grype` | If container images are produced |
| Artefact signing | Sigstore / GitHub Attestations | Provenance chain for release artefacts |
| Licence audit | `liccheck` / `pip-licenses` | Ensure no GPL contamination without review |
| Performance regression | `pytest-benchmark` baselines | Alert on significant regression |

---

## Pre-Commit Hooks (Developer Workstation)

Contributors are expected to install pre-commit hooks before pushing:

```bash
pip install pre-commit
pre-commit install
```

The `.pre-commit-config.yaml` should include at minimum:

- `gitleaks` — prevent secrets from entering version control.
- `ruff` — fast Python linting.
- `bandit` — Python security linter.
- `mypy` — type checking.
- `check-added-large-files` — prevent accidental commit of large data files (ephemerides, observation datasets).

---

## Authentication and Access Control

- **Multi-factor authentication (MFA)** is required for all organisation members and outside collaborators with write access to this repository. This aligns with Cyber Essentials expectations for access control and user authentication.
- **Least privilege.** Repository permissions follow the principle of least privilege. Read access is the default; write access is granted only to active contributors; admin access is restricted to designated maintainers.
- **Service accounts and tokens.** Personal Access Tokens (PATs) are scoped to the minimum required permissions, have expiry dates, and are rotated at least every 90 days. Fine-grained PATs are preferred over classic tokens.
- **SSH keys.** Contributors should use SSH keys with passphrases for Git operations. Key rotation is recommended annually.

---

## Data Handling

- **No classified data.** This repository and all associated artefacts, CI pipelines, and deployments operate at UNCLASSIFIED only.
- **TLE and observation data.** Publicly available TLE data (e.g. from CelesTrak or Space-Track) may be ingested. Contributors must not commit Space-Track credentials, CUI-marked data, or any data subject to distribution restrictions to this repository.
- **Earth Orientation Parameters and ephemerides.** These are public scientific data. Version and provenance should be logged but they carry no classification constraint.
- **Personal data.** This application does not process personal data. If this changes, a Data Protection Impact Assessment (DPIA) must be conducted and this policy updated.

---

## Cyber Essentials Alignment

This project's controls map to the five Cyber Essentials technical control themes:

| CE Control Area | How We Address It |
|-----------------|-------------------|
| **Firewalls / Internet gateways** | Application does not expose network services by default. If deployed as a service, firewall rules and network segmentation are documented in deployment guidance. |
| **Secure configuration** | Secure-by-default configuration; no default passwords; hardened CI/CD pipeline; minimal attack surface. |
| **User access control** | MFA enforced for all repository collaborators; least-privilege permissions; PAT scoping and rotation. |
| **Malware protection** | Dependency scanning (SCA); static analysis (SAST); container image scanning; pre-commit secret detection. |
| **Patch management** | Dependabot automated alerts; defined patch cadence (14 days Critical/High, 90 days Medium/Low); supported version policy. |

---

## NCSC Secure Development Principles Alignment

| NCSC Principle | How We Address It |
|----------------|-------------------|
| Secure development is everyone's concern | Security is part of the definition of done for all PRs. All contributors run pre-commit hooks. |
| Keep your security knowledge sharp | Team reviews OWASP Top 10 and NCSC advisories quarterly. Relevant CVEs are discussed in team standups. |
| Produce clean and maintainable code | Enforced linting, type checking, and code review. Naming conventions and documentation standards are defined in CONTRIBUTING.md. |
| Secure your development environment | MFA, signed commits, least-privilege access, no shared credentials. |
| Protect your code repository | Branch protection, CODEOWNERS, audit logging via GitHub. |
| Secure the build and deployment pipeline | Pinned Actions, minimal token permissions, ephemeral runners, OIDC for cloud auth, environment protection rules. |
| Continually test your security | Automated SAST, SCA, secret scanning on every PR. Periodic manual review of threat model. |
| Plan for security flaws | This vulnerability disclosure policy; defined patch cadence; incident response contact; rollback capability. |

---

## Incident Response

If a security incident is identified (e.g. compromised credentials, malicious dependency, unauthorised access):

1. **Contain.** Revoke compromised credentials immediately. Disable affected deployments if necessary.
2. **Assess.** Determine the scope and impact. Review audit logs (GitHub audit log, CI logs, application logs).
3. **Remediate.** Apply fixes, rotate secrets, update dependencies. Issue a patched release.
4. **Communicate.** Notify affected users via GitHub Security Advisory. Update this policy if process gaps are identified.
5. **Review.** Conduct a post-incident review within 10 working days. Document lessons learned and update the threat model.

---

## Exceptions and Deviations

Any deviation from this policy must be:

- Documented with a rationale and risk assessment.
- Approved by the project security lead.
- Time-bound with a remediation plan.
- Recorded in the project's risk register.

---

## References

- [UK NCSC Secure Development and Deployment Guidance](https://www.ncsc.gov.uk/collection/developers-collection)
- [UK Software Security Code of Practice (DSIT, May 2025)](https://www.gov.uk/government/publications/software-security-code-of-practice)
- [UK NCSC SSCoP Assurance Principles and Claims](https://www.ncsc.gov.uk/guidance/software-security-code-of-practice-assurance-principles-claims)
- [NCSC SSCoP Implementation Guidance](https://www.ncsc.gov.uk/collection/software-security-code-of-practice-implementation-guidance)
- [Cyber Essentials Requirements](https://www.ncsc.gov.uk/cyberessentials/overview)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [GitHub Security Best Practices](https://docs.github.com/en/code-security)

---

## Policy Review

This policy is reviewed at minimum every six months, or immediately following:

- A security incident affecting this project.
- A significant change to the project's architecture or deployment model.
- Publication of updated UK NCSC or SSCoP guidance.
- Changes to the project's classification level or data handling requirements.

---

*This document should be placed at `SECURITY.md` in the repository root. GitHub will automatically surface it in the repository's Security tab.*
