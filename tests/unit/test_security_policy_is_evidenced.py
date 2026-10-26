"""docs/SECURITY.md claims only controls the repository implements.

Audit F-057. It was a generic template asserting SHA-pinned Actions (then
pinned by tag), an SBOM, CodeQL, release signing, hypothesis tests, a main
branch, a CONTRIBUTING.md, that the application exposes no network service,
and a placeholder contact. Each control it now lists as in place cites the
file that implements it, and the CI job by name where there is one.
"""

from __future__ import annotations

import re

from tests.unit.test_deployment_contract import _REPO_ROOT, _repo_only


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:end if end != -1 else None]


def test_every_control_in_place_cites_an_artefact_that_exists() -> None:
    policy = _repo_only("docs/SECURITY.md").read_text(encoding="utf-8")
    workflow = _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs = set(re.findall(r"^  ([a-z_-]+):\s*$", workflow.split("\njobs:", 1)[1], re.M))
    rows = [ln for ln in _section(policy, "## Controls in place").splitlines() if ln.startswith("| ") and "---" not in ln]
    assert len(rows) > 10
    for row in rows[1:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        evidence = cells[-1]
        paths = re.findall(r"`([\w./-]+\.(?:py|yml|yaml|toml|txt|sh|md|cfg)|CODEOWNERS|Dockerfile)`", evidence)
        assert paths, f"no implementing file cited: {row}"
        for path in paths:
            assert (_REPO_ROOT / path).exists(), f"{path} does not exist: {row}"
        for job in re.findall(r"CI job `([a-z_-]+)`", evidence):
            assert job in jobs, f"CI job {job} does not exist: {row}"


def test_the_template_claims_are_gone() -> None:
    policy = _repo_only("docs/SECURITY.md").read_text(encoding="utf-8")
    in_place = _section(policy, "## Controls in place")
    for word in ("hypothesis", "Sigstore", "CONTRIBUTING.md"):
        assert word not in in_place, word


def test_code_scanning_and_the_sbom_are_claimed_only_with_their_workflows() -> None:
    """Both were template claims (F-057); both now exist, and say where."""
    policy = _repo_only("docs/SECURITY.md").read_text(encoding="utf-8")
    in_place = _section(policy, "## Controls in place")
    rows = {row.split("|")[1].strip(): row for row in in_place.splitlines() if row.startswith("| ")}
    assert "`.github/workflows/codeql.yml`" in rows["Code scanning"]
    assert "`scripts/check-sbom.py`" in rows["Software bill of materials"]
    workflow = _repo_only(".github/workflows/codeql.yml").read_text(encoding="utf-8")
    assert "github/codeql-action/analyze@" in workflow and "languages: python" in workflow
    assert "your-domain.example" not in policy
    assert "`main` branch" not in policy
    assert "does not expose network services" not in policy
