"""Shared fixtures and synthetic TLE generation for tle_clustering tests.

TLE format reference (1-indexed column numbers)
------------------------------------------------
Line 1:
  Col  1     : line number '1'
  Col  3-7   : NORAD catalogue number (integer, left-zero-padded to 5 digits)
  Col  8     : classification ('U' = unclassified)
  Col  10-17 : international designator (ignored for tests)
  Col  19-32 : epoch (YYDDD.DDDDDDDD)
  Col  34-43 : first derivative of mean motion (ignored for tests)
  Col  45-52 : second derivative of mean motion (ignored)
  Col  54-61 : BSTAR drag term (ignored)
  Col  63    : ephemeris type ('0')
  Col  65-68 : element set number (ignored)
  Col  69    : checksum (0 for synthetic TLEs — sgp4 accepts this)

Line 2:
  Col  1     : line number '2'
  Col  3-7   : NORAD catalogue number
  Col  9-16  : inclination (degrees, 8 chars)
  Col  18-25 : RAAN (degrees, 8 chars)
  Col  27-33 : eccentricity (7 chars, decimal point omitted)
  Col  35-42 : argument of perigee (degrees, ignored)
  Col  44-51 : mean anomaly (degrees, ignored)
  Col  53-63 : mean motion (revs/day, 11 chars)
  Col  64-68 : revolution number at epoch (ignored)
  Col  69    : checksum (0)

We use a fixed epoch '26091.5' (2026-04-01 12:00:00 UTC, approximately) and
dummy values for fields not used in clustering.  sgp4 will parse these
correctly; the checksum digit is hardcoded to 0 which sgp4 accepts.

Synthetic TLE generation
------------------------
``make_tle_pair(norad, inc_deg, raan_deg, ecc)`` returns a ``(line1, line2)``
tuple with the given orbital elements embedded in valid TLE format.
``make_tle_strings(norad, variations)`` returns a flat list of TLE line strings
for use with ``parse_tle_strings``.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Low-level TLE string builder
# ---------------------------------------------------------------------------

_EPOCH = "26091.50000000"   # 2026 day 91.5 ≈ 2026-04-01 12:00 UTC


def _checksum(line: str) -> int:
    """Compute TLE checksum (mod-10 sum of digits, '-' counts as 1)."""
    total = 0
    for ch in line[:-1]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def make_tle_pair(
    norad: int,
    inc_deg: float,
    raan_deg: float,
    ecc: float,
    epoch: str = _EPOCH,
) -> tuple[str, str]:
    """Return a ``(line1, line2)`` TLE pair with the given mean orbital elements.

    Builds exactly 69-character lines using precise column positions matching
    the TLE standard so that ``Satrec.twoline2rv`` accepts them without error.

    Parameters
    ----------
    norad:
        NORAD catalogue number (1–99999).
    inc_deg:
        Inclination [degrees].
    raan_deg:
        RAAN [degrees].
    ecc:
        Eccentricity [dimensionless, 0–0.9999999].
    epoch:
        Epoch string (YYDDD.DDDDDDDD format, exactly 14 chars).

    Returns
    -------
    tuple[str, str]
        ``(line1, line2)`` suitable for passing to ``Satrec.twoline2rv``.
    """
    n = f"{norad:05d}"
    ecc_str = f"{ecc:.7f}"[2:]          # strip leading "0." → 7 digits

    # TLE Line 1 — strict 69-char layout, checksum in col 69 (index 68)
    # Col:  1  3-7  8  10-17  19-32         34-43          45-52    54-61      63 65-68 69
    l1_body = (
        f"1 {n}U 98067A   {epoch}"       # cols 1-32  (1-indexed)
        f"  .00000000"                    # cols 34-43 (1st deriv MM)
        f"  00000-0"                      # cols 45-52 (2nd deriv MM)
        f"  00000-0"                      # cols 54-61 (BSTAR)
        f" 0  999"                        # cols 62-68 (eph type, elset no.)
    )
    l1 = l1_body + str(_checksum(l1_body + "0"))

    # TLE Line 2 — strict 69-char layout
    # Col:  1  3-7  9-16      18-25      27-33   35-42     44-51     53-63         64-68  69
    l2_body = (
        f"2 {n} "
        f"{inc_deg:8.4f} "
        f"{raan_deg:8.4f} "
        f"{ecc_str} "
        f"100.0000 "
        f"200.0000 "
        f"15.5432109800001"               # mean motion + rev count (16 chars total)
    )
    l2 = l2_body + str(_checksum(l2_body + "0"))

    return l1, l2


def make_tle_strings(
    norad: int,
    variations: list[tuple[float, float, float]],
    epoch: str = _EPOCH,
) -> list[str]:
    """Return a flat list of TLE line strings from a list of element variations.

    Parameters
    ----------
    norad:
        NORAD catalogue number.
    variations:
        List of ``(inc_deg, raan_deg, ecc)`` tuples, one per TLE to generate.
    epoch:
        Epoch string applied to all TLEs.

    Returns
    -------
    list[str]
        Alternating line1, line2, line1, line2, ... strings.
    """
    lines: list[str] = []
    for inc, raan, ecc in variations:
        l1, l2 = make_tle_pair(norad, inc, raan, ecc, epoch=epoch)
        lines.append(l1)
        lines.append(l2)
    return lines


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_norad() -> int:
    """A stable NORAD ID used across tests that don't care about the specific value."""
    return 25544


@pytest.fixture
def tight_cluster_variations() -> list[tuple[float, float, float]]:
    """Five TLEs with sub-tolerance element variations (should form one cluster)."""
    base_inc, base_raan, base_ecc = 51.6400, 247.1234, 0.0001234
    return [
        (base_inc + 0.000, base_raan + 0.000, base_ecc + 0.000_000_0),
        (base_inc + 0.005, base_raan + 0.010, base_ecc + 0.000_005_0),
        (base_inc - 0.003, base_raan - 0.020, base_ecc - 0.000_003_0),
        (base_inc + 0.008, base_raan + 0.030, base_ecc + 0.000_008_0),
        (base_inc - 0.007, base_raan - 0.015, base_ecc - 0.000_007_0),
    ]


@pytest.fixture
def spread_variations() -> list[tuple[float, float, float]]:
    """Four TLEs that are too far apart to cluster under default tolerances."""
    return [
        (51.64, 247.12, 0.000123),
        (52.10, 250.00, 0.001000),   # >0.05 deg RAAN from others
        (51.64, 255.00, 0.000123),   # well outside RAAN tolerance
        (55.00, 247.12, 0.000123),   # well outside inclination tolerance
    ]
