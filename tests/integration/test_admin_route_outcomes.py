"""Every answer the admin user routes give, read off the page as the admin sees it (SPC-071).

The mutation run over spectre/web/routes/admin.py found three kinds of gap.
The inline edit row was never requested (the test named for it fetched the
list page instead), nor was any route given an id that does not exist. The
refusals were checked for a lowercase fragment such as "last admin", which a
reworded or misfiled message still contains, so the message and whether it is
shown as an error or a success were free to change. And the bound on a
username's length was tested on neither side of 64.

Each refusal here is read as the admin reads it: the flash's sentence, and
whether it is styled as an error or a success. Where a branch is reached only
when another admin acts at the same moment, the competing write is stood in
for at the seam the race test uses (test_last_admin_race), so nothing waits.
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from sqlalchemy import false

from spectre.web.auth import PASSWORD_TOO_LONG
from spectre.web.routes import admin
from tests.conftest import csrf_headers
from tests.integration.test_login_hardening import _admin_cookies, _user_id

_ABSENT_ID = 987_654_321
_NOT_FOUND_ROW = "<tr><td colspan='5'>User not found.</td></tr>"
#: Every account this module makes signs in with this; none is ever signed in to.
_PASSWORD = "hunter2"


def _flash(resp: Any) -> tuple[str, str]:
    """(kind, sentence) of the flash a mutating admin response carries."""
    match = re.search(
        r'<div id="admin-flash"[^>]*>\s*<div class="spectre-card spectre-card-(threat|nominal)".*?<p[^>]*>\s*(.*?)\s*</p>',
        resp.text, re.S,
    )
    assert match, "the response carries no flash"
    return ("error" if match.group(1) == "threat" else "success"), html.unescape(match.group(2))


def _create(client: Any, cookies: dict[str, str], username: str, password: str = _PASSWORD,
            role: str = "operator") -> Any:
    return client.post("/admin/users", data={"username": username, "password": password, "role": role},
                       cookies=cookies, headers=csrf_headers(cookies))


def _update(client: Any, cookies: dict[str, str], user_id: int, role: str, new_password: str = "") -> Any:
    return client.post(f"/admin/users/{user_id}", data={"role": role, "new_password": new_password},
                       cookies=cookies, headers=csrf_headers(cookies))


def _delete(client: Any, cookies: dict[str, str], user_id: int) -> Any:
    return client.delete(f"/admin/users/{user_id}", cookies=cookies, headers=csrf_headers(cookies))


def _listed(resp: Any, username: str) -> bool:
    return any(f">{username}<" in row for row in re.findall(r'<tr id="user-row-\d+".*?</tr>', resp.text, re.S))


@pytest.fixture
def cookies(client: Any) -> dict[str, str]:
    return _admin_cookies(client)


def remove_accounts(client: Any, prefixes: tuple[str, ...]) -> None:
    """Delete every account whose name starts with one of *prefixes*.

    The database is shared by every module in the run, so an account left
    behind, an admin above all, changes what a later module's "last admin"
    test is testing.
    """
    admin_cookies = _admin_cookies(client)
    page = client.get("/admin/users", cookies=admin_cookies).text
    for user_id, row in re.findall(r'<tr id="user-row-(\d+)"(.*?)</tr>', page, re.S):
        name = re.search(r'<span style="font-weight:500">([^<]+)</span>', row)
        if name and name.group(1).startswith(prefixes):
            _delete(client, admin_cookies, int(user_id))
    client.cookies.clear()


@pytest.fixture(scope="module", autouse=True)
def _leave_no_accounts(client: Any) -> Any:
    yield
    remove_accounts(client, ("edge_", "a" * 64))


def _ensure(client: Any, cookies: dict[str, str], username: str, role: str = "operator") -> int:
    """The id of *username*, created with *role* if it does not exist yet."""
    if f">{username}<" not in client.get("/admin/users", cookies=cookies).text:
        _create(client, cookies, username, role=role)
    user_id = _user_id(client, cookies, username)
    _update(client, cookies, user_id, role)
    return user_id


class TestCreating:
    @pytest.mark.parametrize(("form", "sentence"), [
        ({"username": "edge_role", "role": "superuser"}, "Invalid role selected."),
        ({"username": "   "}, "Username is required."),
        ({"username": "u" * 65}, "Username must be 64 characters or fewer."),
        ({"username": "two words"},
         "Username may contain only letters, digits, dot, underscore, at-sign and hyphen."),
    ])
    def test_a_refused_account_says_why_as_an_error(
        self, client: Any, cookies: dict[str, str], form: dict[str, str], sentence: str,
    ) -> None:
        fields = {"password": _PASSWORD, "role": "operator", **form}
        resp = _create(client, cookies, fields["username"], fields["password"], fields["role"])
        assert resp.status_code == 200
        assert _flash(resp) == ("error", sentence)
        refused = fields["username"].strip()
        assert not refused or not _listed(resp, refused), "a refused account appears in the table"

    def test_an_empty_password_is_refused_before_the_route_runs(self, client: Any, cookies: dict[str, str]) -> None:
        """The form layer answers 422 for an empty field, so the route's own "Password is required." is not reached."""
        resp = _create(client, cookies, "edge_nopass", password="")
        assert resp.status_code == 422
        assert ">edge_nopass<" not in client.get("/admin/users", cookies=cookies).text

    def test_a_username_of_exactly_64_characters_is_accepted(self, client: Any, cookies: dict[str, str]) -> None:
        name = "a" * 64
        resp = _create(client, cookies, name)
        assert _flash(resp) == ("success", f"User '{name}' created.")
        assert _listed(resp, name), "the table sent back must show the account just made"
        _delete(client, cookies, _user_id(client, cookies, name))


class TestTheInlineRows:
    def test_the_edit_row_is_a_form_for_that_user(self, client: Any, cookies: dict[str, str]) -> None:
        user_id = _ensure(client, cookies, "edge_edit")
        resp = client.get(f"/admin/users/{user_id}/edit", cookies=cookies)
        assert resp.status_code == 200
        assert resp.text.lstrip().startswith(f'<tr id="user-row-{user_id}"')
        assert f'hx-post="/admin/users/{user_id}"' in resp.text
        assert 'name="new_password"' in resp.text
        assert ">edge_edit<" in resp.text

    def test_the_admins_own_edit_row_marks_it_as_theirs(self, client: Any, cookies: dict[str, str]) -> None:
        mine = _user_id(client, cookies, "testadmin")
        other = _ensure(client, cookies, "edge_edit")
        own, theirs = (client.get(f"/admin/users/{uid}/edit", cookies=cookies).text for uid in (mine, other))
        badge = re.compile(r'<span class="spectre-badge[^"]*"[^>]*>you</span>')
        assert badge.search(own)
        assert not badge.search(theirs)

    @pytest.mark.parametrize("action", ["edit", "cancel"])
    def test_a_row_for_an_account_that_does_not_exist_is_a_404(
        self, client: Any, cookies: dict[str, str], action: str,
    ) -> None:
        resp = client.get(f"/admin/users/{_ABSENT_ID}/{action}", cookies=cookies)
        assert resp.status_code == 404
        assert resp.text == _NOT_FOUND_ROW


class TestUpdating:
    def test_an_account_that_does_not_exist_is_a_404(self, client: Any, cookies: dict[str, str]) -> None:
        resp = _update(client, cookies, _ABSENT_ID, "operator")
        assert resp.status_code == 404
        assert resp.text == _NOT_FOUND_ROW

    def test_an_invalid_role_is_an_error(self, client: Any, cookies: dict[str, str]) -> None:
        user_id = _ensure(client, cookies, "edge_update")
        assert _flash(_update(client, cookies, user_id, "superuser")) == ("error", "Invalid role.")

    def test_a_password_bcrypt_cannot_hash_is_an_error_and_changes_nothing(
        self, client: Any, cookies: dict[str, str],
    ) -> None:
        user_id = _ensure(client, cookies, "edge_update")
        resp = _update(client, cookies, user_id, "admin", new_password="x" * 200)
        assert _flash(resp) == ("error", PASSWORD_TOO_LONG)
        assert ">admin</span>" not in re.search(rf'<tr id="user-row-{user_id}".*?</tr>', resp.text, re.S).group(0)

    @pytest.mark.parametrize(("role", "password", "label"), [
        ("admin", "", "role"),
        ("operator", "edge-password-2", "role and password"),
        ("operator", "edge-password-3", "password"),
        ("operator", "", "no changes"),
    ])
    def test_a_saved_change_says_what_changed(
        self, client: Any, cookies: dict[str, str], role: str, password: str, label: str,
    ) -> None:
        user_id = _ensure(client, cookies, "edge_saved", role="admin" if label == "role and password" else "operator")
        resp = _update(client, cookies, user_id, role, new_password=password)
        assert _flash(resp) == ("success", f"User 'edge_saved' updated ({label}).")

    def test_the_last_admin_is_not_demoted(
        self, client: Any, cookies: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user_id = _ensure(client, cookies, "edge_admin", role="admin")

        async def only_one(_db: Any) -> int:
            return 1

        monkeypatch.setattr(admin, "_admin_count", only_one)
        resp = _update(client, cookies, user_id, "operator")
        assert _flash(resp) == ("error", "Cannot demote the last admin account.")

    def test_the_last_admin_can_still_change_their_password(
        self, client: Any, cookies: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The guard is against a demotion. Keeping the admin role while resetting the password is not one."""
        user_id = _ensure(client, cookies, "edge_admin", role="admin")

        async def only_one(_db: Any) -> int:
            return 1

        monkeypatch.setattr(admin, "_admin_count", only_one)
        resp = _update(client, cookies, user_id, "admin", new_password="edge-password-4")
        assert _flash(resp) == ("success", "User 'edge_admin' updated (password).")

    def test_a_demotion_that_loses_the_race_says_so_and_changes_nothing(
        self, client: Any, cookies: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The count saw two admins; by the write, the other was gone, so the guarded write matched no row."""
        user_id = _ensure(client, cookies, "edge_admin", role="admin")

        async def two(_db: Any) -> int:
            return 2

        monkeypatch.setattr(admin, "_admin_count", two)
        monkeypatch.setattr(admin, "_another_admin_remains", false)
        resp = _update(client, cookies, user_id, "operator")
        assert _flash(resp) == ("error", "Cannot demote the last admin account.")
        monkeypatch.undo()
        row = re.search(rf'<tr id="user-row-{user_id}".*?</tr>', client.get("/admin/users", cookies=cookies).text, re.S)
        assert row is not None and ">admin</span>" in row.group(0), "the refused demotion still changed the role"


class TestDeleting:
    def test_an_account_that_does_not_exist_is_an_error(self, client: Any, cookies: dict[str, str]) -> None:
        assert _flash(_delete(client, cookies, _ABSENT_ID)) == ("error", "User not found.")

    def test_the_admin_cannot_delete_themselves(self, client: Any, cookies: dict[str, str]) -> None:
        resp = _delete(client, cookies, _user_id(client, cookies, "testadmin"))
        assert _flash(resp) == ("error", "You cannot delete your own account.")
        assert _listed(resp, "testadmin")

    def test_one_of_two_admins_can_be_deleted(
        self, client: Any, cookies: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two admins is enough: the count is pinned at two, so other modules' admins cannot hide the boundary."""
        user_id = _ensure(client, cookies, "edge_admin_gone", role="admin")

        async def two(_db: Any) -> int:
            return 2

        monkeypatch.setattr(admin, "_admin_count", two)
        resp = _delete(client, cookies, user_id)
        assert _flash(resp) == ("success", "User 'edge_admin_gone' deleted.")
        assert not _listed(resp, "edge_admin_gone")

    def test_the_last_admin_is_not_deleted(
        self, client: Any, cookies: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The actor is an admin, so over HTTP this needs the other admin demoted between sign-in and the count."""
        user_id = _ensure(client, cookies, "edge_admin", role="admin")

        async def only_one(_db: Any) -> int:
            return 1

        monkeypatch.setattr(admin, "_admin_count", only_one)
        resp = _delete(client, cookies, user_id)
        assert _flash(resp) == ("error", "Cannot delete the last admin account.")
        assert _listed(resp, "edge_admin")

    def test_a_delete_that_loses_the_race_says_so_and_deletes_nothing(
        self, client: Any, cookies: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user_id = _ensure(client, cookies, "edge_admin", role="admin")

        async def two(_db: Any) -> int:
            return 2

        monkeypatch.setattr(admin, "_admin_count", two)
        monkeypatch.setattr(admin, "_another_admin_remains", false)
        resp = _delete(client, cookies, user_id)
        assert _flash(resp) == ("error", "Cannot delete the last admin account.")
        assert _listed(resp, "edge_admin")
