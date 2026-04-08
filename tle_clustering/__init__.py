"""TLE Clustering and De-duplication for SPECTRE.

Satellites on the HRR can attract ~100 TLEs per day from multiple providers.
Because each provider fits TLEs from whatever observations are available at
generation time, near-duplicate TLEs for the same object exhibit small
inter-provider variation.  This package clusters near-equivalent TLEs using
DBSCAN and selects a single representative from each cluster, reducing
redundancy before downstream intercept analysis.

Clustering approach
-------------------
Three mean Keplerian elements — inclination, RAAN, and eccentricity — are
normalised by per-element tolerances and clustered with DBSCAN using the
Chebyshev (L-∞) metric.  The L-∞ norm is chosen because it requires every
element to independently satisfy its tolerance: a pair of TLEs is considered
equivalent only if they agree on *all* three elements simultaneously, not just
on average.

The representative TLE for each cluster is the member closest to the cluster
centroid in normalised Chebyshev space; ties are broken by epoch recency.  TLEs
that DBSCAN labels as noise (no neighbours within tolerance) are retained and
flagged so that genuinely different orbit solutions or provider anomalies are
visible to the analyst.

Public API
----------
The simplest entry point for most callers is :func:`cluster_tle_strings`:

    from tle_clustering import cluster_tle_strings, ClusteringConfig

    results = cluster_tle_strings(raw_lines, config=ClusteringConfig())
    for norad_id, result in results.items():
        for cluster in result.clusters:
            downstream_pipeline(cluster.representative.tle)

For finer control, use the sub-modules directly:

    from tle_clustering.parser import parse_tle_strings, group_by_norad
    from tle_clustering.clustering import cluster_all
    from tle_clustering.config import ClusteringConfig
"""

from __future__ import annotations

from tle_clustering.clustering import cluster_all, cluster_records
from tle_clustering.config import ClusteringConfig
from tle_clustering.models import (
    Cluster,
    ClusteringResult,
    NoiseTLE,
    TLERecord,
)
from tle_clustering.parser import (
    group_by_norad,
    parse_tle_pair,
    parse_tle_strings,
)


def cluster_tle_strings(
    lines: list[str],
    config: ClusteringConfig | None = None,
) -> dict[int, ClusteringResult]:
    """Parse raw TLE strings and cluster them, returning one result per NORAD ID.

    This is the primary entry point for pipeline callers.  It combines
    :func:`~tle_clustering.parser.parse_tle_strings`,
    :func:`~tle_clustering.parser.group_by_norad`, and
    :func:`~tle_clustering.clustering.cluster_all` into a single call.

    Parameters
    ----------
    lines:
        Flat list of TLE line strings (two-line or three-line format).
        Name lines are silently skipped; malformed pairs are skipped with a
        WARNING log entry.
    config:
        Clustering configuration.  Defaults to ``ClusteringConfig()`` if
        ``None``.

    Returns
    -------
    dict[int, ClusteringResult]
        One :class:`~tle_clustering.models.ClusteringResult` per NORAD ID
        found in ``lines``.
    """
    if config is None:
        config = ClusteringConfig()

    records = parse_tle_strings(lines)
    groups = group_by_norad(records)
    return cluster_all(groups, config)


__all__ = [
    # High-level entry point
    "cluster_tle_strings",
    # Sub-module re-exports
    "cluster_all",
    "cluster_records",
    "parse_tle_strings",
    "parse_tle_pair",
    "group_by_norad",
    # Configuration
    "ClusteringConfig",
    # Data models
    "Cluster",
    "ClusteringResult",
    "NoiseTLE",
    "TLERecord",
]
