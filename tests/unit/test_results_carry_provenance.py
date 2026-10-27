"""Every top-level result says what produced it (audit F-121).

No domain output carried the code version, the calibration source or the
identity of its inputs, so a verdict or recommendation could not be traced
or reproduced once the session ended.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import spectre
from spectre.astro.pattern_of_life import analyse_pattern_of_life
from spectre.domain.decision import evaluate_scenario
from spectre.domain.manoeuvre_calibration import CALIBRATION_SOURCE
from spectre.domain.pol_assessment import assess_pattern_of_life
from spectre.domain.provenance import Provenance, tle_input
from spectre.domain.threat_assessment import AccessEvidence, CapabilityEvidence, assess_threat
from tests.unit import test_dv_estimation
from tests.unit.test_decision import _scenario


def _populated(p: Provenance | None) -> Provenance:
    assert p is not None
    assert p.code_version == spectre.__version__
    assert p.calibration_source == CALIBRATION_SOURCE
    assert p.inputs
    assert all(len(i.sha256) == 64 for i in p.inputs)
    assert abs(datetime.now(UTC) - p.computed_at) < timedelta(minutes=1)
    return p


def test_a_decision_result_names_its_scenario() -> None:
    scenario = _scenario()
    p = _populated(evaluate_scenario(scenario).provenance)
    assert [i.label for i in p.inputs] == ["scenario"]
    assert p.inputs == _populated(evaluate_scenario(_scenario()).provenance).inputs, "same inputs, same hash"


def test_a_threat_verdict_names_its_evidence() -> None:
    access = AccessEvidence(best_delta_v_m_s=12.0, time_to_arrival_hours=6.0, method="hohmann", regime="GEO")
    p = _populated(assess_threat(access, CapabilityEvidence(intel_threat_level="LOW")).provenance)
    assert [i.label for i in p.inputs] == ["access", "capability"]
    other = assess_threat(access, CapabilityEvidence(intel_threat_level="HIGH")).provenance
    assert other is not None
    assert other.inputs[1].sha256 != p.inputs[1].sha256


def test_a_pattern_of_life_assessment_names_every_tle_and_its_epoch() -> None:
    records = test_dv_estimation.TestTwoTierReporting._catalogue()
    pol = analyse_pattern_of_life(records, satno=1, name="T")
    p = _populated(assess_pattern_of_life(pol).provenance)
    assert len(p.inputs) == len(pol.records)
    assert [i.epoch for i in p.inputs] == [r.epoch for r in pol.records]
    first = pol.records[0]
    assert p.inputs[0].sha256 == hashlib.sha256(
        "\n".join(line.strip() for line in first.tle.strip().splitlines()).encode()
    ).hexdigest()


def test_a_tle_hash_ignores_layout_but_not_content() -> None:
    line1 = "1 25544U 98067A   26290.50000000  .00016717  00000-0  10270-3 0  9005"
    line2 = "2 25544  51.6400 208.9163 0006317  69.9862  25.2906 15.49541392 10001"
    assert tle_input("t", f"{line1}\n{line2}").sha256 == tle_input("t", f"  {line1}  \r\n{line2}\n").sha256
    assert tle_input("t", f"{line1}\n{line2}").sha256 != tle_input("t", f"{line1}\n{line2[:-1]}2").sha256
