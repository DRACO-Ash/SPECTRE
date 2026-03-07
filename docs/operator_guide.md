# SIPC Operator Guide

## Getting Started

### Launching SIPC

**From a terminal (dev mode):**
```powershell
.venv\Scripts\Activate.ps1
sipc-serve
# or equivalently:
uvicorn sipc.web.app:app --reload
```

Then open **http://localhost:8000** in your browser and sign in.

**From Docker:**
```bash
docker run -d -p 8000:8000 \
  -e SECRET_KEY="change-me" \
  -e SIPC_ADMIN_USER="admin" \
  -e SIPC_ADMIN_PASS="change-me" \
  sipc:latest
```

> STK 13 must be running on the **same Windows host** as SIPC for live COM automation.
> On Linux/Docker, SIPC falls back to `FakeStkSession` (no live STK data).

---

## Workflow

### 1. Sign In

Navigate to `http://localhost:8000`. Enter your operator credentials on the login page.
On first run, the admin account is bootstrapped from the `SIPC_ADMIN_USER` / `SIPC_ADMIN_PASS`
environment variables.

---

### 2. Connect STK

Click the **STK** chip in the top navigation bar to expand the STK connection panel.

| Option | When to use |
|--------|-------------|
| **Attach** | STK 13 is already running with a scenario loaded — connect SIPC to that instance |
| **Load** | Provide the full path to a `.sc` file — SIPC will open it in STK |
| **Create** | Enter a scenario name and UTC start/stop times — SIPC creates a blank scenario |

Once connected, the STK chip turns green and the scenario name is shown.

**After an app restart** (when satellites are already in STK but session state is lost):
click **Import from Scenario** in the connected STK panel. SIPC will enumerate all
`B_SAT_*` and `R_SAT_*` objects in the active scenario and repopulate the Blue/Red
asset lists without re-adding or re-propagating the satellites.

---

### 3. Connect UDL

Click the **UDL** chip in the nav bar and enter your UDL credentials.
Credentials are held in memory only — never written to disk.

Once connected, the UDL chip turns green. The following features become available:
- TLE fetch (SATNO lookup)
- HRR watchlist (space surveillance high-interest objects)
- Orbit Catalog search

---

### 4. Define Assets

Assets are defined in the **Blue Assets** and **Red Tracks** columns.

#### Fetch TLE from UDL (recommended)

1. Enter a SATNO in the SATNO field at the top of the column.
2. Click **Fetch TLE** (blue column) or **Fetch TLE** (red column).
3. The Add Asset form opens with the TLE pre-filled and the common name pre-populated.
4. Review and click **Add Blue Asset** or **Add Red Track**.

#### Use HRR Watchlist

The **HRR Watchlist** panel (below each column) shows high-interest radar returns from UDL,
with 1→2→3 day incremental lookback. Click **→ Blue** or **→ Red** on any row to
open the Add Asset form pre-filled with that satellite's TLE and name.

#### Use Orbit Catalog Search

The **Orbit Catalog** search panel allows lookup by name or SATNO (up to 50 results).
Results show the satellite name, SATNO, and TLE age. Click **→ Blue** or **→ Red**
to add a satellite from the catalog.

#### Manual Entry

Click **+ Add Blue Asset** or **+ Add Red Track** and paste the two-line TLE directly.

#### TLE Age Indicator

Each asset in the list shows how many days old its TLE is relative to the scenario
start time. A **STALE** warning appears when the TLE is more than 7 days old.

#### Naming Conventions

| Prefix | Type |
|--------|------|
| `B_SAT_` | Blue (friendly) satellite in STK |
| `R_SAT_` | Red (threat) satellite in STK |

Assets appear in STK under these names. Do not edit them directly in STK during a session.

---

### 5. Generate Maneuver Options (Astrogator)

The **Maneuver Options** panel (Intel/Mission panel) uses STK Astrogator to enumerate
viable intercept burn solutions for a Red satellite targeting a Blue asset.

**Requires:** STK Astrogator licence on the connected STK instance.

**Controls:**

| Field | Description |
|-------|-------------|
| Red satellite | Select from the Red Tracks dropdown |
| Blue target | Select from the Blue Assets dropdown |
| Window start / stop | UTC search window — constrains when burns can occur |
| Max ΔV (km/s) | Solutions requiring more ΔV than this are discarded |
| Burn types | Impulsive and/or Finite burn model |
| Burn locations | Apogee / Perigee / Ascending Node / Descending Node / Poles |

Click **Generate Options**. SIPC runs a differential corrector search in STK Astrogator
for each enabled location × burn type combination over the search window.
Non-converging solutions are silently discarded.

Results appear in the **Maneuver Options** table, sorted by ΔV ascending:

| Location | Type | Burn Epoch (UTC) | ΔV km/s | Transfer | Intercept Range | Notes | |
|----------|------|------------------|---------|----------|-----------------|-------|--|
| Apogee | Impulsive | 2026-03-07 02:14 | 0.312 | 47 min | 0.8 km | — | [Select] |

Click any column header to re-sort. Click **[Select]** on a row to store that maneuver
option in the session for use in the intercept plan.

Click **Re-run Last Search** to re-execute the same search configuration with the
current satellite state (useful after TLE updates or scenario time changes).

> **Note:** The red satellite's propagator is always restored to SGP4 + original TLE
> after the Astrogator search completes, even if the search fails or is interrupted.

---

### 6. Run the Intercept Plan

In the **Run Configuration** panel:

| Field | Description |
|-------|-------------|
| Operator | Your callsign or username — recorded in all provenance logs |
| Source | Data source tag (e.g. `UDL`, `SPADOC`, `MANUAL`) |

Click **Run Plan**. SIPC:
1. Creates or updates satellite objects in STK (SGP4 propagator + TLE)
2. Computes access intervals for all blue/red pairs over the scenario time window
3. Displays candidate intercept windows in the **Intercept Windows** table

---

### 7. Review Results

**Intercept Windows** table columns:

| Column | Description |
|--------|-------------|
| Blue | Blue asset name |
| Red | Red track name |
| Start (UTC) | Window open time |
| End (UTC) | Window close time |
| Duration (s) | Window length |

**Run Log** — scrolling structured log of all actions taken during the session.
Auto-refreshes every 5 seconds. Click **Refresh** to force an update. Click **Clear** to reset.

---

## Troubleshooting

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| STK chip stays amber after connect | STK not running, or scenario not loaded | Start STK 13 and open a scenario, then retry |
| "No satellites in scenario" on Import | STK scenario has no `B_SAT_*`/`R_SAT_*` objects | Add assets via the Add Asset form first |
| "Failed to add the TLE" in log | TLE line length ≠ 69 chars (non-standard UDL data) | Check the WARNING log for exact line content; edit TLE manually |
| Empty Maneuver Options table | No solutions converged in the window | Widen search window, raise max ΔV, or add more burn locations |
| "Astrogator licence not available" | STK Astrogator module not licenced | Verify licence in STK Help → About; contact your licence administrator |
| Empty results in Intercept Windows | No access between any pair in the scenario window | Extend scenario time range or verify TLEs are current |
| UDL chip stays amber | Wrong credentials or UDL unreachable | Retry with correct credentials; check network connectivity |
| COM error on STK connect | pywin32 not registered, or STK not on PATH | Run `python -m win32com.client.makepy` in the SIPC virtual environment |

---

## Time and Units

- All times: **UTC**
- Distances: **km**
- Speeds: **m/s** (ΔV in **km/s**)
- Angles: **degrees**
- Coordinate frame: **ICRF/J2000**

---

## Log Files

Structured JSON-lines logs are written to the `logs/` directory:

```
logs/RUN_<id>.jsonl
```

Each line contains `run_id`, `timestamp`, `level`, `logger`, and `event` fields.
Compatible with `jq` and any JSON-aware log viewer.
