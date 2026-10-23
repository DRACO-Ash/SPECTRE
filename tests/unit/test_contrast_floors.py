"""WCAG AA contrast on the pairs an operator actually reads.

Every figure written into a comment in spectre-theme.css reproduces, which is
rare and worth keeping. It was kept by hand, so a token could be retuned for
one surface and quietly fail on another. That is exactly how the four failures
this module was written for arose:

    control                         before      after
    UNCLASSIFIED banner, dark       3.39:1      5.02:1
    selected hero tab, dark         3.56:1      4.95:1
    selected hero tab, steel        3.42:1      4.83:1
    .callout-gold, steel            3.98:1      6.16:1
    status-minimal on panel, dark   4.10:1      4.72:1

The banner is the sharpest of them. A classification marking is the one label
on the console that must never be ambiguous, and it sat below the floor in the
default theme.

Two of these needed a NEW token rather than a retune. The shared
--spectre-color-nominal-green and --spectre-color-intel-blue are FOREGROUND
colours in other rules, where a light value on a dark surface is correct;
darkening them to fix a fill would have broken those. A dedicated fill token
is the fix that does not rob one rule to pay another.

Floors: 4.5 for normal text. 3.0 applies only at 24px, or 18.66px when bold,
and none of the text here is near either, so 4.5 governs throughout.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "spectre" / "web" / "static"
_AA_NORMAL = 4.5


def _tokens(filename: str, selector: str) -> dict[str, str]:
    """The ``--token: #hex;`` declarations inside *selector*'s own block.

    Block-aware on purpose. spectre-theme.css carries three token blocks in
    one file: ``:root`` for the dark theme, ``[data-theme="steel"]`` and a
    ``prefers-color-scheme: light`` media block. Taking the last declaration
    in the file instead reads a LIGHT value and measures it against a DARK
    surface, which reported status-minimal at 1.87:1 and would have had me
    "fixing" a token that was already correct.
    """
    text = (_STATIC / filename).read_text(encoding="utf-8")
    start = text.find(selector)
    if start < 0:
        return {}
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
    block = text[opening:index]
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", block))


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
    """*foreground* at *alpha* composited onto *background*."""
    f = [int(foreground.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    mixed = [round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3)]
    return "#{:02X}{:02X}{:02X}".format(*mixed)


#: The dark theme is the :root block. The steel theme inherits it and then
#: overrides, first within spectre-theme.css and then in themes.css, which
#: loads afterwards. The merge order below mirrors the cascade.
_DARK = _tokens("spectre-theme.css", ":root {")
_STEEL = {
    **_DARK,
    **_tokens("spectre-theme.css", '[data-theme="steel"]'),
    **_tokens("themes.css", '[data-theme="steel"]'),
    **_tokens("themes.css", ":root"),
}


class TestTheClassificationBanner:
    """White on the banner fill, 11px bold. The floor is 4.5."""

    @pytest.mark.parametrize(("theme", "tokens"), [("dark", _DARK), ("steel", _STEEL)])
    def test_white_on_the_banner_fill_clears_the_floor(
        self, theme: str, tokens: dict[str, str]
    ) -> None:
        fill = tokens["--spectre-classification-nominal-fill"]
        ratio = _ratio("#FFFFFF", fill)
        assert ratio >= _AA_NORMAL, (
            f"the {theme} UNCLASSIFIED banner is {ratio:.2f}:1 on {fill}; a "
            "classification marking must never be the ambiguous thing on the page"
        )

    def test_the_banner_does_not_borrow_the_foreground_green(self) -> None:
        """The fill and the text colour are different jobs and different values.

        --spectre-color-nominal-green is used as TEXT on a dark surface, so it
        is light by necessity. Using it as a fill under white text is what put
        the banner at 3.39:1.
        """
        assert (
            _DARK["--spectre-classification-nominal-fill"]
            != _DARK["--spectre-color-nominal-green"]
        ), "the banner is back on the shared foreground green"


class TestTheSelectedHeroTab:
    """The stateful fill on the primary navigation, 11.5px bold.

    Checked on the composited background, not on the panel surface: the tab's
    background is an 8% wash of intel-blue over the panel, and a ratio taken
    against the bare panel would read better than what is on screen.
    """

    @pytest.mark.parametrize(("theme", "tokens", "panel"), [
        ("dark", _DARK, "--spectre-color-panel-grey"),
        ("steel", _STEEL, "--spectre-surface-panel"),
    ])
    def test_the_active_tab_text_clears_the_floor_on_its_own_wash(
        self, theme: str, tokens: dict[str, str], panel: str
    ) -> None:
        text = tokens["--spectre-tab-active-text"]
        wash = _over(tokens["--spectre-color-intel-blue"], 0.08, tokens[panel])
        ratio = _ratio(text, wash)
        assert ratio >= _AA_NORMAL, (
            f"the {theme} selected tab is {ratio:.2f}:1 ({text} on {wash}), "
            "and it is the state the operator is acting on"
        )


class TestTheMinimalBandOnEverySurfaceItLandsOn:
    """It was audited against two surfaces and used on three."""

    @pytest.mark.parametrize("surface", [
        "--spectre-color-console-black",
        "--spectre-color-deep-space",
        "--spectre-color-panel-grey",
    ])
    def test_minimal_text_clears_the_floor(self, surface: str) -> None:
        ratio = _ratio(_DARK["--spectre-status-minimal"], _DARK[surface])
        assert ratio >= _AA_NORMAL, (
            f"status-minimal is {ratio:.2f}:1 on {surface}; it renders there as "
            "the inactive hero tabs and the HRR table headers"
        )


class TestTheGoldCallout:
    """Steel only. The dark theme's gold sits on a dark surface and is fine."""

    @pytest.mark.parametrize("surface", ["#FFFFFF", "#F3F4F6", "#E5E7EB"])
    def test_gold_text_clears_the_floor_on_every_light_surface(self, surface: str) -> None:
        ratio = _ratio(_STEEL["--gold"], surface)
        assert ratio >= _AA_NORMAL, (
            f"--gold is {ratio:.2f}:1 on {surface} in the steel theme"
        )


class TestTheFloorsAreMeasuredNotAsserted:
    """A sanity check on the arithmetic itself.

    Every test above would pass if _ratio always returned a large number, so
    the two reference pairs with known answers are checked here. Black on white
    is 21:1 exactly, and a colour against itself is 1:1.
    """

    def test_known_pairs(self) -> None:
        assert _ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
        assert _ratio("#1D9E75", "#1D9E75") == pytest.approx(1.0, abs=0.001)

    def test_the_arithmetic_still_reports_a_known_failure(self) -> None:
        """The value the banner used to carry must still measure as failing."""
        assert _ratio("#FFFFFF", "#1D9E75") < _AA_NORMAL
