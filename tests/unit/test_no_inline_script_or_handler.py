"""No template carries script the policy would have to allow inline (SPC-199, evaluation finding F-08).

The Content Security Policy's script-src carried 'unsafe-inline' and 'unsafe-eval' because the templates held inline
<script> blocks, inline event-handler attributes and hx-on attributes, which htmx 1.9.12 compiles with new Function.
Each is now a listener in a first-party file under spectre/web/static/js. These scans keep any of them from coming
back, because one would either be refused by the browser, and a control would go quiet, or force the keyword back.

A <script type="application/json"> block is data, not script: the browser never executes it, so it stays allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parents[2] / "spectre" / "web"
_TEMPLATES = sorted((_WEB / "templates").rglob("*.html"))
_FIRST_PARTY_JS = sorted((_WEB / "static" / "js").glob("*.js"))

#: Jinja and HTML comments, which may describe a handler without carrying one.
_COMMENTS = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)
#: Jinja statements and expressions, which may hold a < or > (`{% if page <= 1 %}`) that would end a tag early, or
#: sit flush against an attribute (`{% if a %}onclick=`). Each is read as a space.
_JINJA = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.S)
_SCRIPT_OPEN = re.compile(r"<script\b([^>]*)>", re.I)
_TAG = re.compile(r"<[a-zA-Z][^<>]*?>", re.S)
_HANDLER = re.compile(r"\son[a-z]+\s*=", re.I)
_HX_ON = re.compile(r"\shx-on[:\-=]", re.I)
_TRIGGER_FILTER = re.compile(r"""hx-trigger\s*=\s*["'][^"']*\[""", re.I)
_EVAL_VALUES = re.compile(r"""\s(?:hx-vals|hx-vars|href|src|action)\s*=\s*["']\s*(?:js|javascript):""", re.I)
_HX_VARS = re.compile(r"\shx-vars\s*=", re.I)


def _source(path: Path) -> str:
    return _COMMENTS.sub("", path.read_text(encoding="utf-8"))


def _name(path: Path) -> str:
    return str(path.relative_to(_WEB / "templates"))


def _tags(source: str) -> list[str]:
    return _TAG.findall(_JINJA.sub(" ", source))


def _anywhere(pattern: re.Pattern[str]) -> list[str]:
    """Every match in the whole of a template, tag or not: a handler or hx-on has no business anywhere in one."""
    return [
        f"{_name(path)}: {match.group(0)}"
        for path in _TEMPLATES
        for match in pattern.finditer(_JINJA.sub(" ", _source(path)))
    ]


def _offenders(pattern: re.Pattern[str]) -> list[str]:
    return [
        f"{_name(path)}: {tag[:90]}"
        for path in _TEMPLATES
        for tag in _tags(_source(path))
        if pattern.search(tag)
    ]


@pytest.mark.parametrize(("source", "pattern"), [
    ('<button class="b {% if page <= 1 %}dis{% endif %}" onclick="alert(1)">', _HANDLER),
    ('<button class="b {% if page <= 1 %}dis{% endif %}" hx-on:click="alert(2)">', _HX_ON),
    ('<span title="{% if tle_age_days > 7 %}old{% endif %}" onmouseover="x()">', _HANDLER),
    ('<div {% if a %}onclick="x()"{% endif %}>', _HANDLER),
    ('<input value="{{ n > 1 }}" hx-trigger="keyup[key==\'Enter\']">', _TRIGGER_FILTER),
])
def test_the_scan_sees_a_handler_after_a_jinja_comparison_in_the_tag(source: str, pattern: re.Pattern[str]) -> None:
    """A < or > inside a Jinja tag or expression must not end the tag the scan reads (review of SPC-199)."""
    assert [tag for tag in _tags(source) if pattern.search(tag)] != []


def test_the_scan_reads_every_template() -> None:
    """If the glob found nothing, every scan below would pass for the wrong reason."""
    assert len(_TEMPLATES) >= 70


def test_no_template_holds_an_inline_script() -> None:
    """Every <script> loads a first-party file by src, or is a JSON data block the browser never runs."""
    offenders = [
        f"{_name(path)}: <script{attrs}>"
        for path in _TEMPLATES
        for attrs in _SCRIPT_OPEN.findall(_source(path))
        if "src=" not in attrs and 'type="application/json"' not in attrs
    ]
    assert offenders == []


def test_every_script_src_is_first_party() -> None:
    sources = [
        re.search(r"""src=["']([^"']+)""", attrs)
        for path in _TEMPLATES
        for attrs in _SCRIPT_OPEN.findall(_source(path))
        if "src=" in attrs
    ]
    assert sources, "no script loads at all, so the scan is not reading what it thinks it is"
    assert [m.group(1) for m in sources if m and not m.group(1).startswith("/static/")] == []


def test_no_template_carries_an_inline_event_handler() -> None:
    assert _offenders(_HANDLER) == []
    assert _anywhere(_HANDLER) == []


def test_no_template_carries_hx_on() -> None:
    """htmx compiles every hx-on attribute with new Function, which needs 'unsafe-eval'."""
    assert _offenders(_HX_ON) == []
    assert _anywhere(_HX_ON) == []


def test_no_hx_trigger_carries_a_filter() -> None:
    """htmx compiles a trigger filter such as keyup[key=='Enter'] with Function, which needs 'unsafe-eval'."""
    assert _offenders(_TRIGGER_FILTER) == []


def test_no_attribute_carries_a_javascript_value_or_hx_vars() -> None:
    """A js: or javascript: value, and hx-vars at all, is evaluated by htmx or the browser."""
    assert _offenders(_EVAL_VALUES) + _offenders(_HX_VARS) == []


def test_htmx_is_told_never_to_evaluate() -> None:
    """With allowEval off htmx refuses every evaluated feature itself, so one added later fails loudly in the
    console as htmx:evalDisallowedError rather than as a policy violation; with allowScriptTags off it never runs a
    <script> that arrives in a swapped fragment."""
    base = (_WEB / "templates" / "base.html").read_text(encoding="utf-8")
    config = re.search(r"""<meta name="htmx-config" content='([^']*)'""", base)
    assert config is not None
    assert '"allowEval":false' in config.group(1).replace(" ", "")
    assert '"allowScriptTags":false' in config.group(1).replace(" ", "")


class TestTheFirstPartyScripts:
    def test_there_are_first_party_scripts(self) -> None:
        assert [p.name for p in _FIRST_PARTY_JS if p.name == "core.js"] == ["core.js"]

    @pytest.mark.parametrize("path", _FIRST_PARTY_JS, ids=lambda p: p.name)
    def test_none_evaluates_a_string(self, path: Path) -> None:
        source = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(encoding="utf-8"), flags=re.S)
        found = re.findall(r"\beval\s*\(|new\s+Function\b|\bFunction\s*\(|set(?:Timeout|Interval)\s*\(\s*['\"]", source)
        assert found == []

    @pytest.mark.parametrize("path", _FIRST_PARTY_JS, ids=lambda p: p.name)
    def test_none_builds_an_inline_handler(self, path: Path) -> None:
        """Markup a script assembles is markup too: a handler in it would be refused like one in a template."""
        source = path.read_text(encoding="utf-8")
        assert re.findall(r"""\son[a-z]+\s*=\s*\\?["']|setAttribute\(\s*['"]on""", source) == []
