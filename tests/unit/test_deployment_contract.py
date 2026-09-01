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
# skips them, and TestDockerOnlyContract below asserts the inverse there so the
# skip is not a hole.
_python_template_only = pytest.mark.skipif(
    _DOCKER_ONLY,
    reason="docker-only package: no recognised Python manifest ships, by design",
)


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

    @_python_template_only
    def test_shipped_manifest_is_committed_and_hash_pinned(self) -> None:
        """requirements.txt is the one manifest the submission carries."""
        body = (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "--hash=sha256:" in body, "the manifest must pin hashes"
        assert re.search(r"^[a-z0-9_.-]+==", body, re.MULTILINE), "every dependency must be pinned"

    @_python_template_only
    def test_python_template_manifest_is_present(self) -> None:
        """The platform's Dependencies stage installs from requirements.txt.

        Without it the stage fails before anything else runs. Its presence also
        selects the python template, which is deliberate: the quality gate is
        met, and the Dockerfile still drives the container build.
        """
        assert (_REPO_ROOT / "requirements.txt").is_file()
        assert (_REPO_ROOT / "Dockerfile").is_file()

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
            for line in (_REPO_ROOT / name).read_text(encoding="utf-8").splitlines():
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
        runtime = (_REPO_ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")
        dockerfile = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
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

        body = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
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
        manifest = (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
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
    _IGNORED = frozenset(
        {".git", ".venv", "venv", "dist", "build", "node_modules", "__pycache__", ".cache"}
    )

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
        req = _REPO_ROOT / "requirements.txt"
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
        runtime = _REPO_ROOT / "requirements-runtime.txt"
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
        assert checked, "no lock file was present to check"

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

        Asserted against the actual root rather than the packager's allowlist,
        so it is just as true inside the uploaded artefact as in the repository.
        """
        root_files = {p.name for p in _REPO_ROOT.iterdir() if p.is_file()}

        for required in ("pyproject.toml", "requirements.txt", "requirements-runtime.txt"):
            assert required in root_files, f"{required} must be at the root: the contract requires it"

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
        return (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

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


class TestDockerOnlyContract:
    """The inverse contract, asserted only inside the docker-only archive.

    Every assertion the python template makes about manifests skips here, so
    without these the docker-only package would travel with a hole where its
    contract should be. The property that matters is the absence that selects
    the template, plus the presence of everything the image actually needs.
    """

    _RECOGNISED = frozenset(
        {
            "requirements.txt",
            "requirements.in",
            "requirements.pip",
            "requires.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "Pipfile",
            "Pipfile.lock",
            "poetry.lock",
            "uv.lock",
            "pdm.lock",
            "pipdeptree.json",
        }
    )

    @pytest.mark.skipif(not _DOCKER_ONLY, reason="python template: manifests ship by design")
    def test_no_recognised_manifest_at_any_depth(self) -> None:
        """A single one anywhere flips the template and restores the broken stage.

        Checked at every depth, not just the root: the analyser walks the tree
        and selects the first directory carrying a name it recognises.
        """
        strays = sorted(
            str(path.relative_to(_REPO_ROOT))
            for path in _REPO_ROOT.rglob("*")
            if path.is_file() and path.name in self._RECOGNISED
        )
        assert not strays, (
            f"these would select the python template: {strays}. The docker-only "
            "archive must carry none of them."
        )

    @pytest.mark.skipif(not _DOCKER_ONLY, reason="python template: manifests ship by design")
    def test_the_image_still_has_a_hashed_lock_to_install(self) -> None:
        """Dropping the manifests must not drop the pinning with them."""
        runtime = _REPO_ROOT / "requirements-runtime.txt"
        assert runtime.is_file(), "the image has nothing to install from"
        body = runtime.read_text(encoding="utf-8")
        assert "--hash=sha256:" in body, "the runtime lock must stay hash-pinned"


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
        body = _repo_only(".dockerignore").read_text(encoding="utf-8")
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
