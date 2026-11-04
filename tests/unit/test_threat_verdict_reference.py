"""The verdict switch's reference table, the owner's sign-off sheet (SPC-175).

tests/reference/threat_verdict_reference.csv gives, for each of the 20
bundled red objects, the verdict the current rule shows, the verdict the
switch would show, Understanding and the reason in one plain line. These
tests compute both verdicts afresh and fail if the table drifts from the
code, so what the owner signs is what the switch does. The data sits beside
the tests so that check runs wherever they do. docs/threat_verdict_reference.md
is the same table rendered for reading, and must agree with the data line for
line; docs/ does not travel in the submission package, so those tests skip
there. With the switch off, the pinned legacy verdicts are what the sweep shows.
"""

from __future__ import annotations

import csv
import re

import pytest

from tests.unit import _verdict_reference as ref
from tests.unit._i13 import i13_problems
from tests.unit.test_threat_understanding_sweep import _LEGACY, _RED


class TestTheTable:
    def test_it_covers_the_twenty_bundled_red_objects_once_each(self) -> None:
        rows = ref.read_rows()
        assert [r["object"] for r in rows] == ref.bundled_red()
        assert sorted(r["object"] for r in rows) == sorted(_RED) == sorted(_LEGACY)
        assert len(rows) == 20

    def test_its_columns_are_the_sign_off_sheets(self) -> None:
        with ref.REFERENCE_CSV.open(encoding="utf-8", newline="") as f:
            header = next(csv.reader(f))
        assert tuple(header) == ref.COLUMNS == ("object", "name", "old_verdict", "new_verdict", "understanding",
                                                "reason")

    def test_each_object_is_one_plain_line(self) -> None:
        lines = ref.REFERENCE_CSV.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 + 20
        for row in ref.read_rows():
            for sentence in re.split(r"(?<=\.)\s+", row["reason"]):
                assert i13_problems(sentence) == [], sentence


class TestTheTableMatchesTheCode:
    def test_the_old_and_new_verdicts_and_reasons_are_what_the_code_computes(self) -> None:
        assert ref.computed_rows() == ref.read_rows()

    def test_the_old_verdict_is_the_pinned_legacy_one(self) -> None:
        assert {r["object"]: r["old_verdict"] for r in ref.read_rows()} == _LEGACY

    @pytest.mark.parametrize("satno", sorted(_LEGACY))
    def test_with_the_switch_off_the_sweep_shows_the_old_verdict(self, satno: str) -> None:
        worst, understanding = ref.bundled(satno)
        from spectre.web.routes import threat

        shown = threat._with_verdict_switch(dict(worst), understanding, switch_on=False)
        assert shown is not None and shown["threat_level"] == _LEGACY[satno]
        assert "verdict_reason" not in shown


def _sheet() -> str:
    """The owner's sheet; docs/ is not in the submission package, so a test reading it skips there.

    Only a missing docs/ skips: with docs/ present, a missing sheet fails.
    """
    if not ref.REFERENCE_MD.parent.is_dir():
        pytest.skip("docs/ is excluded from the submission package")
    return ref.REFERENCE_MD.read_text(encoding="utf-8")


class TestTheSheetAgreesWithTheData:
    def test_the_markdown_is_the_data_rendered(self) -> None:
        assert _sheet() == ref.render_markdown(ref.read_rows())

    def test_every_row_of_the_data_is_a_row_of_the_sheet(self) -> None:
        sheet = _sheet()
        for row in ref.read_rows():
            assert f"| {row['object']} | {row['name']} | {row['old_verdict']} | {row['new_verdict']} | " \
                   f"{row['understanding']} | {row['reason']} |" in sheet

    def test_the_sheet_says_how_many_change_and_asks_for_the_owners_decision(self) -> None:
        rows = ref.read_rows()
        changed = sum(1 for r in rows if r["old_verdict"] != r["new_verdict"])
        sheet = _sheet()
        assert f"{changed} of 20 verdicts change" in sheet
        assert "SPECTRE_THREAT_VERDICT_SWITCH" in sheet
        assert "Owner:" in sheet and "Date:" in sheet

    def test_it_says_everything_the_switch_changes_on_the_screen(self) -> None:
        # The owner signs what the switch does: on the asset screen that is more than the word in the badge.
        sheet = " ".join(_sheet().split())
        assert "The switch changes only the verdict shown" not in sheet
        assert "ranks its actors by the verdict shown, so the actor named most dangerous can change" in sheet
        assert "notice of an actor whose verdict its own Threat range does not bear out no longer appears" in sheet
        assert "Each switched verdict carries its reason" in sheet

    def test_it_follows_the_house_style(self) -> None:
        sheet = _sheet()
        assert "—" not in sheet and "--" not in sheet
        assert not re.search(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", sheet, re.MULTILINE)
