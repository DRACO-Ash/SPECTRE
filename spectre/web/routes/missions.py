"""SPECTRE: Orbital Watch, the mission routes (SPC-248), under /training/m.

Every route serves from the sign-in's training planning state (spectre.web.planning_state.get_training_state) and the
account's training tables; nothing reads or writes the operational state. A mission start binds the mission's roles
to the element sets the training state holds, sets the mission clock as the console's scenario time, applies any
exercise inject, computes every quantity, and puts the bound objects on the training Blue and Red lists, tagged as
training objects. Finishing or abandoning takes them off again and puts back any set the inject replaced.

Each condition is evaluated against the training state whenever the HUD is asked for, and latched once met: nothing
is self-certified. A question read from Asset Screening is graded against the operator's own latest screening of that
asset, kept on the attempt as the console recorded it. Every write to an attempt is a compare and set on its version
(settle), so requests in flight at once never write over each other, and a finish is a conditional end. An answer is final once given, and a choice once made (**Claude's call**): a second try would turn
a four-option choice into a certainty. Every response that changes progress raises training-changed for the page;
a start, finish or abandon also raises training-console-stale, since the console's lists and scenario time changed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import weakref
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.data.intel import get_intel
from spectre.domain.models import BlueAsset, RedTrack
from spectre.training import missions as engine
from spectre.training import quantities
from spectre.training.gamification import award_points, get_config, next_level_gates
from spectre.training.mission_checks import BUDGET_MATCH_M_S, evaluate
from spectre.training.missions import Campaign, Mission, Objective, StartError, load_campaign
from spectre.training.models import MissionAttempt, TrainingProgress
from spectre.training.quantities import Bound, Context
from spectre.web.auth import require_login
from spectre.web.database import get_db
from spectre.web.deps import render
from spectre.web.models import User
from spectre.web.planning_state import SessionState, get_training_state
from spectre.web.routes.training import _apply_level_ups, _get_or_create_progress, _remove_training_objects

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training/m", tags=["training"])

CAMPAIGN_TEMPLATE = "partials/mission_campaign.html"
ALERT_TEMPLATE = "partials/mission_alert.html"
HUD_TEMPLATE = "partials/mission_hud.html"
DEBRIEF_TEMPLATE = "partials/mission_debrief.html"

#: The events a mission response raises (routes.training): training-changed refreshes the page's progress panels and
#: the HUD; training-console-stale reloads the console frame, whose lists and scenario time a start or an end changed.
CHANGED = "training-changed"
CHANGED_AND_STALE = "training-changed, training-console-stale"
#: The gamification action a first pass of a mission is paid as, through the existing path (pass-only).
MISSION_PAY_ACTION = "scenario_completed"
_ANSWER_UNITS_SHOWN = {"count": None}
#: How a refused answer names what it wanted.
_UNIT_WORDS = {"deg": "number of degrees", "km": "distance in km", "m/s": "speed in m/s", "h": "number of hours",
               "min": "number of minutes", "count": "count"}

CurrentUser = Annotated[User, Depends(require_login)]
Db = Annotated[AsyncSession, Depends(get_db)]


def _changed(response: HTMLResponse, *, stale: bool = False) -> HTMLResponse:
    response.headers["HX-Trigger"] = CHANGED_AND_STALE if stale else CHANGED
    return response


def _refused(message: str, status: int) -> HTMLResponse:
    from html import escape

    return HTMLResponse(f'<p class="error-msg" role="alert">{escape(message)}</p>', status_code=status)


# ── Results and locks ────────────────────────────────────────────────────────


@dataclasses.dataclass
class Best:
    stars: int = 0
    points: int = 0
    attempts: int = 0


async def _bests(db: AsyncSession, user_id: int) -> dict[str, Best]:
    """Each mission's best stars and points, and how many attempts were finished, for *user_id*."""
    rows = (await db.execute(select(MissionAttempt).where(
        MissionAttempt.user_id == user_id, MissionAttempt.status == "finished"))).scalars().all()
    bests: dict[str, Best] = {}
    for row in rows:
        best = bests.setdefault(row.mission_id, Best())
        best.stars, best.points = max(best.stars, row.stars), max(best.points, row.score)
        best.attempts += 1
    return bests


def _chapter_lock(campaign: Campaign, chapter_id: str, progress: TrainingProgress) -> str:
    """Why *chapter_id* is locked for *progress*, or "" when it is open."""
    chapter = campaign.chapter(chapter_id)
    if chapter is None or progress.current_level >= chapter.rank_required:
        return ""
    level = get_config().level_def(chapter.rank_required)
    title = level.title if level else f"Level {chapter.rank_required}"
    if chapter.rank_required == progress.current_level + 1:
        unmet = [g.label for g in next_level_gates(progress) if not g.met]
        return f"Reach {title}: " + "; ".join(unmet) + "."
    return f"Reach {title} (Level {chapter.rank_required})."


def mission_lock(campaign: Campaign, mission: Mission, progress: TrainingProgress, bests: dict[str, Best]) -> str:
    """Why *mission* is locked, or "": its chapter's rank, then a star on the mission before it in the chapter."""
    reason = _chapter_lock(campaign, mission.chapter, progress)
    if reason:
        return reason
    order = campaign.in_chapter(mission.chapter)
    place = order.index(mission)
    if place and bests.get(order[place - 1].id, Best()).stars == 0:
        return f"Earn a star on {order[place - 1].title} first."
    return ""


def _teaser(mission: Mission) -> str:
    """The mission's alert line before it starts: fixed roles by name, the rest unnamed, figures not yet computed."""
    names: dict[str, str] = {}
    for role in mission.roles:
        entry = engine.watchlist().get(role.satno, {})
        names[role.name] = str(entry.get("commonName") or f"the nearest {role.side} asset")
    return engine.teaser(mission.alert, names)


def _rank(progress: TrainingProgress) -> dict[str, Any]:
    cfg = get_config()
    level = cfg.level_def(progress.current_level)
    following = cfg.level_def(progress.current_level + 1)
    return {
        "level": progress.current_level,
        "title": level.title if level else "",
        "points": progress.total_points,
        "next_title": following.title if following else "",
        "next_conditions": [g.label for g in next_level_gates(progress)],
    }


def campaign_context(campaign: Campaign, progress: TrainingProgress, bests: dict[str, Best]) -> dict[str, Any]:
    """The campaign page's context (the contract's mission_campaign.html keys)."""
    chapters = []
    for chapter in campaign.chapters:
        reason = _chapter_lock(campaign, chapter.id, progress)
        chapters.append({
            "id": chapter.id, "title": chapter.title, "blurb": chapter.blurb, "rank_required": chapter.rank_required,
            "locked": bool(reason), "lock_reason": reason,
            "missions": [_mission_card(campaign, m, progress, bests) for m in campaign.in_chapter(chapter.id)],
        })
    return {"chapters": chapters, "rank": _rank(progress), "medals_count": 0}


def _mission_card(campaign: Campaign, mission: Mission, progress: TrainingProgress, bests: dict[str, Best]) -> dict[
        str, Any]:
    best = bests.get(mission.id, Best())
    reason = mission_lock(campaign, mission, progress, bests)
    return {
        "id": mission.id, "title": mission.title, "alert_line": _teaser(mission), "par_seconds": mission.par_seconds,
        "stars": best.stars, "best_points": best.points, "best_score": best.points, "attempts": best.attempts,
        "locked": bool(reason), "lock_reason": reason, "needs_udl": mission.needs_udl,
    }


# ── The attempt and the training state ──────────────────────────────────────

#: How many times a write that lost a race to another re-reads the attempt and tries again.
_RETRIES = 32
#: One lock per sign-in around the routes that change its training state (start, finish, abandon), so two of them
#: never interleave their changes to the lists and the scenario time. The training state lives in this process, so
#: an in-process lock is the one that guards it; the database's one-open-attempt index guards the rows.
_STATE_LOCKS: weakref.WeakValueDictionary[Any, asyncio.Lock] = weakref.WeakValueDictionary()
_NOT_RUNNING = "This mission is not running: start it from the campaign."
#: The placeholder error for a question read from a screening the operator has not run, worded at the HUD.
_NOT_YET = "Not yet answerable."


def _state_lock(user: User) -> asyncio.Lock:
    key = user.session_key
    lock = _STATE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _STATE_LOCKS[key] = lock
    return lock


async def _read(db: AsyncSession, attempt_id: int) -> MissionAttempt:
    """The attempt as the database holds it now, not as this session last saw it."""
    query = select(MissionAttempt).where(MissionAttempt.id == attempt_id).execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one()


async def _open(db: AsyncSession, user: User, mission_id: str | None = None) -> MissionAttempt | None:
    query = select(MissionAttempt).where(MissionAttempt.user_id == user.id, MissionAttempt.status == "open")
    if mission_id is not None:
        query = query.where(MissionAttempt.mission_id == mission_id)
    query = query.order_by(MissionAttempt.id.desc()).limit(1).execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one_or_none()


def _bound(attempt: MissionAttempt) -> dict[str, Bound]:
    return {name: Bound(**fields) for name, fields in attempt.roles.items()}


def _started(attempt: MissionAttempt) -> datetime:
    started = attempt.started_at
    return started if started.tzinfo else started.replace(tzinfo=UTC)


def _watched(attempt: MissionAttempt) -> datetime:
    """When the mission's time started: the watch taken, or the start when the HUD was never asked for."""
    moment = attempt.watched_at or attempt.started_at
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def _take_watch(db: AsyncSession, attempt: MissionAttempt) -> MissionAttempt:
    """Start the mission's time at the first HUD, once: a conditional write, so two first HUDs agree."""
    if attempt.watched_at is not None:
        return attempt
    await db.execute(update(MissionAttempt).where(
        MissionAttempt.id == attempt.id, MissionAttempt.watched_at.is_(None),
    ).values(watched_at=datetime.now(UTC)))
    await db.commit()
    return await _read(db, attempt.id)


def _clock(attempt: MissionAttempt) -> datetime:
    return datetime.fromisoformat(attempt.clock_iso)


@dataclasses.dataclass
class Draft:
    """A change to an open attempt, made on a fresh read and written only if no other write came first."""

    states: dict[str, Any]
    values: dict[str, Any]
    extra: dict[str, Any]
    hints_used: int
    changed: bool = False
    error: str | None = None
    status: str = "open"
    #: The objectives this change announced as met, for the HUD's points burst.
    announced: list[str] = dataclasses.field(default_factory=list)


async def settle(db: AsyncSession, attempt_id: int, change: Any, mission: Mission) -> tuple[MissionAttempt, Draft]:
    """Apply *change* to a fresh read of the attempt and write it only if the attempt is still open and unchanged
    since that read (compare and set on its version); otherwise read it again and retry.

    Every write to an attempt goes through here: three answers, a hint and a HUD poll in flight at once each settle
    on what the others wrote, and none of them can write over another's.
    """
    for _ in range(_RETRIES):
        attempt = await _read(db, attempt_id)
        draft = Draft(attempt.objectives, attempt.quantities, attempt.extra, attempt.hints_used)
        if attempt.status != "open":
            draft.error = _NOT_RUNNING
            return attempt, draft
        change(attempt, draft)
        if not draft.changed:
            return attempt, draft
        values = {
            "objectives_json": json.dumps(draft.states), "quantities_json": json.dumps(draft.values),
            "extra_json": json.dumps(draft.extra), "hints_used": draft.hints_used,
            "score": _score(mission, draft.states), "version": attempt.version + 1, "status": draft.status,
        }
        if draft.status != "open":
            now = datetime.now(UTC)
            values |= {"finished_at": now, "seconds": int((now - _watched(attempt)).total_seconds())}
        written = await db.execute(update(MissionAttempt).where(
            MissionAttempt.id == attempt_id, MissionAttempt.version == attempt.version,
            MissionAttempt.status == "open").values(**values))
        if written.rowcount == 1:  # type: ignore[attr-defined]
            await db.commit()
            return await _read(db, attempt_id), draft
        await db.rollback()
    raise RuntimeError(f"mission attempt {attempt_id} kept changing under {_RETRIES} writes")


def restore(state: SessionState, extra: dict[str, Any]) -> None:
    """Take a mission off the training state: its objects, its scenario time, and any set its inject replaced."""
    _remove_training_objects(state)
    for satno, held in (extra.get("restore") or {}).items():
        state.hrr_tle_cache[satno] = held["tle"]
        state.hrr_tle_data_mode[satno] = held["mode"]
    state.scenario_start = state.scenario_stop = None


async def _end(db: AsyncSession, row: MissionAttempt, reason: str) -> bool:
    """End the open attempt *row*, unscored, with the reason the operator is told when they come back to it."""
    ended = await db.execute(update(MissionAttempt).where(
        MissionAttempt.id == row.id, MissionAttempt.status == "open",
    ).values(status="abandoned", finished_at=datetime.now(UTC), version=MissionAttempt.version + 1,
             extra_json=json.dumps({**row.extra, "end_reason": reason})))
    return bool(ended.rowcount == 1)  # type: ignore[attr-defined]


async def _end_open(db: AsyncSession, user: User, state: SessionState, reason: str) -> None:
    """Abandon every attempt *user* has open, each by a conditional write, taking each off the training state."""
    rows = (await db.execute(select(MissionAttempt).where(
        MissionAttempt.user_id == user.id, MissionAttempt.status == "open"))).scalars().all()
    for row in rows:
        if await _end(db, row, reason):
            restore(state, row.extra)
    await db.commit()


async def _not_running(db: AsyncSession, user: User, mission: Mission) -> HTMLResponse:
    """The 409 for a mission that is not running, with the reason its last attempt ended."""
    last = (await db.execute(select(MissionAttempt).where(
        MissionAttempt.user_id == user.id, MissionAttempt.mission_id == mission.id,
    ).order_by(MissionAttempt.id.desc()).limit(1))).scalar_one_or_none()
    if last is None:
        why = "it has not been started."
    elif last.status == "finished":
        why = "it was finished; its debrief has its result."
    else:
        why = str(last.extra.get("end_reason") or "it was abandoned, or ended when you left training.")
    return _refused(f"{mission.title} is not running: {why} Start it again from the Campaign.", 409)


async def classic_running(db: AsyncSession, user: User) -> str:
    """The title of the classic scenario *user* has open, or "": its objects and time share the training state."""
    from spectre.training.models import ChallengeResult
    from spectre.training.scenarios import get_scenario

    row = (await db.execute(select(ChallengeResult).where(
        ChallengeResult.user_id == user.id, ChallengeResult.completed_at.is_(None),
    ).limit(1))).scalar_one_or_none()
    if row is None:
        return ""
    scenario = get_scenario(row.scenario_id)
    return scenario.title if scenario is not None else row.scenario_id


def _put_on_state(state: SessionState, roles: dict[str, Bound], clock: datetime) -> dict[str, Any]:
    """Put the bound objects on the training lists and the clock in its window; return the sets an inject replaced.

    Tool records go too, so every record a check reads is the mission's own work (mission_checks).
    """
    _remove_training_objects(state)
    replaced: dict[str, Any] = {}
    for bound in roles.values():
        model = BlueAsset if bound.side == "blue" else RedTrack
        held: list[Any] = state.blue_assets if bound.side == "blue" else state.red_tracks
        held[:] = [o for o in held if o.name != bound.name]
        held.append(model(name=bound.name, tle=bound.tle, training=True, data_mode=bound.data_mode))
        if state.hrr_tle_cache.get(bound.satno) != bound.tle:
            replaced[bound.satno] = {"tle": state.hrr_tle_cache.get(bound.satno, ""),
                                     "mode": state.hrr_tle_data_mode.get(bound.satno, "REAL")}
            state.hrr_tle_cache[bound.satno] = bound.tle
            state.hrr_tle_data_mode[bound.satno] = bound.data_mode
    state.scenario_start, state.scenario_stop = engine.window(clock)
    state.intercept_history.clear()
    state.last_intercept_result = None
    state.last_threat_assessment = None
    state.last_screening = None
    return replaced


def state_lost(attempt: MissionAttempt, state: SessionState) -> str:
    """Why the training state no longer holds the mission's objects on their bound element sets, or "" when it does.

    A restart or an expired sign-in gives a fresh state, with no objects and the unburned sets: grading against it
    would grade an inject mission against the orbit before the burn.
    """
    missing = []
    for bound in _bound(attempt).values():
        held = state.blue_assets if bound.side == "blue" else state.red_tracks
        if not any(o.name == bound.name and o.tle == bound.tle for o in held):
            missing.append(f"{bound.name} is no longer on the {bound.side.title()} list")
        elif bound.data_mode == "EXERCISE" and state.hrr_tle_cache.get(bound.satno) != bound.tle:
            missing.append(f"the EXERCISE element set of {bound.name} is no longer held")
    if not missing:
        return ""
    if len(missing) == len(attempt.roles) and state.scenario_start is None:
        return ("Ended because the training console was reset (a server restart or an expired sign-in), so it no "
                "longer holds the mission's objects.")
    return "Ended because " + "; ".join(missing) + "."


def data_note(roles: dict[str, Bound]) -> str:
    """Where the bound element sets came from, as the alert says it."""
    words = {"REAL": "live from UDL", "SYNTHETIC": "bundled, SYNTHETIC"}
    modes = sorted({b.data_mode for b in roles.values()})
    parts = [words.get(m, m) for m in modes if m != "EXERCISE"]
    parts += [f"{b.name}: EXERCISE inject" for b in roles.values() if b.data_mode == "EXERCISE"]
    return "Element sets: " + "; ".join(parts)


def _intel_card(mission: Mission, roles: dict[str, Bound]) -> dict[str, Any] | None:
    """The intelligence card of the mission's first red object with a record, quoted, unless an objective asks for
    what the card says: then the operator finds it in the console (**Claude's call**)."""
    asks = any(q.fn.startswith("intel_") for q in mission.quantities)
    for bound in roles.values():
        record = get_intel(bound.satno) if bound.side == "red" and not asks else None
        if record is not None:
            keys = ("country", "orbit", "assessed_threat", "significance", "threat_level", "source")
            return {"name": record.get("name", bound.name), "satno": bound.satno, **{k: record.get(k) for k in keys}}
    return None


def _initial_objectives(mission: Mission) -> dict[str, Any]:
    return {o.id: {"status": "open", "given": None, "points": 0, "best": False, "hint": False, "announced": False}
            for o in mission.objectives}


def _alert_context(mission: Mission, attempt: MissionAttempt) -> dict[str, Any]:
    roles, values, clock, extra = attempt.roles, attempt.quantities, _clock(attempt), attempt.extra
    chapter = load_campaign().chapter(mission.chapter)
    return {
        "mission": {"id": mission.id, "title": mission.title, "chapter_title": chapter.title if chapter else ""},
        "alert_line": engine.fill(mission.alert, roles, values, clock),
        "brief": [engine.fill(line, roles, values, clock) for line in mission.brief],
        "intel_card": extra.get("intel_card"),
        "data_note": extra.get("data_note", ""),
        "exercise_inject": extra.get("inject_line"),
        "first_action": engine.fill(mission.first_action, roles, values, clock),
        "clock_text": engine.clock_text(clock),
    }


# ── What the console shows now: conditions, and the operator's own screenings ─


def _take_screening(mission: Mission, attempt: MissionAttempt, draft: Draft, state: SessionState) -> None:
    """Keep the operator's latest screening of each asset the mission reads one of, as the console recorded it, and
    read the mission's screened quantities from it (quantities.QuantityFn.screened)."""
    from spectre.training.mission_checks import screening_of

    roles = _bound(attempt)
    held: dict[str, Any] = dict(draft.extra.get("screenings") or {})
    for quantity in engine.screened_names(mission):
        bound = roles[engine.screened_asset(mission, quantity)]
        record = screening_of(state, bound, _started(attempt))
        if record is None:
            continue
        seen = quantities.Screened.of(record).as_json()
        if held.get(bound.satno) != seen:
            held[bound.satno] = seen
    if held != (draft.extra.get("screenings") or {}):
        draft.extra = {**draft.extra, "screenings": held}
        draft.values = engine.resolve_screened(mission, draft.values, roles, held)
        draft.changed = True


def _latch(mission: Mission, attempt: MissionAttempt, draft: Draft, state: SessionState) -> None:
    """Mark met every open condition the training state now shows, awarding its points."""
    roles = _bound(attempt)
    for objective in mission.objectives:
        entry = draft.states[objective.id]
        if objective.kind == "condition" and entry["status"] == "open" and objective.check is not None \
                and evaluate(objective.check, state, roles, _started(attempt)):
            entry.update(status="met", points=objective.points, best=True)
            draft.changed = True


def _observe(mission: Mission, state: SessionState) -> Any:
    def change(attempt: MissionAttempt, draft: Draft) -> None:
        _take_screening(mission, attempt, draft, state)
        _latch(mission, attempt, draft, state)
    return change


def _announce(mission: Mission) -> Any:
    def change(attempt: MissionAttempt, draft: Draft) -> None:
        del attempt
        for objective in mission.objectives:
            entry = draft.states[objective.id]
            if entry["status"] == "met" and not entry["announced"]:
                entry["announced"] = True
                draft.announced.append(objective.id)
                draft.changed = True
    return change


# ── The HUD ──────────────────────────────────────────────────────────────────


def _score(mission: Mission, states: dict[str, Any]) -> int:
    awarded = sum(int(states[o.id]["points"]) for o in mission.objectives)
    costs = sum(o.hint.cost for o in mission.objectives if o.hint is not None and states[o.id]["hint"])
    return max(0, awarded - costs)


def _screening_note(attempt: MissionAttempt, state: SessionState | None, asset: str) -> str:
    """Why the operator's latest screening of *asset* (a role) does not count, or "" when there is none such."""
    from spectre.training.mission_checks import default_budget

    record = getattr(state, "last_screening", None)
    bound = _bound(attempt).get(asset)
    if record is None or bound is None or record.asset_satno != bound.satno:
        return ""
    at = record.at if record.at.tzinfo else record.at.replace(tzinfo=UTC)
    if at < _started(attempt):
        return ""
    if record.manual:
        return (f"Your screening of a pasted element set does not count: screen {bound.name} on its own set, "
                "with Manual Asset TLE left empty.")
    if abs(float(record.budget_m_s) - default_budget()) > BUDGET_MATCH_M_S:
        return (f"Your screening at {float(record.budget_m_s):g} m/s does not count: screen at the default Max ΔV, "
                f"{default_budget():g} m/s.")
    return ""


def _waiting_for(mission: Mission, objective: Objective, attempt: MissionAttempt) -> str:
    """The asset whose screening the question is read from, by name, while the operator has not screened it."""
    quantity = objective.quantity or objective.options_from
    asset = engine.screened_asset(mission, quantity)
    if not asset or attempt.quantities.get(quantity) is not None:
        return ""
    return str(attempt.roles[asset]["name"])


def _waiting_text(mission: Mission, objective: Objective, attempt: MissionAttempt, state: SessionState | None) -> str:
    """What the operator must do before a question read from a screening can be answered, or ""."""
    waiting = _waiting_for(mission, objective, attempt)
    if not waiting:
        return ""
    note = _screening_note(attempt, state, engine.screened_asset(mission, objective.quantity or objective.options_from))
    return f"Screen {waiting} first: this is read from your own screening." + (f" {note}" if note else "")


def _condition_note(objective: Objective, attempt: MissionAttempt, state: SessionState | None) -> str:
    """Why the operator's screening does not meet a screening_run condition, or ""."""
    check = objective.check or {}
    return _screening_note(attempt, state, str(check.get("asset", ""))) if check.get("type") == "screening_run" else ""


def _hud_objective(mission: Mission, objective: Objective, entry: dict[str, Any], attempt: MissionAttempt,
                   state: SessionState | None = None) -> dict[str, Any]:
    roles, values, clock = attempt.roles, attempt.quantities, _clock(attempt)
    hint = objective.hint
    used = bool(entry["hint"])
    is_open = entry["status"] == "open"
    waiting = _waiting_text(mission, objective, attempt, state) if is_open else ""
    text = " ".join(t for t in (engine.fill(objective.text, roles, values, clock), waiting,
                                _condition_note(objective, attempt, state) if is_open else "") if t)
    return {
        "id": objective.id,
        "text": text,
        "kind": objective.kind,
        "status": entry["status"],
        "points": objective.points,
        "points_awarded": int(entry["points"]),
        # No hint while the question cannot be answered yet: it would cost points for nothing to do.
        "hint_available": hint is not None and not used and is_open and not waiting,
        "hint_cost": hint.cost if hint is not None else 0,
        "hint_text": engine.fill(hint.say, roles, values, clock) if hint is not None and used else None,
        "spotlight": hint.spotlight if hint is not None and used else None,
        "options": [{"id": o["id"], "label": o["label"]} for o in values.get(objective.options_from) or []]
        if objective.kind == "choice" else [],
        "answer_unit": _ANSWER_UNITS_SHOWN.get(objective.unit, objective.unit) if objective.kind == "answer"
        else None,
        "miss_band": entry.get("miss_band") if entry["status"] == "failed" else None,
    }


# The attempt and what changed, plus three optional facts, keyword-only so no call can swap them.
def hud_context(  # noqa: PLR0913
    mission: Mission, attempt: MissionAttempt, just_met: list[str], *, error: str | None = None,
    best_seconds: int | None = None, state: SessionState | None = None,
) -> dict[str, Any]:
    """The HUD's context (the contract's mission_hud.html keys). *star_lost* is set once any objective has failed: the
    first star needs every objective met, so the shell can offer a restart."""
    states = attempt.objectives
    return {
        "star_lost": any(states[o.id]["status"] == "failed" for o in mission.objectives),
        "mission": {"id": mission.id, "title": mission.title},
        "clock": {"started_at_iso": _watched(attempt).isoformat(), "par_seconds": mission.par_seconds},
        "best_seconds": best_seconds,
        "objectives": [_hud_objective(mission, o, states[o.id], attempt, state) for o in mission.objectives],
        "score": _score(mission, states),
        "hints_used": attempt.hints_used,
        "exercise": attempt.extra.get("inject_line"),
        "all_met": all(states[o.id]["status"] == "met" for o in mission.objectives),
        "just_met": just_met,
        "error": error,
    }


async def _running(db: AsyncSession, user: User, mission_id: str) -> tuple[Mission, MissionAttempt] | HTMLResponse:
    """The mission and the operator's open attempt at it, or the refusal; an attempt whose objects the training state
    lost is ended here, unscored, and says so."""
    mission = load_campaign().mission(mission_id)
    if mission is None:
        return _refused("Mission not found.", 404)
    attempt = await _open(db, user, mission_id)
    if attempt is None:
        return await _not_running(db, user, mission)
    lost = state_lost(attempt, get_training_state(user))
    if lost:
        await _end(db, attempt, lost)
        await db.commit()
        return _changed(_refused(f"{mission.title} has ended, unscored. {lost} Start it again from the Campaign.",
                                 409), stale=True)
    return mission, attempt


# The request, the session and the attempt, plus three keyword-only facts about this response.
async def _hud(  # noqa: PLR0913
    request: Request, db: AsyncSession, mission: Mission, attempt: MissionAttempt, *,
    error: str | None = None, changed: bool = True, state: SessionState | None = None,
) -> HTMLResponse:
    """The HUD after any change: the objectives met since the last HUD are announced by a write of their own, so of two
    HUDs at once only one announces them."""
    attempt, draft = await settle(db, attempt.id, _announce(mission), mission)
    just_met = draft.announced if draft.changed else []
    best = await _best_seconds(db, attempt.user_id, mission.id)
    response = render(request, HUD_TEMPLATE, hud_context(mission, attempt, just_met, error=error, best_seconds=best, state=state),
                      status_code=422 if error else 200)
    return _changed(response) if changed or just_met else response


async def _best_seconds(db: AsyncSession, user_id: int, mission_id: str) -> int | None:
    """The quickest finish of *mission_id* that earned a star, seconds, or None before one."""
    rows = (await db.execute(select(MissionAttempt.seconds).where(
        MissionAttempt.user_id == user_id, MissionAttempt.mission_id == mission_id,
        MissionAttempt.status == "finished", MissionAttempt.stars > 0))).scalars().all()
    return min(rows) if rows else None


async def _running_card(db: AsyncSession, user: User) -> dict[str, str] | None:
    """The mission the operator has open, for the campaign's resume strip, or None."""
    attempt = await _open(db, user)
    mission = load_campaign().mission(attempt.mission_id) if attempt is not None else None
    return {"id": mission.id, "title": mission.title} if mission is not None else None


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/campaign", response_class=HTMLResponse)
async def mission_campaign(request: Request, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """The campaign: chapters, missions, stars, locks with their reasons, and the operator's rank."""
    progress = await _get_or_create_progress(current_user, db)
    context = campaign_context(load_campaign(), progress, await _bests(db, current_user.id))
    return render(request, CAMPAIGN_TEMPLATE, {**context, "running_mission": await _running_card(db, current_user)})


async def _begin(mission: Mission, state: SessionState) -> tuple[dict[str, Bound], datetime, dict[str, Any], dict[
        str, Any]]:
    """Bind, clock, inject and compute: the bound roles, the clock, the quantities, and what the attempt keeps."""
    now = quantities.now_utc()
    roles, clock = engine.bind(mission, state, now)
    roles, clock, inject_line = engine.apply_inject(mission, roles, clock, now)
    replaced = _put_on_state(state, roles, clock)
    extra: dict[str, Any] = {"restore": replaced, "inject_line": inject_line, "data_note": data_note(roles),
                             "intel_card": _intel_card(mission, roles), "screenings": {}}
    try:
        values = await engine.compute_all(mission, Context(roles, clock, state, now))
    except StartError:
        restore(state, extra)
        raise
    return roles, clock, values, extra


@router.post("/{mission_id}/start", response_class=HTMLResponse)
async def mission_start(request: Request, mission_id: str, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """Start *mission_id*: bind its objects, set the clock, apply its inject, compute its figures, open an attempt.

    Under the sign-in's state lock, so a second start waits and then replaces the first; the database holds at most
    one open attempt per account whatever arrives. A classic scenario still running is not ended under it: its
    objects and time share the training state, so the start is refused, saying how to end it.
    """
    return await _start(request, mission_id, current_user, db)


@router.post("/{mission_id}/restart", response_class=HTMLResponse)
async def mission_restart(request: Request, mission_id: str, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """Abandon the attempt at *mission_id* and start it afresh in one step: once an objective has failed, the stars
    are lost for this attempt (star_lost), and a restart is the way back to them."""
    return await _start(request, mission_id, current_user, db, why="Ended because you restarted {title}.")


async def _start(request: Request, mission_id: str, current_user: User, db: AsyncSession, *,
                 why: str = "Ended because you started {title}.") -> HTMLResponse:
    campaign = load_campaign()
    mission = campaign.mission(mission_id)
    if mission is None:
        return _refused("Mission not found.", 404)
    progress = await _get_or_create_progress(current_user, db)
    reason = mission_lock(campaign, mission, progress, await _bests(db, current_user.id))
    if reason:
        return _refused(reason, 403)
    classic = await classic_running(db, current_user)
    if classic:
        return _refused(f"The classic scenario {classic} is running, and a mission would take its objects and time off "
                        "the console. Submit or abandon it on the Free-Play tab first.", 409)
    async with _state_lock(current_user):
        state = get_training_state(current_user)
        await _end_open(db, current_user, state, why.format(title=mission.title))
        try:
            roles, clock, values, extra = await _begin(mission, state)
        except StartError as exc:
            logger.warning("Mission %s could not start: %s", mission.id, exc)
            return _changed(_refused(str(exc), 409), stale=True)
        attempt = MissionAttempt(
            user_id=current_user.id, username=current_user.username, mission_id=mission.id,
            clock_iso=clock.isoformat(), roles_json=json.dumps({n: dataclasses.asdict(b) for n, b in roles.items()}),
            quantities_json=json.dumps(values), objectives_json=json.dumps(_initial_objectives(mission)),
            extra_json=json.dumps(extra),
        )
        db.add(attempt)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            restore(state, extra)
            return _changed(_refused("Another mission started at the same moment: start this one again.", 409),
                            stale=True)
    return _changed(render(request, ALERT_TEMPLATE, _alert_context(mission, attempt)), stale=True)


@router.get("/{mission_id}/hud", response_class=HTMLResponse)
async def mission_hud(request: Request, mission_id: str, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """The HUD, every condition re-evaluated against the training state now; nothing is written unless it changed."""
    found = await _running(db, current_user, mission_id)
    if isinstance(found, HTMLResponse):
        return found
    mission, attempt = found
    attempt = await _take_watch(db, attempt)
    attempt, _ = await settle(db, attempt.id, _observe(mission, get_training_state(current_user)), mission)
    return await _hud(request, db, mission, attempt, changed=False, state=get_training_state(current_user))


def _answerable(mission: Mission, draft: Draft, objective_id: str, kind: str) -> Objective | None:
    """The objective to settle, or None with the reason in *draft*: not this kind, already settled, or not readable
    until the operator has screened its asset."""
    objective = mission.objective(objective_id)
    if objective is None or objective.kind != kind:
        draft.error = f"No {kind} objective {objective_id!r} in this mission."
        return None
    if draft.states[objective.id]["status"] != "open":
        return None   # a repeat (a double click, a second tab): the HUD as it stands, not an error
    if draft.values.get(objective.quantity or objective.options_from) is None:
        draft.error = _NOT_YET
        return None
    return objective


def _explain_waiting(mission: Mission, attempt: MissionAttempt, draft: Draft, objective_id: str,
                     state: SessionState) -> None:
    """Replace _NOT_YET with what to do, and why a screening already run does not count."""
    objective = mission.objective(objective_id)
    if draft.error == _NOT_YET and objective is not None:
        draft.error = _waiting_text(mission, objective, attempt, state) or _NOT_YET


def _settle_answer(mission: Mission, state: SessionState, objective_id: str, value: str) -> Any:
    def change(attempt: MissionAttempt, draft: Draft) -> None:
        _take_screening(mission, attempt, draft, state)
        objective = _answerable(mission, draft, objective_id, "answer")
        if objective is None:
            _explain_waiting(mission, attempt, draft, objective_id, state)
            return
        given = engine.parse_answer(value, objective.unit)
        fn = next(q.fn for q in mission.quantities if q.name == objective.quantity)
        if given is None or not engine.plausible(given, objective.unit, fn):
            draft.error = f"That does not read as a {_UNIT_WORDS.get(objective.unit, objective.unit)}: try again."
            return
        error = engine.answer_error(given, float(draft.values[objective.quantity]), objective.unit)
        met = error <= objective.tolerance
        draft.states[objective.id].update(status="met" if met else "failed", given=value.strip()[:40],
                                          points=objective.points if met else 0,
                                          best=error <= objective.tolerance / 2,
                                          miss_band=None if met else engine.miss_band(error, objective.tolerance))
        draft.changed = True
    return change


@router.post("/{mission_id}/answer", response_class=HTMLResponse)
# FastAPI injects each parameter: the path, the two form fields, the user and the session.
async def mission_answer(  # noqa: PLR0913, PLR0917
    request: Request, mission_id: str, objective_id: Annotated[str, Form()], value: Annotated[str, Form()],
    current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Check an answer against the quantity the mission computed, within its tolerance, once."""
    found = await _running(db, current_user, mission_id)
    if isinstance(found, HTMLResponse):
        return found
    mission, attempt = found
    state = get_training_state(current_user)
    attempt, draft = await settle(db, attempt.id, _settle_answer(mission, state, objective_id, value), mission)
    return await _hud(request, db, mission, attempt, error=draft.error, state=get_training_state(current_user))


def _settle_choice(mission: Mission, state: SessionState, objective_id: str, option_id: str) -> Any:
    def change(attempt: MissionAttempt, draft: Draft) -> None:
        _take_screening(mission, attempt, draft, state)
        objective = _answerable(mission, draft, objective_id, "choice")
        if objective is None:
            _explain_waiting(mission, attempt, draft, objective_id, state)
            return
        option = next((o for o in draft.values[objective.options_from] if o["id"] == option_id), None)
        if option is None:
            draft.error = "Choose one of the options shown."
            return
        met = bool(option["correct"])
        draft.states[objective.id].update(status="met" if met else "failed", given=option["label"],
                                          points=objective.points if met else 0, best=met)
        draft.changed = True
    return change


@router.post("/{mission_id}/choose", response_class=HTMLResponse)
# FastAPI injects each parameter: the path, the two form fields, the user and the session.
async def mission_choose(  # noqa: PLR0913, PLR0917
    request: Request, mission_id: str, objective_id: Annotated[str, Form()], option_id: Annotated[str, Form()],
    current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Settle a choice: met when the option is the one marked correct, failed otherwise, once. A choice read from a
    screening is marked from the operator's own latest screening of that asset."""
    found = await _running(db, current_user, mission_id)
    if isinstance(found, HTMLResponse):
        return found
    mission, attempt = found
    state = get_training_state(current_user)
    attempt, draft = await settle(db, attempt.id, _settle_choice(mission, state, objective_id, option_id), mission)
    return await _hud(request, db, mission, attempt, error=draft.error, state=get_training_state(current_user))


def _settle_hint(mission: Mission, objective_id: str, state: SessionState) -> Any:
    def change(attempt: MissionAttempt, draft: Draft) -> None:
        objective = mission.objective(objective_id)
        entry = draft.states.get(objective_id)
        if objective is None or objective.hint is None or entry is None or entry["hint"] or entry["status"] != "open":
            draft.error = "No hint to take for that objective."
            return
        waiting = _waiting_text(mission, objective, attempt, state)
        if waiting:
            draft.error = f"No hint yet. {waiting}"
            return
        entry["hint"] = True
        draft.hints_used += 1
        draft.changed = True
    return change


@router.post("/{mission_id}/hint", response_class=HTMLResponse)
async def mission_hint(
    request: Request, mission_id: str, objective_id: Annotated[str, Form()], current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Show an open objective's hint and spotlight, at its stated cost in points, recorded as a hint used."""
    found = await _running(db, current_user, mission_id)
    if isinstance(found, HTMLResponse):
        return found
    mission, attempt = found
    attempt, draft = await settle(db, attempt.id, _settle_hint(mission, objective_id,
                                                               get_training_state(current_user)), mission)
    return await _hud(request, db, mission, attempt, error=draft.error, state=get_training_state(current_user))


def _debrief_objective(mission: Mission, objective: Objective, entry: dict[str, Any], attempt: MissionAttempt,
                       passed: bool) -> dict[str, Any]:
    roles, values, clock = attempt.roles, attempt.quantities, _clock(attempt)
    accepted = None
    if passed or entry["status"] == "met":
        if objective.kind == "answer" and values.get(objective.quantity) is not None:
            spec = next(q for q in mission.quantities if q.name == objective.quantity)
            accepted = engine.accepted_text(values[objective.quantity], objective.unit, spec.fn)
        elif objective.kind == "choice":
            accepted = next((o["label"] for o in values.get(objective.options_from) or [] if o["correct"]), None)
    return {"text": engine.fill(objective.text, roles, values, clock), "status": entry["status"],
            "given": entry["given"], "accepted": accepted,
            "explanation": engine.fill(objective.explain, roles, values, clock)}


async def _award_pass(db: AsyncSession, user: User, first_pass: bool) -> tuple[list[Any], int]:
    """Pay a first pass through the existing gamification path; return the level-ups it brought and the rank points
    it paid (none on a replay)."""
    if not first_pass:
        return [], 0
    progress = await _get_or_create_progress(user, db)
    award = award_points(MISSION_PAY_ACTION)
    axis = progress.axis_points.copy()
    for name, delta in award.axis_deltas.items():
        axis[name] = axis.get(name, 0.0) + delta
    progress.axis_points = axis
    progress.total_points += award.total_points
    progress.scenarios_passed += 1
    events, _ = _apply_level_ups(progress)
    return events, award.total_points


def _no_rank_points(stars: int) -> str:
    """Why a finish paid no rank points."""
    return "Replays pay no rank points." if stars else "Rank points are paid for a first pass: every objective met."


def _following(campaign: Campaign, mission: Mission) -> Mission | None:
    """The mission after *mission* in its campaign; None after the last, or for a mission not in the campaign."""
    missions = iter(campaign.missions)
    for each in missions:
        if each == mission:
            return next(missions, None)
    return None


def next_lock_reason(campaign: Campaign, mission: Mission, progress: TrainingProgress, bests: dict[str, Best]) -> (
        str | None):
    """Why the mission after *mission* is still locked, in words naming its chapter when the chapter is the lock;
    None when it is open or there is none."""
    following = _following(campaign, mission)
    if following is None:
        return None
    reason = mission_lock(campaign, following, progress, bests)
    if not reason:
        return None
    chapter = campaign.chapter(following.chapter)
    if chapter is not None and following.chapter != mission.chapter and reason.startswith("Reach "):
        return f"{chapter.title} opens at {reason.removeprefix('Reach ')}"
    return reason


def _next_mission(campaign: Campaign, mission: Mission, progress: TrainingProgress, bests: dict[str, Best]) -> dict[
        str, str] | None:
    candidate = _following(campaign, mission)
    if candidate is not None and not mission_lock(campaign, candidate, progress, bests):
        return {"id": candidate.id, "title": candidate.title}
    return None


def _finishing(mission: Mission, state: SessionState) -> Any:
    def change(attempt: MissionAttempt, draft: Draft) -> None:
        _take_screening(mission, attempt, draft, state)
        _latch(mission, attempt, draft, state)
        draft.status, draft.changed = "finished", True
    return change


def _outcome(mission: Mission, attempt: MissionAttempt) -> engine.Outcome:
    states = attempt.objectives
    all_met = all(states[o.id]["status"] == "met" for o in mission.objectives)
    return engine.stars_for(all_met, attempt.seconds, mission.par_seconds, attempt.hints_used,
                            all(states[o.id]["best"] for o in mission.objectives))


@router.post("/{mission_id}/finish", response_class=HTMLResponse)
async def mission_finish(request: Request, mission_id: str, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """End the attempt: stars, points, the pass paid once, the objects taken off the training state, the debrief.

    The end is a conditional write from open to finished: of several finishes at once, one ends the attempt and is
    paid; the rest find it no longer running.
    """
    found = await _running(db, current_user, mission_id)
    if isinstance(found, HTMLResponse):
        return found
    mission, attempt = found
    campaign = load_campaign()
    async with _state_lock(current_user):
        state = get_training_state(current_user)
        progress = await _get_or_create_progress(current_user, db)
        bests_before = await _bests(db, current_user.id)
        attempt, draft = await settle(db, attempt.id, _finishing(mission, state), mission)
        if draft.error is not None:
            return await _not_running(db, current_user, mission)
        outcome = _outcome(mission, attempt)
        attempt.stars = outcome.stars
        restore(state, attempt.extra)
        events, rank_points = await _award_pass(
            db, current_user, outcome.stars > 0 and bests_before.get(mission.id, Best()).stars == 0)
        await db.commit()
    locked_before = {m.id for m in campaign.missions if mission_lock(campaign, m, progress, bests_before)}
    bests = await _bests(db, current_user.id)
    context = {
        "mission": {"id": mission.id, "title": mission.title},
        "stars": outcome.stars,
        "star_reasons": [dataclasses.asdict(r) for r in outcome.reasons],
        # The mission's own figure is its score; rank points are the training points a first pass pays.
        "score": attempt.score, "points": attempt.score,
        "rank_points_earned": rank_points,
        "rank_note": "" if rank_points else _no_rank_points(outcome.stars),
        "seconds": attempt.seconds, "par_seconds": mission.par_seconds,
        "hints_used": attempt.hints_used,
        "objectives": [_debrief_objective(mission, o, attempt.objectives[o.id], attempt, outcome.stars > 0)
                       for o in mission.objectives],
        "best_answer_note": " ".join(engine.fill(t, attempt.roles, attempt.quantities, _clock(attempt))
                                     for t in (mission.debrief_best, mission.debrief_why) if t),
        "unlocked": [m.title for m in campaign.missions
                     if m.id in locked_before and not mission_lock(campaign, m, progress, bests)],
        "next_mission": _next_mission(campaign, mission, progress, bests),
        "next_lock_reason": next_lock_reason(campaign, mission, progress, bests),
        "rank_up": {"level": events[-1].level, "title": events[-1].title} if events else None,
    }
    return _changed(render(request, DEBRIEF_TEMPLATE, context), stale=True)


@router.post("/{mission_id}/abandon", response_class=HTMLResponse)
async def mission_abandon(request: Request, mission_id: str, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """End the attempt unscored, take its objects off the training state, and show the campaign."""
    async with _state_lock(current_user):
        attempt = await _open(db, current_user, mission_id)
        if attempt is not None and await _end(db, attempt, "you abandoned it."):
            restore(get_training_state(current_user), attempt.extra)
        await db.commit()
    progress = await _get_or_create_progress(current_user, db)
    context = campaign_context(load_campaign(), progress, await _bests(db, current_user.id))
    return _changed(render(request, CAMPAIGN_TEMPLATE, {**context, "running_mission": None}), stale=True)
