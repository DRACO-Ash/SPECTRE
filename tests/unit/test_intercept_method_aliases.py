"""Every intercept method runs its own solver, or is a declared alias.

Audit F-174. The engine offered 25 methods over 23 solvers: RENDEZVOUS ran
the Hohmann solver and PROXIMITY the same Lambert transfer as LAMBERT, while
the docs described them as distinct ("match position and velocity",
"minimise range to target_distance_m"). README counted 23 methods but listed
those two and left out the V-bar and H-bar hops.
"""

from __future__ import annotations

from spectre.domain.models import InterceptMethod
from spectre.web.routes import maneuver
from tests.unit.test_deployment_contract import _repo_only


def _solver(method: InterceptMethod) -> object:
    return maneuver._COAST_ONLY_SOLVERS.get(method) or maneuver._SHAPED_SOLVERS.get(method)


def test_aliases_are_declared_and_have_no_solver_of_their_own() -> None:
    assert maneuver._METHOD_ALIASES == {
        InterceptMethod.RENDEZVOUS: InterceptMethod.HOHMANN,
        InterceptMethod.PROXIMITY: InterceptMethod.LAMBERT,
    }
    for alias in maneuver._METHOD_ALIASES:
        assert _solver(alias) is None, f"{alias} has its own table entry"


def test_every_other_method_has_a_distinct_solver() -> None:
    real = [m for m in InterceptMethod if m not in maneuver._METHOD_ALIASES]
    solvers = [_solver(m) for m in real]
    assert all(s is not None for s in solvers)
    assert len({id(s) for s in solvers}) == len(real) == 23


def test_the_batch_runs_each_solver_once() -> None:
    assert set(maneuver._ALL_METHODS_SEQUENCE) == {m for m in InterceptMethod if m not in maneuver._METHOD_ALIASES}


def test_an_alias_result_says_what_it_ran(monkeypatch: object) -> None:
    from datetime import UTC, datetime

    from spectre.astro.maneuvers import InterceptSolution

    sol = InterceptSolution(
        method="hohmann", burns=[], total_delta_v=0.0,
        departure_epoch=datetime(2026, 1, 1, tzinfo=UTC), arrival_epoch=datetime(2026, 1, 1, 6, tzinfo=UTC),
        miss_distance_km=0.0,
    )
    result = maneuver._solution_to_result(sol, "RED", "BLUE", InterceptMethod.RENDEZVOUS)
    assert "Hohmann" in result.notes and "alias" in result.notes


def test_the_docs_list_the_real_methods() -> None:
    readme = _repo_only("README.md").read_text(encoding="utf-8")
    engine = _repo_only("docs/intercept_engine.md").read_text(encoding="utf-8")
    for text in (readme, engine):
        assert "V-bar" in text and "H-bar" in text
        assert "alias" in text.lower()
