"""The comparison table's two load-bearing behaviours, neither of which was held.

Both were fixed in source this release and both stayed dead to the suite. The
engineering gate reinstated each defect with a single token and all 1,487 tests
went on passing:

● ``maneuver.py`` passed the operator's budget to the envelope sweep as
  ``max_delta_v_km_s=to_km_s(a.max_dv_m_s)``. Replacing that with the old
  hardcoded ``3.0`` changed nothing any test could see, so the "Max dV" field
  could have gone back to being decorative without a single red mark.
● ``_sort_key`` sends a method whose solver failed to ``(99, 0.0)``, behind
  every assessment. Inverting it to ``(0, 0.0)`` restores the exact
  operator-facing defect this release set out to fix: an intercept nobody can
  fly taking the top row of a table that ranks ascending on cost.

``_run_all_methods``, ``_sort_key``, ``_items_from_solutions`` and the route
tail were all zero-hit. The only existing test of this route posts two
satellites that do not exist and asserts "No TLE", so no solver ever ran.

These are integration tests on purpose. The defects live in the wiring between
the form, the solver dispatch and the ranking, which is precisely what a unit
test of any one of those three would miss.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_ROUTE = "/plan/maneuver/apply-all-intercepts"
_TEST_USER = "testadmin"

# Two objects in the same GEO belt, one degree apart. Shared with
# tests/unit/test_intercept_envelope.py, where the sweep's own arithmetic is
# pinned; here they only need to be reachable at one budget and not another.
_RED_GEO = (
    "1 90001U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90001   0.0500  95.0000 0001000   0.0000  10.0000  1.00270000    10"
)
_BLUE_GEO = (
    "1 90002U 26001A   26060.00000000  .00000000  00000-0  00000-0 0  9990\n"
    "2 90002   0.0500  95.0000 0001000   0.0000  11.0000  1.00270000    10"
)


@pytest.fixture()
def seeded_state(auth_cookie: str) -> Any:
    """A session holding one red track and one blue asset, both real GEO TLEs."""
    from spectre.domain.models import BlueAsset, RedTrack

    state = session_state(auth_cookie)
    saved_red, saved_blue = list(state.red_tracks), list(state.blue_assets)
    saved_history = list(state.intercept_history)
    state.red_tracks = [RedTrack(name="RED-GEO", tle=_RED_GEO)]
    state.blue_assets = [BlueAsset(name="BLUE-GEO", tle=_BLUE_GEO)]
    yield state
    state.red_tracks, state.blue_assets = saved_red, saved_blue
    state.intercept_history = saved_history


def _run(client: Any, auth_cookie: str, budget_m_s: float) -> str:
    """POST the batch route at *budget_m_s* and return the rendered table."""
    resp = client.post(
        _ROUTE,
        data={
            "red_sat": "RED-GEO",
            "blue_sat": "BLUE-GEO",
            "manoeuvre_start": "2026-03-01T00:00:00",
            "coast_hours": 0.0,
            "intercept_hours": 24.0,
            "max_dv_m_s": budget_m_s,
        },
        cookies={"spectre_session": auth_cookie},
        headers=csrf_headers(auth_cookie),
    )
    assert resp.status_code == 200, f"the route did not run: {resp.text[:300]}"
    assert "No TLE found" not in resp.text, (
        "the seeded assets were not found, so no solver ran and this test is vacuous"
    )
    return str(resp.text)


def _envelope_row(table: str) -> str:
    """The INTERCEPT_ENVELOPE row, as rendered."""
    rows = re.findall(r"<tr\b.*?</tr>", table, re.S)
    matching = [r for r in rows if "Intercept Envelope" in r or "INTERCEPT_ENVELOPE" in r]
    assert matching, "the envelope method is not in the comparison table at all"
    return matching[0]


class TestTheOperatorBudgetReachesTheSolver:
    """``max_dv_m_s`` on the form has to arrive as km/s at the sweep.

    The whole defect was that it did not: the sweep counted feasibility
    against a hardcoded 3.0 km/s, six times the form's 500 m/s default, a
    budget the operator neither chose nor could see.
    """

    def test_a_tight_budget_and_a_generous_one_disagree(
        self, client: Any, auth_cookie: str, seeded_state: Any
    ) -> None:
        """The same geometry, two budgets, two different answers.

        This is the assertion that kills a hardcoded budget. If the sweep
        ignores the form, both runs return the identical row, because nothing
        else about the request has changed.
        """
        tight = _envelope_row(_run(client, auth_cookie, budget_m_s=1.0))
        generous = _envelope_row(_run(client, auth_cookie, budget_m_s=500.0))
        assert tight != generous, (
            "the envelope row is identical at a 1 m/s and a 500 m/s budget, so "
            "the operator's field is not reaching the solver"
        )

    def test_the_refusal_names_the_budget_the_operator_set(
        self, client: Any, auth_cookie: str, seeded_state: Any
    ) -> None:
        """The message is the operator's only sight of the number in force.

        1 m/s is 0.001 km/s. If the sweep were still on its old hardcoded
        value the message would read 3.000, which is the defect stated out
        loud in the user interface.
        """
        row = _envelope_row(_run(client, auth_cookie, budget_m_s=1.0))
        assert "0.001 km/s" in row, (
            f"the refusal does not name the operator's budget; row was:\n{row[:600]}"
        )
        assert "3.000 km/s" not in row, "the hardcoded budget is back"

    def test_a_generous_budget_produces_a_cost_rather_than_a_refusal(
        self, client: Any, auth_cookie: str, seeded_state: Any
    ) -> None:
        """Otherwise the test above passes against a sweep that always fails."""
        row = _envelope_row(_run(client, auth_cookie, budget_m_s=500.0))
        assert "FAILED" not in row, (
            f"a 500 m/s budget could not reach a one-degree GEO neighbour:\n{row[:600]}"
        )


class TestAnUnreachableInterceptSortsLast:
    """A method that found no solution must never read as the cheapest option.

    ``_sort_key`` ranks ascending on delta-v, so a failed row carrying 0.0
    takes the top of the table. The envelope raising rather than returning
    zero is what moves it, and that only works because the failed row is
    pushed to ``(99, 0.0)``.
    """

    @staticmethod
    def _top_level_rows(table: str) -> list[tuple[str, bool]]:
        """``(method, failed)`` for each comparison row, in render order.

        The two row shapes are distinguished the way the template writes them:
        a solved row carries ``data-sort-1`` with the method value, and a
        failed row carries ``opacity:0.35``. Matching on the first cell
        instead picks up the chevron, and matching every ``<tr>`` picks up the
        detail tables nested inside each solved row.
        """
        rows: list[tuple[str, bool]] = []
        for row in re.findall(r"<tr\b[^>]*>.*?</tr>", table, re.S):
            solved = re.search(r'data-sort-1="([^"]*)"', row)
            if solved:
                rows.append((solved.group(1).upper(), False))
            elif "opacity:0.35" in row:
                cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
                label = re.sub(r"<[^>]+>", "", cells[1]).strip() if len(cells) > 1 else ""
                rows.append((label.upper(), True))
        return rows

    def test_the_failed_envelope_is_not_the_first_row(
        self, client: Any, auth_cookie: str, seeded_state: Any
    ) -> None:
        rows = self._top_level_rows(_run(client, auth_cookie, budget_m_s=1.0))
        assert len(rows) > 1, "only one row rendered, so ordering proves nothing"

        envelope_at = [i for i, (m, _) in enumerate(rows) if "ENVELOPE" in m]
        assert envelope_at, f"the envelope row is missing; rows were {rows}"
        assert envelope_at[0] != 0, (
            "an intercept nobody can fly is the top row of a table ranked "
            f"ascending on cost; order was {[m for m, _ in rows]}"
        )

    def test_every_failed_row_sits_below_every_solved_row(
        self, client: Any, auth_cookie: str, seeded_state: Any
    ) -> None:
        """The general form, which a single method moving would not catch."""
        rows = self._top_level_rows(_run(client, auth_cookie, budget_m_s=1.0))
        assert rows, "no data rows rendered"

        failed_at = [i for i, (_, failed) in enumerate(rows) if failed]
        solved_at = [i for i, (_, failed) in enumerate(rows) if not failed]
        # Asserted, not skipped. This is the single test that kills the
        # _sort_key mutant, and a change making every method succeed would
        # have retired it silently.
        assert failed_at, (
            "no method failed at a 1 m/s budget, so this test no longer "
            "exercises the ordering it exists for"
        )
        assert solved_at, "no method succeeded, so there is no ordering to check"
        assert min(failed_at) > max(solved_at), (
            f"a failed row is ranked above a solved one: failed at {failed_at}, "
            f"solved at {solved_at}"
        )
