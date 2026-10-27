"""The sweep's target cap keeps what the operator asked for.

Audit F-126. Manual targets were appended after the HRR list, so the 100
target cap dropped every pasted target first, without naming them, and the
cap counted HRR objects in an incompatible regime that the sweep then
skipped anyway.
"""

from __future__ import annotations

from types import SimpleNamespace

from spectre.domain.models import ThreatTarget
from spectre.web.routes import threat
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO
from tests.unit.test_astro import ISS_TLE


def _hrr(n: int, tle: str, prefix: str) -> tuple[list[ThreatTarget], dict[str, str]]:
    targets = [ThreatTarget(f"{prefix}-{i}", f"{prefix}{i}", "hrr", 1) for i in range(n)]
    return targets, {t.target_satno: tle for t in targets}


def test_a_manual_target_survives_the_cap_and_the_dropped_are_named() -> None:
    hrr, cache = _hrr(101, _BLUE_GEO, "GEO")
    manual = ThreatTarget("PASTED", "", "manual", None)
    errors: list[str] = []
    kept = threat._cap_targets(
        SimpleNamespace(hrr_tle_cache=cache), [*hrr, manual], {"PASTED": _BLUE_GEO}, "GEO", errors,
    )
    assert kept[0] is manual
    assert len(kept) == threat._MAX_SWEEP_TARGETS
    assert any("GEO-99" in e and "GEO-100" in e for e in errors), errors


def test_an_incompatible_regime_does_not_take_a_slot() -> None:
    leo, leo_cache = _hrr(1, ISS_TLE, "LEO")
    geo, geo_cache = _hrr(100, _BLUE_GEO, "GEO")
    errors: list[str] = []
    kept = threat._cap_targets(
        SimpleNamespace(hrr_tle_cache={**leo_cache, **geo_cache}), [*leo, *geo], {}, "GEO", errors,
    )
    assert kept == geo
    assert errors == ["LEO-0: skipped — GEO red vs LEO target (regime mismatch)"]
