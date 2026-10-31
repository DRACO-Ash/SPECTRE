"""Whether a red satellite could realistically spend what a plan costs.

A plan is judged against what satellites have actually spent on station,
as JCO's NOTSOs state it (``spectre.domain.manoeuvre_evidence``):

● Seen before: within the most this satellite has spent in any 14 days.
● Possible: more than that, or no record for it, but within the most any
  satellite in the record has spent in 14 days.
● Unrealistic: more than any satellite in the record has spent.

A plan is an approach only if it brings the red satellite within
CLOSE_APPROACH_KM of the target, whatever it costs.
"""

from __future__ import annotations

from dataclasses import dataclass

from spectre.domain.manoeuvre_evidence import WINDOW_DAYS, Evidence

#: A result counts as an approach only if it comes within this distance of
#: the target. ASSUMPTION, for the analyst to confirm: 50 km is a common GEO
#: close-approach radius, and closer work is the proximity operations priced
#: on their own (V-bar and H-bar hops).
CLOSE_APPROACH_KM = 50.0

SEEN_BEFORE = "Seen before"
POSSIBLE = "Possible"
UNREALISTIC = "Unrealistic"

#: Bands in the order a ranking should prefer them.
BAND_ORDER = {SEEN_BEFORE: 0, POSSIBLE: 1, UNREALISTIC: 2}


@dataclass(frozen=True)
class Realism:
    """A plan's band and the sentence that justifies it."""

    band: str
    reason: str

    @property
    def discounted(self) -> bool:
        """True when the plan is beyond anything in the record."""
        return self.band == UNREALISTIC


def _named(evidence: Evidence, satno: str) -> str:
    record = evidence.of(satno)
    return record.name if record and record.name else satno


#: The window every figure is over, as the sentences say it.
_WINDOW = f"{WINDOW_DAYS} days"


def _m_s(value: float) -> str:
    return f"{value:,.1f} m/s"


def assess(dv_m_s: float, red_satno: str | None, red_name: str, evidence: Evidence) -> Realism:
    """The band for a plan costing *dv_m_s* flown by the red satellite *red_satno*."""
    own = evidence.of(red_satno)
    fleet = evidence.fleet
    cost = _m_s(dv_m_s)
    record = f"{_m_s(fleet.largest_window_m_s)}, by {_named(evidence, fleet.largest_window_satno)}"
    if own and own.on_station_burns and dv_m_s <= own.busiest_window_m_s:
        return Realism(SEEN_BEFORE, (
            f"{cost} is within the {_m_s(own.busiest_window_m_s)} {red_name} has spent "
            f"on station in its busiest {_WINDOW}."
        ))
    if own and own.on_station_burns:
        history = f"more than {red_name} has spent on station in any {_WINDOW} ({_m_s(own.busiest_window_m_s)})"
    else:
        history = f"for a satellite with no on-station burn in the NOTSO record ({red_name})"
    if dv_m_s <= fleet.largest_window_m_s:
        return Realism(POSSIBLE, (
            f"{cost} is {history}, but within the most any satellite in the record spent "
            f"on station in {_WINDOW} ({record})."
        ))
    return Realism(UNREALISTIC, (
        f"{cost} is more than any satellite in the NOTSO record has spent on station in "
        f"{_WINDOW} ({record})."
    ))


def realistic_budget_m_s(red_satno: str | None, evidence: Evidence) -> tuple[float, str]:
    """What a fastest-arrival plan should be allowed to spend, and why.

    The figure nine in ten satellites stay within over 14 days, or this
    satellite's own busiest 14 days when that is more. A satellite's own
    record is a floor (SJ-21 has two NOTSO burns, 1 m/s, and towed a
    satellite), so it can raise the budget but not lower it. A minimum-time
    plan always spends its whole budget, so the budget is the answer it
    gives; at the panel's maximum it measured the panel, not the satellite.
    """
    own = evidence.of(red_satno)
    typical = evidence.fleet.typical_window_m_s
    if own and own.busiest_window_m_s > typical:
        return own.busiest_window_m_s, f"its own busiest {WINDOW_DAYS} days on station"
    return typical, f"what nine in ten satellites in the NOTSO record stay within over {WINDOW_DAYS} days"
