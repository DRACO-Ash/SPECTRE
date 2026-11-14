"""A failed actor refresh in the screen is reported, not passed over.

Audit F-135. The sweep records a failed last-chance fetch against its
target; the screen had no else branch, so an actor whose refresh failed was
screened on its bootstrap or stale set with no note, and one that raised
took the screen down with it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.models import ThreatActor
from spectre.web.routes import threat
from spectre.web.routes.udl import FetchedElset


async def test_each_failed_refresh_is_noted(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.web.routes import udl

    async def _fetch(satno: int, *_a: Any, **_k: Any) -> Any:
        if satno == 1:
            return None
        if satno == 2:
            raise ConnectionError("UDL timed out")
        return FetchedElset("TLE", "REAL", "18th SPCS")

    monkeypatch.setattr(udl, "fetch_tle_for_satno", _fetch)
    state = SimpleNamespace(
        hrr_tle_cache={}, hrr_tle_data_mode={},
        udl_username="u", udl_password="p", udl_data_mode="REAL", udl_tle_source=None,
    )
    actors = [ThreatActor(actor_name=n, actor_satno=s, country="CHN", regime="GEO")
              for n, s in (("ONE", "1"), ("TWO", "2"), ("THREE", "3"))]
    notes = await threat._refresh_actor_tles(state, actors)
    assert notes == [
        "ONE (1): live element set not fetched; screened on the set already held",
        "TWO (2): live element set not fetched (UDL timed out); screened on the set already held",
    ]
    assert state.hrr_tle_cache == {"3": "TLE"}
