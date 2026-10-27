"""A session token expires eight hours after it was issued.

Audit F-155. Expiry is the only server-side bound on a token that logout did
not revoke, and no test at any layer pinned it: dropping ``max_age`` from the
decode left the suite green.
"""

from __future__ import annotations

import pytest

from spectre.web import auth

_ISSUED = 1_790_000_000


def _at(monkeypatch: pytest.MonkeyPatch, seconds: int) -> None:
    import itsdangerous.timed

    monkeypatch.setattr(itsdangerous.timed.time, "time", lambda: float(seconds))


def test_the_limit_is_eight_hours() -> None:
    assert auth._SESSION_MAX_AGE == 8 * 3600


@pytest.mark.parametrize(("age", "valid"), [(0, True), (28_799, True), (28_801, False), (10 * 86_400, False)])
def test_a_token_is_good_until_the_limit_and_not_after(
    monkeypatch: pytest.MonkeyPatch, age: int, valid: bool,
) -> None:
    _at(monkeypatch, _ISSUED)
    token = auth.make_session_cookie("operator", 0)
    _at(monkeypatch, _ISSUED + age)
    assert (auth.decode_session_cookie(token) == "operator") is valid
