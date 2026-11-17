"""The request line, through the app, read back from stdout (App Store logging standard, 0.48.4).

Body "GET /path 200"; attributes carry the method, the path (never the query
string), the status, the duration, the request id and the platform's asserted
user. No Authorization, Cookie, Set-Cookie, CSRF or session value, and no query
string, appears in any line the request produces.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spectre.web.json_logging import configure_logging
from tests._log_standard import standard_lines


@pytest.fixture(autouse=True)
def json_stdout() -> Iterator[None]:
    """The stdout handler the entrypoint installs, for this module only.

    Under pytest the lifespan leaves the runner's own handlers in charge, so
    the handler is put on here, as the entrypoint would, and taken off after.
    """
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    libraries = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    configure_logging("INFO")
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, library_level in libraries.items():
        logging.getLogger(name).setLevel(library_level)


def _access_lines(out: str) -> list[dict[str, Any]]:
    return [line for line in standard_lines(out) if line["attributes"].get("logger.name") == "spectre.access"]


class TestTheRequestLine:
    def test_a_request_is_one_standard_line_on_stdout(
        self, client: TestClient, capsys: pytest.CaptureFixture[str],
    ) -> None:
        capsys.readouterr()
        client.get("/login", headers={"X-Request-Id": "req-0484-a", "X-Auth-Request-Email": "analyst@example.org"})
        captured = capsys.readouterr()
        assert captured.err == ""
        (line,) = [ln for ln in _access_lines(captured.out) if ln["attributes"]["url.path"] == "/login"]
        assert line["body"] == "GET /login 200"
        assert (line["severity_text"], line["severity_number"]) == ("INFO", 9)
        attributes = line["attributes"]
        assert attributes["http.request.method"] == "GET"
        assert attributes["http.response.status_code"] == 200
        assert isinstance(attributes["http.server.request.duration"], float)
        assert 0 < attributes["http.server.request.duration"] < 60
        assert attributes["http.request.header.x-request-id"] == "req-0484-a"
        assert attributes["user.email"] == "analyst@example.org"

    def test_absent_headers_are_absent_attributes(self, client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        client.get("/login")
        (line,) = _access_lines(capsys.readouterr().out)
        assert "user.email" not in line["attributes"]
        assert "http.request.header.x-request-id" not in line["attributes"]

    def test_a_probe_writes_no_request_line(self, client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        client.get("/healthz")
        assert _access_lines(capsys.readouterr().out) == []

    def test_the_status_is_the_one_returned(self, client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
        capsys.readouterr()
        status = client.get("/no-such-page-0484").status_code
        (line,) = _access_lines(capsys.readouterr().out)
        assert line["body"] == f"GET /no-such-page-0484 {status}"
        assert line["attributes"]["http.response.status_code"] == status


class TestNoCredentialReachesTheLog:
    """Each credential the request or its response carries, sent with a marker, and none found."""

    def test_no_header_cookie_token_or_query_string_appears(
        self, client: TestClient, capsys: pytest.CaptureFixture[str],
    ) -> None:
        capsys.readouterr()
        client.get(
            "/login?next=QUERYMARK1&token=QUERYMARK2",
            headers={
                "Authorization": "Bearer AUTHMARK3",
                "Cookie": "spectre_session=COOKIEMARK4; other=COOKIEMARK5",
                "Set-Cookie": "spectre_session=SETCOOKIEMARK6",
                "X-CSRF-Token": "CSRFMARK7",
                "X-Request-Id": "req-0484-b",
            },
        )
        signed_in = client.post(
            "/login?redirect=QUERYMARK8",
            data={"username": "testadmin", "password": "testpass123"},
            headers={"Authorization": "Basic AUTHMARK9"},
            follow_redirects=False,
        )
        session_value = signed_in.cookies.get("spectre_session")
        assert session_value, "the sign-in set a session cookie to look for"
        out = capsys.readouterr().out
        lines = standard_lines(out)
        assert any(line["body"].startswith("POST /login ") for line in lines)
        for marker in ("QUERYMARK1", "QUERYMARK2", "AUTHMARK3", "COOKIEMARK4", "COOKIEMARK5", "SETCOOKIEMARK6",
                       "CSRFMARK7", "QUERYMARK8", "AUTHMARK9", "testpass123", session_value):
            assert marker not in out, marker
        assert "?" not in "".join(line["attributes"].get("url.path", "") for line in lines)
