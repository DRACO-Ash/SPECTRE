"""An unrecognised solver is scored against the widest band, not RENDEZVOUS.

Audit F-119. ``kind_for_method`` promised that an unknown method falls back
to "the most permissive band" and then returned RENDEZVOUS, which is not the
widest in any regime: GEO plane change runs to 160 m/s against rendezvous
120, and LEO phasing to 200 against 150. An unmapped GEO method costing
130 m/s read AGGRESSIVE where a known plane change of the same cost reads
ANNOYANCE.
"""

from __future__ import annotations

import pytest

from spectre.domain.manoeuvre_calibration import (
    ManoeuvreKind,
    Posture,
    classify_posture,
    kind_for_method,
)

_REGIMES = ("LEO", "MEO", "GEO", "HEO", "GTO")
_RANK = {Posture.BENIGN: 0, Posture.ANNOYANCE: 1, Posture.AGGRESSIVE: 2, Posture.BEYOND_PLATFORM: 3}


def test_the_reported_case_is_no_longer_aggressive() -> None:
    p = classify_posture(130.0, "GEO", kind_for_method("some_new_solver"))
    assert p.posture is Posture.ANNOYANCE


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("dv", [5.0, 20.0, 60.0, 130.0, 180.0, 250.0, 400.0])
def test_an_unknown_method_is_never_scored_above_any_known_kind(regime: str, dv: float) -> None:
    unknown = classify_posture(dv, regime, kind_for_method("some_new_solver")).posture
    for kind in ManoeuvreKind:
        known = classify_posture(dv, regime, kind).posture
        assert _RANK[unknown] <= _RANK[known], f"{dv} m/s in {regime}: unknown {unknown} above {kind} {known}"


def test_the_basis_says_the_method_was_not_recognised() -> None:
    basis = classify_posture(130.0, "GEO", kind_for_method("some_new_solver")).basis
    assert "method" in basis.lower()
    assert "Regime not recognised" not in basis


def test_known_methods_keep_their_kinds() -> None:
    assert kind_for_method("lambert") is ManoeuvreKind.RENDEZVOUS
    assert kind_for_method(" Hohmann ") is ManoeuvreKind.ALTITUDE_CHANGE
