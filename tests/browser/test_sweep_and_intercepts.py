"""The threat sweep and the intercept engine, run for real in Chromium under the console's policy (SPC-199).

A red GEO track, a blue GEO asset and a manual sweep target are added through the console's own routes; the sweep and
the all-methods run are computed by the server, so every table, row and control below is what an operator gets.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from tests.browser.conftest import Browser, Console, post, seed

_RED_GEO = (
    "1 90001U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9993\n"
    "2 90001   0.0500  95.0000 0001000   0.0000  10.0000  1.00270000    14"
)
_BLUE_GEO = (
    "1 90002U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9994\n"
    "2 90002   0.0500  95.0000 0001000   0.0000  11.0000  1.00270000    16"
)


def _assert_clean(console: Console) -> None:
    assert console.problems() == []


@pytest.fixture(scope="module", autouse=True)
def seeded(browser: Browser) -> Iterator[None]:
    """One red track, one blue asset and one manual sweep target in this module's session."""
    seed(browser, [
        ("/assets/red", {"name": "RED-GEO", "tle": _RED_GEO}),
        ("/assets/blue", {"name": "BLUE-GEO", "tle": _BLUE_GEO}),
        ("/plan/threat/add-manual-tle", {"manual_name": "MANUAL-GEO", "manual_tle": _BLUE_GEO,
                                         "manual_confidence": "HIGH"}),
    ])
    yield


def _swept(console: Console) -> Any:
    page = console.open()
    with page.expect_response("**/plan/threat/target-config*"):
        page.select_option("#ts-red-sat", "RED-GEO")
    page.wait_for_selector('button:has-text("Sweep Targets")')
    page.select_option("#ts-tgt-group", "none")
    page.click('button:has-text("Sweep Targets")')
    page.wait_for_selector("#threat-sweep-table", timeout=60000)
    return page


def _all_intercepts(console: Console) -> Any:
    page = console.open()
    page.click('.htab[data-panel="hero-engine"]')
    page.select_option("#ie-red-sat", "RED-GEO")
    page.select_option("#ie-blue-sat", "BLUE-GEO")
    page.click('#intercept-engine-form button[type="submit"]')
    page.wait_for_selector("#all-intercepts-table", state="attached", timeout=120000)
    page.wait_for_load_state("networkidle")
    page.click('.etab[data-panel="et-calculator"]')
    return page


class TestSweepTargetConfig:
    def test_adding_a_manual_target_clears_its_fields(self, console: Console) -> None:
        page = console.open()
        with page.expect_response("**/plan/threat/target-config*"):
            page.select_option("#ts-red-sat", "RED-GEO")
        page.wait_for_selector("#ts-manual-name", state="attached")
        page.evaluate("document.querySelectorAll('#ts-target-config details').forEach(d => d.open = true)")
        page.fill("#ts-manual-name", "SECOND-GEO")
        page.fill("#ts-manual-tle", _BLUE_GEO)
        with page.expect_response("**/plan/threat/add-manual-tle"):
            page.click('button:has-text("Add TLE")')
        page.wait_for_timeout(200)
        assert "SECOND-GEO" in page.inner_text("#manual-tle-list")
        assert page.input_value("#ts-manual-name") == ""
        assert page.input_value("#ts-manual-tle") == ""
        _assert_clean(console)


class TestThreatSweep:
    def test_a_target_row_opens_and_closes_its_profiles_by_click_and_by_key(self, console: Console) -> None:
        page = _swept(console)
        parent = page.locator("tr.threat-parent").first
        parent.click()
        assert parent.get_attribute("aria-expanded") == "true"
        assert page.locator("tr.threat-children-0").first.is_visible()
        parent.focus()
        page.keyboard.press("Enter")
        assert parent.get_attribute("aria-expanded") == "false"
        assert not page.locator("tr.threat-children-0").first.is_visible()
        _assert_clean(console)

    def test_expand_all_and_collapse_all(self, console: Console) -> None:
        page = _swept(console)
        page.click('button:has-text("Expand All")')
        assert page.locator("tr.threat-parent").first.get_attribute("aria-expanded") == "true"
        page.click('button:has-text("Collapse All")')
        assert page.locator("tr.threat-parent").first.get_attribute("aria-expanded") == "false"
        assert not page.locator("tr.threat-child").first.is_visible()
        _assert_clean(console)

    def test_the_search_box_and_the_data_mode_filter_hide_rows(self, console: Console) -> None:
        page = _swept(console)
        page.fill("#threat-search", "no-such-target-anywhere")
        assert not page.locator("tr.threat-parent").first.is_visible()
        page.fill("#threat-search", "")
        assert page.locator("tr.threat-parent").first.is_visible()
        page.select_option("#sweep-dm-filter", "EXERCISE")
        assert not page.locator("tr.threat-parent").first.is_visible()
        page.select_option("#sweep-dm-filter", "")
        assert page.locator("tr.threat-parent").first.is_visible()
        _assert_clean(console)

    def test_a_target_header_and_a_profile_header_sort(self, console: Console) -> None:
        page = _swept(console)
        header = page.locator("#threat-sweep-table thead th[aria-sort]").first
        header.click()
        assert header.get_attribute("aria-sort") == "ascending"
        header.click()
        assert header.get_attribute("aria-sort") == "descending"
        page.click("#threat-group-0")
        child = page.locator("#tsw-child-0-3")
        child.click()
        assert child.get_attribute("aria-sort") == "ascending"
        child.focus()
        page.keyboard.press("Enter")
        assert child.get_attribute("aria-sort") == "descending"
        _assert_clean(console)

    def test_load_fills_the_intercept_engine_without_toggling_its_row(self, console: Console) -> None:
        page = _swept(console)
        page.locator("tr.threat-parent").first.click()
        load = page.locator('tr[id^="threat-row-"] button:has-text("Load")').first
        epoch = load.get_attribute("data-epoch")
        load.click()
        assert "active" in (page.get_attribute("#hero-engine", "class") or "")
        assert page.input_value("#ie-red-sat") == "RED-GEO"
        # A datetime-local input drops ":00" seconds from the value it holds, so an event on a whole minute reads
        # back as HH:MM; the instant is what must match.
        shown = page.input_value('#intercept-engine-form [name="manoeuvre_start"]')
        assert epoch is not None
        assert datetime.fromisoformat(shown) == datetime.fromisoformat(epoch)
        assert page.locator("tr.threat-parent").first.get_attribute("aria-expanded") == "true"
        _assert_clean(console)

    def test_refine_replaces_a_row_whose_load_still_works(self, console: Console) -> None:
        page = _swept(console)
        page.locator("tr.threat-parent").first.click()
        refine = page.locator('tr[id^="threat-row-"] button:has-text("Refine")')
        if refine.count() == 0:
            pytest.skip("no entry in this sweep offers a refine")
        row_id = refine.first.locator("xpath=ancestor::tr").get_attribute("id")
        with page.expect_response("**/plan/threat/refine*", timeout=60000):
            refine.first.click()
        page.wait_for_timeout(300)
        page.locator(f'#{row_id} button:has-text("Load")').click()
        assert "active" in (page.get_attribute("#hero-engine", "class") or "")
        _assert_clean(console)

    def test_decide_opens_the_decision_engine(self, console: Console) -> None:
        page = _swept(console)
        page.locator("tr.threat-parent").first.click()
        decide = page.locator('tr[id^="threat-row-"] button:has-text("Decide")')
        if decide.count() == 0:
            pytest.skip("no entry in this sweep arrives")
        with page.expect_response("**/plan/decision/from-sweep*", timeout=60000):
            decide.first.click()
        page.wait_for_timeout(300)
        assert "active" in (page.get_attribute("#hero-decision", "class") or "")
        _assert_clean(console)


class TestAllIntercepts:
    def test_a_result_row_opens_its_detail_and_a_header_sorts(self, console: Console) -> None:
        page = _all_intercepts(console)
        row = page.locator("#all-intercepts-table tr.threat-parent").first
        row.click()
        assert row.get_attribute("aria-expanded") == "true"
        row.focus()
        page.keyboard.press("Enter")
        assert row.get_attribute("aria-expanded") == "false"
        header = page.locator("#all-intercepts-table thead th[aria-sort]").nth(3)
        header.click()
        assert header.get_attribute("aria-sort") == "ascending"
        header.focus()
        page.keyboard.press("Enter")
        assert header.get_attribute("aria-sort") == "descending"
        _assert_clean(console)

    def test_load_by_key_stages_the_engine_and_leaves_the_row(self, console: Console) -> None:
        page = _all_intercepts(console)
        row = page.locator("#all-intercepts-table tr.threat-parent").first
        load = row.locator('button:has-text("Load")')
        epoch = load.get_attribute("data-epoch")
        page.fill('#intercept-engine-form [name="manoeuvre_start"]', "2026-01-01T00:00")
        load.focus()
        page.keyboard.press("Enter")
        assert row.get_attribute("aria-expanded") == "false"
        # A datetime-local input drops ":00" seconds from the value it holds, so an event on a whole minute reads
        # back as HH:MM; the instant is what must match.
        shown = page.input_value('#intercept-engine-form [name="manoeuvre_start"]')
        assert epoch is not None
        assert datetime.fromisoformat(shown) == datetime.fromisoformat(epoch)
        _assert_clean(console)

    def test_a_second_run_draws_the_trade_space(self, console: Console) -> None:
        page = _all_intercepts(console)
        with page.expect_response("**/plan/maneuver/trade-space-data", timeout=120000):
            page.click('#intercept-engine-form button[type="submit"]')
        page.wait_for_function("document.getElementById('ts-chart-status').textContent.indexOf('plotted') > 0",
                               timeout=30000)
        assert "active" in (page.get_attribute("#et-trade", "class") or "")
        drawn = page.evaluate("!!Chart.getChart(document.getElementById('tradeSpaceChart'))")
        assert drawn is True
        _assert_clean(console)


class TestOrbitalEvents:
    def test_events_are_listed_and_one_sets_the_manoeuvre_start(self, console: Console) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-engine"]')
        page.select_option("#ie-red-sat", "RED-GEO")
        with page.expect_response("**/plan/maneuver/orbital-events*", timeout=60000):
            page.click("#ie-events-btn")
        page.wait_for_selector("#orbital-events button[data-epoch]")
        event = page.locator("#orbital-events button[data-epoch]").first
        epoch = event.get_attribute("data-epoch")
        event.click()
        # A datetime-local input drops ":00" seconds from the value it holds, so an event on a whole minute reads
        # back as HH:MM; the instant is what must match.
        shown = page.input_value('#intercept-engine-form [name="manoeuvre_start"]')
        assert epoch is not None
        assert datetime.fromisoformat(shown) == datetime.fromisoformat(epoch)
        assert page.text_content("#ie-events-btn") == "Events"
        _assert_clean(console)


class TestSingleIntercept:
    def _result(self, console: Console) -> Any:
        page = console.open()
        page.click('.htab[data-panel="hero-engine"]')
        result = post(page, "/plan/maneuver/apply-intercept",
                       {"red_sat": "RED-GEO", "blue_sat": "BLUE-GEO", "method": "lambert"})
        console.inject(result, "#intercept-result")
        page.wait_for_load_state("networkidle")
        page.click('.etab[data-panel="et-calculator"]')
        return page

    def test_copy_puts_the_summary_on_the_clipboard(self, console: Console) -> None:
        page = self._result(console)
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        copy = page.locator('button[data-clip]').first
        copy.click()
        page.wait_for_function("document.querySelector('button[data-clip]').textContent.indexOf('Copied') >= 0")
        assert page.evaluate("navigator.clipboard.readText()") == copy.get_attribute("data-clip")
        _assert_clean(console)

    def test_the_geometry_panel_draws_switches_view_and_closes_on_escape(self, console: Console) -> None:
        page = self._result(console)
        opener = page.locator('#intercept-result form[hx-post="/plan/geometry/intercept"] button[type="submit"]')
        if opener.count() == 0:
            pytest.skip("this result offers no geometry view")
        with page.expect_response("**/plan/geometry/intercept", timeout=60000):
            opener.first.click()
        panel = page.wait_for_selector('[id$="geom-panel"]')
        assert panel is not None
        page.wait_for_timeout(300)
        canvases = page.evaluate(
            "Array.from(document.querySelectorAll('[id$=\"cw-chart-vr\"]')).map(c => !!Chart.getChart(c))"
        )
        assert canvases == [True]
        focused = page.evaluate("document.activeElement.id")
        assert focused.endswith("geom-panel-heading")
        page.locator('[id$="gtab-rt"]').click()
        assert page.evaluate("!!Chart.getChart(document.querySelector('[id$=\"cw-chart-rt\"]'))") is True
        page.keyboard.press("Escape")
        assert page.locator('[id$="geom-panel"]').count() == 0
        assert page.evaluate("document.activeElement.textContent").strip().endswith("Relative Geometry")
        _assert_clean(console)
