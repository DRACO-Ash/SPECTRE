"""H-bar hops grow an out-of-plane oscillation; they do not hold an offset.

Audit F-077. Out-of-plane CW motion is simple harmonic,
z(t) = (zdot0 / n) sin nt: a normal burn of n d reaches d a quarter orbit
later and is back at zero at the half orbit, so at the default half-orbit
cadence each hop ended where it began, and n_hops x d never accumulated as
total_advance_km claimed. Burning n d at each plane crossing, along the
out-of-plane velocity there, raises the amplitude by d each time. That is
what the sequence now describes, flown here through the CW solution.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate
from spectre.astro.tactical import hbar_hop_sequence

_R = 7000.0
_N = math.sqrt(MU_EARTH / _R**3)


def _peak(n_hops: int, d: float) -> float:
    """Largest |z| flown over the sequence, burning at each plane crossing."""
    plan = hbar_hop_sequence(_R, d, n_hops)
    state = CWState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    peak = 0.0
    for _ in range(n_hops):
        sense = 1.0 if state.zd >= 0.0 else -1.0
        state = state._replace(zd=state.zd + sense * plan.delta_v_per_hop)
        for k in range(1, 201):
            peak = max(peak, abs(_cw_propagate(state, _N, plan.time_per_hop_s * k / 200).z))
        state = _cw_propagate(state, _N, plan.time_per_hop_s)
    return peak


@pytest.mark.parametrize("n_hops", [1, 3])
def test_the_amplitude_grows_by_one_hop_per_burn(n_hops: int) -> None:
    plan = hbar_hop_sequence(_R, 2.0, n_hops)
    peak = _peak(n_hops, 2.0)
    assert plan.total_advance_km == pytest.approx(n_hops * 2.0)
    assert peak == pytest.approx(plan.total_advance_km, rel=1e-4)


def test_the_sequence_ends_at_the_peak_a_quarter_orbit_after_the_last_burn() -> None:
    plan = hbar_hop_sequence(_R, 2.0, 3)
    period = 2.0 * math.pi / _N
    assert plan.total_time_s == pytest.approx(2 * period / 2 + period / 4)
    state = CWState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    t = 0.0
    for _ in range(3):
        sense = 1.0 if state.zd >= 0.0 else -1.0
        state = state._replace(zd=state.zd + sense * plan.delta_v_per_hop)
        if t + plan.time_per_hop_s < plan.total_time_s:
            state = _cw_propagate(state, _N, plan.time_per_hop_s)
            t += plan.time_per_hop_s
    assert abs(_cw_propagate(state, _N, plan.total_time_s - t).z) == pytest.approx(6.0, rel=1e-9)


def test_a_cadence_that_is_not_node_to_node_is_refused() -> None:
    period = 2.0 * math.pi / _N
    with pytest.raises(ValueError, match="crossing"):
        hbar_hop_sequence(_R, 2.0, 3, time_per_hop_s=period / 3)
