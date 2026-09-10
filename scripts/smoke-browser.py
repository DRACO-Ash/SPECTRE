#!/usr/bin/env python3
"""Drive the real console in a real browser and fail on anything it reports.

Why this exists
---------------
Two defects reached production returning HTTP 200 with a working server and a
broken page, and 850 server-side tests could see neither:

  * Creating a user committed the row, returned the new table, and then threw
    ``TypeError: e.querySelectorAll is not a function`` in the browser, so the
    swap was abandoned and the operator saw nothing happen.
  * The sidebar "Return to Operations" form submitted without a CSRF token and
    answered 403, stranding the operator inside training mode.

Both are failures of what the browser did with a correct response. A status
code cannot see them. A console-error assertion sees both immediately.

What it does
------------
Boots the application itself on a free port against a throwaway SQLite
database, drives the paths an operator actually walks, and fails on any
uncaught exception, any HTMX swap error, or any same-origin console error.

It is deliberately loud rather than skippable. A probe that quietly does
nothing when its browser is missing is worse than no probe, because the run
still goes green. Set SMOKE_BROWSER_SKIP=1 to skip it on purpose; anything
else that goes wrong is a failure.

Usage
-----
    python3 scripts/smoke-browser.py            # boots its own instance
    python3 scripts/smoke-browser.py --base-url http://127.0.0.1:8099
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ADMIN_USER = "smoke_admin"
_ADMIN_PASS = "smoke-probe-password-not-a-secret"
_SECRET_KEY = "smoke-probe-secret-key-not-a-secret"

# Network failures reaching outside the app are the sandbox or the network, not
# a defect in the page. Everything else, including any same-origin request that
# fails, is ours and fails the probe.
_EXTERNAL_NETWORK_MARKERS = (
    "net::err_connection_reset",
    "net::err_name_not_resolved",
    "net::err_internet_disconnected",
    "net::err_connection_refused",
    "net::err_blocked_by_client",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_chromium() -> str | None:
    """Return an explicit Chromium path, or None to let Playwright decide.

    The pre-provisioned browser directory is versioned, so the path is
    discovered rather than pinned; a hard-coded version would rot silently.
    """
    for root in (Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")),):
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
            if candidate.is_file():
                return str(candidate)
    return None


class _AppUnderTest:
    """Boot the application on a free port against a throwaway database."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._tmp = tempfile.mkdtemp(prefix="spectre-smoke-")
        self._proc: subprocess.Popen[bytes] | None = None
        self.log_path = Path(self._tmp) / "server.log"

    def __enter__(self) -> _AppUnderTest:
        data_dir = Path(self._tmp) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "SECRET_KEY": _SECRET_KEY,
            "SPECTRE_ADMIN_USER": _ADMIN_USER,
            "SPECTRE_ADMIN_PASS": _ADMIN_PASS,
            "SPECTRE_SQLITE_DIR": str(data_dir),
            "SPECTRE_DATA_DIR": str(data_dir),
            "SPECTRE_SESSION_COOKIE_SECURE": "false",
            "PORT": str(self.port),
        }
        log = self.log_path.open("wb")
        self._proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "uvicorn", "spectre.web.app:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=_REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        self._wait_until_ready()
        return self

    def _wait_until_ready(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(
                    f"the application exited during boot:\n{self.log_path.read_text('utf-8', 'replace')[-2000:]}"
                )
            try:
                with urllib.request.urlopen(f"{self.base_url}/login", timeout=2):  # noqa: S310
                    return
            except (urllib.error.URLError, OSError, TimeoutError):
                time.sleep(0.5)
        raise RuntimeError(f"the application did not answer within {timeout:.0f}s")

    def __exit__(self, *_exc: object) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        shutil.rmtree(self._tmp, ignore_errors=True)


class _Recorder:
    """Collect everything the browser complains about, classified."""

    def __init__(self) -> None:
        self.fatal: list[str] = []
        self.ignored: list[str] = []

    def attach(self, page: object) -> None:
        page.on("console", self._on_console)  # type: ignore[attr-defined]
        page.on("pageerror", lambda exc: self.fatal.append(f"uncaught exception: {exc}"))  # type: ignore[attr-defined]

    def _on_console(self, message: object) -> None:
        if message.type != "error":  # type: ignore[attr-defined]
            return
        text = str(message.text)  # type: ignore[attr-defined]
        lowered = text.lower()
        if any(marker in lowered for marker in _EXTERNAL_NETWORK_MARKERS):
            self.ignored.append(text)
            return
        self.fatal.append(f"console error: {text}")

    def drain(self, step: str) -> list[str]:
        found = [f"[{step}] {entry}" for entry in self.fatal]
        self.fatal.clear()
        return found


async def _run(base_url: str) -> list[str]:
    from playwright.async_api import async_playwright

    failures: list[str] = []
    executable = _find_chromium()
    launch: dict[str, object] = {"args": ["--no-sandbox"]}
    if executable:
        launch["executable_path"] = executable

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch)  # type: ignore[arg-type]
        page = await browser.new_page()
        rec = _Recorder()
        rec.attach(page)
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        def check(step: str, condition: bool, detail: str) -> None:
            failures.extend(rec.drain(step))
            if not condition:
                failures.append(f"[{step}] {detail}")

        # 1. Sign in.
        await page.goto(f"{base_url}/login")
        await page.fill('input[name="username"]', _ADMIN_USER)
        await page.fill('input[name="password"]', _ADMIN_PASS)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        check("login", page.url.rstrip("/") == base_url.rstrip("/"),
              f"expected the console at {base_url}, landed on {page.url}")

        # 2. The operator console renders.
        check("console", await page.locator("body").count() == 1, "no body rendered")

        # 3. Create a user and see it appear WITHOUT a reload. This is the
        #    exact motion that failed silently in production.
        await page.goto(f"{base_url}/admin/users")
        await page.wait_for_load_state("networkidle")
        before = await page.locator("#user-tbody tr").count()
        await page.fill("#new-username", "smoke_operator")
        await page.fill("#new-password", "smoke-operator-password")
        await page.select_option("#new-role", "operator")
        await page.click('button:has-text("Create User")')
        await page.wait_for_timeout(1500)
        after = await page.locator("#user-tbody tr").count()
        flash = (await page.locator("#admin-flash").inner_text()).strip()
        check("admin-create", after == before + 1,
              f"the new row never appeared without a reload ({before} -> {after})")
        check("admin-create-flash", bool(flash), "no confirmation message was shown")
        check("admin-create-reset", await page.input_value("#new-username") == "",
              "the create form did not clear after a successful submit")

        # 4. Delete it again, the other flash-carrying swap.
        row = page.locator("#user-tbody tr").nth(after - 1).locator('button:has-text("Delete")')
        if await row.count():
            await row.first.click()
            await page.wait_for_timeout(1500)
            check("admin-delete", await page.locator("#user-tbody tr").count() == before,
                  "the deleted row did not disappear without a reload")

        # 5. Enter training and leave it by the sidebar button, which is the
        #    form that answered 403 in production.
        await page.goto(f"{base_url}/training")
        await page.wait_for_load_state("networkidle")
        leave = page.locator('form[action="/training/leave"]')
        count = await leave.count()
        check("training-enter", count > 0, "no Return to Operations control on the training page")
        if count:
            await leave.nth(count - 1).locator('button[type="submit"]').click()
            await page.wait_for_load_state("networkidle")
            body = await page.content()
            check("training-leave", "CSRF validation failed" not in body,
                  "leaving training mode was rejected by the CSRF guard")
            check("training-leave-lands", page.url.rstrip("/") == base_url.rstrip("/"),
                  f"leaving training did not return to the console, landed on {page.url}")

        # 6. Sign out from the admin page, the second CSRF-less form found.
        await page.goto(f"{base_url}/admin/users")
        await page.wait_for_load_state("networkidle")
        await page.locator('form[action="/logout"] button[type="submit"]').first.click()
        await page.wait_for_load_state("networkidle")
        body = await page.content()
        check("sign-out", "CSRF validation failed" not in body,
              "signing out was rejected by the CSRF guard")

        if rec.ignored:
            print(f"  {len(rec.ignored)} external network message(s) ignored, e.g. {rec.ignored[0][:80]}")
        await browser.close()
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="probe a running instance instead of booting one")
    args = parser.parse_args()

    if os.environ.get("SMOKE_BROWSER_SKIP") == "1":
        print("  SKIPPED by SMOKE_BROWSER_SKIP=1")
        return 0

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  FAIL  playwright is not installed. It is in requirements-dev.txt.")
        print("        This probe does not skip itself: a silent skip is how the")
        print("        defects it exists to catch reached production.")
        return 1

    print("== Browser smoke probe ==")
    if args.base_url:
        failures = asyncio.run(_run(args.base_url))
    else:
        with _AppUnderTest() as app:
            print(f"  booted a throwaway instance on {app.base_url}")
            failures = asyncio.run(_run(app.base_url))

    if failures:
        print(f"  FAIL  {len(failures)} problem(s) the browser reported:")
        for failure in failures:
            print(f"    {failure}")
        return 1
    print("  PASS  login, admin create and delete, training exit and sign out, no console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
