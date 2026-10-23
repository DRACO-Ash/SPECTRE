"""Sort state has to be readable without eyes, and a panel exit has to be scoped.

Three defects this file pins down, all of the same shape: a fact rendered into
one channel only.

1. Sort direction was a glyph. ``.hrr-sort-ind`` received an arrow and nothing
   else was written, so an operator on a screen reader was told a column header
   and never told that the table was sorted by it, or which way. In the threat
   sweep it was worse than that: the indicator spans were in the markup and
   neither sort function ever wrote to them, so the direction was carried by
   row order alone. ``aria-sort`` is the programmatic equivalent, and these
   cases hold it on every sortable header of the four tables, and only on the
   sortable ones: ``aria-sort="none"`` on a column that does not sort would
   advertise an action that is not there.

2. The geometry panel's Escape listener was on ``document`` with no target or
   state check, so an Escape pressed anywhere on the console destroyed it. The
   case that bit was the Escape that dismisses a browser autocomplete in the
   threat sweep search box, in a different hero tab: the operator came back to
   the Intercept Engine and the panel was gone. Scoped to the panel's own
   subtree, keydown still reaches it from every control inside the panel and
   from nowhere else.

3. The panel was opened and destroyed with no focus management either way:
   focus never entered it, and on close it fell to body. The route added for
   the keyboard operator lost them their place at the moment it was supposed to
   help. Focus now moves to the panel heading on open and returns to the
   control that opened it on close.

These read the template source rather than a rendered page because the sort
headers are inside Jinja loops and the behaviour under test is in the inline
scripts the fragments carry. The live-DOM proof is in the review record; these
are the regression fence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / "partials"

# Template, the sort function its headers call, how many sortable headers it
# should have. The counts are deliberate: a new sortable column added without
# aria-sort fails here rather than shipping silent.
_SORTABLE_TABLES = [
    ("all_intercepts_result.html", "aiSort", 7),
    ("threat_sweep.html", "threatSort", 7),
    ("threat_sweep.html", "childSort", 6),
    ("hrr_panel.html", "hrrSort", 10),  # blue and red tables, five columns each
]

_TH_TAG = re.compile(r"<th\b[^>]*>", re.S)


def _source(name: str) -> str:
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def _sortable_th_tags(source: str, sort_fn: str) -> list[str]:
    """Every ``<th>`` opening tag whose onclick calls *sort_fn*."""
    return [t for t in _TH_TAG.findall(source) if f"{sort_fn}(" in t]


class TestEverySortableHeaderDeclaresItsSortState:
    @pytest.mark.parametrize(("template", "sort_fn", "expected"), _SORTABLE_TABLES)
    def test_the_headers_are_where_we_think_they_are(
        self, template: str, sort_fn: str, expected: int
    ) -> None:
        """If this count moves, the case below is no longer covering the table."""
        tags = _sortable_th_tags(_source(template), sort_fn)
        assert len(tags) == expected, (
            f"{template}: expected {expected} headers calling {sort_fn}, found {len(tags)}"
        )

    @pytest.mark.parametrize(("template", "sort_fn", "expected"), _SORTABLE_TABLES)
    def test_each_one_carries_aria_sort_none_at_rest(
        self, template: str, sort_fn: str, expected: int
    ) -> None:
        for tag in _sortable_th_tags(_source(template), sort_fn):
            assert 'aria-sort="none"' in tag, (
                f"{template}: a header calling {sort_fn} has no aria-sort, so its "
                f"sort state exists only as a glyph:\n  {tag}"
            )

    @pytest.mark.parametrize(("template", "sort_fn", "expected"), _SORTABLE_TABLES)
    def test_the_sort_function_writes_both_directions(
        self, template: str, sort_fn: str, expected: int
    ) -> None:
        source = _source(template)
        body = source[source.index(f"function {sort_fn}("):]
        # Up to the next top-level function, so threatSort's body cannot pass
        # on childSort's writes.
        nxt = body.find("\n  function ", 1)
        if nxt > 0:
            body = body[:nxt]
        assert "'ascending'" in body, f"{sort_fn} never sets aria-sort=ascending"
        assert "'descending'" in body, f"{sort_fn} never sets aria-sort=descending"
        assert "aria-sort" in body, f"{sort_fn} never touches aria-sort"

    def test_columns_that_do_not_sort_are_not_advertised_as_sortable(self) -> None:
        """aria-sort on a fixed column would promise an action that is not there."""
        for template, sort_fn, _ in _SORTABLE_TABLES:
            for tag in _TH_TAG.findall(_source(template)):
                if f"{sort_fn}(" in tag:
                    continue
                if "Sort(" in tag:  # another table's sortable header in the same file
                    continue
                assert "aria-sort" not in tag, (
                    f"{template}: a non-sortable header claims a sort state:\n  {tag}"
                )


class TestTheGeometryPanelEscapeIsScopedToThePanel:
    def test_the_keydown_listener_is_not_on_document(self) -> None:
        source = _source("intercept_geometry.html")
        assert "document.addEventListener('keydown'" not in source, (
            "a document-level Escape handler closes the panel from anywhere on "
            "the console, including the sweep search box in another hero tab"
        )
        assert "panel.addEventListener('keydown'" in source

    def test_escape_is_the_only_key_that_closes_it(self) -> None:
        source = _source("intercept_geometry.html")
        assert "event.key !== 'Escape'" in source

    def test_nothing_is_left_on_window_to_be_cleaned_up(self) -> None:
        """A listener that dies with the node needs no global bookkeeping."""
        assert "__spectreGeometryKeydown" not in _source("intercept_geometry.html")


class TestTheGeometryPanelManagesFocus:
    def test_the_panel_has_a_heading_to_send_focus_to(self) -> None:
        source = _source("intercept_geometry.html")
        assert 'id="geom-panel-heading"' in source
        assert 'role="heading"' in source
        assert 'tabindex="-1"' in source, "the heading must be focusable, not tabbable"
        assert 'aria-labelledby="geom-panel-heading"' in source, "the panel is named by it"

    def test_focus_moves_into_the_panel_on_open(self) -> None:
        source = _source("intercept_geometry.html")
        assert re.search(r"getElementById\('geom-panel-heading'\);\s*\n\s*if \(heading\) \{ heading\.focus\(\); \}", source), (
            "the heading is never focused, so opening the panel leaves the "
            "keyboard operator outside it"
        )

    def test_focus_returns_to_the_opener_on_close(self) -> None:
        source = _source("intercept_geometry.html")
        close = source[source.index("function spectreCloseGeometryPanel"):]
        close = close[:close.index("\n  }")]
        assert "opener.focus()" in close, (
            "on close focus falls to body and the operator restarts from the "
            "top of the console"
        )

    def test_the_focused_heading_is_visible(self) -> None:
        """Measured 4.95:1 on the ops panel and 4.66:1 on steel, floor 3:1."""
        source = _source("intercept_geometry.html")
        assert "#geom-panel-heading:focus { outline: 2px solid currentColor; }" in source


class TestTheSweepRowSpeaksRatherThanHovers:
    def test_the_mouse_worded_title_is_gone(self) -> None:
        source = _source("threat_sweep.html")
        assert "Click to expand" not in source, (
            "mouse language on a row that is deliberately keyboard-activatable, "
            "carried by a title attribute nothing announces reliably"
        )

    def test_the_chevron_carries_the_profile_count_as_a_name(self) -> None:
        source = _source("threat_sweep.html")
        assert re.search(
            r'class="threat-chevron"[^>]*role="img"[^>]*aria-label="\{\{ group\.profile_count \}\}',
            source, re.S,
        ), "the count must name the chevron, which is the glyph carrying it"

    def test_the_row_text_is_unchanged_so_the_filter_still_works(self) -> None:
        """threatFilter() searches row textContent; hidden text would pollute it."""
        source = _source("threat_sweep.html")
        assert "sr-only" not in source


class TestChildSortSurvivesAGroupWithIntel:
    def test_only_real_child_rows_are_sorted(self) -> None:
        """The PAIR intel row is one cell with a colspan.

        It carries .threat-children-N like the data rows, so it was collected
        as one, and ``a.cells[col]`` came back undefined: the comparator threw
        on .textContent and child sort did nothing at all for any group that
        had target intel. An aria-sort written after the sort would never have
        been reached.
        """
        source = _source("threat_sweep.html")
        assert "r.id.indexOf('threat-row-') === 0" in source, (
            "childSort collects rows by class alone, so the single-cell intel "
            "row reaches the comparator and throws"
        )
