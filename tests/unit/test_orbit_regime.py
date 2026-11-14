"""Every element set is stated in its regime where its staleness limit and error rate are applied (SPC-215, F-29).

Deep-space orbits were evaluated with no regime statement: a Molniya-class orbit took the LEO 24 h staleness limit
and the LEO error rate, 1 km plus 2 km a day, and nothing on screen said so. Each set is now classified by its period
and eccentricity into LEO, MEO, HEO/Molniya, GEO or other deep-space, and stated in that regime wherever the limit
and the rate are applied. No regime-specific limit or rate could be sourced exactly, so each keeps the figure it had,
LEO's or GEO's, and where that is another regime's figure the screen says "LEO figure applied to <regime>,
unsourced for this regime" (docs/lookup-register.md). One test per regime, each through the staleness limit
(spectre/web/elsets.py) and the error rate (spectre/astro/along_track.py) as applied to a real element set.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import NamedTuple

import pytest

from spectre.astro import along_track
from spectre.astro.constants import MU_EARTH, R_EARTH
from spectre.astro.elset_approach import elset_position_error_km
from spectre.astro.propagator import TLEOrbit
from spectre.domain.decision import BoundElset
from spectre.web.elsets import elset_age
from spectre.web.routes.maneuver import _elset_band
from spectre.web.routes.threat import _regime_of
from tests.unit._decision_reference import EPOCH, EPOCH_DAY, _checksum


def _tle(satno: int, alt_perigee_km: float, alt_apogee_km: float, inc_deg: float) -> str:
    """An element set with these apsides, argument of perigee 270 degrees, both lines 69 columns."""
    a = R_EARTH + (alt_perigee_km + alt_apogee_km) / 2.0
    e = (alt_apogee_km - alt_perigee_km) / (2.0 * a)
    n_rev_day = math.sqrt(MU_EARTH / a**3) * 86_400.0 / (2.0 * math.pi)
    line1 = f"1 {satno:05d}U 26001A   {EPOCH_DAY}  .00000000  00000-0  00000-0 0  999"
    line2 = (f"2 {satno:05d} {inc_deg:8.4f} {40.0:8.4f} {round(e * 1e7):07d} {270.0:8.4f} {0.0:8.4f} "
             f"{n_rev_day:11.8f}{1:5d}")
    return f"{line1}{_checksum(line1)}\n{line2}{_checksum(line2)}"


class Case(NamedTuple):
    tle: str
    regime: str
    figure: str
    limit_h: float
    error_at_two_days_km: float


#: One element set per regime, the figure it is given and what that sets: the limit, and the error at 2 days old.
_CASES = {
    "LEO": Case(_tle(90101, 500.0, 520.0, 51.6), "LEO", "LEO", 24.0, 5.0),
    "MEO": Case(_tle(90102, 20_100.0, 20_300.0, 55.0), "MEO", "LEO", 24.0, 5.0),
    "HEO/Molniya": Case(_tle(90103, 600.0, 39_700.0, 63.4), "HEO/Molniya", "LEO", 24.0, 5.0),
    "GEO": Case(_tle(90104, 35_780.0, 35_792.0, 0.05), "GEO", "GEO", 72.0, 4.0),
    "other deep-space": Case(_tle(90105, 36_380.0, 36_400.0, 0.05), "other deep-space", "GEO", 72.0, 4.0),
}
_UNSOURCED = "{figure} figure applied to {regime}, unsourced for this regime"


@pytest.mark.parametrize("name", list(_CASES))
def test_each_regime_is_stated_with_the_figure_applied(name: str) -> None:
    case = _CASES[name]
    orbit = TLEOrbit(case.tle)
    assert along_track.orbit_regime(orbit.period_minutes, orbit.eccentricity) == case.regime
    basis = along_track.regime_basis(case.tle)
    assert basis is not None
    assert (basis.regime, basis.figure) == (case.regime, case.figure)
    expected = (f"{case.figure} figure, set for {case.regime}" if case.figure == case.regime
                else _UNSOURCED.format(figure=case.figure, regime=case.regime))
    assert basis.applied == expected
    assert basis.line == (f"Regime {case.regime} (period {orbit.period_minutes:.0f} min, e "
                          f"{orbit.eccentricity:.3f}): {expected}.")


@pytest.mark.parametrize("name", list(_CASES))
def test_each_regime_keeps_the_staleness_limit_it_had_and_says_whose_it_is(name: str) -> None:
    case = _CASES[name]
    age = elset_age(case.tle, EPOCH + timedelta(hours=30))
    assert age is not None
    assert age.limit_hours == case.limit_h
    assert age.stale is (case.limit_h < 30.0)
    assert age.regime_line == (f"{case.regime}: staleness limit {case.limit_h:.0f} h, "
                               f"{along_track.regime_basis(case.tle).applied}")  # type: ignore[union-attr]


@pytest.mark.parametrize("name", list(_CASES))
def test_each_regime_keeps_the_error_rate_it_had_and_says_whose_it_is(name: str) -> None:
    case = _CASES[name]
    at = EPOCH + timedelta(days=2)
    assert elset_position_error_km(case.tle, EPOCH, at) == pytest.approx(case.error_at_two_days_km)
    words = along_track.error_rate_words(case.tle)
    at_epoch, per_day = (1, 2) if case.figure == "LEO" else (2, 1)
    assert words == (f"{at_epoch} km plus {per_day} km a day, "
                     f"{along_track.regime_basis(case.tle).applied}")  # type: ignore[union-attr]


def test_the_molniya_orbit_the_evaluation_named_is_stated_as_unsourced() -> None:
    """F-29: a Molniya-class orbit took the LEO 24 h limit with no statement; it keeps the figure, and says so."""
    age = elset_age(_CASES["HEO/Molniya"].tle, EPOCH)
    assert age is not None
    assert "LEO figure applied to HEO/Molniya, unsourced for this regime" in age.regime_line


class TestTheBoundaries:
    def test_eccentricity_alone_makes_heo(self) -> None:
        """A transfer orbit, e about 0.73, is HEO/Molniya by its eccentricity whatever its period."""
        assert along_track.orbit_regime(630.0, 0.73) == "HEO/Molniya"
        assert along_track.orbit_regime(630.0, 0.24) == "MEO"

    def test_a_low_orbit_crossing_2000_km_is_leo(self) -> None:
        """Perigee 500 km, apogee 3,000 km, under SGP4's deep-space period: near-Earth, so LEO."""
        a = R_EARTH + 1750.0
        period = 2.0 * math.pi * math.sqrt(a**3 / MU_EARTH) / 60.0
        assert along_track.orbit_regime(period, 1250.0 / a) == "LEO"

    def test_an_unlike_deep_orbit_is_other_deep_space(self) -> None:
        """Perigee in MEO, apogee past the GEO band, e 0.2: neither MEO nor GEO."""
        a = 36_000.0
        period = 2.0 * math.pi * math.sqrt(a**3 / MU_EARTH) / 60.0
        assert along_track.orbit_regime(period, 0.2) == "other deep-space"

    def test_heo_starts_at_an_eccentricity_of_exactly_025(self) -> None:
        assert along_track.orbit_regime(718.0, 0.25) == "HEO/Molniya"
        assert along_track.orbit_regime(718.0, 0.2499) == "MEO"

    @pytest.mark.parametrize("e", [0.0, 0.01, 0.05, 0.2499])
    def test_a_geosynchronous_period_is_geo_whatever_its_apsides(self, e: float) -> None:
        """V0.40 review: e 0.01 at 1,436 min put the perigee under the GEO band and read "other deep-space"."""
        assert along_track.orbit_regime(1436.0, e) == "GEO"

    def test_the_geo_period_band_is_inclusive_at_both_edges(self) -> None:
        centre, band = along_track.GEO_PERIOD_MIN, along_track.GEO_PERIOD_BAND_MIN
        assert centre == pytest.approx(1436.068, abs=1e-3)
        for edge in (centre - band, centre + band):
            assert along_track.orbit_regime(edge, 0.0) == "GEO"
        assert along_track.orbit_regime(centre + band + 1e-6, 0.0) == "other deep-space"
        assert along_track.orbit_regime(centre - band - 1e-6, 0.0) == "MEO", "no circular orbit between GEO and MEO"

    def test_the_apsides_boundaries(self) -> None:
        """Each comparison at its edge: LEO below an apogee of 2,000 km, MEO from a perigee of 2,000 km to an apogee
        under the GEO band's lower edge, other deep-space at SGP4's deep-space period or over."""
        by = along_track._by_apsides
        leo, meo = along_track._LEO_MAX_ALT, along_track._MEO_MAX_ALT
        assert by(leo - 100.0, leo - 1e-9, 120.0) == "LEO"
        assert by(leo, leo, 128.0) == "MEO"
        assert by(leo - 1e-9, 3000.0, 150.0) == "LEO"
        assert by(20_000.0, meo - 1e-9, 700.0) == "MEO"
        assert by(20_000.0, meo, 700.0) == "other deep-space"
        assert by(leo - 1e-9, 3000.0, 225.0) == "other deep-space"
        assert by(leo - 1e-9, 3000.0, 224.999) == "LEO"

    @pytest.mark.parametrize(("period", "e"), [(math.nan, 0.0), (92.0, math.nan), (math.inf, 0.0), (-1.0, 0.0),
                                               (92.0, -0.1), (92.0, 1.0)])
    def test_an_orbit_that_cannot_be_read_is_refused(self, period: float, e: float) -> None:
        """A NaN period or eccentricity read as LEO silently; it is refused, and a set's statement says "regime not
        readable" beside the rate applied, or LEO's, the stricter, when even its family cannot be read."""
        with pytest.raises(ValueError, match="no regime"):
            along_track.orbit_regime(period, e)

    def test_a_set_whose_regime_cannot_be_read_states_the_rate_applied_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(TLEOrbit, "eccentricity", property(lambda _self: math.nan))
        assert along_track.regime_basis(_CASES["GEO"].tle) is None
        # The rate stated is still the one applied, GEO's, chosen by the regime family as before.
        assert along_track.error_rate_words(_CASES["GEO"].tle) == "2 km plus 1 km a day, regime not readable"

    def test_the_two_classifiers_differ_on_a_slightly_eccentric_geo_set_and_the_statement_says_whose_figure(
        self,
    ) -> None:
        """classify_orbit_regime chooses the figure, and is left as it was so no limit or rate moves; it reads e 0.01
        at 1,436 min as MEO, so the set takes the LEO figure, and the statement says that is unsourced for GEO."""
        tle = _tle(90106, 35_365.0, 36_208.0, 0.05)
        basis = along_track.regime_basis(tle)
        assert basis is not None and basis.regime == "GEO" and basis.figure == "LEO"
        assert basis.applied == "LEO figure applied to GEO, unsourced for this regime"

    def test_an_eccentric_set_beyond_the_geo_band_takes_the_geo_figure_as_heo(self) -> None:
        """V0.40 review: a = 100,000 km, e 0.5 has its perigee beyond the GEO band, so it takes GEO's figure."""
        tle = _tle(90107, 43_621.863, 143_621.863, 10.0)
        basis = along_track.regime_basis(tle)
        assert basis is not None
        assert basis.applied == "GEO figure applied to HEO/Molniya, unsourced for this regime"

    def test_an_unreadable_set_has_no_regime(self) -> None:
        assert along_track.regime_basis("not an element set") is None
        assert along_track.error_rate_words("not an element set") == "1 km plus 2 km a day, regime not readable"


class TestWhereTheFiguresAreApplied:
    """The Decision Engine's bound set, the Intercept Engine's band and the threat sweep's band each state it."""

    def test_a_bound_set_states_its_regime_and_both_figures(self) -> None:
        tle = _CASES["HEO/Molniya"].tle
        bound = BoundElset(side="red", name="R", stk_name="R", satno=90103, tle=tle, data_mode="REAL", epoch=EPOCH,
                           age_hours=3.0, limit_hours=24.0)
        orbit = TLEOrbit(tle)
        assert bound.regime_line == (
            f"Regime HEO/Molniya (period {orbit.period_minutes:.0f} min, e {orbit.eccentricity:.3f}): staleness limit "
            "24 h and element-set error 1 km plus 2 km a day, LEO figure applied to HEO/Molniya, unsourced for this "
            "regime."
        )

    def test_a_bound_set_with_no_limit_or_no_elements_states_none(self) -> None:
        unread = BoundElset(side="blue", name="B", stk_name="B", satno=None, tle=_CASES["GEO"].tle, data_mode="REAL",
                            epoch=None, age_hours=None, limit_hours=None)
        assert unread.regime_line == ""

    def test_the_intercept_engines_band_names_each_sets_figure(self) -> None:
        red, blue = _CASES["HEO/Molniya"].tle, _CASES["LEO"].tle
        band = _elset_band(red, blue, EPOCH + timedelta(hours=6), 50.0)
        assert band is not None
        assert band["note"].endswith(
            "the sweep's rule of thumb, tuned, not sourced: red's 1 km plus 2 km a day, LEO figure applied to "
            "HEO/Molniya, unsourced for this regime, blue's 1 km plus 2 km a day, LEO figure, set for LEO"
        )

    def test_the_sweeps_regime_word_for_an_unreadable_set(self) -> None:
        assert (_regime_of("not an element set"), _regime_of(_CASES["MEO"].tle)) == ("not readable", "MEO")
