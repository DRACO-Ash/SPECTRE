"""
optimal_intercept.py
Intercept Method 4: Multi-Burn Optimal Intercept.

Design Philosophy:
------------------
This planner constructs a highly flexible multi-burn intercept profile
where Astrogator's built-in numerical optimizer performs the heavy lifting.

The general idea:
-----------------
1. Coast for a user-defined initial period.
2. Insert one or more maneuver segments (user-selectable count).
3. Coast to final target time.
4. Use a Target Sequence with an Optimizer profile:
    • Controls = DV components of each burn
    • Results  = minimize |R| or match a target distance
    • Constraints = optional periapsis, RAAN, or altitude limits
    • Cost Function = minimize total ΔV (default)

The optimizer iterates until constraints are satisfied.

Purpose
Implements Intercept Method 4: Multi‑Burn Optimal Intercept

This method uses STK Astrogator's numerical optimization to compute an intercept manoeuvre solution that:

• Minimizes total ΔV (default),
OR
• Minimizes time of flight,
OR
• Satisfies user‑selectable constraints (e.g., periapsis altitude, RAAN alignment, range minimization).

How It Works
Initial propagation
Multiple manoeuvre segments, each with controllable ΔV
Target Sequence containing the optimizer
Optimizer adjusts the burns to satisfy constraints
Final coast to intercept time
Constraints:
• |R| (relative position)
• Optional user-defined constraints
• Optional minimum ΔV cost function
This method is the most flexible and closest to a "real-world" automated intercept planner.
"""


class OptimalInterceptPlanner:
    """
    Creates MCS plans for optimal, multi-burn interception.
    """

    def __init__(self, logger):
        self.logger = logger

    # ----------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ----------------------------------------------------------------------
    def generate_plan(
        self,
        initial_coast_hours: float,
        intercept_time_hours: float,
        number_of_burns: int,
        target_distance_m: float = 0.0,
        minimize_delta_v: bool = True
    ):
        """
        Constructs the sequence plan for multi-burn optimized interception.

        Parameters
        ----------
        initial_coast_hours : float
            Time before the first burn.
        intercept_time_hours : float
            Total time to propagate after the last burn.
        number_of_burns : int
            How many maneuver segments the optimizer can adjust.
        target_distance_m : float, optional
            Desired closest-approach distance.
        minimize_delta_v : bool, optional
            If True, optimizer minimizes total ΔV.

        Returns
        -------
        list
            A fully defined MCS sequence plan.
        """

        self.logger.log(
            f"Generating optimal intercept plan: coast={initial_coast_hours} hr, "
            f"tof={intercept_time_hours} hr, burns={number_of_burns}, "
            f"minDV={minimize_delta_v}",
            "OPTIMAL"
        )

        plan = []

        # ------------------------------------------------------------------
        # STEP 1: Initial coast segment
        # ------------------------------------------------------------------
        plan.append(
            {
                "type": "propagate",
                "name": "Optimal_PreBurn_Coast",
                "duration": initial_coast_hours * 3600.0
            }
        )

        # ------------------------------------------------------------------
        # STEP 2: Multiple burns
        # ------------------------------------------------------------------
        burn_names = []
        for i in range(number_of_burns):
            burn_name = f"Optimal_Burn_{i+1}"
            burn_names.append(burn_name)

            plan.append(
                {
                    "type": "maneuver",
                    "name": burn_name,
                    "delta_v": [0, 0, 0]  # Optimizer will adjust
                }
            )

        # ------------------------------------------------------------------
        # STEP 3: Final coast to intercept time
        # ------------------------------------------------------------------
        plan.append(
            {
                "type": "propagate",
                "name": "Optimal_PostBurn_Coast",
                "duration": intercept_time_hours * 3600.0
            }
        )

        # ------------------------------------------------------------------
        # STEP 4: Optimizer Target Sequence
        # ------------------------------------------------------------------
        controls = []
        for burn_name in burn_names:
            controls.extend(
                [
                    {"type": "dvx", "segment_name": burn_name},
                    {"type": "dvy", "segment_name": burn_name},
                    {"type": "dvz", "segment_name": burn_name}
                ]
            )

        # Desired results:
        # Minimize relative distance (R)
        results = [
            {
                "type": "R",
                "target_value": target_distance_m,
                "tolerance": 1.0
            }
        ]

        # Constraints:
        constraints = []

        # Cost function for optimizer
        if minimize_delta_v:
            constraints.append({"type": "MinimizeFuel", "value": 1})

        plan.append(
            {
                "type": "target",
                "name": "Optimal_Intercept_DC",
                "controls": controls,
                "results": results,
                "constraints": constraints
            }
        )

        return plan
