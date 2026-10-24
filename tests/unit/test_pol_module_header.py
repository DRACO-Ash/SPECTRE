"""The pattern-of-life module says what it measures, not what moved out.

Audit F-095: its header advertised a replaced ΔV method and the anomaly
score, propellant budget and intelligence assessment that now live in
spectre.domain.pol_assessment.
"""

from __future__ import annotations

import spectre.astro.pattern_of_life as pol


def test_the_header_points_judgements_to_the_domain_module() -> None:
    doc = pol.__doc__ or ""
    assert "spectre.domain.pol_assessment" in doc
    for moved in ("Scores the object", "Estimates propellant", "Produces an operator-level"):
        assert moved not in doc
