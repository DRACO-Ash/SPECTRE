#!/usr/bin/env python3
"""Measure game trees under load, and the tree cost cap the measurements give (SPC-188, design D6).

The owner ruled on 2026-11-05 to raise the evaluation budget to 300 s (SPC-178) and then to measure trees under load
and set their own cap. Until 0.38.0 a tree shared the matrix's cap, 12,000 sample-hours, set from the slowest
sampling rate measured on a matrix. A tree's cost is counted by the same model (decision_tree.tree_cost), but a tree
does different work per sample-hour counted, so its own rate is measured here.

Method. Each case is a tree the engine builds in full: Hold course and an Evasive row of N samples burning 0.1 of a
turn in, against Hold and a response, on the reference element sets (tests/unit/_decision_reference.py). Each is run
by evaluate_tree under a RunControl holding the 300 s budget, as the console runs it, while LOAD other processes
keep every core busy, so the tree runs on a loaded machine. The script reports each tree's cost by the model, its
wall time, its rate (sample-hours a second) and the share of its cost that is turn 1, the matrix. The cap the code
holds is the budget times an assumed rate about a fifth under the slowest measured, so a tree at the cap finishes
inside the budget on a machine slower or busier than this one by that much; the script prints what the code holds
beside what the measurements give, and how long a tree at the cap would take at the slowest rate. --at-cap runs one
tree just under the cap instead, to check that a tree that size finishes inside the budget under load.

The figures it prints come from the machine it runs on. Those in the code were measured in the build container (4
cores, Intel Xeon at 2.10 GHz, Python 3.13), not on a deployment target: run it there and set the cap from its
figures before relying on the cap in use.

    PYTHONPATH=. python scripts/measure_tree_cost.py            # every case, every core loaded; about 4 minutes
    PYTHONPATH=. python scripts/measure_tree_cost.py --quick    # two cases; about 2 minutes
    PYTHONPATH=. python scripts/measure_tree_cost.py --load 0   # idle, for comparison
    PYTHONPATH=. python scripts/measure_tree_cost.py --at-cap   # one tree just under the cap; about 4 minutes

It writes nothing. Exit codes: 0 every tree was built in full within the budget; 1 one was not, so its rate is no
measurement and the cap must not be set from this run.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spectre.domain.decision import (  # noqa: E402 - after the repository root is on the path
    EVALUATION_BUDGET_S,
    RunControl,
    Scenario,
    _turn_one_cost_h,
    with_remainder,
)
from spectre.domain.decision_tree import (  # noqa: E402
    _SLOWEST_TREE_SAMPLE_HOURS_PER_S,
    MAX_TREE_SAMPLE_HOURS,
    evaluate_tree,
    tree_cost,
)
from tests.unit import _decision_tree_cases as cases  # noqa: E402
from tests.unit._decision_reference import COPLANAR_LEO, PLANE_CHANGE, ReferenceCase  # noqa: E402

BUILT, NOT_BUILT = 0, 1
#: The share of the slowest rate measured the cap assumes: about a fifth under it, as the matrix's cap assumes.
MARGIN = 0.8


@dataclass(frozen=True)
class Case:
    """A tree to time: the reference case, the Evasive row's samples, the turns, each turn's length and whether our
    response burns to a 20 km target."""

    case:    ReferenceCase
    samples: int
    turns:   int
    turn_h:  float
    burns:   bool

    @property
    def label(self) -> str:
        burn = "Avoid at 20 km" if self.burns else "Avoid, no burn"
        return f"{self.case.name}, {self.samples} samples, {self.turns} x {self.turn_h:g} h, {burn}"

    def scenario(self) -> Scenario:
        rows = [cases.still(), cases.evasive(self.case, n=self.samples, offset_h=0.1 * self.turn_h)]
        responses = [cases.hold(), cases.avoid(20.0 if self.burns else None, hours=0.1 * self.turn_h)]
        return cases.scenario(
            rows, responses, turns=self.turns, horizon_h=self.turns * self.turn_h, bind=self.case,
        )


#: Every case is built in full in the build container, idle in 22 to 56 s. Smaller trees of coplanar_leo do not
#: converge since SPC-202 drew element-set error into every sample, so its smallest here is 200 samples.
CASES: tuple[Case, ...] = (
    Case(PLANE_CHANGE, 300, 2, 1.0, burns=False),
    Case(COPLANAR_LEO, 200, 2, 2.0, burns=True),
    Case(PLANE_CHANGE, 500, 2, 1.0, burns=False),
    Case(PLANE_CHANGE, 300, 3, 0.5, burns=False),
)
QUICK: tuple[Case, ...] = CASES[:2]
#: A tree just under the cap the code holds, about 19,951 sample-hours, refused under the matrix's cap a tree shared
#: until 0.38.0: run with --at-cap to check that a tree that size finishes inside the budget under load.
AT_CAP: tuple[Case, ...] = (Case(PLANE_CHANGE, 800, 3, 0.5, burns=False),)


@dataclass(frozen=True)
class Timed:
    """One tree as run: its cost by the model, sample-hours; turn 1's share of it; its wall time, s; and whether it
    was built in full within the budget."""

    case:     Case
    cost_h:   float
    turn_one: float
    wall_s:   float
    built:    bool

    @property
    def rate(self) -> float:
        """Sample-hours a second of wall time."""
        return self.cost_h / self.wall_s


def _busy(stop: Any) -> None:
    """Keep one core busy until *stop* is set."""
    total = 0
    while not stop.is_set():
        total = sum(i * i for i in range(20_000)) - total


def time_tree(case: Case) -> Timed:
    """Run *case*'s tree as the console runs it, under the 300 s budget, and time it."""
    scenario = case.scenario()
    cost = tree_cost(scenario)
    one = _turn_one_cost_h(with_remainder(scenario))
    run = RunControl(budget_s=EVALUATION_BUDGET_S, stop=lambda: None)
    start = time.monotonic()
    result = evaluate_tree(scenario, run=run)
    wall = time.monotonic() - start
    tree = result.tree
    built = tree is not None and tree.complete_turns == case.turns and not result.budget_ran_out
    return Timed(case, cost, one / cost, wall, built)


def measure(chosen: Sequence[Case], load: int) -> list[Timed]:
    """Time each of *chosen* while *load* other processes keep cores busy, printing each row as it is timed."""
    stop = multiprocessing.Event()
    burners = [multiprocessing.Process(target=_busy, args=(stop,), daemon=True) for _ in range(load)]
    for burner in burners:
        burner.start()
    try:
        timed = []
        for case in chosen:
            timed.append(time_tree(case))
            row = timed[-1]
            print(f"| {case.label} | {row.cost_h:,.0f} | {row.turn_one:.0%} | {row.wall_s:.1f} | {row.rate:.1f} | "
                  f"{'yes' if row.built else 'no'} |", flush=True)
        return timed
    finally:
        stop.set()
        for burner in burners:
            burner.join(timeout=5)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--load", type=int, default=os.cpu_count() or 1,
                        help="processes keeping cores busy while each tree runs (default: one per core)")
    parser.add_argument("--quick", action="store_true", help="time the two smallest cases only")
    parser.add_argument("--at-cap", action="store_true", help="time one tree just under the cap instead")
    args = parser.parse_args(argv)
    chosen = AT_CAP if args.at_cap else QUICK if args.quick else CASES
    print(f"Trees under the {EVALUATION_BUDGET_S:.0f} s budget, {args.load} busy processes, "
          f"{os.cpu_count()} cores, Python {sys.version.split()[0]}.")
    print("| Tree | Cost, sample-hours | Turn 1's share | Wall, s | Rate, sample-hours a second | Built in full |")
    print("|---|---|---|---|---|---|")
    timed = measure(chosen, max(args.load, 0))
    slowest = min(timed, key=lambda t: t.rate)
    print(f"Slowest rate measured: {slowest.rate:.1f} sample-hours a second ({slowest.case.label}).")
    print(f"That rate less a fifth is {slowest.rate * MARGIN:.1f}; the code assumes "
          f"{_SLOWEST_TREE_SAMPLE_HOURS_PER_S:g}, a cap of {MAX_TREE_SAMPLE_HOURS:,.0f} sample-hours, which takes "
          f"{MAX_TREE_SAMPLE_HOURS / slowest.rate:.0f} s at the slowest rate here.")
    if not all(t.built for t in timed):
        print("A tree was not built in full within the budget, so this run sets no cap.")
        return NOT_BUILT
    return BUILT


if __name__ == "__main__":
    sys.exit(main())
