"""The condition checks a mission objective can name, evaluated against the training planning state (SPC-248).

No objective is self-certified: a condition is met only when the console's own record of the operator's work says so.
Each check reads where its tool leaves its last result in the sign-in's training state:

● object_loaded(role, side): the role's object is on the Blue (blue_assets) or Red (red_tracks) list, by catalogue
  number.
● screening_run(asset): an Asset Screening since the mission started of the role's asset, on its own element set
  (not a pasted one that merely carries its number) and at the default Max ΔV, the budget its figures are graded at
  (last_screening, recorded by routes.threat.threat_screen for this purpose).
● sweep_run(red, optional): a Threat Sweep since the mission started (last_threat_assessment), flown from the role's
  red satellite when *red* is given: by catalogue number, on the bound element set.
● intercept_run(red, blue, manoeuvring): an Intercept Engine run since the mission started with the role's red and blue
  satellites, by catalogue number on their bound element sets, and that side manoeuvring (intercept_history, which
  the mission start clears).

There is no decision_evaluated check: the Decision Engine keeps no record of an evaluation it answers at once (it sets
the state's decision_job to None), only of a sampled one run as a job, so a check on it would miss most evaluations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from spectre.data.intel import satno_from_tle
from spectre.training.quantities import Bound

#: The sides a role and the Intercept Engine's Manoeuvring satellite can name.
SIDES = ("blue", "red")



#: A screening counts only at the default Max ΔV: budgets this close are the same budget.
BUDGET_MATCH_M_S = 1e-9

def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _same_set(a: str, b: str) -> bool:
    """Whether two element sets are the same text, whatever their line ends and padding."""
    return a.split() == b.split()


def _is(tle: str | None, bound: Bound) -> bool:
    """Whether *tle* is the bound object's element set: its catalogue number and the set itself."""
    return bool(tle) and str(satno_from_tle(tle or "") or "") == bound.satno and _same_set(tle or "", bound.tle)


def _holds(objects: list[Any], satno: str) -> bool:
    return any(str(satno_from_tle(o.tle) or "") == satno for o in objects)


def object_loaded(state: Any, roles: dict[str, Bound], since: datetime, *, role: str, side: str) -> bool:
    """Whether the role's object is on the console's *side* list."""
    held = state.blue_assets if side == "blue" else state.red_tracks
    return _holds(held, roles[role].satno)


def default_budget() -> float:
    """The Max ΔV Asset Screening and the Threat Sweep open with, m/s."""
    from spectre.domain.manoeuvre_calibration import DEFAULT_SWEEP_BUDGET_M_S

    return float(DEFAULT_SWEEP_BUDGET_M_S)


def screening_of(state: Any, bound: Bound, since: datetime) -> Any | None:
    """The console's record of the last Asset Screening, when it screened *bound* since *since*, on the asset's own
    element set, at the default budget; else None."""
    record = getattr(state, "last_screening", None)
    if record is None or record.asset_satno != bound.satno or _aware(record.at) < _aware(since):
        return None
    if record.manual or abs(float(record.budget_m_s) - default_budget()) > BUDGET_MATCH_M_S:
        return None
    return record


def screening_run(state: Any, roles: dict[str, Bound], since: datetime, *, asset: str) -> bool:
    """Whether Asset Screening has screened the role's asset since the mission started, as screening_of requires."""
    return screening_of(state, roles[asset], since) is not None


def sweep_run(state: Any, roles: dict[str, Bound], since: datetime, *, red: str = "") -> bool:
    """Whether a Threat Sweep has run since the mission started, flown from the role's red satellite when *red* is
    given."""
    sweep = getattr(state, "last_threat_assessment", None)
    if sweep is None or _aware(sweep.sweep_epoch) < since:
        return False
    return not red or _is(sweep.red_tle, roles[red])


def _track_set(tracks: list[Any], name: str) -> str | None:
    return next((t.tle for t in tracks if t.stk_name == name), None)


# Five facts of one check: the state, the bound roles, the start of the attempt, and which red, blue and side the
# objective names; the last three are keyword-only so a call cannot swap them.
def intercept_run(  # noqa: PLR0913
    state: Any, roles: dict[str, Bound], since: datetime, *, red: str, blue: str, manoeuvring: str,
) -> bool:
    """Whether the Intercept Engine has run the role's red against the role's blue with *manoeuvring* burning."""
    del since   # the mission start clears the history, so every run in it is the mission's
    return any(
        r.chaser_side == manoeuvring
        and _is(_track_set(state.red_tracks, r.red_name), roles[red])
        and _is(_track_set(state.blue_assets, r.blue_name), roles[blue])
        for r in getattr(state, "intercept_history", [])
    )


@dataclass(frozen=True)
class CheckFn:
    """A registered check: its function, the arguments that name roles, and any that name a side."""

    fn: Callable[..., bool]
    roles: tuple[str, ...]
    sides: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


CHECKS: dict[str, CheckFn] = {
    "object_loaded": CheckFn(object_loaded, ("role",), ("side",)),
    "screening_run": CheckFn(screening_run, ("asset",)),
    "sweep_run": CheckFn(sweep_run, ("red",), optional=("red",)),
    "intercept_run": CheckFn(intercept_run, ("red", "blue"), ("manoeuvring",)),
}


def check_problems(spec: dict[str, Any], role_names: set[str]) -> list[str]:
    """What is wrong with a condition's *spec*: an unknown type, role or side, or an argument it does not take."""
    kind = spec.get("type")
    entry = CHECKS.get(str(kind))
    if entry is None:
        return [f"unknown check type {kind!r}"]
    args = {k: v for k, v in spec.items() if k != "type"}
    label = f"check {kind}"
    problems = [f"{label} takes no argument {k!r}" for k in args if k not in entry.roles + entry.sides]
    for name in entry.roles:
        if name not in args and name not in entry.optional:
            problems.append(f"{label} needs {name!r}")
        elif name in args and args[name] not in role_names:
            problems.append(f"{label} names unknown role {args[name]!r}")
    problems += [f"{label} needs {s!r} as blue or red" for s in entry.sides if args.get(s) not in SIDES]
    return problems


def evaluate(spec: dict[str, Any], state: Any, roles: dict[str, Bound], since: datetime) -> bool:
    """Whether the condition *spec* holds in *state* for the bound *roles*, counting work done since *since*."""
    entry = CHECKS[str(spec["type"])]
    args = {k: v for k, v in spec.items() if k != "type"}
    return entry.fn(state, roles, _aware(since), **args)
