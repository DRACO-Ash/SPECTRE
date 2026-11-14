"""Every burn of a transfer on one adversary row (SPC-184).

The owner ruled on 2026-11-05 (concept section 9, decision 13) that a scenario opened from the sweep carries every
burn of the transfer, not its first alone. The burns are one adversary action with one P, never alternatives: a
row's hypothesis is its first burn, and the row carries the transfer's later burns after it, each with its own UTC
time and its own prograde, normal and radial parts in m/s, read as in-track, cross-track and radial as the first
burn's are.

What a row applies is worked out here, once the bound red element set's epoch is known. A burn at or before that
epoch is never applied, since the set may already include it (decision._after_burn): exactly those are dropped and
the rest kept. The row then starts from its first applied burn, from the bound red track's own state at that burn,
so the series never applies a burn twice. A row whose every burn is dropped keeps its first burn and is refused
(decision._after_burn): as a single burn the set may include is, or, when that first burn is exactly at the set's
epoch, which the single-burn check passes, by a sentence of its own. A single-burn row is its hypothesis unchanged.

Each later burn is sampled as the first is: the same pointing, timing and B* spreads, its delta-V spread in
proportion to its size, drawn from a seed of its own set by the row's seed and the burn's number, so the same burn
draws the same spread whichever burns before it are dropped.

THIS IS A UNIT BOUNDARY: a transfer burn holds m/s, as the sweep's entry does; the hypotheses built from it hold
km/s, as the astro package does.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

import numpy as np

from spectre.astro.monte_carlo import ManoeuvreHypothesis, elset_state
from spectre.domain.manoeuvre_calibration import from_km_s, to_km_s

#: The most burns one row carries: the sweep's longest transfer has 3, a phasing or hop plan a few more.
MAX_TRANSFER_BURNS = 8
#: The largest burn, m/s, a row may carry: the limit on burn 1's own delta-V field, held for every burn by its size.
MAX_BURN_M_S = 1000.0
#: Below this, km/s, a burn has no size to scale a spread by.
_NO_SIZE_KM_S = 1e-12


def when(moment: datetime) -> str:
    """A UTC time as the operator reads it."""
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


@dataclass(frozen=True)
class TransferBurn:
    """One burn of a transfer: its own UTC time and its prograde, normal and radial parts, m/s, as the sweep gives."""

    at_utc:       datetime
    prograde_m_s: float
    normal_m_s:   float
    radial_m_s:   float

    def __post_init__(self) -> None:
        if self.at_utc.tzinfo is None:
            raise ValueError(f"A transfer burn is at a UTC time with its offset; got {self.at_utc.isoformat()}.")
        parts = (self.prograde_m_s, self.normal_m_s, self.radial_m_s)
        if not all(math.isfinite(p) for p in parts):
            raise ValueError(f"A transfer burn's prograde, normal and radial parts are finite m/s; got {parts!r}.")

    @classmethod
    def of(cls, hypothesis: ManoeuvreHypothesis) -> TransferBurn:
        """A hypothesis's own nominal burn, in the sweep's terms: its delta-V along its RIC direction."""
        parts = np.array([hypothesis.delta_v_radial, hypothesis.delta_v_in_track, hypothesis.delta_v_cross_track])
        norm = float(np.linalg.norm(parts))
        radial, in_track, cross = (hypothesis.delta_v_magnitude_km_s * parts / norm) if norm > 0.0 else parts
        return cls(hypothesis.epoch_utc, from_km_s(float(in_track)), from_km_s(float(cross)), from_km_s(float(radial)))

    @property
    def dv_m_s(self) -> float:
        return math.hypot(self.prograde_m_s, self.normal_m_s, self.radial_m_s)

    @property
    def ric_km_s(self) -> tuple[float, float, float]:
        """Radial, in-track and cross-track, km/s: prograde read as in-track and normal as cross-track."""
        return (to_km_s(self.radial_m_s), to_km_s(self.prograde_m_s), to_km_s(self.normal_m_s))

    def words(self, number: int) -> str:
        """The burn as the operator reads it: its number, time, size and parts."""
        return (
            f"burn {number} at {when(self.at_utc)}, {self.dv_m_s:.1f} m/s (prograde {self.prograde_m_s + 0.0:.1f}, "
            f"normal {self.normal_m_s + 0.0:.1f} and radial {self.radial_m_s + 0.0:.1f} m/s)"
        )

    def recorded(self, number: int | None = None) -> dict[str, object]:
        """The burn as plain values, for provenance, at full precision."""
        lead: dict[str, object] = {} if number is None else {"burn": number}
        return {**lead, "at_utc": self.at_utc.isoformat(), "prograde_m_s": self.prograde_m_s,
                "normal_m_s": self.normal_m_s, "radial_m_s": self.radial_m_s}


def require_transfer(first_at: datetime, then: Sequence[object]) -> None:
    """Later burns are TransferBurns, at most MAX_TRANSFER_BURNS with the first, in time order from the first."""
    if len(then) + 1 > MAX_TRANSFER_BURNS:
        raise ValueError(f"A transfer carries at most {MAX_TRANSFER_BURNS} burns; got {len(then) + 1}.")
    previous = first_at
    for burn in then:
        if not isinstance(burn, TransferBurn):
            raise TypeError(f"A transfer's later burns are TransferBurns; got {type(burn).__name__}.")
        if burn.at_utc < previous:
            raise ValueError(
                f"A transfer's burns are in time order from the first; {burn.at_utc.isoformat()} comes before "
                f"{previous.isoformat()}."
            )
        previous = burn.at_utc


def _seed(row_seed: int, number: int) -> int:
    """Burn *number*'s own seed, from 2, set by the row's; burn 1 keeps the row's own."""
    return int(np.random.SeedSequence([row_seed, number]).generate_state(1)[0])


def _as_hypothesis(
    first: ManoeuvreHypothesis, burn: TransferBurn, number: int, state: np.ndarray | None = None,
) -> ManoeuvreHypothesis:
    """Burn *number* sampled as *first* is: its own time, size and direction, the same spreads, the delta-V spread
    in proportion, and its own seed. *state* is where it starts, read only when it is the row's first applied."""
    radial, in_track, cross = burn.ric_km_s
    size = math.hypot(radial, in_track, cross)
    sigma = first.delta_v_magnitude_1sigma_km_s
    if first.delta_v_magnitude_km_s > _NO_SIZE_KM_S:
        sigma *= size / first.delta_v_magnitude_km_s
    return dataclasses.replace(
        first, epoch_utc=burn.at_utc, delta_v_magnitude_km_s=size, delta_v_radial=radial,
        delta_v_in_track=in_track, delta_v_cross_track=cross, delta_v_magnitude_1sigma_km_s=sigma,
        random_seed=_seed(first.random_seed, number),
        pre_manoeuvre_state_eci_km=first.pre_manoeuvre_state_eci_km if state is None else state,
    )


class RowBurns(NamedTuple):
    """What one row applies: the burn its series starts from, the applied burns after it, and every burn it carries.

    *first* is the row's first applied burn, or its own first burn when every burn is dropped, which the engine then
    refuses (decision._after_burn). *burns* holds every burn the row carries, burn 1 first, and *dropped* the
    numbers, from 1, of those at or before *red_epoch*.
    """

    first:     ManoeuvreHypothesis
    then:      tuple[ManoeuvreHypothesis, ...]
    burns:     tuple[TransferBurn, ...]
    dropped:   tuple[int, ...]
    red_epoch: datetime | None

    @property
    def carried(self) -> int:
        return len(self.burns)

    @property
    def several(self) -> bool:
        return self.carried > 1

    @property
    def applied(self) -> tuple[int, ...]:
        return tuple(k for k in range(1, self.carried + 1) if k not in self.dropped)

    @property
    def all_dropped(self) -> bool:
        return not self.applied

    def applied_by(self, end: datetime) -> int:
        """How many applied burns come before *end*: those a figure over a span ending then can fly."""
        return sum(self.burns[k - 1].at_utc < end for k in self.applied)

    def after(self, end: datetime) -> tuple[int, ...]:
        """The applied burns at or after *end*, which no figure over a span ending then flies."""
        return tuple(k for k in self.applied if self.burns[k - 1].at_utc >= end)

    def recorded(self) -> dict[str, object]:
        """Every burn applied and every burn dropped, for provenance."""
        return {
            "applied": [self.burns[k - 1].recorded(k) for k in self.applied],
            "dropped": [self.burns[k - 1].recorded(k) for k in self.dropped],
            "red_epoch": None if self.red_epoch is None else self.red_epoch.isoformat(),
        }


def row_burns(
    first: ManoeuvreHypothesis, then: Sequence[TransferBurn], red_epoch: datetime | None, red_tle: str,
) -> RowBurns:
    """What a row whose hypothesis is *first* and whose later burns are *then* applies, against the bound red element
    set dated *red_epoch* (None when its epoch cannot be read, so nothing is dropped) and its text *red_tle*."""
    burns = (TransferBurn.of(first), *then)
    if not then:
        return RowBurns(first, (), burns, (), red_epoch)
    dropped = tuple(k for k, burn in enumerate(burns, 1) if red_epoch is not None and burn.at_utc <= red_epoch)
    applied = [k for k in range(1, len(burns) + 1) if k not in dropped]
    if not applied:
        return RowBurns(first, (), burns, dropped, red_epoch)
    lead = applied[0]
    if lead == 1:
        start = first
    else:
        track = elset_state(red_tle, burns[lead - 1].at_utc)
        start = _as_hypothesis(first, burns[lead - 1], lead, None if track is None else track.state_eci_km)
    later = tuple(_as_hypothesis(first, burns[k - 1], k) for k in applied[1:])
    return RowBurns(start, later, burns, dropped, red_epoch)


def _numbers(numbers: Sequence[int]) -> str:
    """Burn numbers in words: "1", "2 and 3", "1, 2 and 3"."""
    shown = [str(k) for k in numbers]
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def _burns_word(numbers: Sequence[int]) -> str:
    return f"Burn {_numbers(numbers)}" if len(numbers) == 1 else f"Burns {_numbers(numbers)}"


def transfer_sentence(burns: RowBurns, end: datetime | None = None) -> str | None:
    """What the row carries, which burns it applies and which it drops and why, and any applied burn the span
    searched, ending at *end*, does not reach; None for a single burn."""
    if not burns.several:
        return None
    said = _applied_and_dropped(burns)
    if end is None or not (late := burns.after(end)):
        return said
    verb, it = ("comes", "it") if len(late) == 1 else ("come", "them")
    return f"{said} {_burns_word(late)} {verb} after the span searched ends, at {when(end)}, so no figure flies {it}."


def _applied_and_dropped(burns: RowBurns) -> str:
    listed = "; ".join(b.words(k) for k, b in enumerate(burns.burns, 1))
    lead = (
        f"This row carries {burns.carried} burns of one transfer, one action with one P, listed in time order: "
        f"{listed}."
    )
    epoch = "" if burns.red_epoch is None else when(burns.red_epoch)
    if burns.all_dropped:
        return (
            f"{lead} None of its {burns.carried} burns is applied: each is at or before the red element set's epoch, "
            f"{epoch}, which may already include it, so the row is not sampled, as its cells say."
        )
    if not burns.dropped:
        return f"{lead} Every burn is applied, in time order."
    verb = "is" if len(burns.dropped) == 1 else "are"
    pronoun = "it is" if len(burns.dropped) == 1 else "each is"
    applied = "is applied" if len(burns.applied) == 1 else "are applied, in time order"
    return (
        f"{lead} {_burns_word(burns.dropped)} {verb} not applied: {pronoun} at or before the red element set's "
        f"epoch, {epoch}, which may already include it. {_burns_word(burns.applied)} {applied}."
    )


def ledger_sentence(burns: RowBurns) -> str | None:
    """The session log's words for a row of several burns: which applied and which dropped; None for one burn."""
    if not burns.several:
        return None
    if burns.all_dropped:
        return f"none of {burns.carried} burns applied, each at or before the red element set's epoch."
    applied = f"burn{'s' if len(burns.applied) > 1 else ''} {_numbers(burns.applied)} of {burns.carried} applied"
    if not burns.dropped:
        return f"{applied}."
    return (
        f"{applied}; burn{'s' if len(burns.dropped) > 1 else ''} {_numbers(burns.dropped)} dropped, at or before the "
        "red element set's epoch."
    )
