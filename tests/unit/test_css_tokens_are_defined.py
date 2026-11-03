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

Names already undefined before this test were listed in ``_KNOWN_UNDEFINED``,
each with what it rendered as. SPC-029 emptied the list. Four names the Steel
theme defined until the token bridge (cee0de7) dropped them are restored as
aliases of theme tokens in style.css, so each follows the theme on its own;
the other nine, which no stylesheet ever defined, had their uses moved onto an
existing token. Both sets are pinned below. The list may only shrink, and an
entry that is no longer used, or is now defined, fails the test.
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
#: entry when its uses are fixed or the name is defined in both themes. Empty
#: since SPC-029; a new entry needs a reason.
_KNOWN_UNDEFINED: dict[str, str] = {}

#: Restored by SPC-029: the role the Steel theme gave each name before the
#: token bridge (cee0de7) removed it, stated once in style.css's :root as an
#: alias of a theme token. --bg-secondary was #edf1f6 beside a #f0f4f8 page,
#: so it is the page surface: a tile recessed into its panel in both themes.
_ALIASES = {
    "--text-primary": "var(--text)",
    "--text-muted": "var(--text-dim)",
    "--panel-bg": "var(--surface)",
    "--bg-secondary": "var(--bg)",
}

#: Defined by no stylesheet at any point, so SPC-029 moved every use onto the
#: existing token named here.
_RETIRED = {
    "--bg-card": "var(--bg)",
    "--border-subtle": "var(--border)",
    "--spectre-color-accent": "var(--spectre-color-intel-blue)",
    "--spectre-color-bg": "var(--spectre-surface-raised)",
    "--spectre-color-border": "var(--spectre-border-default)",
    "--spectre-color-custody-green": "var(--spectre-color-nominal-green)",
    "--spectre-color-surface-2": "var(--spectre-surface-input)",
    "--spectre-color-text-muted": "var(--spectre-text-secondary)",
    "--spectre-size-xsmall": "var(--spectre-size-caption)",
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


def _stripped_sources() -> list[str]:
    return [_COMMENTS.sub("", path.read_text(encoding="utf-8")) for path in _sources()]


def _root_block(filename: str) -> str:
    text = _COMMENTS.sub("", (_WEB / "static" / filename).read_text(encoding="utf-8"))
    start = text.index(":root {")
    return text[start:text.index("}", start)]


def test_the_restored_names_alias_a_theme_token_in_root() -> None:
    """One definition each, in style.css's :root, beside --text and --surface.

    An alias resolves on <html>, where data-theme sits, so it takes the Steel
    value of the token it names without a second definition in themes.css.
    """
    block = _root_block("style.css")
    found = {}
    for name in _ALIASES:
        match = re.search(rf"(?<![-\w]){re.escape(name)}\s*:\s*([^;]+);", block)
        if match:
            found[name] = match.group(1).strip()
    assert found == _ALIASES


def test_no_other_sheet_or_theme_block_redefines_a_restored_name() -> None:
    """The alias is the only definition, so no theme can quietly override it.

    A Steel block that set ``--panel-bg: transparent`` or a pale
    ``--text-muted`` would win on <html> and undo SPC-029 while the :root
    alias still read correctly.
    """
    counts = dict.fromkeys(_ALIASES, 0)
    for text in _stripped_sources():
        for a, b in _DEFINED.findall(text):
            if (a or b) in counts:
                counts[a or b] += 1
    assert counts == dict.fromkeys(_ALIASES, 1), f"definitions of each restored name across the console: {counts}"


def test_the_names_no_sheet_ever_defined_are_no_longer_used() -> None:
    texts = _stripped_sources()
    used = sorted(
        name for name in _RETIRED
        if any(re.search(rf"var\(\s*{re.escape(name)}\s*[,)]", text) for text in texts)
    )
    assert used == [], f"still used and still defined nowhere: {used}"


def test_the_admin_badge_is_an_accent_fill_with_knockout_ink() -> None:
    """``--spectre-color-accent`` behind ``--spectre-color-bg``: a filled pill.

    The ink is the surface the table sits on, .spectre-panel's raised
    surface, which is what "the background's colour" means on this page.
    """
    row = (_WEB / "templates" / "partials" / "admin_user_row.html").read_text(encoding="utf-8")
    assert (
        'style="background:var(--spectre-color-intel-blue); color:var(--spectre-surface-raised)">admin<'
    ) in row
