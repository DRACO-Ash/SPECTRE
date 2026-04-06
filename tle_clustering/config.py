"""Clustering configuration for the TLE de-duplication pipeline.

All tolerances, DBSCAN hyper-parameters, and selection heuristics live here.
Downstream code must not hard-code any of these values; always read from a
``ClusteringConfig`` instance.

Example
-------
Use the defaults::

    cfg = ClusteringConfig()

Override inclination tolerance only::

    cfg = ClusteringConfig(inclination_tolerance_deg=0.005)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClusteringConfig:
    """Configuration for TLE DBSCAN clustering and representative selection.

    Element tolerances
    ------------------
    These define the per-element neighbourhood radius.  Before DBSCAN runs,
    each element is divided by its tolerance so that the normalised space is
    dimensionless and DBSCAN ``eps=1.0`` corresponds exactly to one tolerance
    unit in every axis simultaneously (Chebyshev metric).

    inclination_tolerance_deg:
        Neighbourhood half-width for inclination [degrees].  Default 0.01 °.
    raan_tolerance_deg:
        Neighbourhood half-width for RAAN [degrees].  Default 0.05 °.
    eccentricity_tolerance:
        Neighbourhood half-width for eccentricity [dimensionless].  Default 1e-4.

    DBSCAN parameters
    -----------------
    dbscan_eps:
        DBSCAN neighbourhood radius in normalised space.  Should be left at
        1.0 when tolerances are used for normalisation; increase to widen the
        effective neighbourhood.  Default 1.0.
    dbscan_min_samples:
        Minimum cluster size; TLEs in groups smaller than this are labelled
        noise.  Default 2 (a lone TLE cannot form a cluster by itself).
    dbscan_metric:
        Distance metric passed to DBSCAN.  ``'chebyshev'`` (L-∞ norm) means
        every element must individually satisfy its tolerance — none can be
        compensated by another being well-matched.  Default ``'chebyshev'``.

    Notes
    -----
    To add a fourth clustering dimension (e.g. mean motion), add a
    ``mean_motion_tolerance_rev_per_day`` field here and update
    ``parser.TLERecord`` and ``clustering._normalise`` accordingly — no other
    files need to change.
    """

    # Per-element tolerances
    inclination_tolerance_deg: float = 0.01
    raan_tolerance_deg: float = 0.05
    eccentricity_tolerance: float = 1e-4

    # DBSCAN hyper-parameters
    dbscan_eps: float = 1.0
    dbscan_min_samples: int = 2
    dbscan_metric: str = "chebyshev"

    @classmethod
    def from_constants(cls, config_dict: dict) -> ClusteringConfig:
        """Construct a :class:`ClusteringConfig` from a SIPC constants dict.

        This factory keeps the clustering package decoupled from SIPC's config
        module — the caller reads ``TLE_CLUSTERING`` from ``constants.py`` and
        passes the dict in.  Unknown keys in *config_dict* are silently ignored
        so that adding future constants keys (e.g. ``fetch_window_hours``) does
        not break this constructor.

        Parameters
        ----------
        config_dict:
            Dict sourced from ``sipc.config.constants.TLE_CLUSTERING``.

        Returns
        -------
        ClusteringConfig
            Populated from dict values; any missing key falls back to the
            field default defined on the dataclass.
        """
        return cls(
            inclination_tolerance_deg=float(
                config_dict.get("inclination_tolerance_deg", 0.01)
            ),
            raan_tolerance_deg=float(
                config_dict.get("raan_tolerance_deg", 0.05)
            ),
            eccentricity_tolerance=float(
                config_dict.get("eccentricity_tolerance", 1e-4)
            ),
            dbscan_eps=float(
                config_dict.get("dbscan_eps", 1.0)
            ),
            dbscan_min_samples=int(
                config_dict.get("dbscan_min_samples", 2)
            ),
            dbscan_metric=str(
                config_dict.get("dbscan_metric", "chebyshev")
            ),
        )

    def __post_init__(self) -> None:
        """Validate that all tolerances and DBSCAN parameters are positive."""
        if self.inclination_tolerance_deg <= 0:
            raise ValueError(
                f"inclination_tolerance_deg must be > 0, got {self.inclination_tolerance_deg}"
            )
        if self.raan_tolerance_deg <= 0:
            raise ValueError(
                f"raan_tolerance_deg must be > 0, got {self.raan_tolerance_deg}"
            )
        if self.eccentricity_tolerance <= 0:
            raise ValueError(
                f"eccentricity_tolerance must be > 0, got {self.eccentricity_tolerance}"
            )
        if self.dbscan_eps <= 0:
            raise ValueError(f"dbscan_eps must be > 0, got {self.dbscan_eps}")
        if self.dbscan_min_samples < 1:
            raise ValueError(
                f"dbscan_min_samples must be >= 1, got {self.dbscan_min_samples}"
            )
