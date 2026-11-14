"""The operator console's own controls, driven in Chromium under the policy the console sends (SPC-199).

Each test drives one behaviour the page's scripts carry, through the control an operator touches, and ends by
asserting the browser refused nothing and threw nothing. They passed with the inline scripts and handlers, and they
pass with the static files and listeners that replaced them.
"""

from __future__ import annotations

from typing import Any

from tests.browser.conftest import Console

_RED_GEO = (
    "1 90001U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9993\n"
    "2 90001   0.0500  95.0000 0001000   0.0000  10.0000  1.00270000    14"
)


def _render(template: str, **context: Any) -> str:
    from spectre.web.app import templates

    return templates.env.get_template(template).render(**context)


def _assert_clean(console: Console) -> None:
    assert console.problems() == []


def _hrr_rows() -> dict[str, Any]:
    blue = [
        {"name": "ZULU-SAT", "satno": "40001", "country": "UK", "orbit": "GEO", "rank": "2"},
        {"name": "ALPHA-SAT", "satno": "40002", "country": "US", "orbit": "LEO", "rank": "1"},
    ]
    red = [{"name": "RED-ONE", "satno": "50001", "country": "XX", "orbit": "GEO", "rank": "3"}]
    return {"hrr_blue": blue, "hrr_red": red, "error": None}


class TestTheme:
    def test_the_picker_sets_the_theme_and_it_survives_a_reload(self, console: Console) -> None:
        page = console.open()
        page.select_option("#theme-picker", "steel")
        assert page.get_attribute("html", "data-theme") == "steel"
        assert page.get_attribute("html", "data-spectre-theme") == "light"
        page.reload()
        page.wait_for_load_state("networkidle")
        assert page.get_attribute("html", "data-theme") == "steel"
        assert page.input_value("#theme-picker") == "steel"
        _assert_clean(console)

    def test_an_unknown_saved_theme_is_dropped(self, console: Console) -> None:
        page = console.open()
        page.evaluate("localStorage.setItem('spectre-theme', 'neon')")
        page.reload()
        page.wait_for_load_state("networkidle")
        assert page.get_attribute("html", "data-theme") == "ops"
        assert page.evaluate("localStorage.getItem('spectre-theme')") is None
        _assert_clean(console)


class TestTabs:
    def test_a_sidebar_tab_shows_its_panel_alone(self, console: Console) -> None:
        page = console.open()
        page.click('.stab[data-panel="sb-intel"]')
        assert "active" in (page.get_attribute("#sb-intel", "class") or "")
        assert "active" not in (page.get_attribute("#sb-assets", "class") or "")
        _assert_clean(console)

    def test_an_asset_tab_shows_its_panel_alone(self, console: Console) -> None:
        page = console.open()
        page.click('.atab[data-panel="at-blue"]')
        assert "active" in (page.get_attribute("#at-blue", "class") or "")
        assert "active" not in (page.get_attribute("#at-red", "class") or "")
        _assert_clean(console)

    def test_a_hero_tab_shows_its_panel_and_the_sweep_tab_refreshes_its_targets(self, console: Console) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-engine"]')
        assert "active" in (page.get_attribute("#hero-engine", "class") or "")
        assert "active" not in (page.get_attribute("#hero-sweep", "class") or "")
        with page.expect_request("**/plan/threat/target-config*"):
            page.click('.htab[data-panel="hero-sweep"]')
        assert "active" in (page.get_attribute("#hero-sweep", "class") or "")
        _assert_clean(console)

    def test_an_engine_tab_shows_its_panel_alone(self, console: Console) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-engine"]')
        page.click('.etab[data-panel="et-history"]')
        assert "active" in (page.get_attribute("#et-history", "class") or "")
        assert "active" not in (page.get_attribute("#et-calculator", "class") or "")
        _assert_clean(console)


class TestSidebar:
    def test_the_collapse_control_collapses_and_expands(self, console: Console) -> None:
        page = console.open()
        page.click("#sidebar-collapse-btn")
        assert "sidebar-collapsed" in (page.get_attribute(".console-layout", "class") or "")
        assert page.get_attribute("#sidebar-collapse-btn", "title") == "Expand sidebar"
        page.click("#sidebar-collapse-btn")
        assert "sidebar-collapsed" not in (page.get_attribute(".console-layout", "class") or "")
        assert page.get_attribute("#sidebar-collapse-btn", "title") == "Collapse sidebar"
        _assert_clean(console)

    def test_the_handle_drags_the_sidebar_wider(self, console: Console) -> None:
        page = console.open()
        box = page.locator("#sidebar-resize").bounding_box()
        assert box is not None
        x, y = box["x"] + box["width"] / 2, box["y"] + 50
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 60, y)
        page.mouse.up()
        columns = page.evaluate("document.querySelector('.console-layout').style.gridTemplateColumns")
        assert columns.endswith("px 1fr")
        _assert_clean(console)


class TestSplash:
    def test_the_splash_shows_once_closes_on_a_click_and_stays_closed(self, first_visit: Console) -> None:
        page = first_visit.open()
        assert page.locator("#spectre-splash").count() == 1
        page.click("#spectre-splash")
        page.wait_for_selector("#spectre-splash", state="detached", timeout=3000)
        page.reload()
        page.wait_for_load_state("networkidle")
        assert page.locator("#spectre-splash").count() == 0 or not page.is_visible("#spectre-splash")
        _assert_clean(first_visit)

    def test_a_key_press_closes_the_splash(self, first_visit: Console) -> None:
        page = first_visit.open()
        page.keyboard.press("Escape")
        page.wait_for_selector("#spectre-splash", state="detached", timeout=3000)
        assert page.evaluate("sessionStorage.getItem('spectre-splash-seen')") == "1"
        _assert_clean(first_visit)


class TestIntercepEngineControls:
    def test_events_with_no_satellite_says_to_select_one(self, console: Console) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-engine"]')
        page.evaluate("document.getElementById('ie-red-sat').value = ''; document.getElementById('ie-blue-sat').value = ''")
        page.click("#ie-events-btn")
        assert "Select at least one satellite first." in page.inner_text("#orbital-events")
        _assert_clean(console)

    def test_trade_space_controls_toggle_and_reset(self, console: Console) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-engine"]')
        page.click('.etab[data-panel="et-trade"]')
        page.evaluate("document.getElementById('ts-chart-btn').disabled = false;"
                      "document.getElementById('ts-chart-clear').style.display = ''")
        page.click("#ts-chart-btn")
        assert page.is_visible("#trade-space-canvas-wrap")
        assert page.text_content("#ts-chart-btn") == "Hide Chart"
        page.click("#ts-chart-clear")
        assert not page.is_visible("#trade-space-canvas-wrap")
        assert page.text_content("#ts-chart-status") == "Run 2+ intercepts to enable"
        _assert_clean(console)


class TestFetchBySatno:
    def test_enter_in_the_satno_box_fetches_and_other_keys_do_not(self, console: Console) -> None:
        page = console.open()
        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url) if "/udl/tle" in r.url else None)
        page.fill("#red-satno", "25544")
        page.wait_for_timeout(300)
        assert requests == []
        with page.expect_request("**/udl/tle*"):
            page.press("#red-satno", "Enter")
        assert "satno=25544" in requests[-1]
        _assert_clean(console)

    def test_editing_a_fetched_set_drops_its_data_mode_and_provider(self, console: Console) -> None:
        page = console.open()
        console.inject(
            _render("partials/tle_fields.html", name="ALPHA", tle=_RED_GEO, elset_mode="REAL", elset_source="EXO",
                    tle_epoch_str=None, tle_age_days=None, error=None, fields_side="red"),
            "#red-tle-fields",
        )
        tags = '#red-track-form [name="elset_mode"], #red-track-form [name="elset_source"]'
        assert page.locator(tags).count() == 2
        page.type("#red-tle-text", " ")
        assert page.locator(tags).count() == 0, "an edited set kept a UDL tag"
        _assert_clean(console)

    def test_adding_a_red_track_lists_it_and_keeps_the_typed_fields(self, console: Console) -> None:
        """The hx-on::after-settle on the red track form cleared its fields only for an htmx:afterSettle reaching
        the form that named the form as the requester. The form's request swaps the list outside the form, so in
        htmx 1.9.12 that never happens and the fields were kept; the listener that replaced it keeps that exactly,
        and this pins it until the owner decides whether a refused add should keep what was typed (SPC-199)."""
        page = console.open()
        page.fill("#red-satno", "90001")
        page.fill("#red-tle-name", "RED-FORM")
        page.fill("#red-tle-text", _RED_GEO)
        with page.expect_response("**/assets/red"):
            page.click('#red-track-form button[type="submit"]')
        page.wait_for_timeout(300)
        assert "RED-FORM" in page.inner_text("#red-list")
        assert page.input_value("#red-tle-name") == "RED-FORM"
        assert page.input_value("#red-satno") == "90001"
        _assert_clean(console)


class TestHrr:
    def test_search_lists_matches_and_selecting_one_highlights_its_row(self, console: Console) -> None:
        page = console.open()
        page.click('.atab[data-panel="at-hrr"]')
        console.inject(_render("partials/hrr_panel.html", **_hrr_rows()), "#blue-hrr-list")
        page.fill("#hrr-search-input", "alpha")
        page.wait_for_selector("#hrr-search-dropdown .hrr-dd-item")
        assert page.locator("#hrr-search-dropdown .hrr-dd-item").count() == 1
        page.dispatch_event("#hrr-search-dropdown .hrr-dd-item", "mousedown")
        assert "ALPHA-SAT" in page.input_value("#hrr-search-input")
        assert page.locator(".hrr-row-selected").count() == 1
        _assert_clean(console)

    def test_a_header_sorts_by_click_and_by_key(self, console: Console) -> None:
        page = console.open()
        page.click('.atab[data-panel="at-hrr"]')
        console.inject(_render("partials/hrr_panel.html", **_hrr_rows()), "#blue-hrr-list")
        header = page.locator("#blue-hrr-list table.hrr-table th[aria-sort]").first
        header.click()
        assert header.get_attribute("aria-sort") == "ascending"
        first = page.locator("#blue-hrr-list table.hrr-table tbody tr").first.inner_text()
        assert "ALPHA-SAT" in first
        header.focus()
        page.keyboard.press("Enter")
        assert header.get_attribute("aria-sort") == "descending"
        _assert_clean(console)


class TestUdlChip:
    def test_a_failed_connection_turns_the_chip_amber(self, console: Console) -> None:
        page = console.open()
        console.inject(_render("partials/udl_status.html", error="refused", udl_user=None), "#udl-status")
        assert "dot-amber" in (page.get_attribute("#udl-dropdown .chip-dot", "class") or "")
        assert page.inner_text("#udl-dropdown .chip-label") == "UDL ⚠"
        _assert_clean(console)

    def test_a_connection_turns_the_chip_green_and_closes_the_dropdown(self, console: Console) -> None:
        page = console.open()
        page.click("#udl-dropdown > summary")
        console.inject(_render("partials/udl_status.html", error=None, udl_user="analyst"), "#udl-status")
        assert "dot-green" in (page.get_attribute("#udl-dropdown .chip-dot", "class") or "")
        assert page.get_attribute("#udl-dropdown", "open") is None
        _assert_clean(console)

    def test_a_disconnection_turns_the_chip_grey(self, console: Console) -> None:
        page = console.open()
        console.inject(_render("partials/udl_status.html", error=None, udl_user=None), "#udl-status")
        assert "dot-grey" in (page.get_attribute("#udl-dropdown .chip-dot", "class") or "")
        assert page.inner_text("#udl-dropdown .chip-label") == "UDL"
        _assert_clean(console)


class TestPolSource:
    def test_a_source_radio_shows_its_panel_alone(self, console: Console) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-pol"]')
        page.wait_for_selector('input[name="pol_source"]')
        radios = page.locator('input[name="pol_source"]')
        values = [radios.nth(i).get_attribute("value") for i in range(radios.count())]
        assert len(values) >= 2
        radios.nth(1).check()
        assert page.is_visible(f"#pol-src-{values[1]}")
        assert not page.is_visible(f"#pol-src-{values[0]}")
        _assert_clean(console)


class TestThePolicyRefusesInjectedScript:
    """What F-08 asked for, seen in the browser: script the console did not ship from a file does not run."""

    def test_an_injected_event_handler_does_not_run(self, console: Console) -> None:
        page = console.open()
        console.inject('<img id="probe" src="/static/no-such-probe.png" onerror="window.__spectreInjected = 1">', "#threat-sweep-results")
        page.wait_for_timeout(500)
        assert page.evaluate("window.__spectreInjected") is None
        assert any(v.startswith("script-src") for v in console.violations()), console.violations()

    def test_an_injected_script_block_does_not_run(self, console: Console) -> None:
        page = console.open()
        console.inject("<div><script>window.__spectreInjected = 1</script></div>", "#threat-sweep-results")
        page.wait_for_timeout(300)
        assert page.evaluate("window.__spectreInjected") is None

    def test_an_injected_hx_on_does_not_run(self, console: Console) -> None:
        page = console.open()
        console.inject('<button id="probe" hx-on:click="window.__spectreInjected = 1">x</button>', "#threat-sweep-results")
        page.click("#probe")
        page.wait_for_timeout(300)
        assert page.evaluate("window.__spectreInjected") is None
