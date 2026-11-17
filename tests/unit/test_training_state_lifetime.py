"""The training planning state's lifetime and its tasks (0.47.0 review round c).

● B1: background tasks were filed by sign-in alone, so a UDL Disconnect in the training frame cancelled the
  operational burn watch and refreshes, and the reverse.
● S1: the training state stamped its own creation time, so opened late it outlived its sign-in by up to 8 hours,
  UDL password and all.
● S2: discarding it left the password on the state a task still held.
● S4: ?frame=training opened outside the frame served a training console that looked operational.
● N3, N4: the default watchlist's entries were shared by reference; has_session_state saw one store only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest import mock

import pytest

from spectre.web import planning_state as ps
from spectre.web.models import SessionKey
from spectre.web.routes import udl
from spectre.web.training_frame import is_training_request

_KEY = SessionKey(user_id=515_151, session_id="lifetime")
_HOUR = 3600.0


@pytest.fixture
def clock() -> Iterator[list[float]]:
    """The monotonic clock planning_state reads, set by the test."""
    now = [1_000.0]
    ps._store.pop(_KEY, None)
    ps._training_store.pop(_KEY, None)
    with mock.patch.object(ps.time, "monotonic", lambda: now[0]):
        yield now
    ps._store.pop(_KEY, None)
    ps._training_store.pop(_KEY, None)


class TestTheTrainingStateLivesNoLongerThanItsSignIn:
    """S1."""

    def test_opened_late_it_expires_with_the_sign_in(self, clock: list[float]) -> None:
        ps.get_session_state(_KEY)              # sign-in at T
        clock[0] += 7 * _HOUR                   # training opened at T+7h
        training = ps.get_training_state(_KEY)
        training.udl_username, training.udl_password = "u", "p"
        when = datetime(2026, 1, 1, tzinfo=UTC)
        expires = ps.sign_in_expires_at(_KEY, when)
        assert expires is not None and (expires - when).total_seconds() == pytest.approx(_HOUR)
        assert ps.session_alive(_KEY, training)

        clock[0] += _HOUR + 60                  # T+8h01: the sign-in is dead
        assert not ps.session_alive(_KEY, training)
        ps._prune(clock[0])
        assert _KEY not in ps._training_store
        assert training.udl_password is None, "a task holding it finds no password"

    def test_its_entry_carries_the_sign_ins_time(self, clock: list[float]) -> None:
        clock[0] += 5 * _HOUR
        ps.get_training_state(_KEY)             # the operational entry is made first, now
        assert ps._training_store[_KEY][0] == ps._store[_KEY][0]

    def test_session_alive_needs_the_sign_in(self, clock: list[float]) -> None:
        training = ps.get_training_state(_KEY)
        ps._store.pop(_KEY)
        assert not ps.session_alive(_KEY, training)


class TestDiscarding:
    """S2, N4."""

    def test_discard_blanks_the_credentials_a_task_still_holds(self, clock: list[float]) -> None:
        training = ps.get_training_state(_KEY)
        training.udl_username, training.udl_password = "u", "p"
        ps.discard_training_state(_KEY)
        assert (training.udl_username, training.udl_password) == (None, None)
        assert ps.get_session_state(_KEY).udl_password is None

    def test_clearing_a_sign_in_clears_both_states(self, clock: list[float]) -> None:
        ps.get_training_state(_KEY)
        assert ps.has_session_state(_KEY)
        ps.clear_session_state(_KEY)
        assert not ps.has_session_state(_KEY)
        assert _KEY not in ps._training_store

    def test_clearing_an_account_clears_its_training_states(self, clock: list[float]) -> None:
        training = ps.get_training_state(_KEY)
        training.udl_password = "p"
        ps.clear_account_state(_KEY.user_id)
        assert _KEY not in ps._training_store and training.udl_password is None


def test_each_state_gets_its_own_copy_of_the_default_watchlist(clock: list[float]) -> None:
    """N3."""
    saved = ps.get_default_hrr_objects()
    ps.set_default_hrr_objects([{"satno": "1", "name": "A"}])
    try:
        operational, training = ps.get_session_state(_KEY), ps.get_training_state(_KEY)
        operational.hrr_objects[0]["name"] = "CHANGED"
        assert training.hrr_objects[0]["name"] == "A"
        assert ps.get_default_hrr_objects()[0]["name"] == "A"
    finally:
        ps.set_default_hrr_objects(saved)


class TestTasksAreFiledBySide:
    """B1: a Disconnect on one side cancels that side's tasks only."""

    async def _two_tasks(self) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
        done = asyncio.Event()

        async def work() -> None:
            await done.wait()

        operational = udl._spawn(work(), _KEY)
        with ps.training_request():
            training = udl._spawn(work(), _KEY)
        return operational, training

    async def _settle(self, *tasks: asyncio.Task[None]) -> None:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_a_training_disconnect_leaves_the_operational_tasks(self) -> None:
        operational, training = await self._two_tasks()
        with ps.training_request():
            udl._cancel_session_tasks(_KEY)
        await asyncio.sleep(0)
        assert training.cancelled() and not operational.done()
        await self._settle(operational, training)

    async def test_an_operational_disconnect_leaves_the_training_tasks(self) -> None:
        operational, training = await self._two_tasks()
        udl._cancel_session_tasks(_KEY)
        await asyncio.sleep(0)
        assert operational.cancelled() and not training.done()
        await self._settle(operational, training)

    async def test_leaving_training_cancels_its_tasks_only(self) -> None:
        operational, training = await self._two_tasks()
        udl.cancel_training_tasks(_KEY)
        await asyncio.sleep(0)
        assert training.cancelled() and not operational.done()
        await self._settle(operational, training)
        await asyncio.sleep(0)
        assert (_KEY, True) not in udl._SESSION_TASKS and (_KEY, False) not in udl._SESSION_TASKS


class TestTheFrameQueryCountsOnlyInTheFrame:
    """S4."""

    def test_opened_in_a_tab_it_is_operational(self) -> None:
        assert not is_training_request("/", {"sec-fetch-dest": "document"}, "frame=training")

    def test_in_the_frame_or_with_no_fetch_metadata_it_is_training(self) -> None:
        assert is_training_request("/", {"sec-fetch-dest": "iframe"}, "frame=training")
        assert is_training_request("/", {}, "frame=training")

    def test_the_frames_own_requests_are_training_whatever_their_destination(self) -> None:
        assert is_training_request("/plan", {"sec-fetch-dest": "empty", "x-spectre-frame": "training"}, "")
