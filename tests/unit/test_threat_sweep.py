"""Unit tests for the threat sweep logic."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from spectre.domain.models import (
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
            delta_v_m_s=1.5,
            tof_hours=3.0,
            dv_prograde=1.2,
            dv_normal=0.3,
            dv_radial=0.1,
            method="hohmann",
        )
        assert entry.delta_v_m_s == 1.5
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
                delta_v_m_s=0.8,
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
                delta_v_m_s=1.2,
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
        from spectre.web.routes.threat import _build_target_list

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
        from spectre.web.routes.threat import _build_target_list

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
        from spectre.web.routes.threat import _build_target_list

        class FakeState:
            hrr_objects = [
                {"satno": "11111", "name": "SAT_A", "country": "USA", "rank": 1},
                {"satno": "22222", "name": "SAT_B", "country": "CHN", "rank": 2},
            ]

        targets = _build_target_list(FakeState(), "blue", 3)
        assert len(targets) == 0

    def test_build_target_list_multiple_ranks_separate(self) -> None:
        """Each call returns only the requested rank."""
        from spectre.web.routes.threat import _build_target_list

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
        from spectre.web.routes.threat import _compute_epochs

        now = datetime(2024, 1, 1, tzinfo=UTC)
        epochs = _compute_epochs(_ISS_TLE, now)
        # Should always have at least "now".
        assert len(epochs) >= 1
        assert epochs[0][0] == "now"
        assert epochs[0][1] == now

    def test_sweep_all_methods(self) -> None:
        from spectre.web.routes.threat import _sweep_all_methods, _SweepRequest

        target = ThreatTarget("B_SAT_T", "", "blue", None)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        epochs = [("now", now)]

        # Deliberately wider than any real platform's reserve: this case
        # exercises the eight-method fan-out, not the budget filter. The
        # ISS-to-Tiangong plane change alone is about 10 degrees, which costs
        # thousands of m/s and no object on orbit could fly.
        entries = _sweep_all_methods(
            _SweepRequest(
                red_tle=_ISS_TLE, target_tle=_TIANGONG_TLE, target=target,
                max_dv_m_s=10_000.0, regime="LEO",
            ),
            epochs,
        )
        assert len(entries) >= 1
        methods_seen = {e.method for e in entries}
        assert "hohmann" in methods_seen
        assert entries[0].burn_location == "now"
        assert entries[0].delta_v_m_s > 0

    def test_the_sweep_hohmann_matches_the_textbook_value(self) -> None:
        """Coplanar circular orbits at 400 and 600 km: the two-burn Hohmann
        cost from vis-viva is 110.69 m/s. The sweep propagates SGP4 element
        sets, whose osculating radii differ slightly from the mean ones, so it
        is held to 1 m/s rather than to the last digit."""
        import math

        from spectre.web.routes.threat import _sweep_all_methods, _SweepRequest

        mu, r_earth = 398600.4418, 6378.137

        def circular(alt_km: float) -> str:
            rev_per_day = math.sqrt(mu / (r_earth + alt_km) ** 3) * 86400.0 / (2.0 * math.pi)
            return ("1 99001U 24001A   24001.00000000  .00000000  00000-0  00000-0 0  9990\n"
                    f"2 99001  51.6400 100.0000 0000001   0.0000   0.0000 {rev_per_day:11.8f}    10")

        r1, r2 = r_earth + 400.0, r_earth + 600.0
        a_t = (r1 + r2) / 2.0
        textbook_m_s = 1000.0 * (
            (math.sqrt(mu * (2 / r1 - 1 / a_t)) - math.sqrt(mu / r1))
            + (math.sqrt(mu / r2) - math.sqrt(mu * (2 / r2 - 1 / a_t)))
        )
        assert textbook_m_s == pytest.approx(110.69, abs=0.01)

        entries = _sweep_all_methods(
            _SweepRequest(
                red_tle=circular(400.0), target_tle=circular(600.0),
                target=ThreatTarget("T", "", "blue", None), max_dv_m_s=10_000.0, regime="LEO",
            ),
            [("now", datetime(2024, 1, 1, tzinfo=UTC))],
        )
        hohmann = next(e for e in entries if e.method == "hohmann")
        assert hohmann.delta_v_m_s == pytest.approx(textbook_m_s, abs=1.0)

    def test_sweep_all_methods_filters_by_max_dv(self) -> None:
        from spectre.web.routes.threat import _sweep_all_methods, _SweepRequest

        target = ThreatTarget("B_SAT_T", "", "blue", None)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        epochs = [("now", now)]

        # Use a negative budget to filter everything out.
        entries = _sweep_all_methods(
            _SweepRequest(
                red_tle=_ISS_TLE, target_tle=_TIANGONG_TLE, target=target,
                max_dv_m_s=-1.0, regime="LEO",
            ),
            epochs,
        )
        assert len(entries) == 0

    def test_group_entries(self) -> None:
        """_group_entries groups by target and ranks groups by warning time."""
        from spectre.web.routes.threat import _group_entries

        now = datetime(2024, 1, 1, tzinfo=UTC)
        t_a = ThreatTarget("SAT_A", "111", "hrr", 1)
        t_b = ThreatTarget("SAT_B", "222", "hrr", 1)
        entries = [
            ThreatSweepEntry(target=t_a, burn_epoch=now, burn_location="now",
                             delta_v_m_s=2.0, tof_hours=1.0, dv_prograde=0,
                             dv_normal=0, dv_radial=0, method="hohmann"),
            ThreatSweepEntry(target=t_b, burn_epoch=now, burn_location="now",
                             delta_v_m_s=0.5, tof_hours=1.0, dv_prograde=0,
                             dv_normal=0, dv_radial=0, method="lambert"),
            ThreatSweepEntry(target=t_a, burn_epoch=now, burn_location="apogee",
                             delta_v_m_s=1.0, tof_hours=2.0, dv_prograde=0,
                             dv_normal=0, dv_radial=0, method="lambert"),
        ]

        groups = _group_entries(entries)
        assert len(groups) == 2

        # Groups are ranked on WARNING TIME, matching the headline above them.
        # They used to be ranked on cost while the banner ranked on time, so the
        # two disagreed on the same screen about which target mattered most.
        assert groups[0]["target"].target_name == "SAT_B"
        assert groups[0]["profile_count"] == 1

        assert groups[1]["target"].target_name == "SAT_A"
        # SAT_A's representative is its SOONEST entry (1.0 h, costing 2.0 m/s),
        # not its cheapest (2.0 h, costing 1.0 m/s). An intercept arriving in
        # one hour is the harder problem whatever it costs.
        assert groups[1]["best_tof"] == 1.0
        assert groups[1]["best_dv"] == 2.0
        assert groups[1]["profile_count"] == 2
        # Children are sorted by warning time within the group too, so the row
        # the operator opens first is the soonest arrival, not the cheapest.
        assert groups[1]["children"][0]["entry"].tof_hours == 1.0
        assert groups[1]["children"][1]["entry"].tof_hours == 2.0

    def test_hrr_group_counts(self) -> None:
        """_hrr_group_counts returns correct breakdowns by side and rank."""
        from spectre.web.routes.threat import _hrr_group_counts

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


class TestColourAndWordsAgreeInTheSweep:
    """One colour map for this panel, and one format for the same quantity.

    Two defects the design review found, both of the same kind: a second
    encoding of something already shown, disagreeing with the first.

    THE COLOUR. The posture badge read ``posture_bands`` (BENIGN low/green,
    AGGRESSIVE critical/red) while the row tint read geometric ACCESS, which
    the domain deliberately inverts in ``_POSTURE_TO_ACCESS``: a manoeuvre
    inside an object's routine budget is the most permissive geometry there
    is, so BENIGN carries CRITICAL access. A BENIGN badge therefore sat in a
    high-threat gold row, and the comment beside it claimed the tint
    "reinforces a word the operator can read".

    Both maps were right about different questions. Putting them in one colour
    channel with opposite polarity re-introduced exactly the conflation the
    summary block was redesigned to remove: access and capability are printed
    there as separate labelled values because one combined word used to
    contradict the intelligence panel on the same screen.

    THE UNITS. The parent's Method tooltip printed ``'%.4f' | format(...)``, a
    km/s-era format applied to a value that is now m/s, with no unit, under a
    header reading dV (m/s). The refined row that htmx swaps in printed the
    same field through ``| m_s``. The same cell read "Pro 11.0000" before a
    Refine and "Pro 11" after it.
    """

    _TEMPLATES = (
        Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / "partials"
    )
    _SWEEP = _TEMPLATES / "threat_sweep.html"
    _REFINED = _TEMPLATES / "threat_sweep_row.html"

    def test_the_rows_are_tinted_from_the_posture_map(self) -> None:
        markup = self._SWEEP.read_text(encoding="utf-8")
        assert markup.count("posture_bands.get(") >= 3, (
            "the parent row, the child row and the badge must all read the "
            "single posture map; one of them is using a map of its own"
        )

    def test_no_row_is_tinted_by_the_inverted_access_bands(self) -> None:
        """The literal shape of the defect, which is one edit away from returning."""
        markup = self._SWEEP.read_text(encoding="utf-8")
        assert "'BENIGN', 'ANNOYANCE'" not in markup, (
            "a row is grouping BENIGN with ANNOYANCE again, which is the "
            "access ordering and inverts the posture the badge shows"
        )
        assert 'data-threat="high"' not in markup, "the access-driven tint is back"
        assert 'threat-med' not in markup, "the access-driven tint is back"

    def test_the_delta_v_tooltip_carries_its_unit_in_both_templates(self) -> None:
        for path in (self._SWEEP, self._REFINED):
            markup = path.read_text(encoding="utf-8")
            tooltip = [ln for ln in markup.splitlines() if 'title="Pro ' in ln]
            assert tooltip, f"{path.name} no longer has the component tooltip"
            assert "m/s" in tooltip[0], (
                f"{path.name} prints delta-v components with no unit, under a "
                "column header that reads m/s"
            )
            assert "%.4f" not in tooltip[0], (
                f"{path.name} is back on the km/s-era four-decimal format"
            )

    def test_both_templates_format_the_components_identically(self) -> None:
        """An htmx swap must not change how a number reads."""
        import re

        def components(path: Path) -> list[str]:
            markup = path.read_text(encoding="utf-8")
            line = next(ln for ln in markup.splitlines() if 'title="Pro ' in ln)
            return re.findall(r"\|\s*(\w+)\s*\}\}", line)

        assert components(self._SWEEP) == components(self._REFINED), (
            "the in-table row and the refined row that replaces it format the "
            "same field differently, so the cell changes on a Refine"
        )
