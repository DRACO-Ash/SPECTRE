"""The HRR search dropdown must build nodes, not markup.

The dropdown was a stored cross-site scripting hole, and an unusual one: the
server escaped the name correctly on the way out, and the browser handed it
back decoded. ``_hrrGatherRows`` reads each cell with ``textContent``, so a
satellite name rendered into the table as ``&lt;img src=x onerror=...&gt;`` is
live markup again by the time the search controller sees it. The old builder
concatenated that into ``innerHTML``, which executed it in the analyst's
authenticated session the moment they typed a matching character. Names reach
the HRR tables from UDL and from manual entry, so planting one needed no
privilege at all.

Proved in Chromium before and after: against the old block the payload set a
window flag and an ``<img>`` element appeared in the dropdown; against the
current block the name renders as text, no element appears and the flag stays
false. That run needs a browser, which the Test stage has no reason to carry,
so what travels with the suite is this: a reading of the shipped block that
fails if the string-building habit comes back.

The search term in that browser run is worth recording, because the first
attempt proved nothing. Searching for ``img`` against a name of ``<img ...>``
splits the tag across the ``<mark>`` the highlighter inserts, so the payload
could not fire even against the vulnerable code and the harness passed either
way. The term has to sit in a part of the name outside the tag.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "spectre" / "web" / "templates" / "operator.html"
)


def _hrr_controller() -> str:
    """The one <script> block holding the HRR search controller."""
    source = _TEMPLATE.read_text(encoding="utf-8")
    blocks = re.findall(r"<script>(.*?)</script>", source, re.S)
    owning = [b for b in blocks if "_hrrGatherRows" in b]
    assert len(owning) == 1, (
        f"expected exactly one HRR controller block, found {len(owning)}; "
        "the guards below address one block and would silently skip the rest"
    )
    return owning[0]


class TestTheDropdownIsBuiltFromNodes:
    def test_no_innerhtml_assignment_takes_a_variable(self) -> None:
        """A literal is fine. A variable is how the payload got in.

        ``dropdown.innerHTML = '<div class="hrr-dd-empty">No matches</div>'``
        is a constant and carries nothing. ``dropdown.innerHTML = html`` is the
        defect, whatever ``html`` was built from three lines earlier.
        """
        offenders = []
        for line in _hrr_controller().splitlines():
            match = re.search(r"\.innerHTML\s*\+?=\s*(?P<rhs>.*)$", line)
            if match and not match.group("rhs").lstrip().startswith(("'", '"', "`")):
                offenders.append(line.strip())
        assert not offenders, (
            "every innerHTML assignment in the HRR controller must take a "
            f"string literal; these do not: {offenders}"
        )

    def test_the_entry_fields_reach_the_dom_as_text(self) -> None:
        """Each field the dropdown shows must go through a text sink."""
        block = _hrr_controller()
        assert "createTextNode" in block, "no text node is built at all"
        assert "side.textContent" in block, "the side label is not set as text"
        assert "mark.textContent" in block, "the highlighted run is not set as text"

    def test_the_string_returning_highlighter_is_gone(self) -> None:
        """Its return value was concatenated, so its existence is the risk."""
        block = _hrr_controller()
        assert "_hrrHighlightText" not in block, (
            "the highlighter that returned an HTML string is back"
        )
        assert "_hrrAppendHighlighted" in block, "the node-building highlighter is missing"

    def test_the_row_handler_is_a_listener_not_an_attribute(self) -> None:
        """An onmousedown attribute has to be assembled as markup to exist."""
        block = _hrr_controller()
        assert "onmousedown=" not in block, "the handler is being written as markup again"
        assert "addEventListener('mousedown'" in block, "no mousedown listener is bound"


class TestTheGathererStillDecodes:
    """The premise, pinned.

    If ``_hrrGatherRows`` ever switched to reading ``innerHTML`` instead of
    ``textContent``, the entries would arrive already escaped and the guards
    above would be guarding nothing. They would all still pass. This is the
    test that notices.
    """

    def test_rows_are_read_with_textcontent(self) -> None:
        block = _hrr_controller()
        gatherer = block[block.index("function _hrrGatherRows") :]
        gatherer = gatherer[: gatherer.index("return entries;")]
        assert gatherer.count("textContent") >= 5, (
            "the gatherer no longer reads all five cells as text"
        )
        assert "innerHTML" not in gatherer, (
            "the gatherer reads markup, so the dropdown's input is no longer "
            "decoded text and these guards describe a threat that moved"
        )


@pytest.mark.parametrize("sink", ["replaceChildren", "appendChild"])
def test_the_dropdown_is_emptied_and_filled_through_the_dom(sink: str) -> None:
    assert sink in _hrr_controller(), f"{sink} is absent; the builder has changed shape"
