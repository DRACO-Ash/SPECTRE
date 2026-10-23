"""The keyboard focus indicator, checked against the rule the browser obeys.

Every element that opts into keyboard operation with
``tabindex="0" onkeydown="spectreActivate(event)"`` — the expandable sweep,
screening and all-intercepts rows, every sortable column header, and the four
tab bars — had no focus rule of any kind in either theme. The only focus rules
in style.css are the three input ones, and two of those set ``outline: none``.
So the ring came entirely from Chromium's UA default, and because the ops root
declared no ``color-scheme`` while steel declared ``light``, the root computed
``normal`` and Chromium drew its LIGHT-mode ring, ``rgb(16, 16, 16)``.

Measured in Chromium, before and after, as the painted ring colour against the
surface each control actually sits on:

    control                     surface    before   after
    sweep row, BENIGN tint      #141820     1.07     7.12
    sweep row, CRITICAL tint    tinted      1.19     6.38
    sortable column header      #252B38     1.34     5.67
    inactive hero tab           #252B38     1.34     5.67
    active hero tab             wash        1.47     5.18
    sidebar tab                 #141820     1.07     7.12
    asset tab                   #1E2430     1.22     6.23
    engine tab, ops             #001529     1.03     7.38
    engine tab, steel           #0F1E2E     1.13     6.75

A focus ring is a non-text indicator, so the floor is 3:1, not 4.5:1.

This module reads the TOKEN NAME OUT OF THE RULE rather than naming a token of
its own. That is the whole point: the three colour fixes before this one were
applied to tokens the rendered rule did not read, and a token pinned by a test
is worth nothing if the rule the browser obeys names a different one. If the
rule is retargeted at a different variable, these tests follow it there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "spectre" / "web" / "static"

#: Non-text contrast floor, WCAG 2.1 SC 1.4.11. A focus ring carries no text.
_AA_NON_TEXT = 3.0

#: The elements that carry tabindex="0" onkeydown="spectreActivate(event)", or
#: are the <button> tabs of the four tab bars. Each must be named by a
#: :focus-visible selector; a control the operator can reach but cannot see is
#: the defect this module exists for.
_MUST_BE_COVERED = (
    ".threat-parent",       # sweep, screening and all-intercepts parent rows
    'th[tabindex="0"]',     # every sortable column header, all four tables
    ".stab",                # sidebar tab bar
    ".atab",                # asset sub-tab bar
    ".htab",                # hero tab bar
    ".etab",                # engine sub-tab bar
)


def _read(filename: str) -> str:
    """The stylesheet with its comments removed.

    These files carry long prose comments that quote selectors, token names
    and hex values, and this module's whole method is reading the rule rather
    than trusting a name. Left in, a comment that mentions ``:focus-visible``
    merges into the selector list of the rule after it and the commas inside
    the prose split that list in the wrong places.
    """
    text = (_STATIC / filename).read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _block(filename: str, selector: str) -> str:
    """The text of the first block whose selector contains *selector*."""
    text = _read(filename)
    start = text.find(selector)
    if start < 0:
        return ""
    opening = text.index("{", start)
    depth, index = 0, opening
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return text[opening:index]


def _tokens(filename: str, selector: str) -> dict[str, str]:
    """The ``--token: #hex;`` declarations inside *selector*'s own block."""
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;",
                           _block(filename, selector)))


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
    return "#{:02X}{:02X}{:02X}".format(
        *[round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3)]
    )


# ── The cascade, as the browser resolves it ────────────────────────────────
#
# spectre-theme.css :root, then style.css :root, carry the dark values. Steel
# then overrides them twice: once inside spectre-theme.css and once in
# themes.css, which loads afterwards.
#
# The prefers-color-scheme: light block is modelled as a SEPARATE, later step
# rather than merged into one steel dict, because its selector carries four
# compound parts and therefore outranks themes.css's single attribute
# selector. On a browser that prefers light — which is Chromium's and
# Playwright's default — it is that block, not themes.css, that supplies
# Steel's surfaces. Measuring only the themes.css merge reads surfaces the
# operator is not looking at.
_LIGHT_MEDIA_SELECTOR = ':root:not([data-spectre-theme="dark"])'

_DARK = {**_tokens("spectre-theme.css", ":root {"), **_tokens("style.css", ":root {")}
_STEEL_PREFERS_DARK = {
    **_DARK,
    **_tokens("spectre-theme.css", '[data-theme="steel"]'),
    **_tokens("themes.css", '[data-theme="steel"]'),
}
_STEEL_PREFERS_LIGHT = {
    **_STEEL_PREFERS_DARK,
    **_tokens("spectre-theme.css", _LIGHT_MEDIA_SELECTOR),
}


def _focus_visible_rules() -> list[tuple[str, str]]:
    """Every ``…:focus-visible { … }`` rule in style.css, as (selectors, body)."""
    text = _read("style.css")
    out: list[tuple[str, str]] = []
    for match in re.finditer(r"([^{}]*:focus-visible[^{}]*)\{([^{}]*)\}", text):
        out.append((match.group(1).strip(), match.group(2)))
    return out


def _ring_token_for(selector: str) -> str:
    """The custom property the browser reads for *selector*'s focus ring.

    Found by locating the rule that names the selector, then pulling the
    ``var(--…)`` out of its own outline declaration. Nothing here assumes a
    token name.
    """
    for selectors, body in _focus_visible_rules():
        parts = [s.strip() for s in selectors.split(",")]
        if f"{selector}:focus-visible" not in parts:
            continue
        outline = re.search(r"\boutline\s*:\s*([^;]+);", body)
        assert outline, f"the :focus-visible rule naming {selector} sets no outline"
        token = re.search(r"var\(\s*(--[a-z0-9-]+)\s*\)", outline.group(1))
        assert token, (
            f"{selector}:focus-visible paints {outline.group(1).strip()!r}, which is "
            "a literal rather than a themed token"
        )
        return token.group(1)
    raise AssertionError(f"no :focus-visible rule names {selector}")


class TestTheOpsRootDeclaresItsColourScheme:
    """Steel declared light and ops declared nothing, so the root was ``normal``."""

    def test_the_ops_block_declares_color_scheme_dark(self) -> None:
        block = _block("themes.css", '[data-theme="ops"]')
        assert block, 'themes.css carries no [data-theme="ops"] block'
        assert re.search(r"color-scheme\s*:\s*dark\s*;", block), (
            'the [data-theme="ops"] block does not declare color-scheme: dark, so the '
            "root computes normal and Chromium paints its LIGHT-mode focus ring, "
            "rgb(16, 16, 16), measured at 1.07:1 on a sweep row"
        )

    def test_steel_still_declares_light(self) -> None:
        assert re.search(r"color-scheme\s*:\s*light\s*;",
                         _block("themes.css", '[data-theme="steel"]'))


class TestEveryKeyboardControlIsVisiblyFocused:

    @pytest.mark.parametrize("selector", _MUST_BE_COVERED)
    def test_the_control_has_a_focus_visible_rule_that_paints_a_ring(
        self, selector: str
    ) -> None:
        token = _ring_token_for(selector)
        assert token, selector

    @pytest.mark.parametrize("selector", _MUST_BE_COVERED)
    def test_the_rule_uses_focus_visible_not_focus(self, selector: str) -> None:
        """A bare :focus would leave a ring behind after a mouse click."""
        text = _read("style.css")
        assert not re.search(rf"{re.escape(selector)}\s*:focus\s*(?![-a-z])", text), (
            f"{selector} has a bare :focus rule; a mouse click would leave the ring "
            "on the row the operator has already moved past"
        )

    @pytest.mark.parametrize("selector", _MUST_BE_COVERED)
    def test_the_ring_is_drawn_inside_the_element(self, selector: str) -> None:
        """A ring outside the box is clipped away, which is how the UA ring died.

        The sweep rows sit in a scroll container that clips an outset ring off
        their left and right edges, and a hero tab's outset ring is overdrawn
        by the flex sibling beside it: three of its four edges painted nothing
        at all. A negative outline-offset puts the ring on the element.
        """
        for selectors, body in _focus_visible_rules():
            if f"{selector}:focus-visible" in [s.strip() for s in selectors.split(",")]:
                offset = re.search(r"outline-offset\s*:\s*(-?[\d.]+)px\s*;", body)
                assert offset and float(offset.group(1)) < 0, (
                    f"{selector}:focus-visible draws its ring outside the element, "
                    "where the scroll container or the next tab clips it away"
                )
                return
        raise AssertionError(f"no :focus-visible rule names {selector}")


#: (label, surface colour) for each surface the themed ring can land on, built
#: from the tokens rather than from literals so a surface retune moves these.
def _dark_surfaces(t: dict[str, str]) -> list[tuple[str, str]]:
    return [
        ("console black", t["--spectre-color-console-black"]),
        ("sweep row / sidebar tab bar", t["--spectre-color-deep-space"]),
        ("asset tab bar", t["--spectre-color-orbital-grey"]),
        ("header / hero tab bar", t["--spectre-color-panel-grey"]),
        ("sweep row, CRITICAL tint",
         _over(t["--spectre-status-critical"], 0.12, t["--spectre-color-deep-space"])),
        ("sweep row, HIGH tint",
         _over(t["--spectre-status-high"], 0.10, t["--spectre-color-deep-space"])),
        ("sweep row, VIOLET tint",
         _over(t["--spectre-status-violet"], 0.10, t["--spectre-color-deep-space"])),
        ("active hero tab wash",
         _over(t["--spectre-color-intel-blue"], 0.08, t["--spectre-color-panel-grey"])),
    ]


def _light_surfaces(t: dict[str, str]) -> list[tuple[str, str]]:
    return [
        ("base", t["--spectre-surface-base"]),
        ("row / raised", t["--spectre-surface-raised"]),
        ("header / hero tab bar", t["--spectre-surface-panel"]),
        ("sweep row, CRITICAL tint",
         _over(t["--spectre-status-critical"], 0.12, t["--spectre-surface-raised"])),
        ("active hero tab wash",
         _over(t["--spectre-color-intel-blue"], 0.08, t["--spectre-surface-panel"])),
    ]


_CASES = (
    [("ops", _DARK, label, surface) for label, surface in _dark_surfaces(_DARK)]
    + [("steel, browser prefers light", _STEEL_PREFERS_LIGHT, label, surface)
       for label, surface in _light_surfaces(_STEEL_PREFERS_LIGHT)]
    + [("steel, browser prefers dark", _STEEL_PREFERS_DARK, label, surface)
       for label, surface in _light_surfaces(_STEEL_PREFERS_DARK)]
)


class TestTheRingClearsItsFloorOnEverySurfaceItLandsOn:
    """One raised value cannot be allowed to fix a dark surface and break a light one."""

    @pytest.mark.parametrize(("theme", "tokens", "label", "surface"), _CASES,
                             ids=[f"{c[0]}-{c[2]}" for c in _CASES])
    def test_the_themed_ring_clears_three_to_one(
        self, theme: str, tokens: dict[str, str], label: str, surface: str
    ) -> None:
        token = _ring_token_for(".threat-parent")
        colour = tokens[token]
        ratio = _ratio(colour, surface)
        assert ratio >= _AA_NON_TEXT, (
            f"{token} is {colour} in {theme} and measures {ratio:.2f}:1 on the "
            f"{label} ({surface}); a focus ring is a non-text indicator and its "
            "floor is 3:1"
        )

    @pytest.mark.parametrize(("theme", "tokens"), [
        ("ops", _DARK),
        ("steel, browser prefers light", _STEEL_PREFERS_LIGHT),
        ("steel, browser prefers dark", _STEEL_PREFERS_DARK),
    ])
    def test_the_engine_tab_ring_clears_three_to_one_on_a_bar_that_never_lightens(
        self, theme: str, tokens: dict[str, str]
    ) -> None:
        """.engine-tab-bar is var(--navy-deep) in BOTH themes.

        A ring that followed the theme would turn dark-on-dark there: the steel
        value measured 2.52:1 on #0F1E2E.
        """
        token = _ring_token_for(".etab")
        ratio = _ratio(tokens[token], tokens["--navy-deep"])
        assert ratio >= _AA_NON_TEXT, (
            f"the engine tab ring {token} is {tokens[token]} in {theme} and measures "
            f"{ratio:.2f}:1 on --navy-deep {tokens['--navy-deep']}"
        )

    def test_the_engine_tab_ring_is_not_retuned_for_light_themes(self) -> None:
        """If a light block ever overrides it, the bar goes dark-on-dark again."""
        token = _ring_token_for(".etab")
        for filename, selector in [
            ("spectre-theme.css", '[data-theme="steel"]'),
            ("themes.css", '[data-theme="steel"]'),
            ("spectre-theme.css", _LIGHT_MEDIA_SELECTOR),
        ]:
            assert token not in _tokens(filename, selector), (
                f"{token} is overridden in {filename} {selector}; the engine tab bar "
                "stays var(--navy-deep) in every theme and needs the dark-surface ring"
            )


class TestTheLightValueIsDeclaredWhereItCanWin:
    """themes.css is not the last word when the browser prefers light."""

    def test_the_themed_ring_has_a_light_value_in_the_steel_block(self) -> None:
        token = _ring_token_for(".threat-parent")
        assert (token in _tokens("spectre-theme.css", '[data-theme="steel"]')
                or token in _tokens("themes.css", '[data-theme="steel"]')), (
            f"{token} has no steel value, so the dark ring paints on a light surface"
        )

    def test_the_themed_ring_has_a_light_value_in_the_media_block(self) -> None:
        token = _ring_token_for(".threat-parent")
        assert token in _tokens("spectre-theme.css", _LIGHT_MEDIA_SELECTOR), (
            f"{token} is missing from the prefers-color-scheme: light block, whose "
            "selector outranks themes.css; on a browser that prefers light the "
            "surfaces would come from that block and the ring would not"
        )


class TestTheFloorsAreMeasuredNotAsserted:
    """The arithmetic has to be able to report a failure, or none of this means anything."""

    def test_known_pairs(self) -> None:
        assert _ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
        assert _ratio("#5FA8F5", "#5FA8F5") == pytest.approx(1.0, abs=0.001)

    def test_the_ua_light_mode_ring_still_measures_as_failing(self) -> None:
        """rgb(16, 16, 16) is what Chromium painted while the root said ``normal``."""
        assert _ratio("#101010", _DARK["--spectre-color-deep-space"]) < _AA_NON_TEXT
        assert _ratio("#101010", _DARK["--navy-deep"]) < _AA_NON_TEXT
