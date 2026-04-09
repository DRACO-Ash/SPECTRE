"""Training environment routes.

DATA ISOLATION CONTRACT
-----------------------
These routes NEVER:
  - Access UDL credentials or operational TLEs
  - Touch the operational log queue

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
from sqlalchemy import select
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


# ── Helper: get-or-create TrainingProgress ───────────────────────────────────

async def _get_or_create_progress(
    username: str, db: AsyncSession
) -> TrainingProgress:
    result = await db.execute(
        select(TrainingProgress).where(TrainingProgress.username == username)
    )
    progress: TrainingProgress | None = result.scalar_one_or_none()
    if progress is None:
        cfg   = get_config()
        init_unlocks = []
        lv1 = cfg.level_def(1)
        if lv1:
            init_unlocks = lv1.unlocks[:]
        progress = TrainingProgress(
            username=username,
            current_level=1,
            unlocked_json=json.dumps(init_unlocks),
        )
        db.add(progress)
        await db.commit()
        await db.refresh(progress)
    return progress


# ── Helper: open training session ─────────────────────────────────────────────

async def _open_session(username: str, db: AsyncSession) -> TrainingSession:
    session = TrainingSession(username=username)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Main training page ────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def training_home(
    request: Request,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Main training hub — opens (or resumes) a training session."""
    progress = await _get_or_create_progress(current_user.username, db)
    cfg      = get_config()

    # Open a new session row (we close it on departure via /training/leave)
    session = await _open_session(current_user.username, db)

    available = scenarios_for_level(progress.current_level)
    challenges = [s for s in available if s.challenge]
    free_play  = [s for s in available if not s.challenge]
    unlocked_tutorials = tutorials_for_level(progress.unlocked)

    # Recent results (last 10)
    recent_results = (await db.execute(
        select(ChallengeResult)
        .where(ChallengeResult.username == current_user.username)
        .order_by(ChallengeResult.started_at.desc())
        .limit(10)
    )).scalars().all()

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
    session_id: Annotated[int, Form()] = 0,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Close the training session and return to Operations."""
    if session_id:
        result = await db.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.username == current_user.username,
            )
        )
        ts = result.scalar_one_or_none()
        if ts and ts.ended_at is None:
            ts.ended_at = datetime.now(UTC)
            # Accrue time — normalise started_at to UTC-aware in case SQLite returns naive
            started = ts.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            elapsed = (ts.ended_at - started).total_seconds() / 60.0
            prog = await _get_or_create_progress(current_user.username, db)
            prog.time_in_training_minutes += elapsed
            await db.commit()

    return RedirectResponse(url="/", status_code=303)


# ── Scenario detail panel ─────────────────────────────────────────────────────

@router.get("/scenario/{scenario_id}", response_class=HTMLResponse)
async def training_scenario_detail(
    request: Request,
    scenario_id: str,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Return scenario briefing and objectives panel."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse('<p class="error-msg">Scenario not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user.username, db)
    if progress.current_level < scenario.level_required:
        return HTMLResponse(
            f'<p class="error-msg">Reach Level {scenario.level_required} to unlock this scenario.</p>',
            status_code=403,
        )

    # Count previous attempts
    attempt_count = (await db.execute(
        select(ChallengeResult)
        .where(
            ChallengeResult.username == current_user.username,
            ChallengeResult.scenario_id == scenario_id,
        )
    )).scalars().all()

    return render(request, "partials/training_scenario_detail.html", {
        "scenario": scenario,
        "progress": progress,
        "attempt_number": len(attempt_count) + 1,
    })


# ── Start a scenario attempt ──────────────────────────────────────────────────

async def _start_scenario(
    scenario_id: str,
    username: str,
    db: AsyncSession,
    scored: bool,
    request: Request,
) -> HTMLResponse:
    """Shared logic for scored and explore-mode scenario starts."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse('<p class="error-msg">Scenario not found.</p>', status_code=404)

    # Pre-load synthetic scenario TLE objects into planning state so SPECTRE panels
    # can work with them immediately.  Training TLEs are fully synthetic — they
    # never come from UDL and cannot be confused with operational data.
    try:
        state = get_session_state(username)
        for obj in scenario.objects:
            if obj.side == "blue":
                if not any(obj.satno == getattr(b, "satno", None) or obj.name == b.name
                           for b in state.blue_assets):
                    state.blue_assets.append(BlueAsset(name=obj.name, tle=obj.tle))
            else:
                if not any(obj.satno == getattr(r, "satno", None) or obj.name == r.name
                           for r in state.red_tracks):
                    state.red_tracks.append(RedTrack(name=obj.name, tle=obj.tle))
    except Exception as _tl_exc:
        logger.warning("Could not pre-load scenario TLEs into session state: %s", _tl_exc)

    progress = await _get_or_create_progress(username, db)

    if scored:
        # Count only scored previous attempts for attempt_num / first_try
        prev = (await db.execute(
            select(ChallengeResult)
            .where(
                ChallengeResult.username == username,
                ChallengeResult.scenario_id == scenario_id,
                ChallengeResult.scored == True,  # noqa: E712
            )
        )).scalars().all()
        attempt_num = len(prev) + 1
        progress.scenarios_started += 1
    else:
        attempt_num = 0   # explore runs are not numbered

    cr = ChallengeResult(
        username=username,
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
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Start a scored attempt."""
    return await _start_scenario(scenario_id, current_user.username, db, scored=True, request=request)


@router.post("/scenario/{scenario_id}/explore", response_class=HTMLResponse)
async def training_scenario_explore(
    request: Request,
    scenario_id: str,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Start an unscored free-exploration run.

    A ChallengeResult row is created so the operator can tick off objectives
    and see what they do, but no points are awarded and the attempt counter
    is not incremented.  The row is deleted when the operator resets or submits.
    """
    return await _start_scenario(scenario_id, current_user.username, db, scored=False, request=request)


# ── Reset active scenario ─────────────────────────────────────────────────────

@router.post("/scenario/{scenario_id}/reset", response_class=HTMLResponse)
async def training_scenario_reset(
    request: Request,
    scenario_id: str,
    result_id: Annotated[int, Form()],
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Delete the in-progress ChallengeResult and return a fresh scenario detail.

    This is the clean-reset path: the operator returns to the pre-start briefing
    with no side effects.  Only the current attempt row is removed; previously
    completed attempts are preserved.
    """
    cr_result = await db.execute(
        select(ChallengeResult).where(
            ChallengeResult.id == result_id,
            ChallengeResult.username == current_user.username,
        )
    )
    cr = cr_result.scalar_one_or_none()
    if cr is not None and cr.completed_at is None:
        # Only delete if not yet submitted — don't destroy a scored record
        await db.delete(cr)
        # Roll back scenarios_started counter if this was a scored attempt
        if cr.scored:
            progress = await _get_or_create_progress(current_user.username, db)
            progress.scenarios_started = max(0, progress.scenarios_started - 1)
        await db.commit()

    # Return the scenario detail panel (pre-start state)
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse('<p class="error-msg">Scenario not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user.username, db)
    scored_prev = (await db.execute(
        select(ChallengeResult)
        .where(
            ChallengeResult.username == current_user.username,
            ChallengeResult.scenario_id == scenario_id,
            ChallengeResult.scored == True,  # noqa: E712
        )
    )).scalars().all()

    return render(request, "partials/training_scenario_detail.html", {
        "scenario": scenario,
        "progress": progress,
        "attempt_number": len(scored_prev) + 1,
    })


# ── Submit a scenario attempt ─────────────────────────────────────────────────

@router.post("/scenario/{scenario_id}/submit", response_class=HTMLResponse)
async def training_scenario_submit(
    request: Request,
    scenario_id: str,
    result_id: Annotated[int, Form()],
    objectives_completed: Annotated[str, Form()] = "[]",  # JSON list of obj IDs
    time_taken_minutes: Annotated[float, Form()] = 0.0,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Score a completed scenario attempt and update operator progress."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return HTMLResponse('<p class="error-msg">Scenario not found.</p>', status_code=404)

    result = await db.execute(
        select(ChallengeResult).where(
            ChallengeResult.id == result_id,
            ChallengeResult.username == current_user.username,
        )
    )
    cr = result.scalar_one_or_none()
    if cr is None:
        return HTMLResponse('<p class="error-msg">Attempt record not found.</p>', status_code=404)

    try:
        completed_ids: list[str] = json.loads(objectives_completed)
    except (ValueError, TypeError):
        completed_ids = []

    # Collect operator-supplied answers for answer-type objectives
    form_data = await request.form()
    operator_answers: dict[str, str] = {
        key[len("answer_"):]: str(value)
        for key, value in form_data.items()
        if key.startswith("answer_")
    }

    # Score objectives — validate answer-type objectives against expected answer
    obj_by_id = {o.id: o for o in scenario.objectives}
    axis_scores: dict[str, float] = {}
    total_score = 0
    for obj_id in completed_ids:
        obj = obj_by_id.get(obj_id)
        if obj is None:
            continue
        # Validate answer if the objective has one
        if obj.answer:
            op_ans = operator_answers.get(obj.id, "").strip().lower()
            expected = obj.answer.strip().lower()
            answer_ok = False
            if obj.tolerance is not None:
                # Numeric comparison with tolerance
                try:
                    op_val = float(op_ans)
                    ex_val = float(expected)
                    answer_ok = abs(op_val - ex_val) <= float(obj.tolerance)
                except (ValueError, TypeError):
                    answer_ok = False
            else:
                # Exact string match (case-insensitive)
                answer_ok = op_ans == expected
            if not answer_ok:
                # Checkbox was ticked but answer is wrong — skip the points
                continue
        total_score += obj.points
        axis_scores[obj.skill_axis] = axis_scores.get(obj.skill_axis, 0.0) + obj.points

    passed     = total_score >= scenario.scoring.passing_score
    first_try  = cr.first_try
    is_scored  = cr.scored

    # Award gamification points only for scored attempts
    progress = await _get_or_create_progress(current_user.username, db)
    current_axis = progress.axis_points.copy()
    total_points_earned = 0

    if is_scored:
        # Base completion award
        pa = award_points("scenario_completed", current_axis)
        total_points_earned = pa.total_points
        for axis, delta in pa.axis_deltas.items():
            current_axis[axis] = current_axis.get(axis, 0.0) + delta

    if is_scored and passed:
        pa2 = award_points("challenge_passed", current_axis)
        total_points_earned += pa2.total_points
        for axis, delta in pa2.axis_deltas.items():
            current_axis[axis] = current_axis.get(axis, 0.0) + delta

        if first_try:
            pa3 = award_points("challenge_passed_first_try", current_axis)
            total_points_earned += pa3.total_points
            for axis, delta in pa3.axis_deltas.items():
                current_axis[axis] = current_axis.get(axis, 0.0) + delta

    # Update progress — counters only change on scored attempts
    progress.axis_points = current_axis
    progress.total_points += total_points_earned
    if is_scored and passed:
        progress.scenarios_passed += 1
        if scenario.challenge:
            progress.challenges_passed += 1

    # Level-up check (loop in case of multiple advances)
    level_up_events = []
    newly_unlocked  = []
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
            break
        progress.current_level = lu.new_level
        newly_unlocked.extend(lu.newly_unlocked)
        cur_unlocked = progress.unlocked
        cur_unlocked.extend([x for x in lu.newly_unlocked if x not in cur_unlocked])
        progress.unlocked = cur_unlocked
        if lu.new_level_def:
            level_up_events.append(lu.new_level_def)

    # Save ChallengeResult
    cr.completed_at       = datetime.now(UTC)
    cr.time_taken_minutes = time_taken_minutes
    cr.total_score        = total_score
    cr.passed             = passed
    cr.axis_scores        = axis_scores
    cr.objectives_completed = completed_ids
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
        "level_up_events": level_up_events,
        "newly_unlocked": newly_unlocked,
        "cfg": cfg,
    })


# ── Dashboard partial (HTMX refresh) ─────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def training_dashboard(
    request: Request,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Return the progress dashboard partial."""
    progress  = await _get_or_create_progress(current_user.username, db)
    cfg       = get_config()
    level_def = cfg.level_def(progress.current_level)
    next_lv   = cfg.level_def(progress.current_level + 1)
    pct       = int(level_progress_fraction(progress.current_level, progress.total_points) * 100)
    pts_needed = points_to_next_level(progress.current_level, progress.total_points)
    recommendation = recommended_next_step(
        progress.axis_points, progress.tutorials_completed, progress.current_level
    )

    recent_results = (await db.execute(
        select(ChallengeResult)
        .where(ChallengeResult.username == current_user.username)
        .order_by(ChallengeResult.started_at.desc())
        .limit(5)
    )).scalars().all()

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
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Return a tutorial reading panel."""
    tutorial = get_tutorial(tutorial_id)
    if tutorial is None:
        return HTMLResponse('<p class="error-msg">Tutorial not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user.username, db)
    already_done = tutorial_id in progress.tutorials_completed

    return render(request, "partials/training_tutorial.html", {
        "tutorial": tutorial,
        "already_done": already_done,
    })


@router.post("/tutorial/{tutorial_id}/complete", response_class=HTMLResponse)
async def training_tutorial_complete(
    request: Request,
    tutorial_id: str,
    current_user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Mark a tutorial complete, award points, check for level-up."""
    tutorial = get_tutorial(tutorial_id)
    if tutorial is None:
        return HTMLResponse('<p class="error-msg">Tutorial not found.</p>', status_code=404)

    progress = await _get_or_create_progress(current_user.username, db)

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

    # Level-up check
    level_up_events: list[Any] = []
    newly_unlocked:  list[Any] = []
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
            break
        progress.current_level = lu.new_level
        newly_unlocked.extend(lu.newly_unlocked)
        cur_unlocked = progress.unlocked
        cur_unlocked.extend([x for x in lu.newly_unlocked if x not in cur_unlocked])
        progress.unlocked = cur_unlocked
        if lu.new_level_def:
            level_up_events.append(lu.new_level_def)

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
