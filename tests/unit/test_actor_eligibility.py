"""Only payloads that can still act are screened as actors.

0.6.6 in service: an AEHF-1 screen named a CZ-3B rocket body its most dangerous
actor, with a Fengyun 2C apogee kick motor and payloads two decades old ranked
beside it. Geometry and delta-V say what an object's orbit could reach; a spent
stage has as much of that as an inspector, and no course of action at all.

Ported from charming-dirac 1357a67 as 0f5fa30 left it. The owner ruled on
2026-11-12 to keep the 15-year cut: a payload over 15 years old with no
intelligence record is not screened, and the page says which were left out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spectre.domain.actor_eligibility import WORKING_LIFE_YEARS, why_not_an_actor

_YEAR = 2026
#: The objects of the bundled bootstrap watchlist, spectre/data/hrr_default.json, blue and red.
_BUNDLED_OBJECTS = 38


def _tle(designator: str) -> str:
    """A line 1 carrying international designator *designator*, e.g. '04042A'."""
    return f"1 28451U {designator:<8} 26250.50000000  .00000000  00000-0  00000-0 0  9990\n2 28451"


def _why(name: str, record: dict | None = None, tle: str | None = None, intel: dict | None = None) -> str | None:
    found = why_not_an_actor(name, record, tle, intel, _YEAR)
    return found.kind if found else None


class TestStagesAndFragmentsAreNotActors:
    @pytest.mark.parametrize(("object_type", "kind"), [("ROCKET BODY", "rocket body"), ("DEBRIS", "debris")])
    def test_by_the_catalogue(self, object_type: str, kind: str) -> None:
        assert _why("ANY NAME", {"objectType": object_type, "launchDate": "2024-01-01"}) == kind

    def test_a_decayed_object(self) -> None:
        assert _why("X", {"objectType": "PAYLOAD", "category": "Decayed"}) == "decayed"

    @pytest.mark.parametrize(("name", "kind"), [
        ("CZ-3B R/B", "rocket body"), ("FENGYUN 2C AKM", "rocket body"), ("SL-12 PKM", "rocket body"),
        ("ATLAS 5 CENTAUR (R/B)", "rocket body"), ("FENGYUN 1C DEB", "debris"),
        ("SL-12 R/B(2)", "rocket body"), ("CZ-2D R/B-1", "rocket body"), ("DELTA 1 DEB*", "debris"),
    ])
    def test_by_name_when_the_catalogue_has_no_record(self, name: str, kind: str) -> None:
        assert _why(name) == kind

    @pytest.mark.parametrize("name", ["SJ-21", "TJS-3", "Object A (possible TJS-26A)", "DEBUT-SAT", "SHIYAN 12 01 (SY-12 01)"])
    def test_a_payload_name_is_not_mistaken_for_one(self, name: str) -> None:
        assert _why(name, tle=_tle("21001A")) is None

    def test_the_catalogue_outranks_the_name(self) -> None:
        """A payload whose name happens to read like a stage is still a payload."""
        assert _why("ODD R/B NAME", {"objectType": "PAYLOAD", "launchDate": "2023-05-01"}) is None


class TestPayloadsPastTheirWorkingLife:
    def test_an_old_payload_is_not_an_actor(self) -> None:
        found = why_not_an_actor("FENGYUN 2C", None, _tle("04042A"), None, _YEAR)
        assert found is not None and (found.kind, found.detail) == ("past working life", "launched 2004")

    def test_the_limit_is_inclusive_of_its_last_year(self) -> None:
        launched = _YEAR - WORKING_LIFE_YEARS
        assert _why("BEIDOU 8", {"objectType": "PAYLOAD", "launchDate": f"{launched}-04-09"}) is None
        assert _why("OLDER", {"objectType": "PAYLOAD", "launchDate": f"{launched - 1}-04-09"}) == "past working life"

    def test_the_catalogue_launch_date_is_preferred_to_the_designator(self) -> None:
        assert _why("X", {"objectType": "PAYLOAD", "launchDate": "2022-01-01"}, _tle("04042A")) is None

    def test_an_unknown_age_is_screened(self) -> None:
        """An object nothing dates is exactly the one worth screening."""
        assert _why("Object A (possible TJS-26A)") is None


class TestTheIntelligenceRecordOverrides:
    @pytest.mark.parametrize("status", ["Operational", "Degraded"])
    def test_an_active_record_keeps_an_old_payload(self, status: str) -> None:
        assert _why("LUCH / OLYMP-K", tle=_tle("08001A"), intel={"status": status}) is None

    def test_and_a_catalogue_type_it_contradicts(self) -> None:
        assert _why("X", {"objectType": "DEBRIS"}, intel={"status": "Operational"}) is None

    def test_a_record_with_no_active_status_does_not(self) -> None:
        assert _why("X", tle=_tle("04042A"), intel={"status": "Retired"}) == "past working life"

    def test_every_record_the_intelligence_file_holds_keeps_an_old_payload(self) -> None:
        """The ruling cuts a payload with no record; every record shipped is held as active, so none is cut."""
        from spectre.data.intel import _load

        records = _load()
        assert records
        assert [satno for satno, rec in records.items() if _why("X", tle=_tle("90001A"), intel=rec)] == []


class TestASyntheticSetsPlaceholderDesignatorIsNotALaunchYear:
    """SPC-239. Every bundled bootstrap set carries designator 20001A, a placeholder the generator wrote, so from 2036
    the age rule would cut every bundled object with no intelligence record. A SYNTHETIC set's designator is not read
    as a launch year: such an object is dated by the catalogue alone, and with no catalogue date it is screened."""

    _IN_2036 = 2036

    def test_a_synthetic_set_is_not_dated_by_its_designator(self) -> None:
        found = why_not_an_actor("SJ-21", None, _tle("20001A"), None, self._IN_2036, tle_data_mode="SYNTHETIC")
        assert found is None

    def test_a_real_set_with_the_same_designator_still_is(self) -> None:
        found = why_not_an_actor("SJ-21", None, _tle("20001A"), None, self._IN_2036, tle_data_mode="REAL")
        assert found is not None and (found.kind, found.detail) == ("past working life", "launched 2020")

    def test_the_catalogue_date_still_dates_a_synthetic_set(self) -> None:
        record = {"objectType": "PAYLOAD", "launchDate": "2004-09-01"}
        found = why_not_an_actor("X", record, _tle("20001A"), None, _YEAR, tle_data_mode="SYNTHETIC")
        assert found is not None and (found.kind, found.detail) == ("past working life", "launched 2004")

    def test_no_bundled_object_is_cut_by_age_in_2036_even_with_no_intelligence_record(self) -> None:
        """Every object of the bundled watchlist, read as the console reads it, with its intelligence record set aside,
        is still screened in 2036: none is cut by the placeholder's year."""
        from spectre.web.routes.udl import parse_hrr_notification

        bundled = Path(__file__).resolve().parents[2] / "spectre" / "data" / "hrr_default.json"
        blue, red = parse_hrr_notification(json.loads(bundled.read_text("utf-8"))[0])
        objects = blue + red
        assert len(objects) == _BUNDLED_OBJECTS
        assert {o["tle_data_mode"] for o in objects} == {"SYNTHETIC"}
        cut = {
            o["name"]: found.detail
            for o in objects
            if (found := why_not_an_actor(o["name"], None, o["tle"], None, self._IN_2036,
                                          tle_data_mode=o["tle_data_mode"])) is not None
        }
        assert cut == {}
