"""Training scenarios can be passed, and say true things about orbits.

Audit F-052: planner_05 asked for 300 points from objectives worth 260, so it
could not be passed honestly, and five optimal scores exceeded what their
objectives could award.

Audit F-053: cadet_01 taught that a GEO satellite's RAAN is its longitude.
RAAN is an inertial angle; the sub-satellite longitude for a near-circular,
near-equatorial orbit is RAAN + argument of perigee + mean anomaly - GMST,
which for BLUE-01 is about 231.5 deg East (128.5 deg West), not 45. It also
called a north-south burn longitude keeping; north-south control holds
inclination, east-west control holds longitude.

Longitudes here come from SGP4 and the sgp4 library's own GMST, not from the
application's code.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

import pytest
from sgp4.api import Satrec, jday
from sgp4.propagation import gstime

from spectre.training.scenarios import load_scenarios

_SCENARIOS = load_scenarios()


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.id)
def test_the_scores_add_up(scenario: object) -> None:
    total = sum(o.points for o in scenario.objectives)  # type: ignore[attr-defined]
    assert scenario.scoring.optimal_score == total  # type: ignore[attr-defined]
    assert scenario.scoring.passing_score <= total  # type: ignore[attr-defined]


def _east_longitude(line1: str, line2: str, epoch: datetime) -> float:
    sat = Satrec.twoline2rv(line1, line2)
    jd, fr = jday(epoch.year, epoch.month, epoch.day, epoch.hour, epoch.minute, epoch.second)
    _err, r, _v = sat.sgp4(jd, fr)
    return (math.degrees(math.atan2(r[1], r[0]) - gstime(jd + fr))) % 360.0


def _signed_east(text: str) -> float | None:
    m = re.search(r"slot at (\d+(?:\.\d+)?)\s*°\s*(East|West)", text)
    if not m:
        return None
    value = float(m.group(1))
    return value if m.group(2) == "East" else 360.0 - value


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.id)
def test_a_stated_slot_longitude_is_where_the_satellite_is(scenario: object) -> None:
    stated = _signed_east(scenario.briefing)  # type: ignore[attr-defined]
    if stated is None:
        pytest.skip("no slot longitude stated")
    blue = next(o for o in scenario.objects if o.side == "blue")  # type: ignore[attr-defined]
    epoch = datetime.fromisoformat(scenario.scenario_epoch_utc.replace("Z", "+00:00"))  # type: ignore[attr-defined]
    line1, line2 = blue.tle.splitlines()[-2:]
    actual = _east_longitude(line1, line2, epoch)
    assert abs((actual - stated + 180.0) % 360.0 - 180.0) < 0.5, f"stated {stated}, at {actual:.2f} East"


def test_no_scenario_equates_raan_with_longitude() -> None:
    for scenario in _SCENARIOS:
        text = " ".join([scenario.description, scenario.briefing, scenario.tool_workflow or ""]
                        + [o.description for o in scenario.objectives]).lower()
        assert not re.search(r"raan[^.]*equals[^.]*longitude", text), scenario.id
        assert not re.search(r"longitude[^.]*\(raan", text), scenario.id
        assert "north-south station-keeping burn to maintain its assigned longitude" not in text, scenario.id
