"""A graveyard raise is recognised at the IADC protected-region edge.

Audit F-116. The upper edge was 36,186 km: GEO plus 400 km, copied from the
regime band edge. The IADC Space Debris Mitigation Guidelines define the GEO
protected region as GEO altitude plus or minus 200 km, so the edge is
35,986 km. A standard 300 km raise ends near 36,086 km and was labelled
"relocation". The old test passed only because its "300 km" raise ended
700 km above GEO.
"""

from __future__ import annotations

from spectre.astro.constants import _GEO_BAND_ALT
from spectre.domain import pol_assessment
from spectre.domain.manoeuvre_calibration import per_event_station_keeping_m_s


def _label(delta_alt_km: float) -> str:
    ceiling = per_event_station_keeping_m_s("GEO")[0]
    label, _, _ = pol_assessment._classify(
        9.0, "along_track", "GEO", ceiling, alt_after_km=_GEO_BAND_ALT + delta_alt_km, delta_alt_km=delta_alt_km,
    )
    return label


def test_the_edge_is_geo_plus_200_km() -> None:
    assert pol_assessment._GEO_PROTECTED_MAX_ALT_KM == _GEO_BAND_ALT + 200.0


def test_a_300_km_raise_from_geo_is_disposal() -> None:
    assert _label(300.0) == "graveyard disposal"


def test_a_150_km_raise_is_not() -> None:
    assert _label(150.0) == "relocation"
