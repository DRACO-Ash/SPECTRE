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
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "cognitive_complexity.py"

#: Marks a file the suite itself wrote into the tree while probing the
#: quality gate. Dirt like that is not an operator's work in progress, so
#: the clean-tree check below must not accept it as a reason to stand down.
_PROBE_MARKER = "_scope_probe"


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
    """The gate reports S3776 only on new code, so the check must too.

    The scoping is half the value of the tool. Without it the loop would fail
    on 43 pre-existing functions and be ignored within a day; with it, the
    check reports exactly what the gate will.

    It is measured against the merge base and the WORKING TREE rather than
    against HEAD, because the uploaded artefact is built from the working tree.
    That is not a detail: a one-line change inside an untouched function of
    complexity 67 puts that function in the gate's window, and a check that
    compared commits only would report it clean right up to the upload.
    """

    def _overlaps(self, start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        meter = _load()
        return meter._overlaps({"line": start, "end_line": end}, spans)

    def test_a_function_inside_a_changed_span_is_in_scope(self) -> None:
        assert self._overlaps(10, 20, [(12, 14)])

    def test_a_function_wholly_before_the_change_is_not(self) -> None:
        assert not self._overlaps(10, 20, [(21, 30)])

    def test_a_function_wholly_after_the_change_is_not(self) -> None:
        assert not self._overlaps(10, 20, [(1, 9)])

    def test_a_single_touched_line_puts_the_whole_function_in_scope(self) -> None:
        """One added line inside a 67-complexity function is enough."""
        assert self._overlaps(379, 520, [(567, 567)]) is False
        assert self._overlaps(379, 600, [(567, 567)]) is True

    def test_a_change_at_either_boundary_counts(self) -> None:
        assert self._overlaps(10, 20, [(20, 20)])
        assert self._overlaps(10, 20, [(10, 10)])

    def test_scoping_is_restricted_to_the_sonar_source_roots(self) -> None:
        """A complex script is real complexity but not gate complexity."""
        meter = _load()
        assert "spectre" in meter._SONAR_SOURCE_ROOTS
        assert not "scripts/x.py".startswith(meter._SONAR_SOURCE_ROOTS)

    def test_changed_mode_runs_against_a_clean_tree(self) -> None:
        """End to end, against the real tree.

        It stands down only for dirt that could change the answer, which is
        dirt inside the scanned roots. A blanket clean-tree premise made this
        leg skip on any uncommitted work anywhere, including the suite's own,
        so the one check that runs the meter end to end almost never ran.
        """
        if not _SCRIPT.is_file():
            pytest.skip("scripts/ is excluded from the submission package")
        git = shutil.which("git")
        if git is None or not (_ROOT / ".git").exists():
            pytest.skip("the scoping check needs git")
        dirty = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        ).stdout.strip()
        leaked = [line for line in dirty.splitlines() if _PROBE_MARKER in line]
        assert not leaked, (
            "a gate probe was left in the real tree. This check used to SKIP "
            "on that dirt, so the suite silently switched off the one leg "
            f"that runs the meter end to end: {leaked}"
        )
        # --all, not --changed HEAD. Two defects in one line:
        #
        # ● --changed HEAD on a clean tree is an EMPTY diff, so the script
        #   printed "no diff against HEAD" and exited 0 whatever its scoring
        #   did. Asserting that exit code proved the script STARTS, not that
        #   it measures anything.
        # ● It also had to stand down whenever a scanned root was dirty, which
        #   on a working branch is most of the time, so the one leg that runs
        #   the meter end to end almost never ran.
        #
        # --all depends on no diff at all, so it is deterministic on a dirty
        # tree and the skip above is no longer needed for this leg.
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(_SCRIPT), "--all", "--max", "15"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        )
        measured = re.search(r"(\d+) function\(s\) measured", result.stdout)
        assert measured is not None, (
            "the meter printed no measurement summary, so it did not score; "
            f"stdout was:\n{result.stdout[-400:]}"
        )
        assert int(measured.group(1)) > 100, (
            f"the meter measured only {measured.group(1)} functions across "
            "the whole source tree, which means it is not walking it"
        )
        # The exit code is NOT asserted. --all reports every function over the
        # limit, and the tree carries pre-existing ones that SonarQube does
        # not score because they are not new code. A non-zero exit here is the
        # meter working, not failing.
        assert "ok " in result.stdout, "no function scored under the limit"


class TestTheRulesAgreeWithSonarPython:
    """Audit F-177 and F-178. Each case is checked against sonar-python's
    CognitiveComplexityVisitor (master, read on 24 October 2026), not against
    memory of the whitepaper: try and finally add nothing and finally does not
    nest; every else clause adds 1 without a nesting penalty; the visitor has
    no rule for match, whose case bodies are nested; lambdas add no nesting;
    a boolean sequence inside a call argument is counted once, as its own."""

    def test_a_boolean_one_call_deep_is_counted_once(self) -> None:
        assert _score("def f(a, b, c):\n    if a and g(b or c):\n        pass\n") == 3

    def test_depth_inside_the_call_does_not_matter(self) -> None:
        assert _score("def f(a, b, c):\n    if a and g(h(b or c)):\n        pass\n") == 3

    def test_finally_adds_nothing_and_does_not_nest(self) -> None:
        source = (
            "def f():\n"
            "    try:\n        pass\n"
            "    finally:\n        if x:\n            pass\n"
        )
        assert _score(source) == 1

    def test_a_try_else_costs_one_and_nests(self) -> None:
        source = (
            "def f():\n"
            "    try:\n        pass\n"
            "    except ValueError:\n        pass\n"
            "    else:\n        if x:\n            pass\n"
        )
        assert _score(source) == 1 + 1 + 2

    def test_a_loop_else_costs_one_and_nests(self) -> None:
        source = "def f():\n    for i in y:\n        pass\n    else:\n        if x:\n            pass\n"
        assert _score(source) == 1 + 1 + 2

    def test_match_adds_nothing_but_its_cases_nest(self) -> None:
        source = (
            "def f(v):\n"
            "    match v:\n"
            "        case 1:\n            if x:\n                pass\n"
            "        case _:\n            pass\n"
        )
        assert _score(source) == 2

    def test_a_lambda_adds_no_nesting(self) -> None:
        assert _score("def f():\n    g = lambda v: 1 if v else 2\n") == 1


def test_the_quality_script_no_longer_claims_an_exact_match() -> None:
    script = _ROOT / "scripts" / "check-quality.sh"
    if not script.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    assert "computes exactly" not in script.read_text(encoding="utf-8")
