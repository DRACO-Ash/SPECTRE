"""A scenario may be bound to the real objects it is about; only the sampled and computed paths read it (SPC-100).

Binding a scenario to a held red track and blue asset records which objects
it is about, carries their element sets into the result's provenance and
shows how old they are. A row whose adversary action carries a hypothesis
reads it to sample that row's closest approach (SPC-112), and, bound on both
sides, a row whose action does not move red has its closest approach
computed from both element sets by SGP4 (SPC-120). These tests pin both
halves: the binding is carried and checked, and the lookup path never reads
it.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain import decision
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import (
    BINDING_NOTE,
    ActionType,
    AdversaryAction,
    BoundElset,
    Freshness,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    SelectorStrategy,
    compute_outcome_metrics,
    evaluate_scenario,
    find_robust_response,
)
from spectre.domain.provenance import tle_input
from spectre.web.elsets import ElsetAge
from tests.unit.test_decision_figure_basis import _render
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"


class _Tripwire:
    """A binding that fails the test the moment anything looks inside it."""

    def __getattr__(self, name: str) -> NoReturn:
        raise AssertionError(f"the lookup path read binding.{name}")

    def __bool__(self) -> NoReturn:
        raise AssertionError("the lookup path tested the binding for truth")

    def __eq__(self, other: object) -> NoReturn:
        raise AssertionError("the lookup path compared the binding")

    __hash__ = None  # type: ignore[assignment]

    def __iter__(self) -> NoReturn:
        raise AssertionError("the lookup path iterated the binding")


def _elset(
    side: str = "red", *, hours: float | None = 5.0, limit: float | None = 72.0, satno: int = 50322,
    stk_name: str = "RED_X",
) -> BoundElset:
    epoch = None if hours is None else _NOW - timedelta(hours=hours)
    return BoundElset(
        side=side,  # type: ignore[arg-type]
        name=stk_name, stk_name=stk_name, satno=satno,
        tle=_tle(epoch or _NOW, satno=satno), data_mode="REAL",
        epoch=epoch, age_hours=hours, limit_hours=limit,
    )


def _binding() -> ScenarioBinding:
    return ScenarioBinding(
        red=_elset("red", stk_name="RED_X"),
        blue=_elset("blue", stk_name="BLUE_Y", satno=40001, hours=30.0),
    )


def _four_by_four(binding: ScenarioBinding | None = None) -> Scenario:
    """One adversary row and one friendly row per action type: 16 pairings."""
    adversaries = [
        AdversaryAction(id=f"A{i}", name=t.value, action_type=t, probability=(5 + 2 * i) / 32, confidence=0.7)
        for i, t in enumerate(ActionType)
    ]
    friendlies = [
        FriendlyResponse(
            id=f"F{i}", name=t.value, action_type=t, cost=0.2 + 0.1 * i, reversibility=0.8 - 0.1 * i,
            time_to_execute_hours=2.0 + i,
        )
        for i, t in enumerate(ActionType)
    ]
    return Scenario(
        name="Bound or not", epoch_utc=_NOW, adversary_actions=adversaries,
        friendly_responses=friendlies, horizon_hours=48.0, binding=binding,
    )


class TestTheLookupPathNeverReadsTheBinding:
    def test_the_lookup_path_never_reads_the_binding(self) -> None:
        """SPC-125: the lookup model refuses a bound scenario, reading no more of the binding than that it is there."""
        scenario = _four_by_four()
        bound = dataclasses.replace(scenario)
        bound.binding = _Tripwire()  # type: ignore[assignment]
        with pytest.raises(ValueError, match="evaluate_scenario"):
            compute_outcome_metrics(bound.adversary_actions[0], bound.friendly_responses[0], bound)
        matrix = [
            [compute_outcome_metrics(a, f, scenario) for f in scenario.friendly_responses]
            for a in scenario.adversary_actions
        ]
        assert sum(len(row) for row in matrix) == 16
        chosen = {s: find_robust_response(scenario, matrix, s) for s in SelectorStrategy}
        assert set(chosen) == set(SelectorStrategy)
        assert all(r in scenario.friendly_responses for r in chosen.values())

    def test_the_tripwire_trips(self) -> None:
        with pytest.raises(AssertionError):
            bool(_Tripwire())
        with pytest.raises(AssertionError):
            _ = _Tripwire().red
        with pytest.raises(AssertionError):
            list(_Tripwire())
        with pytest.raises(AssertionError):
            _ = _Tripwire() == None  # noqa: E711 - the comparison is what must trip

    def test_binding_without_a_hypothesis_changes_only_the_closest_approach(self) -> None:
        """Inverted by SPC-120: bound on both sides, the rows that do not move red are computed.

        Before SPC-120, bound and unbound agreed on every figure, mark and choice. Now the three rows whose action
        does not move red share one computed closest approach and time, the manoeuvre row keeps its lookups and
        says why it is not computed, and custody, its gap and our delta-V are the lookups they were.
        """
        for strategy in SelectorStrategy:
            bound = evaluate_scenario(_four_by_four(_binding()), strategy)
            unbound = evaluate_scenario(_four_by_four(), strategy)
            for bound_row, unbound_row, action in zip(
                bound.outcome_matrix, unbound.outcome_matrix, bound.scenario.adversary_actions, strict=True,
            ):
                for cell, plain in zip(bound_row, unbound_row, strict=True):
                    assert (cell.custody_maintained, cell.custody_gap_hours, cell.delta_v_cost_km_s) == (
                        plain.custody_maintained, plain.custody_gap_hours, plain.delta_v_cost_km_s,
                    )
                    if action.action_type is ActionType.MANOEUVRE:
                        assert str(cell.ca_refusal).startswith("Not computed: a manoeuvre with no hypothesis")
                        assert dataclasses.replace(cell, ca_refusal=None, figure_bases=plain.figure_bases) == plain
                    else:
                        assert cell.ca_computed is not None and cell.ca_computed == bound_row[0].ca_computed
            # Bound with no custody status read, custody stays the rule of thumb (SPC-123); with one, it does not.
            assert bound.custody_rule_of_thumb == unbound.custody_rule_of_thumb
            assert bound.basis_lines != unbound.basis_lines
            assert "Closest approach: lookup in 4 of 16 cells, computed in 12." in bound.basis_lines

    def test_a_red_custody_status_replaces_the_rule_of_thumb(self) -> None:
        """K13, the other half of the pin above: bound with the red track's status read, custody is computed."""
        binding = _binding()
        status = CustodyStatus(Custody.HELD, "Custody held.")
        custodied = ScenarioBinding(red=dataclasses.replace(cast("BoundElset", binding.red), custody=status), blue=binding.blue)
        bound = evaluate_scenario(_four_by_four(custodied))
        unbound = evaluate_scenario(_four_by_four())
        assert unbound.custody_rule_of_thumb is True and bound.custody_rule_of_thumb is False
        assert "Custody: lookup in 4 of 16 cells, computed in 12." in bound.basis_lines


class TestABoundResultNamesItsElementSets:
    def test_a_bound_result_names_its_element_sets(self) -> None:
        binding = _binding()
        p = evaluate_scenario(_four_by_four(binding)).provenance
        assert p is not None
        assert [i.label for i in p.inputs] == ["scenario", "red RED_X", "blue BLUE_Y"]
        for ref, elset in zip(p.inputs[1:], binding.bound, strict=True):
            assert ref.epoch == elset.epoch
            assert ref.sha256 == tle_input(ref.label, elset.tle).sha256

    def test_bound_lists_red_first_and_skips_an_absent_side(self) -> None:
        red, blue = _elset("red"), _elset("blue", satno=40001)
        assert ScenarioBinding(red=red, blue=blue).bound == (red, blue)
        assert ScenarioBinding(blue=blue).bound == (blue,)


class TestFreshness:
    @pytest.mark.parametrize("limit", [24.0, 72.0])
    @pytest.mark.parametrize("offset", [-1.0, 0.0, 1e-6])
    def test_freshness_is_the_sweeps_staleness(self, limit: float, offset: float) -> None:
        hours = limit + offset
        stale = ElsetAge(epoch=_NOW, hours=hours, limit_hours=limit).stale
        freshness = _elset(hours=hours, limit=limit).freshness
        assert (freshness is Freshness.OUT_OF_DATE) is stale
        if offset == 0.0:
            assert freshness is Freshness.CURRENT, "an age equal to the limit is still current"

    def test_an_elset_past_its_limit_cannot_read_current(self) -> None:
        assert _elset(hours=100.0, limit=72.0).freshness is Freshness.OUT_OF_DATE
        assert _elset(hours=None, limit=None).freshness is Freshness.UNKNOWN

    @pytest.mark.parametrize(("epoch", "hours", "limit"), [
        (None, 5.0, 72.0),
        (_NOW, None, 72.0),
        (_NOW, 5.0, None),
        (_NOW, -1.0, 72.0),
        (_NOW, math.nan, 72.0),
        (_NOW, math.inf, 72.0),
        (_NOW, 5.0, 0.0),
        (_NOW, 5.0, math.inf),
    ])
    def test_age_facts_are_read_together(
        self, epoch: datetime | None, hours: float | None, limit: float | None,
    ) -> None:
        with pytest.raises(ValueError, match="epoch, age and limit|age|limit"):
            BoundElset(
                side="red", name="R", stk_name="R", satno=1, tle="t", data_mode="REAL",
                epoch=epoch, age_hours=hours, limit_hours=limit,
            )

    def test_an_age_of_zero_is_accepted(self) -> None:
        """elset_age clamps a future epoch to 0 h, so 0 h must bind, or the binder raises outside the try."""
        fresh = _elset(hours=0.0, limit=72.0)
        assert fresh.age_hours == 0.0
        assert fresh.freshness is Freshness.CURRENT
        assert fresh.age_label == "0.0 h"

    def test_each_freshness_has_its_sentence(self) -> None:
        current = _elset(hours=5.0, limit=72.0)
        assert current.sentence == "Orbit current: 5.0 h old at evaluation, limit 72 h."
        assert current.age_label == "5.0 h" and current.limit_label == "72 h"
        old = _elset(hours=13 * 24.0, limit=72.0)
        assert old.sentence == (
            "Orbit out of date: 13.0 d old at evaluation against a 72 h limit, "
            "so a burn since its epoch would not be seen."
        )
        unknown = _elset(hours=None, limit=None)
        assert unknown.sentence == "Its epoch cannot be read, so its age is unknown; read it as out of date."
        assert unknown.age_label is None and unknown.limit_label is None

    @pytest.mark.parametrize("hours", [5.0, 23.95, 24.0, 13 * 24.0])
    def test_the_age_label_is_the_sweeps(self, hours: float) -> None:
        assert _elset(hours=hours).age_label == ElsetAge(epoch=_NOW, hours=hours, limit_hours=72.0).label


class TestSides:
    def test_sides_are_checked(self) -> None:
        with pytest.raises(ValueError, match="red"):
            ScenarioBinding(red=_elset("blue"))
        with pytest.raises(ValueError, match="blue"):
            ScenarioBinding(blue=_elset("red"))
        with pytest.raises(ValueError, match="binding=None"):
            ScenarioBinding()
        with pytest.raises(ValueError, match="side"):
            _elset("green")


class TestWhatTheBindingSays:
    def test_the_note_says_which_rows_are_computed_and_which_sampled(self) -> None:
        """SPC-120: the note no longer says binding changes no figure without a hypothesis."""
        assert "changes no figure" not in BINDING_NOTE
        assert (
            "With both sides bound, the closest approach and its time are computed from these orbits by SGP4, with "
            "no burn, for every row whose action does not move the red track, and sampled for a row whose action "
            "carries a hypothesis" in BINDING_NOTE
        )
        assert "a manoeuvre with no hypothesis names no burn and stays a lookup" in BINDING_NOTE
        # Inverted by SPC-123: with a red track bound, custody is computed too, so not every other figure is a lookup.
        assert "Every other figure is still a lookup." not in BINDING_NOTE
        # Inverted by SPC-121: a manoeuvre response given a target separation has its burn sized; and by SPC-125: a
        # response that does not burn spends 0 m/s against the no-burn orbit, not a lookup.
        assert (
            "With a red track bound, custody is its custody as the sweep judges it at evaluation, carried over the "
            "horizon. Our delta-V is computed for a manoeuvre response given a target separation, and is 0 m/s for a "
            "response that does not burn wherever the closest approach is computed or sampled" in BINDING_NOTE
        )
        assert "km (lookup)" not in BINDING_NOTE and "custody (lookup)" not in BINDING_NOTE
        assert ScenarioBinding(red=_elset()).note is BINDING_NOTE

    def test_the_domain_does_not_import_the_web_layer(self) -> None:
        assert "spectre.web" not in inspect.getsource(decision)


def _strict(template: str, context: dict[str, Any]) -> str:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    return env.get_template(template).render(**context)


class TestTheTemplatesTolerateAMissingBinding:
    def test_the_templates_render_without_binding_under_strict_undefined(self) -> None:
        result = evaluate_scenario(_four_by_four())
        old = SimpleNamespace(**{
            f.name: getattr(result.scenario, f.name) for f in dataclasses.fields(result.scenario)
            if f.name != "binding"
        })
        assert not hasattr(old, "binding")
        result.scenario = old  # type: ignore[assignment]
        html = " ".join(_render(result).split())
        assert "Scenario not bound to a red track or blue asset." in html
        for template in ("partials/decision_panel.html", "partials/decision_bind_fields.html"):
            assert "Not bound" in _strict(template, {"pol": None}), template
