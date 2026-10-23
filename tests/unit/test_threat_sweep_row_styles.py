"""The cascade relationship between the sweep's posture tints and its hover rules.

Two defects in one place, both of them invisible to anything that reads a
declaration without asking which rule the browser obeys.

THE HOVER. Moving the sweep tints from classes to attribute selectors raised
them from (0,1,0) to (0,2,0), which ties ``.threat-parent:hover``. Both sides
carry ``!important`` and the tints came later in the file, so the tint won and
critical, high and violet rows had no hover feedback at all, while the legacy
``.threat-high`` rows in all_intercepts_result.html kept theirs because
(0,1,0) still loses. Measured in Chromium at commit fc465fe, a hovered
critical parent row was pixel-identical to its resting state in both themes
(ops #2E1D24 to #2E1D24, steel #F6E3E3 to #F6E3E3). Nothing in the stylesheet
was missing or misspelled: the losing rule was present and correct.

THE BAND. ``threat_sweep.html`` and ``threat_sweep_row.html`` both call
``posture_bands.get(..., 'unknown')``, and ``posture_label`` defaults to ``""``
on ThreatSweepEntry and on ThreatAssessment, so a row can reach the table with
``data-posture-band="unknown"``. style.css had no rule for that value, so such
a row came out pixel-identical to a BENIGN one, which the comment beside the
BENIGN case calls "the quiet case, which is what the operator should be able
to skim past". The band is latent rather than live at fc465fe: the one site
that builds an entry always sets the label from ``classify_posture``, whose
enum carries exactly the four labels the map covers. These tests hold the
palette to what the templates can emit, not to what they happen to emit now.

WHAT THESE TESTS DO AND DO NOT COVER. They assert the two cascade inputs that
decide the outcome: source order, and specificity. They do not render
anything, so they cannot prove that a hovered row actually changes colour, nor
that the change is large enough to notice, nor that any of it survives a rule
added in themes.css or in a stylesheet loaded later. Those were checked by
driving the console in Chromium and sampling the composited pixels; these
tests are the part of that check which can run in CI. A pixel assertion would
need a browser in the test environment.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CSS = _ROOT / "spectre" / "web" / "static" / "style.css"
_PARTIALS = _ROOT / "spectre" / "web" / "templates" / "partials"
_BANDS_MAP = _PARTIALS / "_posture_bands.html"
_SWEEP = _PARTIALS / "threat_sweep.html"
_REFINED = _PARTIALS / "threat_sweep_row.html"

#: The two row kinds the sweep tints, and the hover rule each one needs.
_ROW_KINDS = (".threat-parent", ".threat-child")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css: str) -> list[tuple[int, str, str]]:
    """Every flat rule as (source order, selector list, declaration block).

    Good enough for this file: the only nested at-rules are two width media
    queries at the very end, long after the threat rules, and the prelude of
    an at-rule never contains a ``.threat-`` selector.
    """
    out: list[tuple[int, str, str]] = []
    for i, m in enumerate(re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css))):
        out.append((i, m.group(1).strip(), m.group(2)))
    return out


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes/attributes/pseudo-classes, elements/pseudo-elements).

    Deliberately simple. It covers the compound selectors used in this file
    and does not implement the special counting rules of :not(), :is() or
    :where(), none of which appear in the rules under test.
    """
    assert not re.search(r":(not|is|where|has)\(", selector), (
        f"{selector!r} uses a functional pseudo-class this helper cannot count"
    )
    s = selector
    ids = len(re.findall(r"#[\w-]+", s))
    s = re.sub(r"#[\w-]+", " ", s)
    attrs = len(re.findall(r"\[[^\]]*\]", s))
    s = re.sub(r"\[[^\]]*\]", " ", s)
    classes = len(re.findall(r"\.[\w-]+", s))
    s = re.sub(r"\.[\w-]+", " ", s)
    pseudo_elements = len(re.findall(r"::[\w-]+", s))
    s = re.sub(r"::[\w-]+", " ", s)
    pseudo_classes = len(re.findall(r":[\w-]+", s))
    s = re.sub(r":[\w-]+", " ", s)
    elements = len(re.findall(r"[a-zA-Z][\w-]*", s))
    return ids, attrs + classes + pseudo_classes, elements + pseudo_elements


def _emitted_bands() -> set[str]:
    """Every data-posture-band value the templates can put on a row."""
    bands = set(re.findall(r":\s*'([a-z]+)'", _BANDS_MAP.read_text(encoding="utf-8")))
    for template in (_SWEEP, _REFINED):
        bands |= set(re.findall(
            r"posture_bands\.get\([^,]+,\s*'([a-z]+)'\s*\)",
            template.read_text(encoding="utf-8"),
        ))
    return bands


class TestEveryEmittedPostureBandIsAnswered:
    """A band the templates can emit and the palette does not know is a lie."""

    #: BENIGN. Untinted on purpose, and the stylesheet says so in as many words.
    _DELIBERATELY_UNTINTED = {"low"}

    def test_the_map_still_emits_the_bands_this_suite_assumes(self) -> None:
        assert _emitted_bands() >= {"low", "high", "critical", "violet", "unknown"}, (
            "the posture map or a template default changed; this suite is "
            "asserting against bands that are no longer emitted"
        )

    def test_every_emitted_band_has_a_tint_or_is_the_documented_quiet_case(self) -> None:
        css = _strip_comments(_CSS.read_text(encoding="utf-8"))
        missing = sorted(
            band
            for band in _emitted_bands() - self._DELIBERATELY_UNTINTED
            if f'[data-posture-band="{band}"]' not in css
        )
        assert not missing, (
            f"style.css has no rule for data-posture-band={missing}. A row "
            "carrying one renders exactly like BENIGN, which the file calls "
            "the quiet case an operator should skim past"
        )

    def test_the_unknown_band_is_tinted_on_both_row_kinds(self) -> None:
        """The literal defect: an unassessed posture reading as a cleared one."""
        css = _strip_comments(_CSS.read_text(encoding="utf-8"))
        for kind in _ROW_KINDS:
            assert f'{kind}[data-posture-band="unknown"]' in css, (
                f"{kind} has no unknown tint, so a row whose posture was never "
                "computed is drawn as BENIGN"
            )

    def test_the_unknown_tint_is_built_from_the_unknown_token(self) -> None:
        """Not a hue borrowed from a threat band, and not a hard-coded colour."""
        css = _strip_comments(_CSS.read_text(encoding="utf-8"))
        for kind in _ROW_KINDS:
            block = re.search(
                re.escape(f'{kind}[data-posture-band="unknown"]') + r"\s*\{([^}]*)\}",
                css,
            )
            assert block is not None
            assert "--spectre-status-unknown-rgb" in block.group(1), (
                f"the {kind} unknown tint is not reading the unknown token"
            )


class TestHoverOutranksEveryPostureTint:
    """The rule the browser obeys for a hovered tinted row has to be the hover one."""

    @staticmethod
    def _tints(rules: list[tuple[int, str, str]], kind: str) -> list[tuple[int, str]]:
        return [
            (order, sel)
            for order, sel, _ in rules
            if sel.startswith(kind) and "[data-posture-band=" in sel
            and ":hover" not in sel and "td" not in sel
        ]

    @staticmethod
    def _hover(rules: list[tuple[int, str, str]], kind: str) -> tuple[int, list[str]]:
        """The one rule whose whole selector list is hover states of this row.

        Matched exactly, so that neighbours such as
        ``.threat-child-header th:hover`` are not mistaken for it.
        """
        row_hover = re.compile(re.escape(kind) + r"(\[data-posture-band\])?:hover$")
        found = [
            (order, [p.strip() for p in sel.split(",")])
            for order, sel, _ in rules
            if all(row_hover.fullmatch(p.strip()) for p in sel.split(","))
        ]
        assert len(found) == 1, (
            f"expected exactly one hover rule for {kind}, found {len(found)}: "
            f"{[parts for _, parts in found]}"
        )
        return found[0]

    def test_the_hover_rule_comes_after_every_tint(self) -> None:
        rules = _rules(_CSS.read_text(encoding="utf-8"))
        for kind in _ROW_KINDS:
            hover_order, _ = self._hover(rules, kind)
            for tint_order, tint_sel in self._tints(rules, kind):
                assert tint_order < hover_order, (
                    f"{tint_sel} is declared after the {kind} hover rule. Both "
                    "carry !important, so on a specificity tie the tint wins "
                    "and the row loses its hover feedback"
                )

    def test_the_hover_rule_outranks_every_tint_on_specificity(self) -> None:
        rules = _rules(_CSS.read_text(encoding="utf-8"))
        for kind in _ROW_KINDS:
            _, hover_parts = self._hover(rules, kind)
            best = max(_specificity(p) for p in hover_parts)
            for _, tint_sel in self._tints(rules, kind):
                assert best > _specificity(tint_sel), (
                    f"the {kind} hover rule tops out at {best} and {tint_sel} "
                    f"is {_specificity(tint_sel)}. Equal specificity plus "
                    "!important on both sides means source order decides, "
                    "which is one reordering away from losing again"
                )

    def test_the_hover_rule_matches_a_banded_row_specifically(self) -> None:
        """Order alone is fragile; the attribute is what makes the win structural."""
        rules = _rules(_CSS.read_text(encoding="utf-8"))
        for kind in _ROW_KINDS:
            _, hover_parts = self._hover(rules, kind)
            assert f"{kind}[data-posture-band]:hover" in hover_parts, (
                f"the {kind} hover rule does not carry a [data-posture-band] "
                "selector, so it only outranks the tints by source order"
            )

    def test_an_untinted_row_still_gets_hover_feedback(self) -> None:
        """all_intercepts_result.html emits .threat-parent with no band attribute."""
        rules = _rules(_CSS.read_text(encoding="utf-8"))
        for kind in _ROW_KINDS:
            _, hover_parts = self._hover(rules, kind)
            assert f"{kind}:hover" in hover_parts, (
                f"{kind}:hover was dropped, so rows without a posture band, "
                "including the comparison table's, lost their hover"
            )
