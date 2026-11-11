"""The operating envelope's document says what the code enforces (SPC-200, evaluation F-09, with SPC-201).

docs/decision-engine-envelope.md states the regimes, element-set ages, horizons, scenario sizes, turns and inputs the
Decision Engine is fit for, each with where in the code it is enforced and what lies outside it. Every row of its
tables names a constant or a function by file and name, as the lookup register does; a row that gives a value gives
the value the code holds. A row whose constant leaves the code, or whose value changes without the document, fails
here, so the document cannot drift from the engine unseen. docs/decision_engine_phases.md links it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from spectre.astro import elset_approach
from spectre.astro.elset_check import _ANGLES
from spectre.astro.monte_carlo import REENTRY_FLOOR_KM
from spectre.domain.decision_envelope import DEEP_SPACE, DEEP_SPACE_GEO
from tests.unit.test_lookup_register import _module, resolve

_ROOT = Path(__file__).resolve().parents[2]
_ENVELOPE = "docs/decision-engine-envelope.md"


def _read(relative: str) -> str:
    """A document under docs/, which the packager strips: the test skips where it is not shipped."""
    path = _ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} not present in this checkout")
    return path.read_text(encoding="utf-8")


def _rows() -> list[list[str]]:
    """Every table row of the envelope document; none where the document is not shipped."""
    path = _ROOT / _ENVELOPE
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith(("| Dimension ", "|---")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 5, f"an envelope row has 5 cells: {line}"
        rows.append(cells)
    return rows


def _where(cell: str) -> tuple[str, str]:
    path, name = re.findall(r"`([^`]+)`", cell)
    return path, name


def test_every_area_the_finding_names_has_a_table() -> None:
    text = _read(_ENVELOPE)
    headings = ("## Element sets", "## Regimes", "## Element-set ages", "## Horizons", "## Scenario sizes and turns",
                "## Inputs", "## What lies outside the envelope altogether")
    for heading in headings:
        assert heading in text, heading
    assert len(_rows()) >= 30


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row[0])
def test_each_row_names_what_the_code_holds(row: list[str]) -> None:
    _dimension, fit, where, value, outside = row
    assert fit and outside, "a row says what it is fit for and what lies outside it"
    path, name = _where(where)
    held = resolve(_module(path), name)
    if value != "none":
        (literal,) = re.findall(r"`([^`]+)`", value)
        assert held == ast.literal_eval(literal), f"{path} {name} holds {held!r}, the envelope says {literal}"


def test_the_angle_ranges_are_the_ones_the_document_states() -> None:
    assert [(f.words, f.low, f.high) for f in _ANGLES] == [
        ("the inclination", 0.0, 180.0),
        ("the right ascension of the ascending node", 0.0, 360.0),
        ("the argument of perigee", 0.0, 360.0),
        ("the mean anomaly", 0.0, 360.0),
    ]


def test_the_reentry_floor_holds_on_both_propagators() -> None:
    assert elset_approach.REENTRY_FLOOR_KM is REENTRY_FLOOR_KM


def test_deep_space_is_flagged_and_not_refused() -> None:
    assert "Its figures stand, flagged." in DEEP_SPACE and "Its figures stand, flagged." in DEEP_SPACE_GEO
    assert "rules of thumb set for LEO and GEO, not validated for this orbit" in DEEP_SPACE
    assert "GEO rules of thumb, tuned rather than sourced" in DEEP_SPACE_GEO


def _row(dimension: str) -> list[str]:
    (row,) = [row for row in _rows() if row[0] == dimension]
    return row


class TestTheClaimsTheReviewFound:
    """Claims the review of SPC-200 found untrue or unclear, held to the code (review findings on the envelope)."""

    def test_the_age_rows_name_the_regimes_the_code_reads(self) -> None:
        """'Deep space' meant SDP4 in one table and perigee beyond GEO in the other: a Molniya set gets 24 h."""
        from spectre.web.elsets import _SLOW_REGIMES

        assert frozenset({"GEO", "DEEP"}) == _SLOW_REGIMES
        slow = _row("Age, regimes GEO and DEEP, h")
        assert "perigee beyond GEO" in slow[1]
        other = _row("Age, every other regime, h")
        assert "HEO" in other[1] and "GTO" in other[1] and "Molniya" in other[1]
        assert not any("deep space" in row[0].lower() for row in _rows())

    def test_a_geo_set_is_not_said_to_be_on_rules_set_for_another_orbit(self) -> None:
        regimes = _row("Near-Earth orbits")
        assert "GEO rules of thumb, tuned rather than sourced" in regimes[4]
        assert "F-29" in regimes[4]

    def test_expected_value_with_every_p_at_0_says_when_the_headline_reads_no_recommendation(self) -> None:
        outside = _row("P under expected value")[4]
        assert "when expected value is the deployment's primary rule" in outside
        assert "the headline shows the primary rule's pick" in outside

    def test_what_lies_outside_lists_nothing_the_engine_checks(self) -> None:
        section = _read(_ENVELOPE).split("## What lies outside the envelope altogether")[1].split("\n## ")[0]
        assert "Refused, as above" not in section

    def test_the_drag_fields_are_checked_and_said_to_have_no_range(self) -> None:
        drag = _row("Drag fields: B*, and the first and second derivatives of the mean motion")
        assert "no range" in drag[1].lower() or "no range" in drag[4].lower()

    def test_every_path_with_no_page_says_where_the_refusal_is_shown(self) -> None:
        text = " ".join(_read(_ENVELOPE).split())
        assert "run log" in text
        for path in ("Pattern of Life", "HRR watchlist fetched from UDL", "the bundled watchlist at start-up",
                     "the training objects", "the UDL history fetch"):
            assert path in text, path

    def test_counts_under_five_are_words(self) -> None:
        text = _read(_ENVELOPE)
        assert not re.search(r"\b[1-4] (digits|turns|rows|lines)\b", text)
        assert "F-29" in text


def test_the_phase_document_links_it() -> None:
    assert _ENVELOPE in _read("docs/decision_engine_phases.md")


def test_it_follows_the_house_style() -> None:
    text = _read(_ENVELOPE)
    assert "—" not in text and "–" not in text
    prose = "\n".join(line for line in text.splitlines() if not line.startswith("|---"))
    assert "--" not in prose
    assert not re.search(r"^(---|\*\*\*|___)\s*$", text, re.MULTILINE), "a horizontal rule"
    assert not re.search(r"^\s*[-*] ", text, re.MULTILINE), "a dash or star bullet"
