"""Longitude spans and predictions wrap at the antimeridian (audit F-117).

GEO longitudes arrive in (-180, 180], but the span was max - min and the
predictions were start + drift x days, unwrapped. An object holding a slot
at 180 degrees read a span of nearly 360 degrees, was called a GEO belt
roamer and took the full longitude-coverage anomaly score; a prediction
could leave the valid interval.
"""

from __future__ import annotations

import pytest

from spectre.domain.pol_assessment import _predicted_longitudes, circular_span_deg, wrap_longitude


@pytest.mark.parametrize(("lons", "span"), [
    ([179.9, -179.9], 0.2),
    ([-179.9, 179.9, 180.0], 0.2),
    ([10.0, 20.0, 15.0], 10.0),
    ([0.0, 120.0, -120.0], 240.0),
    ([42.0], 0.0),
    ([], 0.0),
])
def test_the_span_is_the_shortest_arc_holding_every_longitude(lons: list[float], span: float) -> None:
    assert circular_span_deg(lons) == pytest.approx(span)


@pytest.mark.parametrize(("raw", "wrapped"), [
    (181.0, -179.0), (-181.0, 179.0), (180.0, 180.0), (-180.0, 180.0), (540.0, 180.0), (12.5, 12.5),
])
def test_wrapping_lands_in_minus_180_exclusive_to_180_inclusive(raw: float, wrapped: float) -> None:
    assert wrap_longitude(raw) == pytest.approx(wrapped)


def test_a_prediction_across_the_antimeridian_stays_valid() -> None:
    last = type("Rec", (), {"geo_longitude_deg": 179.0})()
    predictions = _predicted_longitudes(last, 0.1)
    assert predictions == (-178.0, -175.0, -172.0)


def test_a_slot_at_the_antimeridian_is_not_a_belt_roamer() -> None:
    from types import SimpleNamespace

    from spectre.domain import pol_assessment

    records = [SimpleNamespace(geo_longitude_deg=lon, geo_drift_rate_deg_day=0.0)
               for lon in (179.95, -179.98, 179.97, -179.96)]
    pol = SimpleNamespace(records=records, span_days=60.0, drift_phases=[])
    propellant = SimpleNamespace(propellant_used_pct=0.0, rate_multiple=0.0, annual_rate_m_s=0.0, routine_annual_m_s=2.0)
    components = pol_assessment._Components(None, propellant, None)
    intel = pol_assessment._assess_intel(pol, "GEO", [], components)
    assert "roamer" not in intel.mission_profile
    assert "Traverses" not in intel.behaviour_class
    assert "relocation" not in intel.mission_profile
