# SIPC Architecture

## Overview

SIPC follows a **hexagonal architecture** (ports and adapters) pattern. The core
domain logic is completely isolated from external systems (STK, the file system,
the GUI) via well-defined interfaces.

```
┌─────────────────────────────────────────────────────────┐
│                        UI Layer                         │
│  (PySide6 QMainWindow, panels, view-models, workers)    │
└──────────────────────┬──────────────────────────────────┘
                       │ uses domain models + ScenarioPlanner
┌──────────────────────▼──────────────────────────────────┐
│                    Domain Layer                         │
│  (ScenarioPlanner, BlueAsset, RedTrack, InterceptWindow)│
└──────────────────────┬──────────────────────────────────┘
                       │ IStkSession Protocol
┌──────────────────────▼──────────────────────────────────┐
│                   STK Adapter Layer                     │
│  StkComSession (prod)  │  FakeStkSession (tests)        │
└─────────────────────────────────────────────────────────┘
```

## Packages

### `sipc/domain/`
Pure Python. No GUI, no COM, no file I/O. Contains:
- **models.py** — dataclasses: `BlueAsset`, `RedTrack`, `InterceptWindow`, `RunConfig`, `AccessInterval`
- **scenario.py** — `ScenarioPlanner`: orchestrates a planning run
- **geometry.py** — stateless math helpers (AER, closure rate, etc.)
- **exceptions.py** — domain-specific exception hierarchy

### `sipc/stk_adapter/`
Implements the `IStkSession` Protocol for different backends:
- **interface.py** — `IStkSession` as a `typing.Protocol` (structural typing)
- **com_session.py** — `StkComSession`: live STK 13 via pywin32 COM
- **fake.py** — `FakeStkSession`: in-memory double for unit testing
- **exceptions.py** — adapter-specific exceptions

### `sipc/ui/`
PySide6 GUI. Consumes domain models only — never imports from `stk_adapter` directly.
Long-running operations (STK calls) execute in `QRunnable` workers to keep the UI responsive.

### `sipc/app_logging/`
Configures `structlog` with:
- Console renderer (human-readable) for terminal output
- JSON-lines file renderer for post-run analysis
- `run_id` bound to all log records via `structlog.contextvars`

### `sipc/config/`
- **constants.py** — STK naming prefixes, units, step sizes, folder list
- **settings.py** — `Settings` dataclass populated from environment variables

## Key Design Decisions

### Protocol-based STK interface
`IStkSession` is a `typing.Protocol` (structural subtyping), not an ABC.
This means `FakeStkSession` does **not** inherit from `IStkSession` — it just
implements the same methods. This keeps the test double completely independent
of the interface definition, preventing accidental coupling.

### Off-thread STK calls
All STK COM calls block the calling thread. SIPC wraps them in `QRunnable`
workers (`ui/workers.py`) dispatched via `QThreadPool`. Signals (`result`,
`error`, `finished`) communicate results back to the UI thread safely.

### Provenance tagging
Every STK action is logged via `session.log_action(run_id, action, payload)`.
The `run_id` is bound to `structlog.contextvars` at run start, so it
automatically appears in all log records without explicit threading through
every function call.

## Testing Strategy

| Layer         | Test type    | STK dependency |
|---------------|--------------|----------------|
| domain/       | unit         | None           |
| stk_adapter/  | unit (fake)  | None           |
| stk_adapter/  | integration  | STK 13 (opt-in)|
| ui/           | unit (pytest-qt) | None       |

Integration tests are guarded by `@pytest.mark.integration` and auto-skipped
unless `STK_INTEGRATION_TESTS=1` is set.
