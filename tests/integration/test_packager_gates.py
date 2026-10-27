"""Watch every fail-closed branch of the packaging script go red.

These are the guards that decide whether an artefact ships, and until now no
test executed the script at all: they were the least covered code in the
project and the most consequential. Each case here builds a tree from the
tracked files, breaks exactly one thing, runs the real packager, and asserts it
refuses with the message that names the problem.

A guard nobody has watched fail is not a guard. This module is the committed
proof for the packaging gates.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

# Absolute paths: a partial executable name resolves through PATH, which a
# test should not depend on and the analyser flags (S607).
_GIT = shutil.which("git") or "/usr/bin/git"
_SH = shutil.which("sh") or "/bin/sh"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGER = "scripts/package-appstore.sh"

# The suite ships inside the upload, where scripts/ is stripped on purpose and
# there is no .git to build a tree from. These gates are repository-only.
#
# The git EXECUTABLE is checked separately from the .git directory. The
# platform's Test image has the directory, because the runner's helper
# container does the checkout, and no executable, because the job image is a
# bare Python one. Only the fallback path above kept this module from dying on
# FileNotFoundError there, and a fallback is not a guard.
pytestmark = pytest.mark.skipif(
    not (_REPO_ROOT / _PACKAGER).exists()
    or not (_REPO_ROOT / ".git").exists()
    or shutil.which("git") is None,
    reason="packager and git are excluded from the submission package",
)


def _tracked_tree(destination: Path) -> None:
    """Copy the tracked files as they stand in the WORKING TREE.

    Tracked files only, so a stray local artefact cannot make a case pass or
    fail for the wrong reason, but the working-tree content rather than HEAD:
    the first version of this harness used ``git archive HEAD`` and therefore
    exercised the previously committed packager, so every new gate looked
    broken when it was simply absent from the code under test. A harness that
    tests the last commit cannot tell you whether the change you are about to
    make is sound.

    The packager reads the git index for its commit stamp and for the
    tracked-input check, so the copy is initialised as a real repository.
    """
    # S603: fixed argv, no shell, and every path is test-controlled.
    listing = subprocess.run(  # noqa: S603
        [_GIT, "ls-files"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in filter(None, listing):
        source = _REPO_ROOT / relative
        if not source.is_file():
            continue  # deleted in the working tree, or a submodule
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for command in (
        [_GIT, "init", "-q"],
        [_GIT, "add", "-A", "-f"],
        [_GIT, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"],
    ):
        subprocess.run(command, cwd=destination, check=True, capture_output=True)  # noqa: S603


def _run_packager(tree: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SKIP_PACKAGE_TESTS": "1",  # the suite is exercised by its own run
    }
    # S603: fixed argv, no shell, and every path is test-controlled.
    return subprocess.run(  # noqa: S603
        [_SH, _PACKAGER, "--docker-only", "out"],
        check=False,
        cwd=tree, env=env, capture_output=True, text=True, timeout=300,
    )


@pytest.fixture
def tree() -> Iterator[Path]:
    """A throwaway repository built from the tracked files at HEAD."""
    tmp = Path(tempfile.mkdtemp(prefix="spectre-packager-"))
    try:
        _tracked_tree(tmp)
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _assert_refused(tree: Path, expected: str, break_it: Callable[[Path], None]) -> None:
    """Break one thing and assert the packager refuses, naming the problem."""
    break_it(tree)
    result = _run_packager(tree)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"the packager built an artefact it should have refused.\n{combined[-1500:]}"
    )
    assert expected in combined, (
        f"it refused, but not for the reason under test.\nExpected {expected!r} in:\n{combined[-1500:]}"
    )


class TestTheHarnessItself:
    """An unbroken tree must build, or every case below proves nothing."""

    def test_an_untouched_tree_packages_successfully(self, tree: Path) -> None:
        result = _run_packager(tree)
        assert result.returncode == 0, (
            "the fixture cannot build even unbroken, so no refusal below is meaningful.\n"
            f"{(result.stdout + result.stderr)[-2000:]}"
        )
        assert list((tree / "out").glob("*.zip")), "no archive was produced"


class TestTheDockerOnlyArchive:
    """What the docker-only archive must and must not carry, read from the zip.

    These assertions used to live in tests/unit/test_deployment_contract.py,
    gated to run only inside the docker-only archive. The packager drops
    tests/ from that archive, so they were skipped everywhere they could run
    (audit F-179). Built here once, the archive is inspected at every depth.
    """

    _RECOGNISED = frozenset({
        "requirements.txt", "requirements.in", "requirements.pip", "requires.txt",
        "setup.py", "setup.cfg", "pyproject.toml", "Pipfile", "Pipfile.lock",
        "poetry.lock", "uv.lock", "pdm.lock", "pipdeptree.json",
    })

    @pytest.fixture(scope="class")
    def archive(self) -> Iterator[zipfile.ZipFile]:
        tmp = Path(tempfile.mkdtemp(prefix="spectre-archive-"))
        try:
            _tracked_tree(tmp)
            result = _run_packager(tmp)
            assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
            (zip_path,) = (tmp / "out").glob("*.zip")
            with zipfile.ZipFile(zip_path) as zf:
                yield zf
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_recognised_manifest_at_any_depth(self, archive: zipfile.ZipFile) -> None:
        """A single one anywhere flips the analyser to the python template."""
        strays = sorted(n for n in archive.namelist() if Path(n).name in self._RECOGNISED)
        assert not strays, f"these would select the python template: {strays}"

    def test_the_image_still_has_a_hashed_lock_to_install(self, archive: zipfile.ZipFile) -> None:
        """Dropping the manifests must not drop the pinning with them."""
        assert "requirements-runtime.txt" in archive.namelist(), "the image has nothing to install from"
        body = archive.read("requirements-runtime.txt").decode("utf-8")
        assert "--hash=sha256:" in body, "the runtime lock must stay hash-pinned"

    def test_the_suite_does_not_travel(self, archive: zipfile.ZipFile) -> None:
        """Why the assertions above live here: the archive carries no tests."""
        assert not [n for n in archive.namelist() if n.startswith("tests/")]


class TestLedgerGate:
    def test_refuses_a_version_with_no_ledger_entry(self, tree: Path) -> None:
        def break_it(root: Path) -> None:
            ledger = root / "docs" / "CHANGE-LEDGER.md"
            ledger.write_text("# Change ledger\n\nNo entry for any version.\n", encoding="utf-8")

        _assert_refused(tree, "no entry for", break_it)

    def test_refuses_a_submission_carrying_two_probes(self, tree: Path) -> None:
        def break_it(root: Path) -> None:
            version = _current_version(root)
            ledger = root / "docs" / "CHANGE-LEDGER.md"
            ledger.write_text(
                f"## {version}\n\n"
                "| Gate | Class | Change |\n|---|---|---|\n"
                "| One | **PROBE** | first guess |\n"
                "| Two | **PROBE** | second guess |\n",
                encoding="utf-8",
            )

        _assert_refused(tree, "probes", break_it)

    def test_refuses_a_ledger_git_does_not_track(self, tree: Path) -> None:
        """The gate's own input must travel, or the gate only runs here.

        docs/ is gitignored by the standard template and the ledger lives in
        docs/, so this gate passed on one machine and would have failed in a
        clean clone until the file was force-added.
        """
        def break_it(root: Path) -> None:
            subprocess.run(  # noqa: S603
                [_GIT, "rm", "--cached", "-q", "docs/CHANGE-LEDGER.md"],
                cwd=root, check=True, capture_output=True,
            )

        _assert_refused(tree, "git does not track it", break_it)


class TestArchiveScopeGate:
    """Every file in the archive is analysed as application code."""

    # docs/ is absent from this list on purpose: the denylist deletes it from the
    # stage before the archive-scope check runs, so it is unreachable by this
    # route. The check still names it, as a backstop if the denylist changes.
    @pytest.mark.parametrize("unwanted", ["scripts", ".github", ".claude"])
    def test_refuses_non_application_material(self, tree: Path, unwanted: str) -> None:
        def break_it(root: Path) -> None:
            _force_into_archive(root, unwanted)

        _assert_refused(tree, "non-application material", break_it)

    def test_refuses_a_stray_markdown_file_at_the_root(self, tree: Path) -> None:
        def break_it(root: Path) -> None:
            _force_into_archive(root, "NOTES.md", is_file=True)

        _assert_refused(tree, "non-application material", break_it)


class TestManifestGate:
    def test_refuses_a_recognised_manifest_in_a_docker_only_build(self, tree: Path) -> None:
        """A manifest flips the template and restores the broken stage."""
        def break_it(root: Path) -> None:
            # The DROP list removes requirements.txt before staging, so reaching
            # the guard behind it means disabling that drop. That is exactly the
            # scenario the guard exists for: a drop list that stops dropping.
            packager = root / _PACKAGER
            text = packager.read_text(encoding="utf-8")
            assert "requirements.in requirements.txt" in text, "the DROP list shape changed"
            packager.write_text(text.replace("requirements.in requirements.txt", "requirements.in", 1))
            _force_into_archive(root, "requirements.txt", is_file=True, body="anyio==4.14.2\n")

        _assert_refused(tree, "would select the python template", break_it)


class TestSecretGate:
    def test_refuses_a_credential_shaped_file(self, tree: Path) -> None:
        def break_it(root: Path) -> None:
            _force_into_archive(root, "server.key", is_file=True, body="not-a-real-key\n")

        _assert_refused(tree, "credential-shaped files", break_it)

    def test_refuses_a_populated_secret_value(self, tree: Path) -> None:
        def break_it(root: Path) -> None:
            target = root / "spectre" / "web" / "_smoke_config.py"
            target.write_text('SECRET_KEY=a-real-looking-value\n', encoding="utf-8")

        _assert_refused(tree, "populated secret value", break_it)


# ── helpers ───────────────────────────────────────────────────────────────────


def _current_version(root: Path) -> str:
    for line in (root / "spectre" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    raise AssertionError("no __version__ in spectre/__init__.py")


def _force_into_archive(root: Path, name: str, *, is_file: bool = False, body: str = "x\n") -> None:
    """Add *name* to the packager's allowlist and create it, so it is staged.

    The allowlist is the first line of defence; these cases test the
    fail-closed checks that sit behind it, so the material has to get past the
    allowlist first.
    """
    target = root / name
    if is_file:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    else:
        target.mkdir(parents=True, exist_ok=True)
        (target / "placeholder.py").write_text("x = 1\n", encoding="utf-8")

    packager = root / _PACKAGER
    text = packager.read_text(encoding="utf-8")
    assert "\nspectre\n" in text, "the allowlist shape changed; update this helper"
    packager.write_text(text.replace("\nspectre\n", f"\n{name}\nspectre\n", 1), encoding="utf-8")
