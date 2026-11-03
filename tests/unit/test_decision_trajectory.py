"""Show trajectory: each propagated cell opens the existing Hill-frame view for its pair and window (SPC-124).

The view is the geometry route's Clohessy-Wiltshire picture, from both SGP4 states at its start, taking one burn on
the red track relative to the blue asset. A computed cell with no burn draws the pair from the scenario epoch over
the span searched. A cell with our burn draws it as the opposite change in red's relative velocity, from no more
than 24 h before the burn (the route's coast limit), and over the rest of the span. A sampled cell draws the
hypothesis's nominal burn, from the burn when it is before the window; with our burn as well, it says ours is not
drawn. A lookup or refused cell has no link. The m/s conversion is made once, here, at the unit boundary.
"""

from __future__ import annotations

import copy
import html
import re
from datetime import datetime, timedelta

import pytest

from spectre.astro.monte_carlo import BlueBurn
from spectre.domain import decision
from spectre.domain.decision import ScenarioResult, evaluate_scenario
from spectre.web.decision_trajectory import OURS_NOT_DRAWN, TrajectoryLink, trajectory_links
from spectre.web.routes.geometry import COAST_MAX_H, TOF_MAX_HOURS
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_computed import _MANOEUVRE, _NO_ACTION, _computed
from tests.unit.test_decision_figure_basis import _TEMPLATE_DIR
from tests.unit.test_decision_response import (
    _AVOID,
    _HOLD,
    _avoid,
    _computed_scenario,
    _hold,
    _sampled_scenario,
    _sized_stub,
    _WithBurns,
)
from tests.unit.test_decision_sampled import _elset, _steady

_AT = "%Y-%m-%dT%H:%M:%S"


@pytest.fixture(scope="module")
def plane() -> ScenarioResult:
    return _computed()


@pytest.fixture(scope="module")
def leo() -> ScenarioResult:
    return evaluate_scenario(_computed_scenario(_hold(), _avoid()))


def _link(result: ScenarioResult, row: int, col: int) -> TrajectoryLink:
    found = trajectory_links(result)[row][col]
    assert found is not None
    return found


class TestAComputedCell:
    def test_every_computed_cell_has_a_geometry_form(self, plane: ScenarioResult) -> None:
        """50: the bound stk_names, the scenario epoch, tof the span, no coast and no burn."""
        links = trajectory_links(plane)
        assert len(links) == len(plane.outcome_matrix)
        for row, cells in zip(links, plane.outcome_matrix, strict=True):
            assert len(row) == len(cells)
        for col in range(4):
            link = _link(plane, _NO_ACTION, col)
            assert (link.red_sat, link.blue_sat) == ("RED_PC", "BLUE_PC")
            assert link.burn_epoch_str == EPOCH.strftime(_AT)
            assert (link.red_epoch, link.blue_epoch) == (EPOCH.strftime(_AT), EPOCH.strftime(_AT))
            assert link.tof_hours == pytest.approx(1.0)
            assert link.coast_hours == 0.0
            assert (link.dv_prograde, link.dv_normal, link.dv_radial) == (0.0, 0.0, 0.0)
            assert link.context == "decision-sgp4"
            assert link.our_burn is False and link.note is None

    def test_a_lookup_cell_has_none(self, plane: ScenarioResult) -> None:
        assert all(cell is None for cell in trajectory_links(plane)[_MANOEUVRE])

    def test_an_unbound_result_has_none(self, plane: ScenarioResult) -> None:
        unbound = copy.copy(plane)
        unbound.scenario = copy.copy(plane.scenario)
        unbound.scenario.binding = None
        assert all(cell is None for row in trajectory_links(unbound) for cell in row)

    def test_the_aria_label_names_the_cell(self, plane: ScenarioResult) -> None:
        link = _link(plane, _NO_ACTION, 0)
        adversary = plane.scenario.adversary_actions[_NO_ACTION].name
        response = plane.scenario.friendly_responses[0].name
        assert link.aria_label == f"Show trajectory for {adversary} against {response}, in the Hill frame"


class TestOurBurn:
    def test_a_burn_cell_draws_our_burn_reversed_on_red(self, leo: ScenarioResult) -> None:
        """51: 3.085 m/s retrograde on blue is +3.085 m/s prograde on red relative to blue; coast the time to
        execute (0 h)."""
        link = _link(leo, 0, _AVOID)
        assert link.dv_prograde == pytest.approx(3.085, rel=0.01)
        assert link.dv_radial == pytest.approx(0.0, abs=1e-9) and link.dv_normal == pytest.approx(0.0, abs=1e-9)
        assert link.coast_hours == 0.0 and link.burn_epoch_str == EPOCH.strftime(_AT)
        assert link.tof_hours == pytest.approx(leo.outcome_matrix[0][_AVOID].ca_computed.window.span_s / 3600.0)  # type: ignore[union-attr]
        assert link.context == "decision-rk45" and link.our_burn is True

    def test_the_hold_cell_beside_it_is_rk45_with_no_burn(self, leo: ScenarioResult) -> None:
        link = _link(leo, 0, _HOLD)
        assert link.context == "decision-rk45" and link.our_burn is False
        assert (link.dv_prograde, link.coast_hours) == (0.0, 0.0)

    def _late(self, leo: ScenarioResult, at_h: float, span_h: float) -> ScenarioResult:
        """*leo* with its burn moved to *at_h* hours and the span to *span_h*: the drawing reads only these."""
        result = copy.copy(leo)
        result.outcome_matrix = [list(row) for row in leo.outcome_matrix]
        cell = copy.copy(leo.outcome_matrix[0][_AVOID])
        found, figure = cell.ca_computed, cell.ca_response
        assert found is not None and figure is not None and figure.sized.burn is not None
        cell.ca_computed = found._replace(window=found.window._replace(span_s=span_h * 3600.0))
        burn = BlueBurn(at_h * 3600.0, figure.sized.burn.delta_v_ric_km_s)
        cell.ca_response = copy.replace(figure, sized=figure.sized._replace(burn=burn),
                                        burn_at_utc=EPOCH + timedelta(hours=at_h))
        result.outcome_matrix[0][_AVOID] = cell
        return result

    def test_a_burn_two_hours_in_coasts_to_it(self, leo: ScenarioResult) -> None:
        link = _link(self._late(leo, 2.0, 6.0), 0, _AVOID)
        assert link.burn_epoch_str == EPOCH.strftime(_AT)
        assert (link.coast_hours, link.tof_hours) == (pytest.approx(2.0), pytest.approx(4.0))

    def test_a_burn_thirty_hours_in_starts_the_view_six_hours_in(self, leo: ScenarioResult) -> None:
        """53: the route coasts at most 24 h."""
        link = _link(self._late(leo, 30.0, 48.0), 0, _AVOID)
        assert link.burn_epoch_str == (EPOCH + timedelta(hours=6)).strftime(_AT)
        assert link.coast_hours == pytest.approx(24.0) == COAST_MAX_H
        assert link.tof_hours == pytest.approx(18.0)

    def test_a_span_past_the_route_limit_is_drawn_to_it(self, leo: ScenarioResult) -> None:
        link = _link(self._late(leo, 0.0, 200.0), 0, _AVOID)
        assert link.tof_hours == TOF_MAX_HOURS


class TestASampledCell:
    def test_a_sampled_cell_draws_reds_nominal_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """52: and, with our burn as well, says ours is not drawn."""
        monkeypatch.setattr(
            decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))),),
        )
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns(25.0))
        hypothesis = result.scenario.adversary_actions[0].hypothesis
        assert hypothesis is not None
        expected = tuple(hypothesis.delta_v_m_s * c for c in hypothesis.direction_ric)
        hold, avoid = _link(result, 0, _HOLD), _link(result, 0, _AVOID)
        for link in (hold, avoid):
            assert (link.dv_radial, link.dv_prograde, link.dv_normal) == pytest.approx(expected)
            assert link.burn_epoch_str == EPOCH.strftime(_AT) and link.coast_hours == 0.0
            assert link.tof_hours == pytest.approx(1.0)
            assert link.context == "decision-rk45" and link.our_burn is False
        assert hold.note is None
        assert avoid.note == OURS_NOT_DRAWN == (
            "Draws the adversary's nominal burn; our burn is not drawn, since this view takes one burn."
        )

    def test_the_view_ends_at_the_span_searched_not_the_horizon(self) -> None:
        """SPC-118: 20 h old on a 24 h limit over a 48 h horizon, the row searched 4 h, so the view stops there."""
        from tests.unit.test_decision_sampled import _evasive, _Fake
        from tests.unit.test_decision_sampled_span import _one_row

        result = evaluate_scenario(_one_row(_evasive(50), age_h=20.0), sampler=_Fake())
        assert result.searched_span_s == 4 * 3600.0 < result.scenario.horizon_hours * 3600.0
        link = _link(result, 0, 0)
        start = datetime.strptime(link.burn_epoch_str, _AT).replace(tzinfo=EPOCH.tzinfo)
        end = start + timedelta(hours=link.coast_hours + link.tof_hours)
        assert end == EPOCH + timedelta(hours=4)

    def test_a_burn_before_the_window_starts_the_view_at_the_burn(self) -> None:
        early = EPOCH - timedelta(hours=2)
        result = evaluate_scenario(
            decision.Scenario(
                name="Early", epoch_utc=EPOCH,
                adversary_actions=[decision.AdversaryAction("A0", "Burnt", decision.ActionType.MANOEUVRE, 0.5, 0.7,
                                                            hypothesis=_steady(50, at=early))],
                friendly_responses=[_hold()], horizon_hours=1.0,
                binding=decision.ScenarioBinding(
                    red=_elset("red", age=3.0, epoch=EPOCH - timedelta(hours=3)), blue=_elset("blue"),
                ),
            ),
            sampler=_WithBurns(),
        )
        link = _link(result, 0, 0)
        assert link.burn_epoch_str == early.strftime(_AT)
        assert (link.coast_hours, link.tof_hours) == (0.0, pytest.approx(3.0))
        assert link.dv_prograde == pytest.approx(1.0)


def _render_with_links(result: ScenarioResult) -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    from spectre.web.app import templates as _app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(_app_templates.env.filters)
    return env.get_template("partials/decision_results.html").render(result=result, links=trajectory_links(result))


class TestThePage:
    def test_every_show_trajectory_button_has_its_aria_label(self, plane: ScenarioResult) -> None:
        """62."""
        page = _render_with_links(plane)
        buttons = re.findall(r"<button[^>]*>\s*Show trajectory\s*</button>", page)
        links = [link for row in trajectory_links(plane) for link in row if link is not None]
        assert len(buttons) == len(links) == 12
        for link in links:
            assert f'aria-label="{link.aria_label}"' in page

    def test_each_button_name_starts_with_its_visible_label(self, leo: ScenarioResult) -> None:
        """WCAG 2.5.3 Label in Name: a speech user says "Show trajectory", so the accessible name must contain it,
        and starts with it."""
        page = _render_with_links(leo)
        buttons = re.findall(r'<button[^>]*aria-label="([^"]*)"[^>]*>([^<]*)</button>', page)
        assert buttons
        for name, visible in buttons:
            assert html.unescape(name).startswith(visible.strip()), (name, visible)

    def test_only_a_cell_with_our_burn_posts_our_burn(self, leo: ScenarioResult) -> None:
        """The route says our burn is drawn only when the form says so: a hold cell must post false."""
        page = _render_with_links(leo)
        posted = re.findall(r'<input type="hidden" name="our_burn" value="([a-z]+)">', page)
        expected = ["true" if link.our_burn else "false" for row in trajectory_links(leo) for link in row if link]
        assert posted == expected
        assert {"true", "false"} <= set(posted)

    def test_the_cell_that_opened_the_view_is_marked_for_focus(self, plane: ScenarioResult) -> None:
        """Every cell posts to the same view, so the results mark the form that was submitted; the view's close
        and Escape return focus to that cell, not the first such button on the page."""
        page = _render_with_links(plane)
        script = page[page.index('<div id="decision-geometry"'):]
        script = script[script.index("<script>"):script.index("</script>")]
        assert "setAttribute('data-geometry-opener'" in script
        assert "removeAttribute('data-geometry-opener')" in script
        assert "document.addEventListener" not in script, "scoped to the results table, not the whole console"

    def test_each_form_posts_the_route_fields(self, plane: ScenarioResult) -> None:
        page = _render_with_links(plane)
        form = page[page.index('<form class="show-trajectory"'):]
        form = form[:form.index("</form>")]
        assert 'hx-post="/plan/geometry/intercept"' in form
        for name in ("red_sat", "blue_sat", "burn_epoch_str", "dv_prograde", "dv_normal", "dv_radial", "tof_hours",
                     "coast_hours", "method", "red_epoch", "blue_epoch", "context", "our_burn"):
            assert f'name="{name}"' in form, name
        assert 'id="decision-geometry"' in page

    def test_the_sampled_note_is_beside_the_button(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))),),
        )
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns(25.0))
        assert html.unescape(_render_with_links(result)).count(OURS_NOT_DRAWN) == 1

    def test_no_link_is_drawn_without_links(self, plane: ScenarioResult) -> None:
        from tests.unit.test_decision_figure_basis import _render

        assert "Show trajectory" not in _render(plane)
