"""The rows Add Adversary Action and Add Friendly Response clone post what a server-rendered row posts (SPC-199).

decision.js clones the panel's <template id="adv-row-template"> and <template id="fr-row-template">. A row the
operator adds is part of the scenario the engine evaluates, so a template that posts a field of the other kind, or
carries leftover text, changes the scenario without any error in the page. Each template is therefore held to the
first row the server renders in the same panel: one element, the same fields in the same order, and no text but the
remove glyph and the hypothesis wording the server row carries too.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_FIELDS = ("input", "select", "textarea")


def _panel() -> str:
    from spectre.web.app import templates as app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(app_templates.env.filters)
    return env.get_template("partials/decision_panel.html").render(pol=None)


class _Rows(HTMLParser):
    """Each element whose class is a row class, with the names of the fields in it, its text, and whether it sits
    in a <template>; plus the number of top-level elements in each template."""

    def __init__(self, row_class: str) -> None:
        super().__init__(convert_charrefs=True)
        self._row_class = row_class
        self._template: str | None = None
        self._template_depth = 0
        self._row: dict[str, Any] | None = None
        self._row_depth = 0
        self.rows: list[dict[str, Any]] = []
        self.tops: dict[str, int] = {}
        self.stray: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "template":
            self._template, self._template_depth = found.get("id") or "", 0
            self.tops[self._template] = 0
            return
        if self._template is not None and tag not in ("input", "br", "img", "hr", "meta", "link"):
            if self._template_depth == 0:
                self.tops[self._template] += 1
            self._template_depth += 1
        if self._row is not None:
            self._row_depth += tag not in ("input", "br", "img", "hr", "meta", "link")
            if tag in _FIELDS and found.get("name"):
                self._row["names"].append(found["name"])
        elif (found.get("class") or "").split() == [self._row_class]:
            self._row = {"in_template": self._template, "names": [], "text": []}
            self._row_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "template":
            self._template = None
            return
        if self._template is not None:
            self._template_depth -= 1
        if self._row is not None:
            self._row_depth -= 1
            if self._row_depth == 0:
                self.rows.append(self._row)
                self._row = None

    def handle_data(self, data: str) -> None:
        if self._row is not None:
            self._row["text"].append(data)
        elif self._template is not None and data.strip():
            self.stray[self._template] = self.stray.get(self._template, "") + data.strip()


def _rows(row_class: str) -> _Rows:
    parser = _Rows(row_class)
    parser.feed(_panel())
    return parser


def _text(row: dict[str, Any]) -> str:
    return " ".join(" ".join(row["text"]).split())


@pytest.mark.parametrize(("row_class", "template_id"), [
    ("adv-row", "adv-row-template"),
    ("fr-row", "fr-row-template"),
])
class TestAnAddedRowIsTheServerRow:
    def test_the_template_holds_one_row_and_nothing_else(self, row_class: str, template_id: str) -> None:
        parsed = _rows(row_class)
        assert parsed.tops.get(template_id) == 1
        assert parsed.stray.get(template_id, "") == ""

    def test_it_posts_the_same_fields_in_the_same_order(self, row_class: str, template_id: str) -> None:
        parsed = _rows(row_class)
        served = [r for r in parsed.rows if r["in_template"] is None]
        cloned = [r for r in parsed.rows if r["in_template"] == template_id]
        assert served and len(cloned) == 1
        assert cloned[0]["names"] == served[0]["names"]

    def test_it_says_nothing_the_server_row_does_not(self, row_class: str, template_id: str) -> None:
        """Leftover script source, or the other kind of row, would show here as text the operator reads."""
        parsed = _rows(row_class)
        served = [r for r in parsed.rows if r["in_template"] is None]
        cloned = [r for r in parsed.rows if r["in_template"] == template_id]
        assert _text(cloned[0]) == _text(served[0])


def test_a_response_row_posts_no_adversary_field() -> None:
    cloned = [r for r in _rows("fr-row").rows if r["in_template"] == "fr-row-template"]
    assert [n for n in cloned[0]["names"] if not n.startswith("fr_")] == []
