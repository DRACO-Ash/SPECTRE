"""Training mode and user administration, driven in Chromium under the console's policy (SPC-199)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.browser.conftest import Console


def _assert_clean(console: Console) -> None:
    assert console.problems() == []


def _training(console: Console) -> Any:
    page = console.open("/training")
    page.wait_for_function(
        "document.getElementById('tpanel-dashboard').textContent.indexOf('Loading dashboard') < 0", timeout=30000)
    return page


def _in_view(page: Any, selector: str) -> bool:
    return bool(page.evaluate(
        "s => { const r = document.querySelector(s).getBoundingClientRect();"
        " return r.top < window.innerHeight && r.bottom > 0; }", selector))


def _scenario_detail(page: Any) -> None:
    page.click("#tnav-scenarios")
    page.locator('#scenario-list button:has-text("View & Load")').first.click()
    page.wait_for_selector("#scenario-detail form[hx-post$='/start']")


class TestTrainingNavigation:
    def test_a_nav_button_shows_its_panel_alone(self, console: Console) -> None:
        page = _training(console)
        page.click("#tnav-tutorials")
        assert page.is_visible("#tpanel-tutorials")
        assert not page.is_visible("#tpanel-dashboard")
        assert page.evaluate("document.getElementById('tnav-tutorials').style.color") == "rgb(245, 158, 11)"
        _assert_clean(console)

    def test_the_console_tab_loads_the_console_once(self, console: Console) -> None:
        page = _training(console)
        assert page.get_attribute("#training-console-frame", "src") is None
        page.click("#tnav-console")
        assert page.get_attribute("#training-console-frame", "src") == "/"
        assert page.evaluate("document.getElementById('training-main').style.position") == "relative"
        page.click("#tnav-dashboard")
        assert page.evaluate("document.getElementById('training-main').style.position") == ""
        _assert_clean(console)

    def test_load_first_scenario_opens_it_on_the_scenarios_tab(self, console: Console) -> None:
        page = _training(console)
        first = page.locator('#tpanel-dashboard button:has-text("Load First Scenario")')
        if first.count() == 0:
            pytest.skip("this operator's dashboard offers no first scenario")
        first.click()
        page.wait_for_selector("#scenario-detail form[hx-post$='/start']")
        assert page.is_visible("#tpanel-scenarios")
        _assert_clean(console)

    def test_view_and_load_opens_the_scenario_and_scrolls_to_it(self, console: Console) -> None:
        page = _training(console)
        _scenario_detail(page)
        page.wait_for_timeout(800)
        assert _in_view(page, "#scenario-detail")
        _assert_clean(console)

    def test_a_tutorial_start_loads_it_and_its_completion_offers_the_scenarios(self, console: Console) -> None:
        page = _training(console)
        page.click("#tnav-tutorials")
        start = page.locator("#tpanel-tutorials button[hx-get^='/training/tutorial/']").first
        if start.count() == 0:
            pytest.skip("no tutorial is unlocked")
        start.click()
        page.wait_for_selector("#tutorial-detail > *")
        complete = page.locator('#tutorial-detail button:has-text("Mark Complete")')
        if complete.count() == 0:
            pytest.skip("this tutorial is already complete")
        complete.click()
        page.wait_for_selector('#tutorial-detail button:has-text("View Scenarios")')
        page.click('#tutorial-detail button:has-text("View Scenarios")')
        assert page.is_visible("#tpanel-scenarios")
        _assert_clean(console)


class TestAScenarioAttempt:
    def test_ticking_an_objective_records_it_and_abandon_closes_the_panel(self, console: Console) -> None:
        page = _training(console)
        _scenario_detail(page)
        page.click("#scenario-detail form[hx-post$='/start'] button[type=submit]")
        page.wait_for_selector("#scenario-submit-form")
        box = page.locator('#scenario-submit-form input[type="checkbox"]').first
        box.check()
        assert page.input_value("#objectives-json") == f'["{box.get_attribute("value")}"]'
        box.uncheck()
        assert page.input_value("#objectives-json") == "[]"
        if page.locator("#timer-display").count():
            before = page.text_content("#timer-display")
            page.wait_for_timeout(2200)
            assert page.text_content("#timer-display") != before
        page.click('#scenario-detail button:has-text("Abandon")')
        assert page.inner_html("#scenario-detail") == ""
        page.wait_for_timeout(1500)
        _assert_clean(console)

    def test_a_submitted_attempt_offers_the_dashboard(self, console: Console) -> None:
        page = _training(console)
        _scenario_detail(page)
        page.click("#scenario-detail form[hx-post$='/start'] button[type=submit]")
        page.wait_for_selector("#scenario-submit-form")
        page.click('#scenario-submit-form button[type="submit"]')
        page.wait_for_selector('#scenario-detail button:has-text("View Dashboard")')
        page.click('#scenario-detail button:has-text("View Dashboard")')
        assert page.is_visible("#tpanel-dashboard")
        _assert_clean(console)


class TestUserAdministration:
    def test_creating_a_user_clears_the_form(self, console: Console) -> None:
        page = console.open("/admin/users")
        page.fill("#new-username", "browser_operator")
        page.fill("#new-password", "browser-operator-password")
        page.select_option("#new-role", "operator")
        with page.expect_response("**/admin/users"):
            page.click('button:has-text("Create User")')
        page.wait_for_timeout(300)
        assert "browser_operator" in page.inner_text("#user-tbody")
        assert page.input_value("#new-username") == ""
        _assert_clean(console)
