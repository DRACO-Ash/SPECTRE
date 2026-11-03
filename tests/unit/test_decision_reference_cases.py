"""The gate SPC-110 and SPC-120 must pass: three hand-checked closest approaches (SPC-102).

Co-planar LEO, GEO drift-in and a plane change, each a pair of element sets
with a miss distance and a time of closest approach (TCA) from a closed form,
checked here by an independent RK4 two-body integration
(tests/unit/_decision_reference.py). Every path in PATHS must reproduce every
case within its tolerances, from a window starting at the element-set epoch
and from one starting ORIGIN_OFFSET_S later.

PATHS holds the SPECTRE SGP4 path through the closest-approach helper and
SPC-110's "monte_carlo_nominal": the Monte Carlo separation series with one
undispersed sample and no burn, red and blue both on its RK45 model from
their SGP4 states at the window start. SPC-120 adds "decision_phase3": the
Decision Engine itself, evaluating a scenario bound to both element sets with
one row whose action does not move red, so its closest approach is computed
by SGP4 on both objects. Each item is done only when its own path passes
every case at both window starts.

A path with both objects in the same wrong frame passes, because separation
does not depend on the frame; a path that mixes frames between the two
objects fails.
"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from spectre.astro.closest_approach import ClosestApproach, closest_approach
from spectre.astro.monte_carlo import ManoeuvreHypothesis, SeparationWindow, elset_state, run_separation_series
from spectre.astro.propagator import TLE_ERRORS, TLEOrbit, tle_checksum_valid
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    BoundElset,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    evaluate_scenario,
)
from tests.unit import _decision_reference as reference
from tests.unit._decision_reference import (
    EPOCH,
    GATED_ITEMS,
    ORIGIN_OFFSET_S,
    REFERENCE_CASES,
    Circular,
    ReferenceCase,
    coplanar_closed_form,
    crossing_closed_form,
    element_set,
    mean_motion_rev_day,
    parabolic_minimum,
    two_body_separation,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_SOURCE = Path(reference.__file__)
_ALLOWED_IMPORTS = {"__future__", "math", "dataclasses", "datetime", "numpy"}
_TLE_LINE_LENGTH = 69
_WINDOW_STARTS = (0.0, ORIGIN_OFFSET_S)
# How far above the reference miss any other minimum or edge must sit, in tolerances.
_ONE_ENCOUNTER_MARGIN = 5.0

ApproachPath = Callable[[ReferenceCase, float], ClosestApproach]


def _sgp4_separation(case: ReferenceCase, start_s: float) -> Callable[[float], float]:
    """Separation in km at t seconds after a window starting *start_s* after epoch, through TLEOrbit."""
    blue, red = TLEOrbit(case.blue_tle), TLEOrbit(case.red_tle)

    def separation(t: float) -> float:
        when = EPOCH + timedelta(seconds=start_s + t)
        try:
            return float(np.linalg.norm(blue.propagate(when).r - red.propagate(when).r))
        except TLE_ERRORS:
            return math.inf

    return separation


def _monte_carlo_nominal(case: ReferenceCase, start_s: float) -> ClosestApproach:
    """The separation series' one nominal sample: no burn, no spread, negligible drag (B* 0, floored), at the window start."""
    start = EPOCH + timedelta(seconds=start_s)
    blue, red = elset_state(case.blue_tle, start), elset_state(case.red_tle, start)
    assert blue is not None and red is not None
    hypothesis = ManoeuvreHypothesis(
        epoch_utc=start,
        delta_v_magnitude_km_s=0.0,
        delta_v_radial=0.0, delta_v_in_track=0.0, delta_v_cross_track=0.0,
        pre_manoeuvre_state_eci_km=red.state_eci_km,
        delta_v_magnitude_1sigma_km_s=0.0,
        delta_v_pointing_1sigma_deg=0.0,
        epoch_1sigma_seconds=0.0,
        bstar_post=0.0,
        bstar_1sigma=0.0,
        n_samples=1,
    )
    window = SeparationWindow(start_utc=start, span_s=case.horizon_s - start_s, step_s=case.step_s)
    series = run_separation_series(hypothesis, blue, window)
    assert series.n_failed == 0
    return series.approaches[0]


#: Each case's element-set limit, hours: the sweep's 72 h for GEO, 24 h otherwise.
_LIMIT_HOURS: dict[str, float] = {"coplanar_leo": 24.0, "geo_drift_in": 72.0, "plane_change": 24.0}


def _decision_phase3(case: ReferenceCase, start_s: float) -> ClosestApproach:
    """The Decision Engine's computed closest approach (SPC-120): one NO_ACTION row, both sides bound.

    The scenario starts *start_s* after the element-set epoch, so each element set is that old at evaluation,
    against its regime's limit, and its horizon runs to the case's horizon.
    """
    age_h = start_s / 3600.0

    def bound(side: str, tle: str, satno: int) -> BoundElset:
        return BoundElset(
            side=side, name=f"{side} {case.name}", stk_name=f"{side.upper()}_{case.name.upper()}",  # type: ignore[arg-type]
            satno=satno, tle=tle, data_mode="REAL", epoch=EPOCH, age_hours=age_h,
            limit_hours=_LIMIT_HOURS[case.name],
        )

    scenario = Scenario(
        name=case.title, epoch_utc=EPOCH + timedelta(seconds=start_s),
        adversary_actions=[AdversaryAction("A0", "No action", ActionType.NO_ACTION, 0.5, 0.5)],
        friendly_responses=[FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0)],
        horizon_hours=(case.horizon_s - start_s) / 3600.0,
        binding=ScenarioBinding(red=bound("red", case.red_tle, 90002), blue=bound("blue", case.blue_tle, 90001)),
    )
    cell = evaluate_scenario(scenario).outcome_matrix[0][0]
    assert cell.ca_computed is not None, cell.ca_refusal
    return cell.ca_computed.approach


PATHS: dict[str, ApproachPath] = {
    "sgp4": lambda c, s0: closest_approach(_sgp4_separation(c, s0), c.horizon_s - s0, step_s=c.step_s),
    "monte_carlo_nominal": _monte_carlo_nominal,
    "decision_phase3": _decision_phase3,
}

_CLOSED_FORMS: dict[str, Callable[[Circular, Circular], tuple[float, float]]] = {
    "coplanar_leo": coplanar_closed_form,
    "geo_drift_in": coplanar_closed_form,
    "plane_change": crossing_closed_form,
}

_LITERAL_LINES = {
    "coplanar_leo": (
        "2 90001  51.6000  40.0000 0000000   0.0000   0.0000 15.21936487    15",
        "2 90002  51.6000  40.0000 0000000   0.0000   2.0000 15.18623435    10",
    ),
    "geo_drift_in": (
        "2 90001   0.0500  80.0000 0000000   0.0000 100.0000  1.00273791    17",
        "2 90002   0.0500  80.0000 0000000   0.0000  99.5000  1.00380904    15",
    ),
    "plane_change": (
        "2 90001  97.4000  40.0000 0000000   0.0000   1.4000 15.05490646    12",
        "2 90002  97.4000  43.0000 0000000   0.0000   1.7000 15.05490646    19",
    ),
}
_LITERAL_LINE1 = (
    "1 90001U 26001A   26290.50000000  .00000000  00000-0  00000-0 0  9993",
    "1 90002U 26001A   26290.50000000  .00000000  00000-0  00000-0 0  9994",
)

_CASE_IDS = [case.name for case in REFERENCE_CASES]


def _repo_only(name: str) -> Path:
    """A repository-only path; skip when the packaged build leaves it out (.board and docs)."""
    path = _REPO_ROOT / name
    if not path.exists():
        pytest.skip(f"{name} is excluded from the submission package")
    return path


def _local_minima(seps: np.ndarray) -> list[int]:
    """Interior indices whose sample is strictly below both neighbours."""
    return [k for k in range(1, len(seps) - 1) if seps[k] < seps[k - 1] and seps[k] < seps[k + 1]]


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=_CASE_IDS)
def test_each_closed_form_gives_its_hand_checked_literal(case: ReferenceCase) -> None:
    miss, tca = _CLOSED_FORMS[case.name](case.blue, case.red)
    assert miss == pytest.approx(case.miss_km, abs=0.001)
    assert tca == pytest.approx(case.tca_s, abs=0.1)


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=_CASE_IDS)
def test_an_independent_two_body_integration_agrees(case: ReferenceCase) -> None:
    miss, tca = parabolic_minimum(*two_body_separation(case))
    assert miss == pytest.approx(case.miss_km, abs=0.001)
    assert tca == pytest.approx(case.tca_s, abs=0.5)


def test_the_reference_imports_only_its_allowlist() -> None:
    tree = ast.parse(_REFERENCE_SOURCE.read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported, "the scan found no imports at all"
    assert imported <= _ALLOWED_IMPORTS, sorted(imported - _ALLOWED_IMPORTS)


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=_CASE_IDS)
def test_the_element_sets_are_the_stated_elements(case: ReferenceCase) -> None:
    for body, tle, literal1, literal2 in zip(
        (case.blue, case.red), (case.blue_tle, case.red_tle), _LITERAL_LINE1, _LITERAL_LINES[case.name], strict=True,
    ):
        line1, line2 = tle.split("\n")
        assert (line1, line2) == (literal1, literal2)
        assert tle == element_set(body)
        for line in (line1, line2):
            assert len(line) == _TLE_LINE_LENGTH
            assert tle_checksum_valid(line), line
        assert float(line2[8:16]) == pytest.approx(body.inc_deg, abs=1e-4)
        assert float(line2[17:25]) == pytest.approx(body.raan_deg, abs=1e-4)
        assert float(line2[43:51]) == pytest.approx(body.u_deg, abs=1e-4)
        assert float(line2[52:63]) == pytest.approx(mean_motion_rev_day(body), abs=1e-8)


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=_CASE_IDS)
def test_each_case_has_one_encounter_in_its_horizon(case: ReferenceCase) -> None:
    times, seps = two_body_separation(case)
    floor = case.miss_km + _ONE_ENCOUNTER_MARGIN * case.miss_tol_km
    encounter = int(np.argmin(seps))
    assert abs(times[encounter] - case.tca_s) < case.rk4_dt_s
    others = [(float(times[k]), float(seps[k])) for k in _local_minima(seps) if k != encounter]
    assert all(sep >= floor for _, sep in others), others
    assert seps[0] >= floor
    assert seps[-1] >= floor


@pytest.mark.parametrize("start_s", _WINDOW_STARTS, ids=["from-epoch", "from-epoch-plus-600s"])
@pytest.mark.parametrize("case", REFERENCE_CASES, ids=_CASE_IDS)
@pytest.mark.parametrize("path", sorted(PATHS))
def test_every_path_reproduces_every_case(path: str, case: ReferenceCase, start_s: float) -> None:
    result = PATHS[path](case, start_s)
    expected_tca = case.tca_s - start_s
    message = (
        f"{case.name}: {path} gives {result.miss_km:.3f} km at {result.tca_s:.1f} s from a window starting "
        f"{start_s:.0f} s after epoch; the reference is {case.miss_km:.3f} km at {expected_tca:.1f} s, "
        f"within {case.miss_tol_km} km and {case.tca_tol_s} s"
    )
    assert abs(result.miss_km - case.miss_km) <= case.miss_tol_km, message
    assert abs(result.tca_s - expected_tca) <= case.tca_tol_s, message
    assert result.at_window_edge is False, message


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=_CASE_IDS)
def test_the_tolerances_are_tighter_than_the_unrefined_error(case: ReferenceCase) -> None:
    separation = _sgp4_separation(case, 0.0)
    steps = round(case.horizon_s / case.step_s)
    samples = [(separation(k * case.step_s), k * case.step_s) for k in range(steps + 1)]
    miss, tca = min(samples)
    miss_error, tca_error = abs(miss - case.miss_km), abs(tca - case.tca_s)
    assert miss_error > case.miss_tol_km or tca_error > case.tca_tol_s, (miss_error, tca_error)


def _section(text: str, heading: str) -> str:
    after = text.split(heading, 1)[1]
    return after.split("\n## ", 1)[0]


def test_the_gate_is_written_into_the_plan() -> None:
    items = json.loads(_repo_only(".board/items.json").read_text(encoding="utf-8"))
    deps = {item["ref"]: item.get("deps", []) for item in items}
    assert all("SPC-102" in deps[ref] for ref in GATED_ITEMS), {ref: deps[ref] for ref in GATED_ITEMS}
    doc = _repo_only("docs/decision_engine_phases.md").read_text(encoding="utf-8")
    gate = "tests/unit/test_decision_reference_cases.py"
    assert gate in _section(doc, "## Phase 2")
    assert gate in _section(doc, "## Phase 3")
