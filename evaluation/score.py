#!/usr/bin/env python3
"""Score the decision-analysis engine from evaluation/scorecard.json (framework sections 5.2 to 5.5).

Standard library only. Reads the gate ratings and the lens levels and weights, and prints the gate result, the
overall score (sum of weight times level, over 100) to two decimal places, the score band and the verdict.

The verdict applies the framework's rules in order: any gate Red is Fail; then the score bands of section 5.4
(below 2.5 Not ready; 2.5 to 3.49 Conditional; 3.5 or above Ready for operational trial, but more than three gate
Ambers caps it at Conditional; 4.0 or above with every gate Green Ready for accreditation submission). The score band
is also printed without the gate, so a sensitivity run can show whether the weights alone move the band.

Usage:
  python evaluation/score.py                      the scorecard as written
  python evaluation/score.py --equal              every lens weight equal
  python evaluation/score.py --vary L3 1.5        one lens weight times 1.5, the others rescaled to keep 100
  python evaluation/score.py --sensitivity        equal weights, then every lens raised and lowered by 50 %
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CARD = Path(__file__).with_name("scorecard.json")
TOTAL = 100.0


def load(path: Path = CARD) -> dict:
    card = json.loads(path.read_text(encoding="utf-8"))
    weights = sum(lens["weight"] for lens in card["lenses"])
    if abs(weights - TOTAL) > 1e-9:
        raise SystemExit(f"lens weights sum to {weights}, not {TOTAL}")
    for lens in card["lenses"]:
        if lens["level"] not in (1, 2, 3, 4, 5):
            raise SystemExit(f"{lens['id']}: level {lens['level']} is not 1 to 5")
    for gate in card["gates"]:
        if gate["rating"] not in ("Green", "Amber", "Red"):
            raise SystemExit(f"{gate['id']}: rating {gate['rating']} is not Green, Amber or Red")
    return card


def score(lenses: list[dict], weights: dict[str, float] | None = None) -> float:
    w = weights or {lens["id"]: lens["weight"] for lens in lenses}
    return sum(w[lens["id"]] * lens["level"] for lens in lenses) / sum(w.values())


def band(value: float) -> str:
    if value < 2.5:
        return "Not ready"
    if value < 3.5:
        return "Conditional"
    if value < 4.0:
        return "Ready for operational trial"
    return "Ready for accreditation submission"


def verdict(value: float, gates: list[dict]) -> str:
    ratings = [g["rating"] for g in gates]
    if "Red" in ratings:
        return "Fail"
    b = band(value)
    ambers = ratings.count("Amber")
    if b == "Ready for accreditation submission" and ambers:
        b = "Ready for operational trial"
    if b == "Ready for operational trial" and ambers > 3:
        b = "Conditional"
    return b


def equal_weights(lenses: list[dict]) -> dict[str, float]:
    return {lens["id"]: TOTAL / len(lenses) for lens in lenses}


def varied(lenses: list[dict], lens_id: str, factor: float) -> dict[str, float]:
    base = {lens["id"]: float(lens["weight"]) for lens in lenses}
    new = base[lens_id] * factor
    rest = TOTAL - base[lens_id]
    return {k: (new if k == lens_id else v * (TOTAL - new) / rest) for k, v in base.items()}


def report(card: dict, weights: dict[str, float] | None, label: str) -> tuple[float, str, str]:
    value = score(card["lenses"], weights)
    return value, band(value), verdict(value, card["gates"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--card", type=Path, default=CARD)
    ap.add_argument("--equal", action="store_true")
    ap.add_argument("--vary", nargs=2, metavar=("LENS", "FACTOR"))
    ap.add_argument("--sensitivity", action="store_true")
    a = ap.parse_args()
    card = load(a.card)
    gates = card["gates"]
    reds = [g["id"] for g in gates if g["rating"] == "Red"]
    ambers = [g["id"] for g in gates if g["rating"] == "Amber"]
    greens = [g["id"] for g in gates if g["rating"] == "Green"]
    print(f"Gates: {len(reds)} Red {reds}; {len(ambers)} Amber {ambers}; {len(greens)} Green {greens}")
    print(f"Gate result: {'Fail' if reds else 'Pass'}")
    runs: list[tuple[str, dict[str, float] | None]] = []
    if a.sensitivity:
        runs.append(("as written", None))
        runs.append(("equal weights", equal_weights(card["lenses"])))
        for lens in card["lenses"]:
            for factor in (1.5, 0.5):
                runs.append((f"{lens['id']} x{factor:g}", varied(card["lenses"], lens["id"], factor)))
    elif a.equal:
        runs.append(("equal weights", equal_weights(card["lenses"])))
    elif a.vary:
        runs.append((f"{a.vary[0]} x{float(a.vary[1]):g}", varied(card["lenses"], a.vary[0], float(a.vary[1]))))
    else:
        runs.append(("as written", None))
    base_band = band(score(card["lenses"]))
    for label, weights in runs:
        value, b, v = report(card, weights, label)
        moved = "" if b == base_band else f"  <- score band moves from {base_band}"
        print(f"{label:<16} score {value:.2f}  score band {b:<34} verdict {v}{moved}")


if __name__ == "__main__":
    main()
