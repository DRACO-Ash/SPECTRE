"""No new route takes a bare ``Depends(...)`` default (H1).

The Code Quality gate reports python:S8410, FastAPI dependencies without
``Annotated``. The 77 that predate this guard convert file by file as those
files are touched (docs/CODE-QUALITY-GATE.md); this keeps the count from
growing. The allowlist may only shrink: when a file's count falls, lower it.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROUTES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "routes"

# Frozen on 2 November 2026 (0.9.0). Lower a figure when a file improves.
_ALLOWED: dict[str, int] = {
    "admin.py": 12, "decision.py": 0, "gcat.py": 3, "geometry.py": 0, "maneuver.py": 4, "operator.py": 7,
    "plan.py": 1, "pol.py": 5, "threat.py": 6, "training.py": 20, "udl.py": 16,
}


def _is_route(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
        for d in node.decorator_list
    )


def _bare_depends(path: Path) -> int:
    count = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not _is_route(node):
            continue
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]
        count += sum(1 for d in defaults if isinstance(d, ast.Call) and getattr(d.func, "id", None) == "Depends")
    return count


def test_no_route_file_adds_a_bare_depends_default() -> None:
    over = {p.name: n for p in sorted(_ROUTES.glob("*.py"))
            if (n := _bare_depends(p)) > _ALLOWED.get(p.name, 0)}
    assert not over, f"use Annotated[..., Depends(...)] in new route parameters: {over}"


def test_the_guard_sees_a_bare_depends(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("@router.get('/x')\nasync def x(user: User = Depends(require_login)) -> None: ...\n")
    assert _bare_depends(probe) == 1
