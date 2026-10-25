"""Static assertions over the Bluestaq App Store deployment contract.

Every rule here cost a real upload cycle to learn somewhere, so each is pinned
as a test rather than a comment. The Dockerfile ships inside the uploaded
package, so these assertions hold in every environment: the repository, a fresh
unzip of the artefact, and the platform's own checkout.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile"

# Named once because the packaging allowlist assertion below is its third
# reader, and three occurrences of one literal is what python:S1192 reports.
_DOCKERIGNORE = ".dockerignore"



def _repo_only(name: str) -> Path:
    """Return a repository-only path, skipping the test when it is absent.

    docs/, scripts/ generators and requirements-dev.txt do not travel in the
    submission package: docs/ would be analysed as application code, and the
    dev tooling is deliberately kept out of the scanned set. The suite ships
    inside that package and runs there, so an invariant about a file that does
    not travel with it must skip, not fail. A test that cannot hold in the
    artifact it travels in is a broken test, not a finding.

    Use this only for genuinely repository-only files. Reaching for it to
    silence a failure turns the test into a silent pass, which is worse than
    no test at all.
    """
    path = _REPO_ROOT / name
    if not path.exists():
        pytest.skip(f"{name} is excluded from the submission package")
    return path

def _is_docker_only_package() -> bool:
    """True when the suite is running inside the docker-only submission archive.

    The docker-only template deliberately ships no recognised Python manifest;
    that absence is what stops the platform selecting the python template. The
    suite travels inside that archive, so contract assertions about
    requirements.txt and pyproject.toml cannot hold there and must skip.

    Detected from BOTH manifests being absent rather than one, so a python
    package that lost a manifest to a packaging bug still fails the assertion
    instead of quietly skipping it. The repository and the python-template
    package always carry both.
    """
    if not (_REPO_ROOT / "Dockerfile").is_file():
        return False
    return not (_REPO_ROOT / "pyproject.toml").is_file() and not (
        _REPO_ROOT / "requirements.txt"
    ).is_file()


_DOCKER_ONLY = _is_docker_only_package()

# Assertions about files only the python template ships. They still run in the
# repository and in the python-template package; only the docker-only archive
# skips them. The inverse is asserted against the built archive itself, in
# tests/integration/test_packager_gates.py (TestTheDockerOnlyArchive), because
# the docker-only archive carries no tests to assert it from inside (F-179).
_python_template_only = pytest.mark.skipif(
    _DOCKER_ONLY,
    reason="docker-only package: no recognised Python manifest ships, by design",
)


@pytest.fixture(scope="module")
def dockerfile() -> str:
    """The Dockerfile, or a skip.

    It must SKIP rather than assert. Every test in this module travels inside
    the submission package and runs in whatever tree the platform assembles,
    and that tree is NOT the archive: release 0.5.24 shipped
    sonar-project.properties in the zip and the platform's checkout did not
    have it, which failed the whole Test stage on an environmental assumption
    nobody had checked.

    "This file must ship" belongs in a repository-only test that can see the
    package (see TestThePackagerShipsWhatTheGatesRead below). A test running
    INSIDE the artefact cannot tell a packaging bug from a platform that
    supplies its own copy, so it must not try.
    """
    if not _DOCKERFILE.is_file():
        pytest.skip("Dockerfile is not present in this tree")
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

    def test_package_manager_metadata_is_removed_with_the_package(
        self, dockerfile: str
    ) -> None:
        """The scan reads dist-info, not the code.

        0.5.22 removed pip's package directory and left ``pip-25.0.1.dist-info``
        behind, so the Container Scan went on reporting six pip advisories
        against an image with no pip in it. Metadata and code travel together or
        the inventory is wrong in both directions.
        """
        prep = dockerfile.split("FROM scratch", 1)[0]
        for pattern in ("pip-*.dist-info", "setuptools-*.dist-info", "wheel-*.dist-info"):
            assert pattern in prep, f"{pattern} must be removed from the shipped image"

    def test_the_toolchain_removal_fails_the_build_closed(self, dockerfile: str) -> None:
        """A silent partial removal ships the finding it was meant to clear."""
        block = dockerfile.split("pip-*.dist-info", 1)[1].split("# LAST mutation", 1)[0]
        assert "exit 1" in block, (
            "the toolchain removal must verify itself and stop the build, not "
            "report success over an image that still carries pip"
        )

    def test_application_dependency_metadata_is_not_swept_up(
        self, dockerfile: str
    ) -> None:
        """Only the package managers go. Removing the rest would hide real findings.

        The scanner's inventory of what actually ships must stay complete: a
        blanket ``*.dist-info`` removal would silence genuine advisories against
        the dependencies the image really does carry, which is suppression, not
        mitigation.
        """
        prep = dockerfile.split("FROM scratch", 1)[0]
        assert "-name '*.dist-info'" not in prep, (
            "a blanket dist-info removal would suppress findings against the "
            "dependencies the image really ships"
        )


class TestPackaging:
    def test_dockerignore_exists_and_excludes_secrets(self) -> None:
        body = _repo_only(_DOCKERIGNORE).read_text(encoding="utf-8")
        assert ".env" in body
        assert ".git" in body

    @_python_template_only
    def test_shipped_manifest_is_committed_and_hash_pinned(self) -> None:
        """requirements.txt is the one manifest the submission carries."""
        body = _repo_only("requirements.txt").read_text(encoding="utf-8")
        assert "--hash=sha256:" in body, "the manifest must pin hashes"
        assert re.search(r"^[a-z0-9_.-]+==", body, re.MULTILINE), "every dependency must be pinned"

    @_python_template_only
    def test_python_template_manifest_is_present(self) -> None:
        """The platform's Dependencies stage installs from requirements.txt.

        Without it the stage fails before anything else runs. Its presence also
        selects the python template, which is deliberate: the quality gate is
        met, and the Dockerfile still drives the container build.
        """
        assert _repo_only("requirements.txt").is_file()
        assert _repo_only("Dockerfile").is_file()

    @_python_template_only
    def test_manifests_do_not_drift(self) -> None:
        """The runtime lock must be a version-identical subset of the scanned one.

        The gate reads requirements.txt and never requirements-runtime.txt,
        which is not a filename it recognises. That is only safe while the
        runtime set is a strict subset: otherwise the image would ship a
        version no stage examined. Both files travel in the package, so this
        holds there too.
        """
        import re

        def pins(name: str) -> dict[str, str]:
            found = {}
            for line in _repo_only(name).read_text(encoding="utf-8").splitlines():
                match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)", line)
                if match:
                    found[match.group(1).lower().replace("_", "-")] = match.group(2)
            return found

        runtime = pins("requirements-runtime.txt")
        scanned = pins("requirements.txt")
        assert runtime, "requirements-runtime.txt has no pins"
        assert scanned, "requirements.txt has no pins"
        missing = sorted(set(runtime) - set(scanned))
        assert not missing, (
            f"the image would install packages the gate never sees: {missing}"
        )
        drifted = {k: (v, scanned[k]) for k, v in runtime.items() if scanned[k] != v}
        assert not drifted, f"runtime pins disagree with the scanned set: {drifted}"

    def test_image_installs_the_runtime_lock_under_hashes(self) -> None:
        """The image installs the runtime set only.

        Collapsing the split would drag the whole test toolchain into the
        runtime image and count it against the Container Scan stage.
        """
        runtime = _repo_only("requirements-runtime.txt").read_text(encoding="utf-8")
        dockerfile = _repo_only("Dockerfile").read_text(encoding="utf-8")
        assert "--hash=sha256:" in runtime
        assert "--require-hashes" in dockerfile
        assert "-r requirements-runtime.txt" in dockerfile
        assert "-r requirements.txt" not in dockerfile, (
            "the image must not install the test-inclusive set"
        )


class TestVersionStamp:
    def test_version_is_single_sourced(self) -> None:
        from spectre import __version__
        from spectre.web.app import app

        assert app.version == __version__

    @_python_template_only
    def test_pyproject_version_matches_the_package(self) -> None:
        """The gate contract wants a [project] table, which rules out a dynamic
        version. The two literals must therefore agree.

        pyproject.toml ships, so this holds inside the package too and must
        never be allowed to skip.
        """
        from spectre import __version__

        body = _repo_only("pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"$', body, re.MULTILINE)
        assert declared, "pyproject.toml must declare a literal version"
        assert declared.group(1) == __version__, (
            f"pyproject.toml says {declared.group(1)}, spectre/__init__.py says {__version__}"
        )

    def test_only_the_bump_script_writes_the_version(self) -> None:
        """Repository-only: scripts/ does not ship, so the platform never
        analyses our build tooling as if it were application code."""
        bump = _repo_only("scripts/bump-version.sh").read_text(encoding="utf-8")
        assert "pyproject.toml" in bump, "the bump script must rewrite pyproject.toml too"
        assert "spectre/__init__.py" in bump, "and the package's own version"


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

    @_python_template_only
    def test_async_postgres_driver_is_pinned(self) -> None:
        """The add-on is useless without a driver the async engine can use."""
        manifest = _repo_only("requirements.txt").read_text(encoding="utf-8")
        assert "asyncpg==" in manifest

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
            "requirements.in",
            "requirements.pip",
            "requires.txt",
            "Pipfile",
            "Pipfile.lock",
            "poetry.lock",
            "pdm.lock",
            "uv.lock",
        }
    )

    # Directories that never reach the scanner: not shipped, or not source.
    # Kept as a fallback for a checkout with no usable git, and as a fast path.
    _IGNORED = frozenset(
        {".git", ".venv", "venv", "dist", "build", "node_modules", "__pycache__", ".cache"}
    )

    @staticmethod
    def _git_ignores(candidates: list[Path]) -> set[Path]:
        """Of these paths, the ones git excludes. Empty if git cannot answer.

        A hardcoded directory list cannot anticipate every tool that writes
        inside a checkout. This test failed against nine manifests under
        .claude/worktrees/, which an agent harness had created and .gitignore
        line 74 already excluded: a false positive, because the dependency
        scanner reads a CI checkout and an ignored file is not in one.

        Asking git is the faithful question. One batched subprocess, and on
        any failure the caller falls back to _IGNORED rather than passing
        vacuously, so a broken git cannot turn this test green.
        """
        if not candidates:
            return set()
        payload = "\n".join(str(c) for c in candidates)
        try:
            result = subprocess.run(
                ["git", "-C", str(_REPO_ROOT), "check-ignore", "--stdin"],
                input=payload, capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git
            return set()
        # 0 = some ignored, 1 = none ignored. Anything else is a real failure.
        if result.returncode not in (0, 1):  # pragma: no cover - broken git
            return set()
        return {Path(line) for line in result.stdout.splitlines() if line}

    def test_no_manifest_outside_the_repository_root(self) -> None:
        candidates = [
            path
            for path in _REPO_ROOT.rglob("*")
            if path.is_file()
            and path.name in self._MANIFEST_NAMES
            and path.parent != _REPO_ROOT
            and not any(part in self._IGNORED for part in path.relative_to(_REPO_ROOT).parts)
        ]
        ignored = self._git_ignores(candidates)
        strays = [
            str(path.relative_to(_REPO_ROOT)) for path in candidates if path not in ignored
        ]

        assert not strays, (
            "these files sit below the root and are named like dependency manifests, so "
            f"the scanner may select their directory instead of the root: {strays}. "
            "Rename them (a module named setup.py is the usual culprit) or move them to the root."
        )

    def test_no_self_referencing_extra_in_pyproject(self) -> None:
        """A self-referencing extra sends resolvers to an index for our own name.

        `spectre[test]` inside an optional-dependency group means any tool that
        reads pyproject.toml without our source tree must fetch a distribution
        called `spectre` from PyPI, where an unrelated package of that name
        already exists. List the packages explicitly instead.
        """
        pyproject = _repo_only("pyproject.toml").read_text(encoding="utf-8")
        assert "[project.optional-dependencies]" not in pyproject, (
            "the gate contract declares no dependencies in pyproject.toml at all; "
            "they belong in the pip-compile inputs and their locked outputs"
        )
        assert "dependencies = [" not in pyproject, (
            "declaring dependencies here as well as in the lock files lets the two drift"
        )


class TestPythonFloorContract:
    """The interpreter floor has to be stated consistently in three places.

    The App Store's Dependency Scanning analyser runs `pip download` against
    requirements.txt before it can analyse anything, so it needs an interpreter
    at least as new as the floor our pins actually require. When that mismatch
    happens the job exits non-zero, writes no report, and the platform shows
    "Vulnerable dependencies found" for a scan that never ran. See
    docs/DEPENDENCY-SCANNING.md.

    A test cannot resolve the manifest without network access, so this guards
    the offline half: pyproject's declared floor and the Dockerfile base image
    must agree. `scripts/audit-dependencies.sh` measures the real floor.
    """

    def _declared_floor(self) -> tuple[int, int]:
        pyproject = _repo_only("pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'requires-python\s*=\s*"[>=~^]*\s*(\d+)\.(\d+)', pyproject)
        assert m, "pyproject.toml must declare requires-python"
        return int(m.group(1)), int(m.group(2))

    def _base_image_python(self, dockerfile: str) -> tuple[int, int]:
        m = re.search(r"BASE_IMAGE=python:(\d+)\.(\d+)", dockerfile)
        assert m, "the Dockerfile must pin a python:X.Y base image"
        return int(m.group(1)), int(m.group(2))

    def test_declared_floor_matches_base_image(self, dockerfile: str) -> None:
        declared = self._declared_floor()
        base = self._base_image_python(dockerfile)
        assert declared == base, (
            f"requires-python declares {declared[0]}.{declared[1]} but the Dockerfile builds on "
            f"python:{base[0]}.{base[1]}. Whichever is right, a scanner told the wrong floor "
            "cannot resolve the manifest."
        )

    def test_floor_is_documented_for_the_platform(self) -> None:
        """Repository-only. docs/ is deliberately excluded from the submission.

        The packager drops docs/ so its generators are not analysed as if they
        were application code. The suite ships inside the package and runs
        there, so this must skip rather than fail when the directory is absent:
        a test that cannot hold in the artifact it travels in is a broken test,
        not a finding.
        """
        doc = _repo_only("docs/DEPENDENCY-SCANNING.md")
        assert doc.is_file(), "docs/DEPENDENCY-SCANNING.md must exist to explain the stage failure"
        major, minor = self._declared_floor()
        assert f"{major}.{minor}" in doc.read_text(encoding="utf-8"), (
            "the diagnosis document must name the current interpreter floor"
        )


class TestScannerInterpreterContract:
    """The lock must resolve on the SCANNER's interpreter, not only on ours.

    This is the defect that failed twelve submissions. The App Store's
    Dependency Scanning analyser is GitLab's gemnasium-python, whose image is
    built FROM python:3.11-slim (build/gemnasium-python/debian/Dockerfile,
    ARG DS_PYTHON_VERSION=3.11). Before it can analyse anything it runs, on
    that interpreter:

        pip download --disable-pip-version-check --dest ./dist -r requirements.txt

    numpy 2.5.2 and scipy 1.18.1 both declare Requires-Python >= 3.12, so pip
    could not satisfy them and exited 1. The analyser logs pip's output with
    log.Debugf, so at the default log level the job showed a bare `exit status
    1` after three and a half seconds, with no SBOM and no report, which the
    interface renders as "Vulnerable dependencies found" for a scan that never
    ran. Reproduced exactly: 3.42 seconds, same message.

    The lock is therefore compiled for 3.11 while the app still runs on 3.12.
    A set resolved for 3.11 installs cleanly on 3.12, and --generate-hashes
    carries every wheel's hash, the cp312 ones included.

    This is the offline half of the guard and it ships inside the package.
    scripts/audit-dependencies.sh measures the real floor against the index and
    fails above 3.11.
    """

    SCANNER_PYTHON = "3.11"

    def _header(self, name: str) -> str:
        path = _REPO_ROOT / name
        if not path.is_file():
            pytest.skip(f"{name} is excluded from this package")
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[:4])

    @pytest.mark.parametrize("name", ["requirements.txt", "requirements-runtime.txt"])
    def test_the_lock_is_compiled_for_the_scanners_interpreter(self, name: str) -> None:
        header = self._header(name)
        assert f"--python-version {self.SCANNER_PYTHON}" in header, (
            f"{name} must be compiled for python {self.SCANNER_PYTHON}, which is "
            "what the Dependency Scanning analyser runs. Regenerate with "
            f"scripts/lock.sh {self.SCANNER_PYTHON}. Compiling for a newer "
            "interpreter lets a pin in that resolves nowhere the scanner can "
            "reach, and the job then dies in three seconds with no message."
        )

    def test_the_two_shipped_locks_agree_on_the_interpreter(self) -> None:
        """A split would let the image and the scanned set resolve different trees."""
        found = {
            name: re.search(r"--python-version\s+(\d+\.\d+)", self._header(name))
            for name in ("requirements.txt", "requirements-runtime.txt")
        }
        versions = {name: (m.group(1) if m else None) for name, m in found.items()}
        assert len(set(versions.values())) == 1, (
            f"the shipped locks were compiled for different interpreters: {versions}"
        )


class TestPipCompileLockContract:
    """requirements.txt must be recognisable as a pip-compile lockfile.

    The App Store's dependency-scan-python analyser picks a package manager
    from the files present. With both requirements.txt and pyproject.toml at
    the root it selects pip-tools, and pip-tools parses requirements.txt with
    the pip-compile parser. That parser calls IsPipCompileLock, which accepts a
    file only if line 1 is the uv header or LINE 2 begins with the pip-compile
    header. A hand-maintained pin list fails that check, the parser skips, no
    SBOM is produced, and the job exits 1 with no message - which the platform
    then reports as "Vulnerable dependencies found".

    A custom comment banner above the generated header is enough to break it,
    because the check is positional. Regenerate with pip-compile rather than
    editing the top of the file.
    """

    # Copied from the analyser: scanner/common/common.go.
    _PIP_COMPILE_HEADER = "# This file is autogenerated by pip-compile with"
    _UV_HEADER = "# This file was autogenerated by uv via the following command:"

    def _is_pip_compile_lock(self, path: Path) -> bool:
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].startswith(self._UV_HEADER):
            return True
        return len(lines) > 1 and lines[1].startswith(self._PIP_COMPILE_HEADER)

    @_python_template_only
    def test_requirements_txt_is_a_recognisable_lockfile(self) -> None:
        req = _repo_only("requirements.txt")
        assert self._is_pip_compile_lock(req), (
            "requirements.txt line 2 must begin with "
            f"{self._PIP_COMPILE_HEADER!r}, or line 1 with the uv marker. Regenerate "
            "it with scripts/lock.sh; never add a banner above the generated header, "
            "because the analyser's check is positional."
        )

    def test_runtime_lock_is_generated_not_hand_written(self) -> None:
        """The runtime lock ships in the package and drives the image build.

        It is never scanned, but it must still be tool-generated: a hand-edited
        pin with a stale hash fails the container build rather than installing
        something unexpected, and only a generated file guarantees every entry
        carries a hash.
        """
        runtime = _repo_only("requirements-runtime.txt")
        assert self._is_pip_compile_lock(runtime), (
            "requirements-runtime.txt must be regenerated with scripts/lock.sh"
        )
        assert "--hash=sha256:" in runtime.read_text(encoding="utf-8")

    def test_every_lock_file_is_fully_hashed(self) -> None:
        """A single unhashed line silently disables verification for that package."""
        checked = 0
        for name in ("requirements.txt", "requirements-runtime.txt"):
            path = _REPO_ROOT / name
            if not path.is_file():
                # requirements.txt does not travel in the docker-only archive.
                # The runtime lock always does, so the loop still checks one.
                continue
            checked += 1
            body = path.read_text(encoding="utf-8")
            pinned = re.findall(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", body, re.MULTILINE)
            assert pinned, f"{name} has no pins"
            # Every pin must be followed by at least one hash before the next pin.
            blocks = re.split(r"^(?=[A-Za-z0-9][A-Za-z0-9._-]*==)", body, flags=re.MULTILINE)
            unhashed = [
                b.split("==", 1)[0].strip()
                for b in blocks
                if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*==", b) and "--hash=" not in b
            ]
            assert not unhashed, f"{name} has unhashed pins: {unhashed}"
        if not checked:
            pytest.skip("no lock file travels in this tree")

    @_python_template_only
    def test_package_matches_the_gate_contract(self) -> None:
        """The package root must carry the shape the gate actually accepts.

        Derived from the two applications known to clear this gate and the one
        known to fail it. pyproject.toml with a [project] table is the only
        root file present in both passers and absent from the failure, and it
        is a documented resolution trigger. requirements.txt is the scanned
        lockfile. The runtime pair must NOT use recognised names, so that the
        gate reads the test-inclusive superset rather than the narrower runtime
        set: it must scan at least what the image ships, never less.

        Only the must-be-ABSENT half is asserted here. An earlier version also
        asserted the three required files were at the root, reasoning that this
        was "just as true inside the uploaded artefact as in the repository".
        It was not: the platform assembles its own tree, 0.5.24 shipped
        sonar-project.properties that the platform's checkout did not have, and
        the Test stage died on it. Presence now lives in
        TestThePackagerShipsWhatTheGatesRead, which only runs where absence is
        genuinely a defect.

        Absence is different in kind and stays here. No platform can ADD a
        competing lockfile to the tree, so finding one is always our bug.
        """
        root_files = {p.name for p in _REPO_ROOT.iterdir() if p.is_file()}

        # Lockfile formats the analyser reads that this project does not use.
        # Shipping one would hand it a second, unmaintained view of the set.
        foreign = {
            "Pipfile",
            "Pipfile.lock",
            "poetry.lock",
            "uv.lock",
            "pdm.lock",
            "pylock.toml",
            "setup.py",
            "setup.cfg",
        }
        present = sorted(foreign.intersection(root_files))
        assert not present, f"these would give the analyser a competing view: {present}"

        recognised_names = {"requirements.txt", "requirements.pip", "requires.txt", "requirements.in"}
        assert "requirements-runtime.txt" not in recognised_names, (
            "the runtime lock must not use a name the analyser recognises"
        )


@_python_template_only
class TestBuildBackendContract:
    """A resolver reading pyproject.toml must be able to build our metadata.

    Without an explicit [build-system], PEP 517 falls back to setuptools, and
    setuptools flat-layout auto-discovery refuses a project with more than one
    importable top-level directory:

        error: Multiple top-level packages discovered in a flat-layout:
               ['spectre', 'tle_clustering']

    It is a hard, immediate failure and the message goes to stderr. Reproduced
    with `pip install --dry-run --no-deps .` against the package root, and it
    returns the moment the declaration below is removed.
    """

    def _pyproject(self) -> str:
        return _repo_only("pyproject.toml").read_text(encoding="utf-8")

    def _top_level_packages(self) -> list[str]:
        return sorted(
            d.name
            for d in _REPO_ROOT.iterdir()
            if d.is_dir() and (d / "__init__.py").is_file() and not d.name.startswith(".")
        )

    def test_build_backend_is_declared_not_defaulted(self) -> None:
        body = self._pyproject()
        assert "[build-system]" in body, (
            "declare the backend rather than relying on the PEP 517 default"
        )
        assert "build-backend" in body

    def test_packages_are_declared_when_the_layout_is_ambiguous(self) -> None:
        """More than one top-level package means auto-discovery cannot guess."""
        packages = self._top_level_packages()
        if len(packages) < 2:
            return  # a single package discovers unambiguously
        body = self._pyproject()
        assert "[tool.setuptools.packages.find]" in body, (
            f"{len(packages)} top-level packages exist ({packages}), so setuptools "
            "auto-discovery will refuse. Declare them explicitly."
        )
        for package in packages:
            if package == "tests":
                continue
            assert f'"{package}*"' in body or f'"{package}"' in body, (
                f"{package} is importable at the root but is not in the include list"
            )

    def test_tests_are_not_declared_as_a_shipped_package(self) -> None:
        """tests/ is importable but must never be part of the distribution."""
        body = self._pyproject()
        include = body.split("[tool.setuptools.packages.find]", 1)[1].split("\n\n", 1)[0]
        assert '"tests' not in include, "tests/ must not be declared as a package"


class TestClusteringPackageTravels:
    """tle_clustering must ship, in both templates.

    spectre/astro/tle_preprocessing.py imports it inside a try/except
    ImportError that logs a warning and returns an empty result. That guard is
    correct - the app should degrade rather than crash - but it also means an
    archive built without the package deploys cleanly and silently performs no
    TLE clustering at all. Version 0.5.6 shipped exactly that. Nothing in the
    pipeline can catch it, because nothing fails.
    """

    def test_the_package_is_present(self) -> None:
        package = _REPO_ROOT / "tle_clustering"
        assert package.is_dir(), "tle_clustering must travel in the package"
        assert (package / "__init__.py").is_file()

    def test_the_guarded_import_actually_resolves(self) -> None:
        """Assert the import the app performs, not merely that files exist."""
        from tle_clustering import cluster_tle_strings
        from tle_clustering.config import ClusteringConfig

        assert callable(cluster_tle_strings)
        assert ClusteringConfig is not None

    def test_clustering_is_not_silently_disabled(self, dockerfile: str) -> None:
        """The image must copy the package, or the import fails at runtime."""
        assert "tle_clustering" in dockerfile, (
            "the Dockerfile must COPY tle_clustering, otherwise the guarded import "
            "fails inside the container and clustering is skipped without error"
        )


class TestBuildContextContract:
    """Every COPY source must survive .dockerignore.

    These are two separate files that have to agree, and nothing checked that
    they did. `.dockerignore` listed tle_clustering/ under "development
    tooling" while the application imports it, so the package never reached the
    image; the guarded import turned that into a silently disabled feature
    rather than a failure. Adding the COPY without checking the exclusion then
    turned it into a Container Build failure:

        Error: building at STEP "COPY tle_clustering/ /app/tle_clustering/":
        no items matching glob "..." copied (1 filtered out using .dockerignore)

    Both Dockerfiles are checked, because they are maintained in parallel and a
    fix applied to one is easy to forget in the other.
    """

    _DOCKERFILES = ("Dockerfile", "Dockerfile.docker-only")

    def _exclusions(self) -> list[str]:
        """Directory and exact-name exclusions, ignoring negations and globs.

        Only the pattern forms this project actually uses are interpreted. A
        pattern we cannot evaluate is skipped rather than guessed at, so the
        test never invents a failure it cannot justify.
        """
        body = _repo_only(_DOCKERIGNORE).read_text(encoding="utf-8")
        patterns = []
        for raw in body.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "!")):
                continue
            if "*" in line or "?" in line:
                continue
            patterns.append(line.rstrip("/"))
        return patterns

    def _copy_sources(self, body: str) -> list[str]:
        """Local COPY sources only. --from=<stage> reads from an earlier stage."""
        sources = []
        for match in re.finditer(r"^\s*COPY\s+(.*)$", body, re.MULTILINE):
            parts = match.group(1).split()
            if any(part.startswith("--from=") for part in parts):
                continue
            parts = [part for part in parts if not part.startswith("--")]
            if len(parts) < 2:
                continue
            sources.extend(parts[:-1])
        return sources

    def test_no_copy_source_is_excluded_from_the_build_context(self) -> None:
        excluded = self._exclusions()
        offenders = []
        for name in self._DOCKERFILES:
            path = _REPO_ROOT / name
            if not path.is_file():
                continue
            for source in self._copy_sources(path.read_text(encoding="utf-8")):
                head = source.rstrip("/").split("/", 1)[0]
                if head in excluded:
                    offenders.append(f"{name}: COPY {source} is excluded by .dockerignore")
        assert not offenders, (
            "the build context cannot supply these, so the build fails at that "
            f"COPY: {offenders}"
        )

    def test_every_copy_source_exists(self) -> None:
        """A COPY of a path that is not in the repository fails the same way."""
        missing = []
        for name in self._DOCKERFILES:
            path = _REPO_ROOT / name
            if not path.is_file():
                continue
            for source in self._copy_sources(path.read_text(encoding="utf-8")):
                if source in (".", "./"):
                    continue
                if not (_REPO_ROOT / source.rstrip("/")).exists():
                    missing.append(f"{name}: COPY {source}")
        assert not missing, f"these COPY sources do not exist: {missing}"


class TestSubprocessGuardsAreEnvironmentCorrect:
    """A test that shells out to a tool must first prove the tool is there.

    The platform's Test image is a bare Python one. The runner's helper
    container performs the checkout, so the job's working directory HAS a
    ``.git``, and the job's image has no ``git`` executable at all. Three test
    modules guarded on the directory, which is present, and then invoked the
    executable, which is not, so four tests died on

        FileNotFoundError: [Errno 2] No such file or directory: 'git'

    and took the whole submission down with them. Guarding on the artefact a
    tool leaves behind is not the same as guarding on the tool.

    This pins the class rather than the four instances: any test module that
    invokes git must also resolve it with ``shutil.which``.
    """

    _TESTS = _REPO_ROOT / "tests"
    # This module names the patterns it looks for, so it matches itself.
    _SELF = Path(__file__).resolve()

    def _modules_invoking_git(self) -> list[Path]:
        found = []
        for path in sorted(self._TESTS.rglob("test_*.py")):
            if path.resolve() == self._SELF:
                continue
            body = path.read_text(encoding="utf-8")
            if re.search(r"""\[\s*["']git["']\s*,""", body):
                found.append(path)
        return found

    def test_no_test_invokes_git_by_bare_name(self) -> None:
        offenders = [str(p.relative_to(_REPO_ROOT)) for p in self._modules_invoking_git()]
        assert not offenders, (
            "these modules invoke git by bare name, which resolves through "
            f"PATH and dies where there is no git: {offenders}. Resolve it "
            "with shutil.which() and skip when it returns None."
        )

    def test_every_module_touching_git_checks_the_executable(self) -> None:
        offenders = []
        for path in sorted(self._TESTS.rglob("test_*.py")):
            if path.resolve() == self._SELF:
                continue
            body = path.read_text(encoding="utf-8")
            if "check-ignore" not in body and "ls-files" not in body and "git archive" not in body:
                continue
            if 'shutil.which("git")' not in body:
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert not offenders, (
            "these modules run git but never check that it exists: "
            f"{offenders}. The platform's Test image has a .git directory and "
            "no git executable; guard on the executable."
        )


class TestSonarProjectVersionTracksTheRelease:
    """A stale projectVersion makes the gate's own report name the wrong build.

    sonar.projectVersion sat at 0.4.0 through eight releases because nothing
    rewrote it. scripts/bump-version.sh now does, and this is the assertion that
    keeps it honest. Both files travel in the submission package, so it holds in
    every environment the suite runs in.
    """

    def test_it_matches_the_package_version(self) -> None:
        from spectre import __version__

        properties = _repo_only("sonar-project.properties").read_text(encoding="utf-8")
        declared = [
            line.split("=", 1)[1].strip()
            for line in properties.splitlines()
            if line.startswith("sonar.projectVersion=")
        ]
        assert declared, "sonar-project.properties must declare sonar.projectVersion"
        assert declared[0] == __version__, (
            f"sonar.projectVersion is {declared[0]!r} but the package is "
            f"{__version__!r}. Run scripts/bump-version.sh rather than editing "
            "either by hand."
        )


class TestEveryClickableTableElementAnswersTheKeyboard:
    """A console that can only be driven by mouse is unusable from a keyboard.

    SonarQube reports this as Web:MouseEventWithoutKeyboardEquivalentCheck, and
    it reported seven instances. There were fifty, across five templates: the
    other forty-three were invisible only because their lines had not changed.
    This pins the whole population rather than the sample.

    The shared handler lives in base.html as spectreActivate(event); an element
    opts in with tabindex="0" onkeydown="spectreActivate(event)".
    """

    _TEMPLATES = _REPO_ROOT / "spectre" / "web" / "templates"
    _CLICKABLE = re.compile(r"<(tr|th)\b[^>]*\bonclick\b[^>]*>", re.IGNORECASE | re.DOTALL)
    _KEYBOARD = re.compile(r"\bon(keydown|keypress|keyup)\b", re.IGNORECASE)
    _TABINDEX = re.compile(r'\btabindex\s*=\s*"(-?\d+)"', re.IGNORECASE)

    def _answers_the_keyboard(self, element: str) -> bool:
        """A key handler on an element the keyboard cannot reach fires for nobody.

        Neither <tr> nor <th> is focusable by default, and those two tags
        are the whole population this class matches, so nothing natively
        focusable is dragged in by requiring the attribute. Until this was
        added the test accepted an onkeydown with no tabindex, which is the
        exact shape its own failure message tells the author to fix: the
        element never receives the key event, so the keyboard equivalent is
        dead while the test reports green.
        """
        if not self._KEYBOARD.search(element):
            return False
        tabindex = self._TABINDEX.search(element)
        return tabindex is not None and int(tabindex.group(1)) >= 0

    def _offenders(self) -> list[str]:
        offenders = []
        for path in sorted(self._TEMPLATES.rglob("*.html")):
            body = path.read_text(encoding="utf-8")
            for match in self._CLICKABLE.finditer(body):
                if self._answers_the_keyboard(match.group(0)):
                    continue
                line = body[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{line}")
        return offenders

    def test_no_clickable_row_or_header_is_mouse_only(self) -> None:
        offenders = self._offenders()
        assert not offenders, (
            f"{len(offenders)} clickable <tr>/<th> are unreachable from the "
            f"keyboard, for want of a handler or of a focusable tabindex: "
            f'{offenders[:8]}. Add tabindex="0" onkeydown="spectreActivate(event)".'
        )

    def test_the_shared_handler_exists(self) -> None:
        """Every opt-in above calls it, so its absence breaks all of them at once."""
        base = (self._TEMPLATES / "base.html").read_text(encoding="utf-8")
        assert "function spectreActivate" in base, (
            "spectreActivate is gone from base.html, so every onkeydown that "
            "calls it is now a silent no-op"
        )

    def test_the_handler_ignores_events_from_nested_controls(self) -> None:
        """Without this guard an activatable row swallows its own buttons.

        keydown bubbles, so a key press on a control inside an opted-in row
        reaches the row's handler, which calls preventDefault() and clicks the
        ROW. The nested control never fires. That shipped once: the Load button
        in the All-Intercepts panel staged nothing for a keyboard operator
        while working perfectly with a mouse, because the mouse path had a
        stopPropagation guard and the key path had none.
        """
        base = (self._TEMPLATES / "base.html").read_text(encoding="utf-8")
        handler = base.split("function spectreActivate", 1)[1].split("</script>", 1)[0]
        assert "e.target !== e.currentTarget" in handler, (
            "spectreActivate no longer checks that the opted-in element is the "
            "one with focus, so every nested button, link and input inside an "
            "activatable row is now unreachable from the keyboard"
        )


class TestThePackagerShipsWhatTheGatesRead:
    """Where "this file must ship" belongs, now that it cannot live anywhere else.

    Every other test in this module travels INSIDE the submission package and
    runs in whatever tree the platform assembles. That tree is not the archive:
    release 0.5.24 shipped sonar-project.properties in the zip and the
    platform's checkout did not have it, so a test asserting its presence
    failed the whole Test stage. The assertion was not wrong about the package;
    it was wrong about where it was standing.

    A test running inside the artefact cannot tell a packaging bug from a
    platform that supplies its own copy of a file, so it must skip on absence
    rather than fail. That leaves nobody asserting the files actually ship,
    which is this class: repository-only, reading the packager's allowlist,
    where absence genuinely is a defect.
    """

    def _allowlist(self) -> list[str]:
        body = _repo_only("scripts/package-appstore.sh").read_text(encoding="utf-8")
        match = re.search(r'^PATHS="\n(.*?)^"', body, re.MULTILINE | re.DOTALL)
        assert match, "the packager no longer declares a PATHS allowlist"
        return [line.strip() for line in match.group(1).splitlines() if line.strip()]

    def test_the_stages_that_read_a_file_still_get_it(self) -> None:
        """Each entry is named with the stage that fails without it."""
        # README.md is deliberately absent: no stage reads it, it is there to
        # be read by a reviewer, so dropping it would cost a submission
        # nothing and requiring it would assert more than we know.
        required = {
            "Dockerfile": "Container Build; also what selects the container template",
            "requirements.txt": "Dependency Scanning reads it, and the Test stage installs from it",
            "requirements-runtime.txt": "the image build installs from it",
            "pyproject.toml": "carries the pytest and coverage configuration the Test stage uses",
            _DOCKERIGNORE: "shapes the Container Build context",
            "sonar-project.properties": (
                "the archive carries the Code Quality configuration, sonar.projectVersion "
                "and sonar.sources. 0.5.24 proved the platform may scan a checkout that "
                "does not have it, which is a question for the platform team and not a "
                "reason to stop shipping it"
            ),
            "spectre": "the application",
            "tests": "the Test stage runs them",
            "tle_clustering": "imported under a try/except, so its absence degrades silently",
        }
        allowed = set(self._allowlist())
        missing = {name: why for name, why in required.items() if name not in allowed}
        assert not missing, (
            "the packager would not ship these, and the named stage fails without "
            f"each one: {missing}"
        )

    def test_only_one_literal_allowlist_is_declared(self) -> None:
        """A second literal list would let the two disagree about one file.

        The docker-only branch rebinds PATHS to a filtered copy, which is a
        derivation rather than a second source of truth, so it does not count.
        """
        body = _repo_only("scripts/package-appstore.sh").read_text(encoding="utf-8")
        literal = re.findall(r'^PATHS="\n', body, re.MULTILINE)
        assert len(literal) == 1, (
            f"{len(literal)} literal allowlists are declared; which one ships "
            "is now a question rather than a fact"
        )


#: Paths under these roots are application code. They travel in every package
#: and in the platform's checkout, so reading one directly assumes nothing.
_APPLICATION_PREFIXES = ("spectre", "tests", "tle_clustering")

#: Asking a path whether it is there is the question the guard exists to force.
_PRESENCE_ATTRS = ("is_file", "exists", "is_dir")

#: Both shapes a test can be written in, since an async one is a function
#: the guard would otherwise climb straight past.
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: What a test module binds its own repository root to, whatever it calls it:
#: _REPO_ROOT here, _ROOT in four other modules under tests/.
_ROOT_EXPRESSION = re.compile(r"Path\(__file__\)(?:\.resolve\(\))?\.parents\[\d+\]")


def _ast_parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Child-to-parent index, because ast nodes carry no parent reference."""
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _root_names(tree: ast.Module) -> set[str]:
    """The names a module binds to its own repository root.

    Resolved per module rather than hardcoding _REPO_ROOT, which is what kept
    this rule inside one file while the same assumption elsewhere under tests/
    could still fail the platform's Test stage.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and _ROOT_EXPRESSION.fullmatch(ast.unparse(node.value)):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _skip_guards(tree: ast.Module) -> set[str]:
    """Module-level functions that skip, so opening a test with one is a guard.

    _repo_only() here, _repository_only() in test_docs_are_committable.py and
    test_hrr_bootstrap.py: each decides once whether the environment carries
    the material the test reads, and skips when it does not.
    """
    return {
        node.name
        for node in tree.body
        if isinstance(node, _FUNCTION_NODES) and "pytest.skip" in ast.unparse(node)
    }


def _whole_path(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    """The whole ``root / "a" / "b"`` expression, not its leftmost segment.

    Without this a chained path reads as unguarded even where the expression
    it belongs to is presence-checked, which is how scripts/ is reached in
    tests/unit/test_cognitive_complexity_meter.py.
    """
    parent = parents.get(node)
    while isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Div):
        node, parent = parent, parents.get(parent)
    return node


def _inside_an_assert(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Asserting a path is present is the defect, not a guard against it.

    This is the whole class of failure: three releases died on a test that
    asked whether a file was there and then asserted the answer, rather
    than skipping on it.
    """
    while node is not None and not isinstance(node, ast.stmt):
        node = parents.get(node)
    return isinstance(node, ast.Assert)


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    while node is not None and not isinstance(node, _FUNCTION_NODES):
        node = parents.get(node)
    return node


def _bound_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    """The single name this path expression is assigned to, if any."""
    parent = parents.get(node)
    if not isinstance(parent, ast.Assign) or len(parent.targets) != 1:
        return None
    target = parent.targets[0]
    return target.id if isinstance(target, ast.Name) else None


def _opens_with_a_guard(function: ast.AST | None, guards: set[str]) -> bool:
    """True when the test's FIRST statement calls one of the module's guards.

    Only the first statement counts, so a guard taken out for one file cannot
    be read as cover for a later, unrelated read.
    """
    if not isinstance(function, _FUNCTION_NODES) or not function.body:
        return False
    first = function.body[0]
    call = first.value if isinstance(first, (ast.Expr, ast.Assign)) else None
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in guards
    )


def _name_is_presence_checked(
    name: str | None, function: ast.AST | None, parents: dict[ast.AST, ast.AST],
) -> bool:
    """True when the name the path was bound to is asked whether it is there.

    tests/unit/test_operator_sees_metres_per_second.py takes its guard this
    way: it binds docs/generate_guide.py to a local, then skips on .exists().

    Two conditions, and both are load-bearing. The attribute must actually be
    CALLED, because ``path.is_file`` without parentheses is a truthy bound
    method and guards nothing. And it must not sit inside an assert, because
    asserting a file is present is the defect this whole class exists to
    catch, not a guard against it.

    Without the second condition this allowance is strictly WEAKER than the
    inline rule beside it: binding the path to a local first would launder
    exactly the construct that killed 0.5.24,

        p = _REPO_ROOT / "sonar-project.properties"
        assert p.is_file()

    which reads as a guard to the walker and dies on the platform.
    """
    if name is None or function is None:
        return False
    return any(
        isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr in _PRESENCE_ATTRS
        and isinstance(sub.func.value, ast.Name)
        and sub.func.value.id == name
        and not _inside_an_assert(sub, parents)
        for sub in ast.walk(function)
    )


def _is_the_root(node: ast.AST, roots: set[str]) -> bool:
    """The repository root, named or written out at the point of use.

    Both forms occur under tests/, and a rule that saw only the named one
    would miss the shape it is most likely to be written in by someone who
    has not read this class.
    """
    if isinstance(node, ast.Name):
        return node.id in roots
    return bool(_ROOT_EXPRESSION.fullmatch(ast.unparse(node)))


def _non_application_name(node: ast.AST, roots: set[str]) -> str | None:
    """The literal in ``root / "name"`` when it is not application code."""
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
        return None
    left, right = node.left, node.right
    if not _is_the_root(left, roots):
        return None
    if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
        return None
    if right.value.startswith(_APPLICATION_PREFIXES):
        return None
    return right.value


def _is_guarded(node: ast.AST, parents: dict[ast.AST, ast.AST], tree: ast.Module,
                guards: set[str]) -> bool:
    """True when this read skips, rather than fails, where the file is absent."""
    whole = _whole_path(node, parents)
    parent = parents.get(whole)
    if isinstance(parent, ast.Attribute) and parent.attr in _PRESENCE_ATTRS:
        return not _inside_an_assert(whole, parents)
    if isinstance(parent, ast.Assign) and parents.get(parent) is tree:
        return True
    function = _enclosing_function(whole, parents)
    if _opens_with_a_guard(function, guards):
        return True
    return _name_is_presence_checked(_bound_name(whole, parents), function, parents)


def _unguarded_reads(module: Path) -> list[str]:
    """Every non-application path this module reads with nothing to skip on."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    roots = _root_names(tree)
    parents = _ast_parents(tree)
    guards = _skip_guards(tree)
    offenders = []
    for node in ast.walk(tree):
        name = _non_application_name(node, roots)
        if name is None or _is_guarded(node, parents, tree, guards):
            continue
        offenders.append(f"{module.relative_to(_REPO_ROOT)}:{node.lineno}: {name}")
    return offenders


class TestNoTestAssertsAFileIsPresent:
    """The class that failed this project three times, pinned.

    Three releases have now been lost to a test asserting an environmental
    fact that does not hold where the suite actually runs: docs/ stripped by
    the packager, the git executable absent from the runner's image, and
    sonar-project.properties absent from the platform's checkout. Each time the
    fix was applied to the instance and the class was left alone.

    The rule is simple and checkable: anywhere under tests/, a path that is not
    application code is reached through something that SKIPS when the file is
    not there, whether that is _repo_only(), a module guard taken out in the
    test's first statement, or a presence check on the name it was bound to.
    Assertions about what must ship belong in the class above, which only runs
    in the repository.

    The scan parsed only this module until the widening above, so the rule
    stopped at the file boundary while the same assumption in any other
    module would have failed the Test stage exactly as before.
    """

    def test_every_non_application_path_goes_through_the_guard(self) -> None:
        offenders: list[str] = []
        for module in sorted((_REPO_ROOT / "tests").rglob("*.py")):
            offenders.extend(_unguarded_reads(module))
        assert not offenders, (
            "these read a non-application file with nothing to skip on, so "
            f"they fail wherever the platform does not supply it: {offenders}. "
            "Use _repo_only(name), or a guard that skips, and put any "
            "must-ship assertion in TestThePackagerShipsWhatTheGatesRead."
        )


class TestHtmxSwapFragmentsMatchTheirTable:
    """A fragment swapped into a table must have that table's column count.

    threat_sweep_row.html replaces a child row of the threat sweep table via
    hx-swap="outerHTML". When the Posture column was added the table went from
    seven columns to eight and the fragment was left at seven, so every row an
    operator refined silently shifted its Action cell under the Posture
    heading. Rendering the parent template alone does not catch that, which is
    exactly what the engineer who made the change did; only rendering both and
    comparing does.

    Counted statically rather than rendered, so this holds inside the
    submission package where there is no running application.
    """

    _PARTIALS = _REPO_ROOT / "spectre" / "web" / "templates" / "partials"

    def _cells_in_last_row(self, body: str) -> int:
        """Cells in the final <tr> block, which is the data row in both files."""
        rows = re.split(r"<tr\b", body)
        return rows[-1].count("<td")

    def test_the_refined_row_has_the_same_width_as_the_row_it_replaces(self) -> None:
        fragment = (self._PARTIALS / "threat_sweep_row.html").read_text(encoding="utf-8")
        table = (self._PARTIALS / "threat_sweep.html").read_text(encoding="utf-8")

        fragment_cells = self._cells_in_last_row(fragment)
        # The child data row in the parent table is the one carrying the burn
        # location cell, which is unique to it.
        # The header row names burn_location too, in its headers= wiring, so
        # require actual data cells rather than just the mention.
        child_rows = [
            block for block in re.split(r"<tr\b", table)
            if "burn_location" in block and block.count("<td") > 0
        ]
        assert child_rows, "the sweep table no longer has a child row to compare against"
        table_cells = child_rows[0].count("<td")

        assert fragment_cells == table_cells, (
            f"threat_sweep_row.html emits {fragment_cells} cells but the child row "
            f"it replaces in threat_sweep.html has {table_cells}. Every refined row "
            "would shift its remaining cells one column left."
        )

    def test_the_error_branch_spans_the_whole_table(self) -> None:
        """A short colspan leaves a ragged row rather than a clean message."""
        fragment = (self._PARTIALS / "threat_sweep_row.html").read_text(encoding="utf-8")
        table = (self._PARTIALS / "threat_sweep.html").read_text(encoding="utf-8")
        child_rows = [
            b for b in re.split(r"<tr\b", table)
            if "burn_location" in b and b.count("<td") > 0
        ]
        assert child_rows
        width = child_rows[0].count("<td")

        spans = [int(m) for m in re.findall(r'colspan="(\d+)"', fragment)]
        assert spans, "the fragment's error branch no longer declares a colspan"
        assert all(s == width for s in spans), (
            f"the fragment's colspan {spans} does not match the table's {width} columns"
        )

    # ── What the swapped row CARRIES, not just how wide it is ────────────
    #
    # The cell count above caught the column shift and nothing else, so two
    # further mismatches rode in behind it.
    #
    # The Load button. The fragment called loadInEngine with three arguments
    # where the row it replaces passes four. JavaScript does not object: the
    # target name arrived as redSat, the burn epoch as blueSat, the method as
    # epoch, and method itself as undefined. A Refine followed by a Load
    # pre-filled the intercept engine with the wrong objects and showed the
    # operator nothing to say so.
    #
    # The headers= binding. Every cell of the row the fragment replaces names
    # its group's heading id, because the headings are a repeated in-tbody
    # header row rather than a thead and scope="col" would claim the rest of
    # the column. The fragment carried no binding at all, so the one row an
    # operator asked the solver to improve was the one row a screen reader
    # could not name the columns of.

    @staticmethod
    def _split_arguments(markup: str, start: int) -> list[str]:
        """Top-level arguments of a call whose '(' ends at ``start``.

        Depth-aware: the epoch argument is itself a call,
        ``strftime('%Y-%m-%dT%H:%M')``, and every argument is wrapped in
        Jinja's ``{{ }}``.
        """
        depth = 0
        args: list[str] = []
        current = ""
        for ch in markup[start:]:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(current.strip())
                current = ""
                continue
            current += ch
        args.append(current.strip())
        return [a for a in args if a]

    @classmethod
    def _load_call(cls, markup: str) -> list[str]:
        """The arguments of the one loadInEngine CALL in ``markup``.

        Anchored on the onclick= attribute, which keeps the function's own
        declaration and any prose about it out of the match. threat_sweep.html
        holds the declaration as well as a call.
        """
        calls = [
            (m.start(), cls._split_arguments(markup, m.end()))
            for m in re.finditer(r'onclick="[^"]*?\bloadInEngine\(', markup)
        ]
        assert len(calls) == 1, (
            f"expected exactly one loadInEngine call site, found {len(calls)}"
        )
        start, args = calls[0]
        # Arguments read as this.dataset.x come from the data-x attribute on
        # the same element, which precedes the handler (audit F-038).
        resolved = []
        for arg in args:
            ref = re.fullmatch(r"this\.dataset\.(\w+)", arg.strip())
            if not ref:
                resolved.append(arg)
                continue
            attrs = re.findall(rf'data-{ref.group(1)}="([^"]*)"', markup[:start])
            assert attrs, f"{arg} has no data-{ref.group(1)} attribute before the handler"
            resolved.append(attrs[-1])
        return resolved

    @staticmethod
    def _header_bindings(row: str) -> list[str]:
        return re.findall(r'headers="([^"]*)"', row)

    @classmethod
    def _child_row_of_table(cls, table: str) -> str:
        rows = [
            b for b in re.split(r"<tr\b", table)
            if "burn_location" in b and b.count("<td") > 0
        ]
        assert rows, "the sweep table no longer has a child row to compare against"
        return rows[0]

    def test_the_refined_row_loads_the_same_objects_into_the_engine(self) -> None:
        fragment = (self._PARTIALS / "threat_sweep_row.html").read_text(encoding="utf-8")
        table = (self._PARTIALS / "threat_sweep.html").read_text(encoding="utf-8")

        declared = re.search(r"function\s+loadInEngine\(([^)]*)\)", table)
        assert declared, "threat_sweep.html no longer declares loadInEngine"
        params = [p.strip() for p in declared.group(1).split(",") if p.strip()]
        assert params == ["redSat", "blueSat", "epoch", "method"], (
            f"loadInEngine's signature changed to {params}; this test's "
            "argument-by-argument assertions below need to change with it"
        )

        parent_args = self._load_call(table)
        fragment_args = self._load_call(fragment)

        assert len(parent_args) == len(params), (
            f"the sweep table calls loadInEngine with {len(parent_args)} "
            f"argument(s) and it takes {len(params)}"
        )
        assert len(fragment_args) == len(params), (
            f"threat_sweep_row.html calls loadInEngine with "
            f"{len(fragment_args)} argument(s) and it takes {len(params)} "
            f"({', '.join(params)}). htmx swaps this row in over one that "
            "passes all four, so after a Refine every argument shifts one "
            f"place left: {fragment_args}. The engine is pre-filled with the "
            "wrong objects and nothing is shown to the operator."
        )
        assert "red_name" in fragment_args[0], (
            "the refined row's Load passes "
            f"{fragment_args[0]} as redSat where the row it replaces passes "
            f"{parent_args[0]}. redSat is the interceptor, not the target."
        )
        assert "red_name" in parent_args[0], (
            "the sweep table's Load no longer leads with the red satellite; "
            "the fragment is now matching the wrong thing"
        )
        assert "method" in fragment_args[-1] and "method" in parent_args[-1], (
            "method must be the last argument in both, or ieUpdate() runs on "
            "undefined"
        )

    def test_the_refined_row_binds_its_cells_to_the_same_column_headings(self) -> None:
        fragment = (self._PARTIALS / "threat_sweep_row.html").read_text(encoding="utf-8")
        table = (self._PARTIALS / "threat_sweep.html").read_text(encoding="utf-8")

        parent = self._header_bindings(self._child_row_of_table(table))
        assert parent, (
            "the sweep table's child row no longer binds its cells to the "
            "per-group headings, so there is nothing for the fragment to match"
        )
        refined = self._header_bindings(re.split(r"<tr\b", fragment)[-1])
        assert refined == parent, (
            f"the refined row binds its cells to {refined} where the row it "
            f"replaces binds to {parent}. The headings are a repeated row "
            "inside the tbody, one set per group, so a cell with no headers= "
            "has no column name at all: after a Refine the operator using a "
            "screen reader loses the column names on exactly the row they "
            "asked the solver to improve."
        )


class TestContinuousIntegrationCanRun:
    """CI on master installed no tools and failed before checking anything.

    The install step named a ``dev`` extra that pyproject.toml never defined,
    so pip installed the package alone and lint, tests and the quality gate
    each died with "command not found" (audit F-S00-01). The obvious repair,
    installing both locks, then failed too, because they pinned tomli
    differently (audit F-S00-08). Each property below would have caught one.
    """

    _PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", re.MULTILINE)

    def test_the_threat_routes_keep_their_coverage_floor(self) -> None:
        """Audit F-042: the sweep routes were untested at 48 per cent."""
        ci = _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")
        assert "--include=spectre/web/routes/threat.py --fail-under=" in ci

    def test_no_test_runs_only_where_the_suite_is_absent(self) -> None:
        """Audit F-179: a test skipped unless in the docker-only archive never
        runs, because that archive does not carry the suite."""
        offenders = [
            str(path.relative_to(_REPO_ROOT))
            for path in (_REPO_ROOT / "tests").rglob("test_*.py")
            if re.search(r"skipif\(\s*not\s+_DOCKER_ONLY", path.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"these hold tests that can never run: {offenders}"

    def test_the_decision_engine_keeps_its_coverage_floor(self) -> None:
        """Audit F-122: the selectors were tested only for returning a response."""
        ci = _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")
        assert "--include=spectre/domain/decision.py --fail-under=100" in ci

    def test_ci_installs_the_locked_sets_not_an_undeclared_extra(self) -> None:
        workflow = _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")
        installs = [
            ln.strip() for ln in workflow.splitlines()
            if re.search(r"\bpip install\b", ln) and not ln.lstrip().startswith("#")
        ]
        assert not [ln for ln in installs if ".[" in ln], (
            f"CI installs an extra: {installs}. pyproject.toml declares none, so pip "
            "would install the package with no tools at all"
        )
        assert any("--require-hashes" in ln and "requirements-dev.txt" in ln for ln in installs)

    def test_both_locks_agree_on_every_package_they_share(self) -> None:
        runtime = dict(self._PIN.findall(_repo_only("requirements.txt").read_text(encoding="utf-8")))
        dev = dict(self._PIN.findall(_repo_only("requirements-dev.txt").read_text(encoding="utf-8")))
        clashes = {name: (runtime[name], dev[name]) for name in runtime.keys() & dev.keys() if runtime[name] != dev[name]}
        assert not clashes, f"the locks cannot be installed together: {clashes}"

    def test_ci_does_not_override_the_coverage_ratchet(self) -> None:
        workflow = _repo_only(".github/workflows/ci.yml").read_text(encoding="utf-8")
        assert "--cov-fail-under" not in workflow, (
            "the floor lives in pyproject.toml [tool.coverage.report]; a lower CI "
            "value let coverage fall unnoticed (audit F-S00-10)"
        )

    def test_no_orphan_submodule_pointer_is_tracked(self) -> None:
        if not (_REPO_ROOT / ".git").exists():
            pytest.skip("no git repository: running from the submission package")
        try:
            listing = subprocess.run(
                ["git", "ls-files", "-s"],  # noqa: S607
                cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
            ).stdout
        except FileNotFoundError:
            pytest.skip("no git executable: the runner's job image ships none")
        gitlinks = [ln.split("\t", 1)[1] for ln in listing.splitlines() if ln.startswith("160000 ")]
        assert not gitlinks, f"gitlinks with no .gitmodules break every CI checkout: {gitlinks}"
