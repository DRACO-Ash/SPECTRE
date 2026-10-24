"""Comments name the control that actually keeps the runtime lock a subset.

Audit F-184. Four files said scripts/check-quality.sh asserts that
requirements-runtime.txt is a version-identical subset of requirements.txt.
It contains no such check; scripts/preflight-gate.py and the deployment
contract test do.
"""

from __future__ import annotations

from tests.unit.test_deployment_contract import _repo_only

_FILES = ("requirements-runtime.in", "Dockerfile", "scripts/package-appstore.sh", "docs/DEPENDENCY-SCANNING.md")


def test_the_named_controls_contain_the_check() -> None:
    assert "def check_runtime_subset" in _repo_only("scripts/preflight-gate.py").read_text(encoding="utf-8")
    contract = _repo_only("tests/unit/test_deployment_contract.py").read_text(encoding="utf-8")
    assert "def test_manifests_do_not_drift" in contract
    assert "subset" not in _repo_only("scripts/check-quality.sh").read_text(encoding="utf-8").lower()


def test_no_file_credits_check_quality_with_it() -> None:
    for name in _FILES:
        text = " ".join(_repo_only(name).read_text(encoding="utf-8").split())
        assert "check-quality.sh asserts" not in text, name
        assert "`scripts/check-quality.sh` and" not in text, name
        assert "preflight-gate.py" in text, name
