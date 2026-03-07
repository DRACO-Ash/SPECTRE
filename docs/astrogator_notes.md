# STK Astrogator COM Notes

Reference for implementing `StkComSession.compute_maneuver_options` and
`StkComSession.apply_maneuver` against the STK 13 Astrogator Object Model.

---

## Prerequisites

Astrogator is a licensed STK module.  Confirm availability before attempting
any of the operations below:

```python
# At connect time — check whether Astrogator is licensed
try:
    result = root.ExecuteCommand("GetLicensedModules")
    licensed = result.Item(0) if result.IsSucceeded and result.Count > 0 else ""
    astrogator_available = "Astrogator" in licensed
except Exception:
    astrogator_available = False  # Connect layer blocked; assume licensed, fail gracefully at use
```

Surface `astrogator_available` in `SessionState` so the UI panel can be
disabled with a clear message when the licence is absent.

---

## Setting the Astrogator Propagator

```python
# AgEVePropagatorType enum — CONFIRMED values from STK 13 gen_py stubs
# (AB621A84-81D2-45BF-9236-112CF72743D7x0x1x0.py, verified 2026-03-07)
#
#   HPOP=0  J2=1  J4=2  LOP=3  SGP4=4  SPICE=5  StkExternal=6  TwoBody=7
#   GreatArc=9  Ballistic=10  SimpleAscent=11  Astrogator=12
#   Realtime=13  GPS=14  Aviator=15  SP3=17
#
# NOTE: these constants appear in the stubs as tab-indented comments, NOT as
# importable module attributes, so getattr(mod, "ePropagatorAstrogator") returns
# None.  The confirmed literal 12 is used as the fallback in _astrogator_enum_value().
_E_PROPAGATOR_ASTROGATOR = 12  # CONFIRMED STK 13

sat_obj = root.GetObjectFromPath("Satellite/R_SAT_TrackA")
sat_obj.SetPropagatorType(_E_PROPAGATOR_ASTROGATOR)
prop = sat_obj.Propagator  # IAgVePropagatorAstrogator
```

To verify the enum value at runtime:
```python
from win32com.client import gencache
mod = gencache.EnsureModule("{AB621A84-81D2-45BF-9236-112CF72743D7}", 0, 1, 0)
# Inspect mod for AgEVePropagatorType enum members
```

---

## Mission Control Sequence (MCS) structure

```python
mcs = prop.MainSequence  # IAgVAMCSSegmentCollection

# Segment type enum: AgEVASegmentType
# Values must be confirmed from gen_py stubs.  Common values:
#   eVASegmentTypeInitialState    = 0
#   eVASegmentTypePropagate       = 1
#   eVASegmentTypeManeuver        = 2
#   eVASegmentTypeTargetSequence  = 3
#   eVASegmentTypeSequence        = 4

# Insert returns the new segment object
init_state = mcs.Insert(eVASegmentTypeInitialState, "Initial State", "-")
coast      = mcs.Insert(eVASegmentTypePropagate,    "Coast to Burn", "-")
burn       = mcs.Insert(eVASegmentTypeManeuver,     "Intercept Burn", "-")
post_burn  = mcs.Insert(eVASegmentTypePropagate,    "Coast to Intercept", "-")
```

The third argument to `Insert` is the name of the segment **before** which to
insert (`"-"` appends to the end of the sequence).

---

## Initial State segment

```python
# Set epoch and Cartesian state from existing TLE propagator data
init = init_state  # IAgVAInitialState
init.SetElementType(eVAElementTypeCartesian)   # or Keplerian
init.Epoch = "6 Mar 2026 00:00:00.000"         # STK UTCG format

# Keplerian is easier when deriving from TLE
init.SetElementType(eVAElementTypeKeplerian)
elements = init.Element  # IAgVAKeplerianElements
elements.SemiMajorAxis = 6778.0   # km
elements.Eccentricity  = 0.0001
elements.Inclination   = 51.6     # deg
elements.RAAN          = 45.0     # deg
elements.ArgOfPeriapsis = 0.0     # deg
elements.TrueAnomaly   = 120.0    # deg
```

---

## Propagate segment — stop conditions

```python
coast_seg = coast  # IAgVAPropagateSegment
# Stop at a specific duration
stop_coll = coast_seg.StoppingConditions
dur_stop = stop_coll.Add("Duration")
dur_stop.Properties.Trip = 3600.0   # seconds

# OR stop at a specific epoch
epoch_stop = stop_coll.Add("Epoch")
epoch_stop.Properties.Trip = "6 Mar 2026 01:30:00.000"

# OR stop at apogee / perigee / ascending node
apogee_stop = stop_coll.Add("Apoapsis")
```

---

## Maneuver segment — impulsive burn

```python
burn_seg = burn  # IAgVAManeuverSegment
burn_seg.SetManeuverType(eVAManeuverTypeImpulsive)
impulsive = burn_seg.Maneuver  # IAgVAImpulsiveBurn

# Attitude control / frame
impulsive.SetAttitudeControlType(eVAAttitudeControlThrustVector)
thrust_vec = impulsive.AttitudeControl  # IAgVAThrustVector

# Set delta-V components in VNC frame (Velocity-Normal-Co-normal)
thrust_vec.ThrustAxesType = eVAThrustAxesVNC
thrust_vec.DeltaV.AssignCartesian(dv_v, dv_n, dv_c)  # km/s
```

For **finite burns**:
```python
burn_seg.SetManeuverType(eVAManeuverTypeFinite)
finite = burn_seg.Maneuver  # IAgVAFiniteBurn
finite.SetAttitudeControlType(eVAAttitudeControlThrustVector)
# Set engine model, thrust, Isp, duration...
```

---

## Target Sequence — differential corrector

```python
# Replace the post-burn propagate with a TargetSequence for solving
target_seq = mcs.Insert(eVASegmentTypeTargetSequence, "Target Intercept", "-")
ts = target_seq  # IAgVATargetSequence

# Add the differential corrector profile
dc = ts.Profiles.Add("Differential Corrector")
dc_props = dc.Properties  # IAgVADCProperties
dc_props.MaxIterations    = 50
dc_props.TargetingMode    = eVADCTargetingModeCoast  # or eVADCTargetingModeSolve

# Control variable: burn delta-V magnitude
control = dc.ControlParameters.Add("Impulsive Burn.BurnDirection.DeltaV")
control.Enable = True
control.Min    = 0.0
control.Max    = 3.0   # km/s cap

# Constraint: range to blue satellite at intercept epoch
constraint = dc.Results.Add("Range")  # or a custom chain result
constraint.Enable    = True
constraint.DesiredValue = 0.0    # km — want zero miss distance
constraint.Tolerance    = 0.5   # km — accept solutions within 0.5 km
```

---

## Running the MCS and extracting results

```python
prop.Propagate()

# After propagation, read back the solved values
solved_dv    = burn_seg.Maneuver.AttitudeControl.DeltaV.X   # prograde
solved_epoch = coast_seg.FinalState.Epoch                   # burn time
final_state  = post_burn_seg.FinalState                     # IAgVAFinalState
# Range to blue satellite at final state must be queried via access/data provider
```

---

## State preservation pattern

Always restore the red satellite to SGP4 after a maneuver search, even on error:

```python
_E_PROPAGATOR_SGP4 = 4

original_tle = (line1, line2)
try:
    sat_obj.SetPropagatorType(_E_PROPAGATOR_ASTROGATOR)
    # ... build MCS, run, extract results ...
finally:
    sat_obj.SetPropagatorType(_E_PROPAGATOR_SGP4)
    propagator = sat_obj.Propagator
    propagator.CommonTasks.AddSegsFromFile(satno, tle_path)
    propagator.Propagate()
```

---

## Known risks and workarounds

| Issue | Workaround |
|-------|-----------|
| `ePropagatorAstrogator` enum value | **Confirmed = 12** (STK 13, verified 2026-03-07 from gen_py stubs). Stubs define it as a tab-indented comment, not a module attribute, so `getattr(mod, "ePropagatorAstrogator")` returns None — the hardcoded fallback of 12 is correct. |
| ODTK may block `prop.Propagate()` | Test on live system; fall back to `ExecuteCommand("Astrogator Run …")` if OM call fails (unlikely) |
| Differential corrector non-convergence | Catch COM exception from `prop.Propagate()`; log at DEBUG; skip this candidate |
| Segment type enum values | Confirm all `eVASegmentType*` and `eVAManeuverType*` values from gen_py stubs before use |
| Astrogator licence absent | Gate the entire flow on `astrogator_available`; surface human-readable error in UI |
