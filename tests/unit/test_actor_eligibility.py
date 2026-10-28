"""Only payloads that can still act are screened as actors.

0.6.6 in service: an AEHF-1 screen named a CZ-3B rocket body its most dangerous
actor, with a Fengyun 2C apogee kick motor and payloads two decades old ranked
beside it. Geometry and delta-V say what an object's orbit could reach; a spent
stage has as much of that as an inspector, and no course of action at all.
"""

from __future__ import annotations

import pytest

from spectre.domain.actor_eligibility import WORKING_LIFE_YEARS, why_not_an_actor

_YEAR = 2026


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

    @pytest.mark.parametrize("name", ["CZ-3B R/B", "FENGYUN 2C AKM", "SL-12 PKM", "FENGYUN 1C DEB", "ATLAS 5 CENTAUR (R/B)"])
    def test_by_name_when_the_catalogue_has_no_record(self, name: str) -> None:
        assert _why(name) == "rocket body"

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
