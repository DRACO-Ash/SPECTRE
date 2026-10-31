"""The on-station record built from NOTSOs: what counts, once, and in which phase.

Every record here is written in one of the phrasings the JCO export uses, so
the tests hold without the export, which is not shipped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from spectre.domain import manoeuvre_evidence as me


def _rec(satids: list[str] | str, created: str, description: str, **body: str) -> dict:
    return {
        "msgType": "TACREP_NOTSO",
        "createdAt": created,
        "msgBody": {"SatIds": satids, "Event_Description": description, **body},
    }


class TestEachPhrasingIsRead:
    @pytest.mark.parametrize("text", [
        "Delta V: 3.7 m/s",
        "Delta v: 3.7m/s",
        "Delta V:  3.7 m/s",
        "with a delta-v of 3.7 m/s, resulting in a period increase",
        "used a delta v of 3.7 m/s, the effect of which was",
        "Delta V: 3.7",
    ])
    def test_a_stated_burn(self, text: str) -> None:
        burns, _ = me.stated_burns([_rec(["49011"], "2024-01-02T00:00:00Z", text)])
        assert [(b.satno, b.delta_v_m_s, b.phase) for b in burns] == [("49011", 3.7, me.ON_STATION)]


class TestWhichBurnsCount:
    def test_a_follow_up_repeating_a_burn_counts_it_once_at_its_first_report(self) -> None:
        first = _rec(["49011"], "2024-01-02T00:00:00Z", "Delta V: 3.7 m/s")
        again = _rec(["49011"], "2024-01-05T00:00:00Z", "JD 5: refined. Earlier: Delta V: 3.7 m/s")
        burns, _ = me.stated_burns([again, first])
        assert len(burns) == 1
        assert burns[0].reported == datetime(2024, 1, 2, tzinfo=UTC)

    def test_a_message_about_several_satellites_is_not_attributed(self) -> None:
        burns, _ = me.stated_burns([_rec(["1", "2"], "2024-01-02T00:00:00Z", "Delta V: 9 m/s")])
        assert burns == []

    def test_a_record_with_no_date_is_skipped(self) -> None:
        assert me.stated_burns([_rec(["1"], "", "Delta V: 9 m/s")])[0] == []

    def test_an_unreadable_date_is_skipped(self) -> None:
        assert me.stated_burns([_rec(["1"], "yesterday", "Delta V: 9 m/s")])[0] == []

    def test_a_date_without_a_zone_is_utc(self) -> None:
        burns, _ = me.stated_burns([_rec(["1"], "2024-01-02T06:00:00", "Delta V: 9 m/s")])
        assert burns[0].reported == datetime(2024, 1, 2, 6, tzinfo=UTC)


class TestThePhaseOfABurn:
    @pytest.mark.parametrize("context", [
        "TJS-10 is still in GTO and had a",
        "This maneuver appears to be part of its circularising orbit with a",
        "SJ-23 performed a maneuver to inject into GEO at 160E.",
        "the object could be inserted into geosynchronous orbit,",
        "The next maneuver is an apogee burn to normalise the orbit:",
    ])
    def test_reaching_orbit_is_launch_phase(self, context: str) -> None:
        burns, _ = me.stated_burns([_rec(["1"], "2024-01-02T00:00:00Z", f"{context} Delta V: 305.1 m/s")])
        assert burns[0].phase == me.LAUNCH_PHASE

    def test_a_figure_jco_doubts_is_uncertain(self) -> None:
        text = "a delta v of 337.3 m/s. Please note the delta-V has a high uncertainty due to sparse observations"
        burns, _ = me.stated_burns([_rec(["1"], "2024-01-02T00:00:00Z", text)])
        assert burns[0].phase == me.UNCERTAIN

    def test_a_small_trim_after_reaching_orbit_is_on_station(self) -> None:
        text = "After its GTO climb the satellite trimmed with a delta-v of 9.45 m/s"
        burns, _ = me.stated_burns([_rec(["1"], "2024-01-02T00:00:00Z", text)])
        assert burns[0].phase == me.ON_STATION

    def test_once_launch_phase_always_launch_phase(self) -> None:
        plain = _rec(["1"], "2024-01-02T00:00:00Z", "Delta V: 119 m/s")
        later = _rec(["1"], "2024-01-03T00:00:00Z", "inserting it into GEO with a delta V of 119 m/s")
        burns, _ = me.stated_burns([plain, later])
        assert [(b.phase, b.reported.day) for b in burns] == [(me.LAUNCH_PHASE, 2)]


class TestTheBusiestWindow:
    def _burn(self, day: int, dv: float) -> me.StatedBurn:
        return me.StatedBurn("1", dv, datetime(2025, 11, day, tzinfo=UTC), me.ON_STATION)

    def test_burns_within_fourteen_days_add_up(self) -> None:
        assert me.busiest_window_m_s([self._burn(1, 10.0), self._burn(15, 5.0)]) == pytest.approx(15.0)

    def test_burns_further_apart_do_not(self) -> None:
        assert me.busiest_window_m_s([self._burn(1, 10.0), self._burn(16, 5.0)]) == pytest.approx(10.0)

    def test_no_burns_is_nothing(self) -> None:
        assert me.busiest_window_m_s([]) == pytest.approx(0.0)


class TestTheSummary:
    def _evidence(self) -> me.Evidence:
        return me.summarise([
            _rec(["63924"], "2025-05-14T00:00:00Z", "circularising orbit with a delta-v of 999.6 m/s",
                 Sat_Common_Name="TJS-19"),
            _rec(["63924"], "2025-05-20T00:00:00Z", "drift rate change with a delta-v of 9.45 m/s"),
            _rec(["63924"], "2025-05-22T00:00:00Z", "Delta V: 5.8 m/s"),
            _rec(["64467"], "2025-11-24T00:00:00Z", "Delta V: 38.78 m/s",
                 Event_Class="Verified Maneuver / 64467 / COSMOS 2589 / DS"),
            _rec(["64467"], "2025-12-05T00:00:00Z", "Delta V: 18.6 m/s"),
        ], "test")

    def test_a_satellite_is_judged_on_station_only(self) -> None:
        tjs19 = self._evidence().of("63924")
        assert tjs19 is not None
        assert (tjs19.name, tjs19.on_station_burns, tjs19.largest_burn_m_s) == ("TJS-19", 2, 9.45)
        assert tjs19.busiest_window_m_s == pytest.approx(15.25)
        assert (tjs19.launch_phase_max_m_s, tjs19.last_burn) == (999.6, "2025-05-22")

    def test_the_name_falls_back_to_the_event_class(self) -> None:
        cosmos = self._evidence().of("64467")
        assert cosmos is not None and cosmos.name == "COSMOS 2589"

    def test_the_fleet_figures(self) -> None:
        fleet = self._evidence().fleet
        assert (fleet.satellites, fleet.burns) == (2, 4)
        assert (fleet.largest_window_m_s, fleet.largest_window_satno) == (57.38, "64467")
        assert (fleet.first_report, fleet.last_report) == ("2025-05-14", "2025-12-05")

    def test_an_unknown_satellite_has_no_record(self) -> None:
        assert self._evidence().of("99999") is None
        assert self._evidence().of(None) is None

    def test_it_survives_the_file_round_trip(self) -> None:
        evidence = self._evidence()
        assert me.from_json(json.loads(json.dumps(me.to_json(evidence)))) == evidence

    def test_the_typical_window_interpolates(self) -> None:
        assert me._quantile([10.0, 20.0], 0.9) == pytest.approx(19.0)
        assert me._quantile([], 0.9) == pytest.approx(0.0)


class TestTheLiveCacheAddsToTheShippedRecord:
    def _one(self, satno: str, window: float, last: str) -> me.Evidence:
        obj = me.ObjectEvidence(satno, "", 1, window, window, last, 0.0)
        fleet = me.FleetEvidence(1, 1, window, satno, window, last, last, "x")
        return me.Evidence(fleet, {satno: obj})

    def test_the_larger_figure_wins_and_new_satellites_join(self) -> None:
        both = me.merged(self._one("1", 20.0, "2025-01-01"), self._one("1", 30.0, "2026-01-01"))
        merged_one = both.of("1")
        assert merged_one is not None
        assert (merged_one.busiest_window_m_s, merged_one.last_burn) == (30.0, "2026-01-01")
        assert both.fleet.largest_window_m_s == pytest.approx(30.0)
        assert me.merged(self._one("1", 20.0, "x"), self._one("2", 5.0, "y")).of("2") is not None

    def test_the_fleet_ceiling_never_falls(self) -> None:
        kept = me.merged(self._one("1", 172.0, "x"), self._one("2", 5.0, "y"))
        assert (kept.fleet.largest_window_m_s, kept.fleet.largest_window_satno) == (172.0, "1")

    def test_an_unreadable_cache_leaves_the_shipped_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import spectre.data.notso_cache as cache

        def broken() -> None:
            raise OSError("disk gone")

        monkeypatch.setattr(cache, "get_notso_cache", broken)
        assert me.current_evidence() == me.shipped_evidence()

    def test_the_cache_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import spectre.data.notso_cache as cache

        class _Cache:
            def all_records(self) -> list[dict]:
                return [_rec(["1"], "2026-10-01T00:00:00Z", "Delta V: 400 m/s")]

        monkeypatch.setattr(cache, "get_notso_cache", _Cache)
        assert me.current_evidence().fleet.largest_window_m_s == pytest.approx(400.0)


class TestTheShippedFile:
    def test_it_loads_and_agrees_with_itself(self) -> None:
        evidence = me.shipped_evidence()
        windows = [o.busiest_window_m_s for o in evidence.objects.values()]
        assert evidence.fleet.largest_window_m_s == pytest.approx(max(windows))
        assert evidence.fleet.typical_window_m_s < evidence.fleet.largest_window_m_s

    def test_it_holds_figures_and_names_only(self) -> None:
        data = json.loads(me.EVIDENCE_PATH.read_text(encoding="utf-8"))
        allowed = set(me.ObjectEvidence.__dataclass_fields__)
        assert all(set(o) == allowed for o in data["objects"].values())
        assert "@" not in me.EVIDENCE_PATH.read_text(encoding="utf-8")
