"""Regions that stayed dark in the steel theme while their foregrounds went light.

A surface kept dark in a light theme is only half a decision. Every foreground
that paints on it has to be re-pointed too, and .nav-bar is the one place that
was done: it pins its own background and re-colours .nav-user beside it. Three
other surfaces pinned a background and stopped there, so the text on them went
on following the light tokens. Measured in Chromium on the composited surface,
steel theme, prefers-color-scheme: light, which is the path steel runs on:

    control                                   before    after
    .etab                                     2.23:1    6.10:1
    .etab.active                              2.74:1    5.41:1
    .etab.active 2px underline (floor 3)      2.74:1    5.41:1
    #ts-badge .ltab-badge                     2.23:1    6.10:1
    .etab:hover                               1.05:1   14.33:1
    .ltab / .ltab.active / .ltab-badge        1.93:1    6.10:1
    .nav-bar .spectre-badge-nominal           2.54:1    4.76:1
    .nav-dropdown-panel .udl-label            1.93:1    7.12:1
    .nav-dropdown-panel .btn-secondary        2.23:1    7.12:1

The hover figure is the tell. Hovering a tab made it LESS readable, which is
only reachable when a surface and its foregrounds were decided apart.

The third named region, .threat-child-header th, does NOT reproduce, and
TestTheChildSubHeaderIsShadowed below pins why: its var(--navy-deep) never
reaches the screen in steel.

WHY THIS MODULE AND NOT test_contrast_floors.py
-----------------------------------------------
That module merges the steel tokens as :root, then spectre-theme.css's
[data-theme="steel"], then themes.css's. The browser does not. spectre-theme.css
also carries

    @media (prefers-color-scheme: light) {
      :root:not([data-spectre-theme="dark"]):not(.spectre-dark):not([data-theme="ops"])

whose specificity is (0,4,0) against (0,1,0) for [data-theme="steel"], so it
wins however late themes.css loads, and steel always matches it: the theme
switcher sets data-spectre-theme="light" alongside data-theme="steel". Under
that block --spectre-text-secondary is #4B5563, not the #5a7080 themes.css
declares. Every figure above is a figure against #4B5563. A merge order that
reads #5a7080 measures a colour the operator never sees, which is the same
failure mode as pinning a token the rendered rule does not name.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "spectre" / "web" / "static"
_AA_NORMAL = 4.5
_AA_INDICATOR = 3.0

#: The light-mode block in spectre-theme.css that outranks [data-theme="steel"].
_LIGHT_BLOCK = (
    ':root:not([data-spectre-theme="dark"]):not(.spectre-dark):not([data-theme="ops"])'
)


# ── CSS reading ──────────────────────────────────────────────────────

def _block_after(text: str, anchor: str) -> str:
    """The brace-balanced block of the rule whose selector is exactly *anchor*.

    Only occurrences where the next non-space character is the opening brace
    count, so asking for ``[data-theme="steel"] .nav-bar`` does not return
    ``[data-theme="steel"] .nav-bar .spectre-badge-nominal``'s block instead.
    The last such occurrence wins, matching the cascade.
    """
    carries_brace = anchor.rstrip().endswith("{")
    opening = -1
    at = text.find(anchor)
    while at >= 0:
        rest = at + len(anchor)
        if carries_brace:
            opening = text.rindex("{", at, rest)
        else:
            while rest < len(text) and text[rest] in " \t":
                rest += 1
            if rest < len(text) and text[rest] == "{":
                opening = rest
        at = text.find(anchor, at + 1)
    if opening < 0:
        return ""
    depth, index = 0, opening
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return text[opening + 1:index]


def _tokens(filename: str, anchor: str) -> dict[str, str]:
    block = _block_after((_STATIC / filename).read_text(encoding="utf-8"), anchor)
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", block))


def _declarations(filename: str, anchor: str) -> dict[str, str]:
    """``property: value`` pairs of the rule introduced by *anchor*.

    Returns {} when the rule is absent, so a missing fix fails as an assertion
    with a readable message rather than as a KeyError.
    """
    block = _block_after((_STATIC / filename).read_text(encoding="utf-8"), anchor)
    out: dict[str, str] = {}
    for part in block.split(";"):
        if ":" not in part:
            continue
        name, _, value = part.partition(":")
        name = name.strip()
        if name.startswith("--") or not name:
            continue
        out[name] = value.strip()
    return out


#: The steel cascade as Chromium resolves it. Later entries win.
#: :root is the dark base; both [data-theme="steel"] blocks are (0,1,0) and so
#: fall to file order, spectre-theme.css before themes.css; the light media
#: block is (0,4,0) and therefore last whatever the file order.
_STEEL = {
    **_tokens("spectre-theme.css", ":root {"),
    **_tokens("spectre-theme.css", '[data-theme="steel"] {'),
    **_tokens("themes.css", '[data-theme="steel"] {'),
    **_tokens("spectre-theme.css", _LIGHT_BLOCK),
}


def _resolve(value: str) -> str:
    """``var(--x)`` chains down to a hex, against the steel cascade."""
    seen = 0
    while value.startswith("var("):
        token = value[4:value.index(")")].split(",")[0].strip()
        value = _STEEL.get(token, "")
        seen += 1
        if seen > 12:  # a cycle; let the caller's assertion report it
            return ""
    return value.strip()


# ── contrast maths ─────────────────────────────────────────────────

def _luminance(colour: str) -> float:
    raw = colour.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _ratio(foreground: str, background: str) -> float:
    a, b = _luminance(foreground), _luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def _over(foreground: str, alpha: float, background: str) -> str:
    f = [int(foreground.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#{:02X}{:02X}{:02X}".format(*(round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3)))


# ── the cascade model itself ─────────────────────────────────────────

class TestTheCascadeModelMatchesTheBrowser:
    """Checked first. Every ratio below is worthless if these are wrong."""

    @pytest.mark.parametrize(("token", "painted"), [
        ("--spectre-text-secondary", "#4B5563"),   # NOT themes.css's #5a7080
        ("--spectre-text-primary", "#111827"),
        ("--spectre-surface-panel", "#E5E7EB"),    # NOT themes.css's #e0e8f2
        ("--spectre-surface-base", "#F3F4F6"),     # NOT themes.css's #f0f4f8
        ("--spectre-tab-active-text", "#1D4ED8"),  # themes.css; light block is silent
        ("--navy-deep", "#0f1e2e"),
        ("--navy", "#1a2a3a"),
    ])
    def test_the_token_resolves_to_what_chromium_paints(
        self, token: str, painted: str
    ) -> None:
        assert _STEEL[token].lower() == painted.lower(), (
            f"{token} models as {_STEEL[token]} but Chromium paints {painted} in "
            "steel; the merge order no longer matches the cascade and every "
            "figure in this module is measuring a colour nobody sees"
        )

    def test_the_light_media_block_is_the_one_that_outranks_steel(self) -> None:
        """If this selector is ever simplified the merge order above changes."""
        text = (_STATIC / "spectre-theme.css").read_text(encoding="utf-8")
        assert _LIGHT_BLOCK in text, (
            "the prefers-color-scheme: light selector changed shape; re-derive "
            "which block wins for --spectre-text-secondary before trusting _STEEL"
        )


# ── the engine sub-tab bar ───────────────────────────────────────────

_ENGINE_BAR = _declarations("themes.css", '[data-theme="steel"] .engine-tab-bar')
_ETAB_ACTIVE = _declarations("themes.css", '[data-theme="steel"] .etab.active')


class TestTheEngineSubTabBar:
    """style.css pins it to var(--navy-deep); steel keeps that at #0f1e2e."""

    def test_the_bar_is_re_tokened_in_steel(self) -> None:
        assert "background" in _ENGINE_BAR, (
            "[data-theme=\"steel\"] .engine-tab-bar declares no background, so the "
            "bar renders on var(--navy-deep) #0f1e2e while every foreground on it "
            "follows the light tokens: .etab measured 2.23:1 and .etab:hover 1.05:1"
        )
        surface = _resolve(_ENGINE_BAR["background"])
        assert _luminance(surface) > 0.5, (
            f"the steel engine tab bar still paints the dark {surface}"
        )

    @pytest.mark.parametrize(("what", "token"), [
        (".etab", "--spectre-text-secondary"),
        (".etab:hover", "--spectre-text-primary"),
        ("#ts-badge .ltab-badge", "--spectre-text-secondary"),
    ])
    def test_the_inherited_foregrounds_clear_the_floor(self, what: str, token: str) -> None:
        """These carry no steel override; the surface has to be what fixes them."""
        surface = _resolve(_ENGINE_BAR.get("background", ""))
        ratio = _ratio(_STEEL[token], surface)
        assert ratio >= _AA_NORMAL, (
            f"{what} is {ratio:.2f}:1 ({_STEEL[token]} on {surface}) in steel"
        )

    def test_the_active_tab_text_clears_the_floor(self) -> None:
        assert "color" in _ETAB_ACTIVE, (
            "[data-theme=\"steel\"] .etab.active declares no colour, so the selected "
            "sub-tab falls back to var(--gold)"
        )
        surface = _resolve(_ENGINE_BAR.get("background", ""))
        ratio = _ratio(_resolve(_ETAB_ACTIVE["color"]), surface)
        assert ratio >= _AA_NORMAL, (
            f"the steel .etab.active is {ratio:.2f}:1 and it is the state the "
            "operator is acting on"
        )

    def test_the_active_tab_underline_clears_the_indicator_floor(self) -> None:
        """2px of border is the only non-text mark of which sub-tab is open."""
        surface = _resolve(_ENGINE_BAR.get("background", ""))
        declared = _ETAB_ACTIVE.get("border-bottom-color", "")
        assert declared, "the steel .etab.active underline is not re-pointed with its text"
        ratio = _ratio(_resolve(declared), surface)
        assert ratio >= _AA_INDICATOR, (
            f"the steel .etab.active underline is {ratio:.2f}:1 against a 3:1 floor"
        )

    def test_the_active_tab_does_not_read_the_gold_token(self) -> None:
        """--gold is a light-surface foreground and is being retuned elsewhere.

        On this panel it measures 4.97:1 at the current #8A5600 and 3.21:1 if
        --gold goes back to #a07a00, which is under the 4.5 floor for the text
        and leaves the underline on 3.21:1 against a 3 floor. Nothing about the
        selected tab should move when a brand colour is retuned, so the rule
        names --spectre-tab-active-text, which .htab.active already carries.
        """
        for prop in ("color", "border-bottom-color"):
            assert "--gold" not in _ETAB_ACTIVE.get(prop, ""), (
                f".etab.active {prop} is back on var(--gold) in steel"
            )

    @pytest.mark.parametrize("gold", ["#8A5600", "#a07a00"])
    def test_the_active_tab_measures_the_same_under_either_gold(self, gold: str) -> None:
        """The point of the rule above, stated as a measurement.

        --gold is being retuned in this range. Whichever value lands, the
        selected sub-tab reads the same, because it does not read --gold.
        """
        surface = _resolve(_ENGINE_BAR.get("background", ""))
        pinned = dict(_STEEL, **{"--gold": gold})
        value = _ETAB_ACTIVE.get("color", "")
        while value.startswith("var("):
            value = pinned.get(value[4:value.index(")")].split(",")[0].strip(), "")
        ratio = _ratio(value, surface)
        assert ratio >= _AA_NORMAL, (
            f"the steel .etab.active is {ratio:.2f}:1 with --gold at {gold}; "
            "a brand retune is moving the selected tab again"
        )


# ── the lower tab bar ────────────────────────────────────────────────

_LOWER_BAR = _declarations("themes.css", '[data-theme="steel"] .lower-tab-bar')
_LTAB_ACTIVE = _declarations("themes.css", '[data-theme="steel"] .ltab.active')


class TestTheLowerTabBar:
    """No template emits .lower-tab-bar today, so nothing here is on screen.

    It is held anyway because .ltab-badge is NOT dead: #ts-badge renders it
    inside the engine bar. The pair stays measured so the surface and its
    foregrounds cannot drift apart again if the bar returns.
    """

    def test_the_bar_is_re_tokened_in_steel(self) -> None:
        assert "background" in _LOWER_BAR, (
            "[data-theme=\"steel\"] .lower-tab-bar declares no background; on "
            "var(--navy) its .ltab measured 1.93:1"
        )
        assert _luminance(_resolve(_LOWER_BAR["background"])) > 0.5

    def test_its_foregrounds_clear_their_floors(self) -> None:
        surface = _resolve(_LOWER_BAR.get("background", ""))
        assert _ratio(_STEEL["--spectre-text-secondary"], surface) >= _AA_NORMAL
        assert "color" in _LTAB_ACTIVE, "the steel .ltab.active falls back to var(--gold)"
        assert _ratio(_resolve(_LTAB_ACTIVE["color"]), surface) >= _AA_NORMAL
        assert _ratio(
            _resolve(_LTAB_ACTIVE.get("border-bottom-color", "")), surface
        ) >= _AA_INDICATOR


# ── the nav bar, which is the pattern the other three should have followed ───

_NAV_SURFACE = _declarations("themes.css", '[data-theme="steel"] .nav-bar')
_NAV_BADGE = _declarations("themes.css", '[data-theme="steel"] .nav-bar .spectre-badge-nominal')
_NAV_SECONDARY = _declarations(
    "themes.css", '[data-theme="steel"] .nav-dropdown-panel .btn-secondary'
)


class TestEverythingThatPaintsOnTheDarkNav:
    """Staying dark here is deliberate. Being unreadable on it is not."""

    def test_the_nav_is_still_pinned_dark(self) -> None:
        assert _luminance(_NAV_SURFACE["background"]) < 0.1

    def test_the_operator_console_badge_clears_the_floor(self) -> None:
        """11px/500 on an 8% green wash over the nav, so 4.5 governs."""
        assert "color" in _NAV_BADGE, (
            "the OPERATOR CONSOLE badge still takes the steel "
            "--spectre-color-nominal-green, a dark green meant for light "
            "surfaces, and measured 2.54:1 on the dark nav"
        )
        wash = _over(_STEEL["--spectre-color-nominal-green"], 0.08, _NAV_SURFACE["background"])
        ratio = _ratio(_resolve(_NAV_BADGE["color"]), wash)
        assert ratio >= _AA_NORMAL, f"the nav badge is {ratio:.2f}:1 on {wash}"

    @pytest.mark.parametrize("state", ["udl-disconnected", "udl-connected", "udl-error"])
    def test_every_udl_status_colour_clears_the_floor(self, state: str) -> None:
        """One line, three colours, and all three were left on light tokens."""
        rule = _declarations(
            "themes.css", f'[data-theme="steel"] .nav-dropdown-panel .{state} .udl-label'
        )
        assert "color" in rule, f".{state} .udl-label has no steel colour on the dark nav"
        ratio = _ratio(_resolve(rule["color"]), _NAV_SURFACE["background"])
        assert ratio >= _AA_NORMAL, f".{state} .udl-label is {ratio:.2f}:1"

    def test_the_connect_control_clears_the_floor(self) -> None:
        assert "color" in _NAV_SECONDARY, (
            ".btn-secondary in the nav dropdown still takes var(--text-dim), "
            "which is #4B5563 in steel and measured 2.23:1 there"
        )
        ratio = _ratio(_resolve(_NAV_SECONDARY["color"]), _NAV_SURFACE["background"])
        assert ratio >= _AA_NORMAL, f"the nav dropdown .btn-secondary is {ratio:.2f}:1"


# ── the one named region that did not reproduce ──────────────────────────

class TestTheChildSubHeaderIsShadowed:
    """.threat-child-header th names var(--navy-deep) and never paints it.

    The row is emitted inside <table class="hrr-table threat-table">, and
    themes.css carries

        [data-theme="steel"] .hrr-table th { background: ...; color: ...; }

    at (0,2,1) against (0,1,1) for .threat-child-header th, so in steel the
    header paints --spectre-surface-panel with --spectre-text-secondary on it:
    6.10:1, measured. The rule is live in the ops theme, where it measures
    5.33:1, so it is left exactly as it is. Pinned here because the obvious
    fix, lightening .threat-child-header th, would have changed a rule the
    browser ignores in steel and broken the one theme that obeys it.

    Its :hover heading colour is var(--gold) on the same panel, measured at
    4.97:1 and falling to 3.21:1 if --gold goes back to #a07a00. That pair is
    not re-asserted here: test_contrast_floors.TestTheGoldCallout already
    measures --gold against #E5E7EB and owns the retune.
    """

    def test_the_steel_table_header_rule_still_outranks_it(self) -> None:
        text = (_STATIC / "themes.css").read_text(encoding="utf-8")
        assert '[data-theme="steel"] .hrr-table th' in text, (
            "the rule that shadows .threat-child-header th in steel is gone; the "
            "sub-header now paints var(--navy-deep) #0f1e2e under light text"
        )

    def test_what_the_sub_header_actually_paints_clears_the_floor(self) -> None:
        rule = _declarations("themes.css", '[data-theme="steel"] .hrr-table th')
        ratio = _ratio(_resolve(rule["color"]), _resolve(rule["background"]))
        assert ratio >= _AA_NORMAL, f"the steel child sub-header is {ratio:.2f}:1"


class TestTheArithmeticStillReportsAKnownFailure:
    """Every assertion above passes if _ratio only ever returns a big number."""

    def test_known_pairs(self) -> None:
        assert _ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
        assert _ratio("#4B5563", "#4B5563") == pytest.approx(1.0, abs=0.001)

    def test_the_two_pairs_this_module_was_written_for_still_measure_as_failing(self) -> None:
        assert _ratio("#4B5563", "#0f1e2e") == pytest.approx(2.23, abs=0.02)
        assert _ratio("#8A5600", "#0f1e2e") == pytest.approx(2.74, abs=0.02)
