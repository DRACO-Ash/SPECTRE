"""GEO longitude drift is the drift SGP4 actually flies.

Audit F-093. The drift came from the Kozai mean motion alone, which is close
to the rate of mean anomaly only, and left out the secular node and perigee
rates (J2 alone adds about 0.0134 deg/day at GEO) and the deep-space terms
SGP4 applies there. The bundled bootstrap GEO sets, generated at exactly the
sidereal mean motion, read 0.00004 deg/day while SGP4 moves them about
0.0107 deg/day east.

The reference here is the Earth-fixed longitude change over one sidereal day
of SGP4 propagation from the epoch, taken through the propagator's public
API. One sidereal day cancels the daily swing an eccentric orbit adds.
"""

from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

import pytest

from spectre.astro.constants import SIDEREAL_DAY
from spectre.astro.pattern_of_life import _gmst_deg, _satrec_to_record
from spectre.astro.propagator import TLEOrbit

_BOOTSTRAP = Path(__file__).resolve().parents[2] / "spectre" / "data" / "hrr_default.json"


def _geo_tles() -> list[str]:
    body = json.loads(_BOOTSTRAP.read_text(encoding="utf-8"))[0]["msgBody"]
    return [f"{e['line1']}\n{e['line2']}" for e in body if e["orbitRegime"] == "GEO"][:4]


def _flown_drift(tle: str) -> float:
    orbit = TLEOrbit(tle)
    epoch = _satrec_to_record(tle).epoch

    def lon(t: timedelta) -> float:
        sv = orbit.propagate(epoch + t)
        return math.degrees(math.atan2(sv.r[1], sv.r[0])) - _gmst_deg(epoch + t)

    change = (lon(timedelta(seconds=SIDEREAL_DAY)) - lon(timedelta(0)) + 180.0) % 360.0 - 180.0
    return change / (SIDEREAL_DAY / 86400.0)


@pytest.mark.parametrize("tle", _geo_tles())
def test_the_drift_is_the_longitude_rate_sgp4_flies(tle: str) -> None:
    assert _satrec_to_record(tle).geo_drift_rate_deg_day == pytest.approx(_flown_drift(tle), abs=1e-6)


def test_the_bootstrap_sets_drift_east_as_flown() -> None:
    rate = _satrec_to_record(_geo_tles()[0]).geo_drift_rate_deg_day
    assert rate == pytest.approx(0.0107, abs=0.0005)
