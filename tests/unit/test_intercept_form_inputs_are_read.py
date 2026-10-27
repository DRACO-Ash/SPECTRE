"""Every control on the intercept engine form reaches code that reads it.

Audit F-129. "Burns" and "Minimise ΔV" were live controls labelled "Optimal
only", for a method that does not exist, and the route the form posts to did
not even declare them; the single-method route declared them and never read
them. The operator changed either and got the same answer, with no sign the
input had been ignored.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from pathlib import Path

from spectre.web.routes import maneuver

_OPERATOR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / "operator.html"


def _form_inputs() -> set[str]:
    page = _OPERATOR.read_text(encoding="utf-8")
    form = re.search(r'<form id="intercept-engine-form".*?</form>', page, re.S)
    assert form, "the intercept engine form is gone"
    assert 'hx-post="/plan/maneuver/apply-all-intercepts"' in form.group(0)
    return set(re.findall(r'\sname="([a-z_]+)"', form.group(0)))


def _names_read(fn: object) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))  # type: ignore[arg-type]
    body = tree.body[0].body  # type: ignore[attr-defined]
    return {n.id for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.Name)}


def test_every_input_is_a_parameter_the_route_reads() -> None:
    route = maneuver.apply_all_intercepts
    declared = set(inspect.signature(route).parameters)
    inputs = _form_inputs()
    assert inputs - declared == set(), "the route does not declare these form inputs"
    assert inputs - _names_read(route) == set(), "the route declares but never reads these"


def test_the_single_method_route_reads_what_it_declares() -> None:
    route = maneuver.apply_intercept
    form_params = {
        name for name, p in inspect.signature(route).parameters.items()
        if "Form" in str(p.annotation)
    }
    assert form_params - _names_read(route) == set()
