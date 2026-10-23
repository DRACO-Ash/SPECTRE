"""Every ``--x-rgb`` triple carries the channels of its sibling ``--x`` hex.

A band token is a pair, not a value. ``--spectre-status-minimal`` is the text
colour; ``--spectre-status-minimal-rgb`` is the same colour's channels, split
out so a call site can write ``rgba(var(--spectre-status-minimal-rgb), 0.06)``
and keep the wash alpha it already had. The two are only ever meant to be one
colour written twice.

They have come apart once already. ``--spectre-status-minimal`` was raised
from #7A8BA6 to #8696AE so it would clear 4.5:1 on surface-panel, and the
triple was left at ``122, 139, 166``, the old value, which is also
``--spectre-color-sensor-grey``. The MINIMAL band in
``spectre/web/routes/threat.py`` then took its text from one colour and its
6% wash from another. At 6% over #0A0C10 the two composite to the same
#111419, so nothing looked wrong; over surface-raised they differ (#1A1F28 vs
#1B2029) and at a higher alpha they diverge visibly. A split pair is a defect
whether or not today's alpha happens to hide it.

This module holds the pairs together by construction, per theme block, so the
next raise cannot land on the hex alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "spectre" / "web" / "static"

#: The stylesheets that define tokens. themes.css and style.css carry no -rgb
#: triples today; they are swept anyway so a triple added there is caught.
_SHEETS = ("spectre-theme.css", "themes.css", "style.css")

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HEX = re.compile(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;")
_RGB = re.compile(r"(--[a-z0-9-]+)-rgb\s*:\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*;")


def _blanked(text: str) -> str:
    """*text* with every comment replaced by whitespace of the same length.

    Offsets and line numbers survive, so a block's reported line still points
    into the real file. Blanking rather than deleting matters twice over: the
    naming convention comment at the top of spectre-theme.css contains
    ``--spectre-{category}-{property}-{variant}``, whose braces would
    otherwise be read as block delimiters and drag the :root selector into a
    failure message; and a hex quoted in prose cannot be mistaken for a
    declaration.
    """
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _blocks(text: str) -> list[tuple[str, str, int]]:
    """Every brace-delimited block in *text*, as (selector, body, line).

    Block-aware for the same reason ``test_contrast_floors`` is: one
    stylesheet carries several theme blocks, and a triple in the dark block
    must be checked against the dark block's hex, not against whichever
    declaration happens to come last in the file.
    """
    text = _blanked(text)
    out: list[tuple[str, str, int]] = []
    index = 0
    while True:
        opening = text.find("{", index)
        if opening < 0:
            return out
        # A selector starts after the last brace OR statement terminator, so
        # the @import lines above :root do not get swept into its name.
        previous = max(
            text.rfind("}", 0, opening),
            text.rfind("{", 0, opening),
            text.rfind(";", 0, opening),
        )
        selector = " ".join(text[previous + 1:opening].split())
        depth, cursor = 0, opening
        while cursor < len(text):
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        out.append((selector, text[opening + 1:cursor], text.count("\n", 0, opening) + 1))
        index = opening + 1


#: (sheet, line, selector, token, declared channels, sibling hex or None).
#: The sibling is resolved here, from the same block object the triple was
#: read out of, rather than looked up again later by line number: two blocks
#: could in principle open on one line, and a lookup that picked the wrong one
#: would compare a dark triple against a light hex.
Pair = tuple[str, int, str, str, tuple[int, int, int], "str | None"]


def _pairs() -> list[Pair]:
    found: list[Pair] = []
    for sheet in _SHEETS:
        text = (_STATIC / sheet).read_text(encoding="utf-8")
        for selector, body, line in _blocks(text):
            hexes = dict(_HEX.findall(body))
            for base, red, green, blue in _RGB.findall(body):
                found.append((sheet, line, selector, base,
                              (int(red), int(green), int(blue)), hexes.get(base)))
    return found


_PAIRS = _pairs()


def _channels(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _label(pair: Pair) -> str:
    sheet, line, selector, token = pair[0], pair[1], pair[2], pair[3]
    return f"{sheet}:{line} {selector[:28]} {token}"


class TestEveryTripleMatchesItsHex:
    """The whole point of the pair is that it is one colour."""

    @pytest.mark.parametrize("pair", _PAIRS, ids=_label)
    def test_the_channels_are_the_hex(self, pair: Pair) -> None:
        sheet, line, selector, token, declared, sibling = pair
        assert sibling is not None, (
            f"{token}-rgb is declared in {sheet} in the block opening on line "
            f"{line} ({selector[:40]}) with no {token} hex in the same block, "
            "so there is nothing holding the triple to a colour"
        )
        expected = _channels(sibling)
        assert declared == expected, (
            f"{token}-rgb is {declared} but {token} is {sibling} = {expected}, "
            f"in {sheet} in the block opening on line {line} ({selector[:40]}). "
            "The call sites that read the triple paint a different colour from "
            "the ones that read the hex."
        )

    def test_the_sweep_found_the_triples_it_is_meant_to_guard(self) -> None:
        """A parametrised sweep over an empty list passes and proves nothing."""
        tokens = {pair[3] for pair in _PAIRS}
        assert len(_PAIRS) >= 14, (
            f"only {len(_PAIRS)} --*-rgb triples were found; the parser has "
            "stopped seeing them and this module is no longer guarding anything"
        )
        for band in ("critical", "high", "medium", "low", "minimal", "unknown", "violet"):
            assert f"--spectre-status-{band}" in tokens, (
                f"--spectre-status-{band}-rgb was not swept"
            )

    def test_the_comparison_can_still_fail(self) -> None:
        """The arithmetic that would catch the next split still catches one."""
        assert _channels("#8696AE") == (134, 150, 174)
        assert _channels("#7A8BA6") == (122, 139, 166)
        assert _channels("#8696AE") != _channels("#7A8BA6")
