"""DBSCAN-based TLE clustering.

Clusters a list of :class:`~tle_clustering.models.TLERecord` objects for a
single NORAD ID by measuring each pair's separation on every element in
tolerances and then running DBSCAN on those distances (Chebyshev, L-∞, by
default).

Each tolerance is 1.0 in that measure, so ``eps=1.0`` means "every element
within its own tolerance" FOR A PAIR OF NEIGHBOURS. DBSCAN links neighbours:
a chain of sets each within tolerance of the next is one cluster whose ends
can be several tolerances apart. Each cluster carries that span, and
``exceeds_tolerance`` says when it is over one (audit F-163).

Usage::

    from tle_clustering.config import ClusteringConfig
    from tle_clustering.clustering import cluster_records

    result = cluster_records(norad_id=25544, records=records, config=ClusteringConfig())
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from sgp4.api import Satrec
from sklearn.cluster import DBSCAN

from tle_clustering.config import ClusteringConfig
from tle_clustering.models import (
    Cluster,
    ClusteringResult,
    NoiseTLE,
    TLERecord,
)
from tle_clustering.selection import NODE_UNDEFINED_INC_DEG, select_representative

logger = logging.getLogger(__name__)


def _raan_at_common_epoch(records: list[TLERecord]) -> list[float]:
    """Each record's RAAN carried to the latest epoch among them, in degrees.

    Elements were compared at each TLE's own epoch. An ISS-like node regresses
    about 5 degrees a day, so two fits of one orbit taken more than about a
    quarter of an hour apart differed by more than the 0.05 degree tolerance
    and never clustered (audit F-054). Each node is moved by the secular rate
    SGP4 itself derives for that element set (``Satrec.nodedot``), so the
    correction is the one the propagator applies. The results are kept within
    half a turn of the newest record's node, so a group straddling 0/360 is
    not split by the wrap.
    """
    reference = max(r.epoch for r in records)
    newest = max(records, key=lambda r: r.epoch)
    moved = []
    for r in records:
        rate_deg_per_min = math.degrees(Satrec.twoline2rv(r.line1, r.line2).nodedot)
        minutes = (reference - r.epoch).total_seconds() / 60.0
        raan = r.raan_deg + rate_deg_per_min * minutes
        moved.append(newest.raan_deg + ((raan - newest.raan_deg + 180.0) % 360.0 - 180.0))
    return moved


def _axis_distances(
    records: list[TLERecord],
    config: ClusteringConfig,
) -> NDArray[np.float64]:
    """Pairwise separations on each element, in tolerances: shape ``(3, n, n)``.

    Axis 0 is inclination, 1 RAAN, 2 eccentricity. RAAN is compared at a
    common epoch (audit F-054), the short way round the circle (it was
    linear, so 359.99 and 0.01 degrees were 7,199.6 tolerances apart, audit
    F-162), and not at all between two orbits too near the equator for the
    node to mean anything (audit F-171).
    """
    inc = np.array([r.inclination_deg for r in records], dtype=np.float64)
    raan = np.array(_raan_at_common_epoch(records), dtype=np.float64)
    ecc = np.array([r.eccentricity for r in records], dtype=np.float64)

    d_inc = np.abs(inc[:, None] - inc[None, :]) / config.inclination_tolerance_deg
    around = np.abs(raan[:, None] - raan[None, :]) % 360.0
    d_raan = np.minimum(around, 360.0 - around) / config.raan_tolerance_deg
    no_node = (inc[:, None] < NODE_UNDEFINED_INC_DEG) & (inc[None, :] < NODE_UNDEFINED_INC_DEG)
    d_raan[no_node] = 0.0
    d_ecc = np.abs(ecc[:, None] - ecc[None, :]) / config.eccentricity_tolerance
    return np.stack([d_inc, d_raan, d_ecc])


# TLE elements are quantised (1e-4 degrees), so a pair exactly one tolerance
# apart is common, and float noise put it either side of eps. "Within
# tolerance" includes equality; this makes it so.
_INCLUSIVE = 1.0 + 1e-9

def _chebyshev(d: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(d.max(axis=0), dtype=np.float64)


def _euclidean(d: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(np.sqrt((d * d).sum(axis=0)), dtype=np.float64)


def _manhattan(d: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(d.sum(axis=0), dtype=np.float64)


# How each metric the configuration may name combines the three axes.
_COMBINE: dict[str, Callable[[NDArray[np.float64]], NDArray[np.float64]]] = {
    "chebyshev": _chebyshev,
    "euclidean": _euclidean,
    "manhattan": _manhattan,
    "cityblock": _manhattan,
}


def _distance_matrix(axes: NDArray[np.float64], metric: str) -> NDArray[np.float64]:
    """The DBSCAN distance matrix for *metric*, from the per-axis separations."""
    try:
        combine = _COMBINE[metric]
    except KeyError:
        raise ValueError(f"Unsupported dbscan_metric {metric!r}; use one of {sorted(_COMBINE)}") from None
    return combine(axes)


def _circular_mean_deg(values: list[float]) -> float:
    """Mean node of *values*, in [0, 360): a group either side of the seam centres on it.

    Each value is first taken within half a turn of the first, so away from
    the seam this is the plain arithmetic mean, to the last bit.
    """
    if max(values) - min(values) <= 180.0:  # noqa: PLR2004
        return float(np.mean(values))
    ref = values[0]
    unwrapped = [ref + ((v - ref + 180.0) % 360.0 - 180.0) for v in values]
    return float(np.mean(unwrapped)) % 360.0


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

    # --- Pairwise distances in tolerances, then DBSCAN on them ----------------
    axes = _axis_distances(records, config)
    db = DBSCAN(
        eps=config.dbscan_eps * _INCLUSIVE,
        min_samples=config.dbscan_min_samples,
        metric="precomputed",
    )
    labels: NDArray[np.intp] = db.fit_predict(_distance_matrix(axes, config.dbscan_metric))

    # --- Partition records into clusters and noise ----------------------------
    unique_labels = sorted({int(lbl) for lbl in labels})

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

        # Centroid in original (non-normalised) element space; the node as a
        # direction, so a group either side of 0/360 centres on the seam.
        centroid_inc  = float(np.mean([m.inclination_deg for m in members]))
        centroid_raan = _circular_mean_deg([m.raan_deg for m in members])
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
            span_tolerances=float(axes[:, indices][:, :, indices].max()),
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
