"""Each relative-motion solver's answer, flown on two-body orbits (audit F-082).

The CW solvers, collision avoidance and the V-bar hop were tested for sign
or shape only, so a sign or factor error in any of them passed. Here each
answer is applied as an impulse to a deputy beside a circular chief, both
are propagated on the full two-body equations, and the separation reached
is read in the chief's radial, in-track, cross-track frame. Nothing in the
check uses the Clohessy-Wiltshire equations the solvers are built on.

The last test is the checklist: every public solver in tactical.py names
where it is pinned to an independent reference, or says it is a heuristic
with none.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import tactical
from spectre.astro.constants import MU_EARTH

R_REF = 6878.137  # km, 500 km circular
N = math.sqrt(MU_EARTH / R_REF**3)
PERIOD = 2 * math.pi / N


def _two_body(_t: float, s: np.ndarray) -> np.ndarray:
    r = s[:3]
    return np.concatenate([s[3:], -MU_EARTH * r / np.linalg.norm(r) ** 3])


def _propagate(state: np.ndarray, t: float) -> np.ndarray:
    if t == 0.0:
        return state
    sol = solve_ivp(_two_body, (0.0, t), state, method="DOP853", rtol=1e-12, atol=1e-12)
    return np.array(sol.y[:, -1])


def _frame(chief: np.ndarray) -> np.ndarray:
    r_hat = chief[:3] / np.linalg.norm(chief[:3])
    c_hat = np.cross(chief[:3], chief[3:])
    c_hat /= np.linalg.norm(c_hat)
    return np.array([r_hat, np.cross(c_hat, r_hat), c_hat])


def _fly(burns: list[tuple[float, np.ndarray]], until: float) -> tuple[np.ndarray, np.ndarray]:
    """Deputy relative position and velocity (radial, in-track, cross-track) at *until*.

    *burns* are (time, impulse in RIC, km/s), in time order.
    """
    chief = np.array([R_REF, 0.0, 0.0, 0.0, math.sqrt(MU_EARTH / R_REF), 0.0])
    deputy = chief.copy()
    now = 0.0
    for when, dv in [*burns, (until, np.zeros(3))]:
        chief, deputy, now = _propagate(chief, when - now), _propagate(deputy, when - now), when
        deputy = deputy + np.concatenate([np.zeros(3), _frame(chief).T @ dv])
    frame = _frame(chief)
    omega = np.cross(chief[:3], chief[3:]) / np.linalg.norm(chief[:3]) ** 2
    rel_r = deputy[:3] - chief[:3]
    rel_v = deputy[3:] - chief[3:] - np.cross(omega, rel_r)
    return frame @ rel_r, frame @ rel_v


def test_radial_separation_is_reached() -> None:
    r = tactical.cw_radial_separation(R_REF, 1.0, 1200.0)
    pos, _ = _fly([(0.0, np.array([r.delta_v_radial, 0.0, 0.0]))], 1200.0)
    assert pos[0] == pytest.approx(1.0, rel=0.01)
    assert pos[1] == pytest.approx(r.along_track_sep_km, rel=0.01)


def test_along_track_drift_is_reached_with_the_stated_radial_swing() -> None:
    r = tactical.cw_along_track_drift(R_REF, 5.0, 3000.0)
    pos, _ = _fly([(0.0, np.array([0.0, r.delta_v_along_track, 0.0]))], 3000.0)
    assert pos[1] == pytest.approx(5.0, rel=0.01)
    assert pos[0] == pytest.approx(r.radial_sep_km, rel=0.02)


def test_combined_reaches_both_targets() -> None:
    r = tactical.cw_combined(R_REF, 1.0, 5.0, 2500.0)
    pos, _ = _fly([(0.0, np.array([r.delta_v_radial, r.delta_v_along_track, 0.0]))], 2500.0)
    assert pos[0] == pytest.approx(1.0, rel=0.02)
    assert pos[1] == pytest.approx(5.0, rel=0.01)


@pytest.mark.parametrize(("strategy", "axis"), [("radial", 0), ("along_track", 1), ("out_of_plane", 2)])
def test_each_collision_avoidance_burn_gives_the_miss_on_its_axis(strategy: str, axis: int) -> None:
    plan = tactical.collision_avoidance(R_REF, 2.0, 1500.0)
    impulse = np.zeros(3)
    impulse[axis] = getattr(plan, strategy).delta_v
    pos, _ = _fly([(0.0, impulse)], 1500.0)
    assert abs(pos[axis]) == pytest.approx(2.0, rel=0.01)
    assert plan.best.delta_v == min(plan.radial.delta_v, plan.along_track.delta_v, plan.out_of_plane.delta_v)


def test_a_vbar_hop_advances_its_distance_and_stops_for_its_price() -> None:
    hop = tactical.vbar_hop_sequence(R_REF, 2.0, n_hops=1)
    half = hop.delta_v_per_hop / 2.0
    # Inward radial burn; half an orbit later the deputy is back on V-bar, ahead.
    pos, vel = _fly([(0.0, np.array([-half, 0.0, 0.0]))], PERIOD / 2.0)
    assert pos[1] == pytest.approx(2.0, rel=0.01)
    assert abs(pos[0]) < 0.01
    # What is left to stop is the second burn of the pair.
    assert float(np.linalg.norm(vel)) == pytest.approx(half, rel=0.01)
    assert hop.time_per_hop_s == pytest.approx(PERIOD / 2.0)


@pytest.mark.parametrize("half_orbits", [1, 3])
def test_a_vbar_hop_may_take_any_odd_number_of_half_orbits(half_orbits: int) -> None:
    hop = tactical.vbar_hop_sequence(R_REF, 2.0, n_hops=1, time_per_hop_s=half_orbits * PERIOD / 2.0)
    pos, _ = _fly([(0.0, np.array([-hop.delta_v_per_hop / 2.0, 0.0, 0.0]))], hop.time_per_hop_s)
    assert pos[1] == pytest.approx(2.0, rel=0.01)


@pytest.mark.parametrize("time_s", [PERIOD, PERIOD / 3.0, 1000.0])
def test_a_vbar_hop_that_cannot_land_on_vbar_is_refused(time_s: float) -> None:
    # A whole orbit returns the radial hop to its start; other times leave it off V-bar.
    with pytest.raises(ValueError, match="odd number of half orbits"):
        tactical.vbar_hop_sequence(R_REF, 2.0, time_per_hop_s=time_s)


#: Where each public solver in tactical.py is held to an independent reference.
_PINNED: dict[str, tuple[str, ...]] = {
    "phasing_orbit": ("test_tactical_validation.py",),
    "cw_radial_separation": ("test_tactical_fly_the_answer.py",),
    "cw_along_track_drift": ("test_tactical_fly_the_answer.py",),
    "cw_combined": ("test_tactical_fly_the_answer.py",),
    "plane_change": ("test_plane_change_nodes.py",),
    "combined_altitude_plane_change": ("test_combined_plane_change.py",),
    "j2_raan_rate": ("test_tactical_validation.py",),
    "j2_drift_plan": ("test_j2_drift_acceleration.py",),
    "collision_avoidance": ("test_tactical_fly_the_answer.py",),
    "geo_drift": ("test_tactical_validation.py",),
    "graveyard_transfer": ("test_tactical_validation.py",),
    "classify_manoeuvre": ("test_classify_raan_cost.py",),
    "nmc_safety_ellipse": ("test_tactical_validation.py",),
    "optimal_evasion": ("test_tactical.py",),
    "intercept_envelope_analytical": ("test_tactical_validation.py",),
    "relative_motion_stability": ("test_relative_motion_stability.py",),
    "formation_defence_burn": ("test_formation_slot_displacement.py",),
    "vbar_hop_sequence": ("test_tactical_fly_the_answer.py",),
    "hbar_hop_sequence": ("test_hbar_hop_oscillation.py",),
}
#: Scores with no physical reference; labelled heuristic on screen (audit F-041).
_HEURISTIC = {"detectability_metric", "assess_intercept_intent", "fingerprint_manoeuvre", "orbital_terrain"}


def test_every_public_solver_is_pinned_or_declared_heuristic() -> None:
    source = Path(tactical.__file__).read_text(encoding="utf-8")
    public = {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    assert public == set(_PINNED) | _HEURISTIC
    here = Path(__file__).parent
    for name, files in _PINNED.items():
        for f in files:
            assert name in (here / f).read_text(encoding="utf-8"), (name, f)
