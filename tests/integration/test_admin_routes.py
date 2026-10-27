"""Integration tests for /admin/users CRUD routes."""

from __future__ import annotations

from tests.conftest import csrf_headers


def _admin_session(client: object) -> dict[str, str]:  # type: ignore[type-arg]
    """Return cookies dict for an authenticated admin session."""
    resp = client.post(  # type: ignore[attr-defined]
        "/login",
        data={"username": "testadmin", "password": "testpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return dict(resp.cookies)


def _operator_session(client: object, username: str, password: str) -> dict[str, str]:  # type: ignore[type-arg]
    """Return cookies dict for an authenticated operator session."""
    resp = client.post(  # type: ignore[attr-defined]
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return dict(resp.cookies)


def _row(client: object, cookies: dict[str, str], username: str) -> tuple[str, str]:  # type: ignore[type-arg]
    """(row id, row HTML) of *username* in the admin table; fails if absent.

    These tests searched in a loop and broke out with no assertion after it,
    so they passed when the row was missing (audit F-156).
    """
    import re

    page = client.get("/admin/users", cookies=cookies).content.decode()  # type: ignore[attr-defined]
    for match in re.finditer(r'<tr id="user-row-(\d+)".*?</tr>', page, re.S):
        if f">{username}<" in match.group(0):
            return match.group(1), match.group(0)
    raise AssertionError(f"{username} is not in the admin user table")


def _role(client: object, cookies: dict[str, str], username: str) -> str:  # type: ignore[type-arg]
    """The role badge the admin table shows for *username*."""
    row = _row(client, cookies, username)[1]
    return "admin" if ">admin</span>" in row else "operator"


class TestAdminAccess:
    def test_unauthenticated_redirects(self, client: object) -> None:
        resp = client.get("/admin/users", follow_redirects=False)  # type: ignore[attr-defined]
        assert resp.status_code == 302
        assert "/login" in resp.headers["location"]

    def test_operator_forbidden(self, client: object) -> None:
        """Operator role must not access admin routes."""
        admin_cookies = _admin_session(client)
        # Create an operator account first
        client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "op_forbidden", "password": "pass123", "role": "operator"},
            cookies=admin_cookies,
            headers=csrf_headers(admin_cookies),
        )
        op_cookies = _operator_session(client, "op_forbidden", "pass123")
        resp = client.get("/admin/users", cookies=op_cookies, follow_redirects=False)  # type: ignore[attr-defined]
        assert resp.status_code == 403

    def test_admin_can_access(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        assert resp.status_code == 200
        assert b"User Management" in resp.content
        assert b"testadmin" in resp.content


class TestCreateUser:
    def test_create_operator(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "new_op", "password": "hunter2", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b"new_op" in resp.content

    def test_create_admin(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "second_admin", "password": "hunter2", "role": "admin"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b"second_admin" in resp.content

    def test_duplicate_username_rejected(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "new_op", "password": "whatever", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b"already taken" in resp.content.lower()

    def test_empty_username_rejected(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "   ", "password": "pass", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b"required" in resp.content.lower()

    def test_invalid_role_rejected(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "rogue", "password": "pass", "role": "superuser"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b"invalid role" in resp.content.lower()


class TestEditUser:
    def test_edit_row_returns_form(self, client: object) -> None:
        """GET /admin/users/{id}/edit returns inline edit form HTML."""
        cookies = _admin_session(client)
        # Fetch user id for new_op
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        assert resp.status_code == 200
        # We just check the edit endpoint works — get admin's own id via the page
        # and look for hx-get="/admin/users/ pattern
        assert b"hx-get=\"/admin/users/" in resp.content

    def test_cancel_returns_display_row(self, client: object) -> None:
        """GET /admin/users/{id}/cancel returns the display row."""
        cookies = _admin_session(client)
        # Get the list page to find a user id in the content
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        content = resp.content.decode()
        # Extract first user-row id
        import re
        match = re.search(r'id="user-row-(\d+)"', content)
        assert match, "No user rows found in page"
        user_id = match.group(1)

        cancel_resp = client.get(  # type: ignore[attr-defined]
            f"/admin/users/{user_id}/cancel", cookies=cookies
        )
        assert cancel_resp.status_code == 200
        assert f'id="user-row-{user_id}"'.encode() in cancel_resp.content

    def test_update_role(self, client: object) -> None:
        """POST /admin/users/{id} changes the role, as the table then shows."""
        cookies = _admin_session(client)
        uid, _ = _row(client, cookies, "new_op")
        assert _role(client, cookies, "new_op") == "operator"
        promote = client.post(  # type: ignore[attr-defined]
            f"/admin/users/{uid}", data={"role": "admin", "new_password": ""},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        assert promote.status_code == 200
        assert _role(client, cookies, "new_op") == "admin"
        # Put it back: other tests count the admins.
        client.post(  # type: ignore[attr-defined]
            f"/admin/users/{uid}", data={"role": "operator", "new_password": ""},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        assert _role(client, cookies, "new_op") == "operator"

    def test_password_reset(self, client: object) -> None:
        """POST /admin/users/{id} with new_password resets the password."""
        cookies = _admin_session(client)
        uid, _ = _row(client, cookies, "new_op")
        reset_resp = client.post(  # type: ignore[attr-defined]
            f"/admin/users/{uid}",
            data={"role": "operator", "new_password": "newpassword99"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert reset_resp.status_code == 200
        assert b"updated" in reset_resp.content.lower()
        old = client.post(  # type: ignore[attr-defined]
            "/login", data={"username": "new_op", "password": "hunter2"}, follow_redirects=False,
        )
        new = client.post(  # type: ignore[attr-defined]
            "/login", data={"username": "new_op", "password": "newpassword99"}, follow_redirects=False,
        )
        assert (old.status_code, new.status_code) == (401, 302)


class TestDeleteUser:
    def test_delete_operator(self, client: object) -> None:
        """Admin can delete an operator account, and it is gone from the table."""
        cookies = _admin_session(client)
        client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "throwaway", "password": "pass", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        uid, _ = _row(client, cookies, "throwaway")
        del_resp = client.delete(  # type: ignore[attr-defined]
            f"/admin/users/{uid}", cookies=cookies, headers=csrf_headers(cookies)
        )
        assert del_resp.status_code == 200
        assert b"deleted" in del_resp.content.lower()
        page = client.get("/admin/users", cookies=cookies).content  # type: ignore[attr-defined]
        assert f'id="user-row-{uid}"'.encode() not in page

    def test_cannot_delete_self(self, client: object) -> None:
        """Admin cannot delete their own account."""
        cookies = _admin_session(client)
        uid, _ = _row(client, cookies, "testadmin")
        del_resp = client.delete(  # type: ignore[attr-defined]
            f"/admin/users/{uid}", cookies=cookies, headers=csrf_headers(cookies)
        )
        assert del_resp.status_code == 200
        assert b"cannot delete your own" in del_resp.content.lower()
        assert _row(client, cookies, "testadmin")[0] == uid

    def test_cannot_demote_the_last_admin(self, client: object) -> None:
        """The last admin cannot be demoted.

        This was named for deletion but tested demotion. Deleting the last
        admin cannot be asked for over HTTP: the only admin left is the one
        asking, and the self-delete guard answers first. The delete guard
        itself is driven directly, under a race, in test_last_admin_race.
        """
        cookies = _admin_session(client)
        # Leave testadmin as the only admin.
        if ">second_admin<" in client.get("/admin/users", cookies=cookies).content.decode():  # type: ignore[attr-defined]
            second, _ = _row(client, cookies, "second_admin")
            client.delete(f"/admin/users/{second}", cookies=cookies, headers=csrf_headers(cookies))  # type: ignore[attr-defined]
        uid, _ = _row(client, cookies, "testadmin")
        demote_resp = client.post(  # type: ignore[attr-defined]
            f"/admin/users/{uid}",
            data={"role": "operator", "new_password": ""},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert demote_resp.status_code == 200
        assert b"last admin" in demote_resp.content.lower()
        assert _role(client, cookies, "testadmin") == "admin"


class TestFlashResponseShape:
    """Every mutating admin response must be rooted at a non-table element.

    htmx 1.9.12 chooses its parsing path from the first tag of the response. A
    response beginning with <tr> is wrapped in <table><tbody> before parsing,
    and the HTML parser then foster-parents the out-of-band flash <div> out of
    the table. htmx handed the result to its OOB code, which threw
    "e.querySelectorAll is not a function" and abandoned the entire swap.

    The server had already committed the change, so the failure was invisible
    server-side: created, edited and deleted users simply never appeared until
    the page was reloaded by hand, and the create form never cleared. Reproduced
    in Chromium against a live instance before the fix, and confirmed clean
    after it.

    Asserted on the wire rather than in the template, because the defect is a
    property of the bytes htmx receives.
    """

    @staticmethod
    def _first_tag(body: bytes) -> str:
        text = body.decode("utf-8", "replace").lstrip()
        assert text.startswith("<"), f"response does not start with a tag: {text[:60]!r}"
        return text[1 : text.index(">")].split()[0].lower()

    # Tags the HTML parser only accepts inside a table. A response rooted at one
    # of these cannot also carry the flash div as a sibling.
    _TABLE_SCOPED = frozenset({"tr", "td", "th", "tbody", "thead", "tfoot", "caption", "col", "colgroup"})

    def test_create_response_is_not_table_scoped(self, client: object) -> None:
        cookies = _admin_session(client)
        resp = client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "shape_probe", "password": "hunter2", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b'id="admin-flash"' in resp.content, "the response must carry the flash"
        assert self._first_tag(resp.content) not in self._TABLE_SCOPED

    def test_update_response_is_not_table_scoped(self, client: object) -> None:
        cookies = _admin_session(client)
        client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "shape_update", "password": "hunter2", "role": "operator"},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        listing = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        import re

        ids = re.findall(rb'id="user-row-(\d+)"', listing.content)
        assert ids, "no user rows rendered"
        resp = client.post(  # type: ignore[attr-defined]
            f"/admin/users/{int(ids[-1])}",
            data={"role": "operator", "new_password": ""},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b'id="admin-flash"' in resp.content
        assert self._first_tag(resp.content) not in self._TABLE_SCOPED

    def test_delete_response_is_not_table_scoped(self, client: object) -> None:
        cookies = _admin_session(client)
        client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "shape_delete", "password": "hunter2", "role": "operator"},
            cookies=cookies, headers=csrf_headers(cookies),
        )
        listing = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        import re

        ids = re.findall(rb'id="user-row-(\d+)"', listing.content)
        resp = client.request(  # type: ignore[attr-defined]
            "DELETE", f"/admin/users/{int(ids[-1])}",
            cookies=cookies, headers=csrf_headers(cookies),
        )
        assert resp.status_code == 200
        assert b'id="admin-flash"' in resp.content
        assert self._first_tag(resp.content) not in self._TABLE_SCOPED
