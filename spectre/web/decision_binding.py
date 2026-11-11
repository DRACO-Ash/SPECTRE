"""Bind a decision scenario to the real objects it is about (SPC-100).

The operator may name one held red track and one held blue asset. Each is
looked up on its own side only, and its element set's epoch, age and regime
limit are read here, in the web layer where ``elset_age`` lives, then handed
to the domain as plain values. Nothing here does I/O or writes the session.

The binder never falls back to unbound: a name that is no longer held is
refused with a sentence the panel shows inline, as is binding one object to
both sides. It is total on any held element set, because it runs outside the
evaluation's error handling: ``elset_age`` returns None for an unreadable
epoch, its regime lookup catches TLE errors, and ``satno_from_tle`` returns
None for a line it cannot read.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal, NamedTuple, Protocol

from spectre.data.intel import satno_from_tle
from spectre.domain.decision import BoundElset, ScenarioBinding
from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.elsets import elset_age, refused
from spectre.web.planning_state import SessionState

_NOT_HELD = "{kind} {name} is no longer held in this session. Choose another or leave it unbound."
_SAME_SATNO = "Red and blue are the same object (SATNO {satno}). Bind two different objects."
#: What became of a held set the acceptance check refuses at binding (SPC-201).
_NOT_BOUND = "Nothing was bound; add a sound element set for it."


class BindOutcome(NamedTuple):
    """The binding to evaluate with, or the sentence that refuses it; both None when unbound."""

    binding: ScenarioBinding | None
    problem: str | None


class HeldElset(Protocol):
    """What binding reads from a held object: a red track, a blue asset, or a later source (SPC-150)."""

    @property
    def name(self) -> str: ...
    @property
    def stk_name(self) -> str: ...
    @property
    def tle(self) -> str: ...
    @property
    def data_mode(self) -> str: ...
    @property
    def training(self) -> bool: ...


def bound_elset(side: Literal["red", "blue"], held: HeldElset, now: datetime) -> BoundElset:
    """One bound element set from *held*, aged at *now*.

    It takes anything shaped like a held object, so a later source (a sweep
    target, SPC-150) can bind through the same door. The object's own data
    mode is read, never the session's or the target cache's.
    """
    tle = held.tle
    age = elset_age(tle, now)
    return BoundElset(
        side=side, name=held.name, stk_name=held.stk_name, satno=satno_from_tle(tle), tle=tle,
        data_mode=held.data_mode, training=held.training,
        epoch=None if age is None else age.epoch,
        age_hours=None if age is None else age.hours,
        limit_hours=None if age is None else age.limit_hours,
    )


def _held[T: (RedTrack, BlueAsset)](objects: Iterable[T], stk_name: str) -> T | None:
    return next((obj for obj in objects if obj.stk_name == stk_name), None)


def _same_object(red: BoundElset, blue: BoundElset) -> str | None:
    """The refusal when red and blue are one object, by catalogue number. Every set bound has passed the
    acceptance check, which reads its catalogue number (SPC-201), so two identical sets share one and are caught
    here; no comparison of the text is needed."""
    if red.satno is not None and red.satno == blue.satno:
        return _SAME_SATNO.format(satno=red.satno)
    return None


def _unsound(*held: tuple[str, RedTrack | BlueAsset | None]) -> str | None:
    """The sentence refusing the first held set the acceptance check refuses, or None (SPC-201).

    Every ingest path runs the check before storing a set; the binder runs it again, so a set held by any other
    route, or before the check existed, never reaches the engine.
    """
    for kind, obj in held:
        if obj is not None:
            refusal = refused(f"{kind} {obj.name}", obj.tle, outcome=_NOT_BOUND)
            if refusal is not None:
                return refusal
    return None


def bind_scenario(state: SessionState, red_sat: str, blue_sat: str, now: datetime) -> BindOutcome:
    """Bind the held red track *red_sat* and blue asset *blue_sat*; a blank name leaves that side unbound."""
    red_obj = _held(state.red_tracks, red_sat) if red_sat else None
    if red_sat and red_obj is None:
        return BindOutcome(None, _NOT_HELD.format(kind="Red track", name=red_sat))
    blue_obj = _held(state.blue_assets, blue_sat) if blue_sat else None
    if blue_sat and blue_obj is None:
        return BindOutcome(None, _NOT_HELD.format(kind="Blue asset", name=blue_sat))
    unsound = _unsound(("red track", red_obj), ("blue asset", blue_obj))
    if unsound is not None:
        return BindOutcome(None, unsound)
    red = None if red_obj is None else bound_elset("red", red_obj, now)
    blue = None if blue_obj is None else bound_elset("blue", blue_obj, now)
    if red is None and blue is None:
        return BindOutcome(None, None)
    problem = _same_object(red, blue) if red is not None and blue is not None else None
    if problem is not None:
        return BindOutcome(None, problem)
    return BindOutcome(ScenarioBinding(red=red, blue=blue), None)
