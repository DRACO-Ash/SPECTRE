"""P-12: SGP4 against the published verification vectors shipped with the installed sgp4 library.

Property tested: SPECTRE's SGP4 wrapper (spectre/astro/propagator.py, TLEOrbit) reproduces the published
verification output (sgp4/tcppver.out, generated from sgp4/SGP4-VER.TLE by Vallado's C++ reference) at every listed
time, for every case it can take, near-earth (SGP4) and deep-space (SDP4) alike. Each case is also run through
sgp4.api.Satrec directly, so a wrapper difference can be told from a library difference. The gravity model the
wrapper uses is recorded, and the vectors are rerun under WGS-84 to show which model they were generated with.

Framework reference: decision-engine-evaluation-framework.md section 1g (SGP4 limits) and section 2, test programme
row "Propagator verification" (Vallado verification TLE set); evaluation probe 12; gate G7.

Expected result: every listed position within about 1e-6 km and velocity within about 1e-9 km/s of tcppver.out
through Satrec directly (the library's own test allows 2e-7 per printed field). Through the wrapper, whose only
extra step is a datetime with microsecond resolution, the difference is bounded by 1 microsecond of motion (about
1e-5 km and 1e-8 km/s; the first run's 1e-8 km/s velocity bound was tighter than this and was revised after it, the
revision recorded in SUMMARY.md), and the wrapper must equal Satrec exactly at the instant it is handed. The cases on
which the reference itself stops with an SGP4 error code (7 in the library's own test) should make the wrapper raise
RuntimeError at the same instants rather than return a state.

Measured numbers are printed and the full per-case table is written to
evaluation/evidence/physics/p12_sgp4_vectors.csv whether the assertions pass or fail.
"""

from __future__ import annotations

import csv
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import sgp4
from sgp4.api import WGS84, Satrec, jday
from sgp4.conveniences import sat_epoch_datetime

from spectre.astro.propagator import TLEOrbit

_SGP4_DIR = Path(sgp4.__file__).parent
_TLE_FILE = _SGP4_DIR / "SGP4-VER.TLE"
_OUT_FILE = _SGP4_DIR / "tcppver.out"
_EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "physics"
_CSV = _EVIDENCE / "p12_sgp4_vectors.csv"


def _cases() -> list[tuple[str, str, tuple[float, float, float]]]:
    """(line1, line2, (start, stop, step) in minutes) in file order, read as the library's own generator reads them."""
    lines = iter(_TLE_FILE.read_text(encoding="ascii").splitlines())
    cases = []
    for line1 in lines:
        if not line1.startswith("1"):
            continue
        line2 = next(lines)
        start, stop, step = (float(f) for f in line2[69:].split())
        cases.append((line1.rstrip(), line2[:69], (start, stop, step)))
    return cases


def _reference_blocks() -> list[tuple[int, list[tuple[float, np.ndarray, np.ndarray]]]]:
    """Each 'satnum xx' block of tcppver.out with its rows (tsince minutes, r km, v km/s), in file order."""
    blocks: list[tuple[int, list[tuple[float, np.ndarray, np.ndarray]]]] = []
    for raw in _OUT_FILE.read_text(encoding="ascii").replace("\r", "").splitlines():
        if raw.strip().endswith("xx"):
            blocks.append((int(raw.split()[0]), []))
            continue
        fields = raw.split()
        if len(fields) < 7:  # noqa: PLR2004
            continue
        t, *rv = (float(f) for f in fields[:7])
        blocks[-1][1].append((t, np.array(rv[:3]), np.array(rv[3:])))
    return blocks


def _direct(sat: Satrec, tsince: float) -> tuple[int, np.ndarray, np.ndarray]:
    """Satrec.sgp4 at *tsince* minutes after epoch, split into whole and fractional days as the library's test does."""
    whole, fraction = divmod(tsince / 1440.0, 1.0)
    e, r, v = sat.sgp4(sat.jdsatepoch + whole, sat.jdsatepochF + fraction)
    return e, np.array(r), np.array(v)


def _grid(start: float, stop: float, step: float) -> list[float]:
    """Every time the library's generator asks for, the stop included."""
    times, t = [], start
    while t <= stop:
        times.append(t)
        t += step
    if t - stop < step - 1e-6:
        times.append(stop)
    return times


def _row(index: int, case: tuple[str, str, tuple[float, float, float]], block: tuple[int, list]) -> dict[str, object]:
    line1, line2, (start, stop, step) = case
    satnum, rows = block
    sat = Satrec.twoline2rv(line1, line2)
    sat84 = Satrec.twoline2rv(line1, line2, WGS84)
    out: dict[str, object] = {
        "case": index, "satnum": satnum, "method": "SDP4 (deep space)" if sat.method == "d" else "SGP4 (near earth)",
        "period_min": round(2.0 * math.pi / sat.no_kozai, 2), "listed_times": len(rows),
        "grid_times": len(_grid(start, stop, step)),
    }
    # A block whose epoch propagation is NaN repeats the previous case's data line (the library's test notes this),
    # so it holds no reference for this case.
    e0, r0, _ = _direct(sat, 0.0)
    if any(math.isnan(x) for x in r0):
        out.update(compared_direct=0, compared_wrapper=0, note=f"library error {e0} at epoch: no reference vectors")
    else:
        out.update(_compare(sat, sat84, line1, line2, rows))
    out.update(_wrapper_errors(line1, line2, sat, (start, stop, step)))
    return out


def _compare(sat: Satrec, sat84: Satrec, line1: str, line2: str, rows: list) -> dict[str, object]:
    epoch = sat_epoch_datetime(sat)
    dr_d = dv_d = dr_w = dv_w = dr_84 = same_instant = quant_s = 0.0
    n_d = n_w = 0
    wrapper_refused = ""
    try:
        orbit: TLEOrbit | None = TLEOrbit(f"{line1}\n{line2}")
    except (ValueError, RuntimeError, ArithmeticError) as exc:
        orbit, wrapper_refused = None, f"TLEOrbit refused: {exc!r}"
    for t, r_ref, v_ref in rows:
        e, r, v = _direct(sat, t)
        if e == 0:
            dr_d, dv_d = max(dr_d, float(np.max(np.abs(r - r_ref)))), max(dv_d, float(np.max(np.abs(v - v_ref))))
            n_d += 1
        e84, r84, _ = _direct(sat84, t)
        if e84 == 0:
            dr_84 = max(dr_84, float(np.linalg.norm(r84 - r_ref)))
        if orbit is not None:
            try:
                sv = orbit.propagate(epoch + timedelta(minutes=t))
            except RuntimeError as exc:
                wrapper_refused = wrapper_refused or f"t={t} min: {exc}"
                continue
            dr_w = max(dr_w, float(np.linalg.norm(sv.r - r_ref)))
            dv_w = max(dv_w, float(np.linalg.norm(sv.v - v_ref)))
            n_w += 1
            when = sv.epoch
            jd_w, fr_w = jday(when.year, when.month, when.day, when.hour, when.minute,
                              when.second + when.microsecond / 1e6)
            _, r_same, v_same = sat.sgp4(jd_w, fr_w)
            same_instant = max(same_instant, float(np.linalg.norm(sv.r - np.array(r_same))),
                               float(np.linalg.norm(sv.v - np.array(v_same))))
            offset_days = (jd_w - sat.jdsatepoch) + (fr_w - sat.jdsatepochF) - t / 1440.0
            quant_s = max(quant_s, abs(offset_days) * 86400.0)
    return {
        "compared_direct": n_d, "max_abs_dr_direct_km": dr_d, "max_abs_dv_direct_km_s": dv_d,
        "compared_wrapper": n_w, "max_dr_wrapper_km": dr_w, "max_dv_wrapper_km_s": dv_w,
        "max_dr_if_wgs84_km": dr_84, "wrapper_vs_satrec_same_instant": same_instant,
        "datetime_offset_from_listed_s_max": quant_s, "wrapper_refused_listed": wrapper_refused, "note": "",
    }


def _wrapper_errors(line1: str, line2: str, sat: Satrec, span: tuple[float, float, float]) -> dict[str, object]:
    """Where, over the generator's full time grid, the library returns an error code and the wrapper raises."""
    epoch = sat_epoch_datetime(sat)
    try:
        orbit = TLEOrbit(f"{line1}\n{line2}")
    except (ValueError, RuntimeError, ArithmeticError) as exc:
        return {"library_first_error": "", "wrapper_first_error": f"construct: {exc!r}"}
    lib = wrap = ""
    for t in _grid(*span):
        e, _, _ = _direct(sat, t)
        if e != 0 and not lib:
            lib = f"code {e} at t={t} min"
        if not wrap:
            try:
                orbit.propagate(epoch + timedelta(minutes=t))
            except RuntimeError as exc:
                wrap = f"{exc} (t={t} min)"
        if lib and wrap:
            break
    return {"library_first_error": lib, "wrapper_first_error": wrap}


def test_p12_sgp4_against_published_vectors() -> None:
    cases, blocks = _cases(), _reference_blocks()
    assert len(cases) == len(blocks), (len(cases), len(blocks))
    rows = [_row(i, c, b) for i, (c, b) in enumerate(zip(cases, blocks, strict=True), start=1)]
    for (line1, _, _), (satnum, _) in zip(cases, blocks, strict=True):
        assert int(line1[2:7]) == satnum
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with _CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    gravity = Satrec.twoline2rv(cases[0][0], cases[0][1])
    wrapper_sat = TLEOrbit(f"{cases[0][0]}\n{cases[0][1]}")._sat  # noqa: SLF001  read only, to record the model
    print(f"\nP-12 sgp4 {sgp4.__version__}; files {_TLE_FILE.name}, {_OUT_FILE.name}; {len(rows)} cases")
    print(f"P-12 wrapper gravity: radiusearthkm {wrapper_sat.radiusearthkm}, mu {wrapper_sat.mu}, j2 {wrapper_sat.j2}"
          f" (library default {gravity.radiusearthkm}, {gravity.mu}: WGS-72); opsmode {wrapper_sat.operationmode}")
    header = ("case", "satnum", "method", "listed", "cmp_w", "max_dr_direct_km", "max_dr_wrapper_km",
              "max_dv_wrapper_km_s", "max_dr_wgs84_km", "library_first_error", "wrapper_first_error", "note")
    print("P-12 " + " | ".join(header))
    for r in rows:
        print("P-12 " + " | ".join(str(x) for x in (
            r["case"], r["satnum"], r["method"], r["listed_times"], r.get("compared_wrapper"),
            f"{r.get('max_abs_dr_direct_km', float('nan')):.2e}", f"{r.get('max_dr_wrapper_km', float('nan')):.2e}",
            f"{r.get('max_dv_wrapper_km_s', float('nan')):.2e}", f"{r.get('max_dr_if_wgs84_km', float('nan')):.3f}",
            r["library_first_error"], r["wrapper_first_error"], r.get("note", ""),
        )))
    compared = [r for r in rows if r.get("compared_wrapper")]
    worst_dr = max(compared, key=lambda r: r["max_dr_wrapper_km"])
    worst_dv = max(compared, key=lambda r: r["max_dv_wrapper_km_s"])
    deep = [r for r in rows if str(r["method"]).startswith("SDP4")]
    print(f"P-12 overall wrapper max |dr| {worst_dr['max_dr_wrapper_km']:.3e} km (case {worst_dr['case']}, "
          f"{worst_dr['satnum']}); max |dv| {worst_dv['max_dv_wrapper_km_s']:.3e} km/s (case {worst_dv['case']}, "
          f"{worst_dv['satnum']})")
    print(f"P-12 overall direct max per-component |dr| "
          f"{max(r['max_abs_dr_direct_km'] for r in compared):.3e} km, |dv| "
          f"{max(r['max_abs_dv_direct_km_s'] for r in compared):.3e} km/s")
    print(f"P-12 vectors compared: wrapper {sum(r['compared_wrapper'] for r in compared)}, direct "
          f"{sum(r['compared_direct'] for r in compared)}; deep-space cases {len(deep)} of {len(rows)}; "
          f"cases with a library error code {sum(bool(r['library_first_error']) for r in rows)}; "
          f"cases where the wrapper raised {sum(bool(r['wrapper_first_error']) for r in rows)}; "
          f"min WGS-84 offset where compared {min(r['max_dr_if_wgs84_km'] for r in compared):.3f} km")
    print(f"P-12 wrapper against Satrec at the identical instant: max difference "
          f"{max(r['wrapper_vs_satrec_same_instant'] for r in compared):.3e} (km and km/s)")
    print(f"P-12 largest offset of the datetime instant from the listed time, after microsecond rounding: "
          f"{max(r['datetime_offset_from_listed_s_max'] for r in compared):.2e} s")
    print(f"P-12 table written to {_CSV}")

    assert max(r["wrapper_vs_satrec_same_instant"] for r in compared) == 0.0, "the wrapper alters SGP4's output"
    assert worst_dr["max_dr_wrapper_km"] < 2e-5, "wrapper position differs from the published vectors"
    assert worst_dv["max_dv_wrapper_km_s"] < 5e-8, "wrapper velocity differs from the published vectors"
    for r in rows:
        assert bool(r["library_first_error"]) == bool(r["wrapper_first_error"]), r
