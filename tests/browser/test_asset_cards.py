"""The Assets panel's element cards and Asset Screening's session Blue assets, in Chromium.

Training audit 2026-11-16, findings 2-1 and 2-3.

Each card is a <details>, so it opens with a click and no script under the console's policy (SPC-199). A Blue asset
added from the panel reaches the Asset Screening selector without a reload, by the event its list answer raises.
"""

from __future__ import annotations

from tests.browser.conftest import Console

_GEO = (
    "1 30793U 07007A   26250.50000000 -.00000100  00000-0  00000-0 0  9998\n"
    "2 30793   0.0400  95.0000 0002000 270.0000 180.0000  1.00271000 46216"
)


def _add_blue(console: Console, name: str) -> None:
    page = console.page
    page.click('.atab[data-panel="at-blue"]')
    page.fill("#blue-tle-name", name)
    page.fill("#blue-tle-text", _GEO)
    with page.expect_response("**/assets/blue"):
        page.click('#blue-asset-form button[type="submit"]')
    page.wait_for_timeout(300)


class TestTheElementCard:
    def test_clicking_a_blue_asset_opens_its_elements_and_clicking_again_closes_them(self, console: Console) -> None:
        page = console.open()
        _add_blue(console, "CARD-BLUE")
        card = page.locator("#blue-list details.elset-card", has_text="CARD-BLUE")
        assert not card.locator("dl").is_visible(), "the card starts closed"
        card.locator("summary").click()
        assert card.locator("dl").is_visible()
        text = " ".join(card.inner_text().split())
        for shown in ("RAAN 95.00°", "Inclination 0.04°", "Arg. of perigee 270.00°", "Mean anomaly 180.00°",
                      "Data mode MANUAL", "Regime GEO", "Epoch 2026-09-07 12:00:00 UTC"):
            assert shown in text, shown
        assert "° E at now" in text or "° W at now" in text
        card.locator("summary").click()
        assert not card.locator("dl").is_visible()
        assert console.problems() == []


class TestTheScreeningSelector:
    def test_a_blue_asset_added_on_the_panel_is_offered_without_a_reload(self, console: Console) -> None:
        page = console.open()
        page.wait_for_selector("#scr-asset", state="attached")
        assert page.locator('#scr-asset option[value="blue:SCREEN-BLUE"]').count() == 0
        with page.expect_response("**/plan/threat/screen-config*"):
            _add_blue(console, "SCREEN-BLUE")
        page.wait_for_timeout(300)
        option = page.locator('#scr-asset option[value="blue:SCREEN-BLUE"]')
        assert option.count() == 1
        assert option.inner_text() == "SCREEN-BLUE [30793] · GEO · MANUAL"
        assert console.problems() == []

    def test_the_asset_chosen_and_the_budget_typed_survive_an_add_and_a_duplicate_does_not_reload(
        self, console: Console,
    ) -> None:
        """Review of 0.47.0: each Blue-list answer reset the choice to the first HRR object and the budget to 500."""
        page = console.open()
        _add_blue(console, "KEEP-BLUE")
        page.wait_for_timeout(300)
        page.click('.htab[data-panel="hero-screen"]')
        page.select_option("#scr-asset", "blue:KEEP-BLUE")
        page.fill("#scr-max-dv", "1234")
        with page.expect_response("**/plan/threat/screen-config*"):
            _add_blue(console, "KEEP-OTHER")
        page.wait_for_timeout(300)
        assert page.input_value("#scr-asset") == "blue:KEEP-BLUE"
        assert page.input_value("#scr-max-dv") == "1234"
        assert page.locator('#scr-asset option[value="blue:KEEP-OTHER"]').count() == 1

        reloads: list[str] = []
        page.on("request", lambda request: reloads.append(request.url) if "screen-config" in request.url else None)
        _add_blue(console, "KEEP-OTHER")
        page.wait_for_timeout(500)
        assert "already in the session" in page.inner_text("#blue-list")
        assert reloads == [], "a duplicate add reloaded the selector"
        assert page.input_value("#scr-max-dv") == "1234"
        assert console.problems() == []


class TestTheSatelliteSelectors:
    def test_an_added_track_and_asset_reach_every_satellite_picker_without_a_reload(self, console: Console) -> None:
        """The list answer carries the pickers' options out of band, each in a plain carrier aimed at its select
        (partials/sat_select_oob.html): the options land in the select, which keeps its id and its label, and no
        carrier is left behind in the list."""
        page = console.open()
        page.fill("#red-tle-name", "PICK-RED")
        page.fill("#red-tle-text", _GEO)
        with page.expect_response("**/assets/red"):
            page.click('#red-track-form button[type="submit"]')
        page.wait_for_timeout(300)
        _add_blue(console, "PICK-BLUE")
        for select, name in (("#ie-red-sat", "PICK-RED"), ("#ts-red-sat", "PICK-RED"), ("#ie-blue-sat", "PICK-BLUE")):
            assert page.locator(f'{select} option[value="{name}"]').count() == 1, (select, name)
            assert page.locator(f"label:has({select})").count() == 1, f"{select} is still named by its label"
        assert page.locator("#red-list [hx-swap-oob], #blue-list [hx-swap-oob]").count() == 0
        assert page.locator("#red-list option, #blue-list option").count() == 0, "an option was left in a list"
        assert console.problems() == []
