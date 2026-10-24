"""No template opens a form inside another.

Audit F-050. The training Reset form sat inside the scoring form. The HTML
parser ignores a nested <form> start tag, and the inner </form> closed the
outer one, so Reset became a submit button of the scoring form.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_TAG = re.compile(r"<(/?)form\b", re.IGNORECASE)


def _strip_comments(markup: str) -> str:
    """Blank Jinja and HTML comments, keeping their newlines so lines still count."""
    def blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return re.sub(r"<!--.*?-->", blank, re.sub(r"\{#.*?#\}", blank, markup, flags=re.S), flags=re.S)


def _nested_forms(markup: str) -> list[int]:
    """Line numbers where a <form> opens while another is still open."""
    depth, nested = 0, []
    markup = _strip_comments(markup)
    for m in _TAG.finditer(markup):
        if m.group(1):
            depth = max(0, depth - 1)
            continue
        if depth:
            nested.append(markup.count("\n", 0, m.start()) + 1)
        depth += 1
    return nested


def test_no_template_nests_a_form() -> None:
    offenders = {
        str(p.relative_to(_TEMPLATES)): lines
        for p in _TEMPLATES.rglob("*.html")
        if (lines := _nested_forms(p.read_text(encoding="utf-8")))
    }
    assert not offenders, f"a <form> opens inside another: {offenders}"


def test_the_scanner_sees_a_nested_form() -> None:
    assert _nested_forms("<form a>\n<form b></form>\n</form>") == [2]
    assert _nested_forms("<form a></form>\n<form b></form>") == []
