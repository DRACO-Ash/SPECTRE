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


def _over(paths: list[Path], allowed: dict[str, int]) -> dict[str, int]:
    """Each file holding more bare ``Depends`` defaults than *allowed* lets it."""
    return {p.name: n for p in paths if (n := _bare_depends(p)) > allowed.get(p.name, 0)}


def _route_files() -> list[Path]:
    return sorted(_ROUTES.glob("*.py"))


def test_no_route_file_adds_a_bare_depends_default() -> None:
    over = _over(_route_files(), _ALLOWED)
    assert not over, f"use Annotated[..., Depends(...)] in new route parameters: {over}"


def test_the_guard_sees_a_bare_depends(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("@router.get('/x')\nasync def x(user: User = Depends(require_login)) -> None: ...\n")
    assert _bare_depends(probe) == 1


def test_the_guard_sees_a_file_grow_past_its_allowance(tmp_path: Path) -> None:
    """SPC-074: the comparison as well as the count. A keyword-only default is a default too."""
    probe = tmp_path / "threat.py"
    probe.write_text(
        "@router.post('/a')\nasync def a(*, u: User = Depends(require_login)) -> None: ...\n"
        "@router.post('/b')\nasync def b(u: Annotated[User, Depends(require_login)]) -> None: ...\n"
        "def helper(u: User = Depends(require_login)) -> None: ...\n"
    )
    # One route default; the Annotated parameter and the non-route helper are not counted.
    assert _bare_depends(probe) == 1
    assert _over([probe], {"threat.py": 0}) == {"threat.py": 1}
    assert _over([probe], {"threat.py": 1}) == {}


def test_the_guard_reads_every_file_in_its_allowance() -> None:
    """SPC-074: the comparison passes on no files at all, so the scan must find each file the allowance names."""
    scanned = {path.name for path in _route_files()}
    assert set(_ALLOWED) <= scanned, f"the allowance names files the scan no longer finds: {set(_ALLOWED) - scanned}"
    # And the scan reads real routes: the files still holding bare defaults are counted, not skipped.
    assert sum(_bare_depends(path) for path in _route_files() if path.name in _ALLOWED) >= 50
