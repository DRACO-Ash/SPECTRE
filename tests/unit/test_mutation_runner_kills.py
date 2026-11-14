"""A kill scripts/mutate.py records must hold with the killing test run alone.

The runner runs a mutant's covering tests in order and stops at the first
failure. A test that fails only because of what an earlier test in the same
run did to shared state (an account, a cache, a module-level value) fails
after the mutant's earlier tests and passes alone: that is an order-dependent
false kill, and the mutation report's score was inflated by them before. A
kill now counts only once the killing test, run by itself against the mutant,
still fails; if it passes alone, the mutant is recorded as a survivor.

The runner forks a child per pytest run, so these tests drive its decisions
with the launches captured instead of forked.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mutate.py"


def _load_runner():
    """``scripts/mutate.py`` imported as a module: scripts/ is not a package."""
    if not _SCRIPT.is_file():
        pytest.skip("scripts/ is not in this tree")
    spec = importlib.util.spec_from_file_location("_mutate_runner", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_mutate_runner"] = module
    spec.loader.exec_module(module)
    return module


mutate = _load_runner()

_EARLIER = "tests/unit/test_a.py::test_leaves_state_behind"
_KILLER = "tests/unit/test_b.py::test_reads_that_state"


class _CapturingRunner(mutate._Runner):
    """The real runner's decisions, with each pytest run captured rather than forked."""

    def __init__(self, state: Path, ordered: dict[str, list[tuple[str, float]]]) -> None:
        args = argparse.Namespace(jobs=1, budget=60.0, quick_seconds=4.0, full_seconds=0.0,
                                  timeout_floor=30.0, timeout_factor=4.0)
        (state / "work").mkdir(parents=True, exist_ok=True)
        super().__init__(args, state, ordered)
        self.launched: list[object] = []

    def launch(self, mutant, tests, stage, seconds, origin=None, killer=""):  # noqa: PLR0913, PLR0917 - mirrors mutate._Runner.launch, which it stands in for
        started = origin.started if origin is not None else 0.0
        self.launched.append(mutate._Job(mutant, list(tests), stage, 0.0, self.work / "x", started, origin, killer))

    def last(self, stage: str):
        job = self.launched[-1]
        assert job.stage == stage, f"expected a {stage} run next, got {job.stage} with {job.tests}"
        return job

    def rows(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.results.read_text().splitlines()]


def _mutant():
    return mutate.Mutant("spectre/web/csrf.py", 10, 10, 0, 1, "x", "compare", "y")


def _killed_after(runner: _CapturingRunner, tests: list[str], killer: str):
    """Run *tests* against the mutant, *killer* failing, and the unmutated code passing up to it."""
    mutant = _mutant()
    runner.settle(mutate._Job(mutant, tests, "quick", 0.0, runner.work / "q", 0.0), {"rc": 1, "killer": killer})
    control = runner.last("confirm")
    assert control.tests == tests[: tests.index(killer) + 1]
    runner.settle(control, {"rc": 0, "killer": ""})


@pytest.fixture
def runner(tmp_path: Path) -> _CapturingRunner:
    ident = _mutant().ident
    return _CapturingRunner(tmp_path, {ident: [(_EARLIER, 1.0), (_KILLER, 1.0)]})


class TestAKillIsRunAgainWithTheKillerAlone:
    def test_a_killer_that_passes_alone_leaves_the_mutant_a_survivor(self, runner: _CapturingRunner) -> None:
        _killed_after(runner, [_EARLIER, _KILLER], _KILLER)
        alone = runner.last("verify")
        assert alone.tests == [_KILLER]
        assert alone.mutant == _mutant()
        runner.settle(alone, {"rc": 0, "killer": ""})
        [row] = runner.rows()
        assert row["status"] == "survived"
        assert row["killer"] == f"order-dependent: {_KILLER} passes alone"

    def test_a_killer_that_fails_alone_records_the_kill(self, runner: _CapturingRunner) -> None:
        _killed_after(runner, [_EARLIER, _KILLER], _KILLER)
        runner.settle(runner.last("verify"), {"rc": 1, "killer": _KILLER})
        [row] = runner.rows()
        assert row["status"] == "killed"
        assert row["killer"] == _KILLER
        assert row["alone"] is True

    def test_nothing_is_recorded_until_the_killer_has_run_alone(self, runner: _CapturingRunner) -> None:
        _killed_after(runner, [_EARLIER, _KILLER], _KILLER)
        assert not runner.results.exists()

    def test_a_killer_that_already_ran_first_needs_no_second_run(self, runner: _CapturingRunner) -> None:
        _killed_after(runner, [_KILLER, _EARLIER], _KILLER)
        assert [job.stage for job in runner.launched] == ["confirm"]
        [row] = runner.rows()
        assert (row["status"], row["alone"]) == ("killed", True)

    def test_a_killer_alone_that_cannot_run_is_an_error_not_a_kill(self, runner: _CapturingRunner) -> None:
        _killed_after(runner, [_EARLIER, _KILLER], _KILLER)
        runner.settle(runner.last("verify"), {"rc": 4, "killer": ""})
        [row] = runner.rows()
        assert row["status"] == "error"

    def test_a_kill_from_a_whole_file_run_is_checked_with_the_failing_test_alone(
        self, runner: _CapturingRunner,
    ) -> None:
        files = ["tests/unit/test_a.py", "tests/unit/test_b.py"]
        runner.settle(mutate._Job(_mutant(), files, "files", 0.0, runner.work / "f", 0.0), {"rc": 1, "killer": _KILLER})
        control = runner.last("confirm")
        assert control.tests == files
        runner.settle(control, {"rc": 0, "killer": ""})
        assert runner.last("verify").tests == [_KILLER]
