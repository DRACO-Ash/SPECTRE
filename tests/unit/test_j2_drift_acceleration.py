"""J2 drift acceleration: the right direction, and both burns paid for.

Audit F-024. The altitude step was a fixed 50 km chosen by inclination
alone, so for half the signs of the RAAN gap it slowed convergence or sent
it the long way round, while the result claimed to double the rate; and the
cost was the first Hohmann burn only, about half the change.

Independent checks: the secular J2 nodal rate is
-3/2 n J2 (R/p)^2 cos i (Vallado eq. 9-41), computed here directly; the
cost is the two-burn Hohmann closed form.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH
from spectre.astro.tactical import j2_drift_plan

_A = 7000.0


def _rate_deg_day(a: float, inc_deg: float) -> float:
    n = math.sqrt(MU_EARTH / a**3)
    return math.degrees(-1.5 * n * J2_EARTH * (R_EARTH / a) ** 2 * math.cos(math.radians(inc_deg))) * 86400.0


def _hohmann_total(r1: float, r2: float) -> float:
    a_t = (r1 + r2) / 2.0
    return abs(math.sqrt(MU_EARTH * (2 / r1 - 1 / a_t)) - math.sqrt(MU_EARTH / r1)) + abs(
        math.sqrt(MU_EARTH / r2) - math.sqrt(MU_EARTH * (2 / r2 - 1 / a_t))
    )


@pytest.mark.parametrize("delta_raan", [10.0, -10.0])
@pytest.mark.parametrize("inc", [51.6, 97.8])
def test_acceleration_halves_the_convergence_time_for_either_sign(delta_raan: float, inc: float) -> None:
    # Chaser 40 km above the target, both circular, same inclination.
    plan = j2_drift_plan(_A + 40.0, 0.0, inc, _A, 0.0, inc, delta_raan)
    assert plan.accel_convergence_days < plan.convergence_time_days
    assert plan.accel_convergence_days == pytest.approx(plan.convergence_time_days / 2.0, rel=1e-6)
    new_rate = _rate_deg_day(_A + 40.0 + plan.accel_altitude_change_km, inc) - _rate_deg_day(_A, inc)
    assert math.copysign(1.0, new_rate) == -math.copysign(1.0, delta_raan), "must close the gap the short way"
    assert abs(delta_raan) / abs(new_rate) == pytest.approx(plan.accel_convergence_days, rel=1e-6)


def test_the_cost_is_both_hohmann_burns() -> None:
    plan = j2_drift_plan(_A + 40.0, 0.0, 51.6, _A, 0.0, 51.6, 10.0)
    a_new = _A + 40.0 + plan.accel_altitude_change_km
    assert plan.accel_delta_v == pytest.approx(_hohmann_total(_A + 40.0, a_new), rel=1e-9)


def test_the_wrapper_flies_both_burns(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    import numpy as np

    from spectre.astro import maneuvers
    from spectre.astro.propagator import StateVector

    epoch = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)

    class _Circular:
        def __init__(self, a: float, raan_deg: float) -> None:
            i, o = math.radians(51.6), math.radians(raan_deg)
            self._a, self._v = a, math.sqrt(MU_EARTH / a)
            self._n = self._v / a
            self._p = np.array([math.cos(o), math.sin(o), 0.0])
            h = np.array([math.sin(o) * math.sin(i), -math.cos(o) * math.sin(i), math.cos(i)])
            self._q = np.cross(h, self._p)

        def propagate(self, when: datetime) -> StateVector:
            u = self._n * (when - epoch).total_seconds()
            return StateVector(
                epoch=when,
                r=self._a * (math.cos(u) * self._p + math.sin(u) * self._q),
                v=self._v * (-math.sin(u) * self._p + math.cos(u) * self._q),
            )

    by_tle = {"RED": _Circular(_A + 40.0, 10.0), "BLUE": _Circular(_A, 0.0)}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
    sol = maneuvers.j2_drift_intercept("RED", "BLUE", epoch)
    assert len(sol.burns) == 2
    assert sol.total_delta_v == pytest.approx(sum(b.delta_v_mag for b in sol.burns))
    sense = [math.copysign(1.0, b.dv_prograde) for b in sol.burns]
    assert sense[0] == sense[1], "both burns of one altitude change act the same way"
