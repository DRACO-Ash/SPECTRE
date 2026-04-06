"""Data models for TLE clustering results.

All types are pure dataclasses — no framework dependencies — so this module
can be imported freely in unit tests and downstream pipeline code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TLERecord:
    """A single parsed TLE with extracted mean Keplerian elements.

    Parameters
    ----------
    norad_id:
        NORAD catalogue number extracted from TLE line 1.
    line1:
        The original TLE line 1 string (69 characters).
    line2:
        The original TLE line 2 string (69 characters).
    epoch:
        UTC epoch of the TLE element set.
    inclination_deg:
        Mean inclination in degrees [0, 180].
    raan_deg:
        Mean right ascension of the ascending node in degrees [0, 360).
    eccentricity:
        Mean eccentricity [0, 1).

    Notes
    -----
    The ``tle`` property reconstructs the two-line string on demand, avoiding
    any stored redundancy with ``line1``/``line2``.
    """

    norad_id: int
    line1: str
    line2: str
    epoch: datetime
    inclination_deg: float
    raan_deg: float
    eccentricity: float

    @property
    def tle(self) -> str:
        """Return the full two-line element string (line1 + newline + line2)."""
        return f"{self.line1}\n{self.line2}"

    @property
    def elements(self) -> tuple[float, float, float]:
        """Return ``(inclination_deg, raan_deg, eccentricity)`` as a tuple."""
        return (self.inclination_deg, self.raan_deg, self.eccentricity)


@dataclass(frozen=True)
class Cluster:
    """A group of near-equivalent TLEs sharing the same representative.

    Parameters
    ----------
    cluster_id:
        Non-negative integer label assigned by DBSCAN.
    representative:
        The single TLE selected to represent this cluster downstream.
    members:
        All TLEs assigned to this cluster (includes the representative).
    centroid_inclination_deg:
        Mean inclination across cluster members, degrees.
    centroid_raan_deg:
        Mean RAAN across cluster members, degrees.
    centroid_eccentricity:
        Mean eccentricity across cluster members.

    Notes
    -----
    ``size`` is derived from ``members`` so it cannot drift out of sync.
    """

    cluster_id: int
    representative: TLERecord
    members: tuple[TLERecord, ...]
    centroid_inclination_deg: float
    centroid_raan_deg: float
    centroid_eccentricity: float

    @property
    def size(self) -> int:
        """Number of TLEs in this cluster."""
        return len(self.members)

    @property
    def member_epochs(self) -> tuple[datetime, ...]:
        """Epochs of all cluster members, in the same order as ``members``."""
        return tuple(m.epoch for m in self.members)


@dataclass(frozen=True)
class NoiseTLE:
    """A TLE not assigned to any cluster by DBSCAN (label == -1).

    Parameters
    ----------
    record:
        The unpaired TLERecord.
    reason:
        Human-readable explanation for why this TLE is noise (e.g.
        ``"isolated: no neighbours within tolerance"``).
    """

    record: TLERecord
    reason: str


@dataclass(frozen=True)
class ClusteringResult:
    """Complete output of clustering one NORAD ID's TLE set.

    Parameters
    ----------
    norad_id:
        The NORAD catalogue number for which clustering was performed.
    clusters:
        All clusters formed by DBSCAN (label >= 0).
    noise:
        TLEs not assigned to any cluster (DBSCAN label == -1).

    Notes
    -----
    Summary statistics are computed from ``clusters`` and ``noise`` so they
    remain consistent without maintaining separate counters.
    """

    norad_id: int
    clusters: tuple[Cluster, ...]
    noise: tuple[NoiseTLE, ...]

    @property
    def total_tles_in(self) -> int:
        """Total number of TLEs supplied for this NORAD ID."""
        return sum(c.size for c in self.clusters) + len(self.noise)

    @property
    def representative_count(self) -> int:
        """Number of representative TLEs produced (one per cluster)."""
        return len(self.clusters)

    @property
    def noise_count(self) -> int:
        """Number of noise TLEs not assigned to any cluster."""
        return len(self.noise)

    @property
    def cluster_count(self) -> int:
        """Number of clusters formed."""
        return len(self.clusters)

    @property
    def representatives(self) -> tuple[TLERecord, ...]:
        """All representative TLEs, one per cluster, in cluster_id order."""
        return tuple(c.representative for c in self.clusters)

    def summary(self) -> dict[str, int]:
        """Return a dict of summary statistics suitable for logging."""
        return {
            "norad_id":           self.norad_id,
            "total_in":           self.total_tles_in,
            "clusters":           self.cluster_count,
            "representatives_out": self.representative_count,
            "noise":              self.noise_count,
        }
