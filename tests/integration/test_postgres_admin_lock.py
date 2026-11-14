"""On PostgreSQL the last-admin guard takes row locks on the admin rows (SPC-070, SPC-071).

spectre.web.routes.admin._lock_admin_rows is a no-op on SQLite, which runs one
writer at a time, and takes SELECT ... FOR UPDATE on PostgreSQL, where two
transactions could otherwise each see the other's admin in their own snapshot.
On SQLite the line never runs, so the mutation run could not judge it; this
test runs only when the suite is pointed at PostgreSQL, as the CI job
"Tests (pytest, PostgreSQL)" does.

A second connection holds one admin row locked: the acting admin's, which
neither write touches. Both writes that take the lock, a delete and the
demotion of an admin, must then wait on it, which PostgreSQL reports in
pg_stat_activity, and finish once it is released. A write that took no lock
touches only its own row, which nothing holds, so it finishes without waiting.
The test watches for the wait until either it is seen or the request has
finished, so it depends on no clock: a route that took no lock finishes first
and fails it.

The last test runs the race the lock exists for (audit F-149): two demotions
of the last two admins, each in its own transaction, the second started while
the first has written and not committed. With the lock the second waits, then
counts one admin and is refused. Without it the second counts two in its own
snapshot, writes a row nothing holds, and both commit: no admin remains.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from typing import Any

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from spectre.web.models import User
from spectre.web.routes.admin import _set_role
from tests.integration.test_admin_route_outcomes import _create, _delete, _update, remove_accounts
from tests.integration.test_login_hardening import _ADMIN, _admin_cookies, _user_id

_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not _URL.startswith(("postgresql", "postgres")), reason="row locks exist only on PostgreSQL",
)


class _Holder:
    """A connection of its own, on a loop of its own, that holds the admin rows locked until told."""

    def __init__(self) -> None:
        import asyncpg

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        dsn = _URL.replace("postgresql+asyncpg://", "postgresql://")
        self.locker = self._run(asyncpg.connect(dsn))
        self.watcher = self._run(asyncpg.connect(dsn))

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)

    def lock_the_row_of(self, username: str) -> None:
        self._run(self.locker.execute("BEGIN"))
        locked = self._run(self.locker.fetch("SELECT id FROM users WHERE username = $1 FOR UPDATE", username))
        assert len(locked) == 1, f"{username} has no row to lock"

    def release(self) -> None:
        self._run(self.locker.execute("ROLLBACK"))

    def someone_waits_on_a_lock(self) -> bool:
        waiting = self._run(self.watcher.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()",
        ))
        return bool(waiting)

    def close(self) -> None:
        for connection in (self.locker, self.watcher):
            self._run(connection.close())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=30)


@pytest.fixture
def holder() -> Iterator[_Holder]:
    held = _Holder()
    yield held
    held.close()


def _waits_on_the_acting_admins_row(client: Any, holder: _Holder, write: Any) -> Any:
    """Run *write* while the acting admin's row is locked; its response once the lock is released.

    Asserts the write waited on a lock before it finished.
    """
    holder.lock_the_row_of(_ADMIN)
    answered: Future[Any] = Future()

    def run() -> None:
        try:
            answered.set_result(write())
        except BaseException as exc:  # noqa: BLE001 - handed to the test's thread through the future
            answered.set_exception(exc)

    request = threading.Thread(target=run)
    request.start()
    try:
        waited = False
        while not answered.done():
            if holder.someone_waits_on_a_lock():
                waited = True
                break
        assert waited, "the write finished without waiting on the admin rows' locks"
    finally:
        holder.release()
        request.join(timeout=30)
    return answered.result(timeout=30)


def test_a_delete_waits_for_a_lock_held_on_an_admin_row(client: Any, holder: _Holder) -> None:
    cookies = _admin_cookies(client)
    _create(client, cookies, "pg_lock_probe")
    target = _user_id(client, cookies, "pg_lock_probe")
    try:
        answer = _waits_on_the_acting_admins_row(client, holder, lambda: _delete(client, cookies, target))
        assert answer.status_code == 200
        assert ">pg_lock_probe<" not in client.get("/admin/users", cookies=cookies).text
    finally:
        remove_accounts(client, ("pg_lock_probe",))


def test_demoting_an_admin_waits_for_a_lock_held_on_an_admin_row(client: Any, holder: _Holder) -> None:
    cookies = _admin_cookies(client)
    _create(client, cookies, "pg_lock_admin", role="admin")
    target = _user_id(client, cookies, "pg_lock_admin")
    try:
        answer = _waits_on_the_acting_admins_row(
            client, holder, lambda: _update(client, cookies, target, "operator"),
        )
        assert answer.status_code == 200
        row = client.get(f"/admin/users/{target}/edit", cookies=cookies).text
        assert re.search(r'<option value="operator"[^>]*selected', row), "the admin was not demoted"
    finally:
        remove_accounts(client, ("pg_lock_admin",))


_WAITING_ON_A_LOCK = text(
    "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()",
)


async def _admins(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0)


async def _demote_both_at_once(first_name: str, second_name: str) -> tuple[bool, bool, int]:
    """Demote both admins in two overlapping transactions; each answer and the admins left.

    The first demotion writes and stays open. The second starts then, and the
    first commits only once the second has finished or is seen waiting on a
    lock, so the order depends on no clock.
    """
    engine = create_async_engine(_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as first, sessions() as second, sessions() as watcher:
            first_admin = await first.scalar(select(User).where(User.username == first_name))
            second_admin = await second.scalar(select(User).where(User.username == second_name))
            assert first_admin is not None and second_admin is not None
            first_done = await _set_role(first, first_admin, "operator")
            second_write = asyncio.ensure_future(_set_role(second, second_admin, "operator"))
            while not second_write.done():
                if await watcher.scalar(_WAITING_ON_A_LOCK):
                    break
                await watcher.rollback()
                await asyncio.sleep(0)
            await first.commit()
            second_done = await second_write
            await second.commit()
            await watcher.rollback()
            return first_done, second_done, await _admins(watcher)
    finally:
        await engine.dispose()


async def _restore_admin(username: str) -> None:
    engine = create_async_engine(_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(update(User).where(User.username == username).values(role="admin"))
            await db.commit()
    finally:
        await engine.dispose()


async def _admin_count() -> int:
    engine = create_async_engine(_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db:
            return await _admins(db)
    finally:
        await engine.dispose()


def test_two_concurrent_demotions_of_the_last_two_admins_leave_one_admin(client: Any) -> None:
    cookies = _admin_cookies(client)
    _create(client, cookies, "pg_race_admin", role="admin")
    try:
        assert asyncio.run(_admin_count()) == 2, "the race needs exactly two admins; an earlier test left one behind"
        first_done, second_done, admins_left = asyncio.run(_demote_both_at_once(_ADMIN, "pg_race_admin"))
        assert first_done, "the first demotion, with two admins and nothing in its way, was refused"
        assert admins_left == 1, f"two overlapping demotions left {admins_left} admins"
        assert not second_done, "the second demotion was not refused"
    finally:
        asyncio.run(_restore_admin(_ADMIN))
        remove_accounts(client, ("pg_race_",))
