"""The three changed-line gates read the diff whatever the caller's git setup, and never pass on a base they cannot read.

Found by the 0.35.0 review: each parsed only ``+++ b/`` lines, so a developer
with ``diff.noprefix`` or ``diff.mnemonicPrefix`` set saw every finding
vanish, and ``scripts/sonar_rules.py`` handed an option-like base to git, which
wrote the diff to a file and reported 0 findings, exit 0.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.unit.test_deployment_contract import _repo_only

_UNLABELLED = "spectre/web/templates/p.html:2"


def _module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_gate_{name}", _repo_only(f"scripts/{name}.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on master with one committed page, then a branch that adds an unlabelled input on line 2."""
    for args in (("init", "-q", "-b", "master"), ("config", "user.email", "t@example.invalid"),
                 ("config", "user.name", "t"), ("config", "commit.gpgsign", "false")):
        _git(tmp_path, *args)
    page = tmp_path / "spectre" / "web" / "templates" / "p.html"
    page.parent.mkdir(parents=True)
    page.write_text('<label for="a">A</label><input id="a" />\n', encoding="utf-8")
    code = tmp_path / "spectre" / "m.py"
    code.write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "work")
    page.write_text('<label for="a">A</label><input id="a" />\n<input name="b" />\n', encoding="utf-8")
    code.write_text("def f():\n    return 2\n", encoding="utf-8")
    return tmp_path


def _git(cwd: Path, *args: str) -> None:
    git_exe = shutil.which("git")
    if git_exe is None:
        pytest.skip("git is not available here")
    subprocess.run([git_exe, *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603


def _rules(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_repo_only("scripts/sonar_rules.py")), base], cwd=repo, capture_output=True, text=True, check=False,
    )


class TestTheRulesChecker:
    def test_the_finding_is_reported_by_default(self, repo: Path) -> None:
        result = _rules(repo, "master")
        assert (result.returncode, _UNLABELLED in result.stdout) == (1, True)

    @pytest.mark.parametrize("setting", ["diff.noprefix", "diff.mnemonicPrefix"])
    def test_a_diff_prefix_setting_does_not_hide_it(self, repo: Path, setting: str) -> None:
        _git(repo, "config", setting, "true")
        result = _rules(repo, "master")
        assert (result.returncode, _UNLABELLED in result.stdout) == (1, True), result.stdout

    @pytest.mark.parametrize("base", ["--output=written.txt", "--help", "no-such-ref"])
    def test_a_base_that_is_not_a_commit_is_refused_not_passed(self, repo: Path, base: str) -> None:
        result = _rules(repo, base)
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "is not a commit" in result.stderr
        assert not (repo / "written.txt").exists(), "git was handed the base as an option"

    def test_with_no_local_master_the_remote_one_is_the_base(self, repo: Path) -> None:
        """A typical CI checkout holds origin/master and no local master."""
        _git(repo, "update-ref", "refs/remotes/origin/master", "master")
        _git(repo, "branch", "-D", "master")
        result = _rules(repo, "master")
        assert (result.returncode, _UNLABELLED in result.stdout) == (1, True), result.stderr


class TestTheOtherChangedLineGates:
    @pytest.mark.parametrize("setting", ["", "diff.noprefix", "diff.mnemonicPrefix"])
    def test_the_scope_reader_sees_the_changed_line(
        self, repo: Path, setting: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if setting:
            _git(repo, "config", setting, "true")
        monkeypatch.chdir(repo)
        assert _module("sonar_scope").changed_lines("master").get("spectre/m.py") == {2}

    @pytest.mark.parametrize("setting", ["", "diff.noprefix", "diff.mnemonicPrefix"])
    def test_the_complexity_meter_sees_the_changed_line(
        self, repo: Path, setting: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if setting:
            _git(repo, "config", setting, "true")
        meter = _module("cognitive_complexity")
        monkeypatch.setattr(meter, "_ROOT", repo)
        assert meter.changed_line_ranges("master").get("spectre/m.py") == [(2, 2)]

    def test_the_complexity_meter_refuses_a_base_it_cannot_read(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        meter = _module("cognitive_complexity")
        monkeypatch.setattr(meter, "_ROOT", repo)
        with pytest.raises(SystemExit) as stopped:
            meter.changed_line_ranges("no-such-ref")
        assert stopped.value.code == 2
