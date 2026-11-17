"""The training page's mechanics in Chromium, under the console's policy (0.47.0 training audit).

● F0: the console frame loaded once and kept showing the first scenario's lists.
● X3: the console's Manoeuvre Start stayed blank, so the tools ran at today.
● 1-18, G-4: points, level and lists were stale until a manual reload.
● 3-3: an answer typed under an unticked box scored nothing.
● 1-22: the sticky banner slid over the header's Return to Operations button.
● 1-23: the console inside the frame offered a Training link into training again.
● 2-5: the workflow steps ran together in one paragraph.
"""

from __future__ import annotations

import time
from typing import Any

from tests.browser.conftest import Console

_CADET = "cadet_01_geo_stationkeeping"
_CADET_2 = "cadet_02_leo_debris_conjunction"


def _training(console: Console) -> Any:
    page = console.open("/training")
    # A selector wait, not wait_for_function: a string predicate is re-evaluated with eval, which the policy refuses
    # whenever the dashboard has not loaded on the first look.
    page.wait_for_selector("#tpanel-dashboard .spinner", state="detached", timeout=30000)
    return page


def _start(page: Any, scenario_id: str) -> None:
    """Open *scenario_id* on the Free-Play tab and start a scored attempt."""
    page.click("#tnav-scenarios")
    page.locator(f"#scenario-list button[hx-get='/training/scenario/{scenario_id}']").click()
    page.wait_for_selector(f"#scenario-detail form[hx-post='/training/scenario/{scenario_id}/start']")
    page.click("#scenario-detail form[hx-post$='/start'] button[type=submit]")
    page.wait_for_selector("#scenario-submit-form")


def _open_console(page: Any) -> Any:
    """Show the Console tab and wait for the frame's console to be ready."""
    page.click("#tnav-console")
    frame = page.frame_locator("#training-console-frame")
    frame.locator("#blue-list").wait_for(state="attached", timeout=30000)
    return frame


def _until(page: Any, expression: str, timeout_s: float = 30.0) -> None:
    """Poll *expression* until it is true. wait_for_function re-evaluates a string with eval, which the policy refuses."""
    deadline = time.monotonic() + timeout_s
    while not page.evaluate(expression):
        assert time.monotonic() < deadline, f"never true: {expression}"
        page.wait_for_timeout(100)


def _detail_empty(page: Any) -> None:
    _until(page, "document.getElementById('scenario-detail').innerHTML.trim() === ''")


def _frame_loads(page: Any) -> int:
    return int(page.evaluate("window.__frameLoads || 0"))


def _count_frame_loads(page: Any) -> None:
    page.evaluate("""() => { window.__frameLoads = 0;
      document.getElementById('training-console-frame').addEventListener('load', () => { window.__frameLoads++; }); }""")


class TestTheConsoleFrame:
    def test_it_reloads_after_a_scenario_changes_and_shows_its_lists_and_time(self, console: Console) -> None:
        page = _training(console)
        _count_frame_loads(page)
        _start(page, _CADET)
        frame = _open_console(page)
        assert page.get_attribute("#training-console-frame", "src") == "/?frame=training"
        assert "BLUE-01" in (frame.locator("#blue-list").text_content() or "")
        assert frame.locator("input[name=manoeuvre_start]").input_value().startswith("2025-06-15T00:00")
        loads = _frame_loads(page)

        # Opening the tab again with nothing changed keeps the frame as it is.
        page.click("#tnav-dashboard")
        page.click("#tnav-console")
        page.wait_for_timeout(500)
        assert _frame_loads(page) == loads

        # A new scenario replaces the lists: the frame reloads and shows the new ones only.
        page.click("#tnav-scenarios")
        page.click("#scenario-detail button:has-text('Abandon')")
        _detail_empty(page)
        _start(page, _CADET_2)
        frame = _open_console(page)
        _until(page, f"(window.__frameLoads || 0) > {loads}")
        frame.locator("#blue-list:has-text('BLUE-LEO')").wait_for(state="attached", timeout=30000)
        assert "BLUE-01" not in (frame.locator("#blue-list").text_content() or "")
        assert frame.locator("input[name=manoeuvre_start]").input_value().startswith("2025-06-10T08:00")
        assert problems_free(console)

    def test_the_console_in_the_frame_has_no_training_link(self, console: Console) -> None:
        page = _training(console)
        frame = _open_console(page)
        assert frame.locator("a[href='/training']").count() == 0
        assert problems_free(console)

    def test_the_frame_and_an_operations_tab_each_see_their_own_state(self, console: Console) -> None:
        """Review B1: training's objects and epoch stay in the frame; an operations tab never sees them."""
        page = _training(console)
        _start(page, _CADET)
        sent: list[str] = []
        page.on("request", lambda r: sent.append(r.headers.get("x-spectre-frame", ""))
                if r.frame.parent_frame is not None and r.resource_type in ("xhr", "fetch") else None)
        frame = _open_console(page)
        page.wait_for_timeout(1500)   # the console's own requests on load
        assert "BLUE-01" in (frame.locator("#blue-list").text_content() or "")
        # Every htmx request from the frame names it, once: not "training, training" (review N1).
        assert sent and set(sent) == {"training"}, sent
        assert '"X-Spectre-Frame": "training"' in (frame.locator("body").get_attribute("hx-headers") or "")
        # A fetch() from the frame's scripts is served from the training state too (core.js adds the header).
        fetched = page.frame_locator("#training-console-frame").locator("body").evaluate(
            "() => fetch('/').then(r => r.text())")
        assert 'value="2025-06-15T00:00:00"' in fetched
        # So is a raw XMLHttpRequest (review N1), and the frame says it is a training console (review S4).
        xhr = page.frame_locator("#training-console-frame").locator("body").evaluate("""() => new Promise(done => {
          const r = new XMLHttpRequest(); r.open('GET', '/'); r.onload = () => done(r.responseText); r.send(); })""")
        assert 'value="2025-06-15T00:00:00"' in xhr
        assert frame.locator("#training-console-strip").is_visible()

        operations = page.context.new_page()
        operations.goto(f"{console.base_url}/")
        operations.wait_for_load_state("networkidle")
        assert "BLUE-01" not in (operations.locator("#blue-list").text_content() or "")
        assert not operations.locator("input[name=manoeuvre_start]").input_value().startswith("2025-06-15")
        assert operations.locator("a[href='/training']").count() == 1
        operations.close()
        page.click("#tnav-scenarios")
        page.click("#scenario-detail button:has-text('Abandon')")
        _detail_empty(page)
        assert problems_free(console)


class TestTheAttemptPanel:
    def test_steps_are_a_list_and_typing_an_answer_ticks_its_objective(self, console: Console) -> None:
        page = _training(console)
        _start(page, _CADET)
        assert page.locator("#scenario-workflow-steps > li").count() == 5
        assert page.locator("#scenario-epoch").inner_text().startswith("Scenario time: 15 Jun 2025 00:00 UTC")
        page.fill("input[name=answer_obj_read_elements]", "45")
        assert page.is_checked("#obj-box-obj_read_elements")
        assert "obj_read_elements" in page.input_value("#objectives-json")
        page.click("#scenario-detail button:has-text('Abandon')")
        _detail_empty(page)
        assert problems_free(console)

    def test_a_pass_updates_the_sidebar_banner_and_dashboard_without_a_reload(self, console: Console) -> None:
        page = _training(console)
        before = int(page.inner_text("#training-sidebar-points"))
        _start(page, _CADET)
        page.check("#obj-box-obj_load")
        page.fill("input[name=answer_obj_read_elements]", "45")
        page.fill("input[name=answer_obj_confirm_dv]", "2")
        page.click("#scenario-submit-form button[type=submit]")
        page.wait_for_selector("#debrief-objectives")
        after = str(before + 150)
        _until(page, f"document.getElementById('training-sidebar-points').textContent.trim() === '{after}'")
        assert f"{after} pts" in page.inner_text("#training-banner-status")
        page.click("#tnav-dashboard")
        assert after in page.inner_text("#training-dashboard")
        assert problems_free(console)


class TestTheHeader:
    def test_return_to_operations_stays_uncovered_when_the_page_scrolls(self, console: Console) -> None:
        page = _training(console)
        page.set_viewport_size({"width": 1280, "height": 600})
        page.evaluate("window.scrollTo(0, 200)")
        page.wait_for_timeout(200)
        covered = page.evaluate("""() => {
          const b = document.querySelector('.nav-bar form[action="/training/leave"] button');
          const r = b.getBoundingClientRect();
          if (r.bottom <= 0) return 'scrolled away';
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return b.contains(hit) ? '' : (hit ? (hit.id || hit.tagName) : 'nothing');
        }""")
        assert covered == ""
        assert problems_free(console)


def problems_free(console: Console) -> bool:
    assert console.problems() == []
    return True
