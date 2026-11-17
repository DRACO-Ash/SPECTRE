"""Mission writes under real concurrency, against the console served by uvicorn on a file database (SPC-248, B1).

The independent review found lost updates: three settling posts at once all answered "failed" yet two objectives
stayed open, and a correct resubmission was then accepted; a HUD poll could wipe an answer in flight; four finishes
at once all returned a debrief; two starts at once could leave two attempts open. Every write is now a compare and
set on the attempt's version, a finish is a conditional end, and starts are serialised per sign-in with the database
holding one open attempt per account.

Each test signs in afresh, so it has its own training state, and fires its requests from threads at the one server,
whose event loop interleaves them at every await, as it would for a double click or a second tab.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest

from tests.browser.conftest import ADMIN_PASS, ADMIN_USER

_MISSION = "/training/m/know_your_asset"


class _Operator:
    """A fresh sign-in to the live console, with its CSRF token."""

    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=60.0)
        page = self.client.get("/login").text
        token = re.search(r'name="login_csrf" value="([^"]+)"', page)
        assert token
        signed = self.client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS,
                                                  "login_csrf": token.group(1)})
        assert signed.status_code in (302, 303), signed.text[:200]
        # The cookie is marked Secure, which an HTTP client keeps to itself over plain HTTP: it is set by hand, as
        # the browser tests' Chromium sends it to localhost.
        session = signed.cookies["spectre_session"]
        self.client.cookies.clear()
        self.client.cookies.set("spectre_session", session)
        training = self.client.get("/training").text
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', training)
        assert csrf
        self.csrf = csrf.group(1)

    def post(self, path: str, data: dict[str, str] | None = None) -> httpx.Response:
        return self.client.post(path, data=data or {}, headers={"X-CSRF-Token": self.csrf})

    def get(self, path: str) -> httpx.Response:
        return self.client.get(path)

    def statuses(self) -> dict[str, str]:
        return dict(re.findall(r'data-objective-id="([^"]+)" data-status="([^"]+)"', self.get(f"{_MISSION}/hud").text))

    def option(self, objective: str, label: str) -> str:
        block = self.get(f"{_MISSION}/hud").text.split(f'data-objective-id="{objective}"', 1)[1].split("</li>", 1)[0]
        for value, text in re.findall(r'value="([^"]+)"[^>]*>\s*([^<]+)<', block):
            if text.strip() == label:
                return value
        raise AssertionError(f"no option {label!r}")


@pytest.fixture
def operator(live_server: str) -> Iterator[_Operator]:
    op = _Operator(live_server)
    yield op
    op.post(f"{_MISSION}/abandon")
    op.client.close()


def _at_once(calls: list[Callable[[], Any]]) -> list[Any]:
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result() for f in [pool.submit(call) for call in calls]]


def test_settling_posts_at_once_each_settle_and_none_is_lost(operator: _Operator) -> None:
    assert operator.post(f"{_MISSION}/start").status_code == 200
    regime_leo, regime_geo = operator.option("regime", "LEO"), operator.option("regime", "GEO")
    wrong = [
        lambda: operator.post(f"{_MISSION}/answer", {"objective_id": "longitude", "value": "10"}),
        lambda: operator.post(f"{_MISSION}/answer", {"objective_id": "inclination", "value": "3"}),
        lambda: operator.post(f"{_MISSION}/choose", {"objective_id": "regime", "option_id": regime_leo}),
    ] * 3
    polls = [lambda: operator.get(f"{_MISSION}/hud") for _ in range(6)]
    answers = _at_once(wrong + polls)
    assert all(r.status_code == 200 for r in answers), [r.status_code for r in answers]
    assert operator.statuses() == {"longitude": "failed", "inclination": "failed", "regime": "failed"}
    # Nothing was left open for a later, correct post to settle.
    operator.post(f"{_MISSION}/choose", {"objective_id": "regime", "option_id": regime_geo})
    assert operator.statuses()["regime"] == "failed"


def test_a_hud_poll_in_flight_does_not_wipe_an_answer(operator: _Operator) -> None:
    operator.post(f"{_MISSION}/start")
    regime_geo = operator.option("regime", "GEO")
    calls: list[Callable[[], Any]] = [lambda: operator.get(f"{_MISSION}/hud") for _ in range(10)]
    calls.insert(5, lambda: operator.post(f"{_MISSION}/choose", {"objective_id": "regime", "option_id": regime_geo}))
    _at_once(calls)
    assert operator.statuses()["regime"] == "met"


def test_finishes_at_once_end_the_attempt_once(operator: _Operator) -> None:
    operator.post(f"{_MISSION}/start")
    operator.get(f"{_MISSION}/hud")
    finishes = _at_once([lambda: operator.post(f"{_MISSION}/finish") for _ in range(4)])
    assert sorted(r.status_code for r in finishes) == [200, 409, 409, 409]


def test_starts_at_once_leave_one_attempt_open(operator: _Operator) -> None:
    starts = _at_once([lambda: operator.post(f"{_MISSION}/start") for _ in range(4)])
    # The sign-in's state lock serialises them: each start in turn replaces the one before, so every one succeeds.
    assert [r.status_code for r in starts] == [200, 200, 200, 200]
    assert operator.post(f"{_MISSION}/finish").status_code == 200
    # Had two been left open, the second would still be running.
    assert operator.post(f"{_MISSION}/finish").status_code == 409
    assert operator.get(f"{_MISSION}/hud").status_code == 409
