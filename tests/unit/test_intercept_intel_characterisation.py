"""What `_compute_intercept_intel` returns today, pinned before it is split.

The function is 163 statements with 56 branches and sits at roughly half
coverage, so a refactor of it is exactly the kind that silently changes one
branch in forty. These cases snapshot its full output across the method
families and the delta-v bands, so the decomposition that follows is provably
behaviour-preserving rather than merely plausible.

They are characterisation tests: they assert what the code DOES, not what it
should do. A deliberate behaviour change updates them, with the reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain.models import BurnResult, InterceptMethod, InterceptResult
from spectre.web.routes.maneuver import _compute_intercept_intel

_T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _result(
    method: InterceptMethod,
    total_dv_m_s: float,
    tof_hours: float = 6.0,
    miss_km: float = 2.5,
    burns: int = 1,
) -> InterceptResult:
    """An InterceptResult with *total_dv_m_s* split evenly across *burns*."""
    per_burn = total_dv_m_s / burns
    return InterceptResult(
        red_name="SJ-17",
        blue_name="B_SAT_Alpha",
        method=method,
        burns=[
            BurnResult(
                burn_number=i + 1,
                segment_name=f"Burn {i + 1}",
                burn_epoch=_T0 + timedelta(hours=i),
                delta_v_m_s=per_burn,
                dv_prograde=per_burn * 0.9,
                dv_normal=per_burn * 0.3,
                dv_radial=per_burn * 0.1,
            )
            for i in range(burns)
        ],
        total_delta_v_m_s=total_dv_m_s,
        arrival_epoch=_T0 + timedelta(hours=tof_hours),
        intercept_range_km=miss_km,
        notes="characterisation fixture",
    )


class TestTheDeltaVBandsAsTheyStand:
    @pytest.mark.parametrize(
        ("dv_m_s", "expected_class"),
        [
            (0.4, "Micro-manoeuvre"),
            (11.0, "Station-keeping scale"),
            (60.0, "Minor Transfer"),
            (300.0, "Moderate Transfer"),
            (900.0, "Major Transfer"),
            (4000.0, "High-Energy Transfer"),
        ],
    )
    def test_dv_classification(self, dv_m_s: float, expected_class: str) -> None:
        intel = _compute_intercept_intel(_result(InterceptMethod.LAMBERT, dv_m_s), "GEO")
        assert intel["dv_class"] == expected_class

    @pytest.mark.parametrize(
        ("dv_m_s", "expected_level"),
        [(0.5, "VERY LOW"), (11.0, "LOW"), (60.0, "MEDIUM"), (300.0, "HIGH")],
    )
    def test_observability(self, dv_m_s: float, expected_level: str) -> None:
        intel = _compute_intercept_intel(_result(InterceptMethod.LAMBERT, dv_m_s), "GEO")
        assert intel["obs_level"] == expected_level


class TestThePostureBandingAsItStands:
    @pytest.mark.parametrize(
        ("dv_m_s", "regime", "expected_threat"),
        [
            (8.0, "GEO", "LOW"),        # BENIGN
            (60.0, "GEO", "MEDIUM"),    # ANNOYANCE
            (300.0, "GEO", "HIGH"),     # AGGRESSIVE
            (4000.0, "GEO", "CRITICAL"),  # BEYOND PLATFORM
        ],
    )
    def test_threat_level_follows_posture(
        self, dv_m_s: float, regime: str, expected_threat: str
    ) -> None:
        intel = _compute_intercept_intel(_result(InterceptMethod.LAMBERT, dv_m_s), regime)
        assert intel["threat_level"] == expected_threat


class TestTheTimeOfFlightLabel:
    @pytest.mark.parametrize(
        ("hours", "expected"),
        [(0.008, "< 1m"), (0.5, "30m"), (6.0, "6h"), (6.5, "6h 30m"), (50.0, "2d 2h")],
    )
    def test_label(self, hours: float, expected: str) -> None:
        intel = _compute_intercept_intel(
            _result(InterceptMethod.LAMBERT, 60.0, tof_hours=hours), "GEO",
        )
        assert intel["tof_label"] == expected


class TestThePerBurnBreakdown:
    def test_one_row_per_burn_with_its_magnitude_in_m_s(self) -> None:
        intel = _compute_intercept_intel(
            _result(InterceptMethod.BIELLIPTIC, 300.0, burns=3), "GEO",
        )
        assert len(intel["burn_intel"]) == 3
        for row in intel["burn_intel"]:
            assert row["dv_ms"] == pytest.approx(100.0), (
                "300 m/s across three burns is 100 m/s each; 100,000 would mean "
                "the conversion ran again inside the breakdown"
            )
        assert intel["burn_intel"][0]["direction"] == "Prograde"

    def test_components_are_percentages_of_the_vector_magnitude(self) -> None:
        """They are |component| / |vector|, so they do NOT sum to 100.

        The fixture's components are 0.9, 0.3 and 0.1 of the burn magnitude, a
        vector of length 0.954, so the three percentages sum to about 136. That
        is the existing behaviour and it is what a reader of the panel sees;
        pinned here so the split below cannot quietly change it.
        """
        intel = _compute_intercept_intel(_result(InterceptMethod.LAMBERT, 60.0), "GEO")
        row = intel["burn_intel"][0]
        assert row["pro_pct"] == pytest.approx(94.4, abs=0.2)
        assert row["nor_pct"] == pytest.approx(31.5, abs=0.2)
        assert row["rad_pct"] == pytest.approx(10.5, abs=0.2)


class TestTheShapeOfTheWholePayload:
    _KEYS = {
        "manoeuvre_type", "threat_level", "threat_color", "threat_bg",
        "intent_label", "dv_class", "tof_hours", "tof_label", "dv_budget_pct",
        "burn_intel", "obs_level", "obs_color", "obs_reason", "method_insights",
        "summary",
    }

    @pytest.mark.parametrize("method", list(InterceptMethod))
    def test_every_method_returns_the_full_payload(
        self, method: InterceptMethod
    ) -> None:
        """No method may drop a key; a missing one renders blank in the panel."""
        intel = _compute_intercept_intel(_result(method, 60.0), "GEO")
        assert set(intel) == self._KEYS, f"{method.value} changed the payload shape"
        assert isinstance(intel["summary"], str) and intel["summary"]
        assert isinstance(intel["method_insights"], list)

    def test_a_result_with_no_burns_does_not_crash(self) -> None:
        empty = InterceptResult(
            red_name="SJ-17", blue_name="B_SAT_Alpha",
            method=InterceptMethod.LAMBERT, burns=[],
            total_delta_v_m_s=0.0, arrival_epoch=_T0, intercept_range_km=0.0,
        )
        intel = _compute_intercept_intel(empty, "GEO")
        assert intel["burn_intel"] == []
        assert set(intel) == self._KEYS
