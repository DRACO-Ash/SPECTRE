"""The real process, started as the image starts it: JSON lines on stdout, nothing on stderr.

The App Store's logging check starts the container and reads both streams.
Before 0.48.4 SPECTRE wrote nothing to stdout and its boot refusal to stderr as
a traceback. These tests run ``python -m spectre.web._entrypoint`` itself,
because only a real process shows what uvicorn, Python and the app write
before any test harness could intercept it.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import spectre
from tests._log_standard import standard_lines

# The directory that holds the spectre package, so ``-m`` finds it in a source
# checkout and in the unpacked App Store package alike.
_ROOT = Path(spectre.__file__).resolve().parents[1]
_BOOT_TIMEOUT_S = 90.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _environment(tmp_path: Path, port: int, **overrides: str) -> dict[str, str]:
    """The process's environment: this one, with storage in *tmp_path* and no signing key unless given.

    SECRET_KEY is set empty rather than removed, so a developer's .env file,
    which never overrides a variable already present, cannot supply one.
    """
    env = dict(os.environ)
    env.update({
        "PORT": str(port),
        "SECRET_KEY": "",
        "APPSTORE_DAST_SCAN": "",
        "SPECTRE_DATA_DIR": str(tmp_path / "data"),
        "SPECTRE_SQLITE_DIR": str(tmp_path / "sqlite"),
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'sqlite' / 'spectre.db'}",
        "PYTHONUNBUFFERED": "1",
    })
    env.pop("PYTHONWARNINGS", None)
    env.update(overrides)
    return env


def _start(env: dict[str, str]) -> subprocess.Popen[str]:
    # A fixed argument list: this interpreter and the module, no shell and no outside input.
    return subprocess.Popen(
        [sys.executable, "-m", "spectre.web._entrypoint"],
        cwd=_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _wait_for_200(process: subprocess.Popen[str], port: int) -> int:
    deadline = time.monotonic() + _BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return -1
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/",
                headers={"X-Request-Id": "req-boot-0484", "X-Auth-Request-Email": "probe@example.org"},
            )
            # A fixed http URL on loopback, the port this test chose.
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                return int(response.status)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    return 0


def test_without_a_signing_key_it_serves_on_a_throwaway_and_says_so(tmp_path: Path) -> None:
    """The platform's Logging check starts the image with no environment: it must find SPECTRE answering."""
    port = _free_port()
    process = _start(_environment(tmp_path, port))
    try:
        status = _wait_for_200(process, port)
    finally:
        process.terminate()
        out, err = process.communicate(timeout=30)
    assert status == 200, out
    assert err == "", err
    lines = standard_lines(out)
    warn = [line for line in lines if line["attributes"].get("spectre.boot.signing_key") == "ephemeral"]
    assert len(warn) == 1, out
    assert (warn[0]["severity_text"], warn[0]["severity_number"]) == ("WARN", 13)
    assert "SECRET_KEY is not set" in warn[0]["body"]


def test_a_placeholder_signing_key_is_refused_in_one_fatal_json_line(tmp_path: Path) -> None:
    process = _start(_environment(tmp_path, _free_port(), SECRET_KEY="changeme"))
    out, err = process.communicate(timeout=_BOOT_TIMEOUT_S)
    assert process.returncode != 0, out
    assert err == "", err
    lines = standard_lines(out)
    assert lines, "the refusal must be written, to stdout"
    fatal = lines[-1]
    assert (fatal["severity_text"], fatal["severity_number"]) == ("FATAL", 21)
    assert "SECRET_KEY" in fatal["body"]
    assert fatal["attributes"]["config.setting"] == "SECRET_KEY"


@pytest.mark.parametrize("key_source", ["SECRET_KEY", "APPSTORE_DAST_SCAN"])
def test_with_a_key_it_serves_and_logs_only_json_to_stdout(tmp_path: Path, key_source: str) -> None:
    overrides = (
        {"SECRET_KEY": secrets.token_urlsafe(32)} if key_source == "SECRET_KEY" else {"APPSTORE_DAST_SCAN": "true"}
    )
    port = _free_port()
    process = _start(_environment(tmp_path, port, **overrides))
    try:
        status = _wait_for_200(process, port)
    finally:
        process.terminate()
        out, err = process.communicate(timeout=30)
    assert status == 200, out
    assert err == "", err
    lines = standard_lines(out)
    requests = [line for line in lines if line["body"] == "GET / 200"]
    assert requests, out
    attributes = requests[-1]["attributes"]
    assert attributes["http.request.header.x-request-id"] == "req-boot-0484"
    assert attributes["user.email"] == "probe@example.org"
    assert any(line["attributes"].get("logger.name") == "uvicorn.error" for line in lines), "uvicorn's lines are JSON"
    if key_source == "APPSTORE_DAST_SCAN":
        assert any(line["severity_text"] == "WARN" and "THROWAWAY" in line["body"] for line in lines)
