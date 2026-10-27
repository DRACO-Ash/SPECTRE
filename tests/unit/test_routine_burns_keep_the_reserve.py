"""Routine station-keeping does not draw on the discretionary reserve.

Audit F-118. Table 2 separates a platform's lifetime budget into the share
committed to routine operations and a discretionary reserve. The reserve
figure subtracted every confirmed manoeuvre, station-keeping included, so a
well-behaved GEO object read as having exhausted its reserve within a few
years of ordinary north-south maintenance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.domain.manoeuvre_calibration import platform_class_for_regime
from spectre.domain.pol_assessment import assess_pattern_of_life

_START = datetime(2021, 1, 1, tzinfo=UTC)
_FORTNIGHTS_IN_5_YEARS = 130


def _burn(day: float, dv_m_s: float, channel: str) -> SimpleNamespace:
    return SimpleNamespace(
        epoch=_START + timedelta(days=day),
        delta_v_km_s=dv_m_s / 1000.0,
        breakdown=SimpleNamespace(components=(SimpleNamespace(channel=channel, dv_km_s=dv_m_s / 1000.0),)),
        tle_after=SimpleNamespace(alt_km=35786.0, geo_longitude_deg=None),
        delta_alt_km=0.0,
    )


def _pol(burns: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        regime="GEO", manoeuvres=burns, candidate_manoeuvres=[],
        span_days=_FORTNIGHTS_IN_5_YEARS * 14.0, records=[], drift_phases=[],
        interval_stats=None, noise_model=None,
    )


def _station_keeping() -> list[SimpleNamespace]:
    return [_burn(i * 14.0, 1.8, "normal") for i in range(_FORTNIGHTS_IN_5_YEARS)]


def test_five_years_of_station_keeping_keeps_the_full_reserve() -> None:
    a = assess_pattern_of_life(_pol(_station_keeping()))
    assert all(v.is_routine for v in a.manoeuvres), "fixture must be routine throughout"
    assert a.propellant.spent_since_reset_m_s == pytest.approx(_FORTNIGHTS_IN_5_YEARS * 1.8)
    assert a.propellant.discretionary_remaining_m_s == pytest.approx(
        platform_class_for_regime("GEO").discretionary_max_m_s,
    )


def test_a_discretionary_burn_still_draws_on_the_reserve() -> None:
    burns = [*_station_keeping(), _burn(400.0, 34.0, "along_track")]
    a = assess_pattern_of_life(_pol(burns))
    assert sum(not v.is_routine for v in a.manoeuvres) == 1
    assert a.propellant.discretionary_remaining_m_s == pytest.approx(
        platform_class_for_regime("GEO").discretionary_max_m_s - 34.0, abs=0.1,
    )


def test_a_reset_counts_only_discretionary_spend_since() -> None:
    burns = [_burn(10.0, 34.0, "along_track"), *_station_keeping()]
    a = assess_pattern_of_life(_pol(burns), _START + timedelta(days=20))
    assert a.propellant.discretionary_remaining_m_s == pytest.approx(
        platform_class_for_regime("GEO").discretionary_max_m_s,
    )
