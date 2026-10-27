"""GCAT search treats the query as text, and the shared cache survives refreshes.

Audit F-138: the operator's search went to pandas ``str.contains`` with its
default ``regex=True``, on the event loop, across every column; "(" raised
and a catastrophic pattern could stall the server.

Audit F-139: refresh cleared the shared cache before checking whether a
refresh was already running, so a second refresh wiped what the first was
loading; ``_FETCHING`` was reset without try/finally; and N concurrent first
views of a dataset downloaded it N times.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pandas as pd
import pytest

from spectre.web.routes import gcat


@pytest.fixture
def cache() -> Any:
    saved = dict(gcat._CACHE)
    gcat._CACHE.clear()
    gcat._KEY_LOCKS.clear()
    yield gcat._CACHE
    gcat._CACHE.clear()
    gcat._CACHE.update(saved)
    gcat._REFRESH.fetching = False


def _frame(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame({"name": [f"SAT (A{i})" for i in range(rows)], "satcat": [str(i) for i in range(rows)]})


class TestSearch:
    @pytest.mark.parametrize("q", ["(", "(a+)+$", "[", "*"])
    def test_a_query_is_literal_text(self, cache: Any, q: str) -> None:
        cache["k"] = {"df": _frame(), "rows": 3, "cols": 2, "columns": ["name", "satcat"]}
        started = time.perf_counter()
        td = gcat._page_data("k", q=q)
        assert td is not None
        assert time.perf_counter() - started < 1.0

    def test_brackets_match_themselves(self, cache: Any) -> None:
        cache["k"] = {"df": _frame(), "rows": 3, "cols": 2, "columns": ["name", "satcat"]}
        td = gcat._page_data("k", q="(a1)")
        assert td is not None
        assert td["filtered_rows"] == 1


def _slow_fetch(calls: list[str]) -> Any:
    def fetch(key: str, _meta: Any) -> tuple[str, pd.DataFrame]:
        calls.append(key)
        time.sleep(0.05)
        return key, _frame()
    return fetch


class TestRefresh:
    async def test_a_second_refresh_does_not_wipe_the_first(
        self, cache: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(gcat, "_fetch_one", _slow_fetch(calls))
        await asyncio.gather(gcat._refresh_cache(), gcat._refresh_cache())
        assert set(cache) == set(gcat.DATASETS)
        assert len(calls) == len(gcat.DATASETS), "the second refresh ran a second download"
        assert gcat._REFRESH.fetching is False

    async def test_a_failed_refresh_releases_the_flag_and_keeps_the_cache(
        self, cache: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache["k"] = {"df": _frame(), "rows": 3, "cols": 2, "columns": ["name", "satcat"]}

        async def _boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("network gone")

        monkeypatch.setattr(gcat.asyncio, "gather", _boom)
        with pytest.raises(RuntimeError):
            await gcat._refresh_cache()
        assert gcat._REFRESH.fetching is False
        assert "k" in cache, "a failed refresh must not leave the panel empty"

    async def test_concurrent_first_views_download_once(
        self, cache: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(gcat, "_fetch_one", _slow_fetch(calls))
        key = next(iter(gcat.DATASETS))
        results = await asyncio.gather(*(gcat._ensure_cached(key) for _ in range(5)))
        assert all(results)
        assert calls == [key]
