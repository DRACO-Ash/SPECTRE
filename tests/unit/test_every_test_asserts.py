"""Every test checks something that can fail.

Audit F-066 and F-147. Seven tests asserted nothing, passing as long as no
exception was raised; 20 more asserted only a type or that a value was not
None; one asserted ``added >= 0`` on a count, which cannot fail. Each was
rewritten to pin a value. This scan keeps them from coming back.

A check counts if the test has an ``assert``, a ``pytest.raises`` or
``pytest.warns`` block, calls ``pytest.fail``, or calls a helper whose name
starts ``assert``, ``_assert`` or ``_check``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_HELPER_PREFIXES = ("assert", "_assert", "_check")
_CONTEXT_CHECKS = {"raises", "warns"}


def _test_functions() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found = []
    for path in sorted(_TESTS.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                found.append((f"{path.relative_to(_TESTS)}:{node.lineno} {node.name}", node))
    return found


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _checks_something(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call) and _call_name(item.context_expr) in _CONTEXT_CHECKS
            for item in node.items
        ):
            return True
        if isinstance(node, ast.Call) and (
            _call_name(node) == "fail" or _call_name(node).startswith(_HELPER_PREFIXES)
        ):
            return True
    return False


def _type_only(test: ast.expr) -> bool:
    if isinstance(test, ast.Call) and _call_name(test) == "isinstance":
        return True
    return (
        isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot)
        and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value is None
    )


def _cannot_fail(test: ast.expr) -> bool:
    """``x >= 0`` on a count is true of every count."""
    return (
        isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.GtE)
        and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == 0
        and not isinstance(test.left, ast.Constant)
    )


def test_every_test_checks_something() -> None:
    offenders = [where for where, fn in _test_functions() if not _checks_something(fn)]
    assert not offenders, f"these tests pass whenever nothing raises: {offenders}"


def test_no_test_checks_only_types() -> None:
    offenders = []
    for where, fn in _test_functions():
        asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
        others = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
        if asserts and not others and all(_type_only(a.test) for a in asserts):
            offenders.append(where)
    assert not offenders, f"these tests check a type or not-None and no value: {offenders}"


def test_no_assertion_is_true_of_every_count() -> None:
    offenders = [
        f"{where} line {node.lineno}"
        for where, fn in _test_functions()
        for node in ast.walk(fn)
        if isinstance(node, ast.Assert) and _cannot_fail(node.test)
    ]
    assert not offenders, f"these assertions cannot fail: {offenders}"
