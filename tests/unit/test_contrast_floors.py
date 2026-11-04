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

from tests.unit._css import over as _over
from tests.unit._css import ratio as _ratio

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








def _sole_rule_block(filename: str, selector: str) -> str:
    """The declarations inside the one rule whose selector is *selector*.

    Named apart from the looser ``_rule_block`` further down, which used to
    share this name and silently replace it for every call made after the
    module loaded (audit F-274).

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
    block = _sole_rule_block(filename, selector)
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


class TestTheReadersSeeAPlantedFailure:
    """SPC-074: the stylesheet readers, run on a sheet planted with a pair below the floor.

    The arithmetic above is half of every check here; the other half is
    reading the right declaration out of the right block. Each reader joins
    its filename to the static directory, and an absolute path joined that way
    is the path itself, so the planted sheet is read by the same code.
    """

    _SHEET = (
        ":root {\n  --pale: #9AA5B1;\n  --page: #FFFFFF;\n}\n"
        ".light {\n  --pale: #222222;\n}\n"
        ".htab.active { color: var(--pale); }\n"
        ".htab.active::after { color: #000000; }\n"
        "/* .htab.active { color: #000000; } quoted in prose, not a rule */\n"
    )

    def test_a_rule_naming_a_pale_token_measures_below_the_floor(self, tmp_path: Path) -> None:
        sheet = tmp_path / "planted.css"
        sheet.write_text(self._SHEET, encoding="utf-8")
        tokens = _tokens(str(sheet), ":root {")
        # Block-aware: the :root value, not the later .light one.
        assert tokens == {"--pale": "#9AA5B1", "--page": "#FFFFFF"}
        colour = _resolve(_declared(str(sheet), ".htab.active", "color"), tokens)
        assert colour == "#9AA5B1"
        assert _ratio(colour, tokens["--page"]) < _AA_NORMAL

    def test_a_second_rule_for_the_selector_is_refused_rather_than_guessed(self, tmp_path: Path) -> None:
        sheet = tmp_path / "twice.css"
        sheet.write_text(self._SHEET + ".htab.active { color: #000000; }\n", encoding="utf-8")
        with pytest.raises(AssertionError, match="exactly one"):
            _sole_rule_block(str(sheet), ".htab.active")

    @pytest.mark.parametrize(("value", "said"), [
        ("var(--absent)", "carries no hex value"), ("rgb(1, 2, 3)", "cannot resolve"), ("#FFF", "cannot resolve"),
    ])
    def test_a_colour_it_cannot_resolve_is_refused_rather_than_measured(self, value: str, said: str) -> None:
        with pytest.raises(AssertionError, match=said):
            _resolve(value, {"--page": "#FFFFFF"})


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


def _aliases(filename: str, selector: str) -> dict[str, str]:
    """The ``--token: var(--other);`` declarations in *selector*'s own rule."""
    block = _rule_block(filename, selector)
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*var\(\s*(--[a-z0-9-]+)\s*\)\s*;", block))


#: The dark theme's alias chains: style.css's --text-dim names
#: --spectre-text-secondary, which spectre-theme.css's :root names
#: --spectre-color-sensor-grey, which carries the hex.
_DARK_ALIASES = {**_aliases("style.css", ":root"), **_aliases("spectre-theme.css", ":root")}


def _chase(name: str, tokens: dict[str, str], aliases: dict[str, str]) -> str:
    """The hex *name* paints, following ``var()`` aliases until one carries a value."""
    seen: set[str] = set()
    while name not in tokens:
        assert name in aliases and name not in seen, f"{name} resolves to no colour in this theme"
        seen.add(name)
        name = aliases[name]
    return tokens[name]


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


class TestTheAdminPageNamesItsColoursOnce:
    """SPC-029: the user admin page named six tokens no sheet defines.

    Each fell back to the inherited value, so the admin badge was plain row
    text and the success flash was body text. They now name existing tokens,
    and the two that put ink on a fill are measured here in both themes and,
    for Steel, on both of its surface sets (see _STEEL above): themes.css's
    #e8eef5 overlay is what a browser preferring dark paints.
    """

    _ADMIN = _STATIC.parent / "templates" / "partials"

    @pytest.mark.parametrize(("theme", "fill", "ink"), [
        ("dark", _DARK["--spectre-color-intel-blue"], _DARK["--spectre-color-deep-space"]),
        ("steel", _STEEL["--spectre-color-intel-blue"], _STEEL["--spectre-surface-raised"]),
    ])
    def test_the_admin_badge_ink_clears_the_floor_on_its_fill(
        self, theme: str, fill: str, ink: str
    ) -> None:
        row = (self._ADMIN / "admin_user_row.html").read_text(encoding="utf-8")
        assert "background:var(--spectre-color-intel-blue); color:var(--spectre-surface-raised)" in row
        ratio = _ratio(ink, fill)
        assert ratio >= _AA_NORMAL, f"the {theme} admin badge is {ratio:.2f}:1, {ink} on {fill}"

    def test_the_success_flash_names_no_retired_green(self) -> None:
        """Its contrast is measured by TestTheAdminPageNamesOnlyStyledClasses.

        SPC-029 measured the flash text on the bare card overlay, which was
        right while the card named a class nothing styled. SPC-034 gave the
        card its nominal wash, so the surface moved and the measurement moved
        with it, to the composited wash over the page.
        """
        for template in (self._ADMIN / "admin_flash.html", self._ADMIN.parent / "admin" / "users.html"):
            assert "custody-green" not in template.read_text(encoding="utf-8"), template.name

    def test_the_header_caption_takes_the_console_user_label_colour(self) -> None:
        """The signed-in caption sits on .nav-bar, which Steel keeps dark.

        It named --spectre-color-text-muted and so inherited Steel's dark body
        ink (#111827 or #1c2b3a) onto #1a2a3a. No theme token serves that bar in both
        themes, which is why .nav-user carries a Steel override; the caption
        is the same label as the console's .nav-user, so it takes that class.
        """
        page = (_STATIC.parent / "templates" / "admin" / "users.html").read_text(encoding="utf-8")
        caption = re.search(r'<span class="([^"]*)"([^>]*)>\s*\{\{ current_user\.username \}\}', page)
        assert caption, "the admin header caption has moved"
        assert "nav-user" in caption.group(1).split()
        assert "color:" not in caption.group(2), "an inline colour outranks the Steel .nav-user override"
        bar = _declared("themes.css", '[data-theme="steel"] .nav-bar', "background")
        ink = _declared("themes.css", '[data-theme="steel"] .nav-user', "color")
        ratio = _ratio(ink, bar)
        assert ratio >= _AA_NORMAL, f"the Steel caption is {ratio:.2f}:1, {ink} on {bar}"
        dark_bar = _chase(_declared_var(".nav-bar", "background"), _DARK_BRAND, _DARK_ALIASES)
        dark_ink = _chase(_declared_var(".nav-user", "color"), _DARK_BRAND, _DARK_ALIASES)
        ratio = _ratio(dark_ink, dark_bar)
        assert ratio >= _AA_NORMAL, f"the dark caption is {ratio:.2f}:1, {dark_ink} on {dark_bar}"


# ══════════════════════════════════════════════════════════════════════════
# SPC-034: the admin nav bar's ghost buttons, and the flash class nothing styled
# ══════════════════════════════════════════════════════════════════════════

def _uncommented(filename: str) -> str:
    return re.sub(r"/\*.*?\*/", "", (_STATIC / filename).read_text(encoding="utf-8"), flags=re.S)


def _on_screen(filename: str) -> str:
    """*filename* uncommented, less its ``@media print`` blocks, which never paint the console."""
    return re.sub(r"@media print\s*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", _uncommented(filename))


def _raw_tokens(filename: str, selector: str) -> dict[str, str]:
    """Every ``--token: value;`` in *selector*'s own block, values verbatim.

    ``_tokens`` keeps only hex values. The ghost button's hover fill in the
    dark theme is ``rgba(255, 255, 255, 0.07)`` and a card variant's fill is
    an 8% wash in every theme, so measuring either needs the raw value and
    the alias chain that leads to it. Token blocks hold no nested braces, so
    the first closing brace ends the block.
    """
    text = _uncommented(filename)
    start = text.find(selector)
    if start < 0:
        return {}
    opening = text.index("{", start)
    body = text[opening + 1:text.index("}", opening)]
    return {name: value.strip() for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body)}


#: The three token sets the admin page is painted with. Steel has two (see
#: _STEEL above): the media block wins under prefers-color-scheme: light and
#: drops out under prefers dark, leaving themes.css's values.
_RAW_DARK = {**_raw_tokens("style.css", ":root {"), **_raw_tokens("spectre-theme.css", ":root {")}
_RAW_STEEL_PREFERS_DARK = {
    **_RAW_DARK,
    **_raw_tokens("spectre-theme.css", '[data-theme="steel"]'),
    **_raw_tokens("themes.css", '[data-theme="steel"]'),
}
_RAW_STEEL = {**_RAW_STEEL_PREFERS_DARK, **_raw_tokens("spectre-theme.css", _MEDIA_LIGHT)}
_RAW_THEMES = [
    ("dark", _RAW_DARK),
    ("steel", _RAW_STEEL),
    ("steel, prefers dark", _RAW_STEEL_PREFERS_DARK),
]


def _follow(value: str, raw: dict[str, str]) -> str:
    """*value* with every ``var(--x)`` replaced by what *raw* gives ``--x``."""
    seen: set[str] = set()
    while reference := re.fullmatch(r"var\(\s*(--[a-z0-9-]+)\s*\)", value.strip()):
        name = reference.group(1)
        assert name in raw and name not in seen, f"{name} resolves to no value in this theme"
        seen.add(name)
        value = raw[name]
    return value.strip()


def _paint(value: str, under: str) -> str:
    """What a resolved colour value paints over *under*, as ``#RRGGBB``."""
    if value == "transparent":
        return under
    rgba = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value)
    if rgba:
        red, green, blue, alpha = rgba.groups()
        return _over(f"#{int(red):02X}{int(green):02X}{int(blue):02X}", float(alpha), under)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"cannot paint {value!r}"
    return value.upper()


def _rule_listing(filename: str, selector: str) -> str | None:
    """The block of the one rule that lists *selector*, alone or in a selector list.

    ``a:hover`` shares its rule with ``.spectre-link:hover``, so matching the
    whole selector text would miss it. None when no rule lists it, which is
    how the unfixed sheet is measured.
    """
    blocks = [
        body
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _on_screen(filename))
        if selector in (member.strip() for member in head.split(","))
    ]
    assert len(blocks) <= 1, f"{len(blocks)} rules in {filename} list `{selector}`"
    return blocks[0] if blocks else None


def _first_declared(candidates: list[tuple[str, str]], prop: str) -> str:
    """*prop* from the most specific rule in *candidates* that sets it.

    Candidates are listed most specific first, so the first rule that exists
    and declares *prop* is the one the browser obeys. An absent rule is
    skipped: with no Steel override the ghost button falls through to
    ``.spectre-btn``.
    """
    for filename, selector in candidates:
        block = _rule_listing(filename, selector) or ""
        match = re.search(rf"(?<![-\w]){re.escape(prop)}\s*:\s*([^;}}]+)", block)
        if match:
            return match.group(1).strip()
    raise AssertionError(f"no rule in {candidates} declares {prop}")


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes with attributes and pseudo-classes, types) for *selector*."""
    bare = re.sub(r"\[[^\]]*\]", "[]", selector)
    middle = bare.count("[]") + len(re.findall(r"\.[\w-]+", bare)) + len(re.findall(r"(?<!:):[\w-]+", bare))
    return bare.count("#"), middle, len(re.findall(r"(?:^|[\s>+~])[a-z][\w-]*", bare))


_STEEL_GHOST = '[data-theme="steel"] .nav-bar .spectre-btn-ghost'

#: Every rule that can paint an admin nav ghost button's ink or fill:
#: (stylesheet, selector, Steel only, hover only, element only). The link
#: rules reach Console, an <a>; ``a:hover`` (0,1,1) outranks ``.spectre-btn``
#: (0,1,0) for colour, and ``.spectre-btn:hover`` sets none.
_GHOST_CASCADE = [
    ("themes.css", f"{_STEEL_GHOST}:hover", True, True, None),
    ("themes.css", _STEEL_GHOST, True, False, None),
    ("spectre-theme.css", ".spectre-btn:hover", False, True, None),
    ("spectre-theme.css", ".spectre-btn", False, False, None),
    ("spectre-theme.css", "a:hover", False, True, "a"),
    ("spectre-theme.css", "a", False, False, "a"),
]


def _ghost_rules(theme: str, hover: bool, element: str) -> list[tuple[str, str]]:
    """The rules that reach this ghost button, most specific first.

    A tie would be settled by source order, which this does not model, so it
    refuses one rather than guess.
    """
    rules = [
        (filename, selector)
        for filename, selector, steel_only, hover_only, only in _GHOST_CASCADE
        if (theme.startswith("steel") or not steel_only) and (hover or not hover_only) and only in (None, element)
    ]
    ranks = [_specificity(selector) for _, selector in rules]
    assert len(set(ranks)) == len(ranks), f"rules of equal specificity reach the ghost button: {rules}"
    return [rule for _, rule in sorted(zip(ranks, rules, strict=True), reverse=True)]


def _nav_bar(theme: str, raw: dict[str, str]) -> str:
    """The bar the admin nav actions sit on. Steel keeps it dark in themes.css."""
    if theme == "dark":
        return _paint(_follow(f"var({_declared_var('.nav-bar', 'background')})", raw), "#000000")
    return _paint(_declared("themes.css", '[data-theme="steel"] .nav-bar', "background"), "#000000")


class TestTheAdminNavGhostButtons:
    """SPC-034: ``Console`` and ``Sign Out`` on /admin/users, 14px/500.

    Both are ``.spectre-btn .spectre-btn-ghost`` in the nav_actions block,
    which base.html places inside ``nav.nav-bar``. Steel keeps that bar dark
    (#1a2a3a, a Bluestaq identity requirement) but nothing re-pointed the
    ghost button's label, so it took ``.spectre-btn``'s
    var(--spectre-text-primary): Steel's DARK body ink on the dark bar, at
    1.21:1 (#111827) under prefers-color-scheme: light and 1.01:1 (#1c2b3a)
    under prefers dark. The dark theme is measured too, so the Steel fix is
    seen not to move it.
    """

    def test_the_admin_nav_actions_are_ghost_buttons_on_the_nav_bar(self) -> None:
        """What is measured below is what the page renders."""
        templates = _STATIC.parent / "templates"
        base = (templates / "base.html").read_text(encoding="utf-8")
        assert re.search(r'<nav class="nav-bar">.*\{% block nav_actions %\}.*</nav>', base, re.S)
        page = (templates / "admin" / "users.html").read_text(encoding="utf-8")
        start = page.index("{% block nav_actions %}")
        actions = page[start:page.index("{% endblock %}", start)]
        ghosts = re.findall(r'<(\w+)\b[^>]*class="spectre-btn spectre-btn-ghost"', actions)
        assert ghosts == ["a", "button"], f"the nav ghost controls are {ghosts}, not Console <a> and Sign Out <button>"

    @pytest.mark.parametrize("hover", [False, True], ids=["rest", "hover"])
    @pytest.mark.parametrize("element", ["a", "button"], ids=["console", "sign-out"])
    @pytest.mark.parametrize(("theme", "raw"), _RAW_THEMES)
    def test_the_ghost_label_clears_the_floor_on_the_nav_bar(
        self, theme: str, raw: dict[str, str], element: str, hover: bool
    ) -> None:
        rules = _ghost_rules(theme, hover, element)
        surface = _paint(_follow(_first_declared(rules, "background"), raw), _nav_bar(theme, raw))
        ink = _paint(_follow(_first_declared(rules, "color"), raw), surface)
        ratio = _ratio(ink, surface)
        state = "hovered" if hover else "resting"
        assert ratio >= _AA_NORMAL, (
            f"the {theme} {state} admin nav ghost <{element}> is {ratio:.2f}:1, "
            f"{ink} on {surface}, at 14px/500 against a 4.5 floor"
        )


_TEMPLATES = _STATIC.parent / "templates"
_ADMIN_TEMPLATES = sorted((_TEMPLATES / "admin").glob("*.html")) + sorted(
    (_TEMPLATES / "partials").glob("admin_*.html")
)


def _class_names(page: Path) -> set[str]:
    """Every class *page* names, both branches of a Jinja conditional included."""
    attributes = re.findall(r'class="([^"]*)"', page.read_text(encoding="utf-8"))
    return {name for attribute in attributes for name in re.sub(r"\{[%{].*?[%}]\}", " ", attribute).split()}


#: Classes an admin template names for meaning rather than looks. Each needs
#: a test that answers for it; spectre-btn-ghost's is
#: test_a_ghost_button_is_unfilled_by_spectre_btn_itself.
_MARKER_CLASSES = {"spectre-btn-ghost"}

#: A compound that roots a whole theme rather than scoping a region of the page.
_THEME_ROOT = re.compile(r"(?::root|html|\[data-theme=\"[\w-]+\"\])(?::not\([^)]*\))*")


def _selectors() -> list[str]:
    """Every on-screen selector in every stylesheet, selector lists split apart."""
    heads = (
        head
        for sheet in sorted(_STATIC.rglob("*.css"))
        for head in re.findall(r"([^{}]+)\{[^{}]*\}", _on_screen(sheet.relative_to(_STATIC).as_posix()))
    )
    return [member.strip() for head in heads for member in head.split(",")]


def _classes_styled_everywhere() -> set[str]:
    """Classes named in the key compound of a selector with no ancestor but a theme root."""
    styled: set[str] = set()
    for selector in _selectors():
        *ancestors, key = re.split(r"\s*[\s>+~]\s*", selector)
        if all(_THEME_ROOT.fullmatch(ancestor) for ancestor in ancestors):
            styled.update(re.findall(r"\.([\w-]+)", key))
    return styled


class TestTheAdminPageNamesOnlyStyledClasses:
    """SPC-034: the success flash named ``spectre-card-custody``.

    No stylesheet defines it, so the card fell back to the plain
    ``.spectre-card`` and a success looked like any other card. The card
    variants are threat, caution, nominal and info; a successful admin action
    is nominal, the twin of the error branch's threat.
    """

    def test_every_class_an_admin_template_names_is_styled(self) -> None:
        """Styled wherever it appears, not merely named in some selector.

        A rule scoped under an ancestor, such as Steel's ``.nav-bar
        .spectre-btn-ghost``, cannot reach the same class in a table row, so
        only a rule whose sole ancestor is a theme root counts here.
        """
        styled = _classes_styled_everywhere() | _MARKER_CLASSES
        missing = sorted(
            f"{page.name}: {name}"
            for page in _ADMIN_TEMPLATES
            for name in _class_names(page)
            if name not in styled
        )
        assert not missing, f"admin templates name classes no rule styles wherever they appear: {missing}"

    def test_a_ghost_button_is_unfilled_by_spectre_btn_itself(self) -> None:
        """What lets ``spectre-btn-ghost`` stand as a marker in _MARKER_CLASSES.

        The table rows' Edit, Delete and Cancel carry it, and no rule reaches
        them: they look unfilled because ``.spectre-btn`` already is. The only
        rules that name it are Steel's, scoped to the nav bar, where
        TestTheAdminNavGhostButtons measures them. Should an unscoped ghost
        rule ever arrive, this fails, and the marker entry should go.
        """
        assert _declared("spectre-theme.css", ".spectre-btn", "background") == "transparent"
        naming = [selector for selector in _selectors() if re.search(r"\.spectre-btn-ghost(?![\w-])", selector)]
        assert naming, "no rule names .spectre-btn-ghost, so the Steel nav bar fix has gone"
        stray = [selector for selector in naming if not selector.startswith(_STEEL_GHOST)]
        assert not stray, f"rules reach .spectre-btn-ghost outside the Steel nav bar: {stray}"

    @pytest.mark.parametrize("template", ["admin/users.html", "partials/admin_flash.html"])
    def test_a_successful_admin_action_flashes_the_nominal_card(self, template: str) -> None:
        """Success is nominal and failure is threat, whichever template renders it.

        Being styled is not enough: the info card is styled too, and a success
        drawn in the information blue would pass every contrast test here.
        """
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        branches = re.search(
            r"\{% if flash\.type == 'error' %\}([\w-]+)\{% else %\}([\w-]+)\{% endif %\}", text
        )
        assert branches, f"the flash card's class in {template} has moved"
        assert branches.groups() == ("spectre-card-threat", "spectre-card-nominal"), (
            f"the flash in {template} is {branches.group(1)} on error and {branches.group(2)} on success"
        )

    @pytest.mark.parametrize("template", ["admin/users.html", "partials/admin_flash.html"])
    @pytest.mark.parametrize(("theme", "raw"), _RAW_THEMES)
    def test_the_success_flash_text_clears_the_floor_on_its_own_card(
        self, theme: str, raw: dict[str, str], template: str
    ) -> None:
        """The flash text on the card's own fill, composited over the page.

        A card variant replaces .spectre-card's overlay with a translucent
        wash, so the surface under the text is that wash over the page's
        --bg, which html and body paint (style.css).
        """
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        card = re.search(r"spectre-card-threat\{% else %\}(spectre-card-[\w-]+)\{% endif %\}", text)
        colour = re.search(r"\{% else %\}(var\(--[\w-]+\))\{% endif %\}", text)
        assert card and colour, f"the success flash in {template} has moved"
        page = _paint(_follow(_declared("style.css", "html, body", "background"), raw), "#000000")
        wash = _first_declared([("spectre-theme.css", f".{card.group(1)}")], "background")
        fill = _paint(_follow(wash, raw), page)
        ink = _paint(_follow(colour.group(1), raw), fill)
        ratio = _ratio(ink, fill)
        assert ratio >= _AA_NORMAL, (
            f"the {theme} success flash in {template} is {ratio:.2f}:1, {ink} on {fill}"
        )


# ══════════════════════════════════════════════════════════════════════════
# SPC-035: the error flash, the Steel Logout hover, and the Steel bar's focus ring
# ══════════════════════════════════════════════════════════════════════════

_FLASH_TEMPLATES = ["admin/users.html", "partials/admin_flash.html"]


def _error_flash(template: str) -> tuple[str, str]:
    """The error branch's card class and text colour in *template*."""
    text = (_TEMPLATES / template).read_text(encoding="utf-8")
    card = re.search(r"\{% if flash\.type == 'error' %\}(spectre-card-[\w-]+)\{% else %\}", text)
    colour = re.search(r"\{% if flash\.type == 'error' %\}(var\(--[\w-]+\))\{% else %\}", text)
    assert card and colour, f"the error flash in {template} has moved"
    return card.group(1), colour.group(1)


class TestTheErrorFlash:
    """SPC-035: the error branch of the admin flash, the twin of SPC-034's success.

    It painted the shared --spectre-color-threat-red on the threat card's 8%
    wash. Steel's #c0392b measured 4.41:1 over #F3F4F6 and 4.39:1 over
    #f0f4f8, the two Steel page surfaces, at 12px/400 against a 4.5 floor.
    The shared red cannot simply be darkened: it is also the fill under the
    white label of .spectre-btn-threat, so the text gets a token of its own,
    as --spectre-color-nominal-green-text did for the success branch.
    """

    @pytest.mark.parametrize("template", _FLASH_TEMPLATES)
    def test_the_error_flash_names_its_own_text_token(self, template: str) -> None:
        card, colour = _error_flash(template)
        assert card == "spectre-card-threat"
        assert colour == "var(--spectre-color-threat-red-text)", (
            f"the error flash in {template} paints {colour}; the shared threat red "
            "is a fill as well, so the text needs its own token"
        )

    @pytest.mark.parametrize("template", _FLASH_TEMPLATES)
    def test_the_message_is_the_measured_paragraph_s_own_text(self, template: str) -> None:
        """The colour measured below is the one the message is painted in.

        Markup between the paragraph and the message could paint it another
        colour, out of sight of the measurement.
        """
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        paragraph = re.search(r"<p style=\"[^\"]*flash\.type == 'error'[^\"]*\">(.*?)</p>", text, re.S)
        assert paragraph, f"the flash paragraph in {template} has moved"
        assert paragraph.group(1).strip() == "{{ flash.message }}", (
            f"the flash message in {template} is wrapped in {paragraph.group(1).strip()!r}, "
            "so the colour measured is not necessarily the colour it is painted in"
        )

    @pytest.mark.parametrize("block", [".spectre-light,", _MEDIA_LIGHT])
    def test_every_light_block_restates_the_error_text_token(self, block: str) -> None:
        """Both light paths, for the reason given for the neutral badge above."""
        assert "--spectre-color-threat-red-text" in _tokens("spectre-theme.css", block), (
            f"the light block at {block!r} does not restate "
            "--spectre-color-threat-red-text, so it inherits the dark theme's red"
        )

    @pytest.mark.parametrize("template", _FLASH_TEMPLATES)
    @pytest.mark.parametrize(("theme", "raw"), _RAW_THEMES)
    def test_the_error_flash_text_clears_the_floor_on_its_own_card(
        self, theme: str, raw: dict[str, str], template: str
    ) -> None:
        card, colour = _error_flash(template)
        page = _paint(_follow(_declared("style.css", "html, body", "background"), raw), "#000000")
        wash = _first_declared([("spectre-theme.css", f".{card}")], "background")
        fill = _paint(_follow(wash, raw), page)
        ink = _paint(_follow(colour, raw), fill)
        ratio = _ratio(ink, fill)
        assert ratio >= _AA_NORMAL, (
            f"the {theme} error flash in {template} is {ratio:.2f}:1, {ink} on {fill}"
        )


def _load_order() -> list[str]:
    """The stylesheets base.html links, in the order the browser applies them."""
    base = (_TEMPLATES / "base.html").read_text(encoding="utf-8")
    links = re.findall(r'<link rel="stylesheet" href="([^"]+)"', base)
    return [href.removeprefix("/static/") for href in links]


#: Every rule that paints the console's Logout: (stylesheet, selector, Steel
#: only, hover only).
_LOGOUT_CASCADE = [
    ("themes.css", '[data-theme="steel"] .btn-logout:hover', True, True),
    ("themes.css", '[data-theme="steel"] .btn-logout', True, False),
    ("style.css", ".btn-logout:hover", False, True),
    ("style.css", ".btn-logout", False, False),
]


def _logout_rules(theme: str, hover: bool) -> list[tuple[str, str]]:
    """The rules that reach Logout, most specific first, ties to the later sheet.

    This is the tie _ghost_rules refuses to settle, and here it decides the
    answer: ``[data-theme="steel"] .btn-logout`` and ``.btn-logout:hover`` are
    both (0,2,0), and base.html loads themes.css after style.css, so under
    the pointer the Steel resting rule still wins and Logout does not change.
    """
    order = _load_order()
    rules = [
        (filename, selector)
        for filename, selector, steel_only, hover_only in _LOGOUT_CASCADE
        if (theme.startswith("steel") or not steel_only) and (hover or not hover_only)
    ]
    return sorted(rules, key=lambda rule: (_specificity(rule[1]), order.index(rule[0])), reverse=True)


def _on_the_bar(rules: list[tuple[str, str]], theme: str, raw: dict[str, str]) -> tuple[str, str]:
    """(ink, surface) that *rules* paint on the nav bar."""
    surface = _paint(_follow(_first_declared(rules, "background"), raw), _nav_bar(theme, raw))
    return _paint(_follow(_first_declared(rules, "color"), raw), surface), surface


class TestTheSteelLogoutHover:
    """SPC-035: the console's Logout, 10.08px/500 on the nav bar Steel keeps dark.

    Measured, Steel's hovered Logout read 7.12:1, #a0b8cc on #1a2a3a, but
    only because it was the resting state: the Steel rule ties
    ``.btn-logout:hover`` on specificity and loads later, so the pointer
    changed nothing. The admin page's Sign Out on the same bar answers the
    pointer with white on #243548, 12.52:1, and Logout now does the same.
    """

    def test_logout_sits_on_the_nav_bar(self) -> None:
        """What is measured below is where the console renders it."""
        page = (_TEMPLATES / "operator.html").read_text(encoding="utf-8")
        start = page.index("{% block nav_actions %}")
        actions = page[start:page.index("{% endblock %}", start)]
        assert 'class="btn-logout"' in actions

    @pytest.mark.parametrize(("theme", "raw"), _RAW_THEMES)
    def test_the_hovered_logout_clears_the_floor_and_answers_the_pointer(
        self, theme: str, raw: dict[str, str]
    ) -> None:
        ink, surface = _on_the_bar(_logout_rules(theme, hover=True), theme, raw)
        ratio = _ratio(ink, surface)
        assert ratio >= _AA_NORMAL, (
            f"the {theme} hovered Logout is {ratio:.2f}:1, {ink} on {surface}, at 10.08px/500"
        )
        assert (ink, surface) != _on_the_bar(_logout_rules(theme, hover=False), theme, raw), (
            f"the {theme} Logout paints {ink} on {surface} at rest and under the "
            "pointer alike; its hover rule is outranked and shows nothing"
        )

    @pytest.mark.parametrize(("theme", "raw"), _RAW_THEMES[1:])
    def test_steel_logout_hovers_like_sign_out_on_the_same_bar(
        self, theme: str, raw: dict[str, str]
    ) -> None:
        """One control on one bar in two pages, pinned as the sidebar and hero tabs are."""
        logout = _on_the_bar(_logout_rules(theme, hover=True), theme, raw)
        sign_out = _on_the_bar(_ghost_rules(theme, True, "button"), theme, raw)
        assert logout == sign_out, (
            f"the {theme} hovered Logout paints {logout[0]} on {logout[1]} but "
            f"Sign Out on the same bar paints {sign_out[0]} on {sign_out[1]}"
        )


#: A focus ring is a non-text indicator with a 3:1 floor. Every ring the
#: console draws on its own surfaces clears 4.91:1 (see the ring comments in
#: spectre-theme.css), so one that clears 3:1 by a few hundredths has no room
#: for a retuned bar or an antialiased edge. The bar's ring is held to 4.5.
_RING_COMFORT = 4.5


def _rule_custom_properties(filename: str, selector: str) -> dict[str, str]:
    """The ``--token: value;`` declarations of every rule that lists *selector*.

    Every rule, not one: style.css styles ``.nav-bar`` twice, the second time
    inside a narrow-screen media query, and a token set in either reaches a
    control on the bar at some width.
    """
    return {
        name: value.strip()
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _on_screen(filename))
        if selector in (member.strip() for member in head.split(","))
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body)
    }


def _nav_bar_scope(theme: str, raw: dict[str, str]) -> dict[str, str]:
    """*raw* as a control on the nav bar inherits it: the bar's own tokens on top."""
    if theme == "dark":
        return {**raw, **_rule_custom_properties("style.css", ".nav-bar")}
    return {**raw, **_rule_custom_properties("themes.css", '[data-theme="steel"] .nav-bar')}


#: The controls whose focus ring lands on the nav bar, as (the classes any of
#: which names it, the elements it can be). Console and Sign Out are the
#: admin page's; Logout is the console's own, on the same bar.
_BAR_CONTROLS = {
    "admin Console and Sign Out": ({".spectre-btn", ".spectre-btn-ghost"}, {"a", "button"}),
    "console Logout": ({".btn-logout"}, {"button"}),
}
_FOCUS = {":focus", ":focus-visible"}
#: What a control on the bar sits inside, on either page.
_BAR_ANCESTORS = {"html", ":root", "body", "nav", ".nav-bar", "div", ".nav-user-group", "form", ".inline-form"}
_THEME_ROOTS = {
    "dark": {'[data-theme="ops"]', '[data-spectre-theme="dark"]'},
    "steel": {'[data-theme="steel"]', '[data-spectre-theme="light"]'},
}


def _compounds(selector: str) -> list[set[str]]:
    """*selector*'s compound selectors, outermost first, each as its simple parts."""
    return [
        set(re.findall(r"\[[^\]]*\]|::?[\w-]+(?:\([^)]*\))?|[.#]?[\w-]+", compound))
        for compound in re.split(r"\s*[>+~]\s*|\s+", selector.strip())
        if compound
    ]


def _rings_on_the_bar(selector: str, control: str, theme: str) -> bool:
    """Whether *selector* reaches *control*, focused, where it sits on the bar."""
    *ancestors, last = _compounds(selector)
    classes, elements = _BAR_CONTROLS[control]
    around = _BAR_ANCESTORS | _THEME_ROOTS["dark" if theme == "dark" else "steel"]
    return (
        bool(last & classes)
        and bool(last & _FOCUS)
        and last <= classes | elements | _FOCUS
        and all(compound <= around for compound in ancestors)
    )


def _focus_shadow_rules(control: str, theme: str) -> list[tuple[str, str, str]]:
    """(stylesheet, selector, box-shadow) of every rule that rings *control* on the bar.

    Every loaded sheet is read, not one named rule, and the list is put in
    cascade order, winner first: specificity, then the later sheet, then the
    later rule in it. Reading only ``.spectre-btn:focus-visible`` let a more
    specific bar rule put the 3.14:1 ring back unseen.
    """
    order = [name for name in _load_order() if (_STATIC / name).exists()]
    found = [
        (_specificity(member), order.index(filename), position, filename, member.strip(), shadow.group(1).strip())
        for filename in order
        for position, (head, body) in enumerate(re.findall(r"([^{}]+)\{([^{}]*)\}", _on_screen(filename)))
        for member in head.split(",")
        if _rings_on_the_bar(member, control, theme)
        and (shadow := re.search(r"(?<![-\w])box-shadow\s*:\s*([^;}]+)", body))
    ]
    return [rule[3:] for rule in sorted(found, reverse=True)]


class TestTheFocusRingOnTheSteelNavBar:
    """SPC-035: the focus ring on whatever sits on the nav bar.

    ``.spectre-btn:focus-visible`` draws var(--spectre-shadow-focus), a 2px
    ring of the intel blue outside the button, so on the admin page's Console
    and Sign Out it lands on the nav bar. Steel's #0077cc on #1a2a3a measured
    3.14:1. Steel keeps that bar dark, so the bar re-points the ring token to
    --spectre-focus-ring-on-dark, the ring the engine tab bar already uses for
    the same reason.

    The console's Logout, on the same bar, had no focus rule at all and drew
    the browser's own ring. Under Steel's ``color-scheme: light`` that is the
    light-mode ring style.css records at 1.03:1 to 1.07:1 on dark surfaces.
    It now draws the same token, so the bar's override reaches it too.
    """

    def test_a_more_specific_bar_rule_outranks_the_shared_one(self) -> None:
        """The cascade order the measurement below relies on."""
        shared = _specificity(".spectre-btn:focus-visible")
        on_the_bar = _specificity('[data-theme="steel"] .nav-bar .spectre-btn:focus-visible')
        assert on_the_bar > shared
        assert _rings_on_the_bar('[data-theme="steel"] .nav-bar .spectre-btn:focus-visible', "admin Console and Sign Out", "steel")
        assert not _rings_on_the_bar('[data-theme="steel"] .nav-bar .spectre-btn:focus-visible', "admin Console and Sign Out", "dark")
        assert not _rings_on_the_bar(".spectre-btn-threat:focus-visible", "admin Console and Sign Out", "steel")
        assert not _rings_on_the_bar(".panel .spectre-btn:focus-visible", "admin Console and Sign Out", "steel")

    @pytest.mark.parametrize("control", list(_BAR_CONTROLS))
    @pytest.mark.parametrize(("theme", "raw"), _RAW_THEMES)
    def test_the_ring_clears_a_comfortable_margin_on_the_bar(
        self, theme: str, raw: dict[str, str], control: str
    ) -> None:
        rules = _focus_shadow_rules(control, theme)
        assert rules, (
            f"no rule rings the {theme} {control} on the nav bar, so it draws the "
            "browser's own ring, measured as low as 1.03:1 on dark chrome"
        )
        filename, selector, value = rules[0]
        scope = _nav_bar_scope(theme, raw)
        shadow = _follow(value, scope)
        spread = re.fullmatch(r"(?:-?[\d.]+(?:px)?\s+){4}(.+)", shadow)
        assert spread, f"cannot read a colour from {selector} in {filename}: {shadow!r}"
        bar = _nav_bar(theme, raw)
        ring = _paint(_follow(spread.group(1), scope), bar)
        ratio = _ratio(ring, bar)
        assert ratio >= _RING_COMFORT, (
            f"the {theme} focus ring on the {control}, from {selector} in {filename}, "
            f"is {ratio:.2f}:1, {ring} on {bar}: over the 3:1 floor by too little to hold"
        )
