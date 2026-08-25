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

    def test_sweep_verification_uses_no_pipe(self, dockerfile: str) -> None:
        """`find ... | wc -l` would be fail-open, and hadolint DL4006 flags it.

        If find errored with stderr suppressed, wc would still exit 0 and print
        0, so the check would report a clean sweep over a dirty image. The
        verification therefore captures paths directly under `set -eu`.
        """
        sweep = dockerfile.split("# LAST mutation", 1)[1].split("FROM scratch", 1)[0]
        # Comments explain the trap and quote the banned form, so judge the
        # instructions only.
        instructions = "\n".join(
            line for line in sweep.splitlines() if not line.lstrip().startswith("#")
        )
        # `||` is logical OR, not a pipe; strip it before looking for a real one.
        piped = instructions.replace("||", "")
        assert "|" not in piped, "the suid verification must not pipe; a pipe is fail-open"
        assert "set -eu" in instructions, "the sweep must abort the build if find itself fails"

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

    def test_python_template_manifest_is_present(self) -> None:
        """The platform's Dependencies stage installs from requirements.txt.

        Without it the stage fails before anything else runs. Its presence also
        selects the python template, which is deliberate: the quality gate is
        met, and the Dockerfile still drives the container build.
        """
        assert (_REPO_ROOT / "requirements.txt").is_file()
        assert (_REPO_ROOT / "Dockerfile").is_file()

    def test_manifests_do_not_drift(self) -> None:
        """Every runtime pin in the lock must match requirements.txt exactly.

        The image installs from requirements.lock and the pipeline installs from
        requirements.txt. If they disagree, the tested set is not the shipped
        set, which is the kind of gap that only surfaces in production.
        """
        import re

        def pins(name: str) -> dict[str, str]:
            found = {}
            for line in (_REPO_ROOT / name).read_text(encoding="utf-8").splitlines():
                match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)", line)
                if match:
                    found[match.group(1).lower().replace("_", "-")] = match.group(2)
            return found

        lock = pins("requirements.lock")
        manifest = pins("requirements.txt")
        assert lock, "requirements.lock has no pins"
        drifted = {k: (v, manifest.get(k)) for k, v in lock.items() if manifest.get(k) != v}
        assert not drifted, f"runtime pins disagree between the manifests: {drifted}"

    def test_lockfile_is_the_hash_verified_one(self) -> None:
        """Only the lock carries hashes; it is what the image installs."""
        lock = (_REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
        dockerfile = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "--hash=sha256:" in lock
        assert "--require-hashes" in dockerfile
        assert "requirements.lock" in dockerfile


class TestVersionStamp:
    def test_version_is_single_sourced(self) -> None:
        from spectre import __version__
        from spectre.web.app import app

        assert app.version == __version__

    def test_pyproject_takes_its_version_from_the_package(self) -> None:
        body = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'dynamic = ["version"]' in body
        assert 'path = "spectre/__init__.py"' in body


class TestDatabasePortability:
    """The app must run on SQLite and on the PostgreSQL add-on alike."""

    def test_no_sqlite_only_sql_in_the_data_layer(self) -> None:
        """`PRAGMA` is SQLite-only and failed the whole boot on PostgreSQL.

        The migration helper used `PRAGMA table_info(...)` to check for a
        column. On PostgreSQL that is a bare syntax error, so attaching the
        add-on turned a working app into a crash loop. Schema inspection must
        go through SQLAlchemy's dialect-agnostic inspector instead.
        """
        import ast

        source = (_REPO_ROOT / "spectre" / "web" / "database.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Judge executable string literals only. Docstrings and comments discuss
        # the bug on purpose, and matching those would make this test unfixable.
        # Match docstring nodes by identity. Comparing values fails because
        # ast.get_docstring normalises whitespace.
        docstring_nodes = set()
        for node in ast.walk(tree):
            if not isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                continue
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))

        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_nodes
        ]
        offenders = [lit for lit in literals if "PRAGMA" in lit.upper()]
        assert not offenders, f"dialect-specific SQL in the data layer: {offenders}"
        assert "inspect(" in source, "schema checks must use the SQLAlchemy inspector"

    def test_async_postgres_driver_is_pinned(self) -> None:
        """The add-on is useless without a driver the async engine can use."""
        lock = (_REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
        assert "asyncpg==" in lock

    def test_sqlite_is_never_placed_on_the_injected_mount(self) -> None:
        """Guards the two-cycle deploy failure at the source level."""
        settings = (_REPO_ROOT / "spectre" / "config" / "settings.py").read_text(encoding="utf-8")
        sqlite_dir = settings.split("def _resolve_sqlite_dir", 1)[1].split("def ", 1)[0]
        assert "STORAGE_MOUNT_PATH" not in sqlite_dir, (
            "the SQLite directory must not derive from the object-storage mount"
        )


class TestDependencyScannerContract:
    """The platform's dependency scanner picks ONE directory and skips the rest.

    It detects a directory by the presence of a recognised manifest filename,
    announces "Dependency files in other directories will be skipped", and
    resolves only that one. A file merely *named* like a manifest anywhere below
    the root therefore hijacks the scan: the real lockfile is never read, the
    decoy resolves to nothing, and the stage exits non-zero with no report
    artifact to explain why. `spectre/app_logging/setup.py` did exactly that -
    a structlog configuration module with no `setup()` call in it.
    """

    # Names the scanner treats as a Python dependency manifest.
    _MANIFEST_NAMES = frozenset(
        {
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "requirements.txt",
            "requirements.lock",
            "Pipfile",
            "Pipfile.lock",
            "poetry.lock",
            "pdm.lock",
            "uv.lock",
        }
    )

    # Directories that never reach the scanner: not shipped, or not source.
    _IGNORED = frozenset({".git", ".venv", "venv", "dist", "build", "node_modules", "__pycache__"})

    def test_no_manifest_outside_the_repository_root(self) -> None:
        strays = []
        for path in _REPO_ROOT.rglob("*"):
            if not path.is_file() or path.name not in self._MANIFEST_NAMES:
                continue
            if any(part in self._IGNORED for part in path.relative_to(_REPO_ROOT).parts):
                continue
            if path.parent == _REPO_ROOT:
                continue
            strays.append(str(path.relative_to(_REPO_ROOT)))

        assert not strays, (
            "these files sit below the root and are named like dependency manifests, so "
            f"the scanner will resolve them INSTEAD of requirements.lock: {strays}. "
            "Rename them (a module named setup.py is the usual culprit) or move them to the root."
        )

    def test_no_self_referencing_extra_in_pyproject(self) -> None:
        """A self-referencing extra sends resolvers to an index for our own name.

        `spectre[test]` inside an optional-dependency group means any tool that
        reads pyproject.toml without our source tree must fetch a distribution
        called `spectre` from PyPI, where an unrelated package of that name
        already exists. List the packages explicitly instead.
        """
        pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        extras = pyproject.split("[project.optional-dependencies]", 1)
        assert len(extras) == 2, "pyproject.toml must declare optional-dependencies"
        block = extras[1].split("\n[", 1)[0]
        offenders = [
            line.strip()
            for line in block.splitlines()
            if not line.lstrip().startswith("#") and '"spectre' in line
        ]
        assert not offenders, (
            f"optional-dependency groups must not reference the project itself: {offenders}"
        )
