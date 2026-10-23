"""What the quality loop looks at, which is not the same as what it says.

The loop prints "0 finding(s) on changed lines" and a row of PASS lines. Until
0.5.25 it printed that about files it had never opened. Two scoping defects,
the same one twice:

● ``scripts/check-quality.sh`` chose the files to analyse with
  ``git diff --name-only "$BASE...HEAD"``, which names files changed in
  COMMITS. A file edited but not committed was never handed to ruff, and a
  file this branch ADDED was invisible to every leg.
● ``scripts/sonar_scope.py`` then scored the surviving findings against
  ``git diff -U0 "$BASE...HEAD"``, committed line numbers, while ruff had
  reported line numbers from the working tree. The two disagree by however
  many lines the uncommitted edits add or remove, so findings were attributed
  to the wrong lines: some pre-existing smells appeared from nowhere, and -
  the direction that matters - real findings fell out of scope.

Both now read the merge base against the WORKING TREE, which is what the
submission package is built from. These tests pin that, because the failure
mode is a gate that reports green and is believed.

The pinning is BEHAVIOURAL wherever the thing under test can be run. This
module used to assert that the text "merge-base" appeared somewhere in each
script. A reviewer deleted the real ``_git("merge-base", base, "HEAD")`` call,
left behind the comment that explains why it is there, and every test here
stayed green: the string lives in prose as readily as in code. So the scoper
is now imported and exercised against throwaway repositories built under
tmp_path. Only ``check-quality.sh`` is still read as text, having no
importable surface, and then only its executable lines.

Throwaway repositories matter for a second reason. The probes below edit a
tracked file and leave an untracked one; they used to do that under the real
spectre/, and test_cognitive_complexity_meter.py then skipped itself on dirt
this suite had just created. A gate test that quietly disables itself is the
failure this release exists to stop, so nothing here touches the real tree.

scripts/ does not travel in the submission package, so every test here is
repository-only and skips where the directory is absent.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "scripts" / "check-quality.sh"
_SCOPER = _ROOT / "scripts" / "sonar_scope.py"
_METER = _ROOT / "scripts" / "cognitive_complexity.py"

#: What the throwaway repository holds at its base commit.
_TRACKED_AT_BASE = (
    '"""A module the branch already had when it started."""\n'
    "from __future__ import annotations\n"
    "\n"
    "\n"
    "def existing(value: int) -> int:\n"
    "    return value * 2\n"
)

#: Appended but never committed, so its lines exist in the working tree alone.
_UNCOMMITTED_SMELL = (
    "\n\n"
    "def added_in_the_working_tree(value: int) -> bool:\n"
    "    return value == 42\n"
)


def _script(path: Path) -> str:
    """The script's text, or a skip where scripts/ does not travel."""
    if not path.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> str:
    """*path* with its comment lines dropped.

    The gate names the ``BASE...HEAD`` defect in prose in order to explain it,
    so a search over the whole file matches the explanation rather than any
    instruction. Reading only the executable lines lets the explanation stay
    without standing in as evidence. Dropping comment LINES is not by itself
    enough: a trailing comment on an executable line survives, and a literal
    split across two lines leaves no single line carrying the defect. The
    tests below therefore read the anchor assignment and search the joined
    text rather than trusting this helper to do that work.
    """
    return "\n".join(
        line for line in _script(path).splitlines() if not line.lstrip().startswith("#")
    )


def _require_scoper() -> Path:
    """The scoper's path, or a skip where scripts/ does not travel."""
    if not _SCOPER.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    return _SCOPER


def _load_scoper():
    """``scripts/sonar_scope.py`` imported as a module.

    Same idiom as tests/unit/test_cognitive_complexity_meter.py: scripts/ sits
    outside the package, so there is nothing to import by name.
    """
    path = _require_scoper()
    spec = importlib.util.spec_from_file_location("_sonar_scope", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_sonar_scope"] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    """Run a git command inside *repo*.

    Every caller passes the throwaway repository, which is the point: a
    history-rewriting probe must never be able to reach the real checkout.

    The executable is resolved through shutil.which rather than named bare.
    A bare "git" resolves through PATH at call time, and the platform's Test
    stage runs in an image that has no git on it: that cost this project
    three releases, and TestSubprocessGuardsAreEnvironmentCorrect in
    test_deployment_contract.py now fails any module that names it bare.
    """
    git = shutil.which("git")
    if git is None:  # pragma: no cover - the repo fixture skips before this
        pytest.skip("the scoping checks need git")
    subprocess.run(  # noqa: S603
        [git, *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )


def _scope(repo: Path, findings: list[dict]) -> subprocess.CompletedProcess[str]:
    """Run the scoper inside *repo* over a synthesised ruff report."""
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_require_scoper()), "master"],
        cwd=repo,
        input=json.dumps(findings),
        capture_output=True, text=True, check=False,
    )


def _finding(path: Path, row: int) -> dict:
    """One ruff finding, shaped as ``--output-format=json`` emits it."""
    return {
        "filename": path.as_posix(),
        "location": {"row": row},
        "code": "PLR2004",
        "message": "magic value used in comparison",
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repository on branch master, holding one committed module."""
    if shutil.which("git") is None:
        pytest.skip("the scoping checks need git")
    work = tmp_path / "repo"
    (work / "spectre").mkdir(parents=True)
    work = work.resolve()
    _git(work, "init", "-q", "-b", "master")
    _git(work, "config", "user.email", "gate@example.invalid")
    _git(work, "config", "user.name", "Quality Gate Test")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "spectre" / "tracked.py").write_text(_TRACKED_AT_BASE, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    return work


class TestTheGateScriptIsStillAnchoredCorrectly:
    """``check-quality.sh`` has no importable surface, so it is read as text.

    Its executable lines only. Both assertions below were defeated once by a
    string living in a comment, which is why the comments are stripped first.
    """

    def test_no_git_call_uses_a_commit_only_range(self) -> None:
        """The whole executable text, with no line boundaries to hide behind.

        Matching line by line is defeated by splitting the literal:
        ``RANGE="$ANCHOR..."`` on one line and ``"${RANGE}HEAD"`` on the next
        reassembles the defect without any single line carrying it. The
        executable text is therefore joined before it is searched, so a
        two-line smuggle reads the same as a one-line one.
        """
        executable = _code(_GATE)
        assert "..." not in executable, (
            "a three-dot range appears in the gate's executable text. That is "
            "the commit-only comparison, and it means uncommitted work goes "
            "unanalysed. The token is banned outright rather than matched "
            "against HEAD, because a split literal defeats any narrower "
            'pattern: RANGE="$ANCHOR..." on one line and "${RANGE}HEAD" on '
            "the next reassembles the defect with no single line carrying it, "
            "and joining the lines does not help either because the two "
            "halves are no longer adjacent. The script has no other use for "
            "the token, so its absence is the cleanest statement of the rule."
        )
        assert "$ANCHOR" in executable, (
            "the gate no longer measures against the resolved anchor"
        )

    def test_the_merge_base_is_used_as_the_anchor(self) -> None:
        """Asserted on the assignment, not on the token appearing somewhere.

        The previous form was ``"merge-base" in _code(_GATE)``. Stripping
        comment LINES is not enough: deleting the real call and writing
        ``ANCHOR="$BASE"  # anchored on the merge base`` leaves the token on
        an executable line and the test passes. The anchor has to be read from
        the assignment that produces it.
        """
        assignment = re.search(r"^\s*ANCHOR=(.+)$", _code(_GATE), re.M)
        assert assignment is not None, "check-quality.sh no longer sets ANCHOR"
        produced = assignment.group(1).split("#")[0].strip()
        assert "merge-base" in produced, (
            "ANCHOR is not derived from a merge base, so commits landing on "
            f"the base branch after this one started are scored as this "
            f"branch's work; the assignment reads: {produced}"
        )


class TestTheGateCollectsUntrackedFiles:
    def test_untracked_files_are_added_to_the_file_list(self) -> None:
        """A file this branch adds is entirely new code and must be analysed."""
        assert "ls-files --others --exclude-standard" in _script(_GATE), (
            "untracked files are not collected, so a new module is analysed "
            "by nothing"
        )

    @pytest.mark.parametrize(
        "path", [_SCOPER, _METER], ids=["sonar_scope.py", "cognitive_complexity.py"],
    )
    def test_an_untracked_file_is_treated_as_wholly_new(self, path: Path) -> None:
        """All three scripts share the scope, so all three need the same rule.

        The complexity meter is included because it carries the identical
        defect by construction: it reads the same diff, so a module this
        branch adds is scored by nothing at all, whatever its complexity.
        """
        assert "?? " in _script(path), (
            f"{path.name} does not recognise untracked files, so a new "
            "module is out of scope however bad it is"
        )


class TestTheAnchorIsTheMergeBase:
    """The property a merge base provides, and nothing else does.

    Work that lands on the base branch after this branch started belongs to
    whoever committed it. Anchoring on the base branch TIP instead attributes
    every line of it to this branch, and the gate then fails a submission over
    code its author never opened, or passes one because the offsets moved.
    """

    def test_a_later_commit_on_the_base_branch_is_not_this_branch_s_work(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scoper = _load_scoper()

        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "spectre" / "feature_only.py").write_text(
            '"""A module this branch adds."""\n', encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "work on the feature branch")

        _git(repo, "checkout", "-q", "master")
        tracked = repo / "spectre" / "tracked.py"
        tracked.write_text(
            tracked.read_text(encoding="utf-8").replace("value * 2", "value * 3"),
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "a later commit on the base branch")
        _git(repo, "checkout", "-q", "feature")

        monkeypatch.chdir(repo)
        changed = scoper.changed_lines("master")

        assert changed.get("spectre/feature_only.py"), (
            "the branch's own new file is out of scope, so this probe would "
            "pass against a scoper that returned nothing at all"
        )
        assert not changed.get("spectre/tracked.py"), (
            "a commit made on the base branch after this branch started is "
            "being scored as this branch's work, which is what the merge "
            f"base exists to prevent: {sorted(changed.get('spectre/tracked.py', ()))}"
        )


class TestTheScoperMeasuresTheWorkingTree:
    """The headline fix of this release, held by something executable.

    ruff reads the working tree. A scoper that compares COMMITS disagrees with
    it by however many lines the uncommitted edits add, so an operator's
    edit-then-check loop reports clean on the very code being written.
    """

    def test_an_uncommitted_edit_to_a_tracked_file_is_in_scope(self, repo: Path) -> None:
        tracked = repo / "spectre" / "tracked.py"
        committed = tracked.read_text(encoding="utf-8")
        try:
            tracked.write_text(committed + _UNCOMMITTED_SMELL, encoding="utf-8")
            smell_row = len(tracked.read_text(encoding="utf-8").splitlines())
            assert smell_row > len(committed.splitlines()), (
                "the probe must add a line no commit has, or it proves nothing"
            )
            result = _scope(repo, [_finding(tracked, smell_row), _finding(tracked, 6)])
        finally:
            tracked.write_text(committed, encoding="utf-8")

        assert result.returncode == 1, (
            "the scoper reported clean for a finding on an uncommitted edit "
            f"to a tracked file; stdout was:\n{result.stdout}\n{result.stderr}"
        )
        assert f"spectre/tracked.py:{smell_row}" in result.stdout, (
            "the working-tree line number is not the one scored, so findings "
            f"are being attributed to the wrong lines:\n{result.stdout}"
        )
        assert "spectre/tracked.py:6" not in result.stdout, (
            "an untouched pre-existing line was scored, so the scope is not a "
            "scope at all and the loop will send operators refactoring code "
            "their change never went near"
        )


class TestTheGateActuallySeesWhatItClaims:
    """A file this branch ADDED is in no diff, so it needs its own rule.

    Against the old scripts this probe came back clean, which is precisely the
    failure being pinned: a whole new module analysed by nothing.
    """

    def test_a_smell_in_an_untracked_file_is_reported(self, repo: Path) -> None:
        probe = repo / "spectre" / "added_by_this_branch.py"
        probe.write_text(
            '"""A module this branch adds and has not committed."""\n'
            "from __future__ import annotations\n\n\n"
            "def probe(value: int) -> bool:\n"
            "    return value == 42\n",
            encoding="utf-8",
        )
        result = _scope(repo, [_finding(probe, 6)])

        assert result.returncode == 1, (
            "the scoper reported a clean result for a finding in an untracked "
            f"file; stdout was:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "spectre/added_by_this_branch.py:6" in result.stdout
