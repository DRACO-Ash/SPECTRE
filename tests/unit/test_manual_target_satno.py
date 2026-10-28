"""A pasted element set with no readable catalogue number cannot break a sweep.

Audit F-124. ``satno_from_tle`` returns None for a line 1 it cannot read (an
Alpha-5 number, for one), and the sweep wrapped it in ``str()``, so the target
was numbered "None". That looked like a stale set, so with UDL connected the
last-chance fetch ran ``int("None")`` inside a gather with no
``return_exceptions`` and the whole sweep came back HTTP 500. Without UDL the
operator saw "None" as the target's NORAD number.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.models import ThreatTarget
from spectre.web.routes import threat
from spectre.web.routes.udl import FetchedElset
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO

_ALPHA5 = "\n".join(
    ["1 A0001" + line[7:] if line.startswith("1 ") else line for line in _BLUE_GEO.splitlines()]
)


def _state(**extra: Any) -> SimpleNamespace:
    base = {
        "manual_sweep_tles": [{"name": "ALPHA", "tle": _ALPHA5, "confidence": "HIGH"}],
        "hrr_tle_cache": {}, "hrr_tle_data_mode": {},
        "udl_username": "u", "udl_password": "p", "udl_data_mode": "REAL", "udl_tle_source": None,
    }
    base.update(extra)
    return SimpleNamespace(**base)


def test_an_unreadable_number_is_blank_not_none() -> None:
    targets: list[ThreatTarget] = []
    threat._append_manual_targets(_state(), targets)
    assert targets[0].target_satno == ""


async def test_manual_targets_are_not_fetched_and_a_failed_fetch_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectre.web.routes import udl

    asked: list[int] = []

    async def _fetch(satno: int, *_a: Any, **_k: Any) -> Any:
        asked.append(satno)
        if satno == 2:
            raise ConnectionError("UDL timed out")
        return FetchedElset("TLE", "REAL", "18th SPCS")

    monkeypatch.setattr(udl, "fetch_tle_for_satno", _fetch)
    targets = [
        ThreatTarget("PASTED", "12345", "manual", None),
        ThreatTarget("ONE", "1", "hrr", 1),
        ThreatTarget("TWO", "2", "hrr", 1),
    ]
    errors: list[str] = []
    state = _state()
    await threat._fetch_missing_target_tles(state, targets, errors)
    assert sorted(asked) == [1, 2], "an operator's pasted set is never replaced by a fetch"
    assert state.hrr_tle_cache == {"1": "TLE"}
    assert errors == ["TLE fetch failed for TWO (2): UDL timed out"]
