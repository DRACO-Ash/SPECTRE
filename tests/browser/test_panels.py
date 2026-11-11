"""The Decision Engine, pattern of life, GCAT, screening and catalogue panels in Chromium under the policy (SPC-199).

Where an instance with no UDL or GCAT access cannot produce a panel, it is rendered in this process from the real
templates with the fixtures the server-side tests already use, and handed to the live page the way htmx hands it any
fragment.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from tests.browser.conftest import Browser, Console, seed


def _render(template: str, **context: Any) -> str:
    from spectre.web.app import templates

    return templates.env.get_template(template).render(**context)


def _assert_clean(console: Console) -> None:
    assert console.problems() == []


@pytest.fixture(scope="module", autouse=True)
def seeded(browser: Browser) -> Iterator[None]:
    """The red and blue tracks the computed Decision Engine fixture names, held in this module's session."""
    from tests.unit.test_decision_computed import PLANE_CHANGE

    seed(browser, [
        ("/assets/red", {"name": "RED_PC", "tle": PLANE_CHANGE.red_tle}),
        ("/assets/blue", {"name": "BLUE_PC", "tle": PLANE_CHANGE.blue_tle}),
    ])
    yield


class TestDecisionPanel:
    def _panel(self, console: Console) -> Any:
        page = console.open()
        page.click('.htab[data-panel="hero-decision"]')
        page.wait_for_selector("#adv-rows .adv-row")
        return page

    def test_rows_are_added_with_the_next_id_and_removed(self, console: Console) -> None:
        page = self._panel(console)
        before = page.locator("#adv-rows .adv-row").count()
        page.click('button:has-text("+ Add Adversary Action")')
        assert page.locator("#adv-rows .adv-row").count() == before + 1
        added = page.locator("#adv-rows .adv-row").last
        assert added.locator('input[name="adv_id"]').input_value() == f"A{before + 1}"
        assert added.locator("details.adv-hypothesis").count() == 1
        added.locator('button[aria-label="Remove adversary action"]').click()
        assert page.locator("#adv-rows .adv-row").count() == before
        _assert_clean(console)

    def test_a_response_row_carries_its_own_id_on_its_veto_box(self, console: Console) -> None:
        page = self._panel(console)
        page.click('button:has-text("+ Add Friendly Response")')
        added = page.locator("#fr-rows .fr-row").last
        assert added.locator('input[name="fr_id"]').input_value() == "R2"
        assert added.locator('input[name="fr_vetoed"]').get_attribute("value") == "R2"
        assert added.locator("details.fr-burn").count() == 1
        added.locator('button[aria-label="Remove friendly response"]').click()
        assert page.locator("#fr-rows .fr-row").count() == 1
        _assert_clean(console)

    def test_added_rows_post_only_their_own_kind_and_the_engine_counts_them(self, console: Console) -> None:
        """A row of each kind adds one adversary action and one response to the scenario, and nothing else."""
        page = self._panel(console)
        before = page.locator("#adv-rows .adv-row").count()
        page.click('button:has-text("+ Add Adversary Action")')
        page.click('button:has-text("+ Add Friendly Response")')
        posted = page.evaluate(
            """() => { const f = new FormData(document.querySelector('#adv-rows').closest('form'));
                       return {adv: f.getAll('adv_id'), fr: f.getAll('fr_id')}; }"""
        )
        assert posted == {"adv": [f"A{i}" for i in range(1, before + 2)], "fr": ["R1", "R2"]}
        added = page.locator("#fr-rows .fr-row").last
        assert "function" not in added.inner_text()
        assert "`" not in added.inner_text()
        with page.expect_response("**/plan/decision/**", timeout=60000):
            page.click('#adv-rows >> xpath=ancestor::form >> button[type="submit"]')
        page.wait_for_selector("#decision-results :text('response(s)')", timeout=60000)
        assert f"{before + 1} adversary action(s)" in page.locator("#decision-results").inner_text()
        assert "× 2 response(s)" in page.locator("#decision-results").inner_text()
        _assert_clean(console)


@pytest.fixture(scope="module")
def sampled_results() -> str:
    from spectre.domain.decision import evaluate_scenario
    from tests.unit.test_decision_figure_basis import _render as render_results
    from tests.unit.test_decision_sampled import _bound
    from tests.unit.test_decision_tca_histogram import _WithSpeeds

    return str(render_results(evaluate_scenario(_bound(), sampler=_WithSpeeds())))


@pytest.fixture(scope="module")
def linked_results() -> str:
    from tests.unit.test_decision_computed import _computed
    from tests.unit.test_decision_trajectory import _render_with_links

    return str(_render_with_links(_computed()))


class TestDecisionResults:
    def test_the_histogram_draws_and_redraws_for_the_chosen_cell(self, console: Console, sampled_results: str) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-decision"]')
        page.wait_for_selector("#decision-results", state="attached")
        console.inject(sampled_results, "#decision-results")
        assert page.evaluate("!!Chart.getChart(document.getElementById('tca-hist-chart'))") is True
        options = page.locator("#tca-hist-cell option")
        if options.count() > 1:
            second = options.nth(1).get_attribute("value")
            page.select_option("#tca-hist-cell", second)
            shown = page.locator(f'.tca-histogram table[data-cell="{second}"]')
            assert shown.get_attribute("hidden") is None
        assert page.evaluate("!!Chart.getChart(document.getElementById('tca-hist-chart'))") is True
        _assert_clean(console)

    def test_show_trajectory_opens_a_view_whose_escape_returns_to_that_cell(
        self, console: Console, linked_results: str,
    ) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-decision"]')
        page.wait_for_selector("#decision-results", state="attached")
        console.inject(linked_results, "#decision-results")
        button = page.locator('form.show-trajectory button[type="submit"]').nth(1)
        label = button.get_attribute("aria-label")
        with page.expect_response("**/plan/geometry/**", timeout=60000):
            button.click()
        page.wait_for_selector("#decision-geom-panel")
        page.wait_for_timeout(300)
        assert page.locator("form.show-trajectory[data-geometry-opener]").count() == 1
        page.keyboard.press("Escape")
        assert page.locator("#decision-geom-panel").count() == 0
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == label
        _assert_clean(console)


@pytest.fixture
def pol_results() -> str:
    from spectre.web.routes import pol
    from tests.unit.test_threat_understanding_sweep import _RAISES, _held_history

    history = _held_history(_RAISES)
    return _render("partials/pol_results.html", pol=history.pol, source="UDL", pair=None,
                   **pol._pol_view(history.pol))


class TestPatternOfLife:
    def test_the_charts_draw_from_the_chart_data_and_a_header_sorts(self, console: Console, pol_results: str) -> None:
        page = console.open()
        page.click('.htab[data-panel="hero-pol"]')
        page.wait_for_selector("#pol-results", state="attached")
        epochs = ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"]
        data = {"elements": {"epochs": epochs, "altitude": [500, 501, 502], "inclination": [97, 97, 97],
                             "eccentricity": [0.001, 0.001, 0.001], "raan": [10, 11, 12], "period": [94, 94, 94]},
                "manoeuvres": {"epochs": epochs, "dvs_ms": [1.0, 2.0, 3.0], "colors": ["#3b8beb"] * 3,
                               "lons": [None, None, None]},
                "geo": None}
        page.route("**/pol/chart-data/**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(data)))
        with page.expect_request("**/pol/chart-data/**"):
            console.inject(pol_results, "#pol-results")
        page.wait_for_timeout(300)
        assert page.evaluate("!!Chart.getChart(document.getElementById('pol-alt-chart'))") is True
        header = page.locator("#pol-results th[tabindex]").first
        header.click()
        assert header.locator(".hrr-sort-ind").text_content() == " ▲"
        header.focus()
        page.keyboard.press("Enter")
        assert header.locator(".hrr-sort-ind").text_content() == " ▼"
        _assert_clean(console)


@pytest.fixture
def gcat_cached() -> Iterator[None]:
    import pandas as pd

    from spectre.web.routes import gcat

    saved = dict(gcat._CACHE)
    df = pd.DataFrame([{"Satcat": "1", "Name": "ALPHA"}, {"Satcat": "2", "Name": "BRAVO"}])
    gcat._CACHE["currentcat"] = {"df": df, "fetched_at": datetime(2026, 10, 4, tzinfo=UTC), "rows": 2, "cols": 2,
                                 "columns": list(df.columns)}
    yield
    gcat._CACHE.clear()
    gcat._CACHE.update(saved)


def _gcat_open(console: Console, context: dict[str, Any]) -> Any:
    """Open the GCAT tab with the panel the server would send for *context*, which needs no download."""
    page = console.open()
    panel = _render("partials/gcat_panel.html", **context)
    page.route("**/gcat/panel", lambda route: route.fulfill(status=200, content_type="text/html", body=panel))
    page.click('.htab[data-panel="hero-gcat"]')
    page.wait_for_selector(".gcat-ctab")
    return page


class TestGcat:
    def test_a_category_tab_shows_its_datasets(self, console: Console, gcat_cached: None) -> None:
        from spectre.web.routes import gcat

        page = _gcat_open(console, gcat._panel_context(SimpleNamespace(role="admin")))
        second = page.locator(".gcat-ctab").nth(1)
        cat = second.get_attribute("data-cat")
        second.click()
        assert "active" in (second.get_attribute("class") or "")
        assert "active" in (page.get_attribute(f'.gcat-nav-group[data-cat-group="{cat}"]', "class") or "")
        _assert_clean(console)

    def test_a_table_marks_its_dataset_and_the_clear_control_reloads_page_one(
        self, console: Console, gcat_cached: None,
    ) -> None:
        from spectre.web.routes import gcat

        page = _gcat_open(console, gcat._panel_context(SimpleNamespace(role="admin")))
        page.route("**/gcat/table?*", lambda route: route.fulfill(status=200, content_type="text/html", body="<p>table</p>"))
        console.inject(_render("partials/gcat_table.html", **gcat._page_data("currentcat", q="ALPHA")),
                       "#gcat-table-area")
        assert "active" in (page.get_attribute('.gcat-nav .gcat-ds-btn[data-ds="currentcat"]', "class") or "")
        with page.expect_request("**/gcat/table?dataset=currentcat&q=&page=1"):
            page.locator(".gcat-search-clr").first.click()
        _assert_clean(console)

    def test_a_dataset_button_marks_itself_active(self, console: Console, gcat_cached: None) -> None:
        from spectre.web.routes import gcat

        page = _gcat_open(console, gcat._panel_context(SimpleNamespace(role="admin")))
        page.route("**/gcat/table?*", lambda route: route.fulfill(status=200, content_type="text/html", body="<p>table</p>"))
        button = page.locator(".gcat-nav-group.active .gcat-ds-btn").nth(1)
        button.click()
        assert "active" in (button.get_attribute("class") or "")
        assert page.locator(".gcat-ds-btn.active").count() == 1
        _assert_clean(console)


class TestAssetScreening:
    def test_an_actor_row_opens_its_profiles(self, console: Console) -> None:
        from tests.unit.test_threat_screen_template import _context

        page = console.open()
        page.click('.htab[data-panel="hero-screen"]')
        console.inject(_render("partials/threat_screen.html", **_context()), "#threat-screen-results")
        row = page.locator("tr.threat-parent[data-row]").first
        cls = row.get_attribute("data-row")
        child = page.locator(f"tr.scr-child.{cls}").first
        assert not child.is_visible()
        row.click()
        assert child.is_visible()
        row.focus()
        page.keyboard.press("Enter")
        assert not child.is_visible()
        _assert_clean(console)


class TestCatalogue:
    def test_sending_an_object_to_red_opens_the_first_red_panel_section(self, console: Console) -> None:
        page = console.open()
        page.click('.stab[data-panel="sb-intel"]')
        results = [SimpleNamespace(satno="25544", name="ISS", obj_type="PAYLOAD", country="ISS")]
        page.route("**/udl/tle?*", lambda route: route.fulfill(status=200, content_type="text/html", body="<p>table</p>"))
        console.inject(_render("partials/catalog_results.html", status="loaded", q="ISS", results=results, total=1),
                       "#catalog-results")
        page.evaluate("document.querySelector('.panel-red details').removeAttribute('open')")
        with page.expect_response("**/udl/tle?*"):
            page.click('#catalog-results button:has-text("\u2192 Red")')
        page.wait_for_timeout(200)
        assert page.evaluate("document.querySelector('.panel-red details').hasAttribute('open')") is True
        _assert_clean(console)


class TestElementSetRefreshNote:
    def test_a_refresh_that_updated_sets_rereads_the_red_card(self, console: Console) -> None:
        page = console.open()
        page.select_option("#ts-red-sat", "RED_PC")
        page.wait_for_load_state("networkidle")
        refresh = SimpleNamespace(running=False, finished_at=datetime(2026, 11, 11, 12, 0, tzinfo=UTC),
                                  updated=["RED"], current=0, failed=[], refused=[])
        with page.expect_request("**/plan/threat/red-orbit-info*"):
            console.inject(_render("partials/elset_refresh_note.html", refresh=refresh, announce=True),
                           "#elset-refresh-note", swap="outerHTML")
        _assert_clean(console)
