"""
proximity_intercept.py
Intercept Method 2: Terminal Proximity Intercept (distance minimization).

Design Philosophy:
------------------
This planner is suitable for non-docking interception, where the goal
is simply to minimize relative position distance at a specified time.

Unlike rendezvous, velocity matching is NOT required.

Sequence plan includes:
• Initial propagation to target time
• One impulsive ΔV manoeuvre
• Differential corrector attempting to minimize R vector magnitude

Purpose
Implements Intercept Method 2: Terminal Proximity Intercept
(closest approach without matching velocity)

This is not a rendezvous — it finds a manoeuvre that minimizes distance between the threat and friendly satellites at a specified terminal time.

Core Algorithm
Propagate threat forward to a user‑defined intercept window.
Apply an impulsive burn with ΔV as a control parameter.
Use a Target Sequence with result constraints:
• Minimize R magnitude (relative position vector)
User can specify a target miss distance (e.g., 0.1 km).
This is a simpler problem than rendezvous, appropriate for kinetic or proximity operations.
"""


class ProximityInterceptPlanner:
    """
    Creates high-level sequence plans for terminal proximity interception.
    """

    def __init__(self, logger):
        self.logger = logger

    # ------------------------------------------------------------------
    # MAIN PLANNING FUNCTION
    # ------------------------------------------------------------------
    def generate_plan(self, intercept_time_hours: float, target_distance_m: float):
        """
        Constructs a proximity intercept plan.

        Parameters
        ----------
        intercept_time_hours : float
            Time to propagate before evaluating intercept.
        target_distance_m : float
            Desired closest-approach distance (meters).

        Returns
        -------
        list
            Sequence plan for MCSBuilder.
        """

        self.logger.log(
            f"Generating proximity intercept plan: intercept={intercept_time_hours} hours, "
            f"target distance={target_distance_m} m",
            "PROX"
        )

        plan = []

        # --------------------------------------------------------------
        # STEP 1: Propagate to the intercept time
        # --------------------------------------------------------------
        plan.append(
            {
                "type": "propagate",
                "name": "Coast_To_Proximity_Time",
                "duration": intercept_time_hours * 3600.0
            }
        )

        # --------------------------------------------------------------
        # STEP 2: Single impulsive burn
        # --------------------------------------------------------------
        plan.append(
            {
                "type": "maneuver",
                "name": "Proximity_Burn",
                "delta_v": [0, 0, 0]  # DC will adjust
            }
        )

        # --------------------------------------------------------------
        # STEP 3: Target Sequence
        # Attempts to reduce |R| to target_distance_m
        # --------------------------------------------------------------
        plan.append(
            {
                "type": "target",
                "name": "Proximity_DC",
                "controls": [
                    {"type": "dvx", "segment_name": "Proximity_Burn"},
                    {"type": "dvy", "segment_name": "Proximity_Burn"},
                    {"type": "dvz", "segment_name": "Proximity_Burn"}
                ],
                "results": [
                    # Minimize relative position difference
                    {
                        "type": "R",
                        "target_value": target_distance_m,
                        "tolerance": 1.0  # 1 meter tolerance
                    }
                ],
                "constraints": []
            }
        )

        return plan
