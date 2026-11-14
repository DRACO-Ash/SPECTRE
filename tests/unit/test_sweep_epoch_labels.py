"""Burn epochs are named only where the name means something (SPC-004, red team finding 3).

On a station-kept GEO orbit apogee and perigee are 13 km apart and the nodes
are set by a twentieth of a degree of inclination, so "burns at perigee" implied
an energy-optimal choice that does not exist. Those epochs are now labelled as
the time samples they are.
"""

from __future__ import annotations

from datetime import UTC, datetime

from spectre.web.routes.threat import _compute_epochs, _epoch_note
from tests.integration.test_all_intercepts_ranking import _RED_GEO
from tests.unit.test_astro import ISS_TLE

# Each fixture is judged at its own epoch: two years on, SGP4 finds no events
# for the ISS set at all.
_NOW = datetime(2026, 3, 1, tzinfo=UTC)
_ISS_NOW = datetime(2024, 2, 14, 12, tzinfo=UTC)
_NAMED = {"apogee", "perigee", "asc_node", "desc_node"}
# The ISS set with its eccentricity raised from 0.0003 to 0.02.
_ECCENTRIC = ISS_TLE.replace(" 0003399 ", " 0200000 ")


def _labels(tle: str, now: datetime = _NOW) -> set[str]:
    return {label for label, _ in _compute_epochs(tle, now)[1:]}


def test_a_station_kept_geo_orbit_names_nothing() -> None:
    labels = _labels(_RED_GEO)
    assert labels, "the day's samples are still taken"
    assert not labels & _NAMED
    assert all(label.startswith("now +") and label.endswith(" h") for label in labels)


def test_a_near_circular_inclined_orbit_keeps_its_nodes_only() -> None:
    labels = _labels(ISS_TLE, _ISS_NOW)
    assert not labels & {"apogee", "perigee"}
    assert labels & {"asc_node", "desc_node"}


def test_an_eccentric_orbit_keeps_its_apsides() -> None:
    assert _labels(_ECCENTRIC, _ISS_NOW) & {"apogee", "perigee"}


def test_the_note_says_why_for_geo() -> None:
    note = _epoch_note(_RED_GEO)
    assert "eccentricity (0.0001)" in note
    assert "inclination (0.05°)" in note
    assert "phase angle" in note


def test_no_note_where_every_name_holds() -> None:
    assert _epoch_note(_ECCENTRIC) == ""


def test_the_phase_label_at_the_fixtures_own_epoch() -> None:
    # Same elements but mean anomaly, 10 against 11 degrees: 1.0 degree apart.
    from spectre.web.routes.threat import _phase_label
    from tests.integration.test_all_intercepts_ranking import _BLUE_GEO

    assert _phase_label(_RED_GEO, _BLUE_GEO, _NOW) == "1.0\u00b0 ahead of the interceptor"
    assert _phase_label(_BLUE_GEO, _RED_GEO, _NOW) == "1.0\u00b0 behind the interceptor"
