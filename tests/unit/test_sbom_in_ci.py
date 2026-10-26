"""SEC-04: CI produces an SBOM of what the image installs, and checks it.

The CycloneDX SBOM was written only by scripts/audit-dependencies.sh, run by
hand. CI now writes one for requirements-runtime.txt, the lock the image
installs, refuses it unless it lists every pinned package, and keeps it as a
build artifact. Owner request, 26 October 2026.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]


def _repo_file(relative: str) -> Path:
    """A repository file, skipping where the platform's tree omits it."""
    path = _ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not in this tree")
    return path


def _load_checker() -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_sbom", _repo_file("scripts/check-sbom.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_sbom"] = module
    spec.loader.exec_module(module)
    return module


def _sbom(names: list[str]) -> dict[str, object]:
    return {"bomFormat": "CycloneDX", "specVersion": "1.4",
            "components": [{"name": n, "version": "1.0"} for n in names]}


class TestTheSbomChecker:
    def test_an_sbom_listing_every_pin_passes(self, tmp_path: Path) -> None:
        checker = _load_checker()
        lock = tmp_path / "lock.txt"
        lock.write_text("Alpha_Pkg==1.0 \\\n    --hash=sha256:aa\nbeta[extra]==2.0 \\\n    --hash=sha256:bb\n")
        sbom = tmp_path / "sbom.json"
        sbom.write_text(json.dumps(_sbom(["alpha-pkg", "beta"])))
        assert checker.missing_from_sbom(sbom, lock) == []  # type: ignore[attr-defined]

    def test_a_pin_absent_from_the_sbom_is_named(self, tmp_path: Path) -> None:
        checker = _load_checker()
        lock = tmp_path / "lock.txt"
        lock.write_text("alpha==1.0\nbeta==2.0\n")
        sbom = tmp_path / "sbom.json"
        sbom.write_text(json.dumps(_sbom(["alpha"])))
        assert checker.missing_from_sbom(sbom, lock) == ["beta"]  # type: ignore[attr-defined]

    def test_a_document_that_is_not_cyclonedx_is_refused(self, tmp_path: Path) -> None:
        checker = _load_checker()
        lock = tmp_path / "lock.txt"
        lock.write_text("alpha==1.0\n")
        sbom = tmp_path / "sbom.json"
        sbom.write_text(json.dumps({"components": [{"name": "alpha"}]}))
        with pytest.raises(ValueError, match="CycloneDX"):
            checker.missing_from_sbom(sbom, lock)  # type: ignore[attr-defined]


class TestCiProducesTheSbom:
    def test_the_sca_job_writes_checks_and_keeps_it(self) -> None:
        ci = yaml.safe_load(_repo_file(".github/workflows/ci.yml").read_text(encoding="utf-8"))
        steps = ci["jobs"]["sca"]["steps"]
        runs = "\n".join(str(s.get("run", "")) for s in steps)
        assert "--format cyclonedx-json" in runs and "requirements-runtime.txt" in runs
        assert "scripts/check-sbom.py" in runs
        uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
        assert uploads and uploads[0]["with"]["if-no-files-found"] == "error"

    def test_sec_04_is_closed_in_both_policies(self) -> None:
        root = _repo_file("SECURITY.md").read_text(encoding="utf-8")
        row = next(ln for ln in root.splitlines() if ln.startswith("| SEC-04 "))
        assert "Closed" in row, row
        assert "| SBOM | Not produced in CI |" not in _repo_file("docs/SECURITY.md").read_text(encoding="utf-8")
