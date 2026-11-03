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
from typing import Literal, NamedTuple

from spectre.data.intel import satno_from_tle
from spectre.domain.decision import BoundElset, ScenarioBinding
from spectre.domain.models import BlueAsset, RedTrack
from spectre.domain.provenance import tle_input
from spectre.web.elsets import elset_age
from spectre.web.planning_state import SessionState

_NOT_HELD = "{kind} {name} is no longer held in this session. Choose another or leave it unbound."
_SAME_SATNO = "Red and blue are the same object (SATNO {satno}). Bind two different objects."
_SAME_ELSET = "Red and blue hold the same element set. Bind two different objects."


class BindOutcome(NamedTuple):
    """The binding to evaluate with, or the sentence that refuses it; both None when unbound."""

    binding: ScenarioBinding | None
    problem: str | None


def bound_elset(
    side: Literal["red", "blue"], *, name: str, stk_name: str, tle: str, data_mode: str, training: bool,
    now: datetime,
) -> BoundElset:
    """One bound element set from plain values, aged at *now*.

    Plain values rather than a held object, so a later source (a sweep
    target, SPC-150) can bind through the same door.
    """
    age = elset_age(tle, now)
    return BoundElset(
        side=side, name=name, stk_name=stk_name, satno=satno_from_tle(tle), tle=tle,
        data_mode=data_mode, training=training,
        epoch=None if age is None else age.epoch,
        age_hours=None if age is None else age.hours,
        limit_hours=None if age is None else age.limit_hours,
    )


def _held[T: (RedTrack, BlueAsset)](objects: Iterable[T], stk_name: str) -> T | None:
    return next((obj for obj in objects if obj.stk_name == stk_name), None)


def _bind_one(
    side: Literal["red", "blue"], obj: RedTrack | BlueAsset, now: datetime,
) -> BoundElset:
    # The object's own provenance, read once each, never the session's mode or the target cache's.
    return bound_elset(
        side, name=obj.name, stk_name=obj.stk_name, tle=obj.tle, data_mode=obj.data_mode,
        training=obj.training, now=now,
    )


def _same_object(red: BoundElset, blue: BoundElset) -> str | None:
    """The refusal when red and blue are one object, by catalogue number or by identical element set."""
    if red.satno is not None and red.satno == blue.satno:
        return _SAME_SATNO.format(satno=red.satno)
    if tle_input("", red.tle).sha256 == tle_input("", blue.tle).sha256:
        return _SAME_ELSET
    return None


def bind_scenario(state: SessionState, red_sat: str, blue_sat: str, now: datetime) -> BindOutcome:
    """Bind the held red track *red_sat* and blue asset *blue_sat*; a blank name leaves that side unbound."""
    red_obj = _held(state.red_tracks, red_sat) if red_sat else None
    if red_sat and red_obj is None:
        return BindOutcome(None, _NOT_HELD.format(kind="Red track", name=red_sat))
    blue_obj = _held(state.blue_assets, blue_sat) if blue_sat else None
    if blue_sat and blue_obj is None:
        return BindOutcome(None, _NOT_HELD.format(kind="Blue asset", name=blue_sat))
    red = None if red_obj is None else _bind_one("red", red_obj, now)
    blue = None if blue_obj is None else _bind_one("blue", blue_obj, now)
    if red is None and blue is None:
        return BindOutcome(None, None)
    problem = _same_object(red, blue) if red is not None and blue is not None else None
    if problem is not None:
        return BindOutcome(None, problem)
    return BindOutcome(ScenarioBinding(red=red, blue=blue), None)
