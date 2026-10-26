"""A session's log holds what it says it holds and no more (audit F-154).

SessionState wrote every line to a 200-entry deque and also to an unbounded
asyncio.Queue that nothing read, so a long shift's log was retained in full
while the docstring promised 200 entries. The queue had no consumer, so it
is gone rather than bounded.
"""

from __future__ import annotations

import sys
from dataclasses import fields

from spectre.web.planning_state import _MAX_LOG_ENTRIES, SessionState


def test_a_thousand_lines_keep_the_newest_200() -> None:
    state = SessionState()
    for i in range(1000):
        state.append_log(f"line {i}")
    assert _MAX_LOG_ENTRIES == 200
    assert len(state.log_entries) == 200
    assert state.log_entries[0] == "line 800"
    assert state.log_entries[-1] == "line 999"


def test_no_other_field_retains_the_log() -> None:
    state = SessionState()
    before = {f.name: sys.getsizeof(getattr(state, f.name)) for f in fields(state)}
    for i in range(1000):
        state.append_log(f"line {i}")
    grown = [
        f.name for f in fields(state)
        if f.name != "log_entries" and sys.getsizeof(getattr(state, f.name)) != before[f.name]
    ]
    assert grown == []
    assert "log_queue" not in {f.name for f in fields(state)}
