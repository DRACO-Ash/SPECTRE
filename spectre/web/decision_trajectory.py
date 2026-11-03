"""Show trajectory: the geometry route's form values for each Decision Engine cell (SPC-124).

The geometry route draws the red track relative to the blue asset in the Hill frame, from both SGP4 states at a
start time, with an optional coast and one burn on red. Each cell whose closest approach was propagated gets the
values that open that view for its pair and window:

  * a computed cell with no burn starts at the scenario epoch, with no burn, over the span searched;
  * a computed cell with our burn starts at the later of the scenario epoch and 24 h before the burn (the route's
    longest coast), coasts to the burn and draws it as the opposite change in red's relative velocity, over the
    rest of the span;
  * a sampled cell draws the hypothesis's nominal burn the same way, starting at the burn when it is before the
    window; the view takes one burn, so our burn in that cell is not drawn, and the cell says so.

A lookup or refused cell has no link. The view is a third model, Clohessy-Wiltshire, so the route says where its
figures come from and that the cell's stand. THIS IS THE UNIT BOUNDARY for the form: the astro package's km/s
becomes the route's m/s here, through to_m_s, once.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple, cast

from spectre.astro.elset_approach import ELSET_PROPAGATOR, ElsetApproach
from spectre.domain.decision import AdversaryHypothesis, BoundElset, OutcomeMetrics, ScenarioResult
from spectre.domain.decision_figures import ResponseFigure
from spectre.web.format_units import to_m_s
from spectre.web.routes.geometry import COAST_MAX_H, TOF_MAX_HOURS

#: The note beside the button of a sampled cell that also carries our burn.
OURS_NOT_DRAWN = "Draws the adversary's nominal burn; our burn is not drawn, since this view takes one burn."
#: Starts with the button's visible text, so a speech user who says "Show trajectory" reaches it (WCAG 2.5.3).
_ARIA = "Show trajectory for {adversary} against {response}, in the Hill frame"
_AT = "%Y-%m-%dT%H:%M:%S"
_SECONDS_PER_HOUR = 3600.0
_LONGEST_COAST = timedelta(hours=COAST_MAX_H)
#: Which propagator the cell's figures come from, as the geometry route's allowlist names it.
SGP4_CONTEXT = "decision-sgp4"
RK45_CONTEXT = "decision-rk45"


class TrajectoryLink(NamedTuple):
    """The geometry route's form values for one cell: velocities in m/s, times in hours, epochs as text."""

    red_sat: str
    blue_sat: str
    burn_epoch_str: str
    dv_radial: float
    dv_prograde: float
    dv_normal: float
    tof_hours: float
    coast_hours: float
    red_epoch: str
    blue_epoch: str
    context: str
    our_burn: bool
    aria_label: str
    note: str | None


class _View(NamedTuple):
    """Where the drawing starts, how long it coasts to the burn, the burn on red in RIC m/s, and the flight after."""

    start: datetime
    coast_s: float
    dv_ric_m_s: tuple[float, float, float]
    tof_s: float


_NO_BURN = (0.0, 0.0, 0.0)


def _burn_view(start: datetime, end: datetime, burn_at: datetime, dv_ric_m_s: tuple[float, float, float]) -> _View:
    """A burn at *burn_at* drawn over the window *start* to *end*: from the burn when it is before the window, else
    from no more than the longest coast before it."""
    view_start = burn_at if burn_at < start else max(start, burn_at - _LONGEST_COAST)
    return _View(view_start, (burn_at - view_start).total_seconds(), dv_ric_m_s, (end - burn_at).total_seconds())


def _m_s(ric_km_s: tuple[float, float, float], sign: float = 1.0) -> tuple[float, float, float]:
    return cast("tuple[float, float, float]", tuple(sign * cast("float", to_m_s(c)) for c in ric_km_s))


def _computed_view(found: ElsetApproach, figure: ResponseFigure | None) -> tuple[_View, bool]:
    """The computed cell's view, and whether it draws our burn."""
    window = found.window
    end = window.start_utc + timedelta(seconds=window.span_s)
    if figure is None or figure.sized.burn is None:
        return _View(window.start_utc, 0.0, _NO_BURN, window.span_s), False
    burn = figure.sized.burn
    at = window.start_utc + timedelta(seconds=burn.at_s)
    # Our burn changes blue's velocity; relative to blue, red's changes by the opposite.
    return _burn_view(window.start_utc, end, at, _m_s(burn.delta_v_ric_km_s, -1.0)), True


def _sampled_view(result: ScenarioResult, carried: AdversaryHypothesis) -> _View:
    """The sampled cell's view: the hypothesis's nominal burn, over the span searched."""
    start = result.scenario.epoch_utc
    end = start + timedelta(seconds=result.searched_span_s)
    dv = cast("tuple[float, float, float]", tuple(carried.delta_v_m_s * c for c in carried.direction_ric))
    return _burn_view(start, end, carried.hypothesis.epoch_utc, dv)


def _epoch(elset: BoundElset) -> str:
    return "" if elset.epoch is None else elset.epoch.strftime(_AT)


class _CellView(NamedTuple):
    view: _View
    ours: bool
    context: str
    note: str | None


def _cell_view(result: ScenarioResult, i: int, cell: OutcomeMetrics) -> _CellView | None:
    """What a propagated cell draws; None for a lookup or refused one. Read with getattr, so an older cell works."""
    figure = getattr(cell, "ca_response", None)
    found = getattr(cell, "ca_computed", None)
    if found is not None:
        view, ours = _computed_view(found, figure)
        return _CellView(view, ours, SGP4_CONTEXT if found.propagator == ELSET_PROPAGATOR else RK45_CONTEXT, None)
    if getattr(cell, "ca_percentiles", None) is None:
        return None
    note = OURS_NOT_DRAWN if figure is not None and figure.sized.burn is not None else None
    carried = cast("AdversaryHypothesis", result.scenario.adversary_actions[i].hypothesis)
    return _CellView(_sampled_view(result, carried), False, RK45_CONTEXT, note)


def _link(result: ScenarioResult, i: int, j: int) -> TrajectoryLink | None:
    scenario = result.scenario
    binding = scenario.binding
    if binding is None or binding.red is None or binding.blue is None:
        return None
    drawn = _cell_view(result, i, result.outcome_matrix[i][j])
    if drawn is None:
        return None
    view = drawn.view
    radial, prograde, normal = view.dv_ric_m_s
    return TrajectoryLink(
        red_sat=binding.red.stk_name, blue_sat=binding.blue.stk_name, burn_epoch_str=view.start.strftime(_AT),
        dv_radial=radial, dv_prograde=prograde, dv_normal=normal,
        tof_hours=min(view.tof_s / _SECONDS_PER_HOUR, TOF_MAX_HOURS), coast_hours=view.coast_s / _SECONDS_PER_HOUR,
        red_epoch=_epoch(binding.red), blue_epoch=_epoch(binding.blue), context=drawn.context, our_burn=drawn.ours,
        aria_label=_ARIA.format(
            adversary=scenario.adversary_actions[i].name, response=scenario.friendly_responses[j].name,
        ),
        note=drawn.note,
    )


def trajectory_links(result: ScenarioResult) -> list[list[TrajectoryLink | None]]:
    """Per cell, the geometry form that draws it, or None for a lookup or refused cell, or an unbound scenario."""
    return [[_link(result, i, j) for j in range(len(row))] for i, row in enumerate(result.outcome_matrix)]
