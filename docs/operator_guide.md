# SIPC Operator Guide

## Getting Started

### Launching SIPC

**From a terminal (dev mode):**
```powershell
.venv\Scripts\Activate.ps1
sipc
```

**From a packaged EXE:**
```
dist\sipc.exe
```

Ensure STK 13 is open with a scenario loaded before launching SIPC if you
intend to execute live planning runs.

---

## Workflow

### 1. Define Assets

Open the **Assets** tab.

- **Blue Assets** — friendly interceptor satellites
  - Click **Add** and enter the asset name and TLE
  - Asset will appear in STK as `B_SAT_<name>` under the `/Blue` folder
- **Red Tracks** — threat satellite tracks
  - Click **Add** and enter the track name and TLE
  - Track will appear in STK as `R_SAT_<name>` under the `/Red` folder

TLE format: paste both lines (line 1 and line 2) separated by a newline.

### 2. Configure a Run

Open the **Intercept Planning** tab.

| Field | Description |
|-------|-------------|
| Operator | Your callsign or username (recorded in provenance log) |
| Data Source | Tag identifying the source of your TLE data (e.g. `SPADOC`, `MANUAL`) |
| Scenario Path | Full path to the STK `.sc` file, or leave blank to attach to the open scenario |

### 3. Run the Plan

Click **Run Plan**. SIPC will:
1. Create/update satellite objects in STK
2. Compute access for all blue/red pairs
3. Display candidate intercept windows in the results table

The **Run Log** tab shows a live provenance trail of all actions taken.

### 4. Review Results

The results table shows:
- **Start / End (UTC)** — window boundaries
- **Duration (s)** — window length
- **Min Range (km)** — closest approach during the window (once implemented)

---

## Naming Conventions

All STK objects created by SIPC follow these prefixes:

| Prefix | Type |
|--------|------|
| `B_SAT_` | Blue (friendly) satellite |
| `R_SAT_` | Red (threat) satellite |
| `CALC_` | Computed/derived objects |
| `OUT_<RunID>_` | Output data objects for a specific run |

---

## Time and Units

- All times are **UTC**
- Distances in **km**
- Speeds in **m/s**
- Angles in **degrees**
- Coordinate frame: **ICRF/J2000**

---

## Log Files

Per-run log files are written to the `logs/` directory as JSON-lines:

```
logs/RUN_<id>.jsonl
```

Each line is a structured JSON record with `run_id`, `timestamp`, `level`,
`logger`, and `event` fields. These can be ingested into any JSON-aware log
viewer or parsed with `jq`.

---

## Troubleshooting

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| "Not connected to STK" error | STK not running or scenario not loaded | Start STK 13 and open a scenario |
| Empty results table | No access between any pair in the time window | Extend scenario time window or check TLEs |
| Application won't start | PySide6 not installed | Run `pip install -e ".[dev]"` |
| COM error on connect | pywin32 not registered | Run `python -m win32com.client.makepy` |
