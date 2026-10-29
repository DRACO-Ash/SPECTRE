"""Phase angle: how far ahead of or behind the interceptor its target sits.

In a co-orbital intercept the phase angle is the dominant term in the cost, and
the sweep never named it: it reported the burn as at "apogee" or "perigee" on
orbits where the two are 13 km apart, which hides the cause behind a label
(red team finding 3, docs/RED-TEAM-THREAT-SWEEP.md).

The angle is measured in the interceptor's own orbital plane, from its position
to the target's position projected into that plane, positive in the direction
of motion. A target 30 degrees ahead is +30; one 30 degrees behind is -30.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["phase_angle_deg"]


def phase_angle_deg(r_chaser: np.ndarray, v_chaser: np.ndarray, r_target: np.ndarray) -> float:
    """Signed in-plane angle from the chaser to the target, degrees in [-180, 180].

    Positions and velocity in any one inertial frame; only directions matter.
    Raises ``ValueError`` when the chaser's plane is undefined (zero angular
    momentum) or the target sits on the plane's normal, where no angle exists.
    """
    h = np.cross(r_chaser, v_chaser)
    h_norm = float(np.linalg.norm(h))
    if h_norm == 0.0:
        raise ValueError("the chaser's orbital plane is undefined")
    normal = h / h_norm
    in_plane = r_target - float(np.dot(r_target, normal)) * normal
    if float(np.linalg.norm(in_plane)) == 0.0:
        raise ValueError("the target lies on the chaser's orbit normal")
    return math.degrees(math.atan2(float(np.dot(normal, np.cross(r_chaser, in_plane))),
                                   float(np.dot(r_chaser, in_plane))))
