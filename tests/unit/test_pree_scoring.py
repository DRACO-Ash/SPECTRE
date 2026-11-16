"""The vendored Pree scoring core. The central property is that an unknown is never invented.

Ported verbatim from Pree's own ``tests/test_scoring.py`` alongside the module, so the two copies
are held to the same behaviour and a drift between them shows up as a failing test rather than as
a quiet difference in what an operator is told. The only edit on the way in is the import path.

The last two tests are NOT from Pree. They hold the two claims this vendoring adds: that the
module is pure enough to have been lifted at all, and that its provenance is recorded.
"""

from __future__ import annotations

import pytest

from spectre.domain.pree_scoring import (
    UNKNOWN_MARKER,
    WEIGHTS,
    ConfidenceTier,
    ThreatIndicators,
    assess,
    confidence_for,
)

FULL_EVIDENCE = ThreatIndicators(
    closest_approach_km=5.0,
    relative_velocity_kms=0.1,
    manoeuvres_in_window=6,
    baseline_manoeuvres=1.0,
    photometric_sigma=2.5,
    rf_emissions_detected=True,
)


def test_weights_sum_to_one_so_full_evidence_is_a_complete_blend() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_no_evidence_scores_zero_at_insufficient_confidence() -> None:
    result = assess(ThreatIndicators())
    assert result.score == 0.0
    assert result.confidence is ConfidenceTier.INSUFFICIENT
    assert result.evidence_coverage == 0.0
    assert len(result.missing_indicators) == len(WEIGHTS)


def test_every_absent_indicator_is_marked_unknown_not_defaulted() -> None:
    result = assess(ThreatIndicators(closest_approach_km=10.0))
    absent = [c for c in result.contributions if not c.present]
    assert absent, "expected absent indicators for a partial input"
    assert all(c.rationale == UNKNOWN_MARKER for c in absent)
    assert all(c.normalised is None for c in absent)


def test_a_close_slow_manoeuvring_object_scores_high_at_high_confidence() -> None:
    result = assess(FULL_EVIDENCE)
    assert result.score > 80.0
    assert result.confidence is ConfidenceTier.HIGH
    assert result.evidence_coverage == pytest.approx(1.0)
    assert result.missing_indicators == []


def test_a_distant_fast_quiet_object_scores_low_at_high_confidence() -> None:
    result = assess(
        ThreatIndicators(
            closest_approach_km=480.0,
            relative_velocity_kms=7.5,
            manoeuvres_in_window=0,
            baseline_manoeuvres=0.0,
            photometric_sigma=0.0,
            rf_emissions_detected=False,
        )
    )
    assert result.score < 10.0
    assert result.confidence is ConfidenceTier.HIGH


def test_partial_evidence_stays_on_the_same_scale_rather_than_collapsing() -> None:
    """A single strong indicator must not be diluted towards zero by the absent ones."""
    result = assess(ThreatIndicators(closest_approach_km=1.0))
    assert result.score == pytest.approx(100.0)
    # One indicator of five is 0.30 evidence coverage, which is the documented LOW floor.
    # The score is undiluted; the tier is what carries the warning that most evidence is absent.
    assert result.confidence is ConfidenceTier.LOW
    assert result.evidence_coverage == pytest.approx(0.30)


def test_confidence_falls_as_evidence_coverage_falls() -> None:
    full = assess(FULL_EVIDENCE)
    partial = assess(
        ThreatIndicators(
            closest_approach_km=5.0,
            relative_velocity_kms=0.1,
            manoeuvres_in_window=6,
            baseline_manoeuvres=1.0,
        )
    )
    sparse = assess(ThreatIndicators(closest_approach_km=5.0))
    assert full.evidence_coverage > partial.evidence_coverage > sparse.evidence_coverage
    assert full.confidence is ConfidenceTier.HIGH
    assert partial.confidence is ConfidenceTier.MODERATE
    assert sparse.confidence is ConfidenceTier.LOW


def test_cadence_needs_both_the_count_and_the_baseline() -> None:
    """A count with no baseline cannot be judged deviant, so it is reported absent."""
    result = assess(ThreatIndicators(manoeuvres_in_window=9))
    cadence = next(c for c in result.contributions if c.indicator == "manoeuvre_cadence")
    assert cadence.present is False
    assert cadence.rationale == UNKNOWN_MARKER


def test_readings_beyond_the_documented_bounds_are_clamped_not_extrapolated() -> None:
    nearer_than_floor = assess(ThreatIndicators(closest_approach_km=0.0))
    beyond_ceiling = assess(ThreatIndicators(closest_approach_km=100_000.0))
    assert nearer_than_floor.score == pytest.approx(100.0)
    assert beyond_ceiling.score == pytest.approx(0.0)


def test_negative_photometric_sigma_is_as_anomalous_as_positive() -> None:
    dimmer = assess(ThreatIndicators(photometric_sigma=-2.0))
    brighter = assess(ThreatIndicators(photometric_sigma=2.0))
    assert dimmer.score == brighter.score


def test_an_observed_false_differs_from_an_absent_reading() -> None:
    observed_false = assess(ThreatIndicators(rf_emissions_detected=False))
    absent = assess(ThreatIndicators())
    assert observed_false.evidence_coverage > absent.evidence_coverage
    assert observed_false.confidence is not ConfidenceTier.HIGH


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        (1.0, ConfidenceTier.HIGH),
        (0.85, ConfidenceTier.HIGH),
        (0.84, ConfidenceTier.MODERATE),
        (0.60, ConfidenceTier.MODERATE),
        (0.59, ConfidenceTier.LOW),
        (0.30, ConfidenceTier.LOW),
        (0.29, ConfidenceTier.INSUFFICIENT),
        (0.0, ConfidenceTier.INSUFFICIENT),
    ],
)
def test_confidence_tier_boundaries(coverage: float, expected: ConfidenceTier) -> None:
    assert confidence_for(coverage) is expected


def test_every_contribution_carries_a_rationale_so_the_score_is_explainable() -> None:
    result = assess(FULL_EVIDENCE)
    assert len(result.contributions) == len(WEIGHTS)
    assert all(c.rationale for c in result.contributions)


# ── The two claims vendoring itself makes ────────────────────────────────────────────────────


def test_the_vendored_module_is_pure_so_lifting_it_was_legitimate() -> None:
    """The whole case for copying this in rather than calling it over HTTP is that it is pure.

    If someone later adds an import of ``requests``, ``sqlalchemy``, a SPECTRE service, or the
    filesystem, that case quietly stops holding and this module becomes something that should
    have stayed behind an interface. An AST sweep of the real file, not a reading of it.
    """
    import ast
    import sys
    from pathlib import Path

    module_path = Path(__file__).resolve().parents[2] / "spectre" / "domain" / "pree_scoring.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    assert imported, "the sweep found no imports at all, so it would pass against any file"
    outside_stdlib = sorted(name for name in imported if name not in sys.stdlib_module_names)
    assert outside_stdlib == [], (
        f"the vendored core now imports {outside_stdlib}, which is outside the standard library. "
        f"It was copied in rather than called over HTTP precisely because it was pure; if it is "
        f"not pure any more, re-examine that decision rather than widening this test"
    )


def test_the_vendored_module_records_where_it_came_from() -> None:
    """Vendored code with no recorded origin is code nobody can re-sync or diff.

    Pins the commit reference specifically, not merely the word "Pree": a provenance note that
    says only which project it came from cannot tell you which VERSION you are holding, which is
    the one thing you need when deciding whether the copies have drifted.
    """
    import re

    from spectre.domain import pree_scoring

    doc = pree_scoring.__doc__ or ""
    assert "Provenance" in doc, "the module no longer states where it came from"
    assert re.search(r"commit ``[0-9a-f]{7,40}``", doc), (
        "the provenance note no longer carries a commit reference, so a reader cannot tell which "
        "version of Pree this copy corresponds to"
    )


def test_the_velocity_rationale_is_converted_not_merely_relabelled() -> None:
    """The one operator-visible edit made while vendoring, pinned against its own failure mode.

    ``tests/unit/test_operator_sees_metres_per_second.py`` forbids a km/s figure reaching an
    operator outside ``spectre.astro``. It exists because a 42-file conversion missed four sites,
    and one of those four was a label changed from km/s to m/s with the value left alone - which
    the string-based guard could not catch, because relabelling REMOVES the very string it greps
    for. Passing that guard is therefore not evidence of a correct conversion.

    This is the evidence: the number in the sentence must be the input scaled by 1000, for a value
    whose two readings cannot be confused. 0.25 km/s is 250 m/s; a missed conversion would print
    "0 m/s" at this format precision, and a double conversion 250000.
    """
    result = assess(ThreatIndicators(relative_velocity_kms=0.25))
    velocity = next(c for c in result.contributions if c.indicator == "relative_velocity")

    assert "km/s" not in velocity.rationale, "a km/s figure is reaching the operator again"
    assert "250 m/s" in velocity.rationale, (
        f"expected the input scaled by 1000, got {velocity.rationale!r}; a label changed without "
        f"its value is the exact failure the house guard was built for and cannot itself detect"
    )
    assert "2000 m/s" in velocity.rationale, (
        f"the controllable-approach bound is also operator-facing and must be converted, got "
        f"{velocity.rationale!r}"
    )


def test_vendoring_changed_the_wording_but_not_a_single_score() -> None:
    """The unit edit is presentational. If it moved a score, it was not presentational.

    Recomputes the blend independently from WEIGHTS and the normalised values rather than
    comparing against a figure copied from Pree, because a copied expected value would be
    satisfied by editing the copy.
    """
    indicators = ThreatIndicators(
        closest_approach_km=12.4,
        relative_velocity_kms=0.08,
        manoeuvres_in_window=9,
        baseline_manoeuvres=1.5,
        photometric_sigma=3.1,
        rf_emissions_detected=True,
    )
    result = assess(indicators)
    present = [c for c in result.contributions if c.normalised is not None]
    available = sum(c.weight for c in present)
    expected = round(sum(c.weight * (c.normalised or 0.0) for c in present) / available * 100.0, 1)
    assert result.score == expected
