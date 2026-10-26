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
    return [
        (f"{path.relative_to(_TESTS)}:{node.lineno} {node.name}", node)
        for path in sorted(_TESTS.rglob("test_*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
    ]


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
    """``x >= 0`` on a count is true of every count; ``... or True`` of everything (audit F-080)."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(isinstance(v, ast.Constant) and v.value is True for v in test.values)
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


def test_the_checker_catches_or_true() -> None:
    def assertion(src: str) -> ast.expr:
        node = ast.parse(src).body[0]
        assert isinstance(node, ast.Assert)
        return node.test

    assert _cannot_fail(assertion("assert a <= b or True"))
    assert not _cannot_fail(assertion("assert a <= b or c"))


def _searches_without_concluding(body: list[ast.stmt]) -> list[int]:
    """Lines of ``for`` loops that ``break`` with no ``else`` and no assertion after them.

    Such a loop finds a row and checks it, so when the row is absent nothing
    is checked and the test passes (audit F-156).
    """
    lines: list[int] = []
    for i, stmt in enumerate(body):
        if isinstance(stmt, ast.For) and not stmt.orelse and _breaks(stmt):
            following = body[i + 1] if i + 1 < len(body) else None
            if not isinstance(following, ast.Assert):
                lines.append(stmt.lineno)
        blocks = [getattr(stmt, f, []) for f in ("body", "orelse", "finalbody")]
        blocks += [h.body for h in getattr(stmt, "handlers", [])]
        for block in blocks:
            lines.extend(_searches_without_concluding(block))
    return lines


def _breaks(loop: ast.For) -> bool:
    """Whether *loop* itself breaks (not a loop nested inside it)."""
    stack: list[ast.AST] = list(loop.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Break):
            return True
        if not isinstance(node, (ast.For, ast.While, ast.AsyncFor, ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(node))
    return False


def test_no_search_loop_passes_when_it_finds_nothing() -> None:
    offenders = sorted({
        f"{where} line {line}"
        for where, fn in _test_functions()
        for line in _searches_without_concluding(fn.body)
    })
    assert offenders == [], f"these loops break on a find and assert nothing when there is none: {offenders}"


def test_the_search_check_recognises_the_pattern() -> None:
    bad = ast.parse("for x in xs:\n    if x:\n        assert x\n        break\n").body
    with_else = ast.parse("for x in xs:\n    if x:\n        break\nelse:\n    raise AssertionError\n").body
    with_assert = ast.parse("for x in xs:\n    if x:\n        found = x\n        break\nassert found\n").body
    assert _searches_without_concluding(bad) == [1]
    assert _searches_without_concluding(with_else) == []
    assert _searches_without_concluding(with_assert) == []
