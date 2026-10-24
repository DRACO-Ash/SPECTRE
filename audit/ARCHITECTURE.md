# SPECTRE audit: architecture and flow (phase 3)

**Source audited:** tree at `a34e273` (HEAD `1c5ecf2` differs only under `audit/`). Reconstructed from the code, not the docs. Every claim is marked fact, inference or speculation.

## 3.1 Entry points

| # | Entry point | Kind | Location | Evidence |
|---|---|---|---|---|
| E1 | Container process | CMD | `Dockerfile:196` `["/opt/venv/bin/python", "-m", "spectre.web._entrypoint"]` | fact |
| E2 | `spectre.web._entrypoint.main()` | uvicorn launcher | `spectre/web/_entrypoint.py:33-47`, binds `0.0.0.0`, port from `get_settings().port`, `access_log=False` | fact |
| E3 | ASGI app `spectre.web.app:app` | library import / uvicorn target | `spectre/web/app.py:310` | fact |
| E4 | Lifespan startup | startup hook | `spectre/web/app.py:151-214` | fact |
| E5 | 75 HTTP route decorators (74 handlers) across 14 modules | HTTP | table 3.1a, extracted by AST (AST extraction; summary below) | fact |
| E6 | `/static` mount | HTTP static files | `spectre/web/app.py:344` | fact |
| E7 | Background tasks launched at UDL login | event | `spectre/web/routes/udl.py:316-317` `asyncio.create_task(...)` | fact |
| E8 | Thread-pool executions | worker threads | `gcat.py:394,566`, `maneuver.py:865,1117`, `pol.py:803`, `threat.py:1347,1701,1795`, `health.py:66` | fact |
| E9 | Developer and pipeline CLIs | `__main__` | `scripts/*.py` (5), `scripts/*.sh` (9), `docs/generate_guide.py`, `docs/build_gcat_workbook_1.py`, `query_UDL_Data.py` (no guard) | fact; none ships in the image, which copies only `spectre/` and `tle_clustering/` (`Dockerfile:77,84`) |

No scheduled jobs, message consumers or websockets exist (fact: `git grep -n "websocket\|apscheduler\|celery\|cron" -- spectre` returns nothing beyond the route table).

### 3.1a Route table and authentication dependency

Extraction method: AST walk of every `@router.<verb>` decorator, then a text search of the handler signature for `require_login`, `require_admin` and `optional_login`. Global dependency: `FastAPI(dependencies=[Depends(require_csrf)])` at `app.py:314`, so CSRF applies to every route (fact).

| Auth | Count | Routes |
|---|---|---|
| none (public) | 7 | `GET /healthz`, `GET /livez`, `GET /ping`, `GET /readyz` (`health.py:80-109`); `GET /login`, `POST /login`, `POST /logout` (`login.py:109-194`) |
| optional | 1 | `GET /` (`operator.py:44`): login page when anonymous, console when authenticated |
| admin | 6 | `/admin/users` GET, POST; `/admin/users/{id}/edit`, `/cancel` GET; `/admin/users/{id}` POST, DELETE (`admin.py:95-253`) |
| login | 61 | every other route: `/assets/*`, `/scenario/time`, `/log/*`, `/plan/*` (decision, geometry, maneuver, threat, export), `/pol/*`, `/gcat/*`, `/training/*`, `/udl/*` |

CSRF exemptions (fact, `csrf.py:24-25`): methods GET, HEAD, OPTIONS, TRACE; path `/login`. Inference: `POST /logout` is not exempt, so a logout without a token returns 403 rather than logging out. Phase 5 to confirm against `tests/unit/test_csrf.py`.

## 3.2 Call paths to terminal sinks

| Entry | Path (abridged) | Terminal sinks |
|---|---|---|
| E1, E2 | `_entrypoint.main` → `uvicorn.run("spectre.web.app:app")` | network listener `0.0.0.0:$PORT` (default 8080, `settings.py:36`) |
| E4 lifespan | `get_settings` → `logging.basicConfig` (`app.py:161`) → `validate_secret_key` → `validate_data_dir` (mkdir, write probe, unlink, `settings.py:404-413`) → `validate_sqlite_support` → `init_db` (create tables, admin bootstrap, `database.py`) → `_load_hrr_from_disk` (reads data dir, repo root, bundled JSON, `app.py:82-86`) | filesystem (read and probe write), database (DDL, insert), stdout logging |
| Health | `/healthz` `/livez` `/ping` liveness; `/readyz` → `asyncio.to_thread(_write_probe)` (`health.py:54-66`) | filesystem probe write in data dir |
| Login | `post_login` → rate limiter (`rate_limit.py`) → DB user lookup → bcrypt verify → `make_session_cookie` → `set_cookie` (`login.py:167-174`) | database, response cookie, logging |
| Logout | `post_logout` → decode cookie → increment session generation → `clear_session_state(username)` → `delete_cookie` (`login.py:194-217`) | database, process memory, response cookie |
| Admin | `admin.py` → SQLAlchemy CRUD on `User` | database, logging |
| Operator, assets | `operator.py` → `get_session_state` → mutate `SessionState` lists; quick-add → `udl.py` fetch helpers | process memory, UDL network (quick-add) |
| UDL | `udl.py` → `httpx.AsyncClient` with `auth=(user, pass)` to `https://unifieddatalibrary.com/udl/...` (`udl.py:55,117-229,265,594,721,826,1029,1123`) | **outbound network with Basic credentials**, process memory, NOTSO cache file write |
| Intercept engine | `maneuver.py` → `run_in_executor` → `spectre.astro.{maneuvers,events,propagator}`, `domain.manoeuvre_calibration`, `data.intel` | CPU, process memory, logging; UDL network for TLE fetch via `routes.udl` |
| Threat sweep and screen | `threat.py` → UDL TLE fetch (`threat.py:331-352,1127-1146,1418-1437`) → `astro.tle_preprocessing` (DBSCAN via `tle_clustering`) → `run_in_executor` sweep (`threat.py:1347`) → `domain.threat_assessment` | outbound network, CPU, process memory |
| Pattern of Life | `pol.py` → UDL history fetch (`pol.py:124-156`, 120 s timeout) → `astro.{pattern_of_life,tle_filter,notso,monte_carlo,photometry}`, `domain.pol_assessment` | outbound network, CPU, NOTSO cache read |
| Decision | `decision.py` → `domain.decision.evaluate_scenario` | CPU, process memory |
| Geometry | `geometry.py` → `astro.cw_geometry` | CPU, logging |
| GCAT | `gcat.py` → `httpx.Client(follow_redirects=False)` to `https://planet4589.org/space/gcat` in a module thread pool (`gcat.py:333,394`) → pandas parse → in-process cache | outbound network (unauthenticated), process memory |
| Training | `training.py` → `training.{gamification,scenarios,tutorials}` (YAML config) → `training.models` ORM | database, process memory |
| Export | `plan.py:147` → CSV `StreamingResponse` with formula-injection guard (`plan.py:28-31`) | HTTP response body |
| E7 background | `_fetch_onorbit_background(username, password)` → UDL on-orbit catalogue → `set_onorbit_catalog` (process-global); `_discover_tle_sources(username, password, state)` | outbound network, **process-global memory shared by all operators** |

## 3.3 External inputs and trust boundaries

| Boundary | Input | Enters at | Validation observed (fact unless marked) |
|---|---|---|---|
| TB1 Browser to app | form fields, query strings, path params, cookie `spectre_session`, header `X-CSRF-Token`, `X-Forwarded-Proto` | every route | session signature and generation (`auth.py:62-148`); CSRF HMAC (`csrf.py:55-98`); per-route form parsing and bounds (geometry `geometry.py:42`, admin username charset `admin.py:26-34`); `X-Forwarded-Proto` trusted unauthenticated for the HSTS decision only (`app.py:297-307`) |
| TB2 Operator-pasted content | TLE text, NOTSO text, photometry CSV, manual sweep TLEs | `/assets/*`, `/plan/threat/add-manual-tle`, `/pol/notso-correlate`, `/pol/photometry-analyse` | parser-level; depth TBC in phase 5 |
| TB3 UDL responses | JSON element sets, HRR notifications, NOTSO records, state vectors, catalogue | `udl.py`, `pol.py`, `threat.py` | parsed with ad-hoc helpers; UDL `dataMode` tag carried through (`planning_state.py:77-78`) |
| TB4 GCAT responses | TSV datasets | `gcat.py` | scheme check, no redirects (`gcat.py:52-55,333`) |
| TB5 Files on disk | `HRR_List.json` (data dir, then repo root, then bundled), `notso_cache.json`, training YAML | lifespan, NOTSO routes, training | `isinstance` checks (`app.py:111-117`); YAML via `yaml.safe_load` (`training/gamification.py:91`, fact) |
| TB6 Environment | variables in 3.5 | `settings.py` | per variable, 3.5 |
| TB7 Platform | `PORT`, `STORAGE_MOUNT_PATH`, `DATABASE_URL`, `APPSTORE_DAST_SCAN` injection | `settings.py` | as 3.5 |

## 3.4 Credentials and secrets

| Secret | Loaded | Held | Scope | Can reach |
|---|---|---|---|---|
| `SECRET_KEY` | `settings.py:100` from env on every `get_settings()` call | not cached; re-read per call (`settings.py:349-351`) | process (environment) | session and CSRF signing (`auth.py:31`, `csrf.py:47`). Not logged (fact, grep). Fallback: a 48-byte throwaway key when `APPSTORE_DAST_SCAN` is truthy and `SECRET_KEY` is empty (`settings.py:93-103`), with a boot warning (`app.py:173-180`) |
| Bootstrap admin password `SPECTRE_ADMIN_PASS` | `settings.py:338-340` | read at startup by `init_db` | process | bcrypt hashed into DB (`database.py:215,245`); `SPECTRE_ADMIN_RESET` re-applies it on every boot while set (`.env.example`) |
| Operator passwords | `POST /login`, admin forms | transient per request; stored as bcrypt hash (`auth.py:37-45`) | request | DB only |
| Session token | minted `auth.py:59`, cookie `login.py:167-174` | browser; server holds only the generation counter | session (8 h, `auth.py:22`) | cookie flags `httponly=True`, `secure` from `SPECTRE_COOKIE_SECURE` default true, `samesite="lax"`, `max_age=28800`; no `domain`, `path` default |
| **UDL username and password** | `POST /udl/login` form (`udl.py:250-311`) | `SessionState.udl_username`, `.udl_password` as plaintext `str` (`planning_state.py:56-57`) inside `_store: dict[str, SessionState]` (`planning_state.py:113`) | **process-global dict, keyed by SPECTRE username**: shared by every concurrent browser session of that username; not tied to the cookie; cleared only by `/logout` (`login.py:212`) or `/udl/logout` (`udl.py:385`), not by session expiry or revocation (inference from absence of any other `clear_session_state` caller, grep in phase 3 notes) | outbound HTTP Basic to UDL (11 call sites listed in 3.2); passed as plain arguments to background tasks (`udl.py:316-317`) that outlive the request; a custom `__repr__` hides the password (`planning_state.py:93-99`) but `dataclasses.asdict`, `vars()` or a traceback frame dump would expose it (speculation, no such call found); logged? the username is written to the session log (`udl.py:312` `"[UDL] Connected as {username}"`), password not logged (fact, grep of `udl_password` in logger calls returns none) |
| UDL-derived shared data | on-orbit catalogue fetched with one operator's credential | `planning_state._onorbit_catalog` (process-global, `planning_state.py:150`) | process, all operators | served to every operator via `/udl/catalog/search` (`udl.py:981`) regardless of which operator's UDL entitlement fetched it |
| NOTSO records | fetched with an operator's UDL credential (`udl.py:1123-1132`) | `spectre/data/notso_cache.json`, written into the package directory (`notso_cache.py:47,93`) | persistent file, all operators | every operator's PoL NOTSO views (`pol.py:900-1035`) |

## 3.5 Configuration

| Variable | Read at | Default | Absent | Malformed |
|---|---|---|---|---|
| `SECRET_KEY` | `settings.py:100,108` | none | boot fails `ConfigurationError` (`settings.py:366-371`) unless `APPSTORE_DAST_SCAN` set | placeholder or < minimum length: boot fails (`settings.py:372-381`) |
| `APPSTORE_DAST_SCAN` | `settings.py:73` | off | normal | any value not in `_TRUTHY` is off |
| `SPECTRE_DATA_DIR` | `settings.py:121` | then `STORAGE_MOUNT_PATH`, then `./data` | next in chain | validated writable at boot (`settings.py:384-419`) |
| `STORAGE_MOUNT_PATH` | `settings.py:124` | `./data` | as above | as above |
| `SPECTRE_SQLITE_DIR` | `settings.py:164` | `./data` (cwd) (`settings.py:167`) | `./data` | not validated until boot `validate_data_dir` |
| `DATABASE_URL` | `settings.py:180` | `sqlite+aiosqlite:///<SQLITE_DIR>/spectre.db` (`settings.py:183`) | SQLite, boot warns EPHEMERAL (`app.py:198-203`) | normalised by `_normalise_database_url` (`settings.py:130`) |
| `SPECTRE_COOKIE_SECURE` | `settings.py:263` | true | Secure set | only `false/0/no/off` disable |
| `PORT` | `settings.py:270` | 8080 | 8080 | non-integer or out of 1-65535: silently 8080 (`settings.py:273-277`) |
| `SPECTRE_DB_POOL_RECYCLE` | `settings.py:304` | 300 | 300 | non-integer or negative: silently 300 |
| `SPECTRE_LOG_LEVEL` | `settings.py:323` | INFO | INFO | unknown level: silently INFO (`app.py:160`) |
| `SPECTRE_LOG_DIR` | `settings.py:326` | `logs` | n/a | **read into `Settings.log_dir` and never used** (fact: `git grep log_dir` finds only `settings.py` and the uncalled `app_logging/config.py`) |
| `SPECTRE_ADMIN_USER` | `settings.py:336` | `admin` | `admin` | |
| `SPECTRE_ADMIN_PASS` | `settings.py:339` | empty | no bootstrap; boot logs an error per `.env.example` | |
| `SPECTRE_ADMIN_RESET` | `settings.py:344` | off | | resets the admin password on every boot while set |
| Training YAML | `spectre/training/config/*.yaml` | bundled | | TBC phase 5 |

## 3.6 Reconstructed versus documented architecture: divergences (candidate findings)

| ID | Divergence | Documented | Code | Epistemics |
|---|---|---|---|---|
| A1 | Structured logging and run-id correlation do not run | `README.md:359` "app_logging/ ← structlog setup, run_id correlation"; `README.md:102` `SPECTRE_LOG_DIR` "Directory for structlog output files" | `configure_logging` (`app_logging/config.py:12`) has no caller anywhere in the repository; the app uses `logging.basicConfig` (`app.py:161`); the module is excluded from coverage (`pyproject.toml:69`, `sonar-project.properties:41`) | fact |
| A2 | UDL credential scope is wider than documented | `planning_state.py:55` "held in memory for this session only, never persisted"; `README.md:344` "Per-session in-memory state" | keyed by username in a process-global dict; survives cookie expiry and server-side session revocation; shared across a user's concurrent sessions | fact (scope), inference (survives revocation: only two clearing call sites) |
| A3 | UDL-derived data is shared across operators | `planning_state.py:148` "App-level on-orbit catalog (shared across all operator sessions)" acknowledges sharing | one operator's credential populates data every operator sees; same for the NOTSO cache file | fact (mechanism); the entitlement consequence is inference |
| A4 | NOTSO cache bypasses the data-directory contract | `.env.example` and `settings.py:115-127` route writable data to `SPECTRE_DATA_DIR` or `STORAGE_MOUNT_PATH` | `notso_cache.py:47` writes beside the module inside the installed package | fact: the image copies the package to `/app/spectre/` and `chown -R 10001:0 /app` (`Dockerfile:77,94`), so the write succeeds into the container's ephemeral layer and is lost on restart, outside the storage mount |
| A5 | Session log queue has no consumer | `planning_state.py:43` "Async queue of log-line strings for SSE streaming" | no SSE endpoint exists (grep: no `text/event-stream`, the only `StreamingResponse` is CSV export); `asyncio.Queue()` is unbounded, so `QueueFull` (`planning_state.py:108`) never fires and the queue grows for the life of the process | fact |
| A6 | Fire-and-forget tasks | none | `asyncio.create_task` results discarded (`udl.py:316-317`); the event loop holds only a weak reference, so a task can be garbage-collected mid-flight and its exceptions are never observed | fact (code); the GC consequence is documented asyncio behaviour, inference for this code |
| A7 | No request audit path | `_entrypoint.py:44` "request logging is handled by the application's own audit path" | no middleware logs requests; `app.py:327-341` adds headers only; per-route `logger` lines exist for login, admin and UDL events | fact (no request-logging middleware); "audit path" exists only as scattered log lines, inference |
| A8 | Route inventory in `docs/architecture.md` is stale | `docs/architecture.md:14-15` lists "operator · login · udl · maneuver · threat · pol · decision · geometry · gcat · training" | also `admin`, `plan`, `health` routers (`app.py:347-359`) | fact |
| A9 | Schema endpoint off, but a generated schema is committed | `app.py:315-321` turns off `/openapi.json` because it is "a complete attack-surface map" | `docs/openapi.json` (287,166 lines) is committed to the repository | fact; whether `docs/` ships in the upload package is TBC (`.dockerignore` excludes it from the image) |
| A10 | Port and console script | `README.md:49,54` `spectre-serve`, port 8000 | no `[project.scripts]`; `Dockerfile:194` "`spectre-serve` was a console script"; port 8080 (LEDGER O3, O4) | fact |

## Exit check

Every entry point in 3.1 is traced to terminal sinks in 3.2: E1 to E8 row by row, E5 by router group (74 handlers in 14 modules, each module mapped). E9 CLIs are developer tooling outside the runtime; their sinks are summarised in `audit/TOOLS.md` section 5b (subprocess, urlopen) and they are reviewed in phase 5 per ledger row.
