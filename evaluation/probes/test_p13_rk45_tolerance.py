"""P-13: the production RK45 settings against the same equations at tightened tolerances.

Property tested: the Monte Carlo propagator's integration error. The production settings are RK45 at rtol 1e-8 and
atol 1e-10 (spectre/astro/monte_carlo.py:516-517, RK45_RTOL and RK45_ATOL), on the two-body, J2 and exponential-drag
equations _j2_drag_ode (monte_carlo.py:357-395). The same equations are integrated with DOP853 at rtol 1e-12 and
atol 1e-14 as the reference, and the reference is checked against DOP853 at rtol 1e-13 and atol 1e-15 to show it has
converged. Both production paths are measured: _integrate (end-point, used by run_monte_carlo, monte_carlo.py:581-596)
and rk45_arc (dense output with the re-entry event, used by every separation series, monte_carlo.py:1235-1240 and
1349-1371). Two states: a LEO at about 500 km, where drag acts, and a GEO, each from the hand-checked reference element
sets in tests/unit/_decision_reference.py, to 48 h and to 72 h (the default horizon, decision.py:1463).

Framework reference: decision-engine-evaluation-framework.md section 1g ("integrator tolerances ... and their effect
against a reference propagator") and section 2, test programme row "Propagator verification" (RK45 against a
high-order reference integrator at tight tolerance); evaluation probe 13; gate G7; finding F-19.

Expected result: an integration error at 72 h well below the element-set error the code's own model assumes at those
ages (spectre/astro/along_track.py:28-36: 1 km plus 2 km a day in LEO, 2 km plus 1 km a day at GEO), say below 0.1 km.
Because a miss distance is a difference of two integrated orbits, the error in the separation is also measured for
three LEO pairs integrated with the same settings: coplanar_leo (10 km apart in one plane), plane_change (crossing
planes at one altitude) and a dissimilar pair (500 km at 51.6 degrees against 800 km at 98 degrees, built with the
reference module's own element_set). Added after the first run showed the absolute LEO error above 0.1 km, so the
decision-relevant quantity is reported beside it.
The integrator error says nothing about force-model error (no third bodies, no solar radiation pressure, no higher
geopotential); for context only, the production RK45 is also set against SGP4 from the same start, which is a
different model, not truth.

Measured numbers are printed and written to evaluation/evidence/physics/p13_rk45_tolerance.csv whether the
assertions pass or fail.
"""

from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

from spectre.astro import monte_carlo as mc
from spectre.astro.along_track import position_error_km
from spectre.astro.monte_carlo import elset_state
from spectre.astro.propagator import TLEOrbit, regime_from_tle
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE, RE_KM, Circular, element_set

_EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "physics"
_CSV = _EVIDENCE / "p13_rk45_tolerance.csv"
_HORIZONS_H = (48.0, 72.0)
#: B* for the integration comparison: the hypothesis default (monte_carlo.py:251), so drag acts in LEO. The
#: reference element sets carry B* 0, which the code floors to almost no drag.
_BSTAR = 1.0e-4


def _reference(state: np.ndarray, span_s: float, bc: float, rtol: float, atol: float) -> object:
    sol = solve_ivp(mc._j2_drag_ode, (0.0, span_s), state, method="DOP853", rtol=rtol, atol=atol,  # noqa: SLF001
                    args=(bc,), dense_output=True)
    assert sol.success, sol.message
    return sol


def _case(label: str, tle: str) -> list[dict[str, object]]:
    start = elset_state(tle, EPOCH)
    assert start is not None
    state = start.state_eci_km
    bc = mc._ballistic_coefficient_kg_m2(_BSTAR)  # noqa: SLF001
    span = max(_HORIZONS_H) * 3600.0
    ref = _reference(state, span, bc, 1e-12, 1e-14)
    tighter = _reference(state, span, bc, 1e-13, 1e-15)
    arc = mc.rk45_arc(state, span, _BSTAR)
    assert arc is not None
    regime = regime_from_tle(tle)
    orbit = TLEOrbit(tle)
    grid = np.arange(0.0, span + 1.0, 60.0)
    rows = []
    for h in _HORIZONS_H:
        t = h * 3600.0
        end = mc._integrate(state, t, _BSTAR)  # noqa: SLF001
        assert end is not None
        r_ref = ref.sol(t)
        sel = grid[grid <= t]
        dense_max = max(float(np.linalg.norm(arc(x)[:3] - ref.sol(x)[:3])) for x in sel)
        sgp4_gap = float(np.linalg.norm(arc(t)[:3] - orbit.propagate(EPOCH + timedelta(seconds=t)).r))
        rows.append({
            "case": label, "regime": regime, "altitude_km": round(float(np.linalg.norm(state[:3])) - mc._R_E, 1),  # noqa: SLF001
            "bstar": _BSTAR, "ballistic_kg_m2": round(bc, 1), "horizon_h": h,
            "endpoint_rk45_vs_ref_km": float(np.linalg.norm(end[:3] - r_ref[:3])),
            "endpoint_rk45_vs_ref_vel_m_s": 1e3 * float(np.linalg.norm(end[3:] - r_ref[3:])),
            "dense_rk45_at_horizon_vs_ref_km": float(np.linalg.norm(arc(t)[:3] - r_ref[:3])),
            "dense_rk45_max_over_arc_km": dense_max,
            "ref_self_check_km": float(np.linalg.norm(tighter.sol(t)[:3] - r_ref[:3])),
            "elset_model_error_km_at_age": position_error_km(h / 24.0, regime),
            "context_rk45_vs_sgp4_km": sgp4_gap,
        })
    return rows


_DISSIMILAR_RED = element_set(Circular(90003, RE_KM + 800.0, 98.0, 40.0, 0.0))


def _pair(label: str, red_tle: str, blue_tle: str) -> dict[str, object]:
    """The production and reference separation of two orbits over 72 h on a 60 s grid, same B* and settings."""
    span = max(_HORIZONS_H) * 3600.0
    bc = mc._ballistic_coefficient_kg_m2(_BSTAR)  # noqa: SLF001
    arcs = {}
    for side, tle in (("red", red_tle), ("blue", blue_tle)):
        start = elset_state(tle, EPOCH)
        assert start is not None
        arcs[side] = (mc.rk45_arc(start.state_eci_km, span, _BSTAR),
                      _reference(start.state_eci_km, span, bc, 1e-12, 1e-14).sol)
    grid = np.arange(0.0, span + 1.0, 60.0)
    prod = np.array([np.linalg.norm(arcs["red"][0](t)[:3] - arcs["blue"][0](t)[:3]) for t in grid])
    ref = np.array([np.linalg.norm(arcs["red"][1](t)[:3] - arcs["blue"][1](t)[:3]) for t in grid])
    out: dict[str, object] = {"pair": label}
    for h in _HORIZONS_H:
        sel = grid <= h * 3600.0
        out[f"max_sep_error_km_{h:g}h"] = float(np.max(np.abs(prod[sel] - ref[sel])))
        out[f"min_sep_ref_km_{h:g}h"] = float(np.min(ref[sel]))
        out[f"min_sep_error_km_{h:g}h"] = float(abs(np.min(prod[sel]) - np.min(ref[sel])))
    return out


def test_p13_production_rk45_against_tight_dop853() -> None:
    rows = _case("LEO coplanar_leo blue (about 500 km)", COPLANAR_LEO.blue_tle)
    rows += _case("GEO geo_drift_in blue", GEO_DRIFT_IN.blue_tle)
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    with _CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nP-13 production RK45 rtol {mc.RK45_RTOL} atol {mc.RK45_ATOL}; reference DOP853 rtol 1e-12 atol 1e-14; "
          f"self-check DOP853 rtol 1e-13 atol 1e-15")
    for r in rows:
        print(
            f"P-13 {r['case']} ({r['regime']}, {r['altitude_km']} km, B* {r['bstar']}, m/CdA {r['ballistic_kg_m2']}) "
            f"{r['horizon_h']:g} h: end-point RK45 vs ref {r['endpoint_rk45_vs_ref_km']:.3e} km "
            f"({r['endpoint_rk45_vs_ref_vel_m_s']:.3e} m/s); dense RK45 at horizon {r['dense_rk45_at_horizon_vs_ref_km']:.3e} "
            f"km, max over arc {r['dense_rk45_max_over_arc_km']:.3e} km; reference self-check {r['ref_self_check_km']:.1e} km; "
            f"element-set model error at this age {r['elset_model_error_km_at_age']:.1f} km; "
            f"context, RK45 vs SGP4 from same start {r['context_rk45_vs_sgp4_km']:.2f} km"
        )
    print(f"P-13 table written to {_CSV}")
    pairs = [
        _pair("coplanar_leo (10 km apart, one plane)", COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle),
        _pair("plane_change (crossing planes, one altitude)", PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle),
        _pair("dissimilar (800 km at 98 deg against 500 km at 51.6 deg)", _DISSIMILAR_RED, COPLANAR_LEO.blue_tle),
    ]
    with (_EVIDENCE / "p13_rk45_separation.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    for p in pairs:
        print("P-13 separation " + "; ".join(f"{k} {v:.3e}" if isinstance(v, float) else f"{v}" for k, v in p.items()))
    problems = []
    for r in rows:
        tag = f"{r['case']} {r['horizon_h']:g} h"
        if r["ref_self_check_km"] >= 1e-3:
            problems.append(f"{tag}: reference not converged")
        if r["dense_rk45_max_over_arc_km"] >= 0.1:
            problems.append(f"{tag}: absolute RK45 error {r['dense_rk45_max_over_arc_km']:.3f} km >= 0.1 km")
        if r["dense_rk45_max_over_arc_km"] >= 0.1 * float(r["elset_model_error_km_at_age"]):
            problems.append(f"{tag}: absolute RK45 error >= 10 % of the element-set model error")
    for p in pairs:
        if p["max_sep_error_km_72h"] >= 0.1:
            problems.append(f"{p['pair']}: separation error {p['max_sep_error_km_72h']:.3f} km >= 0.1 km at 72 h")
    print("P-13 expectation violations: " + ("; ".join(problems) if problems else "none"))
    assert not problems, problems
