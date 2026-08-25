"""TLE parsing and Keplerian element extraction.

Accepts raw two-line element strings and extracts the mean orbital elements
needed for clustering: inclination, RAAN, and eccentricity.  The ``sgp4``
library's ``Satrec.twoline2rv()`` is used for parsing so that element
extraction is consistent with the SGP4 propagator used elsewhere in SPECTRE.

Usage::

    records = parse_tle_strings(["1 25544U ...", "2 25544 ..."])
    # or already-split pairs:
    records = parse_tle_pair(line1, line2)
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta

from sgp4.api import Satrec

from tle_clustering.models import TLERecord

logger = logging.getLogger(__name__)

# SGP4 epoch reference: 1949-12-31 00:00:00 UTC (Julian date 2433281.5)
_SGP4_EPOCH_JD = 2433281.5


def _jd_to_datetime(jd: float, fr: float) -> datetime:
    """Convert a Julian date split into integer day and fractional day to UTC datetime.

    Parameters
    ----------
    jd:
        Integer part of the Julian date (from sgp4's ``jdsatepoch``).
    fr:
        Fractional day part (from sgp4's ``jdsatepochF``).

    Returns
    -------
    datetime
        UTC-aware datetime corresponding to ``jd + fr``.
    """
    total_jd = jd + fr
    # Days since the Unix epoch (JD 2440587.5)
    days_since_unix = total_jd - 2440587.5
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(days=days_since_unix)


def parse_tle_pair(line1: str, line2: str) -> TLERecord:
    """Parse a single TLE pair and return a :class:`~tle_clustering.models.TLERecord`.

    Parameters
    ----------
    line1:
        TLE line 1 (must start with ``'1 '``).
    line2:
        TLE line 2 (must start with ``'2 '``).

    Returns
    -------
    TLERecord
        Parsed record with extracted elements.

    Raises
    ------
    ValueError
        If sgp4 reports a non-zero error code or the lines are malformed.
    """
    sat = Satrec.twoline2rv(line1.strip(), line2.strip())
    if sat.error != 0:
        raise ValueError(
            f"sgp4 parse error {sat.error} for TLE: {line1.strip()!r}"
        )

    epoch = _jd_to_datetime(sat.jdsatepoch, sat.jdsatepochF)

    inclination_deg = math.degrees(sat.inclo)
    raan_deg = math.degrees(sat.nodeo)
    eccentricity = sat.ecco

    return TLERecord(
        norad_id=sat.satnum,
        line1=line1.strip(),
        line2=line2.strip(),
        epoch=epoch,
        inclination_deg=inclination_deg,
        raan_deg=raan_deg,
        eccentricity=eccentricity,
    )


def parse_tle_strings(lines: list[str]) -> list[TLERecord]:
    """Parse a flat list of TLE line strings into :class:`~tle_clustering.models.TLERecord` objects.

    Lines are consumed in pairs (line1, line2).  Name lines (line 0, common in
    three-line format) are silently skipped — any line not starting with ``'1 '``
    or ``'2 '`` is discarded before pairing.

    Parameters
    ----------
    lines:
        Flat list of TLE strings.  May be two-line or three-line format.
        Blank lines and whitespace-only entries are ignored.

    Returns
    -------
    list[TLERecord]
        Parsed records.  Malformed pairs are skipped with a WARNING log entry;
        they do not raise exceptions so that a batch call can proceed despite
        one bad TLE.
    """
    # Strip and filter blank/name lines
    filtered: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s.startswith(("1 ", "2 ")):
            filtered.append(s)
        else:
            logger.debug("parser: skipping name line: %r", s[:40])

    if len(filtered) % 2 != 0:
        logger.warning(
            "parser: odd number of TLE lines after filtering (%d); "
            "the last line will be skipped.",
            len(filtered),
        )
        filtered = filtered[: len(filtered) - 1]

    records: list[TLERecord] = []
    for i in range(0, len(filtered), 2):
        l1, l2 = filtered[i], filtered[i + 1]
        if not l1.startswith("1 ") or not l2.startswith("2 "):
            logger.warning(
                "parser: unexpected line order at index %d "
                "(expected line1 then line2); skipping pair.",
                i,
            )
            continue
        try:
            records.append(parse_tle_pair(l1, l2))
        except ValueError as exc:
            logger.warning("parser: skipping malformed TLE pair at index %d: %s", i, exc)

    return records


def group_by_norad(records: list[TLERecord]) -> dict[int, list[TLERecord]]:
    """Group a mixed list of :class:`~tle_clustering.models.TLERecord` objects by NORAD ID.

    Parameters
    ----------
    records:
        Parsed TLE records, potentially covering multiple objects.

    Returns
    -------
    dict[int, list[TLERecord]]
        Mapping of NORAD catalogue number → list of records for that object.
        Records within each list preserve their original order.
    """
    groups: dict[int, list[TLERecord]] = {}
    for rec in records:
        groups.setdefault(rec.norad_id, []).append(rec)
    return groups
