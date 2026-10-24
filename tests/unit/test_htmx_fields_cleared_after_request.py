"""Inputs an htmx request sends are not cleared before it reads them.

Audit F-043. The Add TLE button cleared the name and TLE fields in an inline
onclick, which runs before htmx's own click listener collects hx-include
values, so every add sent a blank name and TLE. Reproduced in Chromium; the
browser check is recorded in the remediation log because CI runs no browser.
This rule keeps the pattern out of every template: an element that issues an
htmx request clears inputs in hx-on::after-request, never in onclick.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_TAG = re.compile(r"<[a-zA-Z][^>]*>", re.S)
_HTMX_REQUEST = re.compile(r"\bhx-(?:post|put|patch|get|delete)=")
_ONCLICK = re.compile(r"""\bonclick=(?:"([^"]*)"|'([^']*)')""")
_CLEARS = re.compile(r"\.value\s*=")


def _offenders(markup: str) -> list[str]:
    return [
        tag[:80] for tag in _TAG.findall(markup)
        if _HTMX_REQUEST.search(tag)
        and any(_CLEARS.search(m.group(1) or m.group(2) or "") for m in _ONCLICK.finditer(tag))
    ]


def test_no_htmx_element_clears_inputs_on_click() -> None:
    bad = {
        str(p.relative_to(_TEMPLATES)): found
        for p in _TEMPLATES.rglob("*.html")
        if (found := _offenders(p.read_text(encoding="utf-8")))
    }
    assert not bad, f"clear inputs in hx-on::after-request instead: {bad}"


def test_the_rule_sees_the_old_markup() -> None:
    old = '''<button hx-post="/x" hx-include="[name='a']" onclick="document.getElementById('a').value='';">'''
    assert _offenders(old)
