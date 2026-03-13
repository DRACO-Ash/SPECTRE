"""
rendezvous_planner.py
Intercept Method 1: Direct Rendezvous (position & velocity match).

Design Philosophy:
------------------
This planner returns a high-level "sequence plan" which the MCSBuilder
converts into actual Astrogator segments.

The plan includes:
• Initial propagation to user-selected intercept time
• One impulsive maneuver with 3 controllable ΔV components
• Differential corrector target sequence to match:
    - Relative position = 0
    - Relative velocity = 0

This method produces a docking-style rendezvous.

Purpose
Implements Intercept Method 1: Direct Rendezvous (co‑orbital matching)

This method attempts to bring the threat satellite to match BOTH:

• Position
• Velocity

…of the friendly satellite at a specific future time.

Core Algorithm
A classical STK Astrogator rendezvous profile:

Initial propagate – propagate threat forward by user‑selected guess time.
Maneuver (impulsive) – insert a single burn.
Target Sequence – differential corrector varies ΔV components
Result constraints – minimize relative position and velocity differences
This results in a true rendezvous, not just a close approach.
"""

from datetime import timedelta


class RendezvousPlanner:
    """
    Generates a sequence plan for a full rendezvous solution.
    """

    def __init__(self, logger):
        self.logger = logger

    # ------------------------------------------------------------------
    # MAIN PLANNING FUNCTION
    # ------------------------------------------------------------------
    def generate_plan(self, intercept_time_hours: float, target_distance_m: float = 0.0):
        """
        Creates a sequence plan for rendezvous.

        Parameters
        ----------
        intercept_time_hours : float
            Propagation duration before applying differential corrector.

        Returns
        -------
        list
            High-level sequence plan for MCSBuilder.
        """

        self.logger.log(
            f"Generating rendezvous plan for intercept time = {intercept_time_hours} hours",
            "RNDZ"
        )

        # ------------------------------------------------------------------
        # STEP 1: Propagate forward to intercept time
        # ------------------------------------------------------------------
        plan = [
            {
                "type": "propagate",
                "name": "Coast_To_Intercept",
                "duration": intercept_time_hours * 3600.0  # convert hours → seconds
            }
        ]

        # ------------------------------------------------------------------
        # STEP 2: Insert a manoeuvre (impulsive burn)
        # ------------------------------------------------------------------
        plan.append(
            {
                "type": "maneuver",
                "name": "Rendezvous_Burn",
                "delta_v": [0, 0, 0]  # Differential Corrector will adjust
            }
        )

        # ------------------------------------------------------------------
        # STEP 3: Target Sequence (Differential Corrector)
        # ------------------------------------------------------------------
        plan.append(
            {
                "type": "target",
                "name": "Rendezvous_DC",
                "controls": [
                    {"type": "dvx", "segment_name": "Rendezvous_Burn"},
                    {"type": "dvy", "segment_name": "Rendezvous_Burn"},
                    {"type": "dvz", "segment_name": "Rendezvous_Burn"}
                ],
                "results": [
                    # Match relative position (R — user-configurable miss distance)
                    {"type": "R", "target_value": target_distance_m, "tolerance": 1.0e-3},
                    # Match relative velocity (V vector)
                    {"type": "V", "target_value": 0.0, "tolerance": 1.0e-4}
                ],
                "constraints": []
            }
        )

        return plan
