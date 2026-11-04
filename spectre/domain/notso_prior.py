"""An adversary probability and confidence offered from NOTSO history (SPC-130).

The Decision Engine's P and Conf are the operator's. This module offers a
suggestion for them, which the operator applies with a labelled control or
ignores; it is never written into a row unasked (Threat Understanding concept,
section 7.5, items 2 and 3).

P is the chance of at least one reported event of the row's action type
within the scenario horizon, at the rate the object's NOTSO history shows:
mapped notices in the periods the cache covers, copies of one event counted once.
A spell in which the cache holds no notice for any object is a gap in what was
synced, so it is left out of the time the rate is counted over, never read as
quiet; so is any time before the start of the object's launch year, when it did
not exist to be reported on.
A NOTSO follows human analysis and is withheld for small routine burns, so a
quiet record is not evidence of inactivity. Below MIN_EVENTS nothing is
offered, nor when the chance rounds below the hundredth: never a probability
of 0. No action type is offered the
complement of a manoeuvre's prior. P is therefore a floor on the chance of a
manoeuvre, not the chance of any burn.

Conf is how sure the intelligence behind P is: how fully the NOTSO record is
shown to cover the object's reportable manoeuvres, read from its
OperatorBehaviourProfile as the lower edge of a 95 in 100 Wilson interval on
the share that carried a notice. Whether to file is the adversary's choice,
so however full the record, Conf is capped at MANUFACTURABLE_CAP, the most
Threat Understanding lets any manufacturable item be worth. With no profile,
or one with too few reportable manoeuvres, no Conf is offered.

Both figures are rounded down to the hundredth, so neither reads stronger
than it is. Their basis is LOOKUP: a rate carried over a horizon, uncalibrated
against any outcome.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from spectre.astro.notso import NOTSORecord, NOTSOType, OperatorBehaviourProfile
from spectre.domain.decision import ActionType
from spectre.domain.provenance import Basis, FigureBasis
from spectre.domain.threat_understanding import MANUFACTURABLE_CAP

#: The fewest reported events a prior is offered from. Tuned, not sourced: fewer is not a rate.
MIN_EVENTS = 3
#: Notices whose stated starts lie within this of an event's first notice are copies of that event, not another.
#: Tuned, not sourced: a JCO notice is often followed by a verified or possible restatement of the same burn.
SAME_EVENT = timedelta(hours=24)
#: The Wilson interval's z for 95 in 100.
_WILSON_Z = 1.96
_HOURS_PER_DAY = 24.0
_SECONDS_PER_HOUR = 3600.0
_HUNDREDTHS = 100

#: Which of the engine's action types each NOTSO type reports. A deorbit ends the object's mission rather than
#: threatening an asset, a launch is not the object's own action, and a test or other notice names no action the
#: engine models, so none of them maps.
NOTSO_ACTION_TYPES: dict[NOTSOType, ActionType | None] = {
    NOTSOType.MANOEUVRE: ActionType.MANOEUVRE,
    NOTSOType.PROXIMITY_OPS: ActionType.MANOEUVRE,
    NOTSOType.DEORBIT: None,
    NOTSOType.LAUNCH: None,
    NOTSOType.TEST: None,
    NOTSOType.OTHER: None,
}

PRIOR_NOTE = (
    "a lookup: the rate of reported events in the object's NOTSO history, carried over the scenario horizon; "
    "uncalibrated against any outcome"
)
_NO_TYPE = "No NOTSO type maps to {action}, so no suggestion is offered for it."
_NOT_INACTIVE = (
    " A quiet NOTSO record is not evidence that {red} is inactive: routine burns below the reporting threshold "
    "carry no notice."
)
_NO_SPAN = "The NOTSO cache covers no span of time yet, so no suggestion is offered."
_NO_SPAN_SINCE = (
    "The NOTSO cache covers no time since the start of {red}'s launch year, {year}, so no suggestion is offered."
)
_SINCE = ", none of them before the start of {red}'s launch year, {year}"
_TOO_FEW = (
    "{events} reported {action} events for {red} in the {days:.0f} days the NOTSO cache covers from {start} to {end}, "
    "fewer than the {least} a suggestion needs, so none is offered. Fewer notices are not fewer burns: routine burns "
    "below the reporting threshold carry no notice."
)
_TOO_SMALL = (
    "{events} reported {action} events for {red} in the {days:.0f} days the NOTSO cache covers put the chance of a "
    "reported one within {horizon:g} h below 0.01, too small to offer as a figure, so none is offered. That is not "
    "evidence that {red} is inactive: routine burns below the reporting threshold carry no notice."
)
_BASIS = (
    "P is the chance of at least one reported {action} in {horizon:g} h at the rate of {events} reported events "
    "({notices} notices) in the {days:.0f} days the NOTSO cache covers from {start} to {end}{since}{gaps}, where "
    "{mapped} "
    "notices count as a {action}; a lookup. It is a floor, not the chance of any burn: routine burns below the "
    "reporting threshold carry no notice."
)
_GAPS = ", leaving out {n} spell{s} with no notice for any object, which {verb} in the cache, not quiet"
_NO_HISTORY = (
    "No Conf is offered: no element-set history is held for {red}, so how fully its NOTSO record covers its "
    "manoeuvres is not measured."
)
_UNASSESSABLE = (
    "No Conf is offered: only {reportable} of {red}'s detected manoeuvres were above the reporting threshold, too "
    "few to measure how fully its NOTSO record covers them."
)
_CONFIDENCE = (
    "Conf {conf:.2f} is the lower edge of a 95 in 100 interval on the share of {red}'s reportable manoeuvres its "
    "NOTSO record covered, {noticed} of {reportable}; a lookup."
)
_CAPPED = (
    "Conf {cap:.2f}: the lower edge of a 95 in 100 interval on the share of {red}'s reportable manoeuvres its NOTSO "
    "record covered, {noticed} of {reportable}, is {conf:.2f}, capped at {cap:.2f}, the most SPECTRE gives a NOTSO "
    "filing, since whether to file is the adversary's choice; a lookup."
)


def _floor(value: float) -> float:
    """*value* rounded down to the hundredth, so a figure never reads stronger than it is."""
    return math.floor(value * _HUNDREDTHS) / _HUNDREDTHS


def _label(action: ActionType) -> str:
    return action.value.replace("_", " ")


def _date(moment: datetime) -> str:
    return f"{moment:%d %b %Y}"


@dataclass(frozen=True)
class NoPrior:
    """Why no suggestion is offered, in the operator's words."""

    reason: str


@dataclass(frozen=True)
class NotsoPrior:
    """A P, and a Conf when earned, offered for one action type of one red object, with what it rests on.

    *events* is the sample size: mapped notices in the periods the cache covers, copies of one event counted once;
    *notices* counts them before that. The periods run from *span_start* to *span_end*, *covered_days* in all, less
    *gaps* spells in which the cache holds no notice for any object; *launched* is the object's launch year when the
    cover before its start was left out, else None.
    """

    red:             str
    action_type:     ActionType
    probability:     float
    confidence:      float | None
    events:          int
    notices:         int
    span_start:      datetime
    span_end:        datetime
    covered_days:    float
    gaps:            int
    horizon_hours:   float
    mapped:          tuple[NOTSOType, ...]
    confidence_line: str
    launched:        int | None = None
    basis:           FigureBasis = FigureBasis(Basis.LOOKUP, PRIOR_NOTE)

    def __post_init__(self) -> None:
        """A prior never rests on fewer events than the floor, never reads as no chance, and never shows more Conf
        than a NOTSO filing earns."""
        if self.events < MIN_EVENTS:
            raise ValueError(f"a NOTSO prior needs at least {MIN_EVENTS} events; got {self.events}")
        if not 0.0 < self.probability <= 1.0:
            raise ValueError(f"a NOTSO prior's probability lies in (0, 1]; got {self.probability}")
        if self.confidence is not None and not 0.0 <= self.confidence <= MANUFACTURABLE_CAP:
            raise ValueError(
                f"a NOTSO prior's confidence lies in [0, {MANUFACTURABLE_CAP}]; got {self.confidence}",
            )

    @property
    def suggestion(self) -> str:
        conf = "" if self.confidence is None else f", Conf {self.confidence:.2f}"
        return f"NOTSO suggestion for {self.red}: P {self.probability:.2f}{conf}."

    @property
    def basis_line(self) -> str:
        gaps = "" if self.gaps == 0 else _GAPS.format(
            n=self.gaps, s="" if self.gaps == 1 else "s", verb="is a gap" if self.gaps == 1 else "are gaps",
        )
        return _BASIS.format(
            action=_label(self.action_type), horizon=self.horizon_hours, events=self.events, notices=self.notices,
            start=_date(self.span_start), end=_date(self.span_end), days=self.covered_days, gaps=gaps,
            since="" if self.launched is None else _SINCE.format(red=self.red, year=self.launched),
            mapped=" and ".join(_label_type(t) for t in self.mapped),
        )

    @property
    def lines(self) -> tuple[str, str, str]:
        """The suggestion, what P rests on, and what Conf rests on or why none is offered."""
        return self.suggestion, self.basis_line, self.confidence_line

    @property
    def token(self) -> str:
        """The values shown, as the apply control posts them back: P, then Conf or blank."""
        conf = "" if self.confidence is None else f"{self.confidence:.2f}"
        return f"{self.probability:.2f}|{conf}"


def _label_type(kind: NOTSOType) -> str:
    return kind.value.replace("_", " ")


def _events(starts: Sequence[datetime]) -> int:
    """Distinct events among notice *starts*: a start more than SAME_EVENT after the last event's first opens one."""
    count, opened = 0, None
    for start in sorted(starts):
        if opened is None or start - opened > SAME_EVENT:
            count, opened = count + 1, start
    return count


def _wilson_lower(successes: int, trials: int) -> float:
    """The lower edge of the 95 in 100 Wilson score interval on *successes* of *trials*, with trials above 0."""
    p, z2 = successes / trials, _WILSON_Z * _WILSON_Z
    centre = p + z2 / (2 * trials)
    spread = _WILSON_Z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))
    return (centre - spread) / (1 + z2 / trials)


def _confidence(red: str, profile: OperatorBehaviourProfile | None) -> tuple[float | None, str]:
    """Conf from *profile*, and its line; None and why when the record's coverage is not measured."""
    if profile is None:
        return None, _NO_HISTORY.format(red=red)
    reportable = profile.reportable_manoeuvres
    if profile.behaviour_unassessable or reportable <= 0:
        return None, _UNASSESSABLE.format(red=red, reportable=reportable)
    noticed = round(profile.notification_rate * reportable)
    conf = _floor(_wilson_lower(noticed, reportable))
    if conf > MANUFACTURABLE_CAP:
        return MANUFACTURABLE_CAP, _CAPPED.format(cap=MANUFACTURABLE_CAP, conf=conf, red=red, noticed=noticed,
                                                  reportable=reportable)
    return conf, _CONFIDENCE.format(conf=conf, red=red, noticed=noticed, reportable=reportable)


def _since_launch(
    cover: Sequence[tuple[datetime, datetime]], launched: int | None,
) -> tuple[Sequence[tuple[datetime, datetime]], bool]:
    """*cover* less any time before the start of the *launched* year, and whether that left anything out."""
    if launched is None or not cover:
        return cover, False
    since = datetime(launched, 1, 1, tzinfo=cover[0][0].tzinfo)
    if cover[0][0] >= since:
        return cover, False
    return [(max(low, since), high) for low, high in cover if high > since], True


# PLR0913: the red object, the action and its notices are what the prior is about; the span, horizon and profile
# are each a separate question, and every call passes the last three by keyword.
def notso_prior(  # noqa: PLR0913
    red: str,
    action_type: ActionType,
    notices: Sequence[NOTSORecord],
    *,
    cover: Sequence[tuple[datetime, datetime]],
    horizon_hours: float,
    profile: OperatorBehaviourProfile | None = None,
    launched: int | None = None,
) -> NotsoPrior | NoPrior:
    """The prior for *action_type* by *red* over *horizon_hours*, from its *notices* in *span*, or why there is none.

    *cover* is the periods of time the NOTSO cache covers, in order; *profile*, when given, is red's notices correlated with its held
    element-set history, which is what earns a Conf; *launched*, when known, is red's launch year, before which the
    cover is not counted.
    """
    if not (math.isfinite(horizon_hours) and horizon_hours > 0.0):
        raise ValueError(f"a prior needs a finite horizon above 0 h; got {horizon_hours!r}")
    mapped = tuple(kind for kind, action in NOTSO_ACTION_TYPES.items() if action is action_type)
    if not mapped:
        extra = _NOT_INACTIVE.format(red=red) if action_type is ActionType.NO_ACTION else ""
        return NoPrior(_NO_TYPE.format(action=_label(action_type)) + extra)
    cover, clipped = _since_launch(cover, launched)
    if clipped and not cover:
        return NoPrior(_NO_SPAN_SINCE.format(red=red, year=launched))
    covered_h = sum((high - low).total_seconds() for low, high in cover) / _SECONDS_PER_HOUR
    if covered_h <= 0.0:
        return NoPrior(_NO_SPAN)
    start, end = cover[0][0], cover[-1][1]
    starts = [n.effective_start_utc for n in notices
              if n.notso_type in mapped and any(low <= n.effective_start_utc <= high for low, high in cover)]
    events, days = _events(starts), covered_h / _HOURS_PER_DAY
    if events < MIN_EVENTS:
        return NoPrior(_TOO_FEW.format(events=events, action=_label(action_type), red=red, start=_date(start),
                                       end=_date(end), days=days, least=MIN_EVENTS))
    probability = _floor(1.0 - math.exp(-events * horizon_hours / covered_h))
    if probability <= 0.0:
        return NoPrior(_TOO_SMALL.format(events=events, action=_label(action_type), red=red, days=days,
                                         horizon=horizon_hours))
    confidence, confidence_line = _confidence(red, profile)
    return NotsoPrior(
        red=red, action_type=action_type, probability=probability, confidence=confidence, events=events,
        notices=len(starts), span_start=start, span_end=end, covered_days=days, gaps=len(cover) - 1,
        horizon_hours=horizon_hours, mapped=mapped, confidence_line=confidence_line,
        launched=launched if clipped else None,
    )
