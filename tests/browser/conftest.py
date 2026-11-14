"""The real console, booted on a free port and driven in Chromium under the policy it sends (SPC-199).

The behaviour tests in this directory drive what the page's scripts do, through the DOM an operator touches, so they
pass whether the script is an inline block or a static file. Each one also fails on a Content Security Policy
violation, an uncaught exception or a console error, so under the strict policy a behaviour still wired through an
inline handler, an inline block or an htmx eval fails here rather than going quiet in the browser.

Fragments that need data no throwaway instance holds (UDL, GCAT, a finished evaluation) are rendered in this process
from the real templates and handed to the live page by an intercepted htmx request, so they land the way htmx lands
every fragment and run under the live page's policy.

Chromium is provisioned in the development image and not in the CI runner. Without it these tests skip, saying so;
set SPECTRE_BROWSER_TESTS=require to make a missing browser a failure.
"""

from __future__ import annotations

import itertools
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[2]
ADMIN_USER = "browser_admin"
ADMIN_PASS = "browser-probe-password-not-a-secret"

#: Recorded in the page before any of its own script runs: every policy violation, by directive and blocked source.
_WATCH = """
window.__spectreViolations = [];
document.addEventListener('securitypolicyviolation', function (e) {
  window.__spectreViolations.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline') + ' ' + (e.sample || ''));
});
"""

_SPLASH_SEEN = "try { sessionStorage.setItem('spectre-splash-seen', '1'); } catch (e) {}"

_fixture_ids = itertools.count(1)

#: A form post from inside the page, so it carries the session cookie and the CSRF token as htmx would.
_FETCH = """([path, form]) => fetch(path, {
  method: 'POST',
  headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content},
  body: new URLSearchParams(form),
}).then(r => r.text().then(t => [r.status, t]))"""


def post(page: Any, path: str, form: dict[str, str]) -> str:
    """POST *form* to *path* from the signed-in *page* and return the body; anything but 200 fails."""
    status, text = page.evaluate(_FETCH, [path, form])
    assert status == 200, f"{path} answered {status}"
    return str(text)


def seed(browser: Browser, posts: list[tuple[str, dict[str, str]]]) -> None:
    """Make each post in the module's signed-in session before its tests run."""
    context = browser.browser.new_context(storage_state=browser.signed_in)
    page = context.new_page()
    page.goto(f"{browser.base_url}/")
    for path, form in posts:
        post(page, path, form)
    context.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _provisioned_chromium() -> str | None:
    """A Chromium already in the browsers directory, whatever build Playwright itself expects.

    The directory is versioned, so the path is discovered rather than pinned.
    """
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    patterns = ("chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell",
                "chromium-*/chrome-linux*/chrome")
    for pattern in patterns:
        found = sorted(root.glob(pattern)) if root.is_dir() else []
        if found:
            return str(found[-1])
    return None


def _launch(sync_api: Any) -> tuple[Any, Any]:
    """Start Playwright and Chromium, or skip saying why: a missing browser is not a pass."""
    pw = sync_api.sync_playwright().start()
    options: dict[str, Any] = {"args": ["--no-sandbox"]}
    executable = _provisioned_chromium()
    if executable:
        options["executable_path"] = executable
    try:
        return pw, pw.chromium.launch(**options)
    except sync_api.Error as exc:
        pw.stop()
        if os.environ.get("SPECTRE_BROWSER_TESTS") == "require":
            pytest.fail(f"SPECTRE_BROWSER_TESTS=require and Chromium would not start: {exc}")
        pytest.skip(f"Chromium would not start, so the browser behaviour tests did not run: {str(exc)[:200]}")


def _wait_until_ready(base_url: str, proc: subprocess.Popen[bytes], log: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the console exited during boot:\n{log.read_text('utf-8', 'replace')[-2000:]}")
        try:
            with urllib.request.urlopen(f"{base_url}/login", timeout=2):  # noqa: S310
                return
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.3)
    raise RuntimeError("the console did not answer within 60 s")


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """The console in a process of its own, with its own database and data directory."""
    tmp = Path(tempfile.mkdtemp(prefix="spectre-browser-"))
    data = tmp / "data"
    data.mkdir()
    port = _free_port()
    env = {
        **os.environ,
        "SECRET_KEY": "browser-probe-secret-key-not-a-secret",
        "SPECTRE_ADMIN_USER": ADMIN_USER,
        "SPECTRE_ADMIN_PASS": ADMIN_PASS,
        "SPECTRE_SQLITE_DIR": str(data),
        "SPECTRE_DATA_DIR": str(data),
        "DATABASE_URL": f"sqlite+aiosqlite:///{data}/spectre-browser.db",
        "SPECTRE_SESSION_COOKIE_SECURE": "false",
    }
    log = tmp / "server.log"
    with log.open("wb") as out:
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "uvicorn", "spectre.web.app:app", "--host", "127.0.0.1", "--port", str(port),
             "--log-level", "warning"],
            cwd=_REPO, env=env, stdout=out, stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_until_ready(base_url, proc, log)
            yield base_url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)


@dataclass
class Browser:
    """One Chromium for a module, and the signed-in state each test's context starts from."""

    browser: Any
    base_url: str
    signed_in: dict[str, Any]


@pytest.fixture(scope="module")
def browser(request: pytest.FixtureRequest) -> Iterator[Browser]:
    """Chromium, or a skip that names why: a missing browser is not a pass."""
    sync_api = pytest.importorskip("playwright.sync_api")
    pw, chromium = _launch(sync_api)
    base_url = request.getfixturevalue("live_server")
    try:
        context = chromium.new_context()
        page = context.new_page()
        page.goto(f"{base_url}/login")
        page.fill('input[name="username"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{base_url}/")
        signed_in = context.storage_state()
        context.close()
        yield Browser(chromium, base_url, signed_in)
    finally:
        chromium.close()
        pw.stop()


@dataclass
class Console:
    """A signed-in page, recording what the browser refused or threw."""

    page: Any
    base_url: str
    errors: list[str] = field(default_factory=list)

    def open(self, path: str = "/") -> Any:
        self.page.goto(f"{self.base_url}{path}")
        self.page.wait_for_load_state("networkidle")
        return self.page

    def inject(self, html: str, target: str, swap: str = "innerHTML") -> None:
        """Land *html* in *target* through an htmx request, as every fragment lands."""
        url = f"/__browser_fixture/{next(_fixture_ids)}"
        self.page.route(
            f"**{url}",
            lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html),
        )
        self.page.evaluate("([u, t, s]) => htmx.ajax('GET', u, {target: t, swap: s})", [url, target, swap])
        self.page.wait_for_timeout(250)

    def violations(self) -> list[str]:
        return list(self.page.evaluate("window.__spectreViolations || []"))

    def problems(self) -> list[str]:
        """Every policy violation, uncaught exception and console error so far."""
        return self.violations() + self.errors


def _new_console(browser: Browser, *, splash_seen: bool) -> tuple[Any, Console]:
    context = browser.browser.new_context(storage_state=browser.signed_in)
    context.add_init_script(_WATCH)
    if splash_seen:
        context.add_init_script(_SPLASH_SEEN)
    page = context.new_page()
    console = Console(page, browser.base_url)
    page.on("pageerror", lambda exc: console.errors.append(f"uncaught: {exc}"))
    page.on("console", lambda msg: console.errors.append(f"console: {msg.text}") if msg.type == "error" else None)
    page.on("dialog", lambda dialog: dialog.accept())
    return context, console


@pytest.fixture
def console(browser: Browser) -> Iterator[Console]:
    """A fresh signed-in context per test, the splash already seen this session."""
    context, page_console = _new_console(browser, splash_seen=True)
    yield page_console
    context.close()


@pytest.fixture
def first_visit(browser: Browser) -> Iterator[Console]:
    """A fresh signed-in context that has not seen the splash this session."""
    context, page_console = _new_console(browser, splash_seen=False)
    yield page_console
    context.close()
