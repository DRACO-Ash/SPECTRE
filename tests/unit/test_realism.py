"""Realism bands: each at and either side of its boundary, with its reason."""

from __future__ import annotations

import pytest

from spectre.domain import realism
from spectre.domain.manoeuvre_evidence import Evidence, FleetEvidence, ObjectEvidence


def _evidence() -> Evidence:
    tjs19 = ObjectEvidence("63924", "TJS-19", 8, 9.45, 21.0, "2025-05-27", 999.6)
    cosmos = ObjectEvidence("64467", "COSMOS 2589", 56, 38.8, 171.8, "2026-01-14", 0.0)
    quiet = ObjectEvidence("1", "QUIET", 0, 0.0, 0.0, "", 300.0)
    fleet = FleetEvidence(3, 64, 171.8, "64467", 36.8, "2022-04-28", "2026-03-27", "test")
    return Evidence(fleet, {"63924": tjs19, "64467": cosmos, "1": quiet})


class TestTheBands:
    @pytest.mark.parametrize(("dv", "band"), [
        (0.0, realism.SEEN_BEFORE),
        (21.0, realism.SEEN_BEFORE),
        (21.1, realism.POSSIBLE),
        (171.8, realism.POSSIBLE),
        (171.9, realism.UNREALISTIC),
        (500.0, realism.UNREALISTIC),
    ])
    def test_a_satellite_with_a_record(self, dv: float, band: str) -> None:
        assert realism.assess(dv, "63924", "TJS-19", _evidence()).band == band

    @pytest.mark.parametrize("satno", ["1", "99999", None])
    def test_no_on_station_record_means_never_seen_before(self, satno: str | None) -> None:
        assert realism.assess(0.5, satno, "X", _evidence()).band == realism.POSSIBLE

    def test_only_unrealistic_is_discounted(self) -> None:
        assert realism.assess(500.0, "63924", "TJS-19", _evidence()).discounted
        assert not realism.assess(100.0, "63924", "TJS-19", _evidence()).discounted


class TestTheReasonNamesTheFigures:
    def test_seen_before(self) -> None:
        reason = realism.assess(4.6, "63924", "TJS-19", _evidence()).reason
        assert "4.6 m/s" in reason and "21.0 m/s TJS-19" in reason

    def test_possible_with_a_record(self) -> None:
        reason = realism.assess(165.0, "63924", "TJS-19", _evidence()).reason
        assert "more than TJS-19 has spent on station in any 14 days (21.0 m/s)" in reason
        assert "(171.8 m/s, by COSMOS 2589)" in reason

    def test_possible_without_a_record(self) -> None:
        assert "no on-station burn in the NOTSO record (X)" in realism.assess(5.0, None, "X", _evidence()).reason

    def test_unrealistic(self) -> None:
        reason = realism.assess(587.0, "63924", "TJS-19", _evidence()).reason
        assert "587.0 m/s" in reason and "171.8 m/s, by COSMOS 2589" in reason

    def test_a_record_holder_without_a_name_is_named_by_number(self) -> None:
        evidence = _evidence()
        unnamed = Evidence(evidence.fleet, {"63924": evidence.objects["63924"]})
        assert "by 64467" in realism.assess(587.0, "63924", "TJS-19", unnamed).reason


class TestTheFastestArrivalBudget:
    def test_the_fleet_figure_when_the_satellite_has_spent_less(self) -> None:
        budget, why = realism.realistic_budget_m_s("63924", _evidence())
        assert budget == pytest.approx(36.8) and "nine in ten" in why

    def test_its_own_figure_when_it_has_spent_more(self) -> None:
        budget, why = realism.realistic_budget_m_s("64467", _evidence())
        assert budget == pytest.approx(171.8) and "its own" in why

    def test_no_record(self) -> None:
        assert realism.realistic_budget_m_s(None, _evidence())[0] == pytest.approx(36.8)
