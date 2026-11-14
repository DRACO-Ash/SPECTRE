"""The UDL current fetch and history fetch refuse a set dated in the future by the time it arrives (SPC-226, F-38).

The V0.42 review's mutants M16 and M16b dropped the clock from the two places the UDL route runs the acceptance check
itself, and no test failed. Each fetch is now driven through a stubbed UDL answering a set 3 days ahead of the wall
clock: the current fetch refuses it, naming the epoch, and the history fetch leaves it out and says so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.web.elsets import RefusedElset
from spectre.web.routes.udl import fetch_tle_for_satno, fetch_tle_history_for_satno
from tests.unit.test_elset_freshness import _record, _tle, _udl_answering

_AHEAD = "a set dated in the future would read as current, so check its epoch and this server's clock"


@pytest.mark.asyncio
async def test_the_current_fetch_refuses_a_set_dated_in_the_future() -> None:
    ahead = datetime.now(UTC) + timedelta(days=3)
    with _udl_answering([_record(ahead)]):
        got = await fetch_tle_for_satno(50322, "u", "p")
    assert isinstance(got, RefusedElset)
    assert len(got.check.failures) == 1
    assert got.check.failures[0].startswith(f"its epoch, {ahead:%Y-%m-%d %H:%M} UTC, is 3.0 d after the time")
    assert got.check.failures[0].endswith(_AHEAD)


@pytest.mark.asyncio
async def test_the_current_fetch_takes_a_set_dated_now() -> None:
    now = datetime.now(UTC) - timedelta(minutes=1)
    with _udl_answering([_record(now)]):
        got = await fetch_tle_for_satno(50322, "u", "p")
    assert not isinstance(got, RefusedElset) and got is not None
    assert got.tle == _tle(now)


@pytest.mark.asyncio
async def test_the_history_fetch_leaves_out_a_set_dated_in_the_future_and_says_so() -> None:
    now = datetime.now(UTC)
    past, ahead = now - timedelta(days=1), now + timedelta(days=3)
    with _udl_answering([_record(past), _record(ahead)]):
        history = await fetch_tle_history_for_satno(50322, "u", "p")
    assert list(history) == [_tle(past)]
    assert len(history.refused) == 1
    assert history.refused[0].failures[0].endswith(_AHEAD)
    refusal = history.refusal("RX")
    assert refusal is not None and refusal.startswith("1 element set in the history for RX was refused: its epoch")
