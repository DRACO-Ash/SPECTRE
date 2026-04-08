"""TLE pre-processing: cluster multi-provider TLEs and reduce to one representative per object.

This module is the integration bridge between the :mod:`tle_clustering` standalone
package and the SPECTRE threat-sweep pipeline.  It is intentionally thin — all
clustering logic lives in ``tle_clustering``; this module only handles the
session-state in/out contract.

One representative TLE is written per satno regardless of how many clusters
DBSCAN finds.  When multiple clusters exist (rare: post-manoeuvre objects or
poor coverage), the first representative is used and a WARNING is logged so the
operator is aware that orbit uncertainty is elevated.

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
    config_dict: dict,
) -> tuple[dict[str, str], ClusteringSummary]:
    """Cluster multi-provider TLEs and return a reduced single-TLE cache.

    For each satno in *tle_multiset* with 2+ TLEs, DBSCAN clusters them by
    orbital elements (inclination, RAAN, eccentricity) and selects the best
    representative per cluster.  Exactly **one** TLE is written per satno in
    the returned cache:

    * Single cluster (typical): the representative of that cluster.
    * Multiple clusters (rare — post-manoeuvre or poor data): the representative
      of the first cluster.  A WARNING is logged and ``multi_cluster=True`` is
      set in the per-object summary.
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
        if len(tle_list) < 2:
            # Nothing to cluster — keep existing single TLE unchanged.
            objects_skipped += 1
            obj_summaries.append(ObjectClusteringSummary(
                satno=satno, tles_in=len(tle_list),
                clusters_found=0, representatives_out=min(1, len(tle_list)),
                noise_count=0, reduction_pct=0.0, skipped=True,
            ))
            # Do not write to reduced_cache — caller keeps existing value.
            continue

        total_tles_in += len(tle_list)
        objects_clustered += 1

        # cluster_tle_strings expects a flat list of individual TLE lines.
        # tle_list entries may be combined "line1\nline2" strings; flatten them.
        flat_lines = []
        for tle in tle_list:
            flat_lines.extend(tle.splitlines())

        try:
            results = cluster_tle_strings(flat_lines, cfg)
        except Exception as exc:
            logger.warning(
                "Clustering failed for satno %s: %s — retaining existing cached TLE",
                satno, exc,
            )
            objects_clustered -= 1
            objects_skipped += 1
            total_tles_in -= len(tle_list)
            obj_summaries.append(ObjectClusteringSummary(
                satno=satno, tles_in=len(tle_list),
                clusters_found=0, representatives_out=1,
                noise_count=0, reduction_pct=0.0, skipped=True, fallback=True,
            ))
            # Retain existing cache value unchanged.
            continue

        # Gather all representatives across all ClusteringResult objects.
        reps: list[str] = []
        n_noise = 0
        n_clusters = 0
        for cr in results.values():
            n_clusters += cr.cluster_count
            n_noise += cr.noise_count
            for rep in cr.representatives:
                reps.append(f"{rep.line1}\n{rep.line2}")

        total_noise += n_noise
        is_fallback = False

        if not reps:
            # All TLEs were noise — retain the pre-existing cached TLE.
            fallback_tle = existing_cache.get(satno)
            if fallback_tle:
                reps = [fallback_tle]
                is_fallback = True
                objects_fallback += 1
                logger.warning(
                    "Clustering satno %s: all %d TLEs were noise — retaining existing cached TLE",
                    satno, len(tle_list),
                )
            else:
                # No existing cache and no representatives — skip this satno.
                logger.warning(
                    "Clustering satno %s: all TLEs noise and no cached fallback — skipping",
                    satno,
                )
                obj_summaries.append(ObjectClusteringSummary(
                    satno=satno, tles_in=len(tle_list),
                    clusters_found=n_clusters, representatives_out=0,
                    noise_count=n_noise, reduction_pct=0.0, fallback=True,
                ))
                continue

        # Always write exactly one TLE per satno.
        is_multi = len(reps) > 1
        if is_multi:
            objects_multi_cluster += 1
            logger.warning(
                "Clustering satno %s: %d clusters found — orbit uncertainty elevated; "
                "using first cluster representative",
                satno, len(reps),
            )
        reduced_cache[satno] = reps[0]

        reduction = 100.0 * (1.0 - 1.0 / len(tle_list))
        obj_summaries.append(ObjectClusteringSummary(
            satno=satno, tles_in=len(tle_list),
            clusters_found=n_clusters, representatives_out=1,
            noise_count=n_noise, reduction_pct=reduction,
            multi_cluster=is_multi, fallback=is_fallback,
        ))

        logger.info(
            "Clustering satno %s: %d TLEs → %d cluster(s), 1 rep selected, "
            "%d noise (%.0f%% reduction)",
            satno, len(tle_list), n_clusters, n_noise, reduction,
        )

    # Aggregate stats — representatives_out is always 1 per clustered object.
    total_reps_out = objects_clustered - objects_fallback + (1 if objects_fallback > 0 else 0)
    # Simpler: count how many entries made it into reduced_cache.
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
