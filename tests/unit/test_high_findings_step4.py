"""The five High findings left in step 4 of the audit remediation."""

from __future__ import annotations

import pytest


class TestARaanChangeAgainstTheDriftIsSeen:
    """Audit F-023: magnitudes were subtracted, so +5 against -5 read as 0."""

    @staticmethod
    def _iss_like_daily_rate() -> tuple[float, float, float, float]:
        from spectre.astro.tactical import j2_raan_rate

        a, ecc, inc = 6778.0, 0.0005, 51.6
        return a, ecc, inc, j2_raan_rate(a, ecc, inc)   # about -5 deg/day

    def test_a_node_moved_against_precession_is_detected(self) -> None:
        from spectre.astro.tactical import classify_manoeuvre

        a, ecc, inc, rate = self._iss_like_daily_rate()
        assert rate == pytest.approx(-5.0, abs=0.3)
        result = classify_manoeuvre(a, ecc, inc, 100.0, a, ecc, inc, 105.0, dt_s=86400.0)
        assert "ΔRAAN=" in result.notes, "the node change was cancelled by the drift"
        residual = float(result.notes.split("ΔRAAN=")[1].split("°")[0])
        assert residual == pytest.approx(5.0 - rate, abs=0.01), "about 10 degrees, not 0"

    def test_a_node_that_followed_precession_is_not(self) -> None:
        from spectre.astro.tactical import classify_manoeuvre

        a, ecc, inc, rate = self._iss_like_daily_rate()
        result = classify_manoeuvre(a, ecc, inc, 100.0, a, ecc, inc, 100.0 + rate, dt_s=86400.0)
        assert "ΔRAAN=" not in result.notes

    def test_the_residual_wraps_across_north(self) -> None:
        from spectre.astro.tactical import classify_manoeuvre

        a, ecc, inc, rate = self._iss_like_daily_rate()
        result = classify_manoeuvre(a, ecc, inc, 358.0, a, ecc, inc, (358.0 + rate) % 360.0, dt_s=86400.0)
        assert "ΔRAAN=" not in result.notes, "a drift across 0/360 is not a manoeuvre"


class TestDetectionDoesNotSubtractTheDriftTwice:
    """Found with F-023: the detector compares sets at one instant, then removed
    a day of J2 drift as well."""

    def test_two_tles_days_apart_with_no_manoeuvre_show_no_node_change(self) -> None:
        from spectre.astro.maneuvers import manoeuvre_detect_intercept
        from spectre.astro.pattern_of_life import _parse_tle_epoch
        from tests.unit.test_dv_estimation import _base, _coast

        before = _base()
        after = _coast(before, 2.0)   # the same orbit, two days on, no burn
        start = _parse_tle_epoch(after.splitlines()[0])
        solution = manoeuvre_detect_intercept(before, after, start)
        assert solution.total_delta_v * 1000.0 < 1.0, "a coasting object was charged for a node change"


class TestPhasingRefusesUnequalRadii:
    """Audit F-025: phasing closes the angle at the chaser's radius, so it is a
    rendezvous only when the radii match; it reported 0 km for an altitude gap."""

    def test_unequal_radii_beyond_the_tolerance_raise(self) -> None:
        from spectre.astro.tactical import _PHASING_RADIUS_TOLERANCE_KM, phasing_orbit

        with pytest.raises(ValueError, match="radi"):
            phasing_orbit(6778.0, 6778.0 + _PHASING_RADIUS_TOLERANCE_KM + 1.0, 20.0, 2)

    def test_matching_radii_still_solve(self) -> None:
        from spectre.astro.tactical import _PHASING_RADIUS_TOLERANCE_KM, phasing_orbit

        result = phasing_orbit(6778.0, 6778.0 + _PHASING_RADIUS_TOLERANCE_KM / 2, 20.0, 2)
        assert result.total_delta_v > 0.0


class TestAnUnmeasuredFloorIsNotCalledMeasured:
    """Audit F-032: the drill-down said "measured from N pairs" when the fixed
    0.1 m/s absolute floor stood in."""

    @staticmethod
    def _render(**floor: object) -> str:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        from spectre.web.app import templates as app_templates

        env = Environment(loader=FileSystemLoader("spectre/web/templates"), autoescape=True, undefined=StrictUndefined)
        env.filters.update(app_templates.env.filters)
        source = '{% import "partials/_noise_floor.html" as nf %}{{ nf.floor(f) }}'
        return " ".join(env.from_string(source).render(f=floor).split())

    def test_the_absolute_floor_is_not_called_measured(self) -> None:
        html = self._render(floor_m_s=0.1, measured=False, samples=2, median_m_s=0.0, mad_m_s=0.0,
                            method="insufficient samples — absolute floor")
        assert "measured" not in html.replace("not measured", "")
        assert "absolute floor (not measured)" in html
        assert "insufficient samples" in html

    def test_a_measured_floor_says_where_it_came_from(self) -> None:
        html = self._render(floor_m_s=0.8, measured=True, samples=40, median_m_s=0.3, mad_m_s=0.1,
                            method="median + 5·MAD")
        assert "measured from 40 consecutive element set pairs" in html

    def test_too_few_samples_marks_the_floor_unmeasured(self) -> None:
        from spectre.astro.dv_estimation import calibrate_noise

        assert calibrate_noise([0.0001, 0.0002]).floor_is_measured is False
