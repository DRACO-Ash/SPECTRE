"""A temporal cluster is bounded by its span from its first member.

Audit F-085. Clusters chained off their last member, so a run of element
sets each under the spacing apart grew into one unbounded cluster, and one
representative was chosen from a span that could contain a burn. The same
chaining defect was already fixed in the pattern-of-life merge.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from spectre.astro.tle_filter import cluster_tles, filter_tle_history
from tests.unit.test_pol_status_ladder import _make_record

_SPACING = timedelta(minutes=15)


def _run() -> list:
    base = _make_record()
    # Twelve sets ten minutes apart, with a 5 km semi-major axis step at set 6.
    return [
        dataclasses.replace(
            base, epoch=base.epoch + timedelta(minutes=10 * k), sma_km=base.sma_km + (5.0 if k >= 6 else 0.0),
            element_set_no=k,
        )
        for k in range(12)
    ]


def test_no_cluster_spans_more_than_the_spacing() -> None:
    for cluster in cluster_tles(_run(), min_spacing=_SPACING):
        assert cluster.tles[-1].epoch - cluster.tles[0].epoch < _SPACING


def test_both_sides_of_the_step_survive_filtering() -> None:
    reps, _ = filter_tle_history(_run())
    assert len(reps) > 1
    assert {r.sma_km for r in reps} == {_make_record().sma_km, _make_record().sma_km + 5.0}
