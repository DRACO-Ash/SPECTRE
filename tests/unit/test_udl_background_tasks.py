"""UDL background work is held, single-flight, refreshed and ended on logout.

Audit F-143. Login started two background tasks and discarded their handles,
so the loop held only weak references and a task could be collected before it
finished. The "ready" guard did not cover "loading", so concurrent logins
duplicated the 60 s catalogue pull; once ready the catalogue was never
refreshed; and the tasks kept using the password after UDL logout.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectre.web import planning_state
from spectre.web.routes import udl


@pytest.fixture(autouse=True)
def fresh_catalogue() -> Any:
    saved = (planning_state._onorbit_catalog, planning_state._catalog_status, udl._catalog_loaded_at)
    planning_state.set_catalog_status("not_loaded")
    yield
    planning_state._onorbit_catalog, planning_state._catalog_status, udl._catalog_loaded_at = saved


def _client(gets: list[str]) -> Any:
    async def _get(url: str, **_k: Any) -> Any:
        gets.append(url)
        await asyncio.sleep(0.05)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = [{"satNo": 1, "name": "ONE"}]
        return resp

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = _get
    return client


async def test_two_logins_in_quick_succession_pull_once() -> None:
    gets: list[str] = []
    with patch("httpx.AsyncClient", return_value=_client(gets)):
        await asyncio.gather(
            udl._fetch_onorbit_background("u", "p"), udl._fetch_onorbit_background("u", "p"),
        )
    assert [g for g in gets if g.endswith("/onorbit")] == [f"{udl._UDL_BASE}/onorbit"]
    assert planning_state.get_catalog_status() == "ready"


async def test_a_stale_catalogue_is_pulled_again() -> None:
    gets: list[str] = []
    with patch("httpx.AsyncClient", return_value=_client(gets)):
        await udl._fetch_onorbit_background("u", "p")
        await udl._fetch_onorbit_background("u", "p")
        assert len(gets) == 1, "a fresh catalogue is not pulled again"
        udl._catalog_loaded_at = time.monotonic() - udl._CATALOG_TTL_S - 1
        await udl._fetch_onorbit_background("u", "p")
    assert len(gets) == 2


async def test_a_task_is_held_until_it_finishes_and_logout_cancels_it() -> None:
    done = asyncio.Event()

    async def _work() -> None:
        await done.wait()

    task = udl._spawn(_work(), "alice")
    assert task in udl._BACKGROUND
    udl._cancel_session_tasks("alice")
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)  # done-callbacks run on the next turn of the loop
    assert task.cancelled()
    assert task not in udl._BACKGROUND
    assert "alice" not in udl._SESSION_TASKS
