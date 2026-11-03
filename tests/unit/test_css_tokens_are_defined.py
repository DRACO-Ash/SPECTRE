"""Every CSS custom property a page uses is defined somewhere (SPC-027).

``var(--ops-gold)`` was written about 22 times from the first Pattern of Life
panel on, beside ``--ops-blue``, and never defined. An undefined custom
property makes the declaration invalid at computed-value time, so each of
those headings, figures and labels took the inherited colour instead of gold,
in both themes, and nothing said so.

This sweeps the templates and the static stylesheets for ``var(--name)``
and fails on any name that no stylesheet, template or script defines. A use
with a fallback, ``var(--x, #fff)``, is allowed: it says what it renders when
``--x`` is missing. A name built in a template, ``var(--spectre-status-{{ band
}}-rgb)``, passes when some defined name matches it with one word in place of
each ``{{ }}`` slot, so the text after the slot is checked as well as before.
A declaration counts as a definition only where one can start, so a BEM
selector such as ``.btn--x:hover`` defines nothing.

Names already undefined before this test are listed in ``_KNOWN_UNDEFINED``,
each with what it renders as today. Defining any of them repaints every use in
both themes, which is a design change of its own; the list may only shrink,
and an entry that is no longer used, or is now defined, fails the test.
"""

from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "spectre" / "web"

_COMMENTS = re.compile(r"/\*.*?\*/|\{#.*?#\}|<!--.*?-->", re.DOTALL)
#: A definition starts a declaration: at a line start, after whitespace, ``;``,
#: ``{`` or a quote. ``.btn--x:hover`` is a selector, not a definition of ``--x``.
_DEFINED = re.compile(
    r"(?:^|(?<=[\s;{'\"]))(--[A-Za-z0-9_-]+)\s*:|setProperty\(\s*['\"](--[A-Za-z0-9_-]+)", re.MULTILINE,
)
_USED = re.compile(r"var\(\s*(--(?:[A-Za-z0-9_-]|\{\{.*?\}\})+)\s*(,)?")
_SLOT = re.compile(r"\{\{.*?\}\}")

#: Undefined before SPC-027, with what each use renders as today. Remove an
#: entry when its uses are fixed or the name is defined in both themes.
_KNOWN_UNDEFINED = {
    "--bg-card": "background under a form control; renders transparent, the panel shows through",
    "--bg-secondary": "background of small buttons and tiles; renders transparent",
    "--border-subtle": "border-bottom shorthand; the whole declaration drops, so no rule is drawn",
    "--panel-bg": "background of decision, training, geometry and NOTSO panels; renders transparent",
    "--spectre-color-accent": "background of the admin badge; renders transparent over the badge class",
    "--spectre-color-bg": "text colour of the admin badge; inherits the row's colour",
    "--spectre-color-border": "border-bottom shorthand in the user admin table; no rule is drawn",
    "--spectre-color-custody-green": "colour of a successful admin flash; inherits the body text colour",
    "--spectre-color-surface-2": "background of the user edit row; renders transparent",
    "--spectre-color-text-muted": "colour of user admin notes; inherits the body text colour",
    "--spectre-size-xsmall": "font size in the user admin table; inherits the table's size",
    "--text-muted": "colour of secondary figures and notes; inherits the parent's colour",
    "--text-primary": "colour of primary text in panels; inherits the parent's colour, usually --text",
}


def _sources() -> list[Path]:
    templates = sorted((_WEB / "templates").rglob("*.html"))
    sheets = sorted((_WEB / "static").rglob("*.css"))
    return templates + sheets


def _definitions(texts: list[str]) -> set[str]:
    return {a or b for text in texts for a, b in _DEFINED.findall(text)}


def _is_defined(name: str, defined: set[str]) -> bool:
    """Whether *name* is defined; a templated slot stands for one word, so the text after it counts too."""
    if "{{" not in name:
        return name in defined
    pattern = re.compile("[A-Za-z0-9_]+".join(re.escape(part) for part in _SLOT.split(name)))
    return any(pattern.fullmatch(d) for d in defined)


def _undefined(texts: list[str]) -> dict[str, int]:
    """Each name used without a fallback and defined nowhere in *texts*, with its count of uses."""
    stripped = [_COMMENTS.sub("", text) for text in texts]
    defined = _definitions(stripped)
    missing: dict[str, int] = {}
    for text in stripped:
        for name, fallback in _USED.findall(text):
            if not fallback and not _is_defined(name, defined):
                missing[name] = missing.get(name, 0) + 1
    return missing


def _found() -> dict[str, int]:
    return _undefined([path.read_text(encoding="utf-8") for path in _sources()])


def test_the_sweep_reads_fallbacks_templated_names_and_comments() -> None:
    sample = """
    :root { --a: #fff; --status-high: red; --status-high-rgb: 1, 2, 3; }
    /* --b: #000; a definition in a comment is not one */
    .x { color: var(--a); background: var(--b); border-color: var(--c, #123456); }
    .y { color: var(--status-{{ band }}); outline-color: var(--nope-{{ band }}); }
    .z { color: rgba(var(--status-{{ band }}-rgb), 0.5); fill: var(--status-{{ band }}-gone); }
    """
    assert _undefined([sample]) == {"--b": 1, "--nope-{{ band }}": 1, "--status-{{ band }}-gone": 1}


def test_a_selector_with_a_double_hyphen_is_not_a_definition() -> None:
    """A BEM selector such as ``.btn--zzq:hover`` reads like ``--zzq:`` but defines nothing."""
    sample = """
    .btn--zzq:hover { color: red; }
    .x { color: var(--zzq); }
    <div style="--inline: 1px"></div><span style="width: var(--inline)"></span>
    """
    assert _undefined([sample]) == {"--zzq": 1}


def test_the_sweep_reads_the_whole_console() -> None:
    names = {path.name for path in _sources()}
    assert {"style.css", "themes.css", "spectre-theme.css", "operator.html", "pol_results.html"} <= names


def test_every_custom_property_used_is_defined() -> None:
    new = {name: count for name, count in _found().items() if name not in _KNOWN_UNDEFINED}
    assert new == {}, f"var() names defined nowhere, so each use falls back to the inherited value: {new}"


def test_the_known_undefined_list_only_shrinks() -> None:
    stale = sorted(set(_KNOWN_UNDEFINED) - set(_found()))
    assert stale == [], f"defined now or no longer used, so remove from _KNOWN_UNDEFINED: {stale}"


def test_ops_gold_is_the_brand_gold() -> None:
    """--ops-gold never existed; its uses now take --gold, which both themes define."""
    texts = [path.read_text(encoding="utf-8") for path in _sources()]
    assert not any("--ops-gold" in text for text in texts)
    themes = (_WEB / "static" / "themes.css").read_text(encoding="utf-8")
    style = (_WEB / "static" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"--gold:\s*#C8A415;", style), "the dark theme's gold"
    assert re.search(r"--gold:\s*#8A5600;", themes), "the light theme's gold, 6.16:1 on white"
