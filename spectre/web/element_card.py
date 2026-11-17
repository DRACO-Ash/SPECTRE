"""The element card behind each Blue asset and Red track in the Assets panel.

Training audit 2026-11-16, finding 2-1 (and cross-cutting finding X5).

The panel listed names only, so an element a training step asked for (RAAN, for one) could be read nowhere in the
console. Each card reads the object's own element set: its epoch and age, the data mode it was taken in, the mean
elements as the set carries them, the period and apsis altitudes from them, the regime, and for a near-geostationary
object the sub-satellite longitude at the session's scenario time, or now when none is set.

The mean elements are the set's own (Kozai mean motion, the angles as line 2 holds them), read through the same
parser the pattern-of-life analysis uses, so a figure here is the figure the set states and not an osculating value
SGP4 would give at some other moment. The longitude is SGP4's position at that moment against Greenwich Mean
Sidereal Time, by the GMST the pattern-of-life analysis uses.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from spectre.astro.constants import R_EARTH
from spectre.astro.pattern_of_life import _gmst_deg as gmst_deg
from spectre.astro.pattern_of_life import _satrec_to_record as tle_record
from spectre.astro.propagator import TLE_ERRORS, TLEOrbit
from spectre.web.deps import get_templates
from spectre.web.elsets import ElsetAge, elset_age
from spectre.web.planning_state import SessionState

#: The two list partials and the elements each is swapped into on the console.
BLUE_LIST_TEMPLATE = "partials/blue_list.html"
RED_LIST_TEMPLATE = "partials/red_list.html"
_LIST_TARGETS = (("blue-list", BLUE_LIST_TEMPLATE), ("red-list", RED_LIST_TEMPLATE))

#: The header that tells the page the session's Blue assets changed, so the Asset Screening selector, which lists them
#: after the HRR objects, reloads (training audit 2026-11-16, finding 2-3). Sent only on a real change.
BLUE_CHANGED = {"HX-Trigger": "blueAssetsChanged"}

#: The epoch as the card prints it, to the second, in UTC.
_EPOCH_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


class _HeldObject(Protocol):
    """A Blue asset or Red track: what the card reads from either."""

    name: str
    tle: str
    data_mode: str


@dataclass(frozen=True)
class ElementCard:
    """One object's element set, read for the Assets panel. Angles in degrees, distances in km."""

    epoch_text: str
    #: The set's age at *at*; None only when its epoch cannot be read, and then no card is made.
    age: ElsetAge | None
    #: The moment the age and the longitude are taken at, and whether that is the session's scenario time.
    at_text: str
    at_is_scenario: bool
    data_mode: str
    a_km: float
    ecc: float
    inc_deg: float
    raan_deg: float
    argp_deg: float
    mean_anomaly_deg: float
    period_min: float
    perigee_alt_km: float
    apogee_alt_km: float
    regime: str
    #: Whether the object is near geostationary by the pattern-of-life analysis's own test (regime GEO or DEEP, or
    #: inclination under 15 degrees and mean altitude over 30,000 km), so one longitude describes where it sits.
    near_geo: bool = False
    #: "75.32° E" for a near-geostationary object; empty for any other.
    longitude_text: str = ""
    #: Why a near-geostationary object has no longitude: SGP4 could not reach *at* from this set.
    longitude_note: str = ""


def longitude_text(lon_deg: float) -> str:
    """A longitude in degrees to two decimals and a hemisphere: 75.32° E, 0.50° W; 0.00° E for the meridian, and
    180.00° with none for the antimeridian, which is both."""
    wrapped = (lon_deg + 180.0) % 360.0 - 180.0
    figure = f"{abs(wrapped):.2f}"
    if figure == "180.00":
        return "180.00°"
    # Compared after rounding, so a longitude a hair west of Greenwich prints 0.00° E, not 0.00° W.
    hemisphere = "W" if round(wrapped, 2) < 0.0 else "E"
    return f"{figure}° {hemisphere}"


def sub_satellite_longitude_deg(tle: str, at: datetime) -> float:
    """The longitude under the object at *at*, degrees east in [-180, 180): SGP4's TEME position against GMST.

    Raises what TLE_ERRORS names when SGP4 cannot reach *at* from this set.
    """
    sv = TLEOrbit(tle).propagate(at)
    lon = math.degrees(math.atan2(float(sv.r[1]), float(sv.r[0]))) - gmst_deg(at)
    return (lon + 180.0) % 360.0 - 180.0


def element_card(obj: _HeldObject, at: datetime, *, at_is_scenario: bool) -> ElementCard | None:
    """The card for *obj* at *at*, or None when its element set does not parse."""
    try:
        if TLEOrbit(obj.tle).init_error:
            return None
        rec = tle_record(obj.tle)
    except TLE_ERRORS:
        return None
    # The parser sets a GEO longitude exactly when its near-geostationary test passes; that test is reused here.
    near_geo = rec.geo_longitude_deg is not None
    longitude, note = "", ""
    if near_geo:
        try:
            longitude = longitude_text(sub_satellite_longitude_deg(obj.tle, at))
        except TLE_ERRORS:
            note = "SGP4 could not propagate this set"
    return ElementCard(
        epoch_text=rec.epoch.astimezone(UTC).strftime(_EPOCH_FORMAT),
        age=elset_age(obj.tle, at),
        at_text=at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        at_is_scenario=at_is_scenario,
        data_mode=obj.data_mode,
        a_km=rec.sma_km,
        ecc=rec.ecc,
        inc_deg=rec.inc_deg,
        raan_deg=rec.raan_deg,
        argp_deg=rec.argp_deg,
        mean_anomaly_deg=rec.mean_anomaly_deg,
        period_min=rec.period_min,
        perigee_alt_km=rec.sma_km * (1.0 - rec.ecc) - R_EARTH,
        apogee_alt_km=rec.sma_km * (1.0 + rec.ecc) - R_EARTH,
        regime=rec.regime,
        near_geo=near_geo,
        longitude_text=longitude,
        longitude_note=note,
    )


def cards_for(objects: Iterable[_HeldObject], at: datetime, *, at_is_scenario: bool) -> dict[str, ElementCard | None]:
    """Each object's card by its name; None for one whose element set does not parse."""
    return {obj.name: element_card(obj, at, at_is_scenario=at_is_scenario) for obj in objects}


def element_cards(state: SessionState, now: datetime | None = None) -> dict[str, dict[str, ElementCard | None]]:
    """The template context for both lists: ``blue_cards`` and ``red_cards``, each by object name.

    Taken at the session's scenario start when one is set, else at *now* (the clock when not given).
    """
    at_is_scenario = state.scenario_start is not None
    at = state.scenario_start if state.scenario_start is not None else (now or datetime.now(tz=UTC))
    return {
        "blue_cards": cards_for(state.blue_assets, at, at_is_scenario=at_is_scenario),
        "red_cards": cards_for(state.red_tracks, at, at_is_scenario=at_is_scenario),
    }


def lists_out_of_band(state: SessionState) -> str:
    """Both asset lists as out-of-band swaps, so each card follows a new scenario time or a refreshed element set."""
    tmpl = get_templates()
    context = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks, "error": None, **element_cards(state)}
    return "".join(
        f'<div id="{target}" hx-swap-oob="innerHTML">{tmpl.get_template(template).render(context)}</div>'
        for target, template in _LIST_TARGETS
    )
