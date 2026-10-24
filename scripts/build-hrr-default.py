#!/usr/bin/env python3
"""Build the bundled HRR bootstrap list, reproducibly.

Why this file exists
--------------------
``HRR_List.json`` is the operator's own JCO watchlist. It is gitignored and
dockerignored on purpose: it is operational data and does not belong in a
source repository or a container image. The consequence was that a freshly
deployed instance had NO watchlist at all, so the threat sweep and the asset
screen both stalled at "fetch the HRR list from the UDL panel first", and
anyone evaluating the application without UDL credentials saw nothing work.

This produces a bootstrap list that ships inside the package, so the
capability runs out of the box. It is NOT the operational product and must
never be mistaken for one:

●  the object identities are real and public: NORAD catalogue numbers and
   common names, matched to the assessments already shipped in
   ``adversary_intel.json`` so the intelligence join is exercised;
●  the ELEMENT SETS ARE SYNTHETIC. They are generated here to be physically
   consistent, not observed. Every one is tagged ``SYNTHETIC`` so the
   interface marks it, the startup log says so, and a UDL fetch replaces it.

Run:  python scripts/build-hrr-default.py
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

_OUT = Path(__file__).resolve().parent.parent / "spectre" / "data" / "hrr_default.json"

#: Epoch the synthetic element sets are generated for. Fixed, so rebuilding
#: the file produces identical output rather than a spurious diff.
_EPOCH = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

_MU_EARTH = 398600.4418       # km^3/s^2
_R_EARTH = 6378.137           # km
_SIDEREAL_DAY_S = 86164.0905


def _checksum(line: str) -> int:
    """TLE modulo-10 checksum: digits sum, minus signs count 1, rest 0."""
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def _epoch_field(when: datetime) -> str:
    """TLE epoch as YYDDD.DDDDDDDD."""
    year = when.year % 100
    start = datetime(when.year, 1, 1, tzinfo=UTC)
    day_of_year = (when - start).total_seconds() / 86400.0 + 1.0
    return f"{year:02d}{day_of_year:012.8f}"


def _mean_motion(altitude_km: float) -> float:
    """Revolutions per day for a circular orbit at *altitude_km*."""
    a = _R_EARTH + altitude_km
    period_s = 2.0 * math.pi * math.sqrt(a**3 / _MU_EARTH)
    return 86400.0 / period_s


def make_tle(
    satno: int, *, inclination_deg: float, raan_deg: float, eccentricity: float,
    arg_perigee_deg: float, mean_anomaly_deg: float, mean_motion_rev_day: float,
    rev_number: int = 1000, launch_year: int = 20, launch_number: int = 1,
) -> str:
    """A syntactically valid, physically consistent two-line element set."""
    ecc_field = f"{eccentricity:.7f}".split(".")[1]
    line1 = (
        f"1 {satno:05d}U {launch_year:02d}{launch_number:03d}A   "
        f"{_epoch_field(_EPOCH)}  .00000000  00000-0  00000-0 0  999"
    )
    line1 += str(_checksum(line1))
    line2 = (
        f"2 {satno:05d} {inclination_deg:8.4f} {raan_deg:8.4f} {ecc_field} "
        f"{arg_perigee_deg:8.4f} {mean_anomaly_deg:8.4f} "
        f"{mean_motion_rev_day:11.8f}{rev_number:5d}"
    )
    line2 += str(_checksum(line2))
    return f"{line1}\n{line2}"


_GEO_MEAN_MOTION = 86400.0 / _SIDEREAL_DAY_S   # 1.00273791 rev/day


def geo(satno: int, longitude_deg: float, inclination_deg: float = 0.05) -> str:
    """A near-geostationary element set near *longitude_deg*.

    Right ascension of the ascending node and mean anomaly are offset so that
    objects sit at different longitudes rather than stacking on top of each
    other, which is what makes a screen against them meaningful.
    """
    raan = longitude_deg % 360.0
    return make_tle(
        satno, inclination_deg=inclination_deg, raan_deg=raan,
        eccentricity=0.0002, arg_perigee_deg=270.0,
        mean_anomaly_deg=(360.0 - raan) % 360.0,
        mean_motion_rev_day=_GEO_MEAN_MOTION,
    )


def leo(satno: int, altitude_km: float, inclination_deg: float, raan_deg: float,
        mean_anomaly_deg: float) -> str:
    """A circular low Earth orbit element set."""
    return make_tle(
        satno, inclination_deg=inclination_deg, raan_deg=raan_deg,
        eccentricity=0.0008, arg_perigee_deg=90.0,
        mean_anomaly_deg=mean_anomaly_deg,
        mean_motion_rev_day=_mean_motion(altitude_km),
    )


def heo(satno: int, inclination_deg: float, raan_deg: float) -> str:
    """A Molniya-class highly elliptical element set."""
    return make_tle(
        satno, inclination_deg=inclination_deg, raan_deg=raan_deg,
        eccentricity=0.72, arg_perigee_deg=270.0, mean_anomaly_deg=0.0,
        mean_motion_rev_day=2.0055,
    )


def meo(satno: int, inclination_deg: float, raan_deg: float) -> str:
    """A navigation-altitude element set, about 20,200 km."""
    return make_tle(
        satno, inclination_deg=inclination_deg, raan_deg=raan_deg,
        eccentricity=0.001, arg_perigee_deg=90.0, mean_anomaly_deg=raan_deg,
        mean_motion_rev_day=_mean_motion(20200.0),
    )


# ── The roster ───────────────────────────────────────────────────────────────
#
# RED objects are drawn from adversary_intel.json so the intelligence join is
# exercised end to end: the screen reads each one's assessed threat level and
# operational status, which is what separates the objects worth briefing from
# the ones that merely sit in a convenient orbit.
#
# BLUE objects are real allied satellites by catalogue number and name. They
# are the assets an operator would screen.

_RED: list[tuple[str, str, str, str, int, str]] = [
    # satno,  name,              country, regime, rank, tle
    ("41838", "SJ-17",           "CHN", "GEO", 1, geo(41838, 163.0, 3.47)),
    ("49330", "SJ-21",           "CHN", "GEO", 1, geo(49330, 102.0, 0.30)),
    ("62485", "SJ-25",           "CHN", "GEO", 1, geo(62485, 101.5, 0.20)),
    ("43874", "TJS-3",           "CHN", "GEO", 1, geo(43874, 59.0, 0.50)),
    ("58204", "TJS-10",          "CHN", "GEO", 1, geo(58204, 118.0, 0.40)),
    ("50321", "SY-12 01",        "CHN", "GEO", 1, geo(50321, 93.0, 0.10)),
    ("50322", "SY-12 02",        "CHN", "GEO", 1, geo(50322, 96.0, 0.12)),
    ("40892", "TJS-1",           "CHN", "GEO", 2, geo(40892, 155.0, 2.10)),
    ("41911", "TJS-2",           "CHN", "GEO", 2, geo(41911, 107.5, 1.80)),
    ("63157", "TJS-15",          "CHN", "GEO", 2, geo(63157, 85.0, 0.30)),
    ("40258", "Luch / Olymp-K",  "RUS", "GEO", 1, geo(40258, 18.1, 0.06)),
    ("55841", "Luch / Olymp-2",  "RUS", "GEO", 1, geo(55841, 62.0, 0.08)),
    ("62188", "TJS-13",          "CHN", "HEO", 2, heo(62188, 63.4, 120.0)),
    ("64467", "Cosmos 2589",     "RUS", "HEO", 1, heo(64467, 63.4, 200.0)),
    ("65563", "Yaogan-45",       "CHN", "MEO", 2, meo(65563, 55.0, 40.0)),
    ("65590", "Cosmos 2595",     "RUS", "MEO", 2, meo(65590, 64.8, 300.0)),
    # The two Degraded objects. They matter: a degraded object in a convenient
    # orbit is exactly the case the composite verdict exists to down-rank.
    ("61769", "Kowsar",          "IRN", "LEO", 3, leo(61769, 500.0, 97.4, 120.0, 10.0)),
    ("61768", "Kowsar-1.5",      "IRN", "LEO", 3, leo(61768, 500.0, 97.4, 120.5, 14.0)),
    ("53370", "Khayyam",         "IRN", "LEO", 2, leo(53370, 500.0, 97.4, 210.0, 200.0)),
    ("59065", "Pars-1",          "IRN", "LEO", 2, leo(59065, 500.0, 97.4, 95.0, 300.0)),
]

_BLUE: list[tuple[str, str, str, str, int, str]] = [
    ("30793", "SKYNET 5A",       "GBR", "GEO", 1, geo(30793, 95.0, 0.04)),
    ("33055", "SKYNET 5B",       "GBR", "GEO", 1, geo(33055, 53.0, 0.05)),
    ("34807", "SKYNET 5C",       "GBR", "GEO", 1, geo(34807, 17.8, 0.05)),
    ("40614", "SKYNET 5D",       "GBR", "GEO", 1, geo(40614, 53.5, 0.03)),
    ("36868", "AEHF-1",          "USA", "GEO", 1, geo(36868, 165.0, 4.50)),
    ("38254", "AEHF-2",          "USA", "GEO", 1, geo(38254, 107.0, 5.20)),
    ("32258", "WGS-1",           "USA", "GEO", 2, geo(32258, 175.0, 0.06)),
    ("34713", "WGS-2",           "USA", "GEO", 2, geo(34713, 60.0, 0.05)),
    ("38070", "WGS-4",           "USA", "GEO", 2, geo(38070, 88.5, 0.04)),
    ("39222", "ATHENA-FIDUS",    "FRA", "GEO", 2, geo(39222, 38.0, 0.05)),
    ("41032", "SICRAL 2",        "ITA", "GEO", 2, geo(41032, 37.0, 0.05)),
    ("36581", "SIRIO/NATO",      "NATO", "GEO", 1, geo(36581, 50.0, 0.05)),
    ("43611", "GSAT-7A",         "IND", "GEO", 3, geo(43611, 74.0, 0.07)),
    ("25544", "ISS (ZARYA)",     "INT", "LEO", 3, leo(25544, 420.0, 51.64, 208.9, 319.6)),
    ("39634", "SENTINEL-1A",     "ESA", "LEO", 2, leo(39634, 693.0, 98.18, 45.0, 120.0)),
    ("43437", "SENTINEL-3B",     "ESA", "LEO", 3, leo(43437, 806.0, 98.62, 300.0, 60.0)),
    ("40697", "SENTINEL-2A",     "ESA", "LEO", 2, leo(40697, 786.0, 98.57, 150.0, 240.0)),
    ("37849", "NPP",             "USA", "LEO", 3, leo(37849, 824.0, 98.74, 20.0, 200.0)),
]


def _entry(satno: str, name: str, country: str, regime: str, rank: int, tle: str) -> dict:
    """One watchlist entry, with its regime DERIVED from its element set.

    The declared regime is taken from the application's own classifier rather
    than asserted here, so the label and the orbit can never disagree. The
    screen filters candidate actors on that label, so a mismatch would mean
    filtering an object on a description of an orbit it does not have.

    The classifier reserves GTO for a low perigee with its apogee at GEO, so
    a Molniya-type orbit reads HEO (audit F-016). Both are trans-belt for
    compatibility purposes.
    """
    from spectre.astro.propagator import regime_from_tle

    line1, line2 = tle.split("\n")
    computed = regime_from_tle(tle)
    if computed != regime:
        print(f"  note: {name} ({satno}) declared {regime}, classifier says "
              f"{computed}; using the classifier")
    return {
        "satNo": satno,
        "commonName": name,
        "country": country,
        "rank": rank,
        "orbitRegime": computed,
        # Element set fields. A real JCO notification does not carry these; the
        # parser treats them as optional precisely so the live path is
        # unaffected.
        "line1": line1,
        "line2": line2,
        "tleDataMode": "SYNTHETIC",
    }


def main() -> None:
    body = [_entry(*row) for row in (_BLUE + _RED)]
    notification = {
        "msgType": "JCO-HRR-SATELLITES",
        "source": "SPECTRE-BOOTSTRAP",
        "createdAt": _EPOCH.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "_comment": (
            "BOOTSTRAP DATA, NOT AN OPERATIONAL PRODUCT. Catalogue numbers and "
            "names are real and public. The element sets are SYNTHETIC: "
            "generated by scripts/build-hrr-default.py to be physically "
            "consistent at the stated epoch, not observed. Connect to UDL to "
            "replace them with tracked element sets."
        ),
        "msgBody": body,
    }
    _OUT.write_text(json.dumps([notification], indent=1) + "\n", encoding="utf-8")
    blue = sum(1 for r in body if r["country"] not in {"CHN", "RUS", "IRN", "PRK"})
    print(f"wrote {_OUT.relative_to(Path.cwd())}: {len(body)} objects "
          f"({blue} blue, {len(body) - blue} red)")


if __name__ == "__main__":
    main()
