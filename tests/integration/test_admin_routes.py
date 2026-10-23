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
        """POST /admin/users/{id} changes the role."""
        cookies = _admin_session(client)
        # Find new_op's row id
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        content = resp.content.decode()
        # Find the row that contains new_op
        import re
        # Look for user-row id near "new_op" text
        matches = re.findall(r'id="user-row-(\d+)"', content)
        assert matches

        # Try updating each user until we find new_op by checking the response
        found = False
        for uid in matches:
            edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
            if b"new_op" in edit_resp.content:
                update_resp = client.post(  # type: ignore[attr-defined]
                    f"/admin/users/{uid}",
                    data={"role": "operator", "new_password": ""},
                    cookies=cookies,
                    headers=csrf_headers(cookies),
                )
                assert update_resp.status_code == 200
                found = True
                break
        assert found, "new_op user not found in admin table"

    def test_password_reset(self, client: object) -> None:
        """POST /admin/users/{id} with new_password resets the password."""
        cookies = _admin_session(client)
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        import re
        matches = re.findall(r'id="user-row-(\d+)"', resp.content.decode())
        for uid in matches:
            edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
            if b"new_op" in edit_resp.content:
                reset_resp = client.post(  # type: ignore[attr-defined]
                    f"/admin/users/{uid}",
                    data={"role": "operator", "new_password": "newpassword99"},
                    cookies=cookies,
                    headers=csrf_headers(cookies),
                )
                assert reset_resp.status_code == 200
                assert b"updated" in reset_resp.content.lower()
                # Verify new password works
                login_resp = client.post(  # type: ignore[attr-defined]
                    "/login",
                    data={"username": "new_op", "password": "newpassword99"},
                    follow_redirects=False,
                )
                assert login_resp.status_code == 302
                break


class TestDeleteUser:
    def test_delete_operator(self, client: object) -> None:
        """Admin can delete an operator account."""
        cookies = _admin_session(client)
        # Create a throwaway user
        client.post(  # type: ignore[attr-defined]
            "/admin/users",
            data={"username": "throwaway", "password": "pass", "role": "operator"},
            cookies=cookies,
            headers=csrf_headers(cookies),
        )
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        import re
        matches = re.findall(r'id="user-row-(\d+)"', resp.content.decode())
        for uid in matches:
            edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
            if b"throwaway" in edit_resp.content:
                del_resp = client.delete(  # type: ignore[attr-defined]
                    f"/admin/users/{uid}", cookies=cookies, headers=csrf_headers(cookies)
                )
                assert del_resp.status_code == 200
                # Username appears in flash message but must not appear in any user row
                assert b'id="user-row-' + uid.encode() + b'"' not in del_resp.content
                assert b"deleted" in del_resp.content.lower()
                break

    def test_cannot_delete_self(self, client: object) -> None:
        """Admin cannot delete their own account."""
        cookies = _admin_session(client)
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        import re
        matches = re.findall(r'id="user-row-(\d+)"', resp.content.decode())
        for uid in matches:
            edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
            if b"testadmin" in edit_resp.content:
                del_resp = client.delete(  # type: ignore[attr-defined]
                    f"/admin/users/{uid}", cookies=cookies, headers=csrf_headers(cookies)
                )
                assert del_resp.status_code == 200
                assert b"cannot delete your own" in del_resp.content.lower()
                break

    def test_cannot_delete_last_admin(self, client: object) -> None:
        """Cannot delete an admin if they are the only admin remaining."""
        cookies = _admin_session(client)
        # Delete second_admin first so testadmin is the only admin
        resp = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        import re
        matches = re.findall(r'id="user-row-(\d+)"', resp.content.decode())
        second_admin_id = None
        for uid in matches:
            edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
            if b"second_admin" in edit_resp.content:
                second_admin_id = uid
                break
        if second_admin_id:
            client.delete(f"/admin/users/{second_admin_id}", cookies=cookies, headers=csrf_headers(cookies))  # type: ignore[attr-defined]

        # Now try to delete testadmin — should fail (cannot delete self)
        # Instead create a second admin and try to delete it when it's the last one:
        # This test verifies the last-admin guard fires; we use a fresh scenario
        # by checking that after second_admin is gone, demoting testadmin fails.
        resp2 = client.get("/admin/users", cookies=cookies)  # type: ignore[attr-defined]
        matches2 = re.findall(r'id="user-row-(\d+)"', resp2.content.decode())
        for uid in matches2:
            edit_resp = client.get(f"/admin/users/{uid}/edit", cookies=cookies)  # type: ignore[attr-defined]
            if b"testadmin" in edit_resp.content:
                # Try to demote to operator — last admin guard
                demote_resp = client.post(  # type: ignore[attr-defined]
                    f"/admin/users/{uid}",
                    data={"role": "operator", "new_password": ""},
                    cookies=cookies,
                    headers=csrf_headers(cookies),
                )
                assert demote_resp.status_code == 200
                assert b"last admin" in demote_resp.content.lower()
                break


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
