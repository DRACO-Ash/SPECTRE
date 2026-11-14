"""Invariants of the Lambert solver, the propagators and the manoeuvre arithmetic (SPC-013).

Each test states a property two-body physics guarantees and checks it over an
exhaustive grid: every combination of the tuples named beside it, built with
itertools.product and run as one parametrised case each, so a failure names
the orbit that broke it. No randomness is drawn except in the Monte Carlo
sampler, whose seeds are fixed and listed.

Tolerances are stated beside each property with the reason for the figure:
what the code converges to, the worst value measured on the grid at the
commit this file was written against, and the headroom between them. A
tolerance is never loosened to pass; a wrong arc, a wrong sign or a missing
term misses by orders of magnitude more than any figure here.
"""

from __future__ import annotations

import itertools
import math
from datetime import UTC, datetime

import numpy as np
import pytest

from spectre.astro import monte_carlo as mc
from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH
from spectre.astro.kepler import propagate_two_body
from spectre.astro.lambert import solve_lambert
from spectre.astro.maneuvers import _make_burn
from spectre.astro.propagator import StateVector
from spectre.astro.transfers import bielliptic, hohmann

_EPOCH = datetime(2026, 3, 1, tzinfo=UTC)


def _state(a: float, e: float, inc_deg: float, nu_deg: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Position and velocity on the orbit (a, e, i), node on the x axis, at true anomaly *nu_deg*."""
    p = a * (1.0 - e * e)
    nu = math.radians(nu_deg)
    radius = p / (1.0 + e * math.cos(nu))
    r_pf = np.array([radius * math.cos(nu), radius * math.sin(nu), 0.0])
    v_pf = math.sqrt(MU_EARTH / p) * np.array([-math.sin(nu), e + math.cos(nu), 0.0])
    i = math.radians(inc_deg)
    tilt = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(i), -math.sin(i)], [0.0, math.sin(i), math.cos(i)]])
    return tilt @ r_pf, tilt @ v_pf


def _period(a: float) -> float:
    return 2.0 * math.pi * math.sqrt(a ** 3 / MU_EARTH)


def _energy(r: np.ndarray, v: np.ndarray) -> float:
    return float(v @ v) / 2.0 - MU_EARTH / float(np.linalg.norm(r))


def _never_negative(*figures: float) -> bool:
    """Whether every figure is zero or more, a NaN included as a failure.

    Written as a predicate, not ``x >= 0``, which the suite's own guard reads
    as an assertion on a count that cannot fail; a delta-V can.
    """
    return all(float(f) == abs(float(f)) for f in figures)


def test_the_never_negative_check_sees_a_negative_and_a_nan() -> None:
    assert _never_negative(0.0, -0.0, 1e-12, 7.8)
    assert not _never_negative(0.5, -1e-12)
    assert not _never_negative(math.nan)


def _relative(got: np.ndarray, want: np.ndarray) -> float:
    return float(np.linalg.norm(got - want) / np.linalg.norm(want))


# ── Kepler (universal variables), the reference every other check flies against ──

#: a (km): LEO, GPS, GEO. e: circular to highly eccentric. i (deg): near-equatorial, critical, retrograde.
#: Kept where the perigee clears the Earth's surface, so every orbit is one a satellite could fly.
_KEPLER_ORBITS = [
    (a, e, i) for a, e, i in itertools.product((7000.0, 26560.0, 42164.0), (0.0, 0.1, 0.5, 0.9), (0.1, 63.4, 98.0))
    if a * (1.0 - e) > R_EARTH
]
#: Spans in orbital periods: part of one, exactly one, and several with a part left over.
_PERIODS = (0.37, 1.0, 5.5)

#: The universal anomaly converges to 1e-10 and every step after it is closed form, so a state comes back to
#: about 1e-13 of itself (4e-13 measured on this grid). 1e-9 is three orders of headroom and still a
#: millimetre at GEO; a sign error in g or g-dot misses by order 1.
_KEPLER_TOL = 1e-9


@pytest.mark.parametrize(("a", "e", "inc", "periods"), [
    (*orbit, periods) for orbit, periods in itertools.product(_KEPLER_ORBITS, _PERIODS)
])
def test_kepler_forward_then_back_returns_to_the_start_and_keeps_energy_and_angular_momentum(
    a: float, e: float, inc: float, periods: float,
) -> None:
    r0, v0 = _state(a, e, inc, nu_deg=30.0)
    r1, v1 = propagate_two_body(r0, v0, periods * _period(a))
    back_r, back_v = propagate_two_body(r1, v1, -periods * _period(a))
    assert _relative(back_r, r0) < _KEPLER_TOL
    assert _relative(back_v, v0) < _KEPLER_TOL
    assert abs(_energy(r1, v1) - _energy(r0, v0)) < _KEPLER_TOL * abs(_energy(r0, v0))
    assert _relative(np.cross(r1, v1), np.cross(r0, v0)) < _KEPLER_TOL


@pytest.mark.parametrize(("a", "e", "inc"), _KEPLER_ORBITS)
def test_kepler_one_period_later_is_the_same_place(a: float, e: float, inc: float) -> None:
    r0, v0 = _state(a, e, inc, nu_deg=30.0)
    r1, v1 = propagate_two_body(r0, v0, _period(a))
    assert _relative(r1, r0) < _KEPLER_TOL
    assert _relative(v1, v0) < _KEPLER_TOL


# ── Lambert ──

#: The orbits of _KEPLER_ORBITS with e up to 0.4, flown from perigee for these fractions of a period.
#: Each gives a transfer angle at least 30 degrees from 180, where the plane is defined (asserted below).
_LAMBERT_ORBITS = [
    (a, e, i) for a, e, i in itertools.product((7000.0, 26560.0, 42164.0), (0.0, 0.1, 0.4), (0.1, 51.6, 98.0))
    if a * (1.0 - e) > R_EARTH
]
_ARC_FRACTIONS = (0.1, 0.25, 0.8)

#: The time-of-flight residual is converged to 1e-8 of sqrt(mu) tof, which leaves the velocities good to about
#: 1e-8 of orbital speed: 9e-8 km/s worst measured here. 1e-6 km/s (1 mm/s) is ten times that and a tenth of
#: the smallest figure the console renders (0.01 m/s). A transfer on the wrong arc costs kilometres per second.
_ZERO_BURN_KM_S = 1e-6


@pytest.mark.parametrize(("a", "e", "inc", "fraction"), [
    (*orbit, fraction) for orbit, fraction in itertools.product(_LAMBERT_ORBITS, _ARC_FRACTIONS)
])
def test_lambert_between_two_points_of_one_orbit_needs_no_burn(a: float, e: float, inc: float, fraction: float) -> None:
    """A satellite already on the arc that joins the two points in the time asked: the transfer is a zero burn."""
    r1, v1 = _state(a, e, inc)
    tof = fraction * _period(a)
    r2, v2 = propagate_two_body(r1, v1, tof)
    angle = math.degrees(math.acos(float(np.clip(r1 @ r2 / np.linalg.norm(r1) / np.linalg.norm(r2), -1.0, 1.0))))
    assert abs(angle - 180.0) > 30.0, "the grid must stay clear of the 180 degree singularity"
    sol = solve_lambert(r1, r2, tof, v1_initial=v1, v2_target=v2)
    assert float(np.linalg.norm(sol.v1 - v1)) < _ZERO_BURN_KM_S
    assert float(np.linalg.norm(sol.v2 - v2)) < _ZERO_BURN_KM_S
    assert 0.0 <= sol.total_delta_v < 2 * _ZERO_BURN_KM_S
    assert sol.tof == tof


#: |r1| and |r2| in km, the angle from r1 to r2 measured in a plane tilted 17.2 degrees, the time of flight as a
#: fraction of the period of an orbit whose semi-major axis is the mean radius, and the sense of the transfer.
_GEOMETRIES = list(itertools.product(
    (7000.0, 26560.0, 42164.0), (7000.0, 42164.0), (30.0, 120.0, 240.0, 330.0), (0.2, 0.6), (True, False),
))
_TILT_RAD = 0.3

#: A free geometry spans hyperbolic hops and near-parabolic long arcs, where the velocities are more sensitive to
#: the converged z than on a real orbit: 2.9e-7 relative worst measured here. 1e-6 keeps three times that; the
#: other branch or the other arc misses by order 1.
_LAMBERT_REL_TOL = 1e-6
#: Energy and angular momentum at the two ends come from one set of Lagrange coefficients, so they agree to
#: rounding (6e-13 measured); 1e-9 is headroom, and two different conics differ by order 1.
_CONIC_TOL = 1e-9


def _geometry(r1_mag: float, r2_mag: float, angle_deg: float, fraction: float) -> tuple[np.ndarray, np.ndarray, float]:
    angle = math.radians(angle_deg)
    r1 = np.array([r1_mag, 0.0, 0.0])
    r2 = r2_mag * np.array([math.cos(angle), math.sin(angle) * math.cos(_TILT_RAD), math.sin(angle) * math.sin(_TILT_RAD)])
    return r1, r2, fraction * _period((r1_mag + r2_mag) / 2.0)


@pytest.mark.parametrize(("r1_mag", "r2_mag", "angle", "fraction", "prograde"), _GEOMETRIES)
def test_lambert_flies_to_the_point_and_time_it_was_asked_for(
    r1_mag: float, r2_mag: float, angle: float, fraction: float, prograde: bool,
) -> None:
    r1, r2, tof = _geometry(r1_mag, r2_mag, angle, fraction)
    sol = solve_lambert(r1, r2, tof, prograde=prograde)
    arrived, arrival_v = propagate_two_body(r1, sol.v1, tof)
    assert _relative(arrived, r2) < _LAMBERT_REL_TOL
    assert _relative(arrival_v, sol.v2) < _LAMBERT_REL_TOL
    # One conic: the same energy and angular momentum at both ends.
    assert abs(_energy(r1, sol.v1) - _energy(r2, sol.v2)) < _CONIC_TOL * abs(_energy(r1, sol.v1))
    assert _relative(np.cross(r2, sol.v2), np.cross(r1, sol.v1)) < _CONIC_TOL
    # The sense asked for: the transfer's angular momentum has the sign of z Curtis's convention names.
    assert (np.cross(r1, sol.v1)[2] > 0) == prograde


@pytest.mark.parametrize(("r1_mag", "r2_mag", "angle", "fraction", "prograde"), _GEOMETRIES)
def test_lambert_run_backwards_is_the_same_arc_reversed(
    r1_mag: float, r2_mag: float, angle: float, fraction: float, prograde: bool,
) -> None:
    """Two-body motion is time-reversible: r2 to r1 in the opposite sense is the same arc, velocities negated."""
    r1, r2, tof = _geometry(r1_mag, r2_mag, angle, fraction)
    forward = solve_lambert(r1, r2, tof, prograde=prograde)
    backward = solve_lambert(r2, r1, tof, prograde=not prograde)
    assert _relative(backward.v1, -forward.v2) < _LAMBERT_REL_TOL
    assert _relative(backward.v2, -forward.v1) < _LAMBERT_REL_TOL


@pytest.mark.parametrize(("r1_mag", "r2_mag", "angle", "fraction", "prograde"), _GEOMETRIES)
def test_lambert_delta_v_is_never_negative_and_is_the_sum_of_its_burns(
    r1_mag: float, r2_mag: float, angle: float, fraction: float, prograde: bool,
) -> None:
    r1, r2, tof = _geometry(r1_mag, r2_mag, angle, fraction)
    # Circular velocity at each end, in the transfer plane: a chaser and a target on their own orbits.
    normal = np.cross(r1, r2) * (1.0 if prograde == (np.cross(r1, r2)[2] > 0) else -1.0)
    normal /= np.linalg.norm(normal)
    v_start = math.sqrt(MU_EARTH / r1_mag) * np.cross(normal, r1 / r1_mag)
    v_end = math.sqrt(MU_EARTH / r2_mag) * np.cross(normal, r2 / r2_mag)
    sol = solve_lambert(r1, r2, tof, prograde=prograde, v1_initial=v_start, v2_target=v_end)
    assert _never_negative(sol.delta_v1_mag, sol.delta_v2_mag, sol.total_delta_v)
    assert sol.total_delta_v == pytest.approx(sol.delta_v1_mag + sol.delta_v2_mag, rel=1e-15)
    np.testing.assert_array_equal(sol.delta_v1, sol.v1 - v_start)
    np.testing.assert_array_equal(sol.delta_v2, v_end - sol.v2)
    assert sol.delta_v1_mag == pytest.approx(float(np.linalg.norm(sol.delta_v1)), rel=1e-15)


# ── RK45 (two-body, J2 and drag), the propagator the Monte Carlo and the separation series fly ──

#: a (km): 8000 keeps the e = 0.1 perigee at 822 km, above the 800 km where the model's drag starts, so the
#: only forces are two-body and, where it is left on, J2. e: circular and mildly eccentric. i: equatorial,
#: inclined and retrograde. Hours: a quarter day and a whole one.
_RK45_CASES = list(itertools.product((8000.0, 26560.0, 42164.0), (0.0, 0.1), (0.0, 51.6, 98.0), (6.0, 24.0)))

#: RK45 holds each step to rtol 1e-8 and atol 1e-10, so error grows with the number of steps, which grows with
#: the distance flown. Forward-then-back measured at most 3.6e-7 of the arc length on this grid (24 h in LEO);
#: 1e-6 of the arc length is three times that, and 0.7 km on the longest LEO case, against the tens of
#: kilometres a dropped J2 term or a sign error moves a day's propagation.
_RK45_ARC_TOL = 1e-6
#: Energy and angular momentum drift with the same step error: 2.4e-7 and 1.2e-7 relative measured. 1e-6
#: relative still catches a missing J2 term in the energy, which is 1.6e-3 of it at 8000 km.
_RK45_INVARIANT_TOL = 1e-6


def _rk45(a: float, e: float, inc: float, hours: float) -> tuple[np.ndarray, np.ndarray, float]:
    r0, v0 = _state(a, e, inc, nu_deg=30.0)
    start = np.concatenate([r0, v0])
    end = mc._integrate(start, hours * 3600.0, 0.0)
    assert end is not None
    return start, end, float(np.linalg.norm(v0)) * hours * 3600.0


def _j2_energy(state: np.ndarray) -> float:
    """Specific energy with the J2 term of the potential, which J2 motion conserves."""
    r, v = state[:3], state[3:]
    rm = float(np.linalg.norm(r))
    return _energy(r, v) + MU_EARTH * J2_EARTH * R_EARTH ** 2 / (2.0 * rm ** 3) * (3.0 * (r[2] / rm) ** 2 - 1.0)


@pytest.mark.parametrize("j2", [True, False], ids=["with J2", "two-body"])
@pytest.mark.parametrize("case", _RK45_CASES, ids=str)
def test_rk45_forward_then_back_returns_to_the_start(
    case: tuple[float, float, float, float], j2: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not j2:
        monkeypatch.setattr(mc, "_J2", 0.0)
    start, end, arc = _rk45(*case)
    back = mc._integrate(end, -case[3] * 3600.0, 0.0)
    assert back is not None
    assert float(np.linalg.norm(back[:3] - start[:3])) < _RK45_ARC_TOL * arc


@pytest.mark.parametrize(("a", "e", "inc", "hours"), _RK45_CASES)
def test_rk45_without_perturbations_is_two_body(
    a: float, e: float, inc: float, hours: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """J2 off and above the drag ceiling: energy and the whole angular momentum vector hold, and it flies Kepler."""
    monkeypatch.setattr(mc, "_J2", 0.0)
    start, end, arc = _rk45(a, e, inc, hours)
    assert abs(_energy(end[:3], end[3:]) - _energy(start[:3], start[3:])) < _RK45_INVARIANT_TOL * abs(
        _energy(start[:3], start[3:]))
    assert _relative(np.cross(end[:3], end[3:]), np.cross(start[:3], start[3:])) < _RK45_INVARIANT_TOL
    kepler, _ = propagate_two_body(start[:3], start[3:], hours * 3600.0)
    assert float(np.linalg.norm(end[:3] - kepler)) < _RK45_ARC_TOL * arc


@pytest.mark.parametrize(("a", "e", "inc", "hours"), _RK45_CASES)
def test_rk45_with_j2_keeps_what_an_axisymmetric_field_keeps(a: float, e: float, inc: float, hours: float) -> None:
    """J2 is symmetric about the polar axis: energy with its potential term and the polar angular momentum hold."""
    start, end, _ = _rk45(a, e, inc, hours)
    h0, h1 = np.cross(start[:3], start[3:]), np.cross(end[:3], end[3:])
    assert abs(_j2_energy(end) - _j2_energy(start)) < _RK45_INVARIANT_TOL * abs(_j2_energy(start))
    assert abs(h1[2] - h0[2]) < _RK45_INVARIANT_TOL * float(np.linalg.norm(h0))
    if inc == 0.0:
        # In the equator the J2 force stays in the plane, so the whole vector holds.
        assert _relative(h1, h0) < _RK45_INVARIANT_TOL
    elif a == 8000.0:
        # Control: J2 really is on. In LEO, where it is strongest, the node regresses 0.6 to 2.8 degrees a
        # day on this grid, so the full vector turns by far more than the tolerance. At GPS and GEO the turn
        # in a day is under a hundred times the tolerance, too close to call a control.
        assert _relative(h1, h0) > 100 * _RK45_INVARIANT_TOL


# ── Manoeuvres ──

#: Circular radii (km): 500 km LEO, 1000 km LEO, GPS, GEO. Every ordered pair, the four equal pairs included.
_RADII = (6878.0, 7378.0, 26560.0, 42164.0)


@pytest.mark.parametrize(("r1", "r2"), list(itertools.product(_RADII, _RADII)))
def test_hohmann_is_never_negative_symmetric_and_free_between_equal_orbits(r1: float, r2: float) -> None:
    there, back = hohmann(r1, r2), hohmann(r2, r1)
    assert _never_negative(there.delta_v_1, there.delta_v_2, there.total_delta_v)
    assert there.total_delta_v == there.delta_v_1 + there.delta_v_2
    # Raising and lowering between the same two orbits cost the same and take the same time.
    assert there.total_delta_v == pytest.approx(back.total_delta_v, rel=1e-12)
    assert there.transfer_time_s == pytest.approx(back.transfer_time_s, rel=1e-12)
    if r1 == r2:
        assert there.total_delta_v == 0.0
        assert there.transfer_time_s == pytest.approx(_period(r1) / 2.0, rel=1e-12)


@pytest.mark.parametrize(("r1", "r2"), [(r1, r2) for r1, r2 in itertools.product(_RADII, _RADII) if r1 != r2])
def test_a_hohmann_transfer_flown_arrives_at_the_radius_and_time_it_promised(r1: float, r2: float) -> None:
    """Fly the first burn with Kepler for the stated time: the orbit is at r2, and the second burn circularises it."""
    transfer = hohmann(r1, r2)
    r0, v0 = _state(r1, 0.0, 28.5)
    sense = 1.0 if r2 > r1 else -1.0
    v_after = v0 + sense * transfer.delta_v_1 * v0 / np.linalg.norm(v0)
    r_end, v_end = propagate_two_body(r0, v_after, transfer.transfer_time_s)
    assert float(np.linalg.norm(r_end)) == pytest.approx(r2, rel=_KEPLER_TOL)
    assert abs(float(r_end @ v_end)) / (r2 * float(np.linalg.norm(v_end))) < _KEPLER_TOL, "not at an apsis"
    circular = float(np.linalg.norm(v_end)) + sense * transfer.delta_v_2
    assert circular == pytest.approx(math.sqrt(MU_EARTH / r2), rel=_KEPLER_TOL)


@pytest.mark.parametrize(("r1", "r2", "rb"), list(itertools.product((7000.0, 42164.0), (7000.0, 42164.0), (5e4, 1e5))))
def test_bielliptic_is_never_negative_and_symmetric(r1: float, r2: float, rb: float) -> None:
    there, back = bielliptic(r1, r2, rb), bielliptic(r2, r1, rb)
    assert _never_negative(there.delta_v_1, there.delta_v_2, there.delta_v_3)
    assert there.total_delta_v == there.delta_v_1 + there.delta_v_2 + there.delta_v_3
    assert there.total_delta_v == pytest.approx(back.total_delta_v, rel=1e-12)


#: Burn directions in ECI: the six axes and four diagonals. Magnitudes (km/s): none, 0.1 m/s and 500 m/s.
_DIRECTIONS = [np.array(d, dtype=float) for d in (
    (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (1, 1, 0), (1, -1, 1), (-1, 2, 3), (0, 1, -1),
)]
_MAGNITUDES = (0.0, 1e-4, 0.5)
_BURN_STATES = [(7000.0, 0.0, 51.6), (26560.0, 0.5, 63.4), (42164.0, 0.0, 0.1)]


@pytest.mark.parametrize(("orbit", "direction", "magnitude"), list(itertools.product(
    _BURN_STATES, range(len(_DIRECTIONS)), _MAGNITUDES,
)))
def test_a_burn_split_into_its_axes_keeps_its_size(
    orbit: tuple[float, float, float], direction: int, magnitude: float,
) -> None:
    """The along-track, normal and radial parts are an orthonormal split: never more or less burn than was asked."""
    r, v = _state(*orbit, nu_deg=40.0)
    dv = magnitude * _DIRECTIONS[direction] / np.linalg.norm(_DIRECTIONS[direction])
    burn = _make_burn(1, _EPOCH, dv, StateVector(epoch=_EPOCH, r=r, v=v))
    assert _never_negative(burn.delta_v_mag)
    assert burn.delta_v_mag == pytest.approx(magnitude, rel=1e-12, abs=0.0)
    parts = math.sqrt(burn.dv_prograde ** 2 + burn.dv_normal ** 2 + burn.dv_radial ** 2)
    assert parts == pytest.approx(magnitude, rel=1e-12, abs=0.0)


@pytest.mark.parametrize("orbit", _BURN_STATES)
def test_a_burn_along_the_velocity_is_all_prograde(orbit: tuple[float, float, float]) -> None:
    r, v = _state(*orbit, nu_deg=40.0)
    burn = _make_burn(1, _EPOCH, 0.01 * v / np.linalg.norm(v), StateVector(epoch=_EPOCH, r=r, v=v))
    assert burn.dv_prograde == pytest.approx(0.01, rel=1e-12)
    assert abs(burn.dv_normal) < 1e-15 and abs(burn.dv_radial) < 1e-15


@pytest.mark.parametrize("orbit", _BURN_STATES)
def test_each_axis_of_a_burn_is_reported_on_its_own_axis_with_its_own_sign(orbit: tuple[float, float, float]) -> None:
    """The operator reads the normal and radial parts as figures with a sign; a swap or a flip must show.

    Normal is along h = r x v (the orbit normal), radial along v x h (away
    from the Earth's side of the velocity), as _make_burn's VNB frame defines
    them. Each unit burn along one axis is all on that axis, positive, and
    its opposite is all negative. The 1e-15 km/s floor is round-off on unit
    vectors of a 0.01 km/s burn.
    """
    r, v = _state(*orbit, nu_deg=40.0)
    sv = StateVector(epoch=_EPOCH, r=r, v=v)
    h = np.cross(r, v)
    along_h = 0.01 * h / np.linalg.norm(h)
    away = np.cross(v, h)
    along_vxh = 0.01 * away / np.linalg.norm(away)
    for sign in (1.0, -1.0):
        normal = _make_burn(1, _EPOCH, sign * along_h, sv)
        assert normal.dv_normal == pytest.approx(sign * 0.01, rel=1e-12)
        assert abs(normal.dv_prograde) < 1e-15 and abs(normal.dv_radial) < 1e-15
        radial = _make_burn(1, _EPOCH, sign * along_vxh, sv)
        assert radial.dv_radial == pytest.approx(sign * 0.01, rel=1e-12)
        assert abs(radial.dv_prograde) < 1e-15 and abs(radial.dv_normal) < 1e-15
    # Positive radial points away from the Earth: an outward push along r reads as a positive radial part.
    assert _make_burn(1, _EPOCH, 0.01 * r / np.linalg.norm(r), sv).dv_radial > 0.0


@pytest.mark.parametrize("orbit", _BURN_STATES)
def test_the_ric_frame_is_a_rotation_so_a_burn_keeps_its_size_across_frames(orbit: tuple[float, float, float]) -> None:
    r, v = _state(*orbit, nu_deg=40.0)
    rotation = mc._ric_to_eci_rotation(r, v)
    np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-14)
    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=1e-14)
    for direction in _DIRECTIONS:
        assert float(np.linalg.norm(rotation @ direction)) == pytest.approx(float(np.linalg.norm(direction)), rel=1e-14)


#: Orbits above the drag ceiling (as _RK45_CASES), a 6 h horizon, and the in-track burn that is the control.
_SAMPLE_ORBITS = list(itertools.product((8000.0, 42164.0), (0.0, 0.1), (0.0, 51.6)))


@pytest.mark.parametrize(("a", "e", "inc"), _SAMPLE_ORBITS)
def test_a_zero_delta_v_sample_leaves_the_orbit_unchanged(a: float, e: float, inc: float) -> None:
    r0, v0 = _state(a, e, inc, nu_deg=30.0)
    pre = np.concatenate([r0, v0])
    unburnt = mc._integrate(pre, 6 * 3600.0, 1e-4)
    assert unburnt is not None
    still = mc.propagate_single_sample(np.zeros(5), pre, 1e-4, 6.0)
    assert still is not None
    np.testing.assert_array_equal(still["r_final"], unburnt[:3])
    # Control: a 10 m/s in-track burn lands exactly where the same burn, applied by hand, does. The
    # in-track axis is built here from h x r, not from the rotation under test. The two paths differ
    # only by round-off in the burnt velocity (about 1e-16 relative), which six hours of RK45 does not
    # grow past a millimetre, while a burn of the wrong size or axis misses by kilometres.
    raised = mc.propagate_single_sample(np.array([0.0, 0.01, 0.0, 0.0, 0.0]), pre, 1e-4, 6.0)
    assert raised is not None
    h = np.cross(r0, v0)
    in_track = np.cross(h / np.linalg.norm(h), r0 / np.linalg.norm(r0))
    by_hand = mc._integrate(np.concatenate([r0, v0 + 0.01 * in_track]), 6 * 3600.0, 1e-4)
    assert by_hand is not None
    np.testing.assert_allclose(raised["r_final"], by_hand[:3], rtol=0.0, atol=1e-6)
    assert raised["sma_km"] > still["sma_km"] + 1.0


#: Seeds, nominal magnitudes (km/s) and both distributions, with the spread off so each draw is exact.
_SAMPLER_GRID = list(itertools.product((0, 1, 7), (0.0, 0.002, 0.05), ("gaussian", "uniform")))


@pytest.mark.parametrize(("seed", "magnitude", "distribution"), _SAMPLER_GRID)
def test_the_sampler_never_turns_a_burn_round_or_invents_one(seed: int, magnitude: float, distribution: str) -> None:
    """Pointing scatter turns a burn but never resizes it, and a zero burn with no spread stays zero."""
    r0, v0 = _state(8000.0, 0.0, 51.6)
    hypothesis = mc.ManoeuvreHypothesis(
        epoch_utc=_EPOCH, delta_v_magnitude_km_s=magnitude, delta_v_radial=0.0, delta_v_in_track=1.0,
        delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=np.concatenate([r0, v0]),
        delta_v_magnitude_1sigma_km_s=0.0, delta_v_pointing_1sigma_deg=5.0, n_samples=200, random_seed=seed,
        distribution_type=distribution,
    )
    sizes = np.linalg.norm(mc.generate_samples(hypothesis)[:, :3], axis=1)
    np.testing.assert_allclose(sizes, magnitude, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize(("seed", "distribution"), list(itertools.product((0, 1, 7), ("gaussian", "uniform"))))
def test_a_sampled_burn_is_never_negative_even_when_the_spread_reaches_below_zero(seed: int, distribution: str) -> None:
    """A 1 m/s burn with a 5 m/s spread draws negative sizes; each is folded to its size along the nominal direction.

    generate_samples takes the absolute value of every drawn magnitude, so a
    negative draw becomes a positive burn the same way, never a negative
    burn and never a burn turned round.
    """
    r0, v0 = _state(8000.0, 0.0, 51.6)
    hypothesis = mc.ManoeuvreHypothesis(
        epoch_utc=_EPOCH, delta_v_magnitude_km_s=0.001, delta_v_radial=0.0, delta_v_in_track=1.0,
        delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=np.concatenate([r0, v0]),
        delta_v_magnitude_1sigma_km_s=0.005, delta_v_pointing_1sigma_deg=0.0, n_samples=400, random_seed=seed,
        distribution_type=distribution,
    )
    in_track = mc.generate_samples(hypothesis)[:, 1]
    # No pointing scatter, so every sample lies along +in-track with its size as the component.
    assert _never_negative(*in_track)
    assert (in_track > 0.0).sum() == 400
