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

P carries an interval (SPC-132): the exact (Garwood) 95 in 100 interval on the
Poisson mean behind the events counted, carried over the horizon as P is. The
events are a count over an exposure time, which is what a Poisson interval is
for, and a suggestion rests on as few as MIN_EVENTS of them, where a normal
approximation runs below 0 and under-covers; the exact interval keeps at least
its stated coverage at any count, erring wide. Its edges are rounded outward,
so it never reads narrower than it is. It is an interval on the reported rate:
like P, it says nothing of burns no notice was filed for.

The prior keeps the periods it counted and the notices behind it (SPC-131),
from which its timeline lists, in date order, each covered period, each gap
and each notice, named in words, then the time from the cache's last covered
moment to the moment the prior was asked for, which is uncovered too.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

from scipy.stats import chi2

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
#: The share of the exact Poisson interval left out in each tail: 95 in 100 in all.
_TAIL = 0.025

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
_INTERVAL = (
    "P {p:.2f} lies in {low} to {high:.2f}, an exact Poisson interval, 95 in 100, on the {events} reported events in "
    "the {days:.0f} days covered, carried over {horizon:g} h as P is. It is exact, not approximate, because a "
    "suggestion can rest on as few as {least} events, where an approximate interval runs below 0; the exact one keeps "
    "its 95 in 100 at any count and errs wide. Only expected value reads P; minimax and minimin ignore it."
)
_COVERED = (
    "Covered: {start} to {end} UTC, {days:.1f} days; notices for any object were synced, so this time is counted."
)
_GAP = (
    "Gap: {start} to {end} UTC, {days:.1f} days with no notice for any object; a gap in the cache, not quiet, so it "
    "is not counted."
)
_UNCOVERED_SINCE = (
    "Not covered: {start} to {end} UTC, {days:.1f} days from the cache's last covered moment to the time evaluated, "
    "with no notice for any object; not quiet, so it is not counted."
)
_NOTICE = "Notice: {at} UTC, {kind}; event {n}."
_COPY = "Notice: {at} UTC, {kind}; a copy of event {n}, counted once."
_BEFORE = (
    "Not counted: time before 01 Jan {year}, the start of {red}'s launch year, when it did not exist to be reported "
    "on."
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


def _minute(moment: datetime) -> str:
    return f"{moment:%d %b %Y %H:%M}"


def _ceil(value: float) -> float:
    """*value* rounded up to the hundredth, at most 1: an interval's upper edge, rounded outward."""
    return min(1.0, math.ceil(value * _HUNDREDTHS) / _HUNDREDTHS)


def poisson_interval(events: int) -> tuple[float, float]:
    """The exact (Garwood) 95 in 100 interval on the Poisson mean behind a count of *events*, at least 1.

    Its lower limit is half the chi-square quantile at 0.025 on 2k degrees of freedom; its upper, half the quantile
    at 0.975 on 2k + 2.
    """
    if events < 1:
        raise ValueError(f"an exact Poisson interval here needs a count of at least 1; got {events}")
    return float(chi2.ppf(_TAIL, 2 * events)) / 2.0, float(chi2.ppf(1.0 - _TAIL, 2 * events + 2)) / 2.0


class PriorInterval(NamedTuple):
    """P's interval, its edges rounded outward to the hundredth.

    *low* reads 0.0 when the lower edge is under the hundredth, and is then shown as "under 0.01"; *checked_low* is
    the edge a pick is checked from: *low* itself, unless that is 0.0, when it is the exact lower edge, above 0.
    """

    low:         float
    high:        float
    checked_low: float


@dataclass(frozen=True)
class CountedNotice:
    """A notice a prior counted: its stated start and its NOTSO type."""

    start: datetime
    kind:  NOTSOType


#: The width of the bar a timeline is drawn on, in its own units: the span from the first covered moment to the last.
BAR_UNITS = 1000.0


class TimelineEntry(NamedTuple):
    """One entry of a prior's timeline, named in words, and where it sits on the bar, in BAR_UNITS."""

    kind:  str
    start: datetime
    text:  str
    left:  float
    width: float


class _Place:
    """Places timeline entries on a bar BAR_UNITS wide from *start* to *end*, to the tenth of a unit."""

    def __init__(self, start: datetime, end: datetime) -> None:
        self.start, self.span = start, max((end - start).total_seconds(), 1.0)

    def _at(self, moment: datetime) -> float:
        return round((moment - self.start).total_seconds() / self.span * BAR_UNITS, 1)

    def period(self, kind: str, line: str, low: datetime, high: datetime) -> TimelineEntry:
        days = (high - low).total_seconds() / _SECONDS_PER_HOUR / _HOURS_PER_DAY
        text = line.format(start=_minute(low), end=_minute(high), days=days)
        return TimelineEntry(kind, low, text, self._at(low), round(self._at(high) - self._at(low), 1))

    def notice(self, notice: CountedNotice, mark: tuple[int, bool]) -> TimelineEntry:
        number, copy = mark
        text = (_COPY if copy else _NOTICE).format(at=_minute(notice.start), kind=_label_type(notice.kind), n=number)
        return TimelineEntry("notice", notice.start, text, self._at(notice.start), 0.0)


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
    #: The periods counted, less any before the launch year, and the notices counted in them, in date order
    #: (SPC-131); empty on a prior built without them.
    cover:           tuple[tuple[datetime, datetime], ...] = ()
    counted:         tuple[CountedNotice, ...] = ()
    #: The moment the prior was asked for, when known: the time from the last covered moment to it is uncovered.
    until:           datetime | None = None

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
    def interval(self) -> PriorInterval:
        """P's exact Poisson interval, carried over the horizon as P is, its edges rounded outward."""
        low, high = poisson_interval(self.events)
        exposure = self.horizon_hours / (self.covered_days * _HOURS_PER_DAY)
        exact_low = 1.0 - math.exp(-low * exposure)
        shown = _floor(exact_low)
        return PriorInterval(shown, _ceil(1.0 - math.exp(-high * exposure)), shown if shown > 0.0 else exact_low)

    @property
    def interval_line(self) -> str:
        """P's interval, the method and why it suits a floor read from so few events."""
        interval = self.interval
        low = f"{interval.low:.2f}" if interval.low > 0.0 else "under 0.01"
        return _INTERVAL.format(p=self.probability, low=low, high=interval.high, events=self.events,
                                days=self.covered_days, horizon=self.horizon_hours, least=MIN_EVENTS)

    @property
    def timeline(self) -> tuple[TimelineEntry, ...]:
        """The covered periods, the gaps between them and the notices counted, in date order, then any time from the
        last covered moment to the moment asked for; empty when not kept."""
        if not self.cover:
            return ()
        last = self.cover[-1][1]
        until = last if self.until is None else max(self.until, last)
        place = _Place(self.cover[0][0], until)
        marked = list(zip(self.counted, _numbered([n.start for n in self.counted]), strict=True))
        entries = [] if self.launched is None else [
            TimelineEntry("not counted", self.cover[0][0], _BEFORE.format(year=self.launched, red=self.red), 0.0, 0.0),
        ]
        for i, (low, high) in enumerate(self.cover):
            entries.append(place.period("covered", _COVERED, low, high))
            entries.extend(place.notice(notice, mark) for notice, mark in marked if low <= notice.start <= high)
            if i + 1 < len(self.cover):
                entries.append(place.period("gap", _GAP, high, self.cover[i + 1][0]))
        if until > last:
            entries.append(place.period("gap", _UNCOVERED_SINCE, last, until))
        return tuple(entries)

    @property
    def token(self) -> str:
        """The values shown, as the apply control posts them back: P, then Conf or blank."""
        conf = "" if self.confidence is None else f"{self.confidence:.2f}"
        return f"{self.probability:.2f}|{conf}"


def _label_type(kind: NOTSOType) -> str:
    return kind.value.replace("_", " ")


def _numbered(starts: Sequence[datetime]) -> list[tuple[int, bool]]:
    """Each of *starts*, in date order, with the number of the event it belongs to and whether it copies that event.

    A start more than SAME_EVENT after the last event's first opens a new event.
    """
    marks: list[tuple[int, bool]] = []
    count, opened = 0, None
    for start in starts:
        copy = opened is not None and start - opened <= SAME_EVENT
        if not copy:
            count, opened = count + 1, start
        marks.append((count, copy))
    return marks


def _events(starts: Sequence[datetime]) -> int:
    """Distinct events among notice *starts*: a start more than SAME_EVENT after the last event's first opens one."""
    marks = _numbered(sorted(starts))
    return marks[-1][0] if marks else 0


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
    until: datetime | None = None,
) -> NotsoPrior | NoPrior:
    """The prior for *action_type* by *red* over *horizon_hours*, from its *notices* in *span*, or why there is none.

    *cover* is the periods of time the NOTSO cache covers, in order; *profile*, when given, is red's notices correlated with its held
    element-set history, which is what earns a Conf; *launched*, when known, is red's launch year, before which the
    cover is not counted; *until*, when given, is the moment the prior is asked for, which its timeline runs to.
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
    counted = tuple(sorted(
        (CountedNotice(n.effective_start_utc, n.notso_type) for n in notices
         if n.notso_type in mapped and any(low <= n.effective_start_utc <= high for low, high in cover)),
        key=lambda c: c.start,
    ))
    starts = [c.start for c in counted]
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
        launched=launched if clipped else None, cover=tuple(cover), counted=counted, until=until,
    )
