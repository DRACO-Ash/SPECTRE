"""Classical impulsive orbit transfer calculations.

All functions use the vis-viva equation: v = sqrt(μ × (2/r − 1/a)).
Inputs/outputs in km and km/s unless noted otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sipc.astro.constants import MU_EARTH


@dataclass
class TransferResult:
    """Result of an impulsive orbit transfer calculation."""

    delta_v_1: float          # km/s — first burn magnitude
    delta_v_2: float          # km/s — second burn magnitude
    delta_v_3: float = 0.0    # km/s — third burn (bi-elliptic only)
    total_delta_v: float = 0.0
    transfer_time_s: float = 0.0
    method: str = ""

    def __post_init__(self) -> None:
        if self.total_delta_v == 0.0:
            self.total_delta_v = self.delta_v_1 + self.delta_v_2 + self.delta_v_3


def _v_vis_viva(r: float, a: float, mu: float = MU_EARTH) -> float:
    """Orbital velocity from the vis-viva equation."""
    return math.sqrt(mu * (2.0 / r - 1.0 / a))


def hohmann(r1: float, r2: float, mu: float = MU_EARTH) -> TransferResult:
    """Compute a Hohmann transfer between two circular orbits.

    Args:
        r1: Radius of initial circular orbit (km).
        r2: Radius of target circular orbit (km).
        mu: Gravitational parameter (km³/s²).

    Returns:
        :class:`TransferResult` with two burns and transfer time.
    """
    a_t = (r1 + r2) / 2.0

    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)
    v_t_p = _v_vis_viva(r1, a_t, mu)
    v_t_a = _v_vis_viva(r2, a_t, mu)

    dv1 = abs(v_t_p - v1)
    dv2 = abs(v2 - v_t_a)
    t_transfer = math.pi * math.sqrt(a_t**3 / mu)

    return TransferResult(
        delta_v_1=dv1,
        delta_v_2=dv2,
        transfer_time_s=t_transfer,
        method="hohmann",
    )


def bielliptic(
    r1: float, r2: float, rb: float, mu: float = MU_EARTH,
) -> TransferResult:
    """Compute a bi-elliptic transfer between two circular orbits.

    Args:
        r1: Radius of initial circular orbit (km).
        r2: Radius of target circular orbit (km).
        rb: Intermediate apoapsis radius (km) — must be > max(r1, r2).
        mu: Gravitational parameter (km³/s²).

    Returns:
        :class:`TransferResult` with three burns and transfer time.
    """
    a1 = (r1 + rb) / 2.0
    a2 = (r2 + rb) / 2.0

    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)

    v_t1_p = _v_vis_viva(r1, a1, mu)
    v_t1_a = _v_vis_viva(rb, a1, mu)
    v_t2_a = _v_vis_viva(rb, a2, mu)
    v_t2_p = _v_vis_viva(r2, a2, mu)

    dv1 = abs(v_t1_p - v1)
    dv2 = abs(v_t2_a - v_t1_a)
    dv3 = abs(v2 - v_t2_p)
    t_transfer = math.pi * math.sqrt(a1**3 / mu) + math.pi * math.sqrt(a2**3 / mu)

    return TransferResult(
        delta_v_1=dv1,
        delta_v_2=dv2,
        delta_v_3=dv3,
        transfer_time_s=t_transfer,
        method="bielliptic",
    )
