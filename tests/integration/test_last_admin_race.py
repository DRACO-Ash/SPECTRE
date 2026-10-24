"""The last admin cannot be removed by two admins acting at once.

Audit F-149. The last-admin guard read the admin count and then wrote, with
no lock or conditional statement, so two admins demoting (or deleting) each
other at the same moment each read a count of two and both committed,
leaving no admin. The race is reproduced here deterministically: the guard's
read is made to see the competing commit land just after it counted.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import update

from spectre.web.models import User
from spectre.web.routes import admin
from tests.conftest import csrf_headers
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login, _user_id


@pytest.fixture
def two_admins(client: Any) -> Any:
    cookies = _admin_cookies(client)
    _create_operator(client, cookies, "second_admin", "second-admin-pass")
    other = _user_id(client, cookies, "second_admin")
    client.post(f"/admin/users/{other}", data={"role": "admin"}, cookies=cookies, headers=csrf_headers(cookies))
    yield cookies, other
    # Leave testadmin an admin for the rest of the suite.
    client.cookies.clear()


def _race(monkeypatch: pytest.MonkeyPatch, rival: str) -> None:
    """The guard counts two admins; *rival* is demoted the instant after."""
    real = admin._admin_count

    async def counted_then_raced(db: Any) -> int:
        seen = await real(db)
        await db.execute(update(User).where(User.username == rival).values(role="operator"))
        await db.commit()
        return seen

    monkeypatch.setattr(admin, "_admin_count", counted_then_raced)


def test_a_racing_demotion_cannot_remove_the_last_admin(
    client: Any, two_admins: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cookies, other = two_admins
    _race(monkeypatch, rival="testadmin")
    resp = client.post(f"/admin/users/{other}", data={"role": "operator"}, cookies=cookies,
                       headers=csrf_headers(cookies))
    assert "last admin" in resp.text
    monkeypatch.undo()
    _restore(client)


def test_a_racing_delete_cannot_remove_the_last_admin(
    client: Any, two_admins: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cookies, other = two_admins
    _race(monkeypatch, rival="testadmin")
    resp = client.delete(f"/admin/users/{other}", cookies=cookies, headers=csrf_headers(cookies))
    assert "last admin" in resp.text
    monkeypatch.undo()
    _restore(client)


def _restore(client: Any) -> None:
    """Put testadmin back, signed in as the admin the race left standing."""
    client.cookies.clear()
    session = str(_login(client, "second_admin", "second-admin-pass").cookies["spectre_session"])
    survivor = {"spectre_session": session}
    client.cookies.clear()
    me = _user_id(client, survivor, "testadmin")
    client.post(f"/admin/users/{me}", data={"role": "admin"}, cookies=survivor, headers=csrf_headers(survivor))
    client.cookies.clear()
