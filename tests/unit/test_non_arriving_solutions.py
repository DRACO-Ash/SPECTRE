"""A solution that never reaches the target leaves no warning time (found building SPC-005, 0.10.0).

A plane change only aligns the planes. Its single burn "arrives" the moment it
fires, so its zero flight time ranked it the most dangerous course of action,
arriving in under a minute, whenever it fitted the budget, and decide-by would
then have said the time to act had already passed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from spectre.domain.decide_by import earliest_arrival
from spectre.domain.models import ThreatSweepEntry, ThreatTarget
from spectre.domain.threat_assessment import arrives_at_target, warning_time_rank
from spectre.domain.warning_change import least_warning_by_target
from spectre.web.routes.threat import _compute_worst_coa, _group_entries

_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
_TARGET = ThreatTarget("BLUE-1", "1", "hrr", 1)


def _entry(method: str, tof: float, dv: float = 50.0) -> ThreatSweepEntry:
    return ThreatSweepEntry(target=_TARGET, burn_epoch=_NOW, burn_location="now", delta_v_m_s=dv, tof_hours=tof,
                            dv_prograde=dv, dv_normal=0.0, dv_radial=0.0, method=method, regime="GEO",
                            arrives=arrives_at_target(method))


def test_a_plane_change_does_not_arrive() -> None:
    assert not arrives_at_target("plane_change")
    assert arrives_at_target("hohmann") and arrives_at_target("lambert")


def test_it_ranks_after_every_arriving_intercept() -> None:
    assert warning_time_rank(10.0, 0.0, 500.0, arrives=False) > warning_time_rank(400.0, 30.0, 500.0)


def test_it_is_never_the_worst_case() -> None:
    worst = _compute_worst_coa([_entry("plane_change", 0.0, dv=5.0), _entry("hohmann", 5.0)], None, 500.0)
    assert worst is not None and worst["method"] == "hohmann"


def test_with_nothing_arriving_there_is_no_worst_case() -> None:
    assert _compute_worst_coa([_entry("plane_change", 0.0)], None, 500.0) is None


def test_it_is_no_arrival_for_decide_by_or_the_before_and_after() -> None:
    entries = [_entry("plane_change", 0.0), _entry("hohmann", 5.0)]
    at, entry = earliest_arrival(entries, 500.0)  # type: ignore[misc]
    assert entry.method == "hohmann" and at == _NOW + timedelta(hours=5)
    assert least_warning_by_target(entries, 500.0) == {"BLUE-1": 5.0}
    assert least_warning_by_target([SimpleNamespace(target=_TARGET, delta_v_m_s=1.0, tof_hours=0.0, arrives=False)],
                                   500.0) == {}


def test_a_target_group_leads_with_an_arriving_intercept() -> None:
    group = _group_entries([_entry("plane_change", 0.0), _entry("hohmann", 5.0)])[0]
    assert group["best_method"] == "hohmann" and group["best_arrives"] is True
