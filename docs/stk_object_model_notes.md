# STK Object Model Notes

Reference notes for implementing `StkComSession` against the STK 13 COM API.

## COM Dispatch Entry Point

```python
import win32com.client
app = win32com.client.Dispatch("STK13.Application")
app.Visible = True
root = app.Personality2  # IAgStkObjectRoot
```

## Scenario Operations

```python
# Load a scenario
root.LoadScenario(r"C:\path\to\scenario.sc")

# Get scenario epoch
scenario = root.CurrentScenario
start_time = scenario.StartTime  # Returns STK time string e.g. "1 Jan 2026 00:00:00.000"
stop_time = scenario.StopTime
```

## Creating a Satellite

```python
from win32com.client import constants as c

satellites = root.Children  # IAgStkObjectElementCollection
sat = satellites.New(c.eSatellite, "B_SAT_Alpha")  # Returns IAgSatellite
```

## Moving Objects to Folders

STK uses a folder/group concept. Objects can be moved after creation:

```python
# Folders must be created first if they don't exist
# root.Children.NewFolder("Blue")
sat.InstanceName  # verify name
```

## TLE Propagator

```python
from win32com.client import constants as c

sat.SetPropagatorType(c.ePropagatorStkExternal)
prop = sat.Propagator  # IAgVePropagatorStkExternal
prop.Step = 10  # seconds

# Load TLE
tle_data = prop.TLE
tle_data.Line1 = "1 25544U ..."
tle_data.Line2 = "2 25544 ..."
prop.Propagate()
```

## Access Computation

```python
# obj_a and obj_b are full STK paths e.g. "Satellite/B_SAT_Alpha"
access = root.GetAccessBetween(obj_a, obj_b)  # IAgAccess
access.ComputeAccess()

# Get intervals
intervals = access.AccessIntervals  # IAgAccessIntervalCollection
for i in range(intervals.Count):
    interval = intervals.Item(i)
    print(interval.StartTime, interval.StopTime)
```

## Time String Parsing

STK uses its own time format. Convert to Python datetime:

```python
from datetime import datetime, timezone

def parse_stk_time(stk_time_str: str) -> datetime:
    """Parse STK time string to UTC datetime.

    STK format: "1 Jan 2026 00:00:00.000"
    """
    return datetime.strptime(stk_time_str, "%d %b %Y %H:%M:%S.%f").replace(
        tzinfo=timezone.utc
    )
```

## Connect Commands (alternative to COM object model)

STK also supports text-based Connect commands via `root.ExecuteCommand(cmd)`:

```
New / Scenario ScenarioName
New / Satellite B_SAT_Alpha
SetState */Satellite/B_SAT_Alpha TLE "Line 1" "Line 2"
Access */Satellite/B_SAT_Alpha */Satellite/R_SAT_Track01
```

Connect commands can be easier for batch operations but COM gives more
structured return values. Prefer COM for access intervals.

## Error Handling

COM errors surface as `pywintypes.com_error`. Wrap all COM calls:

```python
import pywintypes

try:
    result = root.Children.New(constants.eSatellite, name)
except pywintypes.com_error as exc:
    raise StkCommandError(f"Failed to create {name}: {exc}") from exc
```

## STK 13 Type Library

To generate early-bound COM constants and get autocomplete:

```powershell
python -m win32com.client.makepy "STK13.Application"
```

This generates a `.py` file in `win32com/gen_py/` that can be used instead
of `win32com.client.constants`.

## Object Path Conventions

STK object paths use the form `<Type>/<Name>`:
- `Satellite/B_SAT_Alpha`
- `Facility/GroundStation01`
- `Sensor/Radar01`

When calling access methods, always use the full path.
