"""Pure-math geometry helpers for intercept planning.

All functions are stateless and have no STK dependency, making them
trivially unit-testable. Angles are in degrees, distances in km,
speeds in m/s unless otherwise noted.
"""

from __future__ import annotations

import math


def ecef_to_sez(
    observer_ecef: tuple[float, float, float],
    target_ecef: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Rotate an ECEF difference vector into the local SEZ frame.

    The SEZ (South-East-Zenith) frame is a topocentric Cartesian frame
    centred on the observer:

    * **S** — points due South along the local meridian
    * **E** — points due East, tangent to the surface
    * **Z** — points toward the geocentric zenith (radially outward)

    The rotation is parameterised by the observer's geocentric latitude
    (φ) and longitude (λ), derived from the ECEF position assuming a
    spherical Earth::

        ┌   ┐   ┌  sinφ cosλ   sinφ sinλ   −cosφ ┐ ┌    ┐
        │ S │   │  −sinλ        cosλ         0    │ │ Δx │
        │ E │ = │                                  │ │ Δy │
        │ Z │   │  cosφ cosλ   cosφ sinλ    sinφ  │ │ Δz │
        └   ┘   └                                  ┘ └    ┘

    Args:
        observer_ecef: (x, y, z) km of the observer.
        target_ecef: (x, y, z) km of the target.

    Returns:
        (S, E, Z) components in km in the local SEZ frame.
    """
    dx = target_ecef[0] - observer_ecef[0]
    dy = target_ecef[1] - observer_ecef[1]
    dz = target_ecef[2] - observer_ecef[2]

    ox, oy, oz = observer_ecef
    lon = math.atan2(oy, ox)
    r_xy = math.sqrt(ox**2 + oy**2)
    lat = math.atan2(oz, r_xy)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    s = sin_lat * cos_lon * dx + sin_lat * sin_lon * dy - cos_lat * dz
    e = -sin_lon * dx + cos_lon * dy
    z = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz

    return s, e, z


def azimuth_elevation_range(
    observer_ecef: tuple[float, float, float],
    target_ecef: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Compute azimuth, elevation, and range from observer to target.

    Both positions must be in the same Earth-Centred Earth-Fixed (ECEF) frame,
    expressed in kilometres.  The conversion uses the local SEZ (South-East-Zenith)
    topocentric frame derived from the observer's geocentric latitude and longitude.

    Azimuth is measured clockwise from North (0–360°).
    Elevation is measured from the local horizontal plane (−90° to +90°).

    Args:
        observer_ecef: (x, y, z) km of the observer.
        target_ecef: (x, y, z) km of the target.

    Returns:
        Tuple of ``(azimuth_deg, elevation_deg, range_km)``.
    """
    s, e, z = ecef_to_sez(observer_ecef, target_ecef)

    range_km = math.sqrt(s**2 + e**2 + z**2)
    if range_km == 0.0:
        return 0.0, 0.0, 0.0

    elevation_deg = math.degrees(math.asin(z / range_km))
    # Azimuth is clockwise from North; in SEZ, North = -S direction
    azimuth_deg = math.degrees(math.atan2(e, -s)) % 360.0

    return azimuth_deg, elevation_deg, range_km


def closure_rate_ms(
    rel_position_km: tuple[float, float, float],
    rel_velocity_ms: tuple[float, float, float],
) -> float:
    """Compute the closure rate (range rate) between two objects.

    A positive value indicates the objects are approaching each other.

    Args:
        rel_position_km: Relative position vector (target − observer) in km.
        rel_velocity_ms: Relative velocity vector (target − observer) in m/s.

    Returns:
        Closure rate in m/s (positive = closing, negative = opening).
    """
    px, py, pz = rel_position_km
    vx, vy, vz = rel_velocity_ms
    range_km = math.sqrt(px**2 + py**2 + pz**2)
    if range_km == 0.0:
        return 0.0
    # Unit range vector (km → dimensionless)
    rx, ry, rz = px / range_km, py / range_km, pz / range_km
    # Dot product with velocity gives range rate (m/s, sign: positive = receding)
    range_rate = rx * vx + ry * vy + rz * vz
    # Closure rate is the negative of range rate
    return -range_rate


def degrees_to_radians(degrees: float) -> float:
    """Convert degrees to radians."""
    return math.radians(degrees)


def radians_to_degrees(radians: float) -> float:
    """Convert radians to degrees."""
    return math.degrees(radians)
