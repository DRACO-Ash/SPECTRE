#!/usr/bin/env python3
"""Measure SonarSource Cognitive Complexity (python:S3776) over this tree.

WHY THIS EXISTS

The App Store's Code Quality gate is SonarQube, and the rule that fails it most
often is S3776, Cognitive Complexity, capped at 15. Cognitive Complexity is NOT
cyclomatic complexity: ruff's C901 counts decision points, while S3776 counts
them with a NESTING PENALTY, so one deeply nested branch can cost more than
five flat ones. The two numbers diverge by a factor of three on real code, so
C901 cannot tell you whether a refactor cleared the gate.

Without a local measure, clearing S3776 is guesswork against a server-side
ruleset you see once per submission. This implements the algorithm so the
population can be measured before the upload rather than after it.

CALIBRATION

The algorithm is implemented from the SonarSource specification and then
CALIBRATED against sixteen functions whose exact Sonar scores are known from a
real scan report. ``--calibrate`` re-runs that comparison. A change to the
scoring rules that breaks a calibration case is wrong, however reasonable it
looks: the gate's number is the only one that counts.

The calibration reads those sixteen functions AT THE REVISION SONAR SCANNED,
not from the working tree, because the whole point of the exercise was to go
and refactor them. Measuring the fixed code against the broken code's scores
would fail for the best possible reason and tell you nothing. The revision is
pinned below; ``git show`` supplies the source, so the check is repository-only
and skips cleanly inside the submission package, which carries no .git.

One case needed a genuine correction rather than a tuning fudge. An ``else:``
whose body is a single ``if`` is the SAME AST node as an ``elif``, and only the
column offset separates them. Scoring both as "else if" under-counted
solve_lambert by exactly 2 against SonarQube, which is how the bug was found.

THE RULES, as implemented

Increment of 1, with a further increment equal to the current nesting depth:
    if, ternary (``x if c else y``), for, while, except handler, match

Increment of 1 with NO nesting penalty (the structure is already announced):
    elif, else, the else clause of a for/while/try, finally

Increment of 1 per SEQUENCE of like boolean operators:
    ``a and b and c``   -> 1      (one sequence)
    ``a and b or c``    -> 2      (two sequences, the operator changes)

Nesting depth is increased by: if/elif/else bodies, ternary operands, for,
while, except, match, and nested function and lambda definitions. A nested
definition adds depth but scores nothing itself, which is why extracting a
helper to module level is the cheapest way to cut a score.

Usage:
    scripts/cognitive_complexity.py                       whole tree, over limit
    scripts/cognitive_complexity.py --max 15              set the limit
    scripts/cognitive_complexity.py --all spectre/x.py    every function
    scripts/cognitive_complexity.py --calibrate           check against Sonar
    scripts/cognitive_complexity.py --json                machine-readable
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_LIMIT = 15

# The revision SonarQube scanned, and therefore the revision the sixteen scores
# below describe. Read at this commit, never from the working tree.
_CALIBRATION_REV = "047a9eb"

# Sixteen functions and the exact score SonarQube reported for each, from the
# scan of release 0.5.23. The line is the ``def`` line as Sonar reports it.
# These are the ground truth; the implementation is tuned to reproduce them.
_CALIBRATION = [
    ("spectre/web/routes/pol.py", 856, 38),
    ("spectre/domain/pol_assessment.py", 774, 47),
    ("spectre/astro/pattern_of_life.py", 685, 37),
    ("spectre/web/routes/threat.py", 304, 24),
    ("spectre/web/routes/maneuver.py", 227, 17),
    ("spectre/web/routes/threat.py", 664, 20),
    ("spectre/astro/dv_estimation.py", 971, 21),
    ("spectre/astro/lambert.py", 44, 17),
    ("spectre/astro/notso.py", 511, 29),
    ("spectre/web/routes/threat.py", 1002, 55),
    ("spectre/web/routes/udl.py", 754, 16),
    ("spectre/astro/propagator.py", 125, 19),
    ("spectre/astro/dv_estimation.py", 843, 37),
    ("spectre/astro/dv_estimation.py", 647, 27),
    ("spectre/domain/pol_assessment.py", 524, 21),
    ("spectre/domain/threat_assessment.py", 359, 16),
]

# The roots SonarQube actually analyses, from sonar-project.properties. A
# function in scripts/ is real complexity but it is not gate complexity: those
# files are neither scanned nor shipped, so failing the loop on them would
# train people to ignore the loop.
_SONAR_SOURCE_ROOTS = ("spectre", "tle_clustering")

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".cache",
    "build", "dist", ".pytest_cache", ".ruff_cache", "SPECTRE-1",
}


class _Scorer(ast.NodeVisitor):
    """Walk one function body and accumulate its cognitive complexity."""

    def __init__(self) -> None:
        self.score = 0
        self.nesting = 0

    # -- helpers ----------------------------------------------------------
    def _structural(self, node: ast.AST, body_attr: str = "body") -> None:
        """An increment that carries the nesting penalty, then descend deeper."""
        self.score += 1 + self.nesting
        self.nesting += 1
        for child in getattr(node, body_attr):
            self.visit(child)
        self.nesting -= 1

    def _flat(self, body: list) -> None:
        """An increment with no nesting penalty; the body keeps the depth."""
        self.score += 1
        self.nesting += 1
        for child in body:
            self.visit(child)
        self.nesting -= 1

    # -- branching --------------------------------------------------------
    def visit_If(self, node: ast.If) -> None:
        self.score += 1 + self.nesting
        self.visit(node.test)
        self.nesting += 1
        for child in node.body:
            self.visit(child)
        self.nesting -= 1

        orelse = node.orelse
        anchor_col = node.col_offset
        while orelse:
            # An ``elif`` parses as a lone If inside orelse. Sonar treats it as
            # "else if": one increment, no nesting penalty, body at this depth.
            #
            # So does an ``else:`` whose body happens to be a single ``if``,
            # and the two are the SAME node type. Only the column separates
            # them: ``elif`` sits at the parent's column, a nested ``if`` is
            # indented past it. Reading them as the same thing under-counted
            # solve_lambert by exactly 2 against SonarQube, which is how this
            # was found.
            if (len(orelse) == 1 and isinstance(orelse[0], ast.If)
                    and orelse[0].col_offset == anchor_col):
                chained = orelse[0]
                self.score += 1
                self.visit(chained.test)
                self.nesting += 1
                for child in chained.body:
                    self.visit(child)
                self.nesting -= 1
                orelse = chained.orelse
            else:
                self._flat(orelse)
                orelse = []

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.score += 1 + self.nesting
        self.visit(node.test)
        self.nesting += 1
        self.visit(node.body)
        self.visit(node.orelse)
        self.nesting -= 1

    # -- loops ------------------------------------------------------------
    def _loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self.score += 1 + self.nesting
        if isinstance(node, ast.While):
            self.visit(node.test)
        else:
            self.visit(node.iter)
        self.nesting += 1
        for child in node.body:
            self.visit(child)
        self.nesting -= 1
        if node.orelse:
            self._flat(node.orelse)

    visit_For = _loop
    visit_AsyncFor = _loop
    visit_While = _loop

    # -- exceptions -------------------------------------------------------
    def visit_Try(self, node: ast.Try) -> None:
        for child in node.body:
            self.visit(child)
        for handler in node.handlers:
            self._structural(handler)
        if node.orelse:
            self._flat(node.orelse)
        if node.finalbody:
            self._flat(node.finalbody)

    visit_TryStar = visit_Try

    # -- match ------------------------------------------------------------
    def visit_Match(self, node: ast.Match) -> None:
        self.score += 1 + self.nesting
        self.visit(node.subject)
        self.nesting += 1
        for case in node.cases:
            for child in case.body:
                self.visit(child)
        self.nesting -= 1

    # -- boolean sequences ------------------------------------------------
    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.score += _boolean_sequences(node)
        for value in node.values:
            # Count each operand's own structure, but never re-count the
            # sequences already charged above.
            for sub in ast.walk(value):
                if isinstance(sub, ast.BoolOp):
                    continue
            self._visit_without_boolops(value)

    def _visit_without_boolops(self, node: ast.AST) -> None:
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                self._visit_without_boolops(value)
            return
        self.visit(node)

    # -- nested definitions ------------------------------------------------
    def _nested_definition(self, node: ast.AST) -> None:
        self.nesting += 1
        for child in getattr(node, "body", []):
            self.visit(child)
        self.nesting -= 1

    visit_FunctionDef = _nested_definition
    visit_AsyncFunctionDef = _nested_definition

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.nesting += 1
        self.visit(node.body)
        self.nesting -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._nested_definition(node)


def _boolean_sequences(node: ast.BoolOp) -> int:
    """Count sequences of like operators in one boolean expression tree.

    ``a and b and c`` is one sequence. ``a and b or c`` is two: the operator
    changes, and the reader has to re-anchor. Parenthesised sub-expressions of
    a different operator count separately, which is what the nesting of BoolOp
    nodes already encodes.
    """
    operators: list[type] = []

    def walk(current: ast.AST, parent_op: type | None) -> None:
        if not isinstance(current, ast.BoolOp):
            for child in ast.iter_child_nodes(current):
                if isinstance(child, ast.BoolOp):
                    walk(child, None)
            return
        op = type(current.op)
        if op is not parent_op:
            operators.append(op)
        for value in current.values:
            walk(value, op)

    walk(node, None)
    return len(operators)


def score_function(node: ast.AST) -> int:
    """Return the cognitive complexity of one function definition."""
    scorer = _Scorer()
    for child in getattr(node, "body", []):
        scorer.visit(child)
    return scorer.score


def measure_source(source: str, path: str) -> list[dict]:
    """Return one record per function definition in *source*."""
    tree = ast.parse(source)
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        results.append({
            "path": path,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "name": node.name,
            "score": score_function(node),
        })
    return results


def measure_path(path: Path) -> list[dict]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        return measure_source(source, str(path.relative_to(_ROOT)))
    except SyntaxError:
        return []


def walk_tree(roots: list[Path]) -> list[dict]:
    results = []
    for root in roots:
        if root.is_file():
            results.extend(measure_path(root))
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            results.extend(measure_path(path))
    return results


def changed_line_ranges(base: str) -> dict[str, list[tuple[int, int]]]:
    """Return, per file, the line ranges the diff against *base* touches.

    SonarQube's quality gate is scoped to NEW CODE, so a function that is well
    over the limit but whose lines nobody touched is not reported, and a
    function one line over that someone edited is. Reproducing that scoping is
    what makes a local check predictive rather than merely stern: without it
    this repository would fail its own loop on 43 pre-existing functions and
    the signal would be ignored within a day.
    """
    git = shutil.which("git")
    if git is None:
        return {}

    # Against the MERGE BASE and the WORKING TREE, not against HEAD.
    #
    # "base...HEAD" would compare commits only, and the artefact is built from
    # the working tree. A refactor that adds one line inside an untouched
    # 67-complexity function puts that function in the gate's window, and a
    # check that cannot see uncommitted work would report it clean right up to
    # the moment of upload. That is exactly how this was found.
    merge_base = subprocess.run(  # noqa: S603
        [git, "merge-base", base, "HEAD"],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    )
    anchor = merge_base.stdout.strip() if merge_base.returncode == 0 else base

    result = subprocess.run(  # noqa: S603
        [git, "diff", "-U0", anchor],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return {}

    ranges: dict[str, list[tuple[int, int]]] = {}
    current = None
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line.startswith("@@") or current is None:
            continue
        # @@ -old,n +new,m @@
        header = line.split("@@")[1].strip()
        plus = [part for part in header.split() if part.startswith("+")]
        if not plus:
            continue
        spec = plus[0][1:]
        start_text, _, count_text = spec.partition(",")
        start = int(start_text)
        count = int(count_text) if count_text else 1
        if count == 0:  # a pure deletion touches no line of the new file
            continue
        ranges.setdefault(current, []).append((start, start + count - 1))
    return ranges


def _overlaps(record: dict, spans: list[tuple[int, int]]) -> bool:
    start, end = record["line"], record["end_line"]
    return any(not (span_end < start or span_start > end) for span_start, span_end in spans)


def run_changed(base: str, limit: int) -> int:
    """Report only functions over the limit whose lines this branch changed."""
    ranges = changed_line_ranges(base)
    if not ranges:
        print(f"  no diff against {base}, or git is unavailable; nothing to check")
        return 0

    offenders = []
    for rel, spans in sorted(ranges.items()):
        path = _ROOT / rel
        if path.suffix != ".py" or not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not rel.startswith(_SONAR_SOURCE_ROOTS):
            continue
        for record in measure_path(path):
            if record["score"] > limit and _overlaps(record, spans):
                offenders.append(record)

    offenders.sort(key=lambda r: (-r["score"], r["path"], r["line"]))
    for record in offenders:
        print(f"  OVER  {record['score']:>3}  {record['path']}:{record['line']}  {record['name']}")

    print()
    if offenders:
        print(f"  {len(offenders)} function(s) this branch touched score above {limit}.")
        print("  SonarQube scopes S3776 to new code, so these are the ones it will report.")
        return 1
    print(f"  no function this branch touched scores above {limit}.")
    return 0


def _report_line(record: dict, limit: int) -> str:
    flag = "OVER" if record["score"] > limit else "ok  "
    return f"  {flag}  {record['score']:>3}  {record['path']}:{record['line']}  {record['name']}"


def _source_at_revision(rel: str) -> str | None:
    """Return *rel* as it stood at the calibration revision, or None."""
    git = shutil.which("git")
    if git is None or not (_ROOT / ".git").exists():
        return None
    result = subprocess.run(  # noqa: S603
        [git, "show", f"{_CALIBRATION_REV}:{rel}"],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def run_calibration() -> int:
    """Compare the implementation with sixteen known SonarQube scores.

    Against the revision Sonar scanned, not the working tree: the whole purpose
    of the report was to change these functions.
    """
    print(f"Calibration against SonarQube's report for 0.5.23, at {_CALIBRATION_REV}")
    print()

    if _source_at_revision(_CALIBRATION[0][0]) is None:
        print(f"  SKIPPED: {_CALIBRATION_REV} is not readable here.")
        print("  This check is repository-only; it needs git and the commit Sonar scanned.")
        print("  Inside the submission package there is no .git, which is expected.")
        return 0

    print(f"  {'sonar':>5}  {'ours':>5}  {'delta':>5}  location")
    mismatches = 0
    missing = 0
    for rel, line, expected in _CALIBRATION:
        source = _source_at_revision(rel)
        if source is None:
            print(f"  {expected:>5}  {'?':>5}  {'?':>5}  {rel}:{line}  NOT AT {_CALIBRATION_REV}")
            missing += 1
            continue
        records = {r["line"]: r for r in measure_source(source, rel)}
        record = records.get(line)
        if record is None:
            print(f"  {expected:>5}  {'-':>5}  {'-':>5}  {rel}:{line}  NO FUNCTION AT THIS LINE")
            missing += 1
            continue
        delta = record["score"] - expected
        mark = "" if delta == 0 else "   <-- MISMATCH"
        if delta:
            mismatches += 1
        print(f"  {expected:>5}  {record['score']:>5}  {delta:>+5}  {rel}:{line}  {record['name']}{mark}")

    print()
    if missing:
        print(f"  FAIL: {missing} calibration case(s) could not be located at {_CALIBRATION_REV}.")
        print("  The pinned revision is wrong, or the case was mis-transcribed.")
        return 1
    if mismatches:
        print(f"  FAIL: {mismatches} case(s) disagree with SonarQube.")
        print("  The scoring rules are wrong. Fix them before trusting any measurement.")
        return 1
    print("  PASS: all 16 cases reproduce SonarQube's score exactly.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", default=None,
                        help="files or directories (default: spectre, tle_clustering)")
    parser.add_argument("--max", type=int, default=_DEFAULT_LIMIT,
                        help=f"the limit to report against (default {_DEFAULT_LIMIT})")
    parser.add_argument("--all", action="store_true", help="list every function, not just those over the limit")
    parser.add_argument("--calibrate", action="store_true", help="check the implementation against known Sonar scores")
    parser.add_argument("--changed", metavar="BASE",
                        help="report only functions whose lines changed against BASE, as Sonar scopes new code")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.calibrate:
        return run_calibration()

    if args.changed:
        return run_changed(args.changed, args.max)

    roots = [Path(p).resolve() for p in args.paths] if args.paths else [
        _ROOT / "spectre", _ROOT / "tle_clustering",
    ]
    records = walk_tree(roots)
    over = [r for r in records if r["score"] > args.max]
    over.sort(key=lambda r: (-r["score"], r["path"], r["line"]))

    if args.json:
        print(json.dumps({"limit": args.max, "measured": len(records), "over": over}, indent=2))
        return 1 if over else 0

    shown = records if args.all else over
    if args.all:
        shown = sorted(shown, key=lambda r: (-r["score"], r["path"], r["line"]))
    for record in shown:
        print(_report_line(record, args.max))

    print()
    print(f"  {len(records)} function(s) measured, {len(over)} over the limit of {args.max}.")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
