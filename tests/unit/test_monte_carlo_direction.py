"""Monte Carlo hypotheses take their delta-V direction from the detection.

Audit F-030. Every hypothesis built from a detection put the whole delta-V
in-track, even for a plane change whose element breakdown had already split
it into along-track, radial and cross-track channels, so a 13 m/s plane
change was simulated as a 13 m/s orbit raise and nothing on the panel said
the direction was assumed.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from spectre.astro.monte_carlo import hypothesis_from_tle_record
from tests.unit.test_pol_status_ladder import _make_record


def _component(channel: str, dv: float, **inputs: float) -> SimpleNamespace:
    return SimpleNamespace(channel=channel, dv_km_s=dv, inputs=inputs)


def _manoeuvre(breakdown: object | None) -> SimpleNamespace:
    rec = _make_record()
    return SimpleNamespace(
        tle_before=rec, epoch=rec.epoch + timedelta(days=1), burn_epoch=rec.epoch + timedelta(hours=6),
        delta_v_km_s=0.013, manoeuvre_type="plane_change", breakdown=breakdown,
    )


def test_a_cross_track_breakdown_gives_a_cross_track_hypothesis() -> None:
    bd = SimpleNamespace(components=(
        _component("along_track", 0.0, delta_a_km=0.0),
        _component("radial", 0.0),
        _component("cross_track", 0.013),
    ))
    mnv = _manoeuvre(bd)
    h = hypothesis_from_tle_record(mnv.tle_before, mnv, n_samples=10)
    assert h.delta_v_cross_track == pytest.approx(0.013)
    assert h.delta_v_in_track == pytest.approx(0.0)
    assert "breakdown" in h.direction_basis


def test_a_lowering_burn_is_retrograde() -> None:
    bd = SimpleNamespace(components=(
        _component("along_track", 0.004, delta_a_km=-7.0),
        _component("radial", 0.003),
        _component("cross_track", 0.0),
    ))
    mnv = _manoeuvre(bd)
    h = hypothesis_from_tle_record(mnv.tle_before, mnv, n_samples=10)
    assert h.delta_v_in_track == pytest.approx(-0.013 * 0.8)
    assert h.delta_v_radial == pytest.approx(0.013 * 0.6)


def test_without_a_breakdown_the_direction_is_assumed_and_says_so() -> None:
    mnv = _manoeuvre(None)
    h = hypothesis_from_tle_record(mnv.tle_before, mnv, n_samples=10)
    assert h.delta_v_in_track == pytest.approx(0.013)
    assert "assumed" in h.direction_basis


def test_the_pre_burn_state_is_taken_at_the_burn() -> None:
    mnv = _manoeuvre(None)
    assert hypothesis_from_tle_record(mnv.tle_before, mnv, n_samples=10).epoch_utc == mnv.burn_epoch
