"""Open a decision scenario from a threat-sweep entry (SPC-150).

The sweep answers "can it reach one of mine, and how long have I got"; the
Decision Engine weighs what to do about it. This fills the engine's panel
from one entry of the sweep the session holds, and only with what the sweep
knows:

● the red track it flew, when that element set is the one still held;
● the target as the blue asset, when it is held as one, matched by catalogue
  number, never by name;
● the transfer's departure burn as a hypothesis, at its own UTC time, read in
  RIC from the solver's velocity, normal and radial parts, and every later burn
  of the transfer with it, each at its own UTC time, one action with one P
  (SPC-184), unless the solution does not list every burn (a hop's), when the
  row carries the departure alone and the panel says why;
● the latest confirmed burn in the red track's held element-set history,
  which evaluate builds from the element set before it through
  hypothesis_from_tle_record (SPC-001);
● a horizon that covers the arrival, and a sample count that fits the
  evaluation's budget at it.

It never fills a probability or a confidence (concept section 7.5), never
evaluates, and says what it filled, from which sweep, what it could not fill
and why. It reads only what the session holds: no fetch, no wall clock.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES
from spectre.data.intel import satno_from_tle
from spectre.domain.decision import longest_horizon_h, picture_age_words
from spectre.domain.decision_transfer import MAX_BURN_M_S, TransferBurn
from spectre.domain.models import ThreatAssessment, ThreatSweepEntry
from spectre.web.decision_threat import readable_picture
from spectre.web.elsets import elset_age
from spectre.web.format_units import format_tof_label
from spectre.web.routes.pol import HELD_HISTORY_MAX_AGE, history_evidence, reserve_reset_for

#: A burn more than this many hours before the scenario epoch is older than the longest staleness limit, so no
#: hypothesis starts there (SPC-114). The panel's burn-time field and the sweep's fixed burns share it.
EARLIEST_BURN_H = -72.0
#: The sample counts a hypothesis row takes, and the step the fit to the budget searches down by.
MIN_SAMPLES, DEFAULT_SAMPLES, MAX_SAMPLES = 100, 500, 2000
_SAMPLE_STEP = 50
#: The longest horizon the engine takes, hours.
MAX_HORIZON_H = 720.0
#: The archetype whose dispersions a sweep transfer takes: it is an intercept, by construction.
SWEEP_ARCHETYPE = "intercept_approach"
#: A departure burn shorter than this, m/s, is zero in all but rounding, so it has no direction.
_ZERO_BURN_M_S = 1e-9
_SECONDS_PER_HOUR = 3600.0
#: The most digits an entry index or a catalogue number posted here may carry; more is neither.
_MAX_DIGITS = 9
#: Below this many minutes the sweep's age reads in minutes; from it, in whole hours.
_MINUTES_IN_HOURS_FROM = 120

_NO_SWEEP = "No threat sweep is held. Run a sweep, then open a scenario from one of its entries."
_NOT_LATEST = "The sweep this was opened from is no longer the latest held. Open the scenario from the latest sweep."
_NO_ENTRY = "That entry is not in the latest sweep. Open the scenario from the latest sweep."
_NO_TRANSFER = (
    "This entry only aligns the planes and reaches no target, so it has no transfer to open as a scenario."
)
_ARRIVED = "This entry's arrival, at {at}, has passed. Sweep again to open a current one."
_NOT_FILLED = (
    "Not pre-filled: P, Conf and Gap keep the engine's defaults, and the friendly responses are yours to set. "
    "Nothing is evaluated until you press Evaluate."
)
_RED_NOT_HELD = "Red track not bound: {red} is not held as a red track in this session, so no hypothesis is pre-filled."
_RED_OTHER_SET = (
    "Red track not bound: the sweep flew a red element set other than the one now held for {red} (a manual "
    "override, or the held set was refreshed since), so no hypothesis is pre-filled. Sweep again to open from the "
    "held set."
)
_BLUE_NOT_HELD = (
    "Blue asset not bound: {target} [{satno}] is not held as a blue asset in this session. Add it under Blue Assets "
    "to bind it."
)
_BLUE_NO_SATNO = "Blue asset not bound: {target} has no catalogue number to match a held blue asset by."
_NO_DEPARTURE = "Adversary row 1 stays a lookup: the sweep's solution for this entry carries no departure burn."
_ZERO_DEPARTURE = "Adversary row 1 stays a lookup: the sweep's departure burn for this entry is zero, so it has no direction."
_DEPARTURE = (
    "Adversary row 1: the transfer's departure burn from the sweep's solution, {dv:.0f} m/s at {at}, its velocity, "
    "normal and radial parts read as in-track, cross-track and radial, which match on a near-circular orbit, with "
    "the {archetype} archetype's dispersions."
)
_BURNED_THEN = " Its departure is before now, so the hypothesis is that it burned then."
_TRANSFER = (
    "Adversary row 1: the transfer's {n} burns from the sweep's solution, one action with one P, each at its own "
    "time with the {archetype} archetype's dispersions. Burn 1's prograde, normal and radial parts are read as "
    "in-track, cross-track and radial, which match on a near-circular orbit; each later burn's are split in red's own "
    "in-track, cross-track and radial frame at its state on the transfer, where the engine applies it. Burn 1, "
    "{dv:.0f} m/s at {at}, is in the fields below; the engine applies {applies}."
)
_SOME_DROPPED = (
    "{burns} of row 1, at {at}, {verb} at or before the red element set held for {red}, dated {epoch}, which may "
    "already include {them}, so the engine will not apply {them}. It applies {kept}."
)
_ALL_DROPPED = (
    "The engine will not sample row 1's closest approach: each of its {n} burns is at or before the red element set "
    "held for {red}, dated {epoch}, so that set may already include them."
)
_NOT_LISTED = (
    "Row 1 carries burn 1 alone: the sweep's {method} solution lists {n} burns summing to {listed:.1f} m/s of the "
    "transfer's {total:.1f} m/s, so not every burn of its transfer, and the engine does not guess the rest."
)
#: The listed burns sum to the solution's cost within this share of it, or 1e-6 m/s, when it lists every burn: the
#: sweep's own sums agree to about 1e-13 m/s, and a hop solution's fall short by a third or more.
_LISTED_TOLERANCE = 1e-6
_TOO_BIG = (
    "{burns} of row 1 {verb} {dv} m/s, over the {most:,.0f} m/s a burn may be, so Evaluate will refuse the row: set "
    "its archetype to None to keep it a lookup, or open a cheaper entry from the sweep."
)
_FIRST_LINE = ", set in the fields above"
_DROPPED_LINE = "; not applied, at or before the red element set's epoch"
_DETECTED = (
    "Adversary row {row}: the burn detected at {at} in {red}'s element-set history, started from the element set "
    "before it, with the {archetype} archetype's dispersions, as the history classes the burn."
)
_NO_DETECTED = "No detected burn is offered: {why}"
_NO_HISTORY = "no element-set history is held for {red}."
_NO_BURN = "{red}'s element-set history holds no confirmed burn."
_OLD_BURN = (
    "{red}'s latest confirmed burn, at {at}, is more than 72 h before now, older than a hypothesis may start."
)
_HISTORY_OLD = (
    "{red}'s element-set history was fetched {age} ago, {limit} min or more, so a burn since then may not be in it. "
    "Sweep again to refresh it."
)
_NOT_SAMPLED = (
    "The engine will not sample row {row}'s closest approach: the red element set held for {red} dates from {epoch}, "
    "after the burn, so it may already include it. The row's burn time still sets when custody is lost."
)
_HORIZON = "Horizon {h} h, to cover the sweep's arrival at {at}."
_SAMPLES = "{n} samples a row, the most of at most {most} that fit the evaluation's budget over that horizon."
_OVER_BUDGET = (
    "At {n} samples a row the evaluation's budget covers about {fits} h, short of the {span:.0f} h this scenario "
    "needs, so the engine will refuse it as over its budget: remove a row, or shorten the horizon, which then ends "
    "before the arrival."
)
_PICTURE = (
    "The engine reads the sweep's Threat picture for {red}, assessed {age} ago, and shows its age beside every figure "
    "it feeds."
)
_NO_PICTURE = "The engine reads no Threat picture from the sweep for {red}."


@dataclass(frozen=True)
class PrefilledRow:
    """One adversary row as the panel shows it; an archetype of "" leaves it a lookup."""

    name: str
    archetype: str = ""
    dv_m_s: str = ""
    direction: tuple[str, str, str] = ("", "", "")
    samples: int = DEFAULT_SAMPLES
    #: The burn's own UTC time, so it does not move while the operator reads the panel; None for no hypothesis.
    burn_at: datetime | None = None
    #: Start from the element set before the detected burn at *burn_at*, from the held history (SPC-001).
    detected: bool = False
    #: Whether the engine will sample it: not a burn the held red element set may already include.
    sampled: bool = True
    #: The transfer's burns after the first, each at its own UTC time (SPC-184); empty for a single burn.
    then: tuple[TransferBurn, ...] = ()
    #: Every burn of the transfer in words, burn 1 first, for the panel to list before Evaluate; empty for one burn.
    burn_lines: tuple[str, ...] = ()
    #: The first burn the engine will apply, when that is not burn_at: the held red set may include those before it.
    starts_at: datetime | None = None

    @property
    def burn_at_iso(self) -> str:
        return "" if self.burn_at is None else self.burn_at.isoformat()

    @property
    def then_value(self) -> str:
        """The later burns as the panel posts them: each "UTC prograde normal radial" in m/s, joined by ";"."""
        return ";".join(f"{b.at_utc.isoformat()} {b.prograde_m_s!r} {b.normal_m_s!r} {b.radial_m_s!r}" for b in self.then)

    @property
    def burn_label(self) -> str:
        return "" if self.burn_at is None else _when(self.burn_at)


@dataclass(frozen=True)
class SweepPrefill:
    """What the panel is filled with, from which sweep, and what it is not filled with and why.

    *problem* refuses the whole fill, and the panel opens unfilled saying why.
    """

    source: str = ""
    scenario_name: str = ""
    horizon_h: str = ""
    red: str = ""
    blue: str = ""
    rows: tuple[PrefilledRow, ...] = ()
    filled: tuple[str, ...] = ()
    left: tuple[str, ...] = ()
    problem: str = ""


class DetectedBurn(NamedTuple):
    """The latest confirmed burn in the held history, the archetype the history classes it as, and when the
    history was fetched."""

    manoeuvre: Any
    archetype: str
    fetched_at: datetime


@dataclass
class _Draft:
    """The fill as it is built; frozen into a SweepPrefill at the end."""

    red: str = ""
    blue: str = ""
    rows: list[PrefilledRow] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=lambda: [_NOT_FILLED])


def _when(moment: datetime) -> str:
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


def _hours(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / _SECONDS_PER_HOUR


def _ago(now: datetime, moment: datetime) -> str:
    minutes = int((now - moment).total_seconds() // 60)
    return f"{minutes} min" if minutes < _MINUTES_IN_HOURS_FROM else f"{minutes // 60} h"


def _whole(raw: str) -> int | None:
    """*raw* as a whole number when it is ASCII digits alone, at most _MAX_DIGITS of them; else None.

    str.isdigit alone passes a superscript or an Arabic-Indic digit, and any length, which int() then refuses
    with a ValueError or reads as a different number.
    """
    text = raw.strip()
    return int(text) if text.isascii() and text.isdigit() and len(text) <= _MAX_DIGITS else None


def _number(value: float) -> str:
    """A form field's value: six significant figures, and never a negative zero."""
    return f"{value + 0.0:.6g}"


def _entry_of(assessment: ThreatAssessment, entry: str, sweep: str) -> ThreatSweepEntry | str:
    """The sweep's entry the control named, or the sentence that refuses it."""
    if assessment.sweep_epoch.isoformat() != sweep.strip():
        return _NOT_LATEST
    index = _whole(entry)
    if index is None or index >= len(assessment.entries):
        return _NO_ENTRY
    chosen = assessment.entries[index]
    return chosen if chosen.arrives else _NO_TRANSFER


def _bind_red(state: Any, assessment: ThreatAssessment, draft: _Draft) -> None:
    """Bind the red track the sweep flew, only while the set it flew is the one held."""
    red = assessment.red_name
    track = next((t for t in state.red_tracks if t.stk_name == red), None)
    if track is None:
        draft.left.append(_RED_NOT_HELD.format(red=red))
    elif track.tle.strip() != (assessment.red_tle or "").strip():
        draft.left.append(_RED_OTHER_SET.format(red=red))
    else:
        draft.red = red
        draft.filled.append(f"Red track: {red}, the object the sweep flew.")


def _same_number(tle: str, satno: str) -> bool:
    number = satno_from_tle(tle)
    return number is not None and number == _whole(satno)


def _bind_blue(state: Any, entry: ThreatSweepEntry, draft: _Draft) -> None:
    """Bind the target as the blue asset when one held carries its catalogue number; a name alone binds nothing."""
    target, satno = entry.target.target_name, (entry.target.target_satno or "").strip()
    if not satno:
        draft.left.append(_BLUE_NO_SATNO.format(target=target))
        return
    asset = next((a for a in state.blue_assets if _same_number(a.tle, satno)), None)
    if asset is None:
        draft.left.append(_BLUE_NOT_HELD.format(target=target, satno=satno))
        return
    draft.blue = asset.stk_name
    draft.filled.append(f"Blue asset: {asset.name}, the target {target}, held as a blue asset (SATNO {satno}).")


def _burn_line(number: int, burn: TransferBurn, dropped: bool) -> str:
    """One burn of the transfer as the panel lists it."""
    words = burn.words(number)
    where = _FIRST_LINE if number == 1 else ""
    return f"{words[0].upper()}{words[1:]}{where}{_DROPPED_LINE if dropped else ''}."


def _numbered(numbers: list[int]) -> str:
    shown = [str(k) for k in numbers]
    joined = shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"
    return f"burn {joined}" if len(numbers) == 1 else f"burns {joined}"


def _applies(dropped: list[int], kept: list[int]) -> str:
    """Which burns the engine applies, in the fill sentence's words: never every burn when one is dropped."""
    if not dropped:
        return "every burn in time order"
    if not kept:
        return "none of them, as said below"
    order = " in time order" if len(kept) > 1 else ""
    return f"{_numbered(kept)}{order}, not {_numbered(dropped)}, as said below"


def _lists_every_burn(entry: ThreatSweepEntry, draft: _Draft) -> bool:
    """Whether the solution lists every burn of its transfer: its burns sum to its cost. A hop solution lists only
    its entry and final burns of several hops, so its row carries burn 1 alone, and the panel says why (SPC-184)."""
    listed = sum(math.hypot(b.prograde, b.normal, b.radial) for b in entry.transfer_m_s)
    if math.isclose(listed, entry.delta_v_m_s, rel_tol=_LISTED_TOLERANCE, abs_tol=_LISTED_TOLERANCE):
        return True
    draft.left.append(_NOT_LISTED.format(
        method=entry.method.upper(), n=len(entry.transfer_m_s), listed=listed, total=entry.delta_v_m_s,
    ))
    return False


def _too_big(burns: tuple[TransferBurn, ...], draft: _Draft) -> None:
    """Name, before Evaluate, any later burn over the size a burn may be, which Evaluate would refuse (SPC-184)."""
    big = [k for k, b in enumerate(burns, 1) if k > 1 and b.dv_m_s > MAX_BURN_M_S]
    if big:
        sizes = " and ".join(f"{burns[k - 1].dv_m_s:,.0f}" for k in big)
        draft.left.append(_TOO_BIG.format(
            burns=_numbered(big).capitalize(), verb="is" if len(big) == 1 else "are", dv=sizes, most=MAX_BURN_M_S,
        ))


def _transfer_row(
    row: PrefilledRow, entry: ThreatSweepEntry, red: tuple[str, datetime | None], draft: _Draft, now: datetime,
) -> PrefilledRow:
    """Row 1 with every burn of the transfer (SPC-184): the later burns carried, each burn listed, and any at or
    before the held red set's epoch named as not applied. Burn 1 is the departure, at the entry's own burn time."""
    first = TransferBurn(entry.burn_epoch, *(entry.departure_m_s or (0.0, 0.0, 0.0)))
    burns = (first, *(TransferBurn(*b) for b in entry.transfer_m_s[1:]))
    name, epoch = red
    dropped = [k for k, b in enumerate(burns, 1) if epoch is not None and b.at_utc <= epoch]
    dated = "" if epoch is None else _when(epoch)
    kept = [k for k in range(1, len(burns) + 1) if k not in dropped]
    sentence = _TRANSFER.format(
        n=len(burns), archetype=MANOEUVRE_ARCHETYPES[SWEEP_ARCHETYPE].name, dv=first.dv_m_s,
        at=_when(entry.burn_epoch), applies=_applies(dropped, kept),
    )
    draft.filled.append(sentence + (_BURNED_THEN if entry.burn_epoch < now else ""))
    lines = tuple(_burn_line(k, b, k in dropped) for k, b in enumerate(burns, 1))
    if dropped and kept:
        one = len(dropped) == 1
        draft.left.append(_SOME_DROPPED.format(
            burns=_numbered(dropped).capitalize(), at=" and ".join(_when(burns[k - 1].at_utc) for k in dropped),
            verb="is" if one else "are", red=name, epoch=dated, them="it" if one else "them",
            kept=_numbered(kept),
        ))
    elif dropped:
        draft.left.append(_ALL_DROPPED.format(n=len(burns), red=name, epoch=dated))
    _too_big(burns, draft)
    starts = burns[kept[0] - 1].at_utc if kept and kept[0] != 1 else None
    return dataclasses.replace(row, then=burns[1:], burn_lines=lines, starts_at=starts, sampled=bool(kept))


def _departure_row(
    entry: ThreatSweepEntry, now: datetime, draft: _Draft, red_epoch: datetime | None = None,
) -> PrefilledRow:
    """Row 1: the transfer's departure burn as a hypothesis, with every later burn of the transfer (SPC-184), or the
    entry named as a lookup and why."""
    name = f"Least-warning {entry.method.upper()} transfer to {entry.target.target_name}"
    if not draft.red:
        return PrefilledRow(name)
    if entry.departure_m_s is None:
        draft.left.append(_NO_DEPARTURE)
        return PrefilledRow(name)
    prograde, normal, radial = entry.departure_m_s
    dv = math.sqrt(prograde ** 2 + normal ** 2 + radial ** 2)
    if dv < _ZERO_BURN_M_S:
        draft.left.append(_ZERO_DEPARTURE)
        return PrefilledRow(name)
    row = PrefilledRow(
        name, archetype=SWEEP_ARCHETYPE, dv_m_s=_number(dv),
        direction=(_number(radial / dv), _number(prograde / dv), _number(normal / dv)), burn_at=entry.burn_epoch,
    )
    if len(entry.transfer_m_s) > 1 and _lists_every_burn(entry, draft):
        return _transfer_row(row, entry, (draft.red, red_epoch), draft, now)
    archetype = MANOEUVRE_ARCHETYPES[SWEEP_ARCHETYPE].name
    sentence = _DEPARTURE.format(dv=dv, at=_when(entry.burn_epoch), archetype=archetype)
    draft.filled.append(sentence + (_BURNED_THEN if entry.burn_epoch < now else ""))
    return row


def latest_detected_burn(state: Any, satno: int | None, red: str, now: datetime) -> DetectedBurn | str:
    """The latest confirmed burn in *satno*'s held history, within 72 h of *now*; else why there is none.

    It reads the held copy only, as every panel does (``held_history``), and fetches nothing. The archetype is
    the history's own class for the burn (``ManoeuvreView.monte_carlo_archetype``), which sets only dispersions.
    """
    held = None if satno is None else state.elset_histories.get(satno)
    if satno is None or held is None:
        return _NO_HISTORY.format(red=red)
    if held.pol is None:
        return str(held.problem)   # held_history's own fixed sentences, safe to show as they are
    assessment, _latest = history_evidence(held.pol, reserve_reset_for(state, satno))
    if not assessment.manoeuvres:
        return _NO_BURN.format(red=red)
    view = max(assessment.manoeuvres, key=lambda v: v.manoeuvre.burn_epoch)
    burn = view.manoeuvre
    if _hours(burn.burn_epoch, now) < EARLIEST_BURN_H:
        return _OLD_BURN.format(red=red, at=_when(burn.burn_epoch))
    return DetectedBurn(burn, view.monte_carlo_archetype, held.fetched_at)


def detected_burn(state: Any, satno: int | None, at: datetime) -> Any | None:
    """The confirmed burn at *at* in *satno*'s held history, for evaluate to build from; None when not held."""
    held = None if satno is None else state.elset_histories.get(satno)
    pol = None if held is None else held.pol
    burns = [] if pol is None else getattr(pol, "manoeuvres", [])
    return next((m for m in burns if m.burn_epoch == at), None)


def _detected_row(state: Any, assessment: ThreatAssessment, now: datetime, draft: _Draft) -> None:
    """Row 2, when the red track is bound and its held history holds a burn in the last 72 h; else say why not."""
    if not draft.red:
        return
    red = assessment.red_name
    found = latest_detected_burn(state, satno_from_tle(assessment.red_tle or ""), red, now)
    if isinstance(found, str):
        draft.left.append(_NO_DETECTED.format(why=found))
        return
    at = found.manoeuvre.burn_epoch
    row = len(draft.rows) + 1
    archetype = MANOEUVRE_ARCHETYPES[found.archetype].name
    draft.filled.append(_DETECTED.format(row=row, at=_when(at), red=red, archetype=archetype))
    # held_history fetches a copy this old again, so a later burn may be missing from it: say so (SPC-119).
    if now - found.fetched_at >= HELD_HISTORY_MAX_AGE:
        limit = int(HELD_HISTORY_MAX_AGE.total_seconds() // 60)
        draft.left.append(_HISTORY_OLD.format(red=red, age=_ago(now, found.fetched_at), limit=limit))
    # The engine does not sample a burn the bound red set may already include (decision._after_burn), so say so.
    age = elset_age(assessment.red_tle or "", now)
    sampled = age is None or age.epoch <= at
    if not sampled and age is not None:
        draft.left.append(_NOT_SAMPLED.format(row=row, red=red, epoch=_when(age.epoch)))
    draft.rows.append(PrefilledRow(f"Detected burn at {_when(at)}", archetype=found.archetype, burn_at=at,
                                   detected=True, sampled=sampled))


def _fit_samples(horizon_h: float, now: datetime, draft: _Draft) -> None:
    """Give each hypothesis row the most samples, of at most DEFAULT_SAMPLES, that fit the budget; say so."""
    sampled = [row for row in draft.rows if row.archetype and row.sampled]
    if not sampled:
        return
    # A row of several burns is integrated from the first the engine applies (SPC-184).
    earliest = min(_hours(row.starts_at or row.burn_at, now) for row in sampled if row.burn_at is not None)
    span = horizon_h + max(0.0, -earliest)
    rows = len(sampled)
    n = next((n for n in range(DEFAULT_SAMPLES, MIN_SAMPLES - 1, -_SAMPLE_STEP)
              if longest_horizon_h(n, rows=rows) >= span), None)
    if n is None:
        n = MIN_SAMPLES
        draft.left.append(_OVER_BUDGET.format(n=n, fits=longest_horizon_h(n, rows=rows), span=span))
    else:
        draft.filled.append(_SAMPLES.format(n=n, most=DEFAULT_SAMPLES))
    draft.rows = [dataclasses.replace(r, samples=n) if r in sampled else r for r in draft.rows]


def _picture_sentence(state: Any, red: str, now: datetime) -> str:
    """Whether the engine will read the sweep's Threat picture for *red*, as decision_threat.held_picture reads it:
    at any age, which it says (SPC-181)."""
    picture = readable_picture(getattr(state, "threat_picture", None), red, now)
    if picture is None:
        return _NO_PICTURE.format(red=red)
    return _PICTURE.format(red=red, age=picture_age_words(now - picture.assessed_at))


def _source(assessment: ThreatAssessment, entry: ThreatSweepEntry, now: datetime) -> str:
    satno = f" [{entry.target.target_satno}]" if entry.target.target_satno else ""
    return (
        f"Opened from the sweep of {assessment.red_name} at {_when(assessment.sweep_epoch)}, "
        f"{_ago(now, assessment.sweep_epoch)} ago: its {entry.method.upper()} transfer to "
        f"{entry.target.target_name}{satno}, departing at {_when(entry.burn_epoch)} and arriving in "
        f"{format_tof_label(entry.tof_hours)}."
    )


def open_from_sweep(state: Any, entry: str, sweep: str, now: datetime) -> SweepPrefill:
    """The panel's fill from entry *entry* of the held sweep whose epoch is *sweep*, at *now*.

    Total: anything the session no longer holds is a sentence, never an exception.
    """
    assessment = getattr(state, "last_threat_assessment", None)
    if assessment is None:
        return SweepPrefill(problem=_NO_SWEEP)
    chosen = _entry_of(assessment, entry, sweep)
    if isinstance(chosen, str):
        return SweepPrefill(problem=chosen)
    arrival = chosen.burn_epoch + timedelta(hours=chosen.tof_hours)
    if arrival <= now:
        return SweepPrefill(problem=_ARRIVED.format(at=_when(arrival)))
    draft = _Draft()
    _bind_red(state, assessment, draft)
    _bind_blue(state, chosen, draft)
    held = elset_age(assessment.red_tle or "", now)
    draft.rows.append(_departure_row(chosen, now, draft, None if held is None else held.epoch))
    _detected_row(state, assessment, now, draft)
    horizon = min(MAX_HORIZON_H, math.ceil(_hours(arrival, now)) + 1.0)
    draft.filled.append(_HORIZON.format(h=f"{horizon:g}", at=_when(arrival)))
    _fit_samples(horizon, now, draft)
    draft.left.append(_picture_sentence(state, assessment.red_name, now))
    return SweepPrefill(
        source=_source(assessment, chosen, now),
        scenario_name=f"{assessment.red_name} on {chosen.target.target_name}, from the sweep at "
                      f"{assessment.sweep_epoch:%H:%M} UTC",
        horizon_h=f"{horizon:g}", red=draft.red, blue=draft.blue, rows=tuple(draft.rows),
        filled=tuple(draft.filled), left=tuple(draft.left),
    )
