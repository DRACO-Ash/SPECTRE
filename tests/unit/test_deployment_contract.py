"""Static assertions over the Bluestaq App Store deployment contract.

Every rule here cost a real upload cycle to learn somewhere, so each is pinned
as a test rather than a comment. The Dockerfile ships inside the uploaded
package, so these assertions hold in every environment: the repository, a fresh
unzip of the artefact, and the platform's own checkout.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    assert _DOCKERFILE.is_file(), "Dockerfile must sit at the package root for template detection"
    return _DOCKERFILE.read_text(encoding="utf-8")


class TestPortContract:
    def test_no_env_port_is_baked_into_the_image(self, dockerfile: str) -> None:
        """An ENV line always beats the code fallback and breaks the readiness probe."""
        assert not re.search(r"^\s*ENV\s+PORT=", dockerfile, re.MULTILINE)
        assert not re.search(r"^\s*ENV\s+.*\bPORT=", dockerfile, re.MULTILINE)

    def test_exposes_8080(self, dockerfile: str) -> None:
        assert re.search(r"^\s*EXPOSE\s+8080\s*$", dockerfile, re.MULTILINE)

    def test_code_default_port_is_8080(self) -> None:
        from spectre.config.settings import DEFAULT_PORT

        assert DEFAULT_PORT == 8080


class TestStorageContract:
    def test_no_data_dir_is_baked_into_the_image(self, dockerfile: str) -> None:
        """A baked path sends writes to the ephemeral layer, lost on redeploy."""
        for banned in ("DATA_DIR=", "STORAGE_MOUNT_PATH=", "DATABASE_URL="):
            assert not re.search(rf"^\s*ENV\s+.*{re.escape(banned)}", dockerfile, re.MULTILINE), (
                f"{banned} must resolve in code, never via ENV"
            )


class TestImageHardening:
    def test_runs_as_a_non_root_numeric_user(self, dockerfile: str) -> None:
        users = re.findall(r"^\s*USER\s+(\S+)", dockerfile, re.MULTILINE)
        assert users, "the image must declare a USER"
        uid = users[-1].split(":")[0]
        assert uid.isdigit(), "USER must be numeric so the platform can resolve it"
        assert int(uid) != 0, "the container must not run as root"

    def test_final_stage_is_flattened_from_scratch(self, dockerfile: str) -> None:
        """The scan reads layer history; one clean layer is the only fix."""
        assert re.search(r"^\s*FROM\s+scratch\s*$", dockerfile, re.MULTILINE)
        assert re.search(r"^\s*COPY\s+--from=prep\s+/\s+/\s*$", dockerfile, re.MULTILINE)

    def test_path_is_re_declared_after_scratch(self, dockerfile: str) -> None:
        """FROM scratch inherits nothing, PATH included."""
        after_scratch = dockerfile.split("FROM scratch", 1)[1]
        assert "PATH=" in after_scratch

    def test_suid_sweep_is_the_last_mutation_of_the_prep_stage(self, dockerfile: str) -> None:
        """A later instruction can re-introduce the bits the sweep just cleared."""
        prep = dockerfile.split("FROM scratch", 1)[0]
        run_blocks = [m.start() for m in re.finditer(r"^\s*RUN\s", prep, re.MULTILINE)]
        sweep = prep.rfind("perm /6000")
        assert sweep != -1, "the prep stage must strip setuid/setgid bits"
        assert max(run_blocks) <= sweep, "no RUN may follow the suid sweep"

    def test_sweep_fails_the_build_closed(self, dockerfile: str) -> None:
        """A residual bit must stop the build, not ship a scan violation."""
        assert "exit 1" in dockerfile.split("perm /6000", 1)[1]

    def test_base_image_is_pinned_by_digest(self, dockerfile: str) -> None:
        assert re.search(r"BASE_IMAGE=\S+@sha256:[0-9a-f]{64}", dockerfile)


class TestPackaging:
    def test_dockerignore_exists_and_excludes_secrets(self) -> None:
        ignore = _REPO_ROOT / ".dockerignore"
        assert ignore.is_file(), "the image build context must be shaped by a .dockerignore"
        body = ignore.read_text(encoding="utf-8")
        assert ".env" in body
        assert ".git" in body

    def test_lockfile_is_committed_and_hash_pinned(self) -> None:
        lock = _REPO_ROOT / "requirements.lock"
        assert lock.is_file(), "a committed lockfile makes the install reproducible"
        body = lock.read_text(encoding="utf-8")
        assert "--hash=sha256:" in body, "the lockfile must pin hashes"
        assert re.search(r"^[a-z0-9_.-]+==", body, re.MULTILINE), "every dependency must be pinned"

    def test_docker_only_template_detection_is_unambiguous(self) -> None:
        """A root requirements.txt would switch the platform to the python template."""
        assert not (_REPO_ROOT / "requirements.txt").exists()
        assert (_REPO_ROOT / "Dockerfile").exists()


class TestVersionStamp:
    def test_version_is_single_sourced(self) -> None:
        from spectre import __version__
        from spectre.web.app import app

        assert app.version == __version__

    def test_pyproject_takes_its_version_from_the_package(self) -> None:
        body = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'dynamic = ["version"]' in body
        assert 'path = "spectre/__init__.py"' in body
