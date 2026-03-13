"""MCSBuilder — translates intercept engine dict plans into Astrogator COM segments."""

from __future__ import annotations

import logging
from typing import Any

from sipc.domain.models import BurnType

logger = logging.getLogger(__name__)

# Astrogator segment type integers (AgEVASegmentType enum values in STK 13).
# Confirmed from gen_py stubs for {13C9EAB7-AEAF-43E3-AD94-93C2D6476CB2}.
_SEG_INITIAL_STATE   = 0   # eVASegmentTypeInitialState
_SEG_PROPAGATE       = 5   # eVASegmentTypePropagate
_SEG_MANEUVER        = 2   # eVASegmentTypeManeuver
_SEG_TARGET_SEQUENCE = 8   # eVASegmentTypeTargetSequence

# Burn / attitude control constants.
_MANEUVER_IMPULSIVE     = 0  # eVAManeuverTypeImpulsive
_ATTITUDE_THRUST_VECTOR = 4  # eVAAttitudeControlThrustVector


def _configure_maneuver_seg(burn_seg: Any) -> None:
    """Set burn segment to impulsive VNC with zero initial ΔV."""
    try:
        burn_seg.SetManeuverType(_MANEUVER_IMPULSIVE)
        maneuver = burn_seg.Maneuver
        maneuver.SetAttitudeControlType(_ATTITUDE_THRUST_VECTOR)
        atc = maneuver.AttitudeControl
        atc.ThrustAxesName = "VNC"
    except Exception as exc:
        logger.debug("_configure_maneuver_seg partial failure (%s); proceeding with defaults", exc)


class MCSBuilder:
    """Translates an intercept engine dict sequence plan into STK Astrogator MCS segments.

    The plan is a list of dicts produced by one of the intercept engine planner
    classes (``LambertPlanner``, ``RendezvousPlanner``, etc.).  The final entry
    must be a ``"target"`` dict — all preceding entries are segments inserted
    inside the Target Sequence so the DC/Optimizer can control them.

    Typical call:

    .. code-block:: python

        mcs.RemoveAll()
        init = mcs.Insert(_SEG_INITIAL_STATE, "Initial State", "-")
        init.Epoch = _to_stk_time(epoch)
        MCSBuilder().build(mcs, plan, "*/Satellite/B_SAT_Alpha", max_dv_km_s=3.0)
        prop.Propagate()
    """

    def build(
        self,
        mcs: Any,
        plan: list[dict],
        blue_sat_path: str,
        max_dv_km_s: float = 3.0,
    ) -> None:
        """Insert Astrogator segments from *plan* into *mcs*.

        All ``"propagate"`` and ``"maneuver"`` steps are placed inside the
        Target Sequence so the DC/Optimizer can observe and control them.

        Args:
            mcs: Astrogator ``MainSequence`` object (Initial State already inserted).
            plan: Sequence plan from an intercept engine ``generate_plan()`` call.
            blue_sat_path: Full STK path to the blue target satellite
                (e.g. ``"*/Satellite/B_SAT_Alpha"``).
            max_dv_km_s: ΔV bound applied symmetrically to each Cartesian control
                parameter (km/s).
        """
        # Separate the target step (last, defines DC/Optimizer) from inner steps.
        target_step: dict | None = None
        inner_steps: list[dict] = []
        for step in plan:
            if step["type"] == "target":
                target_step = step
            else:
                inner_steps.append(step)

        if target_step is None:
            # No targeting — insert raw segments directly into the main sequence.
            for step in inner_steps:
                self._insert_segment(mcs, step)
            logger.debug("MCSBuilder: no target step found; inserted %d raw segments", len(inner_steps))
            return

        # Determine profile type: Optimizer if MinimizeFuel constraint present.
        use_optimizer = any(
            c.get("type") == "MinimizeFuel"
            for c in target_step.get("constraints", [])
        )

        # Create the Target Sequence.
        target_seq = mcs.Insert(_SEG_TARGET_SEQUENCE, target_step["name"], "-")

        # Insert all inner segments into the Target Sequence's inner Sequence.
        inner_seq = target_seq.Segments
        for step in inner_steps:
            self._insert_segment(inner_seq, step)

        # Add the DC or Optimizer profile.
        profile_name = "Optimizer" if use_optimizer else "Differential Corrector"
        try:
            profile = target_seq.Profiles.Add(profile_name)
        except Exception as exc:
            logger.warning("MCSBuilder: could not add %r profile: %s", profile_name, exc)
            return

        if not use_optimizer:
            try:
                profile.Properties.MaxIterations = 50
            except Exception:
                pass

        # Wire control parameters (dvx/dvy/dvz → Cartesian VNC components).
        for ctrl_def in target_step.get("controls", []):
            seg_name = ctrl_def.get("segment_name", "")
            ctrl_type = ctrl_def.get("type", "")
            axis = {"dvx": "X", "dvy": "Y", "dvz": "Z"}.get(ctrl_type)
            if axis is None:
                continue
            param_path = f"{seg_name}.ImpulsiveMnvr.Cartesian.{axis}"
            try:
                ctrl = profile.ControlParameters.Add(param_path)
                ctrl.Enable = True
                ctrl.Min = -max_dv_km_s
                ctrl.Max = max_dv_km_s
            except Exception as exc:
                logger.debug("MCSBuilder: could not add control %r: %s", param_path, exc)

        # Wire result constraints (R → Range, V → RelativeVelocity).
        for result_def in target_step.get("results", []):
            r_type = result_def.get("type", "")
            target_val = result_def.get("target_value", 0.0)
            tolerance  = result_def.get("tolerance", 1.0)
            try:
                if r_type == "R":
                    # target_value and tolerance are in metres; STK Range is in km.
                    result = profile.Results.Add(f"Range to {blue_sat_path}")
                    result.Enable = True
                    result.DesiredValue = target_val / 1000.0
                    result.Tolerance = max(tolerance / 1000.0, 0.001)  # min 1 m
                elif r_type == "V":
                    result = profile.Results.Add(f"Relative Velocity to {blue_sat_path}")
                    result.Enable = True
                    result.DesiredValue = target_val
                    result.Tolerance = max(tolerance, 1e-6)
            except Exception as exc:
                logger.debug("MCSBuilder: could not add result %r: %s", r_type, exc)

        logger.debug(
            "MCSBuilder: built %r (%s) with %d inner segments, %d controls, %d results",
            target_step["name"],
            profile_name,
            len(inner_steps),
            len(target_step.get("controls", [])),
            len(target_step.get("results", [])),
        )

    def _insert_segment(self, container: Any, step: dict) -> None:
        """Insert a single propagate or maneuver segment into *container*."""
        seg_type = step.get("type")
        name = step.get("name", "Segment")

        if seg_type == "propagate":
            duration_s = float(step.get("duration", 0.0))
            seg = container.Insert(_SEG_PROPAGATE, name, "-")
            try:
                stop_coll = seg.StoppingConditions
                stop_coll.RemoveAll()
                dur_stop = stop_coll.Add("Duration")
                dur_stop.Properties.Trip = duration_s
            except Exception as exc:
                logger.debug("MCSBuilder: could not set Duration stop on %r: %s", name, exc)

        elif seg_type == "maneuver":
            seg = container.Insert(_SEG_MANEUVER, name, "-")
            _configure_maneuver_seg(seg)

        else:
            logger.debug("MCSBuilder: unknown step type %r — skipping", seg_type)
