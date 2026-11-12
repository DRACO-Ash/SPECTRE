"""The pre-paint theme script tests membership with includes(), and an open list takes the theme's colours.

● theme-boot.js asked ``valid.indexOf(t) !== -1``, which SonarJS raises as javascript:S7765 when the gate runs it;
  ``valid.includes(t)`` is exact for the string it tests. The script stays an external file: the Content Security
  Policy is script-src 'self', so an inline block would not run.
● Chromium on Windows paints a dark-scheme select's open list from the options' own colours, not the select's. Left
  to the user agent they can be text the same colour as the list, as the sweep's Target Group list was in service.
  option and optgroup now carry the theme's --bg and --text, so they follow both themes.
"""

from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "spectre" / "web"
_THEME_BOOT = _WEB / "static" / "js" / "theme-boot.js"
_COMMENTS = re.compile(r"/\*.*?\*/", re.DOTALL)


def _rules(css: str) -> dict[str, str]:
    """Each rule's selector list, normalised, mapped to its declarations."""
    body = _COMMENTS.sub("", css)
    return {" ".join(sel.split()): decls for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", body)}


class TestTheThemeScript:
    def test_membership_is_tested_with_includes(self) -> None:
        code = _COMMENTS.sub("", _THEME_BOOT.read_text(encoding="utf-8"))
        assert "valid.includes(t)" in code
        assert "indexOf" not in code

    def test_it_stays_an_external_script(self) -> None:
        base = (_WEB / "templates" / "base.html").read_text(encoding="utf-8")
        assert '<script src="/static/js/theme-boot.js"></script>' in base
        assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", base) is None, "no inline script under script-src 'self'"


class TestOptionColours:
    def test_option_and_optgroup_take_the_theme_background_and_text(self) -> None:
        rules = _rules((_WEB / "static" / "style.css").read_text(encoding="utf-8"))
        decls = rules.get("option, optgroup", "")
        assert re.search(r"background-color:\s*var\(--bg\)", decls), decls
        assert re.search(r"(?<![-\w])color:\s*var\(--text\)", decls), decls
