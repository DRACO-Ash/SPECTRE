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
  - Pre-load synthetic scenario TLEs into SessionState on scenario start
    (intentional bridge: training TLEs are fully synthetic, never from UDL)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectre.domain.models import BlueAsset, RedTrack
from spectre.training.gamification import (
    award_points,
    check_level_up,
    get_config,
    level_progress_fraction,
    points_to_next_level,
    recommended_next_step,
)
from spectre.training.models import ChallengeResult, TrainingProgress, TrainingSession
from spectre.training.scenarios import get_scenario, scenarios_for_level
from spectre.training.tutorials import get_tutorial, tutorials_for_level
from spectre.web.auth import require_login
from spectre.web.database import get_db
from spectre.web.deps import render
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training", tags=["training"])

_SCENARIO_NOT_FOUND = '<p class="error-msg">Scenario not found.</p>'


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


# ── Main training page ────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def training_home(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Main training hub — opens (or resumes) a training session."""
    progress = await _get_or_create_progress(current_user, db)
    cfg      = get_config()

    # Open a new session row (we close it on departure via /training/leave)
    session = await _open_session(current_user, db)

    available = scenarios_for_level(progress.current_level)
    challenges = [s for s in available if s.challenge]
    free_play  = [s for s in available if not s.challenge]
    unlocked_tutorials = tutorials_for_level(progress.unlocked)

    recent_results = (await db.execute(_recent_scored(current_user.id, 10))).scalars().all()

    level_def    = cfg.level_def(progress.current_level)
    next_lv_def  = cfg.level_def(progress.current_level + 1)
    progress_pct = int(level_progress_fraction(progress.current_level, progress.total_points) * 100)
    pts_needed   = points_to_next_level(progress.current_level, progress.total_points)
    recommendation = recommended_next_step(
        progress.axis_points,
        progress.tutorials_completed,
        progress.current_level,
    )

    return render(request, "training.html", {
        "user": current_user,
        "progress": progress,
        "cfg": cfg,
        "level_def": level_def,
        "next_lv_def": next_lv_def,
        "progress_pct": progress_pct,
        "pts_needed": pts_needed,
        "recommendation": recommendation,
        "free_play_scenarios": free_play,
        "challenge_scenarios": challenges,
        "unlocked_tutorials": unlocked_tutorials,
        "recent_results": recent_results,
        "training_session_id": session.id,
    })


# ── Leave training mode ───────────────────────────────────────────────────────

@router.post("/leave", response_class=RedirectResponse)
async def training_leave(
    request: Request,
    *,
    session_id: Annotated[int, Form()] = 0,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Close the training session, remove its scenario objects, return to Operations."""
    _remove_training_objects(current_user)
    if session_id:
        result = await db.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == current_user.id,
            )
        )
        ts = result.scalar_one_or_none()
        if ts and ts.ended_at is None:
            # A local, aware now: ts.ended_at is typed as the column, and
            # SQLite hands it back naive after a refresh (audit F-264).
            now = datetime.now(UTC)
            ts.ended_at = now
            # Accrue time — normalise started_at to UTC-aware in case SQLite returns naive
            started = ts.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            elapsed = (now - started).total_seconds() / 60.0
            prog = await _get_or_create_progress(current_user, db)
            prog.time_in_training_minutes += elapsed
            await db.commit()

    return RedirectResponse(url="/", status_code=303)


def _remove_training_objects(owner: User) -> None:
    """Drop every object a training scenario added to the operator's lists."""
    state = get_session_state(owner)
    state.blue_assets = [a for a in state.blue_assets if not a.training]
    state.red_tracks = [t for t in state.red_tracks if not t.training]


# ── Scenario detail panel ─────────────────────────────────────────────────────

@router.get("/scenario/{scenario_id}", response_class=HTMLResponse)
async def training_scenario_detail(
    request: Request,
    scenario_id: str,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Return scenario briefing and objectives panel."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)

    progress = await _get_or_create_progress(current_user, db)
    locked = _scenario_locked(progress, scenario)
    if locked is not None:
        return locked

    # Scored attempts only, so the number shown is the one the start records.
    return render(request, "partials/training_scenario_detail.html", {
        "scenario": scenario,
        "progress": progress,
        "attempt_number": await _scored_attempts(db, current_user.id, scenario_id) + 1,
    })


# ── Start a scenario attempt ──────────────────────────────────────────────────

def _preload_training_objects(scenario: Any, owner: User) -> None:
    """Load a scenario's synthetic objects into the operator's planning state.

    SPECTRE panels can then work with them immediately. Training TLEs are
    fully synthetic and never come from UDL. They are tagged as training
    objects and removed when the operator leaves training; untagged, they
    used to stay in the operational lists for good (audit F-051).
    """
    try:
        state = get_session_state(owner)
        for obj in scenario.objects:
            held: list[Any] = state.blue_assets if obj.side == "blue" else state.red_tracks
            if any(obj.satno == getattr(h, "satno", None) or obj.name == h.name for h in held):
                continue
            model = BlueAsset if obj.side == "blue" else RedTrack
            held.append(model(name=obj.name, tle=obj.tle, training=True, data_mode="SYNTHETIC"))
    # BLE001: a preload failure must not stop the scenario starting.
    except Exception as _tl_exc:  # noqa: BLE001
        logger.warning("Could not pre-load scenario TLEs into session state: %s", _tl_exc)


async def _start_scenario(
    scenario_id: str,
    owner: User,
    db: AsyncSession,
    scored: bool,
    request: Request,
) -> HTMLResponse:
    """Shared logic for scored and explore-mode scenario starts."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)

    progress = await _get_or_create_progress(owner, db)
    locked = _scenario_locked(progress, scenario)
    if locked is not None:
        return locked

    _preload_training_objects(scenario, owner)

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

    return render(request, "partials/training_scenario_active.html", {
        "scenario": scenario,
        "result_id": cr.id,
        "attempt_num": attempt_num,
        "scored": scored,
    })


@router.post("/scenario/{scenario_id}/start", response_class=HTMLResponse)
async def training_scenario_start(
    request: Request,
    scenario_id: str,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Start a scored attempt."""
    return await _start_scenario(scenario_id, current_user, db, scored=True, request=request)


@router.post("/scenario/{scenario_id}/explore", response_class=HTMLResponse)
async def training_scenario_explore(
    request: Request,
    scenario_id: str,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Start an unscored free-exploration run.

    A ChallengeResult row is created so the operator can tick off objectives
    and see what they do, but no points are awarded and the attempt counter
    is not incremented.  Reset deletes the row; submit completes it, marked
    unscored, and it is left out of the activity history and attempt counts.
    """
    return await _start_scenario(scenario_id, current_user, db, scored=False, request=request)


# ── Reset active scenario ─────────────────────────────────────────────────────

@router.post("/scenario/{scenario_id}/reset", response_class=HTMLResponse)
async def training_scenario_reset(
    request: Request,
    scenario_id: str,
    result_id: Annotated[int, Form()],
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Delete the in-progress ChallengeResult and return a fresh scenario detail.

    This is the clean-reset path: the operator returns to the pre-start briefing
    with no side effects.  Only the current attempt row is removed; previously
    completed attempts are preserved.
    """
    cr_result = await db.execute(
        select(ChallengeResult).where(
            ChallengeResult.id == result_id,
            ChallengeResult.user_id == current_user.id,
        )
    )
    cr = cr_result.scalar_one_or_none()
    if cr is not None and cr.completed_at is None:
        # Only delete if not yet submitted — don't destroy a scored record
        await db.delete(cr)
        # Roll back scenarios_started counter if this was a scored attempt
        if cr.scored:
            progress = await _get_or_create_progress(current_user, db)
            progress.scenarios_started = max(0, progress.scenarios_started - 1)
        await db.commit()

    # Return the scenario detail panel (pre-start state)
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse(_SCENARIO_NOT_FOUND, status_code=404)

    progress = await _get_or_create_progress(current_user, db)
    return render(request, "partials/training_scenario_detail.html", {
        "scenario": scenario,
        "progress": progress,
        "attempt_number": await _scored_attempts(db, current_user.id, scenario_id) + 1,
    })


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


def _answer_ok(obj: Any, given: str) -> bool:
    """Whether the operator's answer matches an answer-type objective."""
    op_ans = given.strip().lower()
    expected = obj.answer.strip().lower()
    if obj.tolerance is None:
        return bool(op_ans == expected)  # exact match, case-insensitive
    try:
        return abs(float(op_ans) - float(expected)) <= float(obj.tolerance)
    except (ValueError, TypeError):
        return False


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


def _award(
    axis: dict[str, float], *, is_scored: bool, passed: bool, first_try: bool, challenge: bool,
) -> tuple[int, dict[str, float]]:
    """Points earned by one submission, and the axis totals after them.

    The two challenge awards go to challenge scenarios only. They were given
    for every passed scored attempt, so a free-play pass earned 500 points
    where its authors tuned for 150 (audit F-160).
    """
    actions: list[str] = []
    if is_scored:
        actions.append("scenario_completed")
        if passed and challenge:
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
    *,
    objectives_completed: Annotated[str, Form()] = "[]",  # JSON list of obj IDs
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    total_score, axis_scores, scored_ids = _score_objectives(
        scenario, _objective_ids(objectives_completed), operator_answers, late=late,
    )

    passed     = total_score >= scenario.scoring.passing_score
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
    }

    await db.commit()

    cfg = get_config()
    return render(request, "partials/training_debrief.html", {
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
        "cfg": cfg,
    })


# ── Dashboard partial (HTMX refresh) ─────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def training_dashboard(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Return the progress dashboard partial."""
    progress  = await _get_or_create_progress(current_user, db)
    cfg       = get_config()
    level_def = cfg.level_def(progress.current_level)
    next_lv   = cfg.level_def(progress.current_level + 1)
    pct       = int(level_progress_fraction(progress.current_level, progress.total_points) * 100)
    pts_needed = points_to_next_level(progress.current_level, progress.total_points)
    recommendation = recommended_next_step(
        progress.axis_points, progress.tutorials_completed, progress.current_level
    )

    recent_results = (await db.execute(_recent_scored(current_user.id, 5))).scalars().all()

    available = scenarios_for_level(progress.current_level)
    first_scenario = next((s for s in available if not s.challenge), None)

    return render(request, "partials/training_dashboard.html", {
        "progress": progress,
        "cfg": cfg,
        "level_def": level_def,
        "next_lv_def": next_lv,
        "progress_pct": pct,
        "pts_needed": pts_needed,
        "recommendation": recommendation,
        "recent_results": recent_results,
        "first_scenario": first_scenario,
    })


# ── Tutorial viewer ───────────────────────────────────────────────────────────

@router.get("/tutorial/{tutorial_id}", response_class=HTMLResponse)
async def training_tutorial_view(
    request: Request,
    tutorial_id: str,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Return a tutorial reading panel."""
    tutorial = get_tutorial(tutorial_id)
    if tutorial is None:
        return HTMLResponse('<p class="error-msg">Tutorial not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user, db)
    already_done = tutorial_id in progress.tutorials_completed

    return render(request, "partials/training_tutorial.html", {
        "tutorial": tutorial,
        "already_done": already_done,
    })


@router.post("/tutorial/{tutorial_id}/complete", response_class=HTMLResponse)
async def training_tutorial_complete(
    request: Request,
    tutorial_id: str,
    current_user: Annotated[User, Depends(require_login)],
    db: Annotated[AsyncSession, Depends(get_db)],
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

    cfg = get_config()
    return render(request, "partials/training_tutorial_complete.html", {
        "tutorial": tutorial,
        "points_earned": points_earned,
        "already_done": already_done,
        "level_up_events": level_up_events,
        "newly_unlocked": newly_unlocked,
        "cfg": cfg,
        "progress": progress,
    })
