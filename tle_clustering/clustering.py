"""DBSCAN-based TLE clustering.

Clusters a list of :class:`~tle_clustering.models.TLERecord` objects for a
single NORAD ID by normalising their mean Keplerian elements according to
per-element tolerances and then running DBSCAN with the Chebyshev (L-∞) metric.

The normalisation step maps each tolerance value to 1.0 in the scaled space, so
that ``eps=1.0`` in DBSCAN corresponds exactly to "every element must be within
its own tolerance".  The L-∞ norm enforces this independently per axis: a pair
of TLEs is neighbours only if *all* elements simultaneously satisfy their
respective tolerance, not just the Euclidean average.

Usage::

    from tle_clustering.config import ClusteringConfig
    from tle_clustering.clustering import cluster_records

    result = cluster_records(norad_id=25544, records=records, config=ClusteringConfig())
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from sklearn.cluster import DBSCAN

from tle_clustering.config import ClusteringConfig
from tle_clustering.models import (
    Cluster,
    ClusteringResult,
    NoiseTLE,
    TLERecord,
)
from tle_clustering.selection import select_representative

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _build_feature_matrix(
    records: list[TLERecord],
    config: ClusteringConfig,
) -> NDArray[np.float64]:
    """Build the normalised feature matrix for DBSCAN.

    Each row is ``[inclination / inc_tol, raan / raan_tol, ecc / ecc_tol]``,
    making the feature space dimensionless and each tolerance equal to 1.0.

    Parameters
    ----------
    records:
        TLE records to featurise; must be non-empty.
    config:
        Clustering configuration supplying per-element tolerances.

    Returns
    -------
    NDArray[np.float64]
        Array of shape ``(n, 3)`` where ``n == len(records)``.
    """
    raw = np.array(
        [[r.inclination_deg, r.raan_deg, r.eccentricity] for r in records],
        dtype=np.float64,
    )
    tolerances = np.array(
        [
            config.inclination_tolerance_deg,
            config.raan_tolerance_deg,
            config.eccentricity_tolerance,
        ],
        dtype=np.float64,
    )
    return raw / tolerances


def cluster_records(
    norad_id: int,
    records: list[TLERecord],
    config: ClusteringConfig | None = None,
) -> ClusteringResult:
    """Cluster TLE records for a single NORAD ID and select representatives.

    Parameters
    ----------
    norad_id:
        NORAD catalogue number these records belong to.  Used only for
        labelling the result; the caller is responsible for supplying only
        records matching this ID.
    records:
        TLE records for one object.  Must not be empty.
    config:
        Clustering configuration.  Defaults to ``ClusteringConfig()`` if
        ``None``.

    Returns
    -------
    ClusteringResult
        Structured result containing clusters, noise TLEs, and summary
        statistics.

    Raises
    ------
    ValueError
        If ``records`` is empty.
    """
    if not records:
        raise ValueError(f"cluster_records: no records supplied for NORAD {norad_id}")

    if config is None:
        config = ClusteringConfig()

    # --- Degenerate case: single record can never form a cluster ---------------
    if len(records) == 1:
        noise = (
            NoiseTLE(
                record=records[0],
                reason="isolated: only one TLE supplied (min_samples=2 requires at least 2)",
            ),
        )
        result = ClusteringResult(norad_id=norad_id, clusters=(), noise=noise)
        logger.info(
            "cluster_records: norad=%d tles_in=1 clusters=0 representatives=0 noise=1",
            norad_id,
        )
        return result

    # --- Build normalised feature matrix and run DBSCAN -----------------------
    X = _build_feature_matrix(records, config)

    db = DBSCAN(
        eps=config.dbscan_eps,
        min_samples=config.dbscan_min_samples,
        metric=config.dbscan_metric,
    )
    labels: NDArray[np.intp] = db.fit_predict(X)

    # --- Partition records into clusters and noise ----------------------------
    unique_labels = sorted(set(int(lbl) for lbl in labels))

    clusters: list[Cluster] = []
    noise_list: list[NoiseTLE] = []

    for label in unique_labels:
        indices = [i for i, lbl in enumerate(labels) if int(lbl) == label]
        members = [records[i] for i in indices]

        if label == -1:
            for rec in members:
                noise_list.append(
                    NoiseTLE(
                        record=rec,
                        reason="isolated: no neighbours within tolerance",
                    )
                )
            logger.debug(
                "cluster_records: norad=%d noise_count=%d",
                norad_id,
                len(members),
            )
            continue

        # Centroid in original (non-normalised) element space
        centroid_inc  = float(np.mean([m.inclination_deg for m in members]))
        centroid_raan = float(np.mean([m.raan_deg for m in members]))
        centroid_ecc  = float(np.mean([m.eccentricity for m in members]))

        representative = select_representative(
            members=members,
            centroid_inc_deg=centroid_inc,
            centroid_raan_deg=centroid_raan,
            centroid_ecc=centroid_ecc,
            config=config,
        )

        cluster = Cluster(
            cluster_id=label,
            representative=representative,
            members=tuple(members),
            centroid_inclination_deg=centroid_inc,
            centroid_raan_deg=centroid_raan,
            centroid_eccentricity=centroid_ecc,
        )
        clusters.append(cluster)

        logger.debug(
            "cluster_records: norad=%d cluster_id=%d size=%d "
            "centroid=(inc=%.4f raan=%.4f ecc=%.6f) rep_epoch=%s",
            norad_id,
            label,
            cluster.size,
            centroid_inc,
            centroid_raan,
            centroid_ecc,
            representative.epoch.isoformat(),
        )

    result = ClusteringResult(
        norad_id=norad_id,
        clusters=tuple(clusters),
        noise=tuple(noise_list),
    )

    logger.info(
        "cluster_records: norad=%d tles_in=%d clusters=%d "
        "representatives=%d noise=%d",
        norad_id,
        result.total_tles_in,
        result.cluster_count,
        result.representative_count,
        result.noise_count,
    )

    return result


def cluster_all(
    groups: dict[int, list[TLERecord]],
    config: ClusteringConfig | None = None,
) -> dict[int, ClusteringResult]:
    """Cluster TLE records for multiple NORAD IDs in one call.

    Parameters
    ----------
    groups:
        Mapping of NORAD ID → list of TLE records, as returned by
        :func:`~tle_clustering.parser.group_by_norad`.
    config:
        Clustering configuration applied uniformly to all objects.
        Defaults to ``ClusteringConfig()`` if ``None``.

    Returns
    -------
    dict[int, ClusteringResult]
        One :class:`~tle_clustering.models.ClusteringResult` per NORAD ID.
    """
    if config is None:
        config = ClusteringConfig()

    return {
        norad_id: cluster_records(norad_id, records, config)
        for norad_id, records in groups.items()
    }
