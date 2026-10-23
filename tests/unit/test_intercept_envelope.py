"""The intercept-envelope sweep, held to numbers worked out in this file.

``intercept_envelope_intercept`` was rewritten this release from a radius-only
analytic estimate into a 24-step Lambert sweep, then changed again to raise when
nothing is feasible, to take the operator's budget as ``max_delta_v_km_s``, and
to drop a points list nothing read. None of it was tested. The engineering gate
replaced the whole sweep body with three constants and all 1,397 tests stayed
green, because no test file in the repository named the function.

Every expected figure below is re-derived from the CONTRACT, which is 24 arrival
times spread evenly across the time of flight and solved with ``solve_lambert``,
rather than read back out of the implementation. Each test says why the
magnitude it asserts is the one the physics gives, because a test that only
checks the shape of the answer is what let the original defect ship.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.lambert import solve_lambert
from spectre.astro.maneuvers import intercept_envelope_intercept
from spectre.astro.propagator import TLEOrbit
from spectre.domain.manoeuvre_calibration import (
    DEFAULT_SWEEP_BUDGET_M_S,
    from_km_s,
    to_km_s,
)

#: The TLE epoch of every pair below is day 60 of 2026, so the sweep starts at
#: the epoch and SGP4 is never asked to extrapolate far enough for the drag term
#: to matter. The pairs are synthetic for exactly that reason: a real catalogue
#: object drifts, and a test that has to be re-derived each year is a test that
#: gets deleted.
_EPOCH = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

#: The sweep's own shape, restated here so the reference calculation does not
#: import the implementation's private arithmetic.
_SWEEP_STEPS = 24
_SWEEP_TOF_S = 172800.0

# Two satellites on the GEO belt, one degree apart, inclination and
# eccentricity near zero. This is the geometry the tool exists to assess: a
# co-orbital neighbour closing on a station-kept asset.
_RED_GEO = (
    "1 90001U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90001   0.0500  95.0000 0001000   0.0000  10.0000  1.00270000    10"
)
_BLUE_GEO_ONE_DEGREE_AHEAD = (
    "1 90002U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90002   0.0500  95.0000 0001000   0.0000  11.0000  1.00270000    10"
)
# The same belt, but placed so that the 12 h arrival puts blue diametrically
# opposite red's departure point. See TestDegenerateStepsAreDropped.
_BLUE_GEO_OPPOSED_AT_TWELVE_HOURS = (
    "1 90003U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90003   0.0500  95.0000 0001000   0.0000   9.5100  1.00270000    10"
)
# A 415 km, 51.64 degree LEO object. Nothing it can do reaches the belt inside
# any budget an operator would type.
_RED_LEO = (
    "1 90004U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90004  51.6400 208.9163 0006703  40.5765 319.5681 15.49560532    10"
)


class _ReferenceSweep(NamedTuple):
    """What the sweep should have found, computed without calling it."""

    #: (time of flight in seconds, total delta-V in km/s) per feasible arrival.
    feasible: list[tuple[float, float]]
    #: Arrival times the Lambert solver refused, which are not intercepts.
    dropped: int

    @property
    def cheapest(self) -> tuple[float, float]:
        return min(self.feasible, key=lambda row: row[1])

    @property
    def earliest(self) -> tuple[float, float]:
        return min(self.feasible, key=lambda row: row[0])


def _reference_sweep(
    red_tle: str,
    blue_tle: str,
    budget_km_s: float,
    tof_s: float = _SWEEP_TOF_S,
) -> _ReferenceSweep:
    """Solve the same 24 Lambert problems independently of the sweep.

    Written from the documented contract rather than copied from the loop it
    checks, so that replacing the loop body with constants, which is how the
    engineering gate found the defect, cannot leave this agreeing with it.
    """
    departure = TLEOrbit(red_tle).propagate(_EPOCH)
    target_orbit = TLEOrbit(blue_tle)
    feasible: list[tuple[float, float]] = []
    dropped = 0
    for index in range(_SWEEP_STEPS):
        tof = tof_s * (index + 1) / _SWEEP_STEPS
        try:
            arrival = target_orbit.propagate(_EPOCH + timedelta(seconds=tof))
            arc = solve_lambert(
                departure.r, arrival.r, tof,
                mu=MU_EARTH, v1_initial=departure.v, v2_target=arrival.v,
            )
        except (ValueError, RuntimeError):
            dropped += 1
            continue
        if arc.total_delta_v <= budget_km_s:
            feasible.append((tof, arc.total_delta_v))
    return _ReferenceSweep(feasible=feasible, dropped=dropped)


class TestAFeasibleCoOrbitalIntercept:
    """One degree of GEO belt, which is the cheap case and must stay cheap."""

    def test_the_reported_cost_is_the_cheapest_lambert_arc_in_the_sweep(self) -> None:
        """6.3 m/s, and that figure is what a one degree belt move costs.

        The belt turns at 15.0 deg/h. To arrive one degree ahead of where it
        would otherwise have been after 22 h, red must raise its mean motion by
        one degree in 22 h, which is 2.0e-3 of its semi-major axis, about 85 km,
        and it has to leave the belt radius and return to it. Two impulses at
        that scale come to single-digit m/s, which is the order the calibration
        assessment records for GEO relocation: 11 m/s for 62 degrees over 30
        days, 170 m/s for 90 degrees in 3 days. It also sits inside the 15 m/s
        BENIGN ceiling ``manoeuvre_calibration`` gives GEO phasing, which is
        where a one degree reposition belongs.
        """
        reference = _reference_sweep(_RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, budget_km_s=0.5)
        assert reference.dropped == 0, "this geometry is clean; no step should be refused"
        cheapest_tof_s, cheapest_dv_km_s = reference.cheapest

        solution = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
        )

        assert solution.method == "intercept_envelope"
        assert cheapest_tof_s == pytest.approx(79200.0), (
            "the cheapest arrival is 22 h, just inside one belt revolution; a sweep "
            "that found it anywhere else is not stepping where the contract says"
        )
        assert solution.total_delta_v == pytest.approx(cheapest_dv_km_s, rel=1e-12), (
            "the sweep must report the cheapest arc it found, not an average, not the "
            "last one, and not a constant"
        )
        cost_m_s = from_km_s(solution.total_delta_v)
        assert 1.0 < cost_m_s < 15.0, (
            f"a one degree GEO reposition inside a day costs single-digit m/s; this "
            f"reports {cost_m_s:.1f} m/s"
        )

    def test_miss_distance_km_carries_the_feasible_count(self) -> None:
        """The field is overloaded, so its value has to be checked, not trusted.

        ``miss_distance_km`` holds a COUNT for this method, which the docstring
        states and no other method does. 11 of the 24 arrivals come in under
        500 m/s: every one inside the first belt revolution except the 24 h
        wrap, where the transfer angle collapses and the cost jumps to 8.9 km/s.
        """
        reference = _reference_sweep(_RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, budget_km_s=0.5)

        solution = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
        )

        assert len(reference.feasible) == 11
        assert solution.miss_distance_km == pytest.approx(float(len(reference.feasible))), (
            "miss_distance_km carries the number of feasible arrival times for this "
            "method; a value that ignores the sweep is a count of nothing"
        )

    def test_the_arrival_epoch_is_the_earliest_feasible_arrival(self) -> None:
        """Pins a decoupling this stream cannot fix, so it cannot drift unseen.

        ``total_delta_v`` is the CHEAPEST arc and the arrival epoch is the
        EARLIEST feasible one, and for this pair those are different arrivals:
        2 h against 22 h. The quoted cost therefore does not belong to the
        quoted arrival time. Asserted as it stands rather than corrected,
        because this stream owns no file under ``spectre/``, and reported
        upwards instead.
        """
        reference = _reference_sweep(_RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, budget_km_s=0.5)
        earliest_tof_s, _ = reference.earliest

        solution = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
        )

        assert earliest_tof_s == pytest.approx(7200.0)
        assert solution.departure_epoch == _EPOCH
        assert solution.arrival_epoch == _EPOCH + timedelta(seconds=earliest_tof_s)


class TestNothingFeasibleRaises:
    """A LEO object cannot reach the belt, and the sweep has to say so."""

    def test_an_unreachable_pair_raises_value_error(self) -> None:
        """415 km and 51.64 degrees against GEO: no arrival time saves it.

        A Hohmann transfer from a 415 km orbit to the belt costs about 3.9 km/s
        before the 51.6 degree plane change is paid for, and the sweep's
        single-revolution arcs are nowhere near Hohmann-optimal, so the cheapest
        of the 24 comes in at 11.1 km/s. That is 22 times the 500 m/s budget,
        which is a margin no numerical detail is going to close.
        """
        reference = _reference_sweep(_RED_LEO, _BLUE_GEO_ONE_DEGREE_AHEAD, budget_km_s=0.5)
        assert reference.feasible == []

        with pytest.raises(ValueError):
            intercept_envelope_intercept(
                _RED_LEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
            )

    def test_the_message_names_the_budget_and_the_arrival_times_swept(self) -> None:
        """The operator sees this string, so it has to carry both numbers.

        Without the budget the message cannot be told from a solver failure, and
        the operator cannot tell whether raising their own figure would help.
        Without the count of arrival times it does not say how hard the sweep
        looked before giving up.
        """
        with pytest.raises(ValueError) as refusal:
            intercept_envelope_intercept(
                _RED_LEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
            )

        message = str(refusal.value)
        assert "0.500 km/s" in message, f"the budget is missing from: {message}"
        assert "24 arrival times" in message, f"the sweep width is missing from: {message}"
        assert "48.0 h" in message


class TestDegenerateStepsAreDropped:
    """A gap in the sweep is no intercept, not a cheap one."""

    def test_the_twelve_hour_arrival_is_a_degenerate_lambert_geometry(self) -> None:
        """Proves the branch under test is really reached by this pair.

        Half a degree of belt separation, chosen so that 12 h into the sweep the
        belt has carried blue to within 0.004 degrees of the point diametrically
        opposite red's departure position. At 180 degrees every plane containing
        the two radii is admissible, so ``solve_lambert`` refuses rather than
        returning the confident answer that missed by 74,790 km. This is the
        GEO phasing case, not a contrived one.
        """
        departure = TLEOrbit(_RED_GEO).propagate(_EPOCH)
        twelve_hours_s = _SWEEP_TOF_S * 6 / _SWEEP_STEPS
        arrival = TLEOrbit(_BLUE_GEO_OPPOSED_AT_TWELVE_HOURS).propagate(
            _EPOCH + timedelta(seconds=twelve_hours_s)
        )

        with pytest.raises(ValueError, match="degenerate Lambert geometry"):
            solve_lambert(
                departure.r, arrival.r, twelve_hours_s,
                mu=MU_EARTH, v1_initial=departure.v, v2_target=arrival.v,
            )

    def test_a_sweep_that_loses_steps_still_counts_the_rest(self) -> None:
        """10 feasible out of 24, with the refused steps counted as neither.

        The risk the ``except (ValueError, RuntimeError)`` branch carries is
        that a refused step is quietly treated as a free one. It must not raise
        the feasible count and it must not lower the reported cost. The same
        belt with no refusals gives 11; this pair gives 10, and the difference
        is the 12 h arrival the solver would not touch.
        """
        reference = _reference_sweep(
            _RED_GEO, _BLUE_GEO_OPPOSED_AT_TWELVE_HOURS, budget_km_s=0.5,
        )
        assert reference.dropped >= 1, "this pair is meant to exercise the drop branch"
        assert len(reference.feasible) == 10
        _, cheapest_dv_km_s = reference.cheapest

        solution = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_OPPOSED_AT_TWELVE_HOURS, _EPOCH, max_delta_v_km_s=0.5,
        )

        assert solution.miss_distance_km == pytest.approx(10.0), (
            "a step the solver refused is not a feasible arrival time"
        )
        assert solution.total_delta_v == pytest.approx(cheapest_dv_km_s, rel=1e-12)
        assert solution.total_delta_v > 0.0, "a refused step must not read as a free arc"


class TestTheBudgetReachesTheSolver:
    """The test that proves the operator's field changes the answer."""

    def test_one_geometry_raises_under_a_tight_budget_and_solves_under_a_generous_one(
        self,
    ) -> None:
        """Same pair, same epoch, same sweep: only the budget moves.

        The cheapest arc for this pair costs 6.3 m/s. A 1 m/s budget cannot buy
        it and a 500 m/s budget buys it 11 times over, so if the budget were
        ignored, hardcoded or taken from a distance in kilometres, as it was in
        both of this function's previous versions, these two calls would return
        the same thing.
        """
        reference = _reference_sweep(_RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, budget_km_s=0.5)
        _, cheapest_dv_km_s = reference.cheapest
        assert 0.001 < cheapest_dv_km_s < 0.5, "the two budgets must straddle the cheapest arc"

        with pytest.raises(ValueError, match=r"0\.001 km/s budget"):
            intercept_envelope_intercept(
                _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.001,
            )

        generous = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
        )
        assert generous.total_delta_v == pytest.approx(cheapest_dv_km_s, rel=1e-12)
        assert generous.miss_distance_km == pytest.approx(11.0)


class TestAnUnreachableInterceptIsNeverFree:
    """The regression. This is the defect the engineering gate stopped on."""

    def test_an_unreachable_intercept_does_not_come_back_at_zero_delta_v(self) -> None:
        """Zero sorted ahead of every real assessment in the operator's table.

        The ranked intercept comparison table sorts ascending on cost, so the
        0.0 km/s this function used to return for an unreachable pair took the
        top row: the one geometry no interceptor could fly was presented as the
        cheapest option on the page, above every assessment that had actually
        been solved. The fix is to refuse. The batch runner catches the refusal
        per method, keeps the row, shows the message and sorts it last.
        """
        try:
            priced = intercept_envelope_intercept(
                _RED_LEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
            )
        except ValueError:
            return

        pytest.fail(
            f"an intercept costing at least 11 km/s was priced at "
            f"{priced.total_delta_v:.3f} km/s against a 0.5 km/s budget. At 0.0 it takes "
            "the top row of a table that ranks ascending on cost."
        )


class TestTheOperatorsBudgetArrivesInKilometresPerSecond:
    """``to_km_s`` is new this release and this is the unit boundary it guards."""

    def test_the_conversion_is_a_divide_by_one_thousand(self) -> None:
        """The operator types m/s; ``spectre.astro`` computes in km/s.

        1,000x is the error this boundary exists to stop, and it is silent in
        both directions: a budget 1,000 times too large makes every geometry
        feasible, and one 1,000 times too small makes every geometry raise.
        """
        assert to_km_s(500.0) == pytest.approx(0.5)
        assert to_km_s(DEFAULT_SWEEP_BUDGET_M_S) == pytest.approx(0.5)

    def test_the_sweep_default_mirrors_the_form_default(self) -> None:
        """The docstring claims the default mirrors the operator's 500 m/s.

        It replaced a hardcoded 3.0 km/s, which was six times what the form
        offered and invisible to the operator. If the two defaults drift apart
        again, an operator who leaves the field alone gets a budget they never
        chose and cannot see.
        """
        default = inspect.signature(
            intercept_envelope_intercept
        ).parameters["max_delta_v_km_s"].default

        assert default == pytest.approx(to_km_s(DEFAULT_SWEEP_BUDGET_M_S))

    def test_a_budget_typed_in_m_s_straddles_the_cheapest_arc(self) -> None:
        """End to end, in the operator's units: 5 m/s refuses, 10 m/s solves.

        The cheapest arc costs 6.3 m/s, so these two budgets sit either side of
        it by a fifth and a half. Any conversion error larger than that, and a
        missing or inverted divide is 1,000,000 times larger than that, moves
        both calls to the same side and one of these assertions fails. The
        refusal message is checked in km/s as well, because that string is how
        an operator finds out which budget the solver actually used.
        """
        reference = _reference_sweep(_RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, budget_km_s=0.5)
        _, cheapest_dv_km_s = reference.cheapest
        assert to_km_s(5.0) < cheapest_dv_km_s < to_km_s(10.0)

        with pytest.raises(ValueError, match=r"0\.005 km/s budget"):
            intercept_envelope_intercept(
                _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH,
                max_delta_v_km_s=to_km_s(5.0),
            )

        solution = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH,
            max_delta_v_km_s=to_km_s(10.0),
        )
        assert solution.total_delta_v == pytest.approx(cheapest_dv_km_s, rel=1e-12)


class TestTheTwoMutantsThatSurvivedTheFirstPass:
    """Two single-token changes the first round of tests did not notice.

    The engineering gate found both. Neither is an equivalent mutant: each
    changes an answer an operator reads, just not at the one window and the
    one budget every other test in this module happens to use.
    """

    def test_the_sweep_grid_covers_the_window_the_form_actually_offers(self) -> None:
        """``(index + 1)``, not ``index``, and the difference needs the right window.

        ``tof = tof_max_s * (index + 1) / n_steps`` steps from one slice to the
        full window. Dropping the ``+ 1`` starts at zero, which is not a time
        of flight, and shifts every subsequent step down one slice.

        At the 48 h window used elsewhere in this module both forms report 11
        feasible arrivals and the same cheapest cost, so the mutant survives.
        At 21600 s, which is the ``intercept_hours = 6.0`` default the
        operator's form actually posts, the real sweep reports 21 feasible and
        0.072568 km/s while the mutant reports 20 and 0.076125. The window an
        operator gets by default was the one window nothing swept.
        """
        solution = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH,
            tof_s=21600.0, max_delta_v_km_s=0.5,
        )
        assert solution.miss_distance_km == pytest.approx(21.0), (
            "the six-hour sweep lost a step, so the grid no longer starts at "
            "one slice in"
        )
        assert solution.total_delta_v == pytest.approx(0.072568, abs=1e-6)

    def test_the_budget_is_inclusive_of_an_arc_that_costs_exactly_it(self) -> None:
        """``dv <= budget``, not ``dv < budget``.

        No other test sits on the boundary, so ``<=`` to ``<`` survived. The
        distinction is not academic: an operator who reads a cost off the
        table and types that exact figure back into the budget field is asking
        whether this arc is affordable, and the honest answer is yes.
        """
        reachable = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
        )
        exactly = reachable.total_delta_v

        at_the_boundary = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=exactly,
        )
        assert at_the_boundary.miss_distance_km == pytest.approx(1.0), (
            "an arc costing exactly the budget was refused, so the budget is "
            "exclusive and the cheapest solution is unreachable by its own price"
        )
        assert at_the_boundary.total_delta_v == pytest.approx(exactly)

    def test_a_budget_a_hair_under_the_cheapest_arc_refuses(self) -> None:
        """The other side of the same boundary, so the test above is not one-sided."""
        reachable = intercept_envelope_intercept(
            _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH, max_delta_v_km_s=0.5,
        )
        with pytest.raises(ValueError, match="No intercept within"):
            intercept_envelope_intercept(
                _RED_GEO, _BLUE_GEO_ONE_DEGREE_AHEAD, _EPOCH,
                max_delta_v_km_s=reachable.total_delta_v * 0.999999,
            )
