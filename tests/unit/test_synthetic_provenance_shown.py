"""Results computed from generated element sets say so where they are read.

Audit F-039. The bundled watchlist ships element sets with UDL dataMode
SYNTHETIC. The screening form warned about them, but the sweep and screening
results did not: the sweep carried the mode only in a hidden ``data-dm``
attribute, its Data Mode filter had no SYNTHETIC option, and the screening
panel carried no mode at all. A ranking built on generated orbits read exactly
like one built on tracked ones.

The contexts here are built with the route's own helpers, so the fixture
cannot drift from what the routes pass.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from spectre.domain.models import ThreatSweepEntry, ThreatTarget
from spectre.domain.threat_assessment import rank_actors
from spectre.web.routes.threat import (
    _attach_data_mode,
    _group_entries,
    _provenance_warnings,
)
from tests.unit import test_threat_screen_template as screen
from tests.unit import test_threat_sweep_template as sweep


def _swept(satno: str, name: str) -> ThreatSweepEntry:
    return ThreatSweepEntry(
        target=ThreatTarget(name, satno, "hrr", 1),
        burn_epoch=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        burn_location="now", delta_v_m_s=40.0, tof_hours=5.0,
        dv_prograde=38.0, dv_normal=10.0, dv_radial=5.0,
        method="min_time", regime="GEO",
    )


def _grouped(modes: dict[str, str]) -> list[dict[str, object]]:
    grouped = _group_entries([_swept("30793", "SKYNET-5A"), _swept("40258", "SKYNET-5D")])
    _attach_data_mode(SimpleNamespace(hrr_tle_data_mode=modes), grouped)
    return grouped


class TestTheHelper:
    def test_live_and_operator_entered_sets_raise_nothing(self) -> None:
        assert _provenance_warnings([("red SJ-17", "REAL"), ("target X", "MANUAL")]) == []

    def test_each_mode_names_what_rests_on_it(self) -> None:
        lines = _provenance_warnings([
            ("red SJ-17", "SYNTHETIC"), ("target A", "SYNTHETIC"), ("target B", "TEST"), ("target C", "REAL"),
        ])
        assert lines == ["SYNTHETIC: red SJ-17, target A", "TEST: target B"]


class TestTheSweep:
    def test_a_synthetic_target_is_badged_and_the_result_is_flagged(self) -> None:
        grouped = _grouped({"30793": "SYNTHETIC"})
        warnings = _provenance_warnings(
            [("red SJ-17", "REAL")] + [(f"target {g['target'].target_name}", g["data_mode"]) for g in grouped],
        )
        html = sweep._render(sweep._context(grouped=grouped, provenance_warnings=warnings))
        flat = " ".join(html.split())
        assert "not from live tracking" in flat
        assert "SYNTHETIC: target SKYNET-5A" in flat
        assert html.count('class="provenance-badge"') == 1, "one badge, on the synthetic row only"

    def test_a_live_sweep_carries_no_warning(self) -> None:
        html = sweep._render(sweep._context(grouped=_grouped({}), provenance_warnings=[]))
        assert "not from live tracking" not in " ".join(html.split())
        assert 'class="provenance-badge"' not in html

    def test_the_filter_can_select_synthetic_rows(self) -> None:
        html = sweep._render(sweep._context(grouped=_grouped({"30793": "SYNTHETIC"}), provenance_warnings=[]))
        assert '<option value="SYNTHETIC">' in html


class TestTheScreening:
    def test_a_synthetic_actor_is_badged_and_the_result_is_flagged(self) -> None:
        actor_modes = {"43874": "SYNTHETIC"}
        ranked = screen._context()["screening"].ranked
        warnings = _provenance_warnings(
            [("asset SKYNET-5A", "REAL")]
            + [(f"actor {v.actor_name}", actor_modes.get(v.actor_satno, "REAL")) for v in ranked],
        )
        html = screen._render(screen._context(actor_modes=actor_modes, provenance_warnings=warnings))
        flat = " ".join(html.split())
        assert "not from live tracking" in flat
        assert "SYNTHETIC: actor TJS-3" in flat
        assert html.count('class="provenance-badge"') == 1

    def test_a_synthetic_asset_is_flagged(self) -> None:
        warnings = _provenance_warnings([("asset SKYNET-5A", "SYNTHETIC")])
        html = screen._render(screen._context(actor_modes={}, provenance_warnings=warnings))
        assert "SYNTHETIC: asset SKYNET-5A" in " ".join(html.split())

    def test_a_live_screening_carries_no_warning(self) -> None:
        html = screen._render(screen._context(actor_modes={}, provenance_warnings=[]))
        assert "not from live tracking" not in " ".join(html.split())

    def test_an_empty_ranking_still_renders(self) -> None:
        html = screen._render(screen._context(
            screening=rank_actors([]), actors_reachable=0, actor_modes={}, provenance_warnings=[],
        ))
        assert "No candidate actor can reach this asset" in " ".join(html.split())
