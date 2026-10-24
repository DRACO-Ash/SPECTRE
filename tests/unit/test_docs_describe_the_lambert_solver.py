"""The docs describe the Lambert solver that exists.

Audit F-173. README.md, docs/architecture.md and docs/intercept_engine.md
credited a Battin/Halley Lambert solver to transfers.py, which holds only the
Hohmann and bi-elliptic closed forms, and called lambert.py batched. The
solver is Curtis Algorithm 5.2 (universal variables, bisection on z) in
lambert.py, with multi-revolution solutions since audit F-010.
"""

from __future__ import annotations

import re

from spectre.astro import lambert
from tests.unit.test_deployment_contract import _repo_only

_DOCS = ("README.md", "docs/architecture.md", "docs/intercept_engine.md")


def test_no_doc_names_a_method_the_code_does_not_use() -> None:
    for name in _DOCS:
        text = _repo_only(name).read_text(encoding="utf-8")
        for word in ("Battin", "Halley", "Izzo", "batched"):
            assert word not in text, f"{name} says {word}"


def test_no_doc_puts_lambert_in_transfers() -> None:
    for name in _DOCS:
        for line in _repo_only(name).read_text(encoding="utf-8").splitlines():
            assert not ("transfers.py" in line and re.search(r"lambert", line, re.I)), f"{name}: {line.strip()}"


def test_the_docs_name_curtis_and_multiple_revolutions() -> None:
    engine = _repo_only("docs/intercept_engine.md").read_text(encoding="utf-8")
    assert "Curtis" in engine and "Algorithm 5.2" in engine
    assert "cheapest_lambert" in engine


def test_the_solver_docstring_is_honest() -> None:
    assert "Izzo" not in (lambert.solve_lambert.__doc__ or "")
