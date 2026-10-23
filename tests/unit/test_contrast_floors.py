"""WCAG AA contrast on the pairs an operator actually reads.

Every figure written into a comment in spectre-theme.css reproduces, which is
rare and worth keeping. It was kept by hand, so a token could be retuned for
one surface and quietly fail on another. That is exactly how the four failures
this module was written for arose:

    control                         before      after
    UNCLASSIFIED banner, dark       3.39:1      5.02:1
    selected hero tab, dark         3.56:1      4.95:1
    selected hero tab, steel        3.41:1      4.91:1
    .callout-gold, steel            3.98:1      6.16:1
    status-minimal on panel, dark   4.10:1      4.72:1
    selected sidebar tab, steel     3.66:1      5.27:1

The last row is a different kind of failure and is checked a different way.
Nothing was wrong with any token: --spectre-tab-active-text already measured
4.92:1 here. .stab.active simply still NAMED the shared intel blue after its
twin .htab.active had been moved off it, so the rule the browser obeyed and
the token this module measured were two different colours and every check
below stayed green while the screen sat at 3.66:1. TestTheSelectedSidebarTab
therefore reads the declarations out of the rules themselves.

A fifth failure was created by the fourth. --gold was darkened for
.callout-gold, but --gold is also what .etab.active paints onto a tab bar of
--navy-deep, and in the steel theme the selected engine sub-tab went from
4.15:1 to 2.74:1 measured in Chromium. Ten rules were carried down with it,
and the --gold-dim / --gold-mid / --gold-aNN ladder was left behind at the old
rgba(160, 122, 0) so every gold tint stopped matching the gold text on it.
Both are held below.

The banner is the sharpest of them. A classification marking is the one label
on the console that must never be ambiguous, and it sat below the floor in the
default theme.

Two of these needed a NEW token rather than a retune. The shared
--spectre-color-nominal-green and --spectre-color-intel-blue are FOREGROUND
colours in other rules, where a light value on a dark surface is correct;
darkening them to fix a fill would have broken those. A dedicated fill token
is the fix that does not rob one rule to pay another.

Floors: 4.5 for normal text. 3.0 applies at 24px, or 18.66px when bold, and
to non-text indicators such as a tab underline, a selection marker or a focus
ring. Every piece of TEXT checked here is small, so 4.5 governs it; the handful
of 3.0 cases are named one by one with what earns them.
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


def _rule_block(filename: str, selector: str) -> str:
    """The declarations inside the one rule whose selector is *selector*.

    Comments are stripped first so prose that quotes a selector cannot be
    mistaken for one, and the selector is matched with its trailing ``{`` so
    ``.htab.active`` does not also catch ``.htab.active::after``. A second
    rule with the same selector makes this shout rather than silently
    measuring whichever one happens to come first.
    """
    text = re.sub(r"/\*.*?\*/", "", (_STATIC / filename).read_text(encoding="utf-8"), flags=re.S)
    hits = list(re.finditer(re.escape(selector) + r"\s*\{", text))
    assert len(hits) == 1, (
        f"expected exactly one `{selector}` rule in {filename}, found {len(hits)}"
    )
    opening = hits[0].end() - 1
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


def _declared(filename: str, selector: str, prop: str) -> str:
    """The value *selector*'s own block gives *prop*, verbatim.

    This reads the RULE, not the token table, and that is the whole point of
    it. The lookbehind keeps ``color`` from matching ``border-bottom-color``.
    """
    block = _rule_block(filename, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}\s*:\s*([^;}}]+)", block)
    assert match, f"`{selector}` in {filename} declares no {prop}"
    return match.group(1).strip()


def _resolve(value: str, tokens: dict[str, str]) -> str:
    """A ``var(--token)`` reference or a literal hex, as ``#RRGGBB``."""
    reference = re.fullmatch(r"var\(\s*(--[a-z0-9-]+)\s*\)", value)
    if reference:
        name = reference.group(1)
        assert name in tokens, f"{name} carries no hex value in this theme"
        return tokens[name]
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"cannot resolve {value!r} to a colour"
    return value


#: The dark theme is the :root block. The steel theme inherits it and then
#: overrides: first within spectre-theme.css, then in themes.css, and last of
#: all from spectre-theme.css's own prefers-color-scheme: light block. The
#: merge order below mirrors the cascade.
#:
#: That fourth step is not a load-order step and leaving it out modelled
#: surfaces that are not on screen. The media block selects
#: ``:root:not([data-spectre-theme="dark"]):not(.spectre-dark):not([data-theme="ops"])``,
#: specificity (0,4,0), which beats themes.css's ``[data-theme="steel"]`` at
#: (0,1,0) however late themes.css loads. Chromium with prefers-color-scheme:
#: light and data-theme="steel" computes --spectre-surface-panel as #E5E7EB,
#: the media block's value, not themes.css's #e0e8f2, so the selected hero tab
#: paints on #D3DEE9 and not on #CEDFEF. Steel is the light briefing-room
#: theme, so prefers-color-scheme: light is the path that matters; under
#: prefers-color-scheme: dark the media block drops out and themes.css's
#: values do survive, which is why the three-step model looked plausible.
_MEDIA_LIGHT = ':root:not([data-spectre-theme="dark"])'
_DARK = _tokens("spectre-theme.css", ":root {")
_STEEL = {
    **_DARK,
    **_tokens("spectre-theme.css", '[data-theme="steel"]'),
    **_tokens("themes.css", '[data-theme="steel"]'),
    **_tokens("spectre-theme.css", _MEDIA_LIGHT),
}

#: The strip the sidebar tabs are painted on. There is no wash here, unlike
#: the hero tab: .stab keeps a transparent background in both themes, so the
#: painted surface IS the strip. In the dark theme .sidebar-tabs declares no
#: background and inherits .sidebar's --surface -> --spectre-surface-raised ->
#: --spectre-color-deep-space; Chromium composites #141820. In steel the
#: themes.css override paints the strip directly and composites #DDE5EF.
_SIDEBAR_TAB_BAR = {
    "dark": _DARK["--spectre-color-deep-space"],
    "steel": _declared("themes.css", '[data-theme="steel"] .sidebar-tabs', "background"),
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


class TestTheSelectedSidebarTab:
    """The same stateful navigation fill one level down, 9.52px bold.

    Chromium computes .stab at 0.68rem on a 14px root, so 9.52px at weight
    700. That is nowhere near the large-text exemption, which starts at
    18.66px when bold, so the floor here is 4.5 and not 3.0.

    Unlike every other class in this module these read the DECLARATIONS, not
    the token table. .stab.active was left naming --spectre-color-intel-blue
    when its twin .htab.active was moved to --spectre-tab-active-text, and
    because the tokens themselves were both correct nothing above this line
    could see it. The steel rule painted #0077cc on #DDE5EF at 3.66:1.
    """

    @pytest.mark.parametrize(("theme", "sheet", "selector", "tokens"), [
        ("dark", "style.css", ".stab.active", _DARK),
        ("steel", "themes.css", '[data-theme="steel"] .stab.active', _STEEL),
    ])
    def test_the_active_sidebar_tab_text_clears_the_floor(
        self, theme: str, sheet: str, selector: str, tokens: dict[str, str]
    ) -> None:
        colour = _resolve(_declared(sheet, selector, "color"), tokens)
        surface = _SIDEBAR_TAB_BAR[theme]
        ratio = _ratio(colour, surface)
        assert ratio >= _AA_NORMAL, (
            f"the {theme} selected sidebar tab is {ratio:.2f}:1 ({colour} on "
            f"{surface}) at a computed 9.52px/700, and it is the state the "
            "operator is acting on"
        )

    @pytest.mark.parametrize(("sheet", "sidebar", "hero"), [
        ("style.css", ".stab.active", ".htab.active"),
        (
            "themes.css",
            '[data-theme="steel"] .stab.active',
            '[data-theme="steel"] .htab.active',
        ),
    ])
    def test_the_sidebar_tab_names_the_same_colour_as_the_hero_tab(
        self, sheet: str, sidebar: str, hero: str
    ) -> None:
        """One control in two places. They drifted apart once already.

        Pinning the pair rather than only the ratio is what stops the next
        retune of the hero tab from leaving the sidebar tab behind again.
        """
        assert _declared(sheet, sidebar, "color") == _declared(sheet, hero, "color"), (
            f"{sidebar} and {hero} in {sheet} are on different colours; the "
            "hero tab was moved off the shared intel blue and the sidebar "
            "tab was left on it at 3.66:1"
        )


class TestTheMinimalBandOnEverySurfaceItLandsOn:
    """The MINIMAL verdict's text, on the surfaces a verdict is drawn on.

    --spectre-status-minimal has exactly one consumer in the repository:
    _BAND_COLOURS in spectre/web/routes/threat.py. It does NOT render as the
    inactive hero tabs or the HRR table headers, which an earlier revision of
    this docstring and of the token's comment both claimed. Those two rules
    are covered by TestTheTokenTheInactiveTabsActuallyRead below, against the
    token the browser resolves for them.
    """

    @pytest.mark.parametrize("surface", [
        "--spectre-color-console-black",
        "--spectre-color-deep-space",
        "--spectre-color-panel-grey",
    ])
    def test_minimal_text_clears_the_floor(self, surface: str) -> None:
        ratio = _ratio(_DARK["--spectre-status-minimal"], _DARK[surface])
        assert ratio >= _AA_NORMAL, (
            f"status-minimal is {ratio:.2f}:1 on {surface}; it renders there as "
            "the MINIMAL verdict's text in a threat sweep row"
        )

    def test_the_rgb_companion_is_the_same_colour_as_the_token(self) -> None:
        """The pair is one colour in two notations, so they must not diverge.

        threat.py builds the row wash from the -rgb form and the row's text
        from the hex form. The raise moved the hex and left the -rgb on the
        old value, which is how a token pair starts meaning two colours.
        """
        text = _STATIC / "spectre-theme.css"
        block = text.read_text(encoding="utf-8")
        start = block.index(":root {")
        root = block[start:block.index("\n}", start)]
        channels = re.search(
            r"--spectre-status-minimal-rgb:\s*(\d+),\s*(\d+),\s*(\d+)\s*;", root
        )
        assert channels is not None
        as_hex = "#{:02X}{:02X}{:02X}".format(*(int(c) for c in channels.groups()))
        assert as_hex == _DARK["--spectre-status-minimal"].upper(), (
            f"--spectre-status-minimal-rgb is {as_hex} but the token it names "
            f"is {_DARK['--spectre-status-minimal']}"
        )


class TestTheTokenTheInactiveTabsActuallyRead:
    """The inactive hero tabs and the HRR table headers, in the dark theme.

    A raise was applied to --spectre-status-minimal and justified, in the
    token's own comment, as fixing "the inactive hero tabs and the HRR table
    headers in the dark theme". It reached neither. .htab (style.css:440),
    .hrr-table th (style.css:896) and .sidebar-collapse-btn (style.css:417)
    all declare var(--spectre-text-secondary), which the dark theme resolves
    to --spectre-color-sensor-grey, and that token was not touched. Measured
    composited in Chromium against the unfixed stylesheet, all three painted
    #7A8BA6 on surface-panel #252B38 at 4.10:1 -- the identical figure the
    comment claimed to have raised to 4.72.

    None of the three reaches the large-text exemption. At the 14px root this
    app sets (style.css:101) they compute to 11.48px/700, 9.10px/700 and
    10.50px/400, all under the 18.66px-bold and 24px thresholds, so the 4.5
    floor governs every one of them.
    """

    #: Each dark surface --spectre-text-secondary was observed painting on in
    #: a Chromium sweep of the console, with the rule that put it there.
    DARK_SURFACES = [
        ("--spectre-color-console-black", ".empty-msg and friends on surface-base"),
        ("--spectre-color-deep-space", ".stab, .nav-user, .hrr-satno on surface-raised"),
        ("--spectre-color-orbital-grey", ".atab on surface-overlay"),
        ("--spectre-color-panel-grey", ".htab, .hrr-table th, .sidebar-collapse-btn"),
    ]

    def test_secondary_text_resolves_to_the_sensor_grey_token(self) -> None:
        """The indirection this whole class depends on.

        If --spectre-text-secondary stops resolving to
        --spectre-color-sensor-grey, every ratio below is measuring a token
        the browser no longer reads, which is the exact failure this module
        exists to catch.
        """
        root = (_STATIC / "spectre-theme.css").read_text(encoding="utf-8")
        start = root.index(":root {")
        block = root[start:root.index("\n}", start)]
        assert re.search(
            r"--spectre-text-secondary:\s*var\(--spectre-color-sensor-grey\)\s*;", block
        ), (
            "the dark theme's --spectre-text-secondary no longer resolves to "
            "--spectre-color-sensor-grey, so the surfaces checked here are "
            "being measured against a token nothing renders"
        )

    @pytest.mark.parametrize(("surface", "where"), DARK_SURFACES)
    def test_secondary_text_clears_the_floor_on_every_dark_surface(
        self, surface: str, where: str
    ) -> None:
        ratio = _ratio(_DARK["--spectre-color-sensor-grey"], _DARK[surface])
        assert ratio >= _AA_NORMAL, (
            f"--spectre-text-secondary is {ratio:.2f}:1 on {surface}, where it "
            f"renders as {where}"
        )

    def test_it_clears_the_floor_on_the_gcat_tab_bar(self) -> None:
        """.gcat-ctab-badge sits on --border over surface-raised, not on a surface.

        style.css:1840 gives the badge ``background: var(--border)``, which is
        --spectre-border-default, a 15% sensor-grey wash. Composited over
        surface-raised that is #232934, and the badge's own label is
        --text-dim. A ratio taken against the bare surface reads better than
        what is on screen.
        """
        wash = _over(
            _DARK["--spectre-color-sensor-grey"], 0.15, _DARK["--spectre-color-deep-space"]
        )
        ratio = _ratio(_DARK["--spectre-color-sensor-grey"], wash)
        assert ratio >= _AA_NORMAL, (
            f".gcat-ctab-badge is {ratio:.2f}:1 on its own border wash {wash}"
        )


class TestTheNeutralBadgeIsNotADarkGreyOnALightSurface:
    """.spectre-badge-neutral was the one rule reading the core palette direct.

    The core palette is never restated per theme, so
    ``color: var(--spectre-color-sensor-grey)`` carried a dark-theme grey onto
    Steel's light surfaces: measured in Chromium on /admin/users it was
    2.90:1 on the user table's row tint (around #E7ECF1) and 3.19:1 on
    #F4F6F8, both below the 4.5 floor at 11px/500, before any raise. The row
    tint moves a shade with the table's striping, so the surfaces below are
    pinned to the band it was observed in rather than to one sample.
    That also made the badge the mirror-image
    hazard of the raise above -- lightening sensor-grey for the dark surfaces
    would have taken those two to 2.54 and 2.77. No single grey serves a dark
    backdrop and a light one, so the badge carries its own themed token.
    """

    #: The light surfaces the badge was observed on, plus the panel surface a
    #: future badge placement would land on.
    LIGHT_SURFACES = ["#E7ECF0", "#F4F6F8", "#E5E7EB", "#FFFFFF"]

    def test_the_rule_does_not_read_the_core_palette_directly(self) -> None:
        css = (_STATIC / "spectre-theme.css").read_text(encoding="utf-8")
        start = css.index(".spectre-badge-neutral {")
        block = css[start:css.index("}", start)]
        assert "--spectre-color-sensor-grey" not in block, (
            ".spectre-badge-neutral reads the core palette directly again; the "
            "core palette has no light-theme value, so the badge will paint a "
            "dark-theme grey onto Steel"
        )
        assert "--spectre-badge-neutral-text" in block

    @pytest.mark.parametrize("block", [
        '.spectre-light,',
        ':root:not([data-spectre-theme="dark"])',
    ])
    def test_every_light_block_restates_the_badge_token(self, block: str) -> None:
        """Both light paths, because the cascade reaches them separately.

        Steel under a light system preference is served by the
        prefers-color-scheme block, which outranks the [data-theme="steel"]
        selector; a page with no data-theme at all is served by it too. A
        value present in only one of the two leaves the other falling back to
        the dark :root grey.
        """
        tokens = _tokens("spectre-theme.css", block)
        assert "--spectre-badge-neutral-text" in tokens, (
            f"the light block at {block!r} does not restate "
            "--spectre-badge-neutral-text, so it inherits the dark theme's"
        )

    @pytest.mark.parametrize("surface", LIGHT_SURFACES)
    def test_the_badge_label_clears_the_floor_on_light_surfaces(self, surface: str) -> None:
        ratio = _ratio(_STEEL["--spectre-badge-neutral-text"], surface)
        assert ratio >= _AA_NORMAL, (
            f"the neutral badge is {ratio:.2f}:1 on {surface} in Steel"
        )

    def test_the_badge_label_clears_the_floor_on_the_dark_wash(self) -> None:
        """The dark theme's badge, on its own 8% sensor-grey wash.

        The raise must not be assumed harmless here just because it lightens
        text on a dark backdrop: the wash lightens with it.
        """
        for surface in ("--spectre-color-deep-space", "--spectre-color-console-black"):
            wash = _over(_DARK["--spectre-color-sensor-grey"], 0.08, _DARK[surface])
            ratio = _ratio(_DARK["--spectre-color-sensor-grey"], wash)
            assert ratio >= _AA_NORMAL, (
                f"the dark neutral badge is {ratio:.2f}:1 on {wash}"
            )


class TestTheGoldCallout:
    """Steel only. The dark theme's gold sits on a dark surface and is fine."""

    @pytest.mark.parametrize("surface", ["#FFFFFF", "#F3F4F6", "#E5E7EB"])
    def test_gold_text_clears_the_floor_on_every_light_surface(self, surface: str) -> None:
        ratio = _ratio(_STEEL["--gold"], surface)
        assert ratio >= _AA_NORMAL, (
            f"--gold is {ratio:.2f}:1 on {surface} in the steel theme"
        )


class TestTheSteelModelMatchesWhatChromiumPaints:
    """The merge above has to end on the media block, not on themes.css.

    Every figure in this module for the steel theme is taken from _STEEL, so
    if _STEEL models the wrong cascade the figures are pinned to surfaces that
    are not on screen. These are the values Chromium computes for
    data-theme="steel" under prefers-color-scheme: light, read back off the
    live console. Drop the fourth merge step and five of the six move, as
    does the tab wash below. Only --spectre-surface-raised is white on both
    sides of the question.
    """

    #: token -> computed value, Chromium, steel + prefers-color-scheme: light.
    _PAINTED = {
        "--spectre-surface-base": "#F3F4F6",
        "--spectre-surface-raised": "#FFFFFF",
        "--spectre-surface-overlay": "#FFFFFF",
        "--spectre-surface-panel": "#E5E7EB",
        "--spectre-text-primary": "#111827",
        "--spectre-text-secondary": "#4B5563",
    }

    @pytest.mark.parametrize(("token", "painted"), sorted(_PAINTED.items()))
    def test_the_modelled_surface_is_the_painted_surface(
        self, token: str, painted: str
    ) -> None:
        modelled = _STEEL[token].upper()
        assert modelled == painted.upper(), (
            f"{token} models as {modelled} but Chromium paints {painted} for "
            "steel under prefers-color-scheme: light; the media block at "
            "(0,4,0) beats themes.css at (0,1,0) whatever the load order"
        )

    def test_the_selected_tab_wash_is_the_one_on_screen(self) -> None:
        """#D3DEE9, not themes.css's #CEDFEF."""
        wash = _over(_STEEL["--spectre-color-intel-blue"], 0.08,
                     _STEEL["--spectre-surface-panel"])
        assert wash == "#D3DEE9", (
            f"the steel tab wash models as {wash}; Chromium composites "
            "#D3DEE9 from an 8% intel-blue over the media block's #E5E7EB"
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


# ══════════════════════════════════════════════════════════════════════════
# Gold is two jobs in the steel theme, and each rule has to name the right one
# ══════════════════════════════════════════════════════════════════════════

_AA_LARGE = 3.0

#: style.css carries a :root of its own holding the Bluestaq brand palette
#: (--navy, --navy-deep, --gold, --gold-chrome). _DARK and _STEEL above are
#: built from spectre-theme.css and do not contain it, so it is merged in
#: underneath here. themes.css still wins for steel, which is the order the
#: browser applies.
_BRAND = _tokens("style.css", ":root {")
_DARK_BRAND = {**_BRAND, **_DARK}
_STEEL_BRAND = {**_BRAND, **_STEEL}


def _rule_block(filename: str, selector: str) -> str:
    """The body of *selector*'s OWN rule.

    Anchored on the opening brace rather than a plain substring search, which
    finds the wrong rule: ".gcat-search" occurs first inside ".gcat-search-box",
    and reading that block would have this measure a rule nobody renders.
    """
    text = (_STATIC / filename).read_text(encoding="utf-8")
    head = re.search(re.escape(selector) + r"\s*\{", text)
    assert head, f"{selector} is no longer a rule of its own in {filename}"
    opening = head.end() - 1
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


def _declared_var(selector: str, prop: str, filename: str = "style.css") -> str:
    """The custom property *selector*'s own rule gives to *prop*.

    This reads the rule the browser obeys rather than naming a token and
    hoping. A token pinned by a test is worth nothing if the rendered rule
    names a different one, and that is exactly what happened here: --gold was
    darkened for .callout-gold and went on passing its own 4.5 floor on white,
    while .etab.active, which also reads --gold, was painting it on
    --navy-deep at 2.74:1 with nothing watching.
    """
    block = _rule_block(filename, selector)
    pattern = r"(?<![-\w])" + re.escape(prop) + r"\s*:\s*var\((--[a-z0-9-]+)\)"
    match = re.search(pattern, block)
    assert match, f"{selector} no longer sets {prop} from a custom property"
    return match.group(1)


#: Every rule that paints gold onto chrome both themes deliberately keep dark.
#: Each entry carries the HOST whose background it lands on, and the host's own
#: rule is re-read for the surface token, so moving a bar off --navy-deep is
#: reported rather than quietly measured against a surface no longer in use.
#:
#: (rule, property, host rule, floor, what it is)
_GOLD_ON_NAVY = [
    (".etab.active", "color", ".engine-tab-bar", _AA_NORMAL,
     "the selected engine sub-tab at 10.08px/700, the state an operator is acting on"),
    (".etab.active", "border-bottom-color", ".engine-tab-bar", _AA_LARGE,
     "its 2px underline, the non-text half of that same state"),
    (".ltab.active", "color", ".lower-tab-bar", _AA_NORMAL,
     "the selected lower tab at 9.8px/700"),
    (".mnv-table th:hover:not(.no-sort)", "color", ".mnv-table th", _AA_NORMAL,
     "the manoeuvre-table sort affordance at 10.4px/700"),
    (".threat-child-header th:hover:not(.no-sort)", "color", ".threat-child-header th",
     _AA_NORMAL, "the child-row sort affordance at 9.6px/700"),
    (".gcat-brand-glyph", "color", ".gcat-header", _AA_LARGE,
     "the GCAT brand mark, a 24px glyph and so a 3.0 case"),
    (".gcat-brand-credit a:hover", "color", ".gcat-header", _AA_NORMAL,
     "the hovered credit link at 8.4px/400 on that same dark header"),
    (".gcat-ds-btn.active", "color", ".gcat-nav", _AA_NORMAL,
     "the selected dataset at 11.2px/600 on the dark nav rail"),
    (".gcat-ds-btn.active", "border-left-color", ".gcat-nav", _AA_LARGE,
     "its 3px selection marker"),
    (".gcat-search:focus", "border-color", ".gcat-search", _AA_LARGE,
     "the only focus indicator on the GCAT search field, which sets outline: none"),
]


class TestGoldOnTheChromeBothThemesKeepDark:
    """Steel lightens the panels and leaves the navy chrome alone.

    A gold dark enough to be read on white is not readable on #0f1e2e, and the
    two requirements do not overlap: clearing 4.5:1 on #0f1e2e needs a relative
    luminance of at least 0.236, clearing 4.5:1 on white needs at most 0.183.
    So the chrome gets --gold-chrome and the light surfaces keep --gold, the
    same carve-out --spectre-tab-active-text made for the hero tabs.
    """

    @pytest.mark.parametrize(("rule", "prop", "host", "floor", "what"), _GOLD_ON_NAVY)
    @pytest.mark.parametrize(("theme", "tokens"), [("dark", _DARK_BRAND), ("steel", _STEEL_BRAND)])
    def test_the_token_the_rule_names_clears_the_floor_on_its_own_bar(
        self, theme: str, tokens: dict[str, str],
        rule: str, prop: str, host: str, floor: float, what: str,
    ) -> None:
        surface_token = _declared_var(host, "background")
        assert surface_token in ("--navy", "--navy-deep"), (
            f"{host} is no longer a navy bar but {surface_token}; this table "
            "measures against the wrong surface until it is updated"
        )
        ink = tokens[_declared_var(rule, prop)]
        surface = tokens[surface_token]
        ratio = _ratio(ink, surface)
        assert ratio >= floor, (
            f"{rule} {{{prop}}} is {ratio:.2f}:1 ({ink} on {surface}) in the "
            f"{theme} theme against a {floor} floor. It is {what}."
        )

    def test_the_pagination_chip_can_still_carry_navy_ink(self) -> None:
        """.gcat-pgn-cur is the inverse case: --navy-deep ink ON the gold.

        Darkening --gold darkened the fill under that ink rather than the ink
        on a fill, so it failed in the same release for the opposite reason,
        at 2.74:1 with 10.72px/800 type on it.
        """
        for theme, tokens in (("dark", _DARK_BRAND), ("steel", _STEEL_BRAND)):
            fill = tokens[_declared_var(".gcat-pgn-cur", "background")]
            ink = tokens[_declared_var(".gcat-pgn-cur", "color")]
            ratio = _ratio(ink, fill)
            assert ratio >= _AA_NORMAL, (
                f"the {theme} current-page chip is {ratio:.2f}:1 ({ink} on {fill})"
            )


class TestNoGoldDerivedValueIsSplitFromItsParent:
    """The alpha ladder has to be restated whenever --gold is.

    --gold was darkened to #8A5600 for .callout-gold and --gold-dim, --gold-mid
    and the whole --gold-aNN ladder were left compositing rgba(160, 122, 0). So
    .threat-high tinted itself one gold and printed its delta-V in another, and
    the 6.16:1 claimed for .callout-gold had been measured against a wash mixed
    from the colour --gold no longer was.
    """

    @staticmethod
    def _rgb_of_hex(value: str) -> tuple[int, int, int]:
        raw = value.lstrip("#")
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)

    @staticmethod
    def _gold_rgba_tokens(selector: str) -> dict[str, tuple[int, int, int]]:
        block = _rule_block("themes.css", selector)
        found = re.findall(
            r"(--gold[a-z0-9-]*)\s*:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,",
            block,
        )
        return {name: (int(r), int(g), int(b)) for name, r, g, b in found}

    def test_every_steel_gold_tint_carries_the_rgb_of_steel_gold(self) -> None:
        parent = self._rgb_of_hex(_STEEL["--gold"])
        tints = self._gold_rgba_tokens('[data-theme="steel"]')
        assert len(tints) >= 10, (
            "the steel gold ladder has shrunk to "
            f"{sorted(tints)}; this test is no longer covering it"
        )
        split = {name: rgb for name, rgb in tints.items() if rgb != parent}
        assert not split, (
            f"--gold is {_STEEL['--gold']} = rgb{parent} in the steel theme but "
            f"{len(split)} gold-derived token(s) composite a different hue: "
            + ", ".join(f"{n} = rgb{v}" for n, v in sorted(split.items()))
        )
