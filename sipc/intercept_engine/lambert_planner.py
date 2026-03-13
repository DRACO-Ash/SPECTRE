"""
lambert_planner.py
Intercept Method 3: Lambert Transfer Intercept.

Design Philosophy:
------------------
This planner implements a classical Lambert-style intercept using the
Astrogator differential corrector. It does NOT attempt to solve the
Lambert problem mathematically in Python; instead, it constructs an
STK Astrogator MCS with:

1) Initial propagate (coast)
2) Impulsive burn (DVx, DVy, DVz)
3) Propagate to intercept time
4) Target Sequence minimizing |R| (position match)

The DC adjusts the burn ΔV to satisfy the "Lambert-like" constraint.

Purpose
Implements Intercept Method 3: Lambert Targeting
A Lambert solver computes the required velocity change to move a spacecraft from:

• initial position r₁
to
• final position r₂
in a fixed time of flight Δt

This produces one or two impulsive burns, depending on method chosen.

In STK Astrogator, we mimic a Lambert transfer using a Target Sequence with:

Initial propagation
A manoeuvre with controllable ΔV
A propagation to final time
A targeter solving for R (position match)
Design Notes
• This module does NOT compute Lambert solutions manually.
• Instead, it sets up the DC (differential corrector) so Astrogator computes the intercept solution.
• Users can choose transfer time in hours.
"""


class LambertPlanner:
    """
    Creates high-level MCS sequence plans for Lambert-style interception.
    """

    def __init__(self, logger):
        self.logger = logger

    # ------------------------------------------------------------------
    # MAIN PLANNING FUNCTION
    # ------------------------------------------------------------------
    def generate_plan(self, coast_hours: float, intercept_hours: float, target_distance_m: float = 0.0):
        """
        Generates a Lambert transfer encounter MCS plan.

        Parameters
        ----------
        coast_hours : float
            Pre-burn coast time.
        intercept_hours : float
            Total time of flight to intercept target after burn.

        Returns
        -------
        list
            Sequence plan for MCSBuilder.
        """

        self.logger.log(
            f"Generating Lambert intercept plan: coast={coast_hours} hr, TOF={intercept_hours} hr",
            "LAMBERT"
        )

        # --------------------------------------------------------------
        # STEP 1: Pre-burn coast phase
        # --------------------------------------------------------------
        plan = [
            {
                "type": "propagate",
                "name": "Lambert_PreBurn_Coast",
                "duration": coast_hours * 3600.0
            }
        ]

        # --------------------------------------------------------------
        # STEP 2: Impulsive burn (Delta-V solved by DC)
        # --------------------------------------------------------------
        plan.append(
            {
                "type": "maneuver",
                "name": "Lambert_Burn",
                "delta_v": [0, 0, 0]  # Controlled by differential corrector
            }
        )

        # --------------------------------------------------------------
        # STEP 3: Post-burn coast to intercept time
        # --------------------------------------------------------------
        plan.append(
            {
                "type": "propagate",
                "name": "Lambert_PostBurn_Coast",
                "duration": intercept_hours * 3600.0
            }
        )

        # --------------------------------------------------------------
        # STEP 4: Target Sequence (Lambert-like solver)
        # --------------------------------------------------------------
        plan.append(
            {
                "type": "target",
                "name": "Lambert_DC",

                # Controls: DV components on Lambert_Burn
                "controls": [
                    {"type": "dvx", "segment_name": "Lambert_Burn"},
                    {"type": "dvy", "segment_name": "Lambert_Burn"},
                    {"type": "dvz", "segment_name": "Lambert_Burn"}
                ],

                # Result: match R at intercept point (user-configurable miss distance)
                "results": [
                    {
                        "type": "R",
                        "target_value": target_distance_m,
                        "tolerance": 1.0  # 1 meter match tolerance
                    }
                ],

                "constraints": []
            }
        )

        return plan
