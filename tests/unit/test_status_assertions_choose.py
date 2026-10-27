"""A test asserts one outcome, not success or failure (audit F-166).

``assert resp.status_code in (200, 404)`` passes whether the route works or
not. The training tests were written that way and reported the scoring path
as covered while none of its defects could fail them.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]


def _either_or(node: ast.Compare) -> bool:
    """``x in (2xx, 4xx-or-5xx)``: a membership test across success and failure."""
    if not (len(node.ops) == 1 and isinstance(node.ops[0], ast.In)):
        return False
    target = node.comparators[0]
    if not isinstance(target, (ast.Tuple, ast.List, ast.Set)):
        return False
    codes = [e.value for e in target.elts if isinstance(e, ast.Constant) and isinstance(e.value, int)]
    return any(200 <= c < 300 for c in codes) and any(c >= 400 for c in codes)


def test_no_test_accepts_both_success_and_failure() -> None:
    offenders = [
        f"{path.relative_to(_TESTS)}:{node.lineno}"
        for path in sorted(_TESTS.rglob("test_*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Compare) and _either_or(node)
    ]
    assert offenders == []


def test_the_check_recognises_the_pattern() -> None:
    def compare(src: str) -> ast.Compare:
        node = ast.parse(src, mode="eval").body
        assert isinstance(node, ast.Compare)
        return node

    assert _either_or(compare("r.status_code in (200, 404)"))
    assert not _either_or(compare("r.status_code in (301, 302, 303)"))
    assert not _either_or(compare("r.status_code in (401, 403)"))
