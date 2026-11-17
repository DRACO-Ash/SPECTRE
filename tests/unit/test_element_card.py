"""The element card behind each Blue asset and Red track in the Assets panel.

Training audit 2026-11-16, finding 2-1 (and cross-cutting finding X5).

The panel listed names only, so a training step's RAAN could be read nowhere. These pin each figure on the card to
the element set it comes from, the sub-satellite longitude to an independent reckoning, and the moment it is taken at.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from sgp4.api import Satrec, jday

from spectre.astro.constants import R_EARTH
from spectre.domain.models import BlueAsset, RedTrack
from spectre.web import element_card as element_card_module
from spectre.web.element_card import element_card, element_cards, longitude_text
from spectre.web.planning_state import SessionState

# A station-kept GEO set: inclination 0.04, RAAN 95, argument of perigee 270, mean anomaly 180, e 0.0002.
_GEO = (
    "1 30793U 07007A   26250.50000000 -.00000100  00000-0  00000-0 0  9998\n"
    "2 30793   0.0400  95.0000 0002000 270.0000 180.0000  1.00271000 46216"
)
_LEO = (
    "1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9999\n"
    "2 25544  51.6420 195.0000 0001207  86.9689 273.1630 15.54320000365490"
)
_AT = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)


def _iau82_gmst_deg(at: datetime) -> float:
    """GMST by the IAU-82 expression in UT1 seconds (Vallado, Fundamentals of Astrodynamics, 4th ed., eq. 3-47),
    reckoned here independently of the Meeus form the code under test uses."""
    jd = 2451545.0 + (at - datetime(2000, 1, 1, 12, tzinfo=UTC)).total_seconds() / 86400.0
    t = (jd - 2451545.0) / 36525.0
    seconds = 67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * t + 0.093104 * t**2 - 6.2e-6 * t**3
    return (seconds / 240.0) % 360.0


def _independent_longitude(tle: str, at: datetime) -> float:
    """SGP4 straight from the library, against IAU-82 GMST: no code under test on the path."""
    line1, line2 = tle.splitlines()
    sat = Satrec.twoline2rv(line1, line2)
    jd, fr = jday(at.year, at.month, at.day, at.hour, at.minute, at.second)
    err, r, _ = sat.sgp4(jd, fr)
    assert err == 0
    return (math.degrees(math.atan2(r[1], r[0])) - _iau82_gmst_deg(at) + 180.0) % 360.0 - 180.0


def _signed(text: str) -> float:
    value, hemisphere = text.split("° ")
    return float(value) if hemisphere == "E" else -float(value)


def _with_mean_motion(tle: str, inclination: str, revs_per_day: str) -> str:
    """*tle* with line 2's inclination and mean motion replaced, its checksum recomputed."""
    line1, line2 = tle.splitlines()
    body = line2[:8] + inclination.rjust(8) + line2[16:52] + revs_per_day.rjust(11) + line2[63:68]
    total = sum(int(c) if c.isdigit() else int(c == "-") for c in body)
    return f"{line1}\n{body}{total % 10}"


class TestTheFiguresAreTheSetsOwn:
    def test_every_angle_is_line_two_to_two_decimals(self) -> None:
        card = element_card(BlueAsset(name="SKY", tle=_GEO, data_mode="SYNTHETIC"), _AT, at_is_scenario=False)
        assert card is not None
        assert (round(card.inc_deg, 2), round(card.raan_deg, 2)) == (0.04, 95.0)
        assert (round(card.argp_deg, 2), round(card.mean_anomaly_deg, 2)) == (270.0, 180.0)
        assert card.ecc == pytest.approx(0.0002)
        assert card.data_mode == "SYNTHETIC"
        assert card.epoch_text == "2026-09-07 12:00:00 UTC"

    def test_the_period_and_apsides_follow_from_the_mean_motion(self) -> None:
        card = element_card(BlueAsset(name="SKY", tle=_GEO), _AT, at_is_scenario=False)
        assert card is not None
        assert card.period_min == pytest.approx(1440.0 / 1.00271, rel=1e-9)
        a = (398600.4418 / (2 * math.pi * 1.00271 / 86400.0) ** 2) ** (1 / 3)
        assert card.a_km == pytest.approx(a, rel=1e-9)
        assert card.perigee_alt_km == pytest.approx(a * (1 - 0.0002) - R_EARTH)
        assert card.apogee_alt_km == pytest.approx(a * (1 + 0.0002) - R_EARTH)
        assert card.regime == "GEO"

    def test_the_age_is_taken_at_the_moment_given(self) -> None:
        card = element_card(BlueAsset(name="SKY", tle=_GEO), _AT, at_is_scenario=True)
        assert card is not None and card.age is not None
        assert card.age.hours == pytest.approx(6.0)
        assert card.at_text == "2026-09-07 18:00 UTC"


class TestTheSubSatelliteLongitude:
    def test_a_geostationary_object_has_one_and_it_agrees_with_an_independent_reckoning(self) -> None:
        card = element_card(BlueAsset(name="SKY", tle=_GEO), _AT, at_is_scenario=True)
        assert card is not None and card.near_geo
        assert _signed(card.longitude_text) == pytest.approx(_independent_longitude(_GEO, _AT), abs=0.006)

    def test_it_also_agrees_with_the_mean_longitude(self) -> None:
        """Near circular and near equatorial, the longitude is RAAN + argp + M less GMST to well under 0.1 deg."""
        card = element_card(BlueAsset(name="SKY", tle=_GEO), _AT, at_is_scenario=True)
        assert card is not None
        expected = (95.0 + 270.0 + 180.0 + 0.25 * 1.00271 * 360.0 - _iau82_gmst_deg(_AT) + 180.0) % 360.0 - 180.0
        assert _signed(card.longitude_text) == pytest.approx(expected, abs=0.1)

    def test_a_graveyard_object_above_the_band_has_one(self) -> None:
        """Pattern-of-life's test, not regime GEO alone: a graveyard orbit (regime DEEP) drifts slowly enough for one
        longitude to say where it is."""
        graveyard = _with_mean_motion(_GEO, "0.0400", "0.98750000")
        card = element_card(RedTrack(name="DEAD", tle=graveyard), _AT, at_is_scenario=False)
        assert card is not None
        assert card.regime == "DEEP"
        assert card.near_geo
        assert _signed(card.longitude_text) == pytest.approx(_independent_longitude(graveyard, _AT), abs=0.006)

    def test_an_inclined_meo_object_has_none(self) -> None:
        """Two revolutions a day at 55 degrees, a navigation orbit: the point under it circles the Earth."""
        meo = _with_mean_motion(_GEO, "55.0000", "2.00560000")
        card = element_card(RedTrack(name="NAV", tle=meo), _AT, at_is_scenario=False)
        assert card is not None
        assert card.regime == "MEO"
        assert not card.near_geo
        assert not card.longitude_text

    def test_a_leo_object_has_none(self) -> None:
        card = element_card(RedTrack(name="ISS", tle=_LEO), _AT, at_is_scenario=False)
        assert card is not None
        assert card.regime == "LEO"
        assert not card.near_geo
        assert not card.longitude_text

    def test_a_set_sgp4_cannot_fly_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fails(*_a: object) -> float:
            raise RuntimeError("SGP4 error code 1")

        monkeypatch.setattr(element_card_module, "sub_satellite_longitude_deg", fails)
        card = element_card(BlueAsset(name="SKY", tle=_GEO), _AT, at_is_scenario=True)
        assert card is not None and card.near_geo
        assert not card.longitude_text
        assert card.longitude_note == "SGP4 could not propagate this set"

    @pytest.mark.parametrize(("degrees", "text"), [
        (75.321, "75.32° E"), (-0.5, "0.50° W"), (-0.001, "0.00° E"), (-0.006, "0.01° W"), (359.0, "1.00° W"),
    ])
    def test_it_is_labelled_east_or_west(self, degrees: float, text: str) -> None:
        assert longitude_text(degrees) == text

    @pytest.mark.parametrize("degrees", [180.0, 179.999, -179.996, 540.0, -180.0])
    def test_the_antimeridian_has_no_hemisphere(self, degrees: float) -> None:
        assert longitude_text(degrees) == "180.00°"


class TestTheMomentIsTheScenarioTime:
    def test_a_set_scenario_start_is_used(self) -> None:
        state = SessionState(blue_assets=[BlueAsset(name="SKY", tle=_GEO)], scenario_start=_AT)
        card = element_cards(state, now=datetime(2030, 1, 1, tzinfo=UTC))["blue_cards"]["SKY"]
        assert card is not None
        assert card.at_is_scenario
        assert card.at_text == "2026-09-07 18:00 UTC"

    def test_now_is_used_when_none_is_set(self) -> None:
        state = SessionState(red_tracks=[RedTrack(name="SKY", tle=_GEO)])
        card = element_cards(state, now=_AT)["red_cards"]["SKY"]
        assert card is not None
        assert not card.at_is_scenario
        assert card.at_text == "2026-09-07 18:00 UTC"


class TestASetThatDoesNotParse:
    @pytest.mark.parametrize("tle", ["one line only", "1 garbage\n2 garbage", ""])
    def test_has_no_card(self, tle: str) -> None:
        assert element_card(BlueAsset(name="BAD", tle=tle), _AT, at_is_scenario=False) is None

    def test_is_listed_with_none(self) -> None:
        state = SessionState(blue_assets=[BlueAsset(name="BAD", tle="nonsense")])
        assert element_cards(state, now=_AT)["blue_cards"] == {"BAD": None}
