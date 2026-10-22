"""The instrument that decides whether a refactor cleared the Code Quality gate.

``scripts/cognitive_complexity.py`` implements SonarSource's Cognitive
Complexity (python:S3776) so the number can be known before an upload rather
than after it. It is wired into ``scripts/check-quality.sh``, so a silent drift
in its scoring would quietly stop protecting the gate.

Ruff's C901 cannot stand in for it. C901 counts decision points; S3776 adds a
nesting penalty, so the two diverge by a factor of three on real code and a
function at C901 8 can be at S3776 38.

These tests pin the scoring rules against small cases whose score can be
derived by hand from the specification. The authoritative check is different
and lives in the script itself: ``--calibrate`` replays sixteen functions whose
exact SonarQube scores are known. That one needs git and the commit Sonar
scanned, so it is repository-only.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "cognitive_complexity.py"


def _load():
    if not _SCRIPT.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    spec = importlib.util.spec_from_file_location("_cc_meter", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_cc_meter"] = module
    spec.loader.exec_module(module)
    return module


def _score(source: str) -> int:
    meter = _load()
    records = meter.measure_source(source, "inline")
    assert records, "the fixture must define a function"
    return records[0]["score"]


class TestTheNestingPenalty:
    """What separates S3776 from cyclomatic complexity, and the whole point."""

    def test_three_flat_conditions_cost_three(self) -> None:
        assert _score(
            "def f(a, b, c):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    if c: pass\n"
        ) == 3

    def test_three_nested_conditions_cost_six(self) -> None:
        """1 + (1+1) + (1+2). The same three decisions, twice the score."""
        assert _score(
            "def f(a, b, c):\n"
            "    if a:\n"
            "        if b:\n"
            "            if c: pass\n"
        ) == 6


class TestElseAndElif:
    def test_else_costs_one_with_no_nesting_penalty(self) -> None:
        assert _score("def f(a):\n    if a: pass\n    else: pass\n") == 2

    def test_elif_costs_one_with_no_nesting_penalty(self) -> None:
        assert _score("def f(a, b):\n    if a: pass\n    elif b: pass\n") == 2

    def test_an_else_holding_a_single_if_is_not_an_elif(self) -> None:
        """The case that was wrong, and the only one the calibration caught.

        ``else:`` followed by an indented ``if`` parses to the SAME AST node as
        ``elif``. Only the column offset separates them. Reading them as the
        same thing under-counted solve_lambert by exactly 2 against SonarQube.

        elif:  if(1) + elif(1)                          = 2
        else:  if(1) + else(1) + nested if(1 + 1)       = 4
        """
        as_elif = _score("def f(a, b):\n    if a: pass\n    elif b: pass\n")
        as_else = _score("def f(a, b):\n    if a:\n        pass\n    else:\n        if b:\n            pass\n")
        assert as_elif == 2
        assert as_else == 4


class TestBooleanSequences:
    def test_one_sequence_of_like_operators_costs_one(self) -> None:
        assert _score("def f(a, b, c):\n    if a and b and c: pass\n") == 2

    def test_a_change_of_operator_costs_another(self) -> None:
        assert _score("def f(a, b, c):\n    if a and b or c: pass\n") == 3


class TestLoopsAndExceptions:
    def test_a_loop_carries_the_nesting_penalty(self) -> None:
        assert _score("def f(xs):\n    for x in xs:\n        if x: pass\n") == 3

    def test_an_except_handler_counts(self) -> None:
        assert _score("def f():\n    try:\n        pass\n    except ValueError:\n        pass\n") == 1

    def test_a_try_body_is_not_nested_by_the_try(self) -> None:
        """Only the handler is a branch; the body runs unconditionally."""
        assert _score("def f(a):\n    try:\n        if a: pass\n    except ValueError:\n        pass\n") == 2


class TestNestedDefinitions:
    def test_a_nested_function_adds_depth_but_scores_nothing_itself(self) -> None:
        """Which is why extracting a helper to module level is the cheapest cut."""
        assert _score(
            "def outer(a):\n"
            "    def inner():\n"
            "        if a: pass\n"
            "    return inner\n"
        ) == 2

    def test_the_same_branch_at_module_level_costs_one(self) -> None:
        assert _score("def inner(a):\n    if a: pass\n") == 1


class TestTernaries:
    def test_a_ternary_counts_like_an_if(self) -> None:
        assert _score("def f(a):\n    return 1 if a else 2\n") == 1

    def test_a_nested_ternary_carries_the_penalty(self) -> None:
        assert _score("def f(a, b):\n    return 1 if a else (2 if b else 3)\n") == 3


class TestItAgreesWithSonarQube:
    """The authoritative check. Repository-only: it needs the scanned commit."""

    def test_the_calibration_passes(self) -> None:
        if not _SCRIPT.is_file():
            pytest.skip("scripts/ is excluded from the submission package")
        git = shutil.which("git")
        if git is None or not (_ROOT / ".git").exists():
            pytest.skip("the calibration replays a commit; git is not available here")
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(_SCRIPT), "--calibrate"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, (
            "the meter no longer reproduces SonarQube's own scores, so every "
            f"number it reports is now a guess:\n{result.stdout}\n{result.stderr}"
        )
        assert "PASS" in result.stdout


class TestTheNewCodeScoping:
    """The gate reports S3776 only on new code, so the check must too."""

    def test_changed_mode_reports_nothing_against_head(self) -> None:
        if not _SCRIPT.is_file():
            pytest.skip("scripts/ is excluded from the submission package")
        if shutil.which("git") is None or not (_ROOT / ".git").exists():
            pytest.skip("the scoping check needs git")
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(_SCRIPT), "--changed", "HEAD", "--max", "15"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        )
        # HEAD against HEAD is an empty diff, so nothing is in scope whatever
        # the tree looks like. This pins the scoping, not the scores.
        assert result.returncode == 0, result.stdout
