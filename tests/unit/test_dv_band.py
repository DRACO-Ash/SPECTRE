"""The worst case's delta-V carries a band from element-set age (SPC-005, red team finding 6).

On the GEO fixture pair, red and blue share every element but mean anomaly,
so the winning intercepts are short co-orbital ones and the band can be read
against the red team's measured 0.2 m/s or so per kilometre. The minimum-time
intercept spends the whole budget by construction, so its band is on flight
time instead.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.models import ThreatTarget
from spectre.web.routes import threat
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO

_EPOCH = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
_TARGET = ThreatTarget("BLUE-GEO", "", "manual", None)
_CO_ORBITAL = ("lambert", "hohmann", "phasing", "vbar_hop", "hbar_hop", "bielliptic")


def _band(now: datetime, methods: tuple[str, ...] = ()) -> tuple[dict[str, str], Any]:
    state = SimpleNamespace(manual_sweep_tles=[{"name": "BLUE-GEO", "tle": _BLUE_GEO}], hrr_tle_cache={},
                            hrr_objects=[], tle_of=lambda _n: None)
    basis = threat._sweep_basis(state, [_TARGET], manual={"BLUE-GEO": _BLUE_GEO}, red_regime="GEO",
                                max_dv_m_s=500.0, now=now)
    entries, _, _ = threat._run_target_sweep(basis.frozen, [_TARGET], basis.manual_tle_by_name, _RED_GEO, "GEO",
                                             threat._compute_epochs(_RED_GEO, now), 500.0)
    entries = [e for e in entries if not methods or e.method in methods]
    entries.sort(key=lambda e: threat.warning_time_rank(e.delta_v_m_s, e.tof_hours, 500.0, e.arrives))
    return threat._dv_band(state, entries, _RED_GEO, basis), entries[0]


def _spread(text: str, unit: str) -> float:
    found = re.search(r"± ([0-9.]+) " + unit, text)
    assert found is not None, text
    return float(found.group(1))


def test_the_band_says_what_it_rests_on() -> None:
    band, worst = _band(_EPOCH + timedelta(hours=6), _CO_ORBITAL)
    assert worst.arrives and worst.method != "min_time"
    assert band["dv_band"].startswith("± ")
    assert "moved 2 km and the target's 2 km along track" in band["dv_band_basis"]
    assert "A sensitivity, not a confidence interval." in band["dv_band_basis"]


def test_older_element_sets_widen_the_band() -> None:
    fresh, _ = _band(_EPOCH + timedelta(hours=6), _CO_ORBITAL)
    stale, _ = _band(_EPOCH + timedelta(days=5), _CO_ORBITAL)
    assert "moved 7 km" in stale["dv_band_basis"]
    assert _spread(stale["dv_band_basis"], "m/s") > _spread(fresh["dv_band_basis"], "m/s")


def test_a_minimum_time_intercept_bands_its_flight_time_not_its_budget() -> None:
    """It spends the whole budget by construction: a delta-V band would read a misleading 0."""
    band, worst = _band(_EPOCH + timedelta(hours=6))
    stale, _ = _band(_EPOCH + timedelta(days=5))
    assert worst.method == "min_time"
    assert band["dv_band"] == "(the budget)"
    assert "spends the whole budget by construction" in band["dv_band_basis"]
    assert _spread(stale["dv_band_basis"], "min") > _spread(band["dv_band_basis"], "min")


def test_no_band_without_the_target_element_set() -> None:
    state = SimpleNamespace(manual_sweep_tles=[], hrr_tle_cache={}, hrr_objects=[], tle_of=lambda _n: None)
    _, worst = _band(_EPOCH + timedelta(hours=6))
    basis = threat._sweep_basis(state, [_TARGET], manual={}, red_regime="GEO", max_dv_m_s=500.0, now=_EPOCH)
    assert threat._dv_band(state, [worst], _RED_GEO, basis) == {}


def test_too_few_resolves_give_no_band(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threat, "_band_runs", lambda *_a, **_k: [(42.0, 1.0)])
    band, _ = _band(_EPOCH + timedelta(hours=6))
    assert band == {}


def test_both_orbits_are_moved_both_ways_by_their_own_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.astro.along_track import shift_along_track

    moved: list[tuple[str, float]] = []

    def spy(tle: str, km: float) -> str:
        moved.append(("red" if tle == _RED_GEO else "target", km))
        return shift_along_track(tle, km)

    monkeypatch.setattr(threat, "shift_along_track", spy)
    _band(_EPOCH + timedelta(hours=6), _CO_ORBITAL)
    assert sorted(set(moved)) == [("red", -2.25), ("red", 2.25), ("target", -2.25), ("target", 2.25)]
