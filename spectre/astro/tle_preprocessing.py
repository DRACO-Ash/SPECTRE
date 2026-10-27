"""TLE pre-processing: cluster multi-provider TLEs and reduce to one representative per object.

This module is the integration bridge between the :mod:`tle_clustering` standalone
package and the SPECTRE threat-sweep pipeline.  It is intentionally thin — all
clustering logic lives in ``tle_clustering``; this module only handles the
session-state in/out contract.

One representative TLE is written per satno regardless of how many clusters
DBSCAN finds. When multiple clusters exist (post-manoeuvre objects, poor
coverage, or a fast-regressing RAAN spreading one orbit across several), the
representative of the cluster with the most recent member is used, so an
object that has just manoeuvred is written with its post-burn orbit, and a
WARNING is logged so the operator is aware that orbit uncertainty is elevated.
DBSCAN numbers clusters in scan order, so the "first" representative used
before was the cluster holding the earliest input record (audit F-028).

Input format
------------
*tle_multiset* values are ``"line1\\nline2"`` combined strings, as returned by
:func:`spectre.web.routes.udl.fetch_tle_history_for_satno`.  The function
automatically flattens these before passing to :func:`tle_clustering.cluster_tle_strings`,
which expects a plain ``["line1", "line2", ...]`` list.

Usage::

    from spectre.astro.tle_preprocessing import cluster_and_reduce_tle_cache
    from spectre.config.constants import TLE_CLUSTERING

    reduced_cache, summary = cluster_and_reduce_tle_cache(
        state.hrr_tle_multiset,
        state.hrr_tle_cache,
        TLE_CLUSTERING,
    )
    state.hrr_tle_cache.update(reduced_cache)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ObjectClusteringSummary:
    """Per-object clustering statistics.

    Attributes:
        satno: NORAD catalogue number (as string, matching session-state keys).
        tles_in: Number of TLEs submitted to the clusterer.
        clusters_found: Number of DBSCAN clusters identified.
        representatives_out: Number of representatives selected (one per cluster).
            Always 1 after post-processing; multi-cluster objects are collapsed to
            their first representative and flagged via ``multi_cluster=True``.
        noise_count: TLEs labelled noise (not assigned to any cluster).
        reduction_pct: Percentage reduction: ``100 * (1 - 1 / tles_in)``.
            0.0 when ``tles_in == 0`` or ``skipped == True``.
        skipped: True when fewer than 2 TLEs were available (nothing to cluster).
        multi_cluster: True when DBSCAN returned >1 cluster — orbit uncertainty
            may be elevated (e.g. post-manoeuvre object or poor tracking coverage).
        fallback: True when clustering found no valid representatives and the
            pre-existing cached TLE was retained unchanged.
    """

    satno: str
    tles_in: int
    clusters_found: int
    representatives_out: int
    noise_count: int
    reduction_pct: float
    skipped: bool = False
    multi_cluster: bool = False
    fallback: bool = False


@dataclass
class ClusteringSummary:
    """Aggregate clustering summary for an entire sweep.

    Attributes:
        objects: Per-object breakdown.
        total_tles_in: Sum of TLEs submitted across all objects.
        total_representatives_out: Sum of representatives selected (one per object).
        total_noise: Sum of noise TLEs across all clustered objects.
        objects_skipped: Number of objects with fewer than 2 TLEs (no clustering).
        objects_clustered: Number of objects where DBSCAN ran.
        objects_multi_cluster: Number of objects with >1 cluster (elevated uncertainty).
        objects_fallback: Number of objects where fallback to existing cache was used.
        overall_reduction_pct: ``100 * (1 - total_representatives_out / total_tles_in)``.
            Zero when ``total_tles_in == 0``.
    """

    objects: list[ObjectClusteringSummary] = field(default_factory=list)
    total_tles_in: int = 0
    total_representatives_out: int = 0
    total_noise: int = 0
    objects_skipped: int = 0
    objects_clustered: int = 0
    objects_multi_cluster: int = 0
    objects_fallback: int = 0
    overall_reduction_pct: float = 0.0


# ── Main entry point ──────────────────────────────────────────────────────────

def cluster_and_reduce_tle_cache(
    tle_multiset: dict[str, list[str]],
    existing_cache: dict[str, str],
    config_dict: dict[str, Any],
) -> tuple[dict[str, str], ClusteringSummary]:
    """Cluster multi-provider TLEs and return a reduced single-TLE cache.

    For each satno in *tle_multiset* with 2+ TLEs, DBSCAN clusters them by
    orbital elements (inclination, RAAN, eccentricity) and selects the best
    representative per cluster.  Exactly **one** TLE is written per satno in
    the returned cache:

    * Single cluster (typical): the representative of that cluster.
    * Multiple clusters (post-manoeuvre or poor data): the representative of
      the cluster with the most recent member.  A WARNING is logged and
      ``multi_cluster=True`` is set in the per-object summary.
    * All noise (very rare): the pre-existing cached TLE is retained unchanged
      and ``fallback=True`` is set.

    Satnos present in *existing_cache* but absent from *tle_multiset* are not
    written to *reduced_cache* at all; the caller's original ``hrr_tle_cache``
    is left unchanged for those entries.

    Parameters
    ----------
    tle_multiset:
        Mapping of satno (str) → list of ``"line1\\nline2"`` TLE strings.
        Each combined string is automatically flattened before parsing.
        Populated by :func:`spectre.web.routes.udl.fetch_tle_history_for_satno`.
    existing_cache:
        Current ``state.hrr_tle_cache`` (satno → single TLE string).  Used as
        a fallback for satnos where clustering produces no representatives.
    config_dict:
        ``spectre.config.constants.TLE_CLUSTERING`` dict.

    Returns
    -------
    tuple[dict[str, str], ClusteringSummary]
        * ``reduced_cache``: satno → best-representative TLE string.  Only
          contains entries for satnos that were processed (present in
          *tle_multiset* with 2+ TLEs, or falling back from noise).
        * ``summary``: :class:`ClusteringSummary` with per-object and aggregate stats.
    """
    try:
        from tle_clustering import cluster_tle_strings
        from tle_clustering.config import ClusteringConfig
    except ImportError:
        logger.warning(
            "tle_clustering package not available — skipping TLE clustering step"
        )
        return {}, ClusteringSummary()

    cfg = ClusteringConfig.from_constants(config_dict)

    reduced_cache: dict[str, str] = {}
    obj_summaries: list[ObjectClusteringSummary] = []
    total_tles_in = 0
    total_noise = 0
    objects_skipped = 0
    objects_clustered = 0
    objects_multi_cluster = 0
    objects_fallback = 0

    for satno, tle_list in tle_multiset.items():
        outcome = _reduce_one(satno, tle_list, existing_cache, cfg, cluster_tle_strings)
        obj_summaries.append(outcome.summary)
        if outcome.clustered:
            objects_clustered += 1
            total_tles_in += len(tle_list)
        else:
            objects_skipped += 1
        total_noise += outcome.noise
        objects_multi_cluster += outcome.multi
        objects_fallback += outcome.fallback
        if outcome.tle is not None:
            reduced_cache[satno] = outcome.tle

    # Representatives written; a fallback keeps the cached TLE, which the
    # caller already holds, so it is not written again (audit F-213).
    total_reps_out = len(reduced_cache)

    overall_reduction = (
        100.0 * (1.0 - total_reps_out / total_tles_in)
        if total_tles_in > 0 else 0.0
    )

    summary = ClusteringSummary(
        objects=obj_summaries,
        total_tles_in=total_tles_in,
        total_representatives_out=total_reps_out,
        total_noise=total_noise,
        objects_skipped=objects_skipped,
        objects_clustered=objects_clustered,
        objects_multi_cluster=objects_multi_cluster,
        objects_fallback=objects_fallback,
        overall_reduction_pct=overall_reduction,
    )

    logger.info(
        "TLE clustering complete: %d objects clustered, %d skipped; "
        "%d TLEs → %d representatives (%.0f%% reduction, %d noise, %d multi-cluster, %d fallback)",
        objects_clustered, objects_skipped,
        total_tles_in, total_reps_out, overall_reduction,
        total_noise, objects_multi_cluster, objects_fallback,
    )

    return reduced_cache, summary


# An object needs at least this many TLEs before clustering means anything.
_MIN_TLES_TO_CLUSTER = 2


@dataclass
class _Outcome:
    """What reducing one object's TLE list produced, for the caller to tally."""

    summary: ObjectClusteringSummary
    tle: str | None = None    # written to the reduced cache when set
    clustered: bool = False   # counted as clustered (else skipped)
    noise: int = 0
    multi: bool = False
    fallback: bool = False


def _reduce_one(
    satno: str,
    tle_list: list[str],
    existing_cache: dict[str, str],
    cfg: Any,
    cluster_tle_strings: Any,
) -> _Outcome:
    """Cluster one object's TLEs and choose the single TLE to write."""
    if len(tle_list) < _MIN_TLES_TO_CLUSTER:
        # Nothing to cluster — keep existing single TLE unchanged.
        return _Outcome(ObjectClusteringSummary(
            satno=satno, tles_in=len(tle_list),
            clusters_found=0, representatives_out=min(1, len(tle_list)),
            noise_count=0, reduction_pct=0.0, skipped=True,
        ))

    # cluster_tle_strings expects a flat list of individual TLE lines.
    # tle_list entries may be combined "line1\nline2" strings; flatten them.
    flat_lines = [line for tle in tle_list for line in tle.splitlines()]

    try:
        results = cluster_tle_strings(flat_lines, cfg)
    except Exception as exc:  # noqa: BLE001 - any clustering failure keeps the cached TLE
        logger.warning(
            "Clustering failed for satno %s: %s — retaining existing cached TLE",
            satno, exc,
        )
        # Retain existing cache value unchanged. A fallback is counted as one,
        # and a representative only when there is a cached TLE to fall back
        # to; both were wrong here (audit F-215).
        return _Outcome(ObjectClusteringSummary(
            satno=satno, tles_in=len(tle_list),
            clusters_found=0, representatives_out=1 if existing_cache.get(satno) else 0,
            noise_count=0, reduction_pct=0.0, skipped=True, fallback=True,
        ), fallback=True)

    # Newest cluster first, by its most recent member epoch.
    clusters = sorted(
        (c for cr in results.values() for c in cr.clusters),
        key=lambda c: max(c.member_epochs),
        reverse=True,
    )
    reps = [f"{c.representative.line1}\n{c.representative.line2}" for c in clusters]
    n_noise = sum(cr.noise_count for cr in results.values())
    n_clusters = sum(cr.cluster_count for cr in results.values())

    if not reps:
        return _all_noise(satno, tle_list, existing_cache, n_clusters, n_noise)

    # DBSCAN links neighbours, so a cluster can be a chain whose ends differ
    # by several tolerances: a slow drift, or a small manoeuvre bridged by
    # intermediate fits, hidden inside one representative (audit F-163).
    for c in clusters:
        if c.exceeds_tolerance:
            logger.warning(
                "Clustering satno %s: a cluster of %d spans %.1f tolerances end to end — "
                "a chain of fits; possible slow drift or a bridged manoeuvre",
                satno, c.size, c.span_tolerances,
            )

    # Always write exactly one TLE per satno.
    is_multi = len(reps) > 1
    if is_multi:
        logger.warning(
            "Clustering satno %s: %d clusters found — orbit uncertainty elevated; "
            "using the representative of the most recent cluster",
            satno, len(reps),
        )

    reduction = 100.0 * (1.0 - 1.0 / len(tle_list))
    logger.info(
        "Clustering satno %s: %d TLEs → %d cluster(s), 1 rep selected, "
        "%d noise (%.0f%% reduction)",
        satno, len(tle_list), n_clusters, n_noise, reduction,
    )
    return _Outcome(
        ObjectClusteringSummary(
            satno=satno, tles_in=len(tle_list),
            clusters_found=n_clusters, representatives_out=1,
            noise_count=n_noise, reduction_pct=reduction,
            multi_cluster=is_multi, fallback=False,
        ),
        tle=reps[0], clustered=True, noise=n_noise, multi=is_multi,
    )


def _all_noise(
    satno: str,
    tle_list: list[str],
    existing_cache: dict[str, str],
    n_clusters: int,
    n_noise: int,
) -> _Outcome:
    """Every TLE was noise: keep the cached TLE if there is one, else drop the object."""
    fallback_tle = existing_cache.get(satno)
    if not fallback_tle:
        logger.warning(
            "Clustering satno %s: all TLEs noise and no cached fallback — skipping",
            satno,
        )
        return _Outcome(
            ObjectClusteringSummary(
                satno=satno, tles_in=len(tle_list),
                clusters_found=n_clusters, representatives_out=0,
                noise_count=n_noise, reduction_pct=0.0, fallback=True,
            ),
            clustered=True, noise=n_noise, fallback=True,
        )
    logger.warning(
        "Clustering satno %s: all %d TLEs were noise — retaining existing cached TLE",
        satno, len(tle_list),
    )
    reduction = 100.0 * (1.0 - 1.0 / len(tle_list))
    logger.info(
        "Clustering satno %s: %d TLEs → %d cluster(s), 1 rep selected, "
        "%d noise (%.0f%% reduction)",
        satno, len(tle_list), n_clusters, n_noise, reduction,
    )
    return _Outcome(
        ObjectClusteringSummary(
            satno=satno, tles_in=len(tle_list),
            clusters_found=n_clusters, representatives_out=1,
            noise_count=n_noise, reduction_pct=reduction,
            multi_cluster=False, fallback=True,
        ),
        tle=fallback_tle, clustered=True, noise=n_noise, fallback=True,
    )
