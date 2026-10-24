"""Refutation checks for batch R1. Runs against the scratch clone; mutates nothing."""
import math
import sys
from datetime import UTC, datetime, timedelta

import numpy as np

sys.path.insert(0, "/tmp/claude-0/-home-user-SPECTRE/e332f7aa-9fda-59a8-9619-1afe89475fea/scratchpad/tree")

from spectre.astro import maneuvers as M  # noqa: E402
from spectre.astro import tactical as T  # noqa: E402
from spectre.astro.constants import MU_EARTH as MU, classify_orbit_regime  # noqa: E402
from spectre.astro.lambert import solve_lambert  # noqa: E402
from spectre.astro.propagator import (  # noqa: E402
    KeplerianElements, StateVector, keplerian_to_state, state_to_keplerian,
)

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def circ_state(a, inc, raan, u_deg, t=EPOCH):
    return keplerian_to_state(KeplerianElements(a=a, ecc=0.0, inc=inc, raan=raan, argp=0.0, ta=u_deg, epoch=t))


ORBITS = {}


class FakeSat:
    jdsatepoch = 2461041.5


class FakeOrbit:
    """Circular Keplerian stand-in for TLEOrbit, keyed by a label string."""

    def __init__(self, key):
        self.a, self.inc, self.raan, self.u0 = ORBITS[key]
        self._sat = FakeSat()

    def propagate(self, t):
        n = math.sqrt(MU / self.a**3)
        dt = (t - EPOCH).total_seconds()
        return circ_state(self.a, self.inc, self.raan, self.u0 + math.degrees(n * dt), t)


M.TLEOrbit = FakeOrbit  # monkeypatch module attribute only (in-process)


def hdr(s):
    print("\n==== " + s)


# F-S01-03 Lambert retrograde (98 deg) 10 deg hop
hdr("F-S01-03 lambert retrograde")
for inc in (51.6, 98.0):
    a = 7000.0
    s1 = circ_state(a, inc, 0.0, 0.0)
    s2 = circ_state(a, inc, 0.0, 10.0)
    n = math.sqrt(MU / a**3)
    tof = math.radians(10.0) / n * 1.05
    sol = solve_lambert(s1.r, s2.r, tof, v1_initial=s1.v, v2_target=s2.v)
    sol_r = solve_lambert(s1.r, s2.r, tof, prograde=False, v1_initial=s1.v, v2_target=s2.v)
    h_t = np.cross(s1.r, sol.v1)
    h_s = np.cross(s1.r, s1.v)
    print(f"inc={inc}: prograde=True dv1={sol.delta_v1_mag:.3f} km/s total={sol.total_delta_v:.3f}; "
          f"h_transfer.h_sat sign={np.sign(np.dot(h_t, h_s))}; prograde=False total={sol_r.total_delta_v:.4f}")

# F-S01-04 GEO 30 deg, 24 h
hdr("F-S01-04 lambert multi-rev")
a = 42164.0
s1 = circ_state(a, 0.1, 0.0, 0.0)
s2 = circ_state(a, 0.1, 0.0, 30.0)
for tof_h in (2.0, 12.0, 24.0, 48.0):
    try:
        sol = solve_lambert(s1.r, s2.r, tof_h * 3600, v1_initial=s1.v, v2_target=s2.v)
        print(f"tof={tof_h} h: returned total dv={sol.total_delta_v*1000:.1f} m/s")
    except Exception as e:  # noqa: BLE001
        print(f"tof={tof_h} h: raised {type(e).__name__}: {e}")

# F-S01-12 regime classification
hdr("F-S01-12 regimes")
for name, a, e in [("Molniya", 26562, 0.74), ("Tundra", 42164, 0.27), ("GTO", 24396, 0.73),
                   ("GEO", 42164, 0.0003), ("GPS", 26560, 0.01), ("ISS", 6780, 0.0004)]:
    print(name, classify_orbit_regime(a, e))

# F-S01-17 retrograde circular equatorial round trip
hdr("F-S01-17 inc=180 round trip")
sv = circ_state(7000.0, 180.0, 0.0, 30.0)
kep = state_to_keplerian(sv)
sv2 = keplerian_to_state(kep)
print("r in", sv.r.round(3), "r out", sv2.r.round(3), "err km", round(float(np.linalg.norm(sv.r - sv2.r)), 3))

# F-S02-05 radial amplitude vs CW sampling
hdr("F-S02-05 radial amplitude")


def cw_x(t, n, x0, xd0, yd0):
    return (4 - 3 * math.cos(n * t)) * x0 + math.sin(n * t) * xd0 / n + 2 * (1 - math.cos(n * t)) * yd0 / n


r = 7000.0
n = math.sqrt(MU / r**3)
v = 0.001
res = T.relative_motion_stability(r, 0, 0, 0, 0, v, 0)
xs = [abs(cw_x(t, n, 0, 0, v)) for t in np.linspace(0, 2 * math.pi / n, 2001)]
print(f"code A_x={res.radial_amplitude_km:.4f} km; sampled max|x|={max(xs):.4f}; 4v/n={4*v/n:.4f}")

# F-S02-04 stability wrapper on two circular co-orbiting objects, dr=1 km
hdr("F-S02-04 stability_intercept projection")
ORBITS["blue"] = (7000.0, 51.6, 10.0, 40.0)
ORBITS["red"] = (7001.0, 51.6, 10.0, 40.0)
sb = FakeOrbit("blue").propagate(EPOCH)
sr = FakeOrbit("red").propagate(EPOCH)
v_hat = sb.v / sb.v_mag
h = np.cross(sb.r, sb.v)
nh = h / np.linalg.norm(h)
bh = np.cross(v_hat, nh)
dr = sr.r - sb.r
dv = sr.v - sb.v
res = T.relative_motion_stability(sb.r_mag, *(float(np.dot(dr, e)) for e in (bh, v_hat, nh)),
                                  *(float(np.dot(dv, e)) for e in (bh, v_hat, nh)))
n_b = math.sqrt(MU / 7000.0**3)
n_r = math.sqrt(MU / 7001.0**3)
Tb = 2 * math.pi / n_b
true_drift = 7000.0 * (n_r - n_b) * Tb
print(f"code drift={res.along_track_drift_km_per_orbit:.3f} km/orbit; true two-body drift={true_drift:.3f}; "
      f"4.5pi={4.5*math.pi:.3f}; -3pi={-3*math.pi:.3f}")

# F-S02-13 opposite-sign RAAN manoeuvre
hdr("F-S02-13 raan sign")
a1 = 6780.0
rate = T.j2_raan_rate(a1, 0.0, 51.6)
print(f"J2 rate {rate:.3f} deg/day")
for man in (+2.0, -2.0):
    raan2 = 100.0 + rate + man
    c = T.classify_manoeuvre(a1, 0.0, 51.6, 100.0, a1, 0.0, 51.6, raan2, 86400.0)
    print(f"manoeuvre {man:+} deg: type={c.manoeuvre_type} dv={c.estimated_delta_v*1000:.1f} m/s notes={c.notes}")

# F-S02-14 RAAN-only plane change cost
hdr("F-S02-14 raan cost")
i = math.radians(51.6)
dO = math.radians(1.0)
th = math.acos(math.cos(i)**2 + math.sin(i)**2 * math.cos(dO))
v1 = math.sqrt(MU / a1)
c = T.classify_manoeuvre(a1, 0.0, 51.6, 100.0, a1, 0.0, 51.6, 100.0 + rate - 1.0, 86400.0)
print(f"code dv={c.estimated_delta_v*1000:.2f} m/s; closed form 2v sin(th/2)={2*v1*math.sin(th/2)*1000:.2f} m/s; ratio={c.estimated_delta_v/(2*v1*math.sin(th/2)):.3f}")

# F-S02-15 J2 plan
hdr("F-S02-15 j2 plan")
for d in (+20.0, -20.0):
    p = T.j2_drift_plan(7000.0, 0.0, 51.6, 7100.0, 0.0, 51.6, d)
    print(f"delta_raan={d}: conv={p.convergence_time_days:.1f} d, accel(da={p.accel_altitude_change_km}) conv={p.accel_convergence_days:.1f} d, accel_dv={p.accel_delta_v*1000:.2f} m/s")
h2 = M.hohmann(7000.0, 6950.0)
print(f"two-burn hohmann 7000->6950 total={h2.total_delta_v*1000:.2f} m/s")

# F-S02-16 plane change circular tie
hdr("F-S02-16 plane_change")
pc = T.plane_change(7000.0, 1.0, 0.0)
print("circular optimal_location:", pc.optimal_location)

# F-S02-23 formation radial displacement
hdr("F-S02-23 formation")
r = 7000.0
n = math.sqrt(MU / r**3)
for tt in (600.0, 1200.0, 2400.0):
    cola = T.collision_avoidance(r, 1.0, tt)
    fb = T.formation_defence_burn(r, r, tt, 1.0)
    dvx = cola.best.delta_v
    ts = np.linspace(0, 2 * math.pi / n, 4001)
    rng = max(math.hypot(dvx / n * math.sin(n * t), -2 * dvx / n * (1 - math.cos(n * t))) for t in ts)
    print(f"tca={tt}: best={cola.best.strategy} dv={dvx*1000:.2f} m/s; code displacement={fb.formation_impact_km:.3f}; true max range (radial strat)={rng:.3f}")

# F-S02-18 collision avoidance achieved miss
hdr("F-S02-18 COLA achieved miss")
cola = T.collision_avoidance(r, 1.0, 1200.0)
t = 1200.0
for s in (cola.radial, cola.along_track):
    if s.strategy == "radial":
        x = s.delta_v / n * math.sin(n * t); y = -2 * s.delta_v / n * (1 - math.cos(n * t))
    else:
        x = 2 * s.delta_v / n * (1 - math.cos(n * t)); y = s.delta_v * (4 * math.sin(n * t) - 3 * n * t) / n
    print(f"{s.strategy}: reported miss={s.miss_distance_km}, achieved |r|={math.hypot(x, y):.3f}")
print("best", cola.best.strategy)

# F-S02-27 cw_combined vs pure radial
hdr("F-S02-27 cw_combined test premise")
from spectre.astro.constants import R_EARTH  # noqa: E402
LEO_R = R_EARTH + 500.0
pure = T.cw_radial_separation(LEO_R, 5.0, 1800.0)
comb = T.cw_combined(LEO_R, 5.0, 0.0, 1800.0)
print(f"pure radial dvx={pure.delta_v_radial*1000:.3f} m/s; combined dvx={comb.delta_v_radial*1000:.3f} dvy={comb.delta_v_along_track*1000:.3f} m/s")

# Wrapper checks with fake circular orbits
hdr("F-S01-07 hohmann lowering")
ORBITS["hi"] = (8000.0, 51.6, 10.0, 0.0)
ORBITS["lo"] = (7000.0, 51.6, 10.0, 0.0)
s = M.hohmann_intercept("hi", "lo", EPOCH)
print("lowering burns dv_prograde:", [round(b.dv_prograde * 1000, 2) for b in s.burns])

hdr("F-S01-06 bielliptic signs")
s = M.bielliptic_intercept("lo", "hi", EPOCH)
print("raising burns dv_prograde:", [round(b.dv_prograde * 1000, 2) for b in s.burns],
      "| ideal signs + , + , - (v_t2_p > v2)")

hdr("F-S01-05 hohmann miss")
ORBITS["hi_phase"] = (8000.0, 51.6, 10.0, 90.0)
s = M.hohmann_intercept("lo", "hi_phase", EPOCH)
# fly Hohmann: red arrives at u = 180 deg at arrival
r_red_arr = circ_state(8000.0, 51.6, 10.0, 180.0).r
r_blue_arr = FakeOrbit("hi_phase").propagate(s.arrival_epoch).r
print(f"reported miss={s.miss_distance_km}, actual={np.linalg.norm(r_red_arr - r_blue_arr):.0f} km")

hdr("F-S01-08 hbar parity")
ORBITS["b2"] = (7000.0, 51.6, 10.0, 0.0)
ORBITS["r2"] = (7000.0, 51.7, 10.0, 0.0)
for nh_ in (3, 2):
    s = M.hbar_hop_intercept("r2", "b2", EPOCH, n_hops=nh_)
    zdot_end = s.burns[0].dv_normal * math.cos(math.pi * nh_)
    print(f"n_hops={nh_}: burn1 n={s.burns[0].dv_normal*1000:.3f} burn2 n={s.burns[1].dv_normal*1000:.3f} m/s; "
          f"residual zdot after burn2 (CW) = {(zdot_end + s.burns[1].dv_normal)*1000:.3f} m/s")

hdr("F-S01-10 combined plane change burn split")
ORBITS["red_pc"] = (7000.0, 50.0, 10.0, 0.0)
ORBITS["blue_pc"] = (8000.0, 51.0, 10.0, 0.0)
s = M.plane_change_intercept("red_pc", "blue_pc", EPOCH)
print("burn1 (pro, nor)", round(s.burns[0].dv_prograde * 1000, 2), round(s.burns[0].dv_normal * 1000, 2),
      "burn2 (pro, nor)", round(s.burns[1].dv_prograde * 1000, 2), round(s.burns[1].dv_normal * 1000, 2))

hdr("F-S01-09 evasion ignores red")
ORBITS["redA"] = (7000.0, 51.6, 10.0, 5.0)
ORBITS["redB"] = (9000.0, 98.0, 200.0, 170.0)
a_ = M.evasion_intercept("redA", "b2", EPOCH)
b_ = M.evasion_intercept("redB", "b2", EPOCH)
print("redA", a_.total_delta_v, a_.miss_distance_km, "| redB", b_.total_delta_v, b_.miss_distance_km)

hdr("F-S02-06 nmc wrapper axis")
s = M.nmc_intercept("r2", "b2", EPOCH, along_track_km=2.0)
b = s.burns[0]
print(f"burn radial={b.dv_radial*1000:.3f} prograde={b.dv_prograde*1000:.3f} m/s; total_delta_v={s.total_delta_v*1000:.3f} m/s")

hdr("F-S01-02 plane change raan only")
ORBITS["p1"] = (7000.0, 53.0, 0.0, 0.0)
ORBITS["p2"] = (7000.0, 53.0, 10.0, 0.0)
s = M.plane_change_intercept("p1", "p2", EPOCH)
print("dv", s.total_delta_v)
