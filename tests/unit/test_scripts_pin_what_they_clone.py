"""A script that clones and builds a tool pins and verifies what it builds.

Audit F-183. verify-dependency-scan.sh cloned the upstream analyser at
whatever HEAD was current, built it and ran it, and package-appstore.sh ran
it automatically on every package build whenever Go was installed.
"""

from __future__ import annotations

import re

from tests.unit.test_deployment_contract import _REPO_ROOT, _repo_only

_SHA = re.compile(r"\b[0-9a-f]{40}\b")


def test_every_clone_names_a_ref_and_checks_a_commit() -> None:
    _repo_only("scripts")
    for path in sorted((_REPO_ROOT / "scripts").glob("*.sh")):
        text = path.read_text(encoding="utf-8")
        for line in (ln for ln in text.splitlines() if "git clone" in ln and not ln.lstrip().startswith("#")):
            assert "--branch" in line, f"{path.name}: clone with no pinned ref: {line.strip()}"
            assert _SHA.search(text), f"{path.name}: no commit to verify the clone against"
            assert "rev-parse" in text, f"{path.name}: the cloned commit is never checked"


def test_the_packager_runs_the_analyser_only_when_asked() -> None:
    text = _repo_only("scripts/package-appstore.sh").read_text(encoding="utf-8")
    call = next(ln for ln in text.splitlines() if "verify-dependency-scan.sh" in ln and ln.startswith("if "))
    assert "RUN_DS_VERIFY" in call and '= "1"' in call
