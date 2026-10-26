"""Representative TLE selection from a cluster.

Given a set of cluster members and their centroid, selects the single TLE
whose normalised elements are closest to the centroid under the Chebyshev
(L-∞) metric — consistent with the distance measure used during clustering.

Tie-breaking rule: when two or more members share the minimum Chebyshev
distance, the one with the most recent epoch is preferred.

Usage::

    rep = select_representative(
        members=members,
        centroid_inc_deg=centroid_inc,
        centroid_raan_deg=centroid_raan,
        centroid_ecc=centroid_ecc,
        config=config,
    )
"""

from __future__ import annotations

import logging

from tle_clustering.config import ClusteringConfig
from tle_clustering.models import TLERecord

logger = logging.getLogger(__name__)


# Below this inclination, in degrees, the ascending node is not a meaningful
# direction: fits of one near-equatorial GEO orbit scatter across any RAAN,
# so a pair both under it is not compared on RAAN (audit F-171).
NODE_UNDEFINED_INC_DEG = 0.1


def raan_separation_deg(a: float, b: float) -> float:
    """Angular separation of two nodes the short way round, in degrees.

    RAAN was treated as linear, so 359.99 and 0.01 were 359.98 apart, not
    0.02 (audit F-162).
    """
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def node_compared(inc_a_deg: float, inc_b_deg: float) -> bool:
    """Whether two orbits' nodes mean anything to compare."""
    return not (inc_a_deg < NODE_UNDEFINED_INC_DEG and inc_b_deg < NODE_UNDEFINED_INC_DEG)


def _chebyshev_distance_normalised(
    record: TLERecord,
    centroid_inc_deg: float,
    centroid_raan_deg: float,
    centroid_ecc: float,
    config: ClusteringConfig,
) -> float:
    """Compute the Chebyshev distance from a TLE to a centroid in normalised space.

    Each element difference is divided by its tolerance before taking the
    maximum, so the result is in the same dimensionless units as ``dbscan_eps``.

    Parameters
    ----------
    record:
        TLE record to measure.
    centroid_inc_deg:
        Cluster centroid inclination [degrees].
    centroid_raan_deg:
        Cluster centroid RAAN [degrees].
    centroid_ecc:
        Cluster centroid eccentricity [dimensionless].
    config:
        Configuration supplying per-element tolerances.

    Returns
    -------
    float
        Chebyshev distance in normalised space (dimensionless).
    """
    d_inc  = abs(record.inclination_deg - centroid_inc_deg)  / config.inclination_tolerance_deg
    d_raan = (
        raan_separation_deg(record.raan_deg, centroid_raan_deg) / config.raan_tolerance_deg
        if node_compared(record.inclination_deg, centroid_inc_deg) else 0.0
    )
    d_ecc  = abs(record.eccentricity    - centroid_ecc)      / config.eccentricity_tolerance
    return max(d_inc, d_raan, d_ecc)


def select_representative(
    members: list[TLERecord],
    centroid_inc_deg: float,
    centroid_raan_deg: float,
    centroid_ecc: float,
    config: ClusteringConfig,
) -> TLERecord:
    """Select the cluster member closest to the centroid in normalised Chebyshev space.

    Parameters
    ----------
    members:
        Non-empty list of TLE records belonging to the same cluster.
    centroid_inc_deg:
        Mean inclination of the cluster [degrees].
    centroid_raan_deg:
        Mean RAAN of the cluster [degrees].
    centroid_ecc:
        Mean eccentricity of the cluster [dimensionless].
    config:
        Clustering configuration supplying per-element tolerances.

    Returns
    -------
    TLERecord
        The selected representative.

    Raises
    ------
    ValueError
        If ``members`` is empty.

    Notes
    -----
    Tie-breaking: among members sharing the minimum Chebyshev distance,
    the one with the most recent (latest) epoch is chosen.  This prefers
    the freshest observation when the orbit solutions are otherwise
    indistinguishable.
    """
    if not members:
        raise ValueError("select_representative: members list must not be empty")

    distances = [
        _chebyshev_distance_normalised(
            m, centroid_inc_deg, centroid_raan_deg, centroid_ecc, config
        )
        for m in members
    ]

    min_dist = min(distances)

    # Collect all members sharing the minimum distance
    candidates = [
        m for m, d in zip(members, distances, strict=True)
        if d == min_dist
    ]

    # Tie-break: most recent epoch wins
    representative = max(candidates, key=lambda m: m.epoch)

    logger.debug(
        "select_representative: selected epoch=%s dist=%.6f from %d member(s) "
        "(%d tie(s) broken by recency)",
        representative.epoch.isoformat(),
        min_dist,
        len(members),
        len(candidates),
    )

    return representative
