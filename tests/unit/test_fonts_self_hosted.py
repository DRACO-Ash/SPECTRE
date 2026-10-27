"""The console's fonts come from its own origin.

Audit F-170. The loaded theme stylesheet imported JetBrains Mono and IBM Plex
Sans from Google on every console load, which is why the content security
policy allowed fonts.googleapis.com and fonts.gstatic.com. Every operator's
console therefore told a third party when it opened.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "spectre" / "web" / "static"
_REMOTE = re.compile(r"""(@import\s+url\(\s*['"]?https?://|url\(\s*['"]?https?://)""", re.I)


def test_no_static_file_fetches_from_another_origin() -> None:
    offenders = [
        str(path.relative_to(_STATIC))
        for path in _STATIC.rglob("*")
        if path.suffix in {".css", ".html"} and _REMOTE.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_every_self_hosted_font_file_exists() -> None:
    css = (_STATIC / "fonts" / "fonts.css").read_text(encoding="utf-8")
    files = set(re.findall(r"url\(([^)]+\.woff2)\)", css))
    assert files, "fonts.css names no font files"
    for name in files:
        assert (_STATIC / "fonts" / name).stat().st_size > 1000, name
    families = set(re.findall(r"font-family: '([^']+)'", css))
    assert families == {"JetBrains Mono", "IBM Plex Sans"}


def test_the_licences_travel_with_the_fonts() -> None:
    for name in ("OFL-JetBrainsMono.txt", "OFL-IBMPlexSans.txt"):
        assert "SIL Open Font License" in (_STATIC / "fonts" / name).read_text(encoding="utf-8")


def test_the_policy_no_longer_names_google() -> None:
    from spectre.web.app import _CSP

    assert "google" not in _CSP
    assert "gstatic" not in _CSP
