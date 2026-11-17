"""SPECTRE: Orbital Watch, the mission engine (SPC-248, docs/training-game-design.md sections 4 to 9).

A mission is flown in the real console against real catalogue objects. Its file (config/missions.yaml) binds roles to
catalogue numbers, names the quantities to compute, and types each objective: a *condition* the console's own record
must show (spectre.training.mission_checks), an *answer* checked against a computed quantity within a tolerance, or a
*choice* among options an engine produced. No figure is typed in the file and no objective is self-certified.

Loading validates everything and fails loudly: an unknown role, quantity function, check type or placeholder, a figure
typed into text, a control an objective names but its words do not, an alert over 15 words or a brief line over 25.
Whether each spotlight selector and named control exists in the rendered console is checked by the mission harness
(tests/browser/test_mission_harness.py), which plays every mission.

At start the engine binds each role to the element set the training state holds for it (the bundled SYNTHETIC set, or
the live one once the operator has connected UDL in the training frame), sets the mission clock, applies any exercise
inject, and computes every quantity, which is stored with the attempt so scoring uses exactly those figures.

The mission clock is now when every bound set passes the staleness check at now, else the newest epoch among them
(**Claude's call**, design section 4). It becomes the training state's scenario time, so the element cards and the
Intercept Engine read it.
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from spectre.training import exercise_inject, mission_checks, quantities
from spectre.training.quantities import QUANTITIES, Bound, Context

_CONFIG_PATH = Path(__file__).parent / "config" / "missions.yaml"
_WATCHLIST_PATH = Path(__file__).resolve().parents[1] / "data" / "hrr_default.json"

KINDS = ("condition", "answer", "choice")
UNITS = ("deg", "km", "m/s", "h", "min", "count")
#: The red countries, as the console's Threat Sweep and Asset Screening split the watchlist.
RED_COUNTRIES = frozenset({"CHN", "RUS", "IRN", "PRK"})
#: Placeholders every text may use besides roles and quantities.
BUILTINS = ("clock",)
#: The axes of an inject burn, in the order the file gives them.
_BURN_AXES = ("radial", "along-track", "cross-track")
MAX_ALERT_WORDS = 15
MAX_BRIEF_LINES = 3
MAX_BRIEF_WORDS = 25
#: How long the scenario window runs past the mission clock.
WINDOW_HOURS = 72
#: A figure: a digit that does not continue a word, so "SGP4" is a name and "12" a figure.
_DIGIT = re.compile(r"(?<![A-Za-z])\d")
_FORMATTER = string.Formatter()


class MissionError(ValueError):
    """The mission file is wrong; the message lists every problem found."""


# ── The schema ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    blurb: str
    rank_required: int


@dataclass(frozen=True)
class RoleSpec:
    """A role: a fixed catalogue number, or the watchlist object of *side* nearest another role at the clock."""

    name: str
    side: str
    satno: str = ""
    nearest_to: str = ""


@dataclass(frozen=True)
class InjectSpec:
    role: str
    burn_m_s: tuple[float, float, float]
    at: str


@dataclass(frozen=True)
class QuantitySpec:
    name: str
    fn: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Hint:
    say: str
    spotlight: str
    cost: int


@dataclass(frozen=True)
class Objective:
    id: str
    kind: str
    text: str
    points: int
    check: dict[str, Any] | None = None
    quantity: str = ""
    tolerance: float = 0.0
    unit: str = ""
    options_from: str = ""
    hint: Hint | None = None
    controls: tuple[str, ...] = ()
    explain: str = ""


@dataclass(frozen=True)
class Mission:
    id: str
    chapter: str
    title: str
    par_seconds: int
    alert: str
    roles: tuple[RoleSpec, ...]
    quantities: tuple[QuantitySpec, ...]
    brief: tuple[str, ...]
    objectives: tuple[Objective, ...]
    debrief_best: str
    debrief_why: str
    first_action: str
    first_controls: tuple[str, ...] = ()
    inject: InjectSpec | None = None
    needs_udl: bool = False

    def objective(self, objective_id: str) -> Objective | None:
        return next((o for o in self.objectives if o.id == objective_id), None)

    def role(self, name: str) -> RoleSpec:
        return next(r for r in self.roles if r.name == name)


@dataclass(frozen=True)
class Campaign:
    chapters: tuple[Chapter, ...]
    missions: tuple[Mission, ...]

    def mission(self, mission_id: str) -> Mission | None:
        return next((m for m in self.missions if m.id == mission_id), None)

    def chapter(self, chapter_id: str) -> Chapter | None:
        return next((c for c in self.chapters if c.id == chapter_id), None)

    def in_chapter(self, chapter_id: str) -> list[Mission]:
        return [m for m in self.missions if m.chapter == chapter_id]


# ── Parsing ──────────────────────────────────────────────────────────────────


def _hint(raw: Any) -> Hint | None:
    if not raw:
        return None
    return Hint(say=str(raw.get("say", "")), spotlight=str(raw.get("spotlight", "")), cost=int(raw.get("cost", 0)))


def _objective(raw: dict[str, Any]) -> Objective:
    return Objective(
        id=str(raw.get("id", "")), kind=str(raw.get("kind", "")), text=str(raw.get("text", "")),
        points=int(raw.get("points", 0)), check=raw.get("check"), quantity=str(raw.get("quantity", "")),
        tolerance=float(raw.get("tolerance", 0.0)), unit=str(raw.get("unit", "")),
        options_from=str(raw.get("options_from", "")), hint=_hint(raw.get("hint")),
        controls=tuple(str(c) for c in raw.get("controls", [])), explain=str(raw.get("explain", "")),
    )


def _role(name: str, raw: dict[str, Any]) -> RoleSpec:
    return RoleSpec(name=name, side=str(raw.get("side", "")), satno=str(raw.get("satno", "")),
                    nearest_to=str(raw.get("nearest_to", "")))


def _inject(raw: Any) -> InjectSpec | None:
    if not raw:
        return None
    burn = tuple(float(x) for x in raw.get("burn_m_s", []))
    if len(burn) != len(_BURN_AXES):
        raise MissionError(f"an inject burn needs three components, got {len(burn)}")
    return InjectSpec(role=str(raw.get("role", "")), burn_m_s=(burn[0], burn[1], burn[2]), at=str(raw.get("at", "")))


def _mission(raw: dict[str, Any]) -> Mission:
    debrief = raw.get("debrief") or {}
    first = raw.get("first_action") or {}
    return Mission(
        id=str(raw.get("id", "")), chapter=str(raw.get("chapter", "")), title=str(raw.get("title", "")),
        par_seconds=int(raw.get("par_seconds", 0)), alert=str(raw.get("alert", "")),
        roles=tuple(_role(n, r or {}) for n, r in (raw.get("roles") or {}).items()),
        quantities=tuple(QuantitySpec(n, str((q or {}).get("fn", "")), dict((q or {}).get("args") or {}))
                         for n, q in (raw.get("quantities") or {}).items()),
        brief=tuple(str(b) for b in raw.get("brief") or []),
        objectives=tuple(_objective(o or {}) for o in raw.get("objectives") or []),
        debrief_best=str(debrief.get("best", "")), debrief_why=str(debrief.get("why", "")),
        first_action=str(first.get("say", "")), first_controls=tuple(str(c) for c in first.get("controls", [])),
        inject=_inject(raw.get("inject")), needs_udl=bool(raw.get("needs_udl", False)),
    )


def parse(raw: dict[str, Any]) -> Campaign:
    """The campaign in *raw* (the YAML's mapping), validated: MissionError lists every problem."""
    chapters = tuple(Chapter(str(c.get("id", "")), str(c.get("title", "")), str(c.get("blurb", "")),
                             int(c.get("rank_required", 1))) for c in raw.get("chapters") or [])
    campaign = Campaign(chapters, tuple(_mission(m or {}) for m in raw.get("missions") or []))
    problems = validate(campaign)
    if problems:
        raise MissionError("missions.yaml: " + "; ".join(problems))
    return campaign


@lru_cache(maxsize=1)
def load_campaign() -> Campaign:
    """The campaign in config/missions.yaml, validated once and cached."""
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        return parse(yaml.safe_load(fh) or {})


# ── Validation ───────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def watchlist() -> dict[str, dict[str, Any]]:
    """The bundled watchlist by catalogue number: the objects every mission role must be one of."""
    with open(_WATCHLIST_PATH, encoding="utf-8") as fh:
        messages = json.load(fh)
    return {str(o["satNo"]): o for message in messages for o in message.get("msgBody", [])}


def side_of(country: str) -> str:
    """The side the console gives an object of *country*."""
    return "red" if country.strip().upper() in RED_COUNTRIES else "blue"


def _role_problems(mission: Mission) -> list[str]:
    names = {r.name for r in mission.roles}
    problems: list[str] = []
    for role in mission.roles:
        where = f"{mission.id} role {role.name}"
        if role.side not in mission_checks.SIDES:
            problems.append(f"{where}: side must be blue or red")
        if bool(role.satno) == bool(role.nearest_to):
            problems.append(f"{where}: give a satno or nearest_to, one of them")
        elif role.satno and role.satno not in watchlist():
            problems.append(f"{where}: {role.satno} is not a catalogue number on the watchlist")
        elif role.satno and side_of(str(watchlist()[role.satno].get("country", ""))) != role.side:
            problems.append(f"{where}: {role.satno} is not {role.side} on the watchlist")
        elif role.nearest_to and (role.nearest_to not in names or role.nearest_to == role.name):
            problems.append(f"{where}: nearest_to names no other role")
    return problems


def _quantity_problems(mission: Mission) -> list[str]:
    names = {r.name for r in mission.roles}
    problems: list[str] = []
    for q in mission.quantities:
        where = f"{mission.id} quantity {q.name}"
        entry = QUANTITIES.get(q.fn)
        if entry is None:
            problems.append(f"{where}: unknown function {q.fn!r}")
            continue
        for arg, value in q.args.items():
            if arg in entry.roles and value not in names:
                problems.append(f"{where}: {arg} names unknown role {value!r}")
            elif arg in entry.constants and not isinstance(value, int | float):
                problems.append(f"{where}: {arg} must be a number")
            elif arg not in entry.roles + entry.constants:
                problems.append(f"{where}: {q.fn} takes no argument {arg!r}")
        problems += [f"{where}: {q.fn} needs {r!r}" for r in entry.roles if r not in q.args]
    return problems


def _kind_of(mission: Mission, quantity: str) -> str:
    spec = next((q for q in mission.quantities if q.name == quantity), None)
    return QUANTITIES[spec.fn].kind if spec is not None and spec.fn in QUANTITIES else ""


def _objective_problems(mission: Mission, objective: Objective) -> list[str]:
    where = f"{mission.id} objective {objective.id}"
    problems: list[str] = []
    if objective.kind not in KINDS:
        return [f"{where}: kind must be one of {', '.join(KINDS)}"]
    if objective.points <= 0:
        problems.append(f"{where}: points must be positive")
    if objective.kind == "condition":
        problems += [f"{where}: {p}" for p in
                     mission_checks.check_problems(objective.check or {}, {r.name for r in mission.roles})]
    elif objective.kind == "answer":
        if _kind_of(mission, objective.quantity) != "number":
            problems.append(f"{where}: quantity {objective.quantity!r} is not a number this mission computes")
        if objective.tolerance <= 0 or objective.unit not in UNITS:
            problems.append(f"{where}: an answer needs a positive tolerance and a unit of {', '.join(UNITS)}")
    elif _kind_of(mission, objective.options_from) != "options":
        problems.append(f"{where}: options_from {objective.options_from!r} is not an options quantity")
    problems += _screened_problems(mission, objective, where)
    if objective.hint is not None and (not objective.hint.spotlight or objective.hint.cost < 0):
        problems.append(f"{where}: a hint needs a spotlight and a cost of zero or more")
    words = f"{objective.text} {objective.hint.say if objective.hint else ''}"
    problems += [f"{where}: names control {c!r} its text and hint do not" for c in objective.controls if c not in words]
    return problems


def _screened_problems(mission: Mission, objective: Objective, where: str) -> list[str]:
    """A question read from the operator's screening needs a screening_run condition on that asset before it."""
    asset = screened_asset(mission, objective.quantity or objective.options_from)
    if not asset:
        return []
    earlier = mission.objectives[: mission.objectives.index(objective)]
    if any(o.check and o.check.get("type") == "screening_run" and o.check.get("asset") == asset for o in earlier):
        return []
    return [f"{where}: reads the screening of {asset!r}, so a screening_run of it must come first"]


def _texts(mission: Mission) -> list[tuple[str, str]]:
    """Every text of *mission* that takes placeholders, with where it is."""
    texts = [("alert", mission.alert), ("first_action", mission.first_action),
             ("debrief.best", mission.debrief_best), ("debrief.why", mission.debrief_why)]
    texts += [(f"brief line {i + 1}", line) for i, line in enumerate(mission.brief)]
    for o in mission.objectives:
        name = f"objective {o.id}"
        texts += [(name, o.text), (f"{name} explain", o.explain)]
        if o.hint is not None:
            texts.append((f"{name} hint", o.hint.say))
    return texts


def _fields(text: str) -> list[tuple[str, str, str]]:
    """The literal text, field name and format spec of each placeholder in *text*."""
    return [(lit, name or "", spec or "") for lit, name, spec, _ in _FORMATTER.parse(text) if name is not None
            or lit]


def _text_problems(mission: Mission) -> list[str]:
    allowed = {r.name for r in mission.roles} | {q.name for q in mission.quantities} | set(BUILTINS)
    # An options quantity has no single value to print, and a screened one none until the operator screens.
    options = {q.name for q in mission.quantities if _kind_of(mission, q.name) == "options"} | screened_names(mission)
    problems: list[str] = []
    for where, text in _texts(mission):
        try:
            parts = _fields(text)
        except ValueError as exc:
            problems.append(f"{mission.id} {where}: {exc}")
            continue
        for literal, name, _ in parts:
            if _DIGIT.search(literal):
                problems.append(f"{mission.id} {where}: a figure is typed in the text ({literal.strip()!r})")
            if name and (name not in allowed or name in options):
                problems.append(f"{mission.id} {where}: unknown placeholder {{{name}}}")
    return problems


def _length_problems(mission: Mission) -> list[str]:
    problems = []
    if len(mission.alert.split()) > MAX_ALERT_WORDS:
        problems.append(f"{mission.id} alert: over {MAX_ALERT_WORDS} words")
    if len(mission.brief) > MAX_BRIEF_LINES:
        problems.append(f"{mission.id} brief: over {MAX_BRIEF_LINES} lines")
    problems += [f"{mission.id} brief line {i + 1}: over {MAX_BRIEF_WORDS} words"
                 for i, line in enumerate(mission.brief) if len(line.split()) > MAX_BRIEF_WORDS]
    return problems


def _inject_problems(mission: Mission) -> list[str]:
    inject = mission.inject
    if inject is None:
        return []
    problems = []
    if inject.role not in {r.name for r in mission.roles}:
        problems.append(f"{mission.id} inject: unknown role {inject.role!r}")
    if not exercise_inject.valid_at(inject.at):
        problems.append(f"{mission.id} inject: at must be start, the only burn time handled")
    return problems


def _mission_problems(mission: Mission, campaign: Campaign) -> list[str]:
    problems = []
    if campaign.chapter(mission.chapter) is None:
        problems.append(f"{mission.id}: unknown chapter {mission.chapter!r}")
    if mission.par_seconds <= 0 or not mission.objectives or not mission.title:
        problems.append(f"{mission.id}: needs a title, a positive par_seconds and objectives")
    ids = [o.id for o in mission.objectives]
    if len(ids) != len(set(ids)):
        problems.append(f"{mission.id}: objective ids repeat")
    problems += _role_problems(mission) + _quantity_problems(mission) + _text_problems(mission)
    problems += _length_problems(mission) + _inject_problems(mission)
    for objective in mission.objectives:
        problems += _objective_problems(mission, objective)
    return problems


def validate(campaign: Campaign) -> list[str]:
    """Every problem in *campaign*; empty when it loads."""
    problems: list[str] = []
    for kind, ids in (("chapter", [c.id for c in campaign.chapters]), ("mission", [m.id for m in campaign.missions])):
        if len(ids) != len(set(ids)):
            problems.append(f"{kind} ids repeat")
    for mission in campaign.missions:
        problems += _mission_problems(mission, campaign)
    return problems


# ── Binding, the clock and the inject ────────────────────────────────────────


class StartError(RuntimeError):
    """A mission cannot start on the data the training state holds; the message says why, for the operator."""


def _held(state: Any, satno: str) -> tuple[str, str, str, str] | None:
    """The watchlist object *satno* in *state*: its name, country, element set and data mode, or None."""
    entry = next((o for o in state.hrr_objects if str(o.get("satno") or "").strip() == satno), None)
    tle = state.hrr_tle_cache.get(satno)
    if entry is None or not tle:
        return None
    name = str(entry.get("name") or satno).strip()
    return name, str(entry.get("country") or ""), tle, str(state.hrr_tle_data_mode.get(satno, "REAL"))


def _bind_fixed(spec: RoleSpec, state: Any) -> Bound:
    from spectre.web.elsets import refused

    held = _held(state, spec.satno)
    if held is None:
        raise StartError(f"The watchlist holds no element set for {spec.satno}.")
    name, country, tle, mode = held
    refusal = refused(name, tle)
    if refusal is not None:
        raise StartError(refusal)
    return Bound(spec.name, spec.satno, name, spec.side, tle, mode, country)


def _bind_nearest(spec: RoleSpec, reference: Bound, state: Any, at: datetime, taken: set[str]) -> Bound:
    """The watchlist object on *spec*'s side, in *reference*'s regime, nearest it at *at*."""
    regime = quantities.regime_of(reference.tle)
    best: tuple[float, Bound] | None = None
    for obj in state.hrr_objects:
        satno = str(obj.get("satno") or "").strip()
        held = _held(state, satno) if satno and satno not in taken else None
        if held is None or side_of(held[1]) != spec.side or quantities.regime_of(held[2]) != regime:
            continue
        distance = quantities.range_at(reference.tle, held[2], at)
        if best is None or distance < best[0]:
            best = (distance, Bound(spec.name, satno, held[0], spec.side, held[2], held[3], held[1]))
    if best is None:
        raise StartError(f"No {spec.side} watchlist object shares {reference.name}'s regime.")
    return best[1]


def mission_clock(bound: list[Bound], now: datetime) -> datetime:
    """Now, when every bound set passes the staleness check at now; else the newest epoch among them."""
    from spectre.web.elsets import elset_age

    ages = [elset_age(b.tle, now) for b in bound]
    if all(a is not None and not a.stale and not a.future for a in ages):
        return now.replace(microsecond=0)
    epochs = [a.epoch for a in ages if a is not None]
    if not epochs:
        raise StartError("No bound element set has a readable epoch.")
    return max(epochs).astimezone(UTC)


def bind(mission: Mission, state: Any, now: datetime) -> tuple[dict[str, Bound], datetime]:
    """Each role bound to the element set *state* holds for it, and the mission clock they give."""
    roles = {r.name: _bind_fixed(r, state) for r in mission.roles if r.satno}
    clock = mission_clock(list(roles.values()), now)
    for _ in range(2):   # a nearest object's own set can move the clock; the second pass settles on it
        taken = {b.satno for b in roles.values() if b.role not in {r.name for r in mission.roles if r.nearest_to}}
        for spec in (r for r in mission.roles if r.nearest_to):
            roles[spec.name] = _bind_nearest(spec, roles[spec.nearest_to], state, clock, taken)
        settled = mission_clock(list(roles.values()), now)
        if settled == clock:
            break
        clock = settled
    return roles, clock


def apply_inject(mission: Mission, roles: dict[str, Bound], clock: datetime, now: datetime) -> tuple[
        dict[str, Bound], datetime, str | None]:
    """The roles with the mission's exercise inject applied, the clock it gives, and the EXERCISE line."""
    spec = mission.inject
    if spec is None:
        return roles, clock, None
    target = roles[spec.role]
    try:
        done = exercise_inject.inject(target.tle, exercise_inject.inject_time(clock, spec.at), spec.burn_m_s)
    except exercise_inject.InjectError as exc:
        raise StartError(f"The exercise inject could not be applied to {target.name}: {exc}.") from exc
    roles = {**roles, spec.role: Bound(target.role, target.satno, target.name, target.side, done.tle, "EXERCISE",
                                       target.country)}
    radial, along, cross = spec.burn_m_s
    line = (f"EXERCISE: {target.name} burns at {done.epoch:%d %b %H:%M} UTC: {radial:+.2f} m/s radial, "
            f"{along:+.2f} m/s along-track, {cross:+.2f} m/s cross-track, on the element set held for it "
            f"({target.data_mode}). Not observed behaviour.")
    return roles, mission_clock(list(roles.values()), now), line


def screened_names(mission: Mission) -> set[str]:
    """The mission's quantities read from the operator's own screening rather than computed at start."""
    return {q.name for q in mission.quantities if q.fn in QUANTITIES and QUANTITIES[q.fn].screened}


async def compute_all(mission: Mission, ctx: Context) -> dict[str, Any]:
    """Every quantity the mission names, in the order it names them; a screened one is None until the operator's
    screening resolves it (resolve_screened)."""
    values: dict[str, Any] = {}
    screened = screened_names(mission)
    for q in mission.quantities:
        if q.name in screened:
            values[q.name] = None
            continue
        try:
            values[q.name] = await quantities.compute(ctx, q.fn, q.args)
        except (quantities.QuantityError, RuntimeError, ValueError) as exc:
            raise StartError(f"{mission.title} cannot start: {exc}") from exc
    return values


def resolve_screened(mission: Mission, values: dict[str, Any], roles: dict[str, Bound],
                     screenings: dict[str, Any]) -> dict[str, Any]:
    """*values* with every screened quantity read from the operator's screening of its asset, where one is held.

    *screenings* holds the operator's latest qualifying screening of each asset, by catalogue number, as
    quantities.Screened.as_json gives it; a quantity whose asset has none stays None.
    """
    resolved = dict(values)
    for q in mission.quantities:
        entry = QUANTITIES.get(q.fn)
        if entry is None or not entry.screened:
            continue
        held = screenings.get(roles[q.args[entry.screened]].satno)
        resolved[q.name] = None if held is None else quantities.from_screening(
            q.fn, q.args, quantities.Screened.from_json(held), roles)
    return resolved


def screened_asset(mission: Mission, quantity: str) -> str:
    """The role whose screening a screened quantity is read from, or "" for a quantity computed at start."""
    spec = next((q for q in mission.quantities if q.name == quantity), None)
    entry = QUANTITIES.get(spec.fn) if spec is not None else None
    return str(spec.args[entry.screened]) if spec is not None and entry is not None and entry.screened else ""


# ── Texts ────────────────────────────────────────────────────────────────────


def clock_text(clock: datetime) -> str:
    return clock.astimezone(UTC).strftime("%d %b %Y %H:%M UTC")


def fill(text: str, roles: dict[str, Any], values: dict[str, Any], clock: datetime) -> str:
    """*text* with each placeholder replaced: a role by its object's name, a quantity by its value, {clock}."""
    mapping = {**values, **{name: bound["name"] if isinstance(bound, dict) else bound.name
                            for name, bound in roles.items()}, "clock": clock_text(clock)}
    return text.format_map(mapping)


def teaser(text: str, names: dict[str, str]) -> str:
    """*text* before a start: each placeholder in *names* replaced, every other one, not yet computed, by "…"."""
    return "".join(literal + (names.get(name, "…") if name is not None else "")
                   for literal, name, _, _ in _FORMATTER.parse(text))


# ── Answers ──────────────────────────────────────────────────────────────────

_UNIT_WORDS: dict[str, tuple[str, ...]] = {
    "deg": ("degrees", "degree", "deg", "°"),
    "km": ("kilometres", "kilometers", "km"),
    "m/s": ("m/s", "mps"),
    "h": ("hours", "hour", "hrs", "hr", "h"),
    "min": ("minutes", "minute", "mins", "min"),
    "count": ("objects", "object"),
}
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


def _commas(text: str) -> str:
    """A single comma between digits is a decimal comma ("79,72"); any other comma separates thousands."""
    if text.count(",") == 1 and "." not in text and re.search(r"\d,\d", text):
        return text.replace(",", ".")
    return text.replace(",", "")


#: The readings an answer can plausibly be, by the quantity it is checked against, else by its unit: one outside is
#: refused as unreadable and not spent, rather than scored as a final miss.
_PLAUSIBLE_BY_FN: dict[str, tuple[float, float]] = {
    "subsat_longitude": (-180.0, 180.0), "inclination_deg": (0.0, 180.0), "period_min": (0.0, 100_000.0),
}
_PLAUSIBLE_BY_UNIT: dict[str, tuple[float, float]] = {
    "deg": (-360.0, 360.0), "km": (0.0, 1e6), "m/s": (-1e5, 1e5), "h": (0.0, 1e4), "min": (0.0, 1e5),
    "count": (0.0, 1e4),
}


def plausible(value: float, unit: str, fn: str = "") -> bool:
    """Whether *value* is a reading the quantity could have: a longitude within ±180, an inclination 0 to 180..."""
    low, high = _PLAUSIBLE_BY_FN.get(fn) or _PLAUSIBLE_BY_UNIT.get(unit, (-float("inf"), float("inf")))
    return low <= value <= high


def parse_answer(given: str, unit: str) -> float | None:
    """The number in *given*, its unit word stripped, a trailing E or W read as a hemisphere for degrees, a single
    decimal comma read as a point; or None."""
    text = _commas(given.strip().lower())
    sign = 1.0
    if unit == "deg" and text[-1:] in ("e", "w"):
        sign = -1.0 if text.endswith("w") else 1.0
        text = text[:-1].strip()
    for word in _UNIT_WORDS.get(unit, ()):
        if text.endswith(word):
            text = text[: -len(word)].strip()
            break
    if not _NUMBER.fullmatch(text):
        return None
    return sign * float(text)


def answer_error(value: float, truth: float, unit: str) -> float:
    """How far *value* is from *truth*: the shorter way round for degrees."""
    if unit == "deg":
        return abs((value - truth + 180.0) % 360.0 - 180.0)
    return abs(value - truth)


def accepted_text(value: Any, unit: str, fn: str = "") -> str:
    """The computed answer as the console shows it: a longitude with its hemisphere, another angle in degrees."""
    if fn == "subsat_longitude":
        from spectre.web.element_card import longitude_text

        return longitude_text(float(value))
    if unit == "deg":
        return f"{float(value):.2f}°"
    if unit == "count":
        return str(int(value))
    return f"{float(value):.2f} {unit}"


# ── Stars ────────────────────────────────────────────────────────────────────


@dataclass
class StarReason:
    star: int
    earned: bool
    why: str


@dataclass
class Outcome:
    stars: int
    reasons: list[StarReason] = field(default_factory=list)


def stars_for(all_met: bool, seconds: int, par: int, hints: int, all_best: bool) -> Outcome:
    """Up to three stars: one for every objective met, one within par, one with no hints and every answer best."""
    first = StarReason(1, all_met, "Every objective met." if all_met else "Not every objective was met.")
    within = all_met and seconds <= par
    second = StarReason(2, within, f"Finished in {mmss(seconds)} against a par of {mmss(par)}." if all_met
                        else "Needs every objective met first.")
    best = all_met and hints == 0 and all_best
    third = StarReason(3, best, "No hints, and every answer within half its tolerance or the best choice."
                       if best else _why_not_best(all_met, hints))
    reasons = [first, second, third]
    return Outcome(sum(1 for r in reasons if r.earned), reasons)


def _why_not_best(all_met: bool, hints: int) -> str:
    if not all_met:
        return "Needs every objective met first."
    if hints:
        return hints_words(hints) + "."
    return "An answer was outside half its tolerance."


def mmss(seconds: int) -> str:
    """A duration as minutes and seconds: "0:13", "2:30", "12:05"."""
    minutes, rest = divmod(max(0, int(seconds)), 60)
    return f"{minutes}:{rest:02d}"


def hints_words(hints: int) -> str:
    """ "1 hint used", "2 hints used"."""
    return f"{hints} hint used" if hints == 1 else f"{hints} hints used"


def miss_band(error: float, tolerance: float) -> str:
    """How far a missed answer was, in words only: "close" within three times its tolerance, else "far"."""
    return "close" if error <= 3.0 * tolerance else "far"


def window(clock: datetime) -> tuple[datetime, datetime]:
    """The scenario window a mission sets: the clock and WINDOW_HOURS after it."""
    return clock, clock + timedelta(hours=WINDOW_HOURS)
