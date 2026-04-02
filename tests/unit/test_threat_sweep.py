"""Unit tests for the threat sweep logic."""

from __future__ import annotations

from datetime import UTC, datetime

from sipc.domain.models import (
    ThreatAssessment,
    ThreatSweepEntry,
    ThreatTarget,
)

# ISS TLE (epoch 2024) — used for deterministic testing.
_ISS_TLE = (
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9002\n"
    "2 25544  51.6400 208.9163 0006703  40.5765 319.5681 15.49560532999999"
)

_TIANGONG_TLE = (
    "1 48274U 21035A   24001.50000000  .00020000  00000-0  25000-3 0  9003\n"
    "2 48274  41.4700 120.0000 0005000  30.0000 330.0000 15.60000000100000"
)


class TestThreatTarget:
    """ThreatTarget model instantiation."""

    def test_blue_target(self) -> None:
        t = ThreatTarget(
            target_name="B_SAT_Alpha",
            target_satno="",
            target_source="blue",
            hrr_rank=None,
        )
        assert t.target_source == "blue"
        assert t.hrr_rank is None

    def test_hrr_target(self) -> None:
        t = ThreatTarget(
            target_name="COSMOS 2542",
            target_satno="44835",
            target_source="hrr",
            hrr_rank=1,
        )
        assert t.target_source == "hrr"
        assert t.hrr_rank == 1


class TestThreatSweepEntry:
    """ThreatSweepEntry construction and fields."""

    def test_entry_fields(self) -> None:
        target = ThreatTarget("Test", "12345", "blue", None)
        entry = ThreatSweepEntry(
            target=target,
            burn_epoch=datetime(2024, 1, 1, tzinfo=UTC),
            burn_location="now",
            delta_v_km_s=1.5,
            tof_hours=3.0,
            dv_prograde=1.2,
            dv_normal=0.3,
            dv_radial=0.1,
            method="hohmann",
        )
        assert entry.delta_v_km_s == 1.5
        assert entry.method == "hohmann"
        assert entry.notes == ""


class TestThreatAssessment:
    """ThreatAssessment model."""

    def test_empty_assessment(self) -> None:
        a = ThreatAssessment(
            red_name="R_SAT_Track01",
            sweep_epoch=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert a.entries == []
        assert a.errors == []
        assert a.target_count == 0

    def test_assessment_with_entries(self) -> None:
        target = ThreatTarget("B_SAT_X", "", "blue", None)
        entries = [
            ThreatSweepEntry(
                target=target,
                burn_epoch=datetime(2024, 1, 1, tzinfo=UTC),
                burn_location="now",
                delta_v_km_s=0.8,
                tof_hours=2.0,
                dv_prograde=0.7,
                dv_normal=0.1,
                dv_radial=0.0,
                method="hohmann",
            ),
            ThreatSweepEntry(
                target=target,
                burn_epoch=datetime(2024, 1, 1, tzinfo=UTC),
                burn_location="apogee",
                delta_v_km_s=1.2,
                tof_hours=3.0,
                dv_prograde=1.0,
                dv_normal=0.2,
                dv_radial=0.0,
                method="hohmann",
            ),
        ]
        a = ThreatAssessment(
            red_name="R_SAT_Track01",
            sweep_epoch=datetime(2024, 1, 1, tzinfo=UTC),
            entries=entries,
            target_count=1,
        )
        assert len(a.entries) == 2
        assert a.target_count == 1


class TestSweepHelpers:
    """Test the sweep helper functions from the threat route module."""

    def test_build_target_list_blue_rank1(self) -> None:
        """Blue-side HRR Rank 1 objects are returned."""
        from sipc.web.routes.threat import _build_target_list

        class FakeState:
            hrr_objects = [
                {"satno": "11111", "name": "SAT_A", "country": "USA", "rank": 1},
                {"satno": "22222", "name": "SAT_B", "country": "CHN", "rank": 1},
                {"satno": "33333", "name": "SAT_C", "country": "GBR", "rank": 2},
            ]

        targets = _build_target_list(FakeState(), "blue", 1)
        assert len(targets) == 1
        assert targets[0].target_name == "SAT_A"
        assert targets[0].hrr_rank == 1

    def test_build_target_list_red_rank1(self) -> None:
        """Red-side HRR Rank 1 objects are returned."""
        from sipc.web.routes.threat import _build_target_list

        class FakeState:
            hrr_objects = [
                {"satno": "11111", "name": "SAT_A", "country": "USA", "rank": 1},
                {"satno": "22222", "name": "SAT_B", "country": "CHN", "rank": 1},
                {"satno": "55555", "name": "SAT_E", "country": "RUS", "rank": 1},
            ]

        targets = _build_target_list(FakeState(), "red", 1)
        assert len(targets) == 2
        names = {t.target_name for t in targets}
        assert names == {"SAT_B", "SAT_E"}

    def test_build_target_list_no_match(self) -> None:
        """Empty list when no objects match the requested side/rank."""
        from sipc.web.routes.threat import _build_target_list

        class FakeState:
            hrr_objects = [
                {"satno": "11111", "name": "SAT_A", "country": "USA", "rank": 1},
                {"satno": "22222", "name": "SAT_B", "country": "CHN", "rank": 2},
            ]

        targets = _build_target_list(FakeState(), "blue", 3)
        assert len(targets) == 0

    def test_build_target_list_multiple_ranks_separate(self) -> None:
        """Each call returns only the requested rank."""
        from sipc.web.routes.threat import _build_target_list

        class FakeState:
            hrr_objects = [
                {"satno": "11111", "name": "SAT_A", "country": "USA", "rank": 0},
                {"satno": "22222", "name": "SAT_B", "country": "USA", "rank": 3},
                {"satno": "33333", "name": "SAT_C", "country": "USA", "rank": 5},
            ]

        assert len(_build_target_list(FakeState(), "blue", 0)) == 1
        assert len(_build_target_list(FakeState(), "blue", 3)) == 1
        assert len(_build_target_list(FakeState(), "blue", 5)) == 1

    def test_compute_epochs(self) -> None:
        from sipc.web.routes.threat import _compute_epochs

        now = datetime(2024, 1, 1, tzinfo=UTC)
        epochs = _compute_epochs(_ISS_TLE, now)
        # Should always have at least "now".
        assert len(epochs) >= 1
        assert epochs[0][0] == "now"
        assert epochs[0][1] == now

    def test_sweep_all_methods(self) -> None:
        from sipc.web.routes.threat import _sweep_all_methods

        target = ThreatTarget("B_SAT_T", "", "blue", None)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        epochs = [("now", now)]

        entries = _sweep_all_methods(
            red_tle=_ISS_TLE,
            target_tle=_TIANGONG_TLE,
            target=target,
            epochs=epochs,
            max_dv=10.0,
        )
        assert len(entries) >= 1
        methods_seen = {e.method for e in entries}
        assert "hohmann" in methods_seen
        assert entries[0].burn_location == "now"
        assert entries[0].delta_v_km_s > 0

    def test_sweep_all_methods_filters_by_max_dv(self) -> None:
        from sipc.web.routes.threat import _sweep_all_methods

        target = ThreatTarget("B_SAT_T", "", "blue", None)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        epochs = [("now", now)]

        # Use negative max_dv to filter everything out.
        entries = _sweep_all_methods(
            red_tle=_ISS_TLE,
            target_tle=_TIANGONG_TLE,
            target=target,
            epochs=epochs,
            max_dv=-1.0,
        )
        assert len(entries) == 0

    def test_group_entries(self) -> None:
        """_group_entries groups by target and sorts by best delta-V."""
        from sipc.web.routes.threat import _group_entries

        now = datetime(2024, 1, 1, tzinfo=UTC)
        t_a = ThreatTarget("SAT_A", "111", "hrr", 1)
        t_b = ThreatTarget("SAT_B", "222", "hrr", 1)
        entries = [
            ThreatSweepEntry(target=t_a, burn_epoch=now, burn_location="now",
                             delta_v_km_s=2.0, tof_hours=1.0, dv_prograde=0,
                             dv_normal=0, dv_radial=0, method="hohmann"),
            ThreatSweepEntry(target=t_b, burn_epoch=now, burn_location="now",
                             delta_v_km_s=0.5, tof_hours=1.0, dv_prograde=0,
                             dv_normal=0, dv_radial=0, method="lambert"),
            ThreatSweepEntry(target=t_a, burn_epoch=now, burn_location="apogee",
                             delta_v_km_s=1.0, tof_hours=2.0, dv_prograde=0,
                             dv_normal=0, dv_radial=0, method="lambert"),
        ]

        groups = _group_entries(entries)
        assert len(groups) == 2
        # SAT_B has best dV (0.5), so it sorts first.
        assert groups[0]["target"].target_name == "SAT_B"
        assert groups[0]["best_dv"] == 0.5
        assert groups[0]["profile_count"] == 1
        # SAT_A has best dV 1.0 (from the apogee entry).
        assert groups[1]["target"].target_name == "SAT_A"
        assert groups[1]["best_dv"] == 1.0
        assert groups[1]["profile_count"] == 2
        # Children are sorted by dV within the group.
        assert groups[1]["children"][0]["entry"].delta_v_km_s == 1.0
        assert groups[1]["children"][1]["entry"].delta_v_km_s == 2.0

    def test_hrr_group_counts(self) -> None:
        """_hrr_group_counts returns correct breakdowns by side and rank."""
        from sipc.web.routes.threat import _hrr_group_counts

        class FakeState:
            hrr_objects = [
                {"satno": "11111", "name": "SAT_A", "country": "USA", "rank": 1},
                {"satno": "22222", "name": "SAT_B", "country": "USA", "rank": 1},
                {"satno": "33333", "name": "SAT_C", "country": "CHN", "rank": 2},
                {"satno": "44444", "name": "SAT_D", "country": "GBR", "rank": 3},
                {"satno": "55555", "name": "SAT_E", "country": "RUS", "rank": 0},
            ]

        blue_hrr, red_hrr = _hrr_group_counts(FakeState())
        # Blue HRR: 2× rank 1, 1× rank 3
        assert (1, 2) in blue_hrr
        assert (3, 1) in blue_hrr
        # Red HRR: 1× rank 0, 1× rank 2
        assert (0, 1) in red_hrr
        assert (2, 1) in red_hrr

    def test_entry_sorting(self) -> None:
        """Entries should be sortable by delta_v_km_s."""
        target = ThreatTarget("X", "", "blue", None)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        entries = [
            ThreatSweepEntry(target=target, burn_epoch=now, burn_location="now",
                             delta_v_km_s=2.0, tof_hours=1.0, dv_prograde=0, dv_normal=0,
                             dv_radial=0, method="hohmann"),
            ThreatSweepEntry(target=target, burn_epoch=now, burn_location="apogee",
                             delta_v_km_s=0.5, tof_hours=1.0, dv_prograde=0, dv_normal=0,
                             dv_radial=0, method="hohmann"),
            ThreatSweepEntry(target=target, burn_epoch=now, burn_location="perigee",
                             delta_v_km_s=1.0, tof_hours=1.0, dv_prograde=0, dv_normal=0,
                             dv_radial=0, method="hohmann"),
        ]
        entries.sort(key=lambda e: e.delta_v_km_s)
        assert entries[0].delta_v_km_s == 0.5
        assert entries[1].delta_v_km_s == 1.0
        assert entries[2].delta_v_km_s == 2.0
