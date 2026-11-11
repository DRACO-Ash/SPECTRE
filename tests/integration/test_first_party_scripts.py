"""The console's own scripts are served as scripts, and every name the markup asks for exists (SPC-199).

The behaviour the templates used to carry inline is in spectre/web/static/js, reached through data-* attributes.
Two ways that could fail without any template test noticing: a file served with a type the browser refuses under
X-Content-Type-Options: nosniff, so nothing in it runs; and an attribute naming an action, init or htmx handler no
file registers, so the control does nothing. These hold both, through the application.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

_WEB = Path(__file__).resolve().parents[2] / "spectre" / "web"
_SCRIPT_SRC = re.compile(r"""<script\b[^>]*\bsrc=["']([^"']+)["']""")

#: The attribute each kind of name is read from, and the registration that answers it.
_KINDS = {
    "action": ("data-action", "data-action-change", "data-action-input", "data-action-focus"),
    "init": ("data-init",),
    "afterRequest": ("data-after-request",),
    "afterSettle": ("data-after-settle",),
}


def _pages(client: Any, cookie: str) -> dict[str, str]:
    cookies = {"spectre_session": cookie}
    return {path: client.get(path, cookies=cookies).text for path in ("/", "/training", "/admin/users", "/login")}


def _registered() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {kind: set() for kind in _KINDS}
    for path in (_WEB / "static" / "js").glob("*.js"):
        for kind, name in re.findall(r"SPECTRE\.(action|init|afterRequest|afterSettle)\(\s*'([^']+)'",
                                     path.read_text(encoding="utf-8")):
            found[kind].add(name)
    return found


def _asked_for() -> dict[str, set[tuple[str, str]]]:
    asked: dict[str, set[tuple[str, str]]] = {kind: set() for kind in _KINDS}
    for path in (_WEB / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for kind, attrs in _KINDS.items():
            for attr in attrs:
                for name in re.findall(rf'\s{attr}="([^"]+)"', text):
                    asked[kind].add((path.name, name))
    return asked


class TestServedAsScript:
    def test_every_page_loads_core_first_party_script(self, client: Any, auth_cookie: str) -> None:
        for path, page in _pages(client, auth_cookie).items():
            assert "/static/js/core.js" in _SCRIPT_SRC.findall(page), path

    def test_each_script_a_page_names_is_served_as_javascript(self, client: Any, auth_cookie: str) -> None:
        sources = {src for page in _pages(client, auth_cookie).values() for src in _SCRIPT_SRC.findall(page)}
        assert {"/static/js/core.js", "/static/js/operator.js", "/static/js/training.js"} <= sources
        for src in sorted(sources):
            resp = client.get(src)
            assert resp.status_code == 200, src
            assert resp.headers["content-type"].split(";")[0] == "text/javascript", src
            assert resp.headers["x-content-type-options"] == "nosniff", src

    def test_the_operator_page_names_each_of_its_files(self, client: Any, auth_cookie: str) -> None:
        page = _pages(client, auth_cookie)["/"]
        names = {Path(src).name for src in _SCRIPT_SRC.findall(page) if src.startswith("/static/js/")}
        assert names == {"theme-boot.js", "core.js", "operator.js", "sweep.js", "intercepts.js", "pol.js", "gcat.js",
                         "decision.js"}


class TestEveryNameIsRegistered:
    def test_the_markup_asks_for_names(self) -> None:
        """If the scan found nothing, the check below would pass for the wrong reason."""
        asked = _asked_for()
        assert len(asked["action"]) >= 40
        assert asked["init"] and asked["afterRequest"] and asked["afterSettle"]

    @pytest.mark.parametrize("kind", sorted(_KINDS))
    def test_each_name_the_markup_asks_for_is_registered(self, kind: str) -> None:
        registered = _registered()[kind]
        missing = sorted((template, name) for template, name in _asked_for()[kind] if name not in registered)
        assert missing == []
