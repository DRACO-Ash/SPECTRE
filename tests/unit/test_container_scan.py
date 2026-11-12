"""The container check scans the image the way the App Store's Container Scan does, and leaves nothing behind.

0.6.10 on the other line failed the App Store Container Scan on the interpreter, python-3.12.15 (CVE-2026-115557,
fixed in 3.12.16). Trivy does not read the CPython build in /usr/local, so a local Trivy run called the image clean;
Grype reads it. scripts/verify-container.sh now runs Grype and fails on a High or Critical finding that has a fix. A
scan that could not run is reported SKIPPED, never PASS, and the run's last line says so.

A run that died before its cleanup left the build host's proxy CA certificate and the patched Dockerfile in the
repository root, under names the ignore file missed by one character, where ``git add -A`` would commit them.

Every test here drives the script's own shell functions with ``docker`` stubbed, so none needs Docker or a network.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_deployment_contract import _repo_only

_SCRIPT = "scripts/verify-container.sh"
#: Base image digests a release must not ship on again, each with why.
_SUPERSEDED = {
    "6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70": "Python 3.12.15, CVE-2026-115557",
}
_BASE = re.compile(r"^ARG BASE_IMAGE=python:3\.12-slim-bookworm@sha256:([0-9a-f]{64})$", re.M)
#: The two files the script writes in the repository root while it builds behind a proxy.
_LEFT_BEHIND = (".verify-proxy-ca.crt", ".Dockerfile.verify")
#: Stands in for docker: logs its arguments, answers ``db update`` as $DB says, and prints $FINDINGS for a scan.
_DOCKER_STUB = """
docker() {
    printf '%s\\n' "$*" >> "$LOG"
    case "$*" in
        *" db update") [ "$DB" = ok ] ;;
        *) cat > /dev/null; printf '%s' "$FINDINGS" ;;
    esac
}
"""


def _sh() -> str:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX shell here")
    return sh


def _function(text: str, name: str) -> str:
    """The shell function *name* as the script defines it, on one line or many."""
    match = re.search(rf"^{name}\(\) \{{.*?\}}$", text, re.M) if f"{name}() {{ " in text else None
    match = match or re.search(rf"^{name}\(\) \{{\n.*?^\}}$", text, re.M | re.S)
    assert match, f"{_SCRIPT} defines no {name}()"
    return match.group(0)


def _harness(*names: str) -> str:
    text = _repo_only(_SCRIPT).read_text(encoding="utf-8")
    image = re.search(r"^GRYPE_IMAGE=.*$", text, re.M)
    assert image or "scan_image" not in names, f"{_SCRIPT} names no GRYPE_IMAGE"
    return "\n".join([_DOCKER_STUB, image.group(0) if image else "", *(_function(text, n) for n in names)])


def _scan(
    tmp_path: Path, env: dict[str, str], cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    log = tmp_path / "docker.log"
    log.touch()
    program = _harness("pass", "fail", "scan_image") + '\nIMAGE=spectre:verify\nscan_image\nprintf "state=%s\\n" "$SCAN_STATE"\n'
    # S603: a resolved shell running the repository's own functions.
    done = subprocess.run(  # noqa: S603
        [_sh(), "-c", program], capture_output=True, text=True, check=False, cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "LOG": str(log), "DB": "ok", "FINDINGS": "", **env},
    )
    return done, log.read_text(encoding="utf-8")


class TestTheImageScan:
    def test_an_unreachable_database_is_skipped_and_never_passed(self, tmp_path: Path) -> None:
        done, _ = _scan(tmp_path, {"DB": "unreachable"})
        assert done.returncode == 0, done.stderr
        assert "SKIPPED" in done.stdout and "not a pass" in done.stdout
        assert "PASS" not in done.stdout
        assert "state=SKIPPED" in done.stdout

    def test_a_fixable_high_or_critical_finding_fails_the_check(self, tmp_path: Path) -> None:
        finding = "\n    High CVE-2026-115557 python 3.12.15 -> 3.12.16"
        done, log = _scan(tmp_path, {"FINDINGS": finding})
        assert done.returncode == 1
        assert "CVE-2026-115557" in done.stdout and "FAIL" in done.stdout
        assert "--only-fixed" in log, "only findings with a fix stop the Container Scan"

    def test_no_fixable_finding_passes(self, tmp_path: Path) -> None:
        done, log = _scan(tmp_path, {})
        assert done.returncode == 0, done.stderr
        assert "PASS  no High or Critical finding has a fix available" in done.stdout
        assert "docker:spectre:verify" in log, "the image just built is the one scanned"

    def test_skip_image_scan_skips_without_calling_docker(self, tmp_path: Path) -> None:
        done, log = _scan(tmp_path, {"SKIP_IMAGE_SCAN": "1"})
        assert done.returncode == 0, done.stderr
        assert "SKIPPED" in done.stdout and "PASS" not in done.stdout
        assert log == ""

    def test_the_database_is_cached_in_a_named_volume(self, tmp_path: Path) -> None:
        _, log = _scan(tmp_path, {})
        assert all("-v spectre-grype-db:/db" in line for line in log.splitlines()), log

    def test_the_proxy_ca_reaches_the_database_download(self, tmp_path: Path) -> None:
        _, log = _scan(tmp_path, {"PROXY_CA_BUNDLE": "/certs/proxy.crt"})
        assert "/certs/proxy.crt:/etc/ssl/certs/ca-certificates.crt:ro" in log.splitlines()[0]

    def test_a_relative_proxy_ca_is_mounted_by_its_full_path(self, tmp_path: Path) -> None:
        # Docker reads a relative -v source as a named volume, so the database download would fail for the wrong reason.
        _, log = _scan(tmp_path, {"PROXY_CA_BUNDLE": "certs/proxy.crt"}, cwd=tmp_path)
        assert f"{tmp_path}/certs/proxy.crt:/etc/ssl/certs/ca-certificates.crt:ro" in log.splitlines()[0]

    def test_the_grype_image_is_pinned_by_digest(self) -> None:
        text = _repo_only(_SCRIPT).read_text(encoding="utf-8")
        assert re.search(r'^GRYPE_IMAGE="\$\{GRYPE_IMAGE:-anchore/grype:v[0-9.]+@sha256:[0-9a-f]{64}\}"$', text, re.M)

    def test_the_last_line_does_not_call_a_skipped_scan_a_pass(self) -> None:
        text = _repo_only(_SCRIPT).read_text(encoding="utf-8")
        assert re.search(r"^scan_image$", text, re.M), "the stage runs"
        assert '[ "$SCAN_STATE" = SKIPPED ]' in text.split("scan_image\n", 2)[-1]


class TestNothingIsLeftBehind:
    def test_the_exit_trap_removes_the_proxy_ca_and_the_patched_dockerfile(self, tmp_path: Path) -> None:
        for name in _LEFT_BEHIND:
            (tmp_path / name).write_text("left by a failed build", encoding="utf-8")
        program = _harness("cleanup") + '\nCONTAINER=spectre-verify-test\nWORK=""\ncleanup\n'
        # S603: a resolved shell running the repository's own function, in a scratch directory.
        done = subprocess.run(  # noqa: S603
            [_sh(), "-c", program], cwd=tmp_path, capture_output=True, text=True, check=False,
            env={"PATH": "/usr/bin:/bin", "LOG": str(tmp_path / "docker.log")},
        )
        assert done.returncode == 0, done.stderr
        assert [name for name in _LEFT_BEHIND if (tmp_path / name).exists()] == []

    @pytest.mark.parametrize("name", _LEFT_BEHIND)
    def test_git_ignores_what_a_failed_run_leaves(self, name: str) -> None:
        patterns = [
            line.strip().lstrip("/") for line in _repo_only(".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith(("#", "!"))
        ]
        assert any(fnmatch.fnmatchcase(name, p) for p in patterns), f"{name} would be committed by git add -A"


class TestTheBaseImage:
    @pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.docker-only"])
    def test_the_base_digest_is_not_a_superseded_one(self, dockerfile: str) -> None:
        digests = _BASE.findall(_repo_only(dockerfile).read_text(encoding="utf-8"))
        assert len(digests) == 1, f"{dockerfile} must pin one python:3.12-slim-bookworm digest"
        assert digests[0] not in _SUPERSEDED, f"{dockerfile} ships {_SUPERSEDED.get(digests[0])}"

    def test_both_dockerfiles_build_on_the_same_base(self) -> None:
        pinned = {name: _BASE.findall(_repo_only(name).read_text(encoding="utf-8"))
                  for name in ("Dockerfile", "Dockerfile.docker-only")}
        assert pinned["Dockerfile"] == pinned["Dockerfile.docker-only"]
