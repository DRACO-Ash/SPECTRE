"""Low findings in the astro and config modules (audit step 4, Low).

Each test names its finding. Several were sign, guard or wording defects too
small to need a module of their own.
"""

from __future__ import annotations

import ast
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from spectre.astro import constants, tactical, transfers
from spectre.astro.constants import GEO_RADIUS, MU_EARTH, R_EARTH
from spectre.astro.propagator import StateVector, state_to_keplerian

_ROOT = Path(__file__).resolve().parents[2]


class TestF191RetrogradeCircularEquatorial:
    """True longitude ran backwards for a retrograde circular equatorial orbit."""

    @staticmethod
    def _ta(angle_deg: float) -> float:
        r = GEO_RADIUS
        v = math.sqrt(MU_EARTH / r)
        a = math.radians(angle_deg)
        # Moving clockwise seen from +z: inclination 180 degrees.
        state = StateVector(
            epoch=datetime(2026, 1, 1, tzinfo=UTC),
            r=np.array([r * math.cos(a), r * math.sin(a), 0.0]),
            v=np.array([v * math.sin(a), -v * math.cos(a), 0.0]),
        )
        return state_to_keplerian(state).ta

    def test_it_advances_in_the_direction_of_motion(self) -> None:
        # A quarter turn of motion from +x (angle 0) reaches angle -90.
        assert (self._ta(-90.0) - self._ta(0.0)) % 360.0 == pytest.approx(90.0)

    def test_it_is_measured_from_the_x_axis_along_the_motion(self) -> None:
        assert self._ta(90.0) == pytest.approx(270.0)


class TestF192BiellipticGuards:
    def test_an_intermediate_radius_inside_the_target_is_refused(self) -> None:
        with pytest.raises(ValueError, match="rb"):
            transfers.bielliptic(7000.0, 42164.0, 30000.0)

    def test_a_radius_inside_the_earth_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Earth"):
            transfers.bielliptic(6000.0, 42164.0, 90000.0)

    def test_a_valid_transfer_still_prices(self) -> None:
        assert transfers.bielliptic(7000.0, 105000.0, 210000.0).total_delta_v > 0.0


def test_f193_no_unused_constant_in_the_config_module() -> None:
    """Seven unit and frame constants were declared and read nowhere; one said ICRF."""
    source = (_ROOT / "spectre" / "config" / "constants.py").read_text(encoding="utf-8")
    names = [t.id for n in ast.parse(source).body if isinstance(n, ast.AnnAssign | ast.Assign)
             for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)]
    users = "\n".join(p.read_text(encoding="utf-8") for p in (_ROOT / "spectre").rglob("*.py")
                      if p.name != "constants.py" or p.parent.name != "config")
    assert [n for n in names if not re.search(rf"\b{n}\b", users)] == []


class TestF194F195F203Constants:
    def test_no_earth_radius_literal_outside_the_constants_module(self) -> None:
        hits = [str(p.relative_to(_ROOT)) for p in (_ROOT / "spectre").rglob("*.py")
                if p.name != "constants.py" and "6378.137" in p.read_text(encoding="utf-8")]
        assert hits == []

    def test_the_geo_band_is_built_from_its_tolerance(self) -> None:
        assert constants._MEO_MAX_ALT == constants._GEO_BAND_ALT - constants._GEO_TOL_ALT
        assert constants._GEO_MAX_ALT == constants._GEO_BAND_ALT + constants._GEO_TOL_ALT

    def test_the_sidereal_day_is_the_iers_value(self) -> None:
        assert constants.SIDEREAL_DAY == 86164.0905

    def test_the_perigee_floor_is_named(self) -> None:
        assert tactical.MIN_PERIGEE_ALT_KM == 100.0


class TestF196CollisionAvoidanceMiss:
    """Each strategy reported the requested miss, not the separation it reaches."""

    def test_the_along_track_miss_includes_its_radial_swing(self) -> None:
        plan = tactical.collision_avoidance(R_EARTH + 500.0, 2.0, 1500.0)
        n = math.sqrt(MU_EARTH / (R_EARTH + 500.0) ** 3)
        t = 1500.0
        dv = plan.along_track.delta_v
        radial = 2.0 * dv / n * (1.0 - math.cos(n * t))
        along = dv * (4.0 * math.sin(n * t) - 3.0 * n * t) / n
        assert plan.along_track.miss_distance_km == pytest.approx(math.hypot(radial, along))
        assert plan.along_track.miss_distance_km > 2.0

    def test_the_out_of_plane_miss_is_exactly_the_target(self) -> None:
        plan = tactical.collision_avoidance(R_EARTH + 500.0, 2.0, 1500.0)
        assert plan.out_of_plane.miss_distance_km == pytest.approx(2.0)


def test_f200_a_long_time_of_flight_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from spectre.astro import cw_geometry

    valid, notes = cw_geometry._check_validity(10.0, 0.0001, cw_geometry._TOF_WARN_HOURS + 1.0)
    assert valid, "a long flight is a caveat, not an invalid geometry"
    with caplog.at_level(logging.WARNING):
        cw_geometry._log_validity(notes)
    assert "Time of flight" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        cw_geometry._log_validity(cw_geometry._check_validity(10.0, 0.0001, 1.0)[1])
    assert caplog.text == ""


class TestPatternOfLifeLows:
    def test_f210_the_panel_reads_the_modules_drift_threshold(self) -> None:
        template = (_ROOT / "spectre/web/templates/partials/pol_results.html").read_text(encoding="utf-8")
        line = next(t for t in template.splitlines() if '"→E" if dr' in t)
        assert "0.005" not in line
        assert "pol.drift_stationary_deg_day" in line

    def test_f207_gmst_is_named_for_what_it_computes(self) -> None:
        from spectre.astro import pattern_of_life

        assert not hasattr(pattern_of_life, "_gst_deg")
        assert "Mean Sidereal" in (pattern_of_life._gmst_deg.__doc__ or "")

    def test_f211_one_set_of_secular_rates(self) -> None:
        from spectre.astro import pattern_of_life

        assert not hasattr(pattern_of_life, "_j2_raan_rate")
        assert not hasattr(pattern_of_life, "_j2_argp_rate")

    def test_f212_a_missing_longitude_is_a_gap_in_the_chart(self) -> None:
        source = (_ROOT / "spectre/astro/pattern_of_life.py").read_text(encoding="utf-8")
        line = next(t for t in source.splitlines() if "chart_lons " in t and "=" in t)
        assert line.rstrip().endswith("else None for r in cr]")


def test_f187_every_vendored_script_is_in_the_manifest_as_it_is() -> None:
    import hashlib
    import json

    static = _ROOT / "spectre" / "web" / "static"
    manifest = json.loads((static / "vendored.json").read_text(encoding="utf-8"))["packages"]
    assert sorted(p["file"] for p in manifest) == sorted(f.name for f in static.glob("*.js"))
    for p in manifest:
        body = (static / p["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == p["sha256"], p["file"]
        assert p["version"].encode() in body[:2000] or f'version:"{p["version"]}"'.encode() in body, p["file"]
