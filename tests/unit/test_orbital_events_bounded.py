"""Orbital-event search stops when it has what it needs, and stays off the loop.

Audit F-040. find_orbital_events stepped the whole scenario window at 30 s
with no early exit, and the window was bounded only by stop > start; it ran
on the event loop, so a long scenario stalled every request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.astro import events
from spectre.astro.propagator import TLEOrbit
from tests.unit.test_astro import ISS_TLE

_START = datetime(2024, 2, 14, tzinfo=UTC)
# Equatorial and circular: no node crossings, so the quota is never met.
_EQUATORIAL = (
    "1 90001U 26001A   24045.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90001   0.0000  95.0000 0001000   0.0000  10.0000 15.00000000    10"
)


def _count_propagations(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]
    real = TLEOrbit.propagate

    def counted(self: TLEOrbit, t: datetime) -> Any:
        calls[0] += 1
        return real(self, t)

    monkeypatch.setattr(TLEOrbit, "propagate", counted)
    return calls


def test_the_scan_stops_once_every_type_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_propagations(monkeypatch)
    found = events.find_orbital_events(ISS_TLE, _START, _START + timedelta(days=30))
    assert len(found) == 12, "three of each of the four types"
    # Three ISS orbits are under five hours, 600 steps of 30 s; not 86,400.
    assert calls[0] < 1000


def test_the_scan_is_capped_when_the_quota_cannot_be_met(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_propagations(monkeypatch)
    events.find_orbital_events(_EQUATORIAL, _START, _START + timedelta(days=365))
    assert calls[0] <= events._MAX_SCAN_S / 30.0 + 2
