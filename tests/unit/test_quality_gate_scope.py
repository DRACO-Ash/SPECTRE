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

scripts/ does not travel in the submission package, so every test here is
repository-only and skips where the directory is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "scripts" / "check-quality.sh"
_SCOPER = _ROOT / "scripts" / "sonar_scope.py"
_METER = _ROOT / "scripts" / "cognitive_complexity.py"


def _script(path: Path) -> str:
    """The script's text, or a skip where scripts/ does not travel."""
    if not path.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    return path.read_text(encoding="utf-8")


class TestNeitherScriptComparesCommitsOnly:
    """``BASE...HEAD`` is the defect, in both files. It must not come back."""

    #: Tokens that mark a line as an actual git invocation rather than prose.
    #: Matching on "...HEAD" alone fails on the comments in both scripts that
    #: name the defect in order to explain it, which would make this test
    #: unfixable without deleting the explanation.
    _INVOCATION = ("_git(", "git diff", "--name-only", '"diff"')

    @pytest.mark.parametrize("path", [_GATE, _SCOPER], ids=["check-quality.sh", "sonar_scope.py"])
    def test_no_git_call_uses_a_commit_only_range(self, path: Path) -> None:
        offenders = [
            line.strip()
            for line in _script(path).splitlines()
            if "...HEAD" in line and any(tok in line for tok in self._INVOCATION)
        ]
        assert not offenders, (
            "a commit-only range is back, so uncommitted work is unanalysed: "
            f"{offenders}"
        )

    @pytest.mark.parametrize("path", [_GATE, _SCOPER], ids=["check-quality.sh", "sonar_scope.py"])
    def test_the_merge_base_is_used_as_the_anchor(self, path: Path) -> None:
        assert "merge-base" in _script(path), (
            "without a merge base, commits landing on the base branch after "
            "this one started are scored as this branch's work"
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


class TestTheGateActuallySeesWhatItClaims:
    """The behavioural half. The checks above read text; this one runs it.

    A deliberate smell is written into an untracked file under spectre/ and the
    static-analysis leg is asked about it. Against the old scripts this probe
    came back clean, which is precisely the failure being pinned.
    """

    @staticmethod
    def _requirements() -> None:
        if not _GATE.is_file() or not _SCOPER.is_file():
            pytest.skip("scripts/ is excluded from the submission package")
        if shutil.which("git") is None or not (_ROOT / ".git").exists():
            pytest.skip("the scoping check needs git")
        if shutil.which("ruff") is None:
            pytest.skip("ruff is not on PATH in this environment")

    def test_a_smell_in_an_untracked_file_is_reported(self) -> None:
        self._requirements()
        probe = _ROOT / "spectre" / "_scope_probe_delete_me.py"
        probe.write_text(
            '"""Temporary probe written by the test suite."""\n'
            "from __future__ import annotations\n\n\n"
            "def probe(value: int) -> bool:\n"
            "    return value == 42\n",
            encoding="utf-8",
        )
        try:
            result = subprocess.run(  # noqa: S603
                [sys.executable, str(_SCOPER), "HEAD"],
                cwd=_ROOT,
                input=json.dumps([{
                    "filename": probe.as_posix(),
                    "location": {"row": 6},
                    "code": "PLR2004",
                    "message": "magic value",
                }]),
                capture_output=True, text=True, check=False,
            )
        finally:
            probe.unlink(missing_ok=True)

        assert result.returncode == 1, (
            "the scoper reported a clean result for a finding in an untracked "
            f"file; stdout was:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "_scope_probe_delete_me.py" in result.stdout
