# Intercept Engine

The `sipc/intercept_engine/` package provides four orbit-mechanics algorithms for computing
intercept trajectories.  Each algorithm generates a **dict-based sequence plan** that is
translated into an STK Astrogator Mission Control Sequence (MCS) by `MCSBuilder`.

---

## Algorithms

### Lambert (`LambertPlanner`)
Classic two-impulse Lambert's problem solver.

| Step | Type | Description |
|------|------|-------------|
| 1 | `propagate` | Coast from current epoch to burn epoch (`coast_hours`) |
| 2 | `maneuver` | Intercept burn (DC solves ΔV) |
| 3 | `propagate` | Coast from burn to intercept (`intercept_hours`) |
| 4 | `target` | DC constraint: Range to blue = 0 km |

```python
plan = LambertPlanner(logger).generate_plan(coast_hours=1.0, intercept_hours=6.0)
```

### Rendezvous (`RendezvousPlanner`)
Close approach with matching velocity — used when the red satellite must station-keep near blue.

| Step | Type | Description |
|------|------|-------------|
| 1 | `propagate` | Coast to burn epoch |
| 2 | `maneuver` | Intercept burn |
| 3 | `target` | DC constraints: Range = 0 km **and** Relative Velocity = 0 km/s |

```python
plan = RendezvousPlanner(logger).generate_plan(coast_hours=1.0)
```

### Proximity (`ProximityInterceptPlanner`)
Fly to a specified stand-off distance (e.g. 1000 m) rather than zero range.

| Step | Type | Description |
|------|------|-------------|
| 1 | `propagate` | Coast to burn epoch |
| 2 | `maneuver` | Intercept burn |
| 3 | `target` | DC constraint: Range = `target_distance_m` (converted to km for STK) |

```python
plan = ProximityInterceptPlanner(logger).generate_plan(coast_hours=1.0, target_distance_m=1000.0)
```

### Optimal (`OptimalInterceptPlanner`)
Fuel-optimal multi-burn solution via Astrogator Optimizer.

| Step | Type | Description |
|------|------|-------------|
| 1 | `propagate` | Initial coast |
| 2–N+1 | `maneuver` | N impulsive burns (DC/Optimizer controls all ΔV components) |
| N+2 | `propagate` | Post-burn coast to intercept epoch |
| N+3 | `target` | Optimizer: minimise total ΔV subject to Range ≤ `target_distance_m` |

```python
plan = OptimalInterceptPlanner(logger).generate_plan(
    initial_coast_hours=1.0,
    intercept_time_hours=6.0,
    number_of_burns=2,
    target_distance_m=0.0,
    minimize_delta_v=True,
)
```

---

## Dict Plan Format

Each planner returns a `list[dict]` where each dict has a `"type"` key:

```python
# propagate step
{"type": "propagate", "name": "Coast", "duration": 3600.0}  # duration in seconds

# maneuver step
{"type": "maneuver", "name": "Intercept Burn"}

# target step (last in plan)
{
    "type": "target",
    "name": "Target Intercept",
    "controls": ["dvx", "dvy", "dvz"],   # components to control (per burn)
    "results": [
        {"name": "R", "target_value": 0.0},        # range in metres
        {"name": "V", "target_value": 0.0},        # rel velocity in km/s
        {"name": "MinimizeFuel"},                   # Optimizer cost (Optimal only)
    ],
}
```

---

## MCSBuilder Translation

`MCSBuilder.build(mcs, plan, blue_sat_path, max_dv_km_s)` in `sipc/stk_adapter/mcs_builder.py`
translates the dict plan into STK COM calls:

1. Separate the `target` step from inner steps.
2. Insert a **Target Sequence** segment into the MCS.
3. Insert all `propagate` and `maneuver` steps **inside** the Target Sequence (the DC needs
   to observe their final states).
4. Add a **Differential Corrector** or **Optimizer** profile depending on whether a
   `MinimizeFuel` result is present.
5. Map controls to Cartesian ΔV paths: `"{seg_name}.ImpulsiveMnvr.Cartesian.X/Y/Z"`.
6. Map results to Range / RelativeVelocity data providers on `blue_sat_path`.

---

## Integration with STK Adapter

### Search flow (`compute_maneuver_options`)
If `ManeuverSearchConfig.intercept_methods` is non-empty, `StkComSession` runs
`_solve_via_intercept_engine` for each method after the standard burn-location loop.
Results appear in the same sorted table.  SGP4 is always restored.

### Direct apply flow (`apply_intercept_plan`)
`POST /plan/maneuver/apply-intercept` → `StkComSession.apply_intercept_plan(config: InterceptConfig)`:
1. Build targeting MCS → run DC/Optimizer → extract solved ΔV.
2. Build fixed MCS encoding the solved burn as literal ΔV values → propagate.
3. Red satellite remains on Astrogator in STK (permanently moved).
4. Returns `ManeuverOption` stored in `state.selected_maneuver`.

This is the **recommended operator workflow** when timing parameters are known in advance.
Use the "Generate Options" search flow only when exploring burn locations.

---

## UI — Intercept Engine Panel

Located in the operator console below the Maneuver Search section.

| Input | Description |
|-------|-------------|
| Red satellite | Aggressor satellite (Astrogator will be applied to this object) |
| Blue satellite | Target satellite (DC/Optimizer targets range to this object) |
| Algorithm | Lambert / Rendezvous / Proximity / Optimal |
| Manoeuvre start | UTC epoch for Initial State; blank = use scenario epoch |
| Coast hours | Duration from manoeuvre start to burn epoch |
| Intercept TOF | Coast duration after burn (Lambert, Optimal only) |
| Target distance (m) | Stand-off range for Proximity / Optimal |
| Burns | Number of impulses (Optimal only) |
| Max ΔV (km/s) | Upper bound on total ΔV; result discarded if exceeded |
| Minimise ΔV | Use Optimizer instead of DC (Optimal only) |

The `ieUpdate()` JavaScript function hides irrelevant inputs for the selected algorithm.

---

## Logger Compatibility

The four planner classes use `.log(msg: str, tag: str = "")` instead of the standard Python
logging API. `_EngineLogger` in `com_session.py` bridges them:

```python
class _EngineLogger:
    def __init__(self, py_logger: logging.Logger) -> None:
        self._log = py_logger
    def log(self, msg: str, tag: str = "") -> None:
        self._log.debug("[%s] %s", tag, msg)
```

Pass `_EngineLogger(logger)` when instantiating any planner.
