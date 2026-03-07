# SIPC Architecture

## Overview

SIPC follows a **hexagonal architecture** (ports and adapters) pattern. The core
domain logic is completely isolated from external systems (STK, the database,
the web layer) via well-defined interfaces.

```
┌─────────────────────────────────────────────────────────┐
│                      Web Layer                          │
│  FastAPI + Jinja2 + HTMX (routes, templates, partials)  │
│  Session auth (signed cookies) · SQLite/PostgreSQL DB   │
└──────────────────────┬──────────────────────────────────┘
                       │ uses domain models + planners
┌──────────────────────▼──────────────────────────────────┐
│                    Domain Layer                         │
│  ScenarioPlanner · ManeuverPlanner                      │
│  BlueAsset · RedTrack · InterceptWindow · RunConfig     │
│  BurnType · BurnLocation · ManeuverOption               │
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
- **models.py** — dataclasses: `BlueAsset`, `RedTrack`, `InterceptWindow`,
  `RunConfig`, `AccessInterval`, `BurnType`, `BurnLocation`, `ManeuverOption`,
  `ManeuverSearchConfig`
- **scenario.py** — `ScenarioPlanner`: orchestrates an access-window planning run
- **maneuver_planner.py** — `ManeuverPlanner`: validates config, delegates to STK
  Astrogator, sorts results by ΔV, logs provenance
- **geometry.py** — stateless math helpers (AER, closure rate, etc.)
- **exceptions.py** — domain-specific exception hierarchy

### `sipc/stk_adapter/`
Implements the `IStkSession` Protocol for different backends:
- **interface.py** — `IStkSession` as a `typing.Protocol` (structural typing)
- **com_session.py** — `StkComSession`: live STK 13 via pywin32 COM (Object Model
  exclusively; Connect command layer blocked by ODTK)
- **fake.py** — `FakeStkSession`: in-memory double for unit testing
- **exceptions.py** — adapter-specific exceptions (`StkCommandError`,
  `StkConnectionError`)

### `sipc/web/`
FastAPI application. Operators access via any browser — no desktop install required.
- **app.py** — application factory + lifespan startup (DB init, admin bootstrap)
- **auth.py** — session cookies (itsdangerous), `require_login` dependency, 8hr expiry
- **database.py** — async SQLAlchemy engine + admin account bootstrap from env vars
- **models.py** — `User` ORM model
- **planning_state.py** — per-session in-memory state (`SessionState`): assets,
  maneuver options, UDL credentials, STK session reference
- **routes/**
  - `login.py` — `GET/POST /login`, `POST /logout`
  - `operator.py` — dashboard, asset CRUD, `/plan`, STK connect/disconnect/import,
    run log
  - `udl.py` — UDL login/logout, TLE fetch (latest + epoch modes), HRR watchlist,
    orbit catalog search
  - `maneuver.py` — `/plan/maneuver/search`, `/refresh`, `/select`
- **templates/** — Jinja2 HTML (base, login, operator, HTMX partials)
- **static/** — dark-mode military CSS, SIPC logo SVG, favicon

### `sipc/app_logging/`
Configures `structlog` with:
- Console renderer (human-readable) for terminal output
- JSON-lines file renderer for post-run analysis
- `run_id` bound to all log records via `structlog.contextvars`

### `sipc/config/`
- **constants.py** — STK naming prefixes (`B_SAT_`, `R_SAT_`), units, step sizes,
  folder list
- **settings.py** — `Settings` dataclass populated from environment variables

## Key Design Decisions

### Protocol-based STK interface
`IStkSession` is a `typing.Protocol` (structural subtyping), not an ABC.
`FakeStkSession` does **not** inherit from `IStkSession` — it just implements the
same methods. This keeps the test double completely independent of the interface
definition, preventing accidental coupling.

### Off-thread STK calls
All STK COM calls block the calling thread. The web layer dispatches them via
`asyncio.get_event_loop().run_in_executor(None, ...)` so FastAPI's async event
loop is never blocked.

### In-memory session state
`SessionState` is a single in-memory object per server process. It holds the
current blue/red asset lists, UDL credentials, the live `IStkSession` reference,
and maneuver results. It is **not** persisted — connecting to an existing STK
scenario after an app restart requires clicking **Import from Scenario** to
re-populate asset lists from `B_SAT_*`/`R_SAT_*` objects already in STK.

### HTMX partial swap pattern
All operator actions (add asset, run plan, fetch TLE, generate maneuver options)
return HTML fragments that HTMX swaps into targeted DOM elements — no full page
reloads. `HX-Refresh: true` is used only when server-rendered dropdowns (populated
at page load) need to reflect updated state.

### Provenance tagging
Every planning run is assigned a `run_id` (UUID). It is bound to `structlog`
context at run start and automatically appears in all log records for that run.

### Database
SQLite by default (`sipc.db`). Switch to PostgreSQL by setting:
```
DATABASE_URL=postgresql+asyncpg://user:pass@host/sipc_db
```
No code changes required — the async SQLAlchemy adapter handles the swap.

## Testing Strategy

| Layer          | Test type       | STK dependency      |
|----------------|-----------------|---------------------|
| `domain/`      | unit            | None                |
| `stk_adapter/` | unit (fake)     | None                |
| `web/routes/`  | integration (TestClient) | None       |
| `stk_adapter/` | integration     | STK 13 (opt-in)     |
| Astrogator     | integration     | STK 13 + licence (opt-in) |

Integration tests are guarded by `@pytest.mark.integration` and auto-skipped
unless `STK_INTEGRATION_TESTS=1` is set.
