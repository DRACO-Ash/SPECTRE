"""TLE cadence filtering and deduplication.

Given a chronologically-sorted list of TLERecords for a single object,
this module groups consecutive TLEs whose epochs are closer than a
regime-aware minimum spacing threshold, selects the best representative
from each cluster, and flags quality issues in the resulting sequence.

Typical use::

    from spectre.astro.tle_filter import filter_tle_history
    reps, flags = filter_tle_history(records)

The filter removes duplicate-pass TLEs that would create false delta-V
signatures in Pattern of Life analysis, without averaging (which is
physically meaningless for SGP4 mean elements).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from spectre.astro.pattern_of_life import TLERecord
from spectre.config.constants import TLE_FILTER

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class QualityFlag:
    """A single structured quality warning from the cadence filter.

    Attributes
    ----------
    epoch:
        The TLE epoch the flag is anchored to (used for sorting).
    flag_type:
        One of ``"gap"``, ``"bstar"``, or ``"cluster"``.
    message:
        Human-readable description for display in the UI.
    """

    epoch: datetime
    flag_type: str
    message: str

    def __str__(self) -> str:  # Jinja2 ``{{ flag }}`` falls back to this
        return self.message


@dataclass
class TLECluster:
    """A group of TLEs whose epochs fall within the spacing threshold."""

    tles: list[TLERecord] = field(default_factory=list)

    @property
    def span_seconds(self) -> float:
        if len(self.tles) < 2:
            return 0.0
        return (
            max(t.epoch for t in self.tles) - min(t.epoch for t in self.tles)
        ).total_seconds()

    @property
    def earliest_epoch(self):
        return min(t.epoch for t in self.tles)

    @property
    def latest_epoch(self):
        return max(t.epoch for t in self.tles)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _min_spacing(regime: str) -> timedelta:
    """Return the regime-appropriate minimum epoch spacing threshold."""
    if regime in ("GEO", "DEEP"):
        return timedelta(seconds=TLE_FILTER["min_spacing_geo_s"])
    if regime == "MEO":
        return timedelta(seconds=TLE_FILTER["min_spacing_meo_s"])
    # LEO, HEO, GTO, and anything unrecognised
    return timedelta(seconds=TLE_FILTER["min_spacing_leo_s"])


# ── Public functions ──────────────────────────────────────────────────────────

def cluster_tles(
    tles: Sequence[TLERecord],
    min_spacing: timedelta | None = None,
) -> list[TLECluster]:
    """Group a TLE list into temporal clusters.

    Parameters
    ----------
    tles:
        TLERecords for a single NORAD ID.  Need not be sorted on input.
    min_spacing:
        Minimum epoch gap to start a new cluster.  If *None*, inferred
        from the regime of the first record.

    Returns
    -------
    list[TLECluster]
        Clusters in chronological order; each contains one or more TLEs.
    """
    if not tles:
        return []

    sorted_tles = sorted(tles, key=lambda t: t.epoch)

    if min_spacing is None:
        min_spacing = _min_spacing(sorted_tles[0].regime)

    clusters: list[TLECluster] = [TLECluster(tles=[sorted_tles[0]])]
    for tle in sorted_tles[1:]:
        gap = tle.epoch - clusters[-1].tles[-1].epoch
        if gap >= min_spacing:
            clusters.append(TLECluster(tles=[tle]))
        else:
            clusters[-1].tles.append(tle)

    return clusters


def select_representative(cluster: TLECluster) -> TLERecord:
    """Pick the best TLE from a cluster.

    Priority:
    1. Lowest ``rms_residual`` (if populated from UDL metadata).
    2. Most recent epoch.
    3. Highest ``element_set_no`` as a tiebreaker.
    """
    candidates = cluster.tles

    with_rms = [t for t in candidates if t.rms_residual is not None]
    if with_rms:
        return min(
            with_rms,
            key=lambda t: (t.rms_residual, -t.epoch.timestamp()),
        )

    return max(candidates, key=lambda t: (t.epoch, t.element_set_no))


def quality_flag_sequence(reps: list[TLERecord]) -> list[QualityFlag]:
    """Walk the representative sequence and generate quality-warning flags.

    Checks for:
    * Data gaps exceeding the staleness threshold for the object's regime.
    * Large fractional jumps in the B* drag coefficient (catalogue artefact).
    """
    if len(reps) < 2:
        return []

    flags: list[QualityFlag] = []
    for i in range(1, len(reps)):
        cur  = reps[i]
        prev = reps[i - 1]
        regime = cur.regime

        # Staleness / data gap
        stale_h = (
            TLE_FILTER["staleness_warn_geo_h"]
            if regime in ("GEO", "DEEP")
            else TLE_FILTER["staleness_warn_leo_h"]
        )
        gap_h = (cur.epoch - prev.epoch).total_seconds() / 3600.0
        if gap_h > stale_h:
            flags.append(QualityFlag(
                epoch=cur.epoch,
                flag_type="gap",
                message=(
                    f"Gap of {gap_h:.0f}h before {cur.epoch.strftime('%Y-%m-%d')} "
                    f"exceeds {stale_h}h staleness threshold — potential hidden manoeuvre"
                ),
            ))

        # B* discontinuity
        if abs(prev.bstar) > 1e-12:
            ratio = abs(cur.bstar - prev.bstar) / abs(prev.bstar)
            if ratio > TLE_FILTER["bstar_discontinuity_frac"]:
                flags.append(QualityFlag(
                    epoch=cur.epoch,
                    flag_type="bstar",
                    message=(
                        f"B* discontinuity near {cur.epoch.strftime('%Y-%m-%d')}: "
                        f"{prev.bstar:.2e} → {cur.bstar:.2e} "
                        f"({ratio:.0%} change) — possible catalogue maintenance"
                    ),
                ))

    return flags


def filter_tle_history(
    records: list[TLERecord],
) -> tuple[list[TLERecord], list[QualityFlag]]:
    """Apply regime-aware cadence filtering to a sorted TLE sequence.

    Groups consecutive TLEs that fall within the regime-appropriate
    minimum spacing threshold into clusters and selects one high-quality
    representative per cluster.  Flags operational anomalies in the
    resulting sequence (data gaps, B* discontinuities, large clusters).

    Parameters
    ----------
    records:
        Chronologically sorted ``TLERecord`` list (as returned by
        ``parse_tle_history``).

    Returns
    -------
    representatives : list[TLERecord]
        One TLE per cluster, in chronological order.
    quality_flags : list[QualityFlag]
        Structured quality warnings; each exposes ``epoch``, ``flag_type``,
        and ``message`` attributes for UI rendering.
    """
    if not records:
        return [], []

    # Infer regime from the middle of the sequence (most representative)
    regime = records[len(records) // 2].regime
    spacing = _min_spacing(regime)

    clusters = cluster_tles(records, min_spacing=spacing)
    reps = [select_representative(c) for c in clusters]
    reps.sort(key=lambda r: r.epoch)

    flags = quality_flag_sequence(reps)

    # Note operationally interesting large clusters
    large = TLE_FILTER["large_cluster_threshold"]
    for c in clusters:
        if len(c.tles) >= large:
            flags.append(QualityFlag(
                epoch=c.earliest_epoch,
                flag_type="cluster",
                message=(
                    f"Large cluster of {len(c.tles)} TLEs near "
                    f"{c.earliest_epoch.strftime('%Y-%m-%d')} — possible tracking campaign "
                    f"or real-time manoeuvre observation (span {c.span_seconds/60:.0f} min)"
                ),
            ))

    # Sort most-recent first
    flags.sort(key=lambda f: f.epoch, reverse=True)

    logger.debug(
        "TLE filter: %d → %d records (%d clusters, %d flags)",
        len(records), len(reps), len(clusters), len(flags),
    )
    return reps, flags
