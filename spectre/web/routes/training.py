"""Training environment routes.

DATA ISOLATION CONTRACT
-----------------------
These routes NEVER:
  - Access UDL credentials or operational TLEs
  - Touch the operational session log

They ONLY:
  - Read training_* database tables via get_db()
  - Read static YAML configs via spectre.training.*
  - Write to training_* database tables
  - Pre-load synthetic scenario TLEs into the sign-in's TRAINING planning
    state on scenario start, remove them when the scenario ends, and set that
    state's scenario time to the scenario's epoch

The training planning state (spectre.web.planning_state.get_training_state)
is the sign-in's own, apart from its operational one: every /training route
and every request from the console in the training frame uses it
(spectre.web.training_frame), and it is discarded when the operator leaves
training. Nothing here reads or writes the operational lists or window
(0.47.0 review B1).
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Select, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.domain.models import BlueAsset, RedTrack
from spectre.training.gamification import (
    award_points,
    check_level_up,
    get_config,
    level_progress_fraction,
    next_level_gates,
    points_to_next_level,
    recommended_next_step,
)
from spectre.training.models import ChallengeResult, MissionAttempt, TrainingProgress, TrainingSession
from spectre.training.scenarios import (
    VERDICT_LABELS,
    content_title,
    get_scenario,
    scenarios_for_level,
    with_titles,
)
from spectre.training.tutorials import get_tutorial, tutorials_for_level
from spectre.web.auth import require_login
from spectre.web.database import get_db
from spectre.web.deps import render
from spectre.web.elsets import refused
from spectre.web.models import User
from spectre.web.planning_state import SessionState, discard_training_state, get_training_state
from spectre.web.routes.udl import cancel_training_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training", tags=["training"])

_SCENARIO_NOT_FOUND = '<p class="error-msg">Scenario not found.</p>'
_DETAIL_TEMPLATE = "partials/training_scenario_detail.html"

#: The events a training response raises for the page (training.js, training.html). training-changed re-fetches
#: the sidebar, banner, dashboard, tutorial and scenario lists (audit 1-18, G-4); training-console-stale marks the
#: console frame for a reload, because the planning lists or the scenario time changed (audit F0).
_CHANGED = "training-changed"
_CHANGED_AND_STALE = "training-changed, training-console-stale"

CurrentUser = Annotated[User, Depends(require_login)]
Db = Annotated[AsyncSession, Depends(get_db)]


# ── Helper: get-or-create TrainingProgress ───────────────────────────────────

async def _get_or_create_progress(
    owner: User, db: AsyncSession
) -> TrainingProgress:
    result = await db.execute(
        select(TrainingProgress).where(TrainingProgress.user_id == owner.id)
    )
    progress: TrainingProgress | None = result.scalar_one_or_none()
    if progress is None:
        cfg   = get_config()
        init_unlocks = []
        lv1 = cfg.level_def(1)
        if lv1:
            init_unlocks = lv1.unlocks[:]
        progress = TrainingProgress(
            user_id=owner.id,
            username=owner.username,
            current_level=1,
            unlocked_json=json.dumps(init_unlocks),
        )
        db.add(progress)
        try:
            await db.commit()
        except IntegrityError:
            # Two first requests raced: the other one inserted the row between
            # the select and this commit. Use its row rather than a 500 (F-276).
            await db.rollback()
            return (await db.execute(
                select(TrainingProgress).where(TrainingProgress.user_id == owner.id)
            )).scalar_one()
        await db.refresh(progress)
    return progress


# ── Helper: open training session ─────────────────────────────────────────────

async def _open_session(owner: User, db: AsyncSession) -> TrainingSession:
    """The operator's open session, or a new one when none is open.

    Every visit to the hub inserted a row, so a refresh left an unclosed
    session behind each time (audit F-276).
    """
    current = (await db.execute(
        select(TrainingSession)
        .where(TrainingSession.user_id == owner.id, TrainingSession.ended_at.is_(None))
        .order_by(TrainingSession.started_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if current is not None:
        return current
    session = TrainingSession(user_id=owner.id, username=owner.username)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Helper: level gates ──────────────────────────────────────────────────────
#
# Only the detail view used to check the level. Start, explore, submit and
# tutorial completion did not, so a Level 1 operator could start and submit a
# Level 5 challenge or bank every tutorial on first login (audit F-159).

def _scenario_locked(progress: TrainingProgress, scenario: Any) -> HTMLResponse | None:
    """A 403 if *progress* has not reached *scenario*'s level, else ``None``."""
    if progress.current_level >= scenario.level_required:
        return None
    return HTMLResponse(
        f'<p class="error-msg">Reach Level {scenario.level_required} to unlock this scenario.</p>',
        status_code=403,
    )


def _tutorial_locked(progress: TrainingProgress, tutorial_id: str) -> HTMLResponse | None:
    """A 403 if the tutorial is not in the operator's unlocked list, else ``None``."""
    if f"tutorial:{tutorial_id}" in progress.unlocked:
        return None
    return HTMLResponse(
        '<p class="error-msg">This tutorial unlocks at a later level.</p>', status_code=403,
    )


def _recent_scored(user_id: int, limit: int) -> Select[ChallengeResult]:
    """The operator's latest scored attempts.

    Exploration runs are not history: they used to show as PASS or FAIL
    beside scored attempts (audit F-167).
    """
    return (
        select(ChallengeResult)
        .where(ChallengeResult.user_id == user_id, ChallengeResult.scored.is_(True))
        .order_by(ChallengeResult.started_at.desc())
        .limit(limit)
    )


async def _scored_attempts(db: AsyncSession, user_id: int, scenario_id: str) -> int:
    """How many scored attempts account *user_id* has made at *scenario_id*."""
    rows = (await db.execute(
        select(ChallengeResult).where(
            ChallengeResult.user_id == user_id,
            ChallengeResult.scenario_id == scenario_id,
            ChallengeResult.scored.is_(True),
        )
    )).scalars().all()
    return len(rows)


def _changed(response: HTMLResponse, *, console: bool = True) -> HTMLResponse:
    """*response*, raising the events that bring the rest of the training page up to date."""
    response.headers["HX-Trigger"] = _CHANGED_AND_STALE if console else _CHANGED
    return response


# ── The hub's progress panels ─────────────────────────────────────────────────

async def _hub_context(owner: User, db: AsyncSession, progress: TrainingProgress) -> dict[str, Any]:
    """Everything the sidebar, banner, dashboard, tutorial and scenario lists show.

    One builder for the page, the dashboard and the refresh that follows every
    change, so they cannot disagree (audit 1-18, 1-19).
    """
    cfg = get_config()
    available = scenarios_for_level(progress.current_level)
    free_play = [s for s in available if not s.challenge]
    return {
        "progress": progress,
        "cfg": cfg,
        "level_def": cfg.level_def(progress.current_level),
        "next_lv_def": cfg.level_def(progress.current_level + 1),
        "progress_pct": int(level_progress_fraction(progress.current_level, progress.total_points) * 100),
        "pts_needed": points_to_next_level(progress.current_level, progress.total_points),
        "gates": next_level_gates(progress),
        "recommendation": recommended_next_step(progress),
        "free_play_scenarios": free_play,
        "challenge_scenarios": [s for s in available if s.challenge],
        "unlocked_tutorials": tutorials_for_level(progress.unlocked),
        "recent_results": (await db.execute(_recent_scored(owner.id, 5))).scalars().all(),
        "first_scenario": free_play[0] if free_play else None,
        "content_title": content_title,
        "campaign_next": await campaign_next(db, owner, progress),
    }


async def campaign_next(db: AsyncSession, owner: User, progress: TrainingProgress) -> dict[str, str] | None:
    """The first mission of the Campaign the operator can fly and has no star on yet, for the Dashboard's Start Here;
    None when every open mission has its star."""
    from spectre.training.missions import load_campaign
    from spectre.web.routes.missions import _bests, mission_lock

    campaign = load_campaign()
    bests = await _bests(db, owner.id)
    for mission in campaign.missions:
        best = bests.get(mission.id)
        if (best is None or best.stars == 0) and not mission_lock(campaign, mission, progress, bests):
            return {"id": mission.id, "title": mission.title}
    return None


# ── Main training page ────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def training_home(request: Request, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """Main training hub — opens (or resumes) a training session."""
    progress = await _get_or_create_progress(current_user, db)
    session = await _open_session(current_user, db)
    return render(request, "training.html", {
        **await _hub_context(current_user, db, progress),
        "user": current_user,
        "training_session_id": session.id,
    })


@router.get("/refresh", response_class=HTMLResponse)
async def training_refresh(request: Request, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """The hub's progress panels, each swapped out of band into its place (audit 1-18, G-4).

    The page asks for this whenever a response raises training-changed, so a
    completion, a submission or a level-up shows without a reload.
    """
    progress = await _get_or_create_progress(current_user, db)
    return render(request, "partials/training_refresh.html", await _hub_context(current_user, db, progress))


# ── Leave training mode ───────────────────────────────────────────────────────

async def leave_training(owner: User, db: AsyncSession) -> None:
    """Everything leaving training undoes (audit 1-21).

    The sign-in's training planning state is discarded, with every object and
    the scenario time training put in it and anything added by hand in the
    training frame; the operational state was never touched, so there is
    nothing to put back (0.47.0 review B1). An attempt still open is cancelled
    (its panel has gone with the page), and the open session is closed with
    its time added to the operator's total.
    """
    # Tasks training started (a UDL login in the frame) go too; the operational ones are untouched (review S2).
    cancel_training_tasks(owner.session_key)
    discard_training_state(owner)
    await _cancel_open_attempts(db, owner)
    await _abandon_open_missions(db, owner)
    await _close_sessions(db, owner)
    await db.commit()


async def _mission_running(db: AsyncSession, owner: User) -> str:
    """The title of the mission *owner* has open, or ""."""
    from spectre.training.missions import load_campaign

    row = (await db.execute(select(MissionAttempt).where(
        MissionAttempt.user_id == owner.id, MissionAttempt.status == "open").limit(1))).scalar_one_or_none()
    if row is None:
        return ""
    mission = load_campaign().mission(row.mission_id)
    return mission.title if mission is not None else row.mission_id


async def _abandon_open_missions(db: AsyncSession, owner: User) -> None:
    """Mark every mission attempt *owner* has open abandoned: its objects went with the training state (SPC-248)."""
    await db.execute(
        update(MissionAttempt)
        .where(MissionAttempt.user_id == owner.id, MissionAttempt.status == "open")
        .values(status="abandoned", finished_at=datetime.now(UTC))
    )


async def _close_sessions(db: AsyncSession, owner: User) -> None:
    """Close every open training session of *owner*, adding its time to their total."""
    open_sessions = (await db.execute(
        select(TrainingSession).where(TrainingSession.user_id == owner.id, TrainingSession.ended_at.is_(None))
    )).scalars().all()
    if not open_sessions:
        return
    # A local, aware now: ts.ended_at is typed as the column, and SQLite hands
    # it back naive after a refresh (audit F-264).
    now = datetime.now(UTC)
    prog = await _get_or_create_progress(owner, db)
    for ts in open_sessions:
        ts.ended_at = now
        started = ts.started_at if ts.started_at.tzinfo else ts.started_at.replace(tzinfo=UTC)
        prog.time_in_training_minutes += max(0.0, (now - started).total_seconds() / 60.0)


@router.post("/leave", response_class=RedirectResponse)
async def training_leave(current_user: CurrentUser, db: Db) -> RedirectResponse:
    """Close the training session, remove its scenario objects, return to Operations."""
    await leave_training(current_user, db)
    return RedirectResponse(url="/", status_code=303)


def _remove_training_objects(state: SessionState) -> None:
    """Drop every object a scenario added to the training lists; objects added by hand in the frame stay."""
    state.blue_assets = [a for a in state.blue_assets if not a.training]
    state.red_tracks = [t for t in state.red_tracks if not t.training]


def _set_scenario_time(state: SessionState, scenario: Any) -> None:
    """Make *scenario*'s epoch the training console's scenario start, its horizon the window's end.

    The console's Manoeuvre Start and the other tools read the scenario start
    and fall back to now when it is blank, so synthetic objects were
    propagated months past their epoch (audit 2-7, X3, 4-8). *state* is the
    training state, so the operational window is never touched.
    """
    epoch = scenario.epoch
    if epoch is None:
        return
    state.scenario_start = epoch
    state.scenario_stop = epoch + timedelta(hours=scenario.horizon_hours)


# ── Scenario detail panel ─────────────────────────────────────────────────────

async def _detail(request: Request, owner: User, db: AsyncSession, scenario: Any) -> HTMLResponse:
    """The scenario's briefing panel, before an attempt starts."""
    progress = await _get_or_create_progress(owner, db)
    # Scored attempts only, so the number shown is the one the start records.
    return render(request, _DETAIL_TEMPLATE, {
        "scenario": scenario,
        "progress": progress,
        "attempt_number": await _scored_attempts(db, owner.id, scenario.id) + 1,
        "titles": with_titles,
    })


@router.get("/scenario/{scenario_id}", response_class=HTMLResponse)
async def training_scenario_detail(
    request: Request, scenario_id: str, current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Return scenario briefing and objectives panel."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)

    progress = await _get_or_create_progress(current_user, db)
    locked = _scenario_locked(progress, scenario)
    if locked is not None:
        return locked
    return await _detail(request, current_user, db, scenario)


# ── Start a scenario attempt ──────────────────────────────────────────────────

def _preload_training_objects(scenario: Any, owner: User) -> None:
    """Load a scenario's synthetic objects into the operator's planning state.

    SPECTRE panels can then work with them immediately. Training TLEs are
    fully synthetic and never come from UDL. They are tagged as training
    objects and removed when the scenario ends or the operator leaves
    training; untagged, they used to stay in the operational lists for good
    (audit F-051).
    """
    try:
        state = get_training_state(owner)
        for obj in scenario.objects:
            held: list[Any] = state.blue_assets if obj.side == "blue" else state.red_tracks
            if any(obj.satno == getattr(h, "satno", None) or obj.name == h.name for h in held):
                continue
            # The one acceptance check every ingest path runs (SPC-201): a refused set is never loaded, and the
            # operator's run log says so, naming the object and what failed.
            refusal = refused(obj.name, obj.tle)
            if refusal is not None:
                state.append_log(f"[TRAINING] {refusal}")
                continue
            model = BlueAsset if obj.side == "blue" else RedTrack
            held.append(model(name=obj.name, tle=obj.tle, training=True, data_mode="SYNTHETIC"))
    # BLE001: a preload failure must not stop the scenario starting.
    except Exception as _tl_exc:  # noqa: BLE001
        logger.warning("Could not pre-load scenario TLEs into session state: %s", _tl_exc)


async def _cancel_open_attempts(db: AsyncSession, owner: User, result_id: int | None = None) -> None:
    """Delete *owner*'s attempts not yet submitted (only *result_id*, when given), and uncount the scored ones.

    An attempt left open counted as made, so the next one lost the first-try
    bonus (audit G-3). Submitted attempts are never touched.
    """
    query = select(ChallengeResult).where(
        ChallengeResult.user_id == owner.id, ChallengeResult.completed_at.is_(None),
    )
    if result_id is not None:
        query = query.where(ChallengeResult.id == result_id)
    ids = [cr.id for cr in (await db.execute(query)).scalars().all()]
    if not ids:
        return
    # The delete itself re-checks that each row is still open, so an attempt
    # submitted since the select is never removed, and the count given back is
    # the scored rows this delete removed, not those the select saw.
    still_open = (ChallengeResult.id.in_(ids), ChallengeResult.completed_at.is_(None))
    scored = (await db.execute(delete(ChallengeResult).where(*still_open, ChallengeResult.scored.is_(True))))
    await db.execute(delete(ChallengeResult).where(*still_open))
    removed: int = scored.rowcount  # type: ignore[attr-defined]
    if removed:
        progress = await _get_or_create_progress(owner, db)
        progress.scenarios_started = max(0, progress.scenarios_started - removed)


async def _start_scenario(
    scenario_id: str,
    owner: User,
    db: AsyncSession,
    scored: bool,
    request: Request,
) -> HTMLResponse:
    """Shared logic for scored and explore-mode scenario starts.

    The last scenario's objects and any attempt still open go first, so the
    lists hold this scenario's objects only (audit 1-21).
    """
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)

    progress = await _get_or_create_progress(owner, db)
    locked = _scenario_locked(progress, scenario)
    if locked is not None:
        return locked
    running = await _mission_running(db, owner)
    if running:
        # Its objects and time share the training state, and would be taken off the console under it (SPC-248).
        return HTMLResponse(
            f'<p class="error-msg" role="alert">The mission {html.escape(running)} is running, and a scenario would '
            "take its objects and time off the console. Finish or abandon it on the Campaign tab first.</p>",
            status_code=409,
        )

    state = get_training_state(owner)
    _remove_training_objects(state)
    await _cancel_open_attempts(db, owner)
    _preload_training_objects(scenario, owner)
    _set_scenario_time(state, scenario)

    # Explore runs are not numbered; a scored attempt counts only scored ones.
    attempt_num = await _scored_attempts(db, owner.id, scenario_id) + 1 if scored else 0
    if scored:
        progress.scenarios_started += 1

    cr = ChallengeResult(
        user_id=owner.id,
        username=owner.username,
        scenario_id=scenario_id,
        attempt_num=attempt_num,
        first_try=(attempt_num == 1 and scored),
        scored=scored,
    )
    db.add(cr)
    await db.commit()
    await db.refresh(cr)

    return _changed(render(request, "partials/training_scenario_active.html", {
        "scenario": scenario,
        "result_id": cr.id,
        "attempt_num": attempt_num,
        "scored": scored,
        "titles": with_titles,
    }))


@router.post("/scenario/{scenario_id}/start", response_class=HTMLResponse)
async def training_scenario_start(
    request: Request, scenario_id: str, current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Start a scored attempt."""
    return await _start_scenario(scenario_id, current_user, db, scored=True, request=request)


@router.post("/scenario/{scenario_id}/explore", response_class=HTMLResponse)
async def training_scenario_explore(
    request: Request, scenario_id: str, current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Start an unscored free-exploration run.

    A ChallengeResult row is created so the operator can tick off objectives
    and see what they do, but no points are awarded and the attempt counter
    is not incremented.  Reset deletes the row; submit completes it, marked
    unscored, and it is left out of the activity history and attempt counts.
    """
    return await _start_scenario(scenario_id, current_user, db, scored=False, request=request)


# ── Reset or abandon the active scenario ──────────────────────────────────────

@router.post("/scenario/{scenario_id}/reset", response_class=HTMLResponse)
async def training_scenario_reset(
    request: Request,
    scenario_id: str,
    result_id: Annotated[int, Form()],
    current_user: CurrentUser,
    db: Db,
) -> HTMLResponse:
    """Delete the in-progress ChallengeResult and return a fresh scenario detail.

    This is the clean-reset path: the operator returns to the pre-start
    briefing with the scenario's objects gone from the planning lists. Only
    the current attempt row is removed; previously completed attempts are
    preserved.
    """
    await _cancel_open_attempts(db, current_user, result_id)
    _remove_training_objects(get_training_state(current_user))
    await db.commit()

    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)
    # The briefing is shown only at a level that opens it: Reset returned a
    # locked scenario's briefing that the detail route refuses (review S5).
    locked = _scenario_locked(await _get_or_create_progress(current_user, db), scenario)
    if locked is not None:
        return locked
    return _changed(await _detail(request, current_user, db, scenario))


@router.post("/scenario/{scenario_id}/abandon", response_class=HTMLResponse)
async def training_scenario_abandon(
    scenario_id: str,
    result_id: Annotated[int, Form()],
    current_user: CurrentUser,
    db: Db,
) -> HTMLResponse:
    """Close the attempt panel, cancelling the attempt and removing the scenario's objects (audit G-3, 1-21).

    Abandon used to close the panel in the browser only: the attempt stayed
    open, counted as made, and cost the next attempt its first-try bonus.
    """
    await _cancel_open_attempts(db, current_user, result_id)
    _remove_training_objects(get_training_state(current_user))
    await db.commit()
    return _changed(HTMLResponse(""))


# ── Submit a scenario attempt ─────────────────────────────────────────────────

def _objective_ids(raw: str) -> list[str]:
    """The client's completed-objective list, as distinct ids in order.

    A repeated id used to add its points once per repetition, so any
    self-certified scenario passed on demand (audit F-158).
    """
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return list(dict.fromkeys(x for x in parsed if isinstance(x, str)))


#: The ways an operator writes each answer unit, longest first within each, stripped from the end of an answer.
_UNIT_SPELLINGS: dict[str, tuple[str, ...]] = {
    "hours": ("hours", "hour", "hrs", "hr", "h"),
    "degrees": ("degrees", "degree", "deg", "°"),
    "km": ("kilometres", "kilometers", "km"),
    "m/s": ("m/s", "mps"),
}


def _bare_answer(given: str, unit: str | None) -> str:
    """*given* without a trailing unit that matches the objective's, and for hours a leading "T+" (audit 3-3).

    "T+18h", "18 h" and "18h" were refused for an answer in hours.
    """
    text = given.strip().lower()
    wanted = (unit or "").strip().lower()
    if wanted == "hours":
        text = re.sub(r"^t\s*\+\s*", "", text)
    for spelling in _UNIT_SPELLINGS.get(wanted, (wanted,) if wanted else ()):
        if text.endswith(spelling):
            return text[:-len(spelling)].strip()
    return text


#: A plain decimal number, signed or not. float() also takes "1_8", "nan", "inf" and "1.8e1", none of which an
#: operator means as an answer (review nit).
_PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


def _answer_ok(obj: Any, given: str) -> bool:
    """Whether the operator's answer matches an answer-type objective."""
    op_ans = given.strip().lower()
    expected = obj.answer.strip().lower()
    if obj.tolerance is None:
        return bool(op_ans == expected)  # exact match, case-insensitive
    number = _bare_answer(given, obj.unit)
    if not _PLAIN_NUMBER.fullmatch(number):
        return False
    try:
        return abs(float(number) - float(expected)) <= float(obj.tolerance)
    except (ValueError, TypeError):
        return False


def _ticked(scenario: Any, completed_ids: list[str], answers: dict[str, str]) -> list[str]:
    """The objectives ticked, and those answered: typing an answer ticks its objective (audit 3-3)."""
    answered = [o.id for o in scenario.objectives if o.answer and answers.get(o.id, "").strip()]
    return list(dict.fromkeys([*completed_ids, *answered]))


def _elapsed_minutes(cr: ChallengeResult) -> float:
    """Minutes since the attempt started, by the server's clock.

    The client's own figure was stored as given, negative or not, and a
    "submit within the time limit" objective was self-certified (audit F-168).
    """
    started = cr.started_at
    if started.tzinfo is None:  # SQLite returns naive datetimes
        started = started.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - started).total_seconds() / 60.0)


def _over_time(scenario: Any, elapsed_min: float) -> bool:
    """Whether a timed scenario was submitted after its limit."""
    limit = scenario.time_limit_minutes
    return limit is not None and elapsed_min > limit


def _score_objectives(
    scenario: Any, completed_ids: list[str], operator_answers: dict[str, str], *, late: bool = False,
) -> tuple[int, dict[str, float], list[str]]:
    """Total and per-axis points for the ticked objectives, and those that scored.

    An objective with an expected answer scores only when the answer given
    matches it; a ticked box with a wrong answer earns nothing. A
    time-limited objective scores nothing on a late submission.
    """
    obj_by_id = {o.id: o for o in scenario.objectives}
    axis_scores: dict[str, float] = {}
    total_score = 0
    scored: list[str] = []
    for obj_id in completed_ids:
        obj = obj_by_id.get(obj_id)
        if obj is None or (late and obj.time_limited):
            continue
        if obj.answer and not _answer_ok(obj, operator_answers.get(obj.id, "")):
            continue
        scored.append(obj_id)
        total_score += obj.points
        axis_scores[obj.skill_axis] = axis_scores.get(obj.skill_axis, 0.0) + obj.points
    return total_score, axis_scores, scored


def _why_unmet(obj: Any, ticked: list[str], late: bool) -> str:
    """Why an objective that did not score did not, without saying what would have."""
    if obj.id not in ticked:
        return "not answered" if obj.answer else "not ticked"
    if late and obj.time_limited:
        return "submitted after the time limit"
    return "outside tolerance" if obj.tolerance is not None else "not the accepted answer"


# Seven facts of one attempt, each needed to say why an objective did or did not score; the last three are
# keyword-only so no call can swap them.
def _objective_outcomes(  # noqa: PLR0913
    scenario: Any, ticked: list[str], answers: dict[str, str], scored_ids: list[str], *,
    late: bool, scored: bool, passed: bool,
) -> list[dict[str, Any]]:
    """Every objective, met or not, with the answer given and, where it gives nothing away, the one accepted.

    The debrief said "Review the objectives above" with no objectives above
    (audit 1-16). On a *scored* attempt the accepted answer is shown for an
    objective that was met, or for every objective once the attempt *passed*;
    otherwise an unmet answer reads "outside tolerance" with no value, and an
    explore run never shows one, so neither a failed nor an explore run is an
    answer key for the next scored attempt (review S3).
    """
    outcomes = []
    for obj in scenario.objectives:
        given = answers.get(obj.id, "").strip()
        met = obj.id in scored_ids
        outcomes.append({
            "description": with_titles(obj.description),
            "points": obj.points,
            "met": met,
            "why": "" if met else _why_unmet(obj, ticked, late),
            "has_answer": bool(obj.answer),
            "given": VERDICT_LABELS.get(given, given) if obj.answer else "",
            "accepted": obj.accepted_answer if scored and (met or passed) else "",
        })
    return outcomes


def _award(
    axis: dict[str, float], *, is_scored: bool, passed: bool, first_try: bool, challenge: bool,
) -> tuple[int, dict[str, float]]:
    """Points earned by one submission, and the axis totals after them.

    Every award needs a pass. scenario_completed was paid for any scored
    submission, a zero score among them, so seven empty submissions met the
    Level 4 Decision Quality gate (audit G-1, 1-20); gamification.yaml sets
    no scaling by score, so a fail earns nothing. The two challenge awards go
    to challenge scenarios only: they were given for every passed scored
    attempt, so a free-play pass earned 500 points where its authors tuned
    for 150 (audit F-160).
    """
    actions: list[str] = []
    if is_scored and passed:
        actions.append("scenario_completed")
        if challenge:
            actions.append("challenge_passed")
            if first_try:
                actions.append("challenge_passed_first_try")
    earned = 0
    for action in actions:
        pa = award_points(action, axis)
        earned += pa.total_points
        for name, delta in pa.axis_deltas.items():
            axis[name] = axis.get(name, 0.0) + delta
    return earned, axis


def _apply_level_ups(progress: Any) -> tuple[list[Any], list[str]]:
    """Advance *progress* through every level it now qualifies for."""
    level_up_events: list[Any] = []
    newly_unlocked: list[str] = []
    while True:
        lu = check_level_up(
            current_level=progress.current_level,
            total_points=progress.total_points,
            axis_points=progress.axis_points,
            tutorials_completed=progress.tutorials_completed,
            scenarios_passed=progress.scenarios_passed,
            challenges_passed=progress.challenges_passed,
        )
        if not lu.levelled_up:
            return level_up_events, newly_unlocked
        progress.current_level = lu.new_level
        newly_unlocked.extend(lu.newly_unlocked)
        cur_unlocked = progress.unlocked
        cur_unlocked.extend([x for x in lu.newly_unlocked if x not in cur_unlocked])
        progress.unlocked = cur_unlocked
        if lu.new_level_def:
            level_up_events.append(lu.new_level_def)


async def _open_attempt(
    db: AsyncSession, owner: User, scenario: Any, result_id: int,
) -> ChallengeResult | HTMLResponse:
    """The operator's attempt at *scenario*, claimed for scoring, or the refusal.

    The attempt must be the operator's, be for this scenario (a row from one
    scenario was scored against another's objectives, audit F-159), be at a
    level the operator holds, and not yet be submitted.
    """
    cr = (await db.execute(
        select(ChallengeResult).where(
            ChallengeResult.id == result_id,
            ChallengeResult.user_id == owner.id,
            ChallengeResult.scenario_id == scenario.id,
        )
    )).scalar_one_or_none()
    if cr is None:
        return HTMLResponse('<p class="error-msg">Attempt record not found.</p>', status_code=404)

    locked = _scenario_locked(await _get_or_create_progress(owner, db), scenario)
    if locked is not None:
        return locked

    # Claim the attempt atomically: only the first submission of an open
    # attempt is scored. Resubmitting a completed result_id re-awarded every
    # point and counter each time (audit F-049); the conditional update also
    # stops two concurrent submissions both scoring.
    claim = await db.execute(
        update(ChallengeResult)
        .where(ChallengeResult.id == cr.id, ChallengeResult.completed_at.is_(None))
        .values(completed_at=datetime.now(UTC))
    )
    if claim.rowcount == 0:  # type: ignore[attr-defined]
        return HTMLResponse(
            '<p class="error-msg">This attempt has already been submitted.</p>', status_code=409,
        )
    return cr


def _axis_change(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """How far each axis total moved, for the axes that moved.

    The debrief listed objective points per axis as "Skill Points Earned",
    but the totals move by the award actions' weights (audit F-172).
    """
    moved = {k: after.get(k, 0.0) - before.get(k, 0.0) for k in after.keys() | before.keys()}
    return {k: v for k, v in moved.items() if round(v) != 0}


@router.post("/scenario/{scenario_id}/submit", response_class=HTMLResponse)
async def training_scenario_submit(
    request: Request,
    scenario_id: str,
    result_id: Annotated[int, Form()],
    current_user: CurrentUser,
    db: Db,
    objectives_completed: Annotated[str, Form()] = "[]",  # JSON list of obj IDs
) -> HTMLResponse:
    """Score a completed scenario attempt and update operator progress."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)

    cr = await _open_attempt(db, current_user, scenario, result_id)
    if isinstance(cr, HTMLResponse):
        return cr

    elapsed_min = _elapsed_minutes(cr)
    late = _over_time(scenario, elapsed_min)

    # Collect operator-supplied answers for answer-type objectives
    form_data = await request.form()
    operator_answers: dict[str, str] = {
        key[len("answer_"):]: str(value)
        for key, value in form_data.items()
        if key.startswith("answer_")
    }
    ticked = _ticked(scenario, _objective_ids(objectives_completed), operator_answers)
    total_score, axis_scores, scored_ids = _score_objectives(scenario, ticked, operator_answers, late=late)

    # A timed scenario submitted after its limit does not pass, whatever it
    # scored: the late operator_timed_full_cycle passed on 400 of 400 (audit 4-7).
    passed     = total_score >= scenario.scoring.passing_score and not late
    is_scored  = cr.scored

    # Award gamification points only for scored attempts
    progress = await _get_or_create_progress(current_user, db)
    axis_before = dict(progress.axis_points)
    total_points_earned, current_axis = _award(
        progress.axis_points.copy(), is_scored=is_scored, passed=passed,
        first_try=cr.first_try, challenge=scenario.challenge,
    )

    # Update progress — counters only change on scored attempts
    progress.axis_points = current_axis
    progress.total_points += total_points_earned
    if is_scored and passed:
        progress.scenarios_passed += 1
        if scenario.challenge:
            progress.challenges_passed += 1

    level_up_events, newly_unlocked = _apply_level_ups(progress)
    outcomes = _objective_outcomes(scenario, ticked, operator_answers, scored_ids, late=late,
                                   scored=is_scored, passed=passed)

    # Save ChallengeResult
    cr.completed_at       = datetime.now(UTC)
    cr.time_taken_minutes = elapsed_min
    cr.total_score        = total_score
    cr.passed             = passed
    cr.axis_scores        = axis_scores
    cr.objectives_completed = scored_ids
    cr.debrief = {
        "optimal_score": scenario.scoring.optimal_score,
        "passing_score": scenario.scoring.passing_score,
        "points_earned": total_points_earned,
        "level_ups": [{"level": ld.level, "title": ld.title} for ld in level_up_events],
        "newly_unlocked": newly_unlocked,
        "objectives": outcomes,
    }

    # The attempt is over, so its objects leave the planning lists (audit 1-21).
    _remove_training_objects(get_training_state(current_user))
    await db.commit()

    return _changed(render(request, "partials/training_debrief.html", {
        "scenario": scenario,
        "cr": cr,
        "total_score": total_score,
        "passed": passed,
        "is_scored": is_scored,
        "points_earned": total_points_earned,
        "axis_scores": axis_scores,
        "axis_change": _axis_change(axis_before, current_axis),
        "late": late,
        "elapsed_min": elapsed_min,
        "level_up_events": level_up_events,
        "newly_unlocked": newly_unlocked,
        "objective_outcomes": outcomes,
        "content_title": content_title,
        "cfg": get_config(),
    }))


# ── Dashboard partial (HTMX refresh) ─────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def training_dashboard(request: Request, current_user: CurrentUser, db: Db) -> HTMLResponse:
    """Return the progress dashboard partial."""
    progress = await _get_or_create_progress(current_user, db)
    return render(request, "partials/training_dashboard.html", await _hub_context(current_user, db, progress))


# ── Tutorial viewer ───────────────────────────────────────────────────────────

@router.get("/tutorial/{tutorial_id}", response_class=HTMLResponse)
async def training_tutorial_view(
    request: Request, tutorial_id: str, current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Return a tutorial reading panel, for a tutorial the operator has unlocked (audit 1-26)."""
    tutorial = get_tutorial(tutorial_id)
    if tutorial is None:
        return HTMLResponse('<p class="error-msg">Tutorial not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user, db)
    locked = _tutorial_locked(progress, tutorial_id)
    if locked is not None:
        return locked
    already_done = tutorial_id in progress.tutorials_completed

    return render(request, "partials/training_tutorial.html", {
        "tutorial": tutorial,
        "already_done": already_done,
    })


@router.post("/tutorial/{tutorial_id}/complete", response_class=HTMLResponse)
async def training_tutorial_complete(
    request: Request, tutorial_id: str, current_user: CurrentUser, db: Db,
) -> HTMLResponse:
    """Mark a tutorial complete, award points, check for level-up."""
    tutorial = get_tutorial(tutorial_id)
    if tutorial is None:
        return HTMLResponse('<p class="error-msg">Tutorial not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user, db)
    locked = _tutorial_locked(progress, tutorial_id)
    if locked is not None:
        return locked

    points_earned = 0
    already_done  = tutorial_id in progress.tutorials_completed

    if not already_done:
        # Award points
        current_axis = progress.axis_points.copy()
        points_earned = tutorial.points
        current_axis[tutorial.skill_axis] = current_axis.get(tutorial.skill_axis, 0.0) + points_earned
        progress.axis_points   = current_axis
        progress.total_points += points_earned
        progress.tutorials_done += 1

        done = progress.tutorials_completed[:]
        done.append(tutorial_id)
        progress.tutorials_completed = done

    level_up_events, newly_unlocked = _apply_level_ups(progress)

    await db.commit()

    return _changed(render(request, "partials/training_tutorial_complete.html", {
        "tutorial": tutorial,
        "points_earned": points_earned,
        "already_done": already_done,
        "level_up_events": level_up_events,
        "newly_unlocked": newly_unlocked,
        "content_title": content_title,
        "cfg": get_config(),
        "progress": progress,
    }), console=False)
