"""The sweep's Threat picture, held for the Decision Engine to read (SPC-171).

The sweep is where ACCESS, the threat range, Understanding, the cues and
decide-by are worked out for one red track. The Decision Engine has no
intercept in view, so it cannot bound a range by access or set a deadline of
its own; it reads the picture the sweep last held, and only when it is bound
to the same red track, while it is current, and its deadline only for the
blue asset it was set for (concept section 7.5, item 5: one deadline, so the
two cannot disagree).

hold_threat_picture is the sweep's half: one call after the sweep's decide-by
is set. held_picture is the engine's half. Neither fetches anything.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Any

from spectre.domain import threat_understanding as tu
from spectre.domain.decide_by import DecideBy, Due
from spectre.domain.decision import ScenarioBinding, ThreatPicture

#: How long the engine reads a held picture: the age at which the sweep would fetch the red track's history again
#: (pol.HELD_HISTORY_MAX_AGE), so a range and cues older than this may have moved. Tuned, not sourced.
THREAT_PICTURE_MAX_AGE = timedelta(minutes=30)
_OTHER_TARGET = (
    "The sweep's decide-by is for {target}, not {blue}, the blue asset bound here, so no deadline is set to collect "
    "against."
)


def hold_threat_picture(
    state: Any, red_name: str, understanding: tu.ThreatUnderstanding | None, decide: DecideBy, now: datetime,
) -> None:
    """Hold what the sweep just assessed for *red_name*; a sweep whose model failed holds nothing.

    A withheld decide-by holds no deadline, so the engine cannot show a cue landing in time against one.
    """
    if understanding is None:
        state.threat_picture = None
        return
    span = understanding.range
    state.threat_picture = ThreatPicture(
        red=red_name, floor=span.floor, ceiling=span.ceiling, understanding=understanding.understanding.level,
        cues=understanding.cues, decide_at=None if decide.due is Due.NONE else decide.decide_at,
        decide_by=decide.sentence, assessed_at=now, target=decide.target,
    )


def _current(picture: Any, binding: ScenarioBinding | None, now: datetime) -> ThreatPicture | None:
    """*picture* when it is for the bound red track and under THREAT_PICTURE_MAX_AGE old at *now*; else None."""
    red = None if binding is None else binding.red
    if not isinstance(picture, ThreatPicture) or red is None or picture.red != red.stk_name:
        return None
    if picture.assessed_at is None or now - picture.assessed_at >= THREAT_PICTURE_MAX_AGE:
        return None
    return picture


def held_picture(state: Any, binding: ScenarioBinding | None, now: datetime) -> ThreatPicture | None:
    """The picture the sweep held for the bound red track, while it is current at *now*; None for another red
    track, an older picture, or with none bound.

    The sweep's decide-by is for its soonest target. With another blue asset bound here, it is not this asset's
    deadline, so the picture is read with no deadline, and collect first cannot count against it.
    """
    picture = _current(getattr(state, "threat_picture", None), binding, now)
    blue = None if binding is None else binding.blue
    if picture is None or blue is None or not picture.target or picture.target in (blue.name, blue.stk_name):
        return picture
    return dataclasses.replace(
        picture, decide_at=None, decide_by=_OTHER_TARGET.format(target=picture.target, blue=blue.stk_name),
    )
