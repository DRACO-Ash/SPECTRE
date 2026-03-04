"""Pure-math geometry helpers for intercept planning.

All functions are stateless and have no STK dependency, making them
trivially unit-testable. Angles are in degrees, distances in km,
speeds in m/s unless otherwise noted.
"""

from __future__ import annotations

import math


def azimuth_elevation_range(
    observer_ecef: tuple[float, float, float],
    target_ecef: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Compute azimuth, elevation, and range from observer to target.

    Both positions must be in the same Earth-Centred Earth-Fixed (ECEF) frame,
    expressed in kilometres.

    Args:
        observer_ecef: (x, y, z) km of the observer.
        target_ecef: (x, y, z) km of the target.

    Returns:
        Tuple of ``(azimuth_deg, elevation_deg, range_km)``.

    Note:
        This is a geometric stub — a full implementation requires
        conversion to local topocentric frame (SEZ or NED).
    """
    dx = target_ecef[0] - observer_ecef[0]
    dy = target_ecef[1] - observer_ecef[1]
    dz = target_ecef[2] - observer_ecef[2]

    range_km = math.sqrt(dx**2 + dy**2 + dz**2)
    # Stub: return placeholder angles until full SEZ transform is implemented
    azimuth_deg = math.degrees(math.atan2(dy, dx)) % 360.0
    elevation_deg = math.degrees(math.asin(dz / range_km)) if range_km > 0 else 0.0

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
