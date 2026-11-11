"""Decision Engine: the operating envelope, checked at evaluation entry (SPC-200, evaluation F-09, with F-30).

docs/decision-engine-envelope.md states the regimes, element-set ages, horizons, scenario sizes, turns and inputs the
engine is fit for, and where each is enforced. Most of it is enforced where the input is read and refused there in a
sentence. What is read here is what a bound element set itself says, flagged on the result in a sentence of its own:

● An object on SGP4's deep-space branch, SDP4: a period of about 225 minutes or more, as the library itself decides
  (propagator.TLEOrbit.deep_space). Flagged, not refused: SDP4 is a sound propagator, but the staleness limit and the
  element-set error model the engine applies to the set are rules of thumb. For a GEO set they are the GEO ones,
  tuned rather than sourced; for any other orbit on SDP4 they were set for LEO and GEO and are not validated for it
  (evaluation F-29). No new limit is invented here; SPC-215 will source them.
● An object below the re-entry floor at an instant searched (F-30). The SGP4 search refuses it
  (elset_approach.elset_closest_approach), every computed cell says so, and the result says it here once.

Pure: no I/O. Imports nothing from the engine at run time, so the engine can import it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spectre.astro.propagator import DEEP_SPACE_PERIOD_MIN, TLE_ERRORS, TLEOrbit, regime_from_tle

if TYPE_CHECKING:
    from spectre.domain.decision import BoundElset, Scenario

#: An element set SGP4 propagates with SDP4 that is not a GEO set (HEO, Molniya-class, GTO, MEO over the switch, or
#: beyond GEO), flagged and not refused. The library chooses SDP4 from the un-Kozai'd mean motion; the period shown
#: is the Kozai one, so the sentence says "about" and never claims a comparison the figure cannot support.
DEEP_SPACE = (
    "The {side} element set {name} is propagated with SDP4, SGP4's deep-space branch, which the library chooses for "
    f"a period of about {DEEP_SPACE_PERIOD_MIN:g} min or more (this set's is about {{period:.1f}} min): the "
    "staleness limit applied to it, {limit:g} h, and the element-set error model are rules of thumb set for LEO and "
    "GEO, not validated for this orbit, so its age and the uncertainty of its time of closest approach may be "
    "misstated. Its figures stand, flagged."
)
#: A GEO set on SDP4: the limit and error model applied are the GEO ones, so the sentence says they are the GEO rules
#: of thumb, tuned rather than sourced, not that they were set for some other orbit.
DEEP_SPACE_GEO = (
    "The {side} element set {name} is a GEO set, propagated with SDP4, SGP4's deep-space branch (period about "
    "{period:.1f} min): the staleness limit applied to it, {limit:g} h, and the element-set error model are the "
    "engine's GEO rules of thumb, tuned rather than sourced (SPC-215 will source them), so its age and the "
    "uncertainty of its time of closest approach may be misstated. Its figures stand, flagged."
)
#: An element set whose object is below the re-entry floor at an instant searched: no computed miss is shown.
DECAYED = (
    "The {side} element set {name} puts its object below the {floor:g} km re-entry floor at an instant searched: it "
    "has decayed or is decaying, so no closest approach is computed from it."
)


def _deep_space(elset: BoundElset) -> str | None:
    """The flag for *elset* when SGP4 propagates it with SDP4; None otherwise, or when it does not parse, which the
    engine's own checks refuse elsewhere."""
    try:
        orbit = TLEOrbit(elset.tle)
    except TLE_ERRORS:
        return None
    if not orbit.deep_space or elset.limit_hours is None:
        return None
    # The regime the staleness limit and the error model are chosen by (web.elsets, astro.along_track).
    sentence = DEEP_SPACE_GEO if regime_from_tle(elset.tle) == "GEO" else DEEP_SPACE
    return sentence.format(side=elset.side, name=elset.name, period=orbit.period_minutes, limit=elset.limit_hours)


def envelope_lines(scenario: Scenario, decayed: tuple[str, str, float] | None = None) -> tuple[str, ...]:
    """Each breach of the operating envelope *scenario* shows, in a sentence: each bound set on SDP4, red first, and
    *decayed*, the side, name and floor of the set the SGP4 search refused below the re-entry floor, when it did."""
    binding = scenario.binding
    bound = () if binding is None else binding.bound
    lines = [line for line in (_deep_space(elset) for elset in bound) if line is not None]
    if decayed is not None:
        side, name, floor = decayed
        lines.append(DECAYED.format(side=side, name=name, floor=floor))
    return tuple(lines)
