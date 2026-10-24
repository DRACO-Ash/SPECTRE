"""The docs describe the test suite and CI that exist.

Audit F-180. pyproject.toml declared an `integration` marker no test used and
nothing read SPECTRE_INTEGRATION_TESTS, though README.md and
docs/architecture.md described opt-in network tests guarded by both; both
claimed "74 parametrised tactical solver cases" for a file with no
parametrisation, and README.md listed five CI jobs where ci.yml has seven.
"""

from __future__ import annotations

import re
import tomllib

from tests.unit.test_deployment_contract import _REPO_ROOT, _repo_only


def test_every_declared_marker_is_used() -> None:
    config = tomllib.loads(_repo_only("pyproject.toml").read_text(encoding="utf-8"))
    markers = [m.split(":")[0].strip() for m in config["tool"]["pytest"]["ini_options"].get("markers", [])]
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (_REPO_ROOT / "tests").rglob("*.py"))
    for marker in markers:
        assert f"mark.{marker}" in sources, f"marker {marker!r} is declared and used by no test"


def test_no_doc_promises_tests_that_do_not_exist() -> None:
    for name in ("README.md", "docs/architecture.md"):
        text = _repo_only(name).read_text(encoding="utf-8")
        assert "SPECTRE_INTEGRATION_TESTS" not in text, name
        assert "opt-in network" not in text, name
        assert not re.search(r"\d+\+?\s+parametrised", text), name


def test_the_readme_lists_every_ci_job() -> None:
    workflow = _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs = re.findall(r"^  ([a-z_-]+):\s*$", workflow.split("\njobs:", 1)[1], re.M)
    line = next(ln for ln in _repo_only("README.md").read_text(encoding="utf-8").splitlines() if "workflows/ci.yml" in ln)
    for job in jobs:
        assert job in line, f"README's CI line omits {job}"
