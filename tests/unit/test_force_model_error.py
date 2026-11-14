"""What the engine's force model leaves out, measured by regime and burn size and stated (SPC-209, evaluation F-19).

The engine's RK45 flies two-body, J2 and exponential drag, and the module said burn dispersion dominates force-model
error at 48 h. The evaluation found RK45 and SDP4, which has lunisolar terms, 11 to 18 km apart at GEO over 48 to
72 h. This measures the omission against a higher-fidelity reference (tests/unit/_force_model_reference.py: J2 to J4,
the Moon and the Sun from analytic series, cannonball radiation pressure at Cr 1.3 and 0.02 m^2/kg, and the engine's
own drag), after checking the reference itself:

● with J3, J4, the Moon, the Sun and radiation pressure off, its equations are the engine's to rounding, and it flies
  the engine's model to the engine's own stated integrator error (monte_carlo.INTEGRATOR_ERROR_KM);
● its J3 and J4 accelerations are the gradient of the zonal potential;
● its Sun reproduces Meeus's worked example 25.a (Astronomical Algorithms, 2nd ed., 1998) and is within Meeus's 0.01
  degree of the 2026 equinoxes and solstices (USNO, to the minute); its Moon, Montenbruck and Gill's series, is within
  0.05 degree and 100 km of Meeus's worked example 47.a, from a fuller lunar theory, and puts the Moon within 0.05
  degree of opposition and conjunction at the full moon of 3 March and the new moon of 17 February 2026 (USNO, to the
  minute). No accuracy figure for Montenbruck and Gill's lunar series could be checked in this build, so these bounds
  are the check used, not a published accuracy.

The measurement flies 6 reference pairs, one to three per regime as along_track.orbit_regime states it: the 500 km
co-planar and 550 km polar pairs of tests/unit/_decision_reference.py and a 500 km co-planar pair whose closest
approach comes about 26 h on (LEO), a co-planar pair at 20,200 km and 55 degrees (MEO), the GEO drift-in pair, closest
about 31 h on, and a Molniya pair, e 0.74 at 63.4 degrees, perigee 528 km, 0.1 degree apart in mean anomaly
(HEO/Molniya). Each object starts from its SGP4 state at the cases' epoch, B* 1e-4, Cr 1.3. Blue's area-to-mass ratio
is 0.02 m^2/kg; red's is the same (alike), or 0.005 or none (unlike), since radiation pressure on two objects of the
same ratio largely cancels in their separation and on two unlike objects does not. Red is given an in-track burn at
the epoch of none, 0.1, 1 or 10 m/s: a collision-avoidance burn, half the evasive and station-keeping archetypes'
2 m/s, and the phasing archetype's. Read every 60 s up to 24, 48 and 72 h:

● position: how far the reference moves each object from where the engine's forces put it, both flown by DOP853 at
  rtol 1e-11, so the integrator's own error, stated apart, is not in it;
● separation: how far the reference moves the pair's separation, alike and unlike;
● the sampled spread: half the width between P5 and P95 of the pair's separation over 200 samples of the engine's own
  draws (monte_carlo.generate_samples, seed 42) flown by the engine's forces, each burn sampled with the Intercept /
  Approach archetype's spreads, 3 per cent of the delta-V, 1.5 degrees and 15 s, the tightest the engine holds, and
  B* 1e-5 either way; with no burn it is drag's spread alone. The share is the separation change, the worst case,
  over the spread at the same instant, the largest at any instant read every 10 min up to the horizon;
● the closest approach: how far the reference moves the pair's nominal closest approach up to the horizon, set
  against half the width from P5 to P95 of the samples' own closest approaches, the misses a sampled cell's P5 is
  read from. Each is the nearest 60 s reading refined along the straight line of the relative velocity.

Measured at this commit (scipy 1.17.1, sgp4 2.27), by 72 h: each object moves up to 7.01 km in LEO, 3.25 km in MEO,
23.81 km at GEO and 7.89 km in HEO/Molniya. Alike, a close pair's separation moves under 0.1 km outside LEO and up to
4.05 km in LEO, where the late pair's moves most when it is thousands of km apart; unlike, with no burn, it moves 1.19
km in MEO, 2.42 km at GEO and 1.64 km in HEO/Molniya. With no burn the spread is drag's alone and the change exceeds it
in every pair. The worst share at any instant, by regime, with burns of 0.1, 1 and 10 m/s: LEO 1.78, 0.135 and 0.0155;
MEO 0.354, 0.0355 and 0.0038; GEO 4.83, 0.074 and 0.0063; HEO/Molniya 0.905, 0.0885 and 0.0081. The closest approach
moves less against its own spread: under a tenth with 1 m/s or more in every pair; with 0.1 m/s up to 0.69 at GEO and
1.13 for the late LEO pair by 24 h, when its closest approach falls at the window's end. monte_carlo.FORCE_MODEL_KM and
FORCE_MODEL_SHARE state the figures, rounded up, and docs/decision_engine_phases.md carries both tables, all held here
to what is measured. The file takes about 50 s, most of it the measurement, which runs once per pair and is cached.
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import monte_carlo
from spectre.astro.along_track import orbit_regime, position_error_km
from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES, ManoeuvreHypothesis, generate_samples
from spectre.astro.propagator import TLEOrbit
from spectre.domain import decision
from tests.unit import _force_model_reference as ref
from tests.unit._decision_reference import (
    COPLANAR_LEO,
    EPOCH,
    EPOCH_DAY,
    GEO_DRIFT_IN,
    PLANE_CHANGE,
    RE_KM,
    SIDEREAL_DAY_S,
    Circular,
    _checksum,
    coplanar_closed_form,
    element_set,
)
from tests.unit.test_deployment_contract import _repo_only
from tests.unit.test_p5_half_width import _SKEWED, _series

_HOUR_S = 3600.0
_BSTAR = 1e-4
_STEP_S = 60.0
_HORIZONS = (24, 48, 72)
_BURNS_M_S = (0.0, 0.1, 1.0, 10.0)
_ARCHETYPE = MANOEUVRE_ARCHETYPES["intercept_approach"]
_SAMPLES = 200
_SEED = 42
#: Each stated figure is at most this much above the one measured, km.
_SLACK_KM = 0.01
_DEG = math.pi / 180.0


def _molniya_set(satno: int, anomaly_deg: float) -> str:
    """A two-line element set of a Molniya orbit at *anomaly_deg* of mean anomaly, both lines 69 columns with computed
    checksums: half a sidereal day's period, e 0.74, 63.4 degrees, RAAN 40 degrees and perigee at 270 degrees."""
    n = 2.0 * 86400.0 / SIDEREAL_DAY_S
    ecc, inc, raan, argp = 0.74, 63.4, 40.0, 270.0
    line1 = f"1 {satno:05d}U 26001A   {EPOCH_DAY}  .00000000  00000-0  00000-0 0  999"
    line2 = (f"2 {satno:05d} {inc:8.4f} {raan:8.4f} {round(ecc * 1e7):07d} {argp:8.4f} {anomaly_deg:8.4f} "
             f"{n:11.8f}{1:5d}")
    return f"{line1}{_checksum(line1)}\n{line2}{_checksum(line2)}"


#: Each pair's regime, red's element set and blue's. The late LEO pair's closest approach comes about 26 h after the
#: epoch and the GEO pair's about 31 h after it; the rest are closest within the first few hours.
_PAIRS: dict[str, tuple[str, str, str]] = {
    "LEO, 500 km": ("LEO", COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle),
    "LEO, 500 km, late": ("LEO", element_set(Circular(90002, RE_KM + 510.0, 51.6, 40.0, 13.0)),
                          COPLANAR_LEO.blue_tle),
    "LEO, 550 km polar": ("LEO", PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle),
    "MEO": ("MEO", element_set(Circular(90002, RE_KM + 20210.0, 55.0, 40.0, 0.1)),
            element_set(Circular(90001, RE_KM + 20200.0, 55.0, 40.0, 0.0))),
    "GEO": ("GEO", GEO_DRIFT_IN.red_tle, GEO_DRIFT_IN.blue_tle),
    "HEO/Molniya": ("HEO/Molniya", _molniya_set(90002, 179.9), _molniya_set(90001, 180.0)),
}
_REGIMES = ("LEO", "MEO", "GEO", "HEO/Molniya")
#: Red's area-to-mass ratio, m^2/kg, in each case flown, blue's always being 0.02: alike, then two unlike objects.
_RED_AREA_TO_MASS = (ref.SRP_AREA_TO_MASS_M2_KG, 0.005, 0.0)
_CASES = len(_RED_AREA_TO_MASS)
#: How often the sampled spread is read for the worst share over time, s.
_SPREAD_STEP_S = 600.0


@dataclass(frozen=True)
class Measured:
    """What one pair gives by one horizon, km unless stated. Per burn, none, 0.1, 1 and 10 m/s:

    ● alike_km and unlike_km: the largest change in the pair's separation up to the horizon, with red's area-to-mass
      ratio blue's, and the worse of red at 0.005 and at 0 m^2/kg;
    ● spread_km: half the width from P5 to P95 of the samples' separation at the horizon;
    ● share: the largest change, the worst case of the three, over the spread at the same instant, at any instant
      read every 10 min up to the horizon; infinite where the spread is nothing;
    ● miss_moved_km: how far the reference moves the nominal closest approach up to the horizon, the worst case;
    ● miss_spread_km: half the width from P5 to P95 of the samples' closest approaches up to the horizon, the misses
      a sampled cell's P5 is read from.

    position_km: the largest change in any object's position, with any burn, in any case.
    """

    position_km: float
    alike_km: tuple[float, ...]
    unlike_km: tuple[float, ...]
    spread_km: tuple[float, ...]
    share: tuple[float, ...]
    miss_moved_km: tuple[float, ...]
    miss_spread_km: tuple[float, ...]


def _start(tle: str) -> np.ndarray:
    track = monte_carlo.elset_state(tle, EPOCH)
    assert track is not None
    return track.state_eci_km


def _burnt(state: np.ndarray, dv_km_s: float) -> np.ndarray:
    out = state.copy()
    out[3:] += monte_carlo._ric_to_eci_rotation(out[:3], out[3:]) @ np.array([0.0, dv_km_s, 0.0])
    return out


def _sampled(pre: np.ndarray, dv_km_s: float) -> tuple[np.ndarray, np.ndarray]:
    """The engine's own draws for a burn of *dv_km_s* from *pre*, each moved to the epoch: the states at the epoch that
    put each sample through its burn at its own time, and each sample's ballistic coefficient after it."""
    hypothesis = ManoeuvreHypothesis(
        epoch_utc=EPOCH, delta_v_magnitude_km_s=dv_km_s, delta_v_radial=0.0, delta_v_in_track=dv_km_s,
        delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=pre,
        delta_v_magnitude_1sigma_km_s=dv_km_s * _ARCHETYPE.delta_v_1sigma_fraction,
        delta_v_pointing_1sigma_deg=_ARCHETYPE.pointing_1sigma_deg,
        epoch_1sigma_seconds=_ARCHETYPE.timing_1sigma_seconds, bstar_post=_BSTAR, n_samples=_SAMPLES,
        random_seed=_SEED,
    )
    samples = generate_samples(hypothesis)
    at_burn = ref.flown_for(np.repeat(pre[None], _SAMPLES, 0), samples[:, 3], ref.Objects.alike(_SAMPLES, _BSTAR))
    for state, dv in zip(at_burn, samples[:, :3], strict=True):
        state[3:] += monte_carlo._ric_to_eci_rotation(state[:3], state[3:]) @ dv
    ballistic = np.array([monte_carlo._ballistic_coefficient_kg_m2(_BSTAR + b) for b in samples[:, 4]])
    after = ref.Objects(ballistic, np.zeros(_SAMPLES))
    return ref.flown_for(at_burn, -samples[:, 3], after), ballistic


def _closest(relative: np.ndarray, upto: int) -> np.ndarray:
    """Each object's closest approach, km, over the first *upto* readings of its state relative to blue (k, n, 6):
    the nearest reading, refined along the straight line its relative velocity draws, at most one step either way."""
    seps = np.linalg.norm(relative[:upto, :, :3], axis=2)
    nearest = np.argmin(seps, axis=0)
    at = relative[nearest, np.arange(relative.shape[1])]
    r, v = at[:, :3], at[:, 3:]
    speed2 = np.maximum(np.einsum("ij,ij->i", v, v), 1e-30)
    lo = np.where(nearest == 0, 0.0, -_STEP_S)
    hi = np.where(nearest == upto - 1, 0.0, _STEP_S)
    tau = np.clip(-np.einsum("ij,ij->i", r, v) / speed2, lo, hi)
    return np.linalg.norm(r + v * tau[:, None], axis=1)


@functools.cache
def _measured(pair: str) -> dict[int, Measured]:
    _, red_tle, blue_tle = _PAIRS[pair]
    red, blue = _start(red_tle), _start(blue_tle)
    grid = np.arange(0.0, max(_HORIZONS) * _HOUR_S + 1.0, _STEP_S)
    burns = len(_BURNS_M_S)
    nominal = np.array([blue] + [_burnt(red, dv / 1000.0) for dv in _BURNS_M_S for _ in range(_CASES)])
    area = [ref.SRP_AREA_TO_MASS_M2_KG] + [a for _ in _BURNS_M_S for a in _RED_AREA_TO_MASS]
    objects = ref.Objects(np.full(len(nominal), monte_carlo._ballistic_coefficient_kg_m2(_BSTAR)),
                          ref.SRP_CR * np.array(area))
    full = ref.flown(nominal, ref.Model(objects, ref.FULL, EPOCH), grid)
    engine = ref.flown(nominal, ref.Model(objects, ref.OPERATIONAL, EPOCH), grid)
    position = np.linalg.norm(full[:, :, :3] - engine[:, :, :3], axis=2).max(axis=1)
    # (time, burn, case): each red's separation change; the engine's separation is the same in every case.
    full_rel, engine_rel = full[:, 1:] - full[:, :1], engine[:, 1:] - engine[:, :1]
    change = np.abs(np.linalg.norm(full_rel[:, :, :3], axis=2) - np.linalg.norm(engine_rel[:, :, :3], axis=2))
    change = change.reshape(len(grid), burns, _CASES)
    worst = change.max(axis=2)
    every = int(_SPREAD_STEP_S / _STEP_S)
    clouds = []
    for dv in _BURNS_M_S:
        states, ballistic = _sampled(red, dv / 1000.0)
        flown = ref.flown(states, ref.Model(ref.Objects(ballistic, np.zeros(_SAMPLES)), ref.OPERATIONAL, EPOCH), grid,
                          rtol=1e-9, atol=1e-9)
        clouds.append(flown - engine[:, :1])
    out = {}
    for hours in _HORIZONS:
        upto = int(hours * _HOUR_S / _STEP_S) + 1
        spread, share, moved, miss_spread = [], [], [], []
        for j in range(burns):
            seps = np.linalg.norm(clouds[j][:upto:every, :, :3], axis=2)
            p5, p95 = np.percentile(seps, [5.0, 95.0], axis=1)
            band = (p95 - p5) / 2.0
            spread.append(float(band[-1]))
            ratios = np.divide(worst[:upto:every, j], band, out=np.full(len(band), np.inf), where=band > 0.0)
            share.append(float(np.max(ratios[1:])))
            reds = slice(1 + j * _CASES, 1 + (j + 1) * _CASES)
            mine = _closest(full[:, reds] - full[:, :1], upto)
            theirs = _closest(engine[:, reds] - engine[:, :1], upto)
            moved.append(float(np.max(np.abs(mine - theirs))))
            q5, q95 = np.percentile(_closest(clouds[j], upto), [5.0, 95.0])
            miss_spread.append(float(q95 - q5) / 2.0)
        out[hours] = Measured(
            position_km=float(position[:upto].max()),
            alike_km=tuple(float(x) for x in change[:upto, :, 0].max(axis=0)),
            unlike_km=tuple(float(x) for x in change[:upto, :, 1:].max(axis=(0, 2))),
            spread_km=tuple(spread), share=tuple(share), miss_moved_km=tuple(moved),
            miss_spread_km=tuple(miss_spread),
        )
    return out


def _figure(hours: int) -> tuple[float, float, float, float, float, float]:
    """What FORCE_MODEL_KM states by *hours*, as measured: each regime's largest position change, LEO, MEO, GEO and
    HEO/Molniya, and the largest separation change of any pair with any burn, alike and unlike."""
    leo, meo, geo, heo = (
        max(_measured(p)[hours].position_km for p, (r, _, _) in _PAIRS.items() if r == regime) for regime in _REGIMES
    )
    alike = max(max(_measured(p)[hours].alike_km) for p in _PAIRS)
    unlike = max(max(_measured(p)[hours].unlike_km) for p in _PAIRS)
    return (leo, meo, geo, heo, alike, unlike)


def _shares(regime: str) -> tuple[float, float, float]:
    """What FORCE_MODEL_SHARE states for *regime*, as measured: for burns of 0.1, 1 and 10 m/s, the largest share of
    the spread the separation change reaches at any instant up to 72 h, in any of the regime's pairs, in any case."""
    found = [_measured(p)[max(_HORIZONS)].share for p, (r, _, _) in _PAIRS.items() if r == regime]
    small, medium, large = (max(s[j] for s in found) for j in (1, 2, 3))
    return (small, medium, large)


class TestTheReference:
    """Checked before any figure it gives is trusted."""

    _STATES = (
        np.array([6778.0, 120.0, -40.0, -0.1, 7.6, 0.5]),           # 400 km: drag on
        np.array([3000.0, -4200.0, 4600.0, 5.1, 3.9, -1.2]),        # about 7,000 km out: under 800 km, drag on
        np.array([7300.0, 900.0, 1200.0, 0.4, 6.0, 4.2]),           # over 800 km: drag off
        np.array([42164.0, 30.0, 10.0, -0.002, 3.0747, 0.001]),     # GEO
    )

    def test_with_the_added_forces_off_its_equations_are_the_engines(self) -> None:
        bc = monte_carlo._ballistic_coefficient_kg_m2(_BSTAR)
        states = np.array(self._STATES)
        model = ref.Model(ref.Objects.alike(len(states), _BSTAR), ref.OPERATIONAL, EPOCH)
        mine = ref.acceleration(0.0, states[:, :3], states[:, 3:], model)
        engine = np.array([monte_carlo._j2_drag_ode(0.0, s, bc)[3:] for s in states])
        np.testing.assert_allclose(mine, engine, rtol=1e-13, atol=0.0)
        undragged = monte_carlo._j2_drag_ode(0.0, states[0], 0.0)[3:]
        assert np.linalg.norm(engine[0] - undragged) > 1e-12, "drag is on at 400 km"

    @pytest.mark.parametrize("pair", list(_PAIRS))
    def test_with_the_added_forces_off_it_flies_the_engines_model(self, pair: str) -> None:
        """Against the engine's own equations integrated tightly, to integrator tolerance; against the production
        RK45, within the engine's own stated integrator error at 72 h (INTEGRATOR_ERROR_KM, GEO's figure at GEO and
        LEO's, the larger, elsewhere)."""
        regime, red_tle, blue_tle = _PAIRS[pair]
        states = np.array([_start(red_tle), _start(blue_tle)])
        span = max(_HORIZONS) * _HOUR_S
        grid = np.arange(0.0, span + 1.0, 600.0)
        mine = ref.flown(states, ref.Model(ref.Objects.alike(2, _BSTAR), ref.OPERATIONAL, EPOCH), grid)
        bc = monte_carlo._ballistic_coefficient_kg_m2(_BSTAR)
        stated = monte_carlo.INTEGRATOR_ERROR_KM[72][1 if regime == "GEO" else 0]
        for k, state in enumerate(states):
            tight = solve_ivp(monte_carlo._j2_drag_ode, (0.0, span), state, method="DOP853", rtol=1e-12, atol=1e-14,
                              args=(bc,), t_eval=grid)
            assert tight.success
            assert np.max(np.linalg.norm(tight.y[:3].T - mine[:, k, :3], axis=1)) < 0.002, pair
            arc = monte_carlo.rk45_arc(state, span, _BSTAR)
            assert arc is not None
            production = np.array([arc(t)[:3] for t in grid])
            assert np.max(np.linalg.norm(production - mine[:, k, :3], axis=1)) <= stated, pair

    def test_j3_and_j4_are_the_gradient_of_the_zonal_potential(self) -> None:
        mu, re = monte_carlo._MU, monte_carlo._R_E

        def potential(r: np.ndarray) -> float:
            rn = float(np.linalg.norm(r))
            s = r[2] / rn
            p3 = 0.5 * (5.0 * s**3 - 3.0 * s)
            p4 = 0.125 * (35.0 * s**4 - 30.0 * s**2 + 3.0)
            return -mu / rn * (ref.J3 * (re / rn) ** 3 * p3 + ref.J4 * (re / rn) ** 4 * p4)

        for r in (np.array([6778.0, 120.0, 2000.0]), np.array([-3000.0, 4200.0, -4600.0]), np.array([7000.0, 0, 0])):
            h = 1e-3
            gradient = np.array([(potential(r + h * e) - potential(r - h * e)) / (2 * h) for e in np.eye(3)])
            np.testing.assert_allclose(ref.zonal_j3_j4(r[None])[0], gradient, rtol=1e-6, atol=1e-16)

    def test_radiation_pressure_is_the_cannonball_figure_in_sunlight_and_none_in_the_shadow(self) -> None:
        sun = ref.sun_position_km(ref.centuries_tt(EPOCH))
        to_sun = sun / np.linalg.norm(sun)
        positions = np.array([7000.0 * to_sun, -7000.0 * to_sun])
        objects = ref.Objects.alike(2, _BSTAR)
        only = ref.Forces(j3_j4=False, moon=False, sun=False, srp=True)
        still = np.zeros((2, 3))
        extra = (ref.acceleration(0.0, positions, still, ref.Model(objects, only, EPOCH))
                 - ref.acceleration(0.0, positions, still, ref.Model(objects, ref.OPERATIONAL, EPOCH)))
        # 4.56e-6 N/m^2 by Cr 1.3 by 0.02 m^2/kg is 1.186e-7 m/s^2 at 1 au, scaled by the inverse square.
        expected = 4.56e-6 * 1.3 * 0.02 * 1e-3 * (ref.AU_KM / np.linalg.norm(positions[0] - sun)) ** 2
        assert np.linalg.norm(extra[0]) == pytest.approx(expected, rel=1e-9)
        assert float(extra[0] @ to_sun) < 0.0, "pushed away from the Sun"
        assert np.linalg.norm(extra[1]) < 1e-20

    def test_the_sun_reproduces_meeus_example_25a(self) -> None:
        """1992 October 13.0 TD, JDE 2448908.5: true longitude 199.90988 degrees and R 0.99766 au (Meeus, 25.a)."""
        longitude, latitude, distance = ref.sun_ecliptic((2448908.5 - 2451545.0) / 36525.0)
        assert math.degrees(longitude) % 360.0 == pytest.approx(199.90988, abs=2e-5)
        assert latitude == 0.0
        assert distance / ref.AU_KM == pytest.approx(0.99766, abs=1e-5)

    @pytest.mark.parametrize(("when", "longitude"), [
        (datetime(2026, 3, 20, 14, 46, tzinfo=UTC), 0.0), (datetime(2026, 6, 21, 8, 24, tzinfo=UTC), 90.0),
        (datetime(2026, 9, 23, 0, 5, tzinfo=UTC), 180.0), (datetime(2026, 12, 21, 20, 50, tzinfo=UTC), 270.0),
    ])
    def test_the_sun_is_within_meeuss_accuracy_at_the_2026_equinoxes_and_solstices(
        self, when: datetime, longitude: float,
    ) -> None:
        """The Sun's apparent longitude is 0, 90, 180 or 270 degrees at each (USNO's times, to the minute, so within
        0.0003 degree); apparent is the geometric longitude less 0.00569 degree of aberration and 0.00478 sin(omega)
        of nutation (Meeus, chapter 25). Within Meeus's 0.01 degree; measured at most 0.0065."""
        t = ref.centuries_tt(when)
        omega = (125.04 - 1934.136 * t) * _DEG
        apparent = math.degrees(ref.sun_ecliptic(t)[0]) - 0.00569 - 0.00478 * math.sin(omega)
        assert abs((apparent - longitude + 180.0) % 360.0 - 180.0) < 0.01

    def test_the_moon_against_meeus_example_47a(self) -> None:
        """1992 April 12.0 TD, JDE 2448724.5: longitude 133.162655 and latitude -3.229126 degrees, distance 368,409.7
        km (Meeus, 47.a, from a fuller lunar theory). Measured: 0.0053 and 0.0022 degree, 51 km."""
        longitude, latitude, distance = ref.moon_ecliptic((2448724.5 - 2451545.0) / 36525.0)
        assert abs(math.degrees(longitude) % 360.0 - 133.162655) < 0.05
        assert abs(math.degrees(latitude) + 3.229126) < 0.05
        assert abs(distance - 368409.7) < 100.0

    @pytest.mark.parametrize(("when", "elongation"), [
        (datetime(2026, 3, 3, 11, 38, tzinfo=UTC), 180.0), (datetime(2026, 2, 17, 12, 1, tzinfo=UTC), 0.0),
    ])
    def test_the_moon_at_the_2026_full_and_new_moons(self, when: datetime, elongation: float) -> None:
        """The Moon's longitude less the Sun's is 180 degrees at full moon and 0 at new (USNO's times, to the minute,
        so within 0.005 degree). Measured 0.007 and 0.016 degree."""
        t = ref.centuries_tt(when)
        found = math.degrees(ref.moon_ecliptic(t)[0] - ref.sun_ecliptic(t)[0])
        assert abs((found - elongation + 180.0) % 360.0 - 180.0) < 0.05


@pytest.mark.parametrize("pair", list(_PAIRS))
def test_each_pair_is_in_its_regime(pair: str) -> None:
    regime, red_tle, blue_tle = _PAIRS[pair]
    for tle in (red_tle, blue_tle):
        orbit = TLEOrbit(tle)
        assert orbit_regime(orbit.period_minutes, orbit.eccentricity) == regime


def test_the_late_pairs_closest_approach_is_a_day_on() -> None:
    """Every other pair but GEO's is closest within hours of the epoch; this one about 26 h on, two-body."""
    blue = Circular(90001, RE_KM + 500.0, 51.6, 40.0, 0.0)
    _, tca_s = coplanar_closed_form(blue, Circular(90002, RE_KM + 510.0, 51.6, 40.0, 13.0))
    assert 26.0 < tca_s / _HOUR_S < 26.5
    assert GEO_DRIFT_IN.tca_s / _HOUR_S > 31.0


class TestWhatIsMeasured:
    @pytest.mark.parametrize("hours", _HORIZONS)
    def test_each_stated_figure_holds_what_is_measured(self, hours: int) -> None:
        for said, found in zip(monte_carlo.FORCE_MODEL_KM[hours], _figure(hours), strict=True):
            assert found <= said <= found + _SLACK_KM, (hours, said, found)

    def test_the_stated_figures(self) -> None:
        assert monte_carlo.FORCE_MODEL_KM == {
            24: (2.33, 1.31, 7.24, 2.8, 1.32, 1.36),
            48: (4.67, 2.31, 15.08, 5.41, 2.74, 2.81),
            72: (7.01, 3.25, 23.81, 7.89, 4.05, 4.16),
        }

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_each_stated_share_holds_what_is_measured(self, regime: str) -> None:
        """Rounded up to 2 significant figures, so at or above what is measured and at most 11 per cent over it."""
        for said, found in zip(monte_carlo.FORCE_MODEL_SHARE[regime], _shares(regime), strict=True):
            assert found <= said <= found * 1.11, (regime, said, found)

    def test_the_stated_shares(self) -> None:
        assert monte_carlo.FORCE_MODEL_SHARE == {
            "LEO": (1.8, 0.14, 0.016),
            "MEO": (0.36, 0.036, 0.0038),
            "GEO": (4.9, 0.074, 0.0063),
            "HEO/Molniya": (0.91, 0.089, 0.0082),
        }

    def test_at_geo_each_object_moves_as_the_evaluation_found(self) -> None:
        """F-19: RK45 and SDP4 part by 11 to 18 km at GEO over 48 to 72 h. The reference moves each GEO object 15 km
        by 48 h and 24 km by 72 h. Two objects of the same area-to-mass ratio move alike, so their separation moves
        under 0.1 km with no burn; when one has none, it moves 2.4 km."""
        geo = _measured("GEO")
        assert 11.0 < geo[48].position_km < 18.0
        assert geo[72].position_km > 18.0
        assert geo[72].alike_km[0] < 0.1
        assert 2.3 < geo[72].unlike_km[0] < 2.5

    @pytest.mark.parametrize("pair", ["MEO", "GEO", "HEO/Molniya"])
    def test_outside_leo_unlike_objects_part_by_a_kilometre_or_more_by_72_h_and_alike_ones_by_under_a_tenth(
        self, pair: str,
    ) -> None:
        found = _measured(pair)[72]
        assert found.alike_km[0] < 0.1, pair
        assert found.unlike_km[0] > 1.0, pair

    def test_with_no_burn_it_exceeds_the_drag_spread_in_every_pair(self) -> None:
        for pair in _PAIRS:
            assert _measured(pair)[72].share[0] > 1.0, pair

    def test_with_a_burn_of_0_1_m_s_it_exceeds_the_spread_in_leo_and_at_geo_and_is_over_a_tenth_elsewhere(self) -> None:
        shares = {regime: _shares(regime)[0] for regime in _REGIMES}
        assert shares["LEO"] > 1.0 and shares["GEO"] > 1.0
        assert 0.1 < shares["MEO"] < 1.0 and 0.1 < shares["HEO/Molniya"] < 1.0

    def test_with_a_burn_of_1_m_s_it_is_over_a_tenth_in_leo_and_under_a_tenth_elsewhere(self) -> None:
        shares = {regime: _shares(regime)[1] for regime in _REGIMES}
        assert 0.1 < shares["LEO"] < 0.2
        assert all(shares[r] < 0.1 for r in ("MEO", "GEO", "HEO/Molniya"))

    def test_with_a_burn_of_10_m_s_it_is_under_a_fiftieth_everywhere(self) -> None:
        assert all(_shares(regime)[2] < 0.02 for regime in _REGIMES)

    def test_the_closest_approach_a_cell_reads_moves_less(self) -> None:
        """Set against the spread of the samples' closest approaches, the misses a sampled cell's P5 is read from:
        under a tenth with a burn of 1 m/s or more in every pair; with 0.1 m/s up to 0.69 at GEO, and 1.13 for the
        late LEO pair by 24 h, whose closest approach then falls at the window's end."""
        shares = {
            (pair, hours, j): found.miss_moved_km[j] / found.miss_spread_km[j]
            for pair in _PAIRS for hours, found in _measured(pair).items() for j in (1, 2, 3)
        }
        assert all(share < 0.1 for (_, _, j), share in shares.items() if j > 1)
        assert 1.1 < shares[("LEO, 500 km, late", 24, 1)] < 1.2
        assert 0.6 < max(s for (p, _, j), s in shares.items() if p == "GEO" and j == 1) < 0.7

    def test_against_the_element_set_error_each_sample_draws(self) -> None:
        """With no burn, by 72 h: between alike objects, outside LEO under a tenth of the smallest element-set error
        the engine draws (2 km by the GEO figure, 1 km by the LEO figure, which MEO and HEO/Molniya take), and in LEO
        the 500 km pairs' at or over it; between unlike objects at GEO, over it."""
        for pair, (regime, _, _) in _PAIRS.items():
            floor = position_error_km(0.0, "GEO" if regime == "GEO" else "LEO")
            alike = _measured(pair)[72].alike_km[0]
            if regime != "LEO":
                assert alike < floor / 10.0, pair
        assert _measured("LEO, 500 km")[72].alike_km[0] >= position_error_km(0.0, "LEO")
        assert _measured("LEO, 500 km, late")[72].alike_km[0] >= position_error_km(0.0, "LEO")
        assert _measured("GEO")[72].unlike_km[0] > position_error_km(0.0, "GEO")


_ROW = re.compile(r"^\| (?P<pair>[^|]+?) \| (?P<h>\d+) h \|(?P<rest>.+)\|$")


def _table(heading: str) -> dict[tuple[str, int], list[float]]:
    """The SPC-209 table under *heading* in docs/decision_engine_phases.md, by pair and horizon."""
    text = _repo_only("docs/decision_engine_phases.md").read_text(encoding="utf-8")
    section = text[text.index(heading):]
    section = section[: section.index("\n\n", section.index("| Pair"))]
    rows = {}
    for line in section.splitlines():
        match = _ROW.match(line.strip())
        if match:
            rows[(match["pair"], int(match["h"]))] = [float(c.strip()) for c in match["rest"].split("|")]
    return rows


def _printed_as(shown: float, value: float) -> bool:
    """Whether *shown* is *value* as printed, to half its last digit and 2 per cent for another platform's sums."""
    digit = 0.00005 if shown < 1.0 and value < 1.0 else 0.005
    return abs(shown - value) <= digit + 0.02 * abs(value)


def test_the_table_of_what_the_forces_move_is_what_is_measured() -> None:
    rows = _table("**What the forces move** (SPC-209")
    assert len(rows) == len(_PAIRS) * len(_HORIZONS)
    for (pair, hours), printed in rows.items():
        found = _measured(pair)[hours]
        expected = [found.position_km, *found.alike_km, *found.unlike_km]
        assert len(printed) == len(expected)
        for shown, value in zip(printed, expected, strict=True):
            assert abs(shown - value) <= 0.0005 + 0.005 * (shown >= 1.0) + 0.01 * abs(value), (pair, hours, shown)


def test_the_table_against_the_spread_is_what_is_measured() -> None:
    rows = _table("**Against the spread sampled** (SPC-209")
    assert len(rows) == len(_PAIRS) * len(_HORIZONS)
    for (pair, hours), printed in rows.items():
        found = _measured(pair)[hours]
        misses = [found.miss_moved_km[j] / found.miss_spread_km[j] for j in (1, 2, 3)]
        spreads, shares = printed[:3], printed[3:]
        assert len(printed) == 9
        for shown, value in zip(spreads, found.spread_km[1:], strict=True):
            assert abs(shown - value) <= 0.0005 + 0.05 * (shown >= 100.0) + 0.01 * abs(value), (pair, hours, shown)
        for shown, value in zip(shares, [*found.share[1:], *misses], strict=True):
            assert _printed_as(shown, value), (pair, hours, shown, value)


_BASE_72 = (
    "force model, not in the spread: RK45 leaves out J3 and J4, the Moon, the Sun and solar radiation pressure, which "
    "against a higher-fidelity reference moved each object of 6 reference pairs up to 7.01 km in LEO, 3.25 km in MEO, "
    "23.81 km at GEO and 7.89 km in HEO/Molniya by 72 h, and a pair's separation up to 4.05 km when both objects have "
    "the same area-to-mass ratio and up to 4.16 km when one has 0.02 m^2/kg and the other 0.005 or none; "
)
_AGAINST = ", set against the spread sampled at any instant up to 72 h, between such unlike objects, they are "


class TestTheWords:
    def test_in_leo(self) -> None:
        assert monte_carlo.force_model_words(72.0, "LEO") == (
            f"{_BASE_72}in LEO{_AGAINST}larger than it with no burn, when it is drag's alone, and with a burn of "
            "0.1 m/s (1.8 times it), over a tenth of it with a burn of 1 m/s (0.14 times) and under a tenth with a "
            "burn of 10 m/s (0.016 times)"
        )

    def test_at_geo(self) -> None:
        assert monte_carlo.force_model_words(72.0, "GEO").endswith(
            f"at GEO{_AGAINST}larger than it with no burn, when it is drag's alone, and with a burn of 0.1 m/s (4.9 "
            "times it), and under a tenth with a burn of 1 m/s (0.074 times) or 10 m/s (0.0063 times)"
        )

    @pytest.mark.parametrize(("regime", "where", "small", "medium", "large"), [
        ("MEO", "in MEO", "0.36", "0.036", "0.0038"),
        ("HEO/Molniya", "in HEO/Molniya", "0.91", "0.089", "0.0082"),
    ])
    def test_in_meo_and_heo(self, regime: str, where: str, small: str, medium: str, large: str) -> None:
        assert monte_carlo.force_model_words(72.0, regime).endswith(
            f"{where}{_AGAINST}larger than it with no burn, when it is drag's alone, over a tenth of it with a burn of "
            f"0.1 m/s ({small} times) and under a tenth with a burn of 1 m/s ({medium} times) or 10 m/s ({large} "
            "times)"
        )

    def test_a_regime_not_measured_or_not_read_takes_the_worst_measured_for_each_burn(self) -> None:
        worst = (
            f"{_AGAINST}larger than it with no burn, when it is drag's alone, and with a burn of 0.1 m/s (4.9 times "
            "it), over a tenth of it with a burn of 1 m/s (0.14 times) and under a tenth with a burn of 10 m/s (0.016 "
            "times)"
        )
        assert monte_carlo.force_model_words(72.0, "other deep-space") == (
            f"{_BASE_72}other deep-space was not measured, so in whichever of LEO, MEO, GEO and HEO/Molniya each is "
            f"largest{worst}"
        )
        assert monte_carlo.force_model_words(72.0) == (
            f"{_BASE_72}red's regime could not be read, so in whichever of LEO, MEO, GEO and HEO/Molniya each is "
            f"largest{worst}"
        )

    def test_shares_all_on_one_side_of_the_spread_read_as_one_list(self) -> None:
        assert monte_carlo._share_words((2.0, 1.5, 1.0)) == (
            "larger than it with no burn, when it is drag's alone, and with a burn of 0.1 m/s (2 times it), 1 m/s "
            "(1.5 times it) or 10 m/s (1 times it)"
        )
        assert monte_carlo._share_words((0.05, 0.01, 0.001)).endswith(
            "drag's alone, and under a tenth with a burn of 0.1 m/s (0.05 times), 1 m/s (0.01 times) or 10 m/s "
            "(0.001 times)"
        )

    def test_a_horizon_takes_the_shortest_measured_at_or_past_it(self) -> None:
        assert "2.33 km in LEO, 1.31 km in MEO, 7.24 km at GEO and 2.8 km in HEO/Molniya by 24 h" in (
            monte_carlo.force_model_words(6.0, "LEO"))
        assert "up to 2.74 km when both objects" in monte_carlo.force_model_words(30.0, "LEO")
        assert monte_carlo.force_model_words(100.0, "GEO").endswith(
            "(0.0063 times); it was measured to 72 h only, and grows with time")

    def test_the_sampled_note_states_it_before_the_seed_for_reds_regime(self) -> None:
        series = _series(_SKEWED)
        note = decision._sampled_bases(series, 12.0, regime="GEO").closest_approach_km.note
        assert note.endswith(
            f"; {monte_carlo.integrator_error_words(12.0)}; {monte_carlo.handover_words(12.0)}; "
            f"{monte_carlo.force_model_words(12.0, 'GEO')}; {decision.seed_words(series)}",
        )
        unread = decision._sampled_bases(series, 12.0).closest_approach_km.note
        assert f"; {monte_carlo.force_model_words(12.0)}; " in unread


def test_the_module_states_where_burn_dispersion_dominates() -> None:
    """The module said the burn spread dominates force-model error at 48 h, so high-fidelity ephemeris is
    unnecessary. It now says where that holds and where it does not."""
    doc = " ".join((monte_carlo.__doc__ or "").split())
    assert "high-fidelity ephemeris is unnecessary" not in doc
    assert "It leaves out J3 and J4, the Moon, the Sun and solar radiation pressure" in doc
    assert ("they move each object up to 24 km at GEO by 72 h. Two objects of the same area-to-mass ratio move "
            "largely alike, so a close pair's separation moves under 0.1 km at GEO; when one has none and the other "
            "0.02 m^2/kg, it moves 2.4 km") in doc
    assert ("With no burn the spread is drag's alone, and they exceed it in every regime. With a burn of 0.1 m/s "
            "they can exceed it in LEO and at GEO and are over a tenth of it in MEO and HEO/Molniya; with 1 m/s, "
            "over a tenth in LEO and under a tenth elsewhere; with 10 m/s, under a tenth everywhere") in doc
    assert "not so large" not in doc.lower()


def test_the_guide_names_the_forces_left_out_among_what_it_does_not_do() -> None:
    guide = re.sub(r'"\s+"', "", _repo_only("docs/generate_guide.py").read_text(encoding="utf-8"))
    start = guide.index('"What It Does Not Do"')
    limits = guide[start:guide.index("_add_callout(", start)]
    assert ("It does not model J3 and J4, the Moon, the Sun or solar radiation pressure: they move each object up to "
            "24 km at GEO by 72 h. Two objects of the same area-to-mass ratio move largely alike, but when they "
            "differ the separation moves too, by up to 2.4 km at GEO") in limits
    assert ("they exceed the sampled spread with no burn, and can with a burn of 0.1 m/s in LEO and at GEO; they "
            "are under a tenth of it from 1 m/s outside LEO and from 10 m/s in LEO") in limits
