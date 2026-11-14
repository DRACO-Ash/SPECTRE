"""The closest approach before and after a burn, for Interactions (SPC-173).

Concept section 5.4: a closest approach after a burn counts only when it is
closer than before it. Before is the red object's last element set from
before the burn, flown across the same window as if it had not burned;
after is its set from after the burn. Both are searched against the same
blue set by the shared helper, and the pair carries the position error the
sweep assumes for each set at its own TCA (SPC-118), so a change smaller
than that is not read as closer.
"""

from __future__ import annotations

from datetime import timedelta

from spectre.astro.elset_approach import (
    BurnApproach,
    ElsetFailure,
    burn_approach,
    elset_closest_approach,
    elset_position_error_km,
)
from spectre.astro.monte_carlo import SeparationWindow
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN

_WINDOW = SeparationWindow(EPOCH, 24 * 3600.0)
_BEFORE = (COPLANAR_LEO.red_tle, EPOCH - timedelta(hours=6))
_AFTER = (GEO_DRIFT_IN.red_tle, EPOCH - timedelta(hours=2))
_BLUE = (GEO_DRIFT_IN.blue_tle, EPOCH - timedelta(hours=12))


class TestBeforeAndAfter:
    def test_each_side_is_its_own_red_set_against_the_same_blue_set_over_one_window(self) -> None:
        found = burn_approach(_BEFORE, _AFTER, _BLUE, _WINDOW)
        assert isinstance(found, BurnApproach)
        assert found.before == elset_closest_approach(_BEFORE[0], _BLUE[0], _WINDOW)
        assert found.after == elset_closest_approach(_AFTER[0], _BLUE[0], _WINDOW)

    def test_the_margin_is_the_position_error_of_both_sets_at_each_tca(self) -> None:
        found = burn_approach(_BEFORE, _AFTER, _BLUE, _WINDOW)
        assert isinstance(found, BurnApproach)
        at_before = EPOCH + timedelta(seconds=found.before.approach.tca_s)
        at_after = EPOCH + timedelta(seconds=found.after.approach.tca_s)
        expected = (elset_position_error_km(_BEFORE[0], _BEFORE[1], at_before)
                    + elset_position_error_km(_BLUE[0], _BLUE[1], at_before)
                    + elset_position_error_km(_AFTER[0], _AFTER[1], at_after)
                    + elset_position_error_km(_BLUE[0], _BLUE[1], at_after))
        assert found.margin_km == expected
        assert found.after_tca == at_after


class TestAFailureNamesItsSide:
    def test_a_before_set_that_does_not_parse_is_refused_as_red(self) -> None:
        assert burn_approach(("not an element set", EPOCH), _AFTER, _BLUE, _WINDOW) == ElsetFailure("red", "unparsable")

    def test_an_after_set_that_does_not_parse_is_refused_as_red(self) -> None:
        assert burn_approach(_BEFORE, ("not an element set", EPOCH), _BLUE, _WINDOW) == ElsetFailure("red", "unparsable")

    def test_a_blue_set_that_does_not_parse_is_refused_as_blue(self) -> None:
        assert burn_approach(_BEFORE, _AFTER, ("not an element set", EPOCH), _WINDOW) == ElsetFailure(
            "blue", "unparsable")
