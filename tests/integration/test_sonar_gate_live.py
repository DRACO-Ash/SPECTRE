"""The SonarQube gate, run for real: a pinned SonarQube in docker, a real scan, a real verdict.

Runs when docker is available and skips otherwise, as the browser tests do
with Chromium. SPECTRE_SONAR_TESTS=require turns a missing docker into a
failure (CI's sonarqube job sets it); SPECTRE_SONAR_TESTS=skip leaves this to
that job. It starts its own server on a free port under its own container
name, so a SonarQube already running on the machine is never touched, and it
removes the container whatever happens.

One server, two analyses: a tree with a known bug must fail and name it, and
the same tree with the bug fixed must pass. The second run reuses the first
run's server through the credentials file a kept run leaves, so both the
start-a-server path and the reuse path are exercised.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "scripts" / "sonar-gate.sh"
_SH = shutil.which("sh") or "/bin/sh"
_DOCKER = shutil.which("docker")
_MODE = os.environ.get("SPECTRE_SONAR_TESTS", "auto")


def _docker_works() -> bool:
    if _DOCKER is None:
        return False
    # S603: fixed argv, no shell.
    return subprocess.run([_DOCKER, "info"], capture_output=True, check=False, timeout=60).returncode == 0  # noqa: S603


if not _GATE.is_file():
    pytest.skip("scripts/ is excluded from the submission package", allow_module_level=True)
if _MODE == "skip":
    pytest.skip("SPECTRE_SONAR_TESTS=skip", allow_module_level=True)
if not _docker_works():
    if _MODE == "require":
        pytest.fail("SPECTRE_SONAR_TESTS=require and docker is not available", pytrace=False)
    pytest.skip("docker is not available, so SonarQube cannot run here", allow_module_level=True)


_BUGGY = '''"""A fixture module with one known bug."""


def is_unset(total: float) -> bool:
    return total == 0.0
'''

_FIXED = '''"""The same module with the bug fixed."""

import math


def is_unset(total: float) -> bool:
    return math.isclose(total, 0.0, abs_tol=1e-12)
'''


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def server() -> Iterator[dict[str, str]]:
    """Names for one throwaway server; the container is removed on the way out."""
    name = f"spectre-sonar-gate-test-{uuid.uuid4().hex[:8]}"
    names = {"container": name, "host": f"http://127.0.0.1:{_free_port()}", "kept": ""}
    try:
        yield names
    finally:
        assert _DOCKER is not None
        subprocess.run([_DOCKER, "rm", "-f", "-v", name], capture_output=True, check=False, timeout=120)  # noqa: S603
        if names["kept"]:
            Path(names["kept"]).unlink(missing_ok=True)


def _run_gate(tree: Path, report: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # S603: fixed argv, no shell, test-controlled paths.
    return subprocess.run(  # noqa: S603
        [_SH, str(_GATE), str(tree)],
        env={**os.environ, "SONAR_REPORT": str(report), **env},
        capture_output=True, text=True, timeout=1500, check=False,
    )


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("sonar-gate-tree")
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "totals.py").write_text(_BUGGY, encoding="utf-8")
    return root


def test_a_known_bug_fails_the_gate_and_is_named(server: dict[str, str], tree: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    result = _run_gate(tree, report_path, {
        "SONAR_HOST_URL": server["host"], "SONAR_CONTAINER": server["container"], "SONAR_KEEP": "1",
    })
    output = result.stdout + result.stderr
    kept = re.search(r"its credentials are in (\S+) \(mode 0600\)", output)
    if kept:
        server["kept"] = kept.group(1)
    assert result.returncode == 1, output[-3000:]
    assert "app/totals.py:5 python:S1244" in output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "FAIL"
    assert {"file": "app/totals.py", "line": 5, "rule": "python:S1244"}.items() <= report["issues"][0].items()
    assert kept, "SONAR_KEEP=1 did not leave the credentials file it promises"
    assert oct(Path(kept.group(1)).stat().st_mode & 0o777) == "0o600"
    assert "admin:" not in output and "squ_" not in output, "a credential reached the output"


def test_the_fixed_tree_passes_on_the_reused_server(server: dict[str, str], tree: Path, tmp_path: Path) -> None:
    if not server["kept"]:
        pytest.fail("the first run left no server to reuse", pytrace=False)
    (tree / "app" / "totals.py").write_text(_FIXED, encoding="utf-8")
    report_path = tmp_path / "report.json"
    result = _run_gate(tree, report_path, {"SONAR_HOST_URL": server["host"], "SONAR_AUTH_FILE": server["kept"]})
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-3000:]
    assert "using the SonarQube already running" in output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert (report["verdict"], report["counts"]["issues"], report["counts"]["hotspots_to_review"]) == ("PASS", 0, 0)
