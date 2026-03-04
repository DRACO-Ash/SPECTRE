# SIPC — STK Intercept Planning Console

Rapid intercept replanning console interfacing with AGI Systems Tool Kit (STK) via COM automation.

## Overview

SIPC provides analysts with a PySide6 GUI for:
- Defining blue/red asset sets (satellites, ground stations)
- Configuring intercept planning runs with provenance tracking
- Executing STK scenario updates on-the-fly via the STK Object Model
- Reviewing access windows, geometry data, and run logs

## Requirements

- Windows 10/11 (STK COM is Windows-only)
- Python ≥ 3.14
- AGI STK 13.0 (with Object Model licence)
- pywin32 ≥ 311

## Quick Start

```powershell
# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install in editable mode with dev extras
pip install -e ".[dev]"

# Run unit tests (no STK required)
pytest tests/unit/

# Launch the application
sipc
```

## Integration Tests

Integration tests require a running STK 13 installation and are opt-in:

```powershell
$env:STK_INTEGRATION_TESTS = "1"
pytest tests/integration/
```

## Project Structure

```
sipc/                   ← repo root
├── sipc/               ← importable package
│   ├── stk_adapter/    ← IStkSession interface + COM + fake implementations
│   ├── domain/         ← intercept planning logic (decoupled from STK)
│   ├── ui/             ← PySide6 GUI components
│   ├── app_logging/    ← structlog setup + run_id correlation
│   └── config/         ← constants and runtime settings
├── tests/
│   ├── unit/           ← fast tests using FakeStkSession
│   └── integration/    ← live STK tests (opt-in)
├── scripts/            ← build helpers
└── docs/               ← architecture + operator guide
```

## Build EXE

```powershell
pip install -e ".[build]"
python scripts/build_exe.py
```

Output: `dist/sipc.exe`

## Naming Conventions

| Prefix     | Meaning                        |
|------------|--------------------------------|
| `B_SAT_`   | Blue satellite asset           |
| `R_SAT_`   | Red track satellite            |
| `CALC_`    | Computed/derived STK objects   |
| `OUT_`     | Run output folders             |

All times are UTC. Distances in km, speeds in m/s, angles in degrees.
Coordinate frame: ICRF/J2000.

## Contributing

See `docs/architecture.md` for design decisions and hexagonal architecture overview.
