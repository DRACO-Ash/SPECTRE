"""Table markup must balance, because nothing else in the loop looks at it.

A `scope="col"` sweep over threat_screen.html used the pattern ``<th`` without
a word boundary, so it matched the opening ``<thead>`` and rewrote it as
``<th scope="col"ead>``. The table lost its header section: Chromium parsed
zero ``thead`` elements, foster-parented the header row into the ``tbody``,
rendered a stray empty header cell as a third row, and ``table.tHead`` was
null. That template is rendered by a live route.

It shipped through every gate green. pytest, check-quality.sh, ruff, mypy, the
complexity calibration and the preflight gate all passed, because not one of
them parses HTML. The commit message even carried the tell, reporting twelve
headers for an eleven-column table: the twelfth was the tag it had eaten.

So the counts are compared against the merge base rather than asserted
absolutely. Templates legitimately open a tag in one Jinja branch and close it
in another, and several here do; a flat "opens equals closes" rule would be
noise. What must never happen is a file getting WORSE than it was.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = _ROOT / "spectre" / "web" / "templates"
_BASE = "origin/master"

#: Tags whose imbalance changes how a browser builds the table. A stray <div>
#: is a layout nuisance; a stray <thead> moves rows between sections.
_TABLE_TAGS = ("table", "thead", "tbody", "tr")


def _strip_comments(markup: str) -> str:
    """Remove Jinja and HTML comments.

    A tag NAMED in a comment is not markup. The comments in these templates
    discuss <tr> and <thead> by name precisely because that is what the code
    around them does, and counting those as open tags reported two real files
    as newly unbalanced on this guard's first run.
    """
    markup = re.sub(r"\{#.*?#\}", "", markup, flags=re.S)
    return re.sub(r"<!--.*?-->", "", markup, flags=re.S)


def _counts(markup: str) -> dict[str, tuple[int, int]]:
    """``{tag: (opens, closes)}`` for the table tags in *markup*."""
    body = _strip_comments(markup)
    out: dict[str, tuple[int, int]] = {}
    for tag in _TABLE_TAGS:
        opens = len(re.findall(rf"<{tag}\b", body, re.I))
        closes = len(re.findall(rf"</{tag}\s*>", body, re.I))
        out[tag] = (opens, closes)
    return out


def _templates() -> list[Path]:
    return sorted(_TEMPLATES.rglob("*.html"))


class TestNoTemplateContainsASplicedTag:
    """The literal damage, which no balance count would catch on its own.

    ``<th scope="col"ead>`` is balanced as far as a counter is concerned: it
    opened no ``thead`` and closed none. It is only visible as a malformed
    attribute name, so that is what is checked.
    """

    @pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
    def test_no_attribute_is_spliced_into_a_tag_name(self, path: Path) -> None:
        markup = _strip_comments(path.read_text(encoding="utf-8"))
        spliced = re.findall(r'<\w+\s+[^>]*"[a-z]{2,}>', markup)
        assert not spliced, (
            f"{path.name} contains a tag whose name was spliced by an "
            f"attribute edit: {spliced}. A sweep that rewrote <th> and caught "
            f"<thead> is how this happens."
        )

    @pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
    def test_no_opening_table_tag_carries_a_stray_word_after_a_quote(
        self, path: Path
    ) -> None:
        for tag in _TABLE_TAGS:
            markup = _strip_comments(path.read_text(encoding="utf-8"))
            bad = re.findall(rf'<{tag}\b[^>]*"\w+>', markup)
            assert not bad, f"{path.name}: malformed <{tag}>: {bad}"
        assert markup  # the read is the assertion's subject


class TestTableBalanceDoesNotGetWorse:
    """Measured against the merge base, so pre-existing Jinja asymmetry is not noise."""

    @staticmethod
    def _at_base(relative: str) -> str | None:
        git = shutil.which("git")
        if git is None or not (_ROOT / ".git").exists():
            return None
        result = subprocess.run(  # noqa: S603
            [git, "show", f"{_BASE}:{relative}"],
            cwd=_ROOT, capture_output=True, text=True, check=False,
        )
        return result.stdout if result.returncode == 0 else None

    @pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
    def test_no_table_tag_is_more_unbalanced_than_at_the_merge_base(
        self, path: Path
    ) -> None:
        relative = path.relative_to(_ROOT).as_posix()
        base_markup = self._at_base(relative)
        if base_markup is None:
            # New file, or no git. A new file must simply balance.
            for tag, (opens, closes) in _counts(path.read_text(encoding="utf-8")).items():
                assert opens == closes, (
                    f"{path.name} is new and its <{tag}> does not balance: "
                    f"{opens} open, {closes} close"
                )
            return

        now = _counts(path.read_text(encoding="utf-8"))
        before = _counts(base_markup)
        for tag in _TABLE_TAGS:
            drift_now = abs(now[tag][0] - now[tag][1])
            drift_before = abs(before[tag][0] - before[tag][1])
            assert drift_now <= drift_before, (
                f"{path.name}: <{tag}> balance got worse. Now {now[tag][0]} "
                f"open and {now[tag][1]} close; at {_BASE} it was "
                f"{before[tag][0]} and {before[tag][1]}"
            )


class TestTheScanCanActuallySeeTheDefect:
    """Without this, every test above could be passing on an empty file list."""

    def test_it_found_templates_to_scan(self) -> None:
        assert len(_templates()) > 20, "the template sweep found almost nothing"

    def test_the_splice_pattern_matches_the_real_damage(self) -> None:
        """The exact string that shipped, so the guard is pinned to it."""
        damaged = '      <th scope="col"ead>\n        <tr>'
        assert re.findall(r'<\w+\s+[^>]*"[a-z]{2,}>', damaged), (
            "the splice pattern no longer recognises the defect it was "
            "written for, so it is guarding nothing"
        )

    def test_the_balance_check_notices_a_removed_opening_tag(self) -> None:
        intact = "<table><thead><tr><th>a</th></tr></thead><tbody></tbody></table>"
        broken = intact.replace("<thead>", "", 1)
        assert _counts(intact)["thead"] == (1, 1)
        assert _counts(broken)["thead"] == (0, 1)
