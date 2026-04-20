# SPECTRE: OpenAPI & Cloud-Native Containerisation Plan

> **Document:** Architecture Compatibility Plan  
> **Version:** 0.1 — Living Document  
> **Classification:** UNCLASSIFIED  
> **Date:** 2026-04-12  
> **Status:** DRAFT — For iterative refinement

---

## 1. Goal Restatement

Ensure the **Space Intercept Planning Console (SPECTRE)** — a pure-Python astrodynamics application providing fast manoeuvre calculations for Protect & Defend operators — is fully compatible with OpenAPI standards and containerised for deployment to any cloud provider without vendor lock-in.

---

## 2. Knowns / Unknowns / Assumptions

### Knowns

| # | Fact | Source |
|---|------|--------|
| K1 | SPECTRE is a pure-Python astrodynamics application (no COTS orbital tools) | Persona spec |
| K2 | Core stack: astropy, skyfield, orekit-python, sgp4, beyond, NumPy, SciPy, JAX | Persona spec |
| K3 | Visualisation: Matplotlib, Plotly, Cesium, VTK | Persona spec |
| K4 | Target OS: Windows (current), but containerisation implies Linux runtime | Persona spec + this plan |
| K5 | Operational tempo: must be rapid, easy to use, true benefit to P&D operators | Persona spec |
| K6 | Classification: Unclassified | Persona spec |
| K7 | Orbit determination: required | Persona spec |
| K8 | Parallelism options: multiprocessing, joblib, Dask, Ray, MPI4py | Persona spec |

### Unknowns

| # | Unknown | Impact if unresolved |
|---|---------|---------------------|
| U1 | Current SPECTRE architecture (monolith? modules? CLI? web app? desktop GUI?) | Determines the entire API extraction and containerisation strategy |
| U2 | Current state of any existing API surface (REST endpoints, function calls, CLI commands) | Determines how much new API design is needed vs wrapping existing interfaces |
| U3 | Deployment target cloud(s) and any existing infrastructure | Drives IaC approach, networking, and registry choices |
| U4 | Authentication/authorisation requirements for API consumers | Drives security architecture of the API layer |
| U5 | Data sources in production (Space-Track, Celestrak, local TLE cache, sensors) | Drives containerised data access patterns and network policy |
| U6 | Orekit dependency — JVM requirement inside a Python container | Significant container complexity; needs explicit handling |
| U7 | JAX GPU requirements in production | Drives container base image and cloud compute selection |
| U8 | Expected concurrent users / API request volume | Drives scaling architecture and container orchestration |
| U9 | Latency budget for manoeuvre calculations | Determines whether async/queue patterns are needed |
| U10 | VTK/Cesium rendering — server-side or client-side? | Drives whether visualisation is in the API container or a separate frontend |

### Assumptions

| # | Assumption | Confidence | Default | Risk if wrong |
|---|-----------|------------|---------|---------------|
| A1 | SPECTRE is currently a monolithic Python application (scripts/modules, not yet a web service) | MEDIUM | Proceed with API-first containerisation plan | If already a web service, plan simplifies significantly |
| A2 | The API will serve a web-based frontend (Cesium globe + Plotly charts) via a separate static container | MEDIUM | Design API as headless compute service, frontend as separate concern | If desktop-only, API layer may be overkill initially |
| A3 | Kubernetes is the target orchestration platform (cloud-agnostic) | HIGH | Design for K8s with Helm charts | If serverless/ECS-only, simplify orchestration layer |
| A4 | No GPU required in initial deployment (JAX CPU-only mode acceptable) | MEDIUM | CPU-only containers initially, GPU as an opt-in upgrade | If GPU critical, container and node pool strategy changes substantially |
| A5 | orekit-python (JCC) will require a JVM in the container | HIGH | Multi-stage build with JVM layer | Adds ~200-400MB to image; explore orekit alternatives if weight is a concern |
| A6 | Visualisation is split: Cesium/Plotly on client, Matplotlib/VTK for server-side plot generation (export as PNG/SVG) | MEDIUM | Separate frontend and compute containers | If VTK interactive rendering needed server-side, requires GPU + VirtualGL |

---

## 3. Clarifying Questions (Resolve Before Phase 2)

These are ordered by impact on the plan. Answering any of them may change the architecture materially.

| # | Question | Why it matters | Proposed default |
|---|----------|---------------|-----------------|
| Q1 | What is SPECTRE's current form — CLI scripts, a GUI app, a library of modules, or already a web service? | Determines how much refactoring is needed to expose an API. A CLI-based tool needs a different wrapping strategy than an already-modular library. | Assume modular Python library with some CLI entry points |
| Q2 | What is the target deployment — single-team internal tool (< 10 users), multi-unit shared service (10–100), or enterprise-scale (100+)? | Drives container orchestration complexity: single Docker Compose at the low end, full Kubernetes with autoscaling at the high end. | Assume small-team (< 20 users), design for growth to 100 |
| Q3 | Is orekit-python a hard dependency, or can its functions be replaced by poliastro/beyond/custom code? | Orekit requires a JVM, which adds significant container complexity and image size. If replaceable, the container story simplifies dramatically. | Assume orekit is required for high-fidelity OD; plan for JVM in container |
| Q4 | Does SPECTRE currently have a frontend, or is output purely terminal/file-based? | Determines whether we're containerising compute-only (API) or compute + UI. | Assume no existing web frontend; plan to build one |
| Q5 | What are the data freshness requirements for TLEs and EOP? Real-time fetch, daily cache, or pre-loaded? | Drives network egress policy in the container, data volume mounts, and sidecar patterns. | Assume daily cached TLEs with manual refresh option |

---

## 4. Architecture Overview

### 4.1 Target Architecture — Container Topology

```
┌─────────────────────────────────────────────────────────────────┐
│  EXTERNAL (Untrusted)                                           │
│  [Browser / C2 System] ──HTTPS──► [Ingress / API Gateway]      │
└──────────────────────────────────────┬──────────────────────────┘
                                       │ TLS termination
┌──────────────────────────────────────▼──────────────────────────┐
│  FRONTEND TIER (Container: spectre-ui)                          │
│  [Cesium Globe + Plotly Dashboard — static SPA served by Nginx] │
└──────────────────────────────────────┬──────────────────────────┘
                                       │ OpenAPI REST
┌──────────────────────────────────────▼──────────────────────────┐
│  API TIER (Container: spectre-api)                              │
│  [FastAPI Application — OpenAPI 3.1 auto-generated spec]        │
│  ├── /scenarios      — CRUD for engagement scenarios            │
│  ├── /propagate      — Orbit propagation (sync or async)        │
│  ├── /manoeuvre       — Manoeuvre planning & Lambert solvers     │
│  ├── /access          — Sensor access & custody analysis        │
│  ├── /od              — Orbit determination filter runs          │
│  └── /health          — Liveness & readiness probes             │
└──────┬──────────────────────────────────────┬───────────────────┘
       │                                      │
       │ Internal                              │ Async tasks
┌──────▼──────────┐                  ┌────────▼──────────────────┐
│  DATA TIER      │                  │  WORKER TIER              │
│  (Container:    │                  │  (Container:              │
│  spectre-db)    │                  │  spectre-worker)          │
│                 │                  │                           │
│  PostgreSQL     │                  │  Celery / RQ / Dask       │
│  + Redis cache  │                  │  Long-running propagation │
│                 │                  │  Monte Carlo sweeps       │
│  Scenarios,     │                  │  OD batch processing      │
│  TLE cache,     │                  │                           │
│  results store  │                  │  Same Python environment  │
└─────────────────┘                  │  as spectre-api           │
                                     └───────────────────────────┘
```

### 4.2 Key Design Decisions

| # | Decision | Rationale | Alternatives considered |
|---|----------|-----------|----------------------|
| D1 | **FastAPI** as the API framework | Native OpenAPI 3.1 spec generation, async support, Pydantic validation, excellent Python ecosystem fit | Flask+apispec (less native OpenAPI), Django REST Framework (heavier than needed) |
| D2 | **Separate frontend and API containers** | Independent scaling, independent deployment, clean API contract, frontend can be swapped without touching compute | Monolith with templates (faster to start, harder to scale/maintain) |
| D3 | **Async worker for long computations** | Manoeuvre planning and Monte Carlo sweeps can take seconds to minutes; blocking the API thread is unacceptable for operator tempo | Synchronous-only with timeouts (simpler but limits operational utility) |
| D4 | **PostgreSQL for persistence, Redis for cache/queue** | Battle-tested, cloud-agnostic, managed service available on every provider | SQLite (no concurrency), MongoDB (unnecessary complexity for structured data) |
| D5 | **Helm chart for Kubernetes deployment** | Cloud-agnostic orchestration; Helm provides templated, versionable deployment manifests | Docker Compose (not production-grade for multi-cloud), Kustomize (less parameterised) |
| D6 | **Multi-stage Docker build** | Minimise image size; separate build dependencies (JVM/compilers) from runtime | Single-stage (bloated image, larger attack surface) |

---

## 5. OpenAPI Compatibility Plan

### 5.1 OpenAPI 3.1 Specification Strategy

SPECTRE's API will be **spec-first with FastAPI auto-generation**, meaning:

1. **Pydantic models define the contract.** Every request/response body is a Pydantic v2 model with explicit field types, units documentation, coordinate frame annotations, and examples.
2. **FastAPI auto-generates the OpenAPI 3.1 JSON/YAML spec** from route decorators and Pydantic models.
3. **The generated spec is committed to the repo** as a versioned artefact (`openapi.yaml`) and validated in CI.
4. **Consumers (frontend, C2 systems, allied tools) code-gen their clients** from the published spec.

### 5.2 API Domain Model — Resource Design

```
/api/v1/
├── /scenarios
│   ├── POST   — Create a new engagement scenario
│   ├── GET    — List scenarios (filtered, paginated)
│   └── /{id}
│       ├── GET    — Retrieve scenario detail
│       ├── PUT    — Update scenario
│       ├── DELETE — Remove scenario
│       └── /run   — POST: execute analysis (returns job ID)
│
├── /objects
│   ├── POST   — Register a space object (from TLE, state vector, or elements)
│   ├── GET    — List tracked objects
│   └── /{id}
│       ├── GET            — Object detail + current state
│       ├── /propagate     — POST: propagate to epoch or over time span
│       └── /elements      — GET: current orbital elements (classical, equinoctial, etc.)
│
├── /manoeuvres
│   ├── POST   — Plan a manoeuvre (Hohmann, Lambert, general delta-v)
│   └── /{id}  — GET: retrieve manoeuvre result
│
├── /access
│   ├── POST   — Compute access windows (object-to-sensor or object-to-object)
│   └── /{id}  — GET: retrieve access result
│
├── /od
│   ├── POST   — Submit observations for orbit determination
│   └── /{id}  — GET: retrieve OD solution (state + covariance)
│
├── /jobs
│   ├── GET        — List running/completed jobs
│   └── /{id}
│       ├── GET    — Job status + progress
│       ├── DELETE — Cancel job
│       └── /result — GET: retrieve computation result
│
├── /data
│   ├── /tle      — GET: cached TLE data; POST: upload TLEs
│   └── /eop      — GET: current EOP status; POST: trigger refresh
│
└── /health
    ├── /live      — GET: liveness (container is running)
    └── /ready     — GET: readiness (dependencies available, data loaded)
```

### 5.3 Pydantic Model Standards (OpenAPI Schema Quality)

Every model must enforce the numerical discipline rules from the astrodynamics persona:

```python
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from typing import Optional

class CoordinateFrame(str, Enum):
    """Explicit coordinate frame — no ambiguity at API boundaries."""
    GCRS = "GCRS"        # Geocentric Celestial Reference System
    ITRS = "ITRS"        # International Terrestrial Reference System
    TEME = "TEME"        # True Equator, Mean Equinox
    J2000 = "J2000"      # EME2000 / GCRS aligned
    EME2000 = "EME2000"

class TimeSystem(str, Enum):
    """Explicit time system — mixing UTC and TT is a defect."""
    UTC = "UTC"
    TT = "TT"
    TAI = "TAI"
    TDB = "TDB"
    UT1 = "UT1"
    GPS = "GPS"

class StateVector(BaseModel):
    """Cartesian state vector with mandatory frame and units metadata."""
    epoch: datetime = Field(..., description="State epoch")
    time_system: TimeSystem = Field(..., description="Time system of the epoch")
    frame: CoordinateFrame = Field(..., description="Reference frame")
    position_km: list[float] = Field(
        ..., min_length=3, max_length=3,
        description="Position vector [x, y, z] in kilometres"
    )
    velocity_km_s: list[float] = Field(
        ..., min_length=3, max_length=3,
        description="Velocity vector [vx, vy, vz] in km/s"
    )

    model_config = {"json_schema_extra": {
        "examples": [{
            "epoch": "2026-04-12T12:00:00Z",
            "time_system": "UTC",
            "frame": "GCRS",
            "position_km": [6778.0, 0.0, 0.0],
            "velocity_km_s": [0.0, 7.668, 0.0]
        }]
    }}

class PropagationRequest(BaseModel):
    """Request to propagate a space object."""
    object_id: str = Field(..., description="Tracked object identifier")
    start_epoch: datetime
    end_epoch: datetime
    time_system: TimeSystem = Field(default=TimeSystem.UTC)
    output_frame: CoordinateFrame = Field(default=CoordinateFrame.GCRS)
    step_size_seconds: float = Field(default=60.0, gt=0)
    force_model: Optional[str] = Field(
        default="default",
        description="Force model config name — see /config/force-models"
    )

class PropagationResult(BaseModel):
    """Propagation output with full provenance."""
    job_id: str
    object_id: str
    frame: CoordinateFrame
    time_system: TimeSystem
    force_model_description: str = Field(
        ..., description="Human-readable force model config used"
    )
    ephemeris: list[StateVector]
    computation_time_ms: float
    integrator_steps: int
    warnings: list[str] = Field(default_factory=list)
```

### 5.4 OpenAPI Spec Validation in CI

```yaml
# .github/workflows/openapi-validate.yml (conceptual)
steps:
  - name: Generate OpenAPI spec
    run: python -c "from spectre.api.app import app; import json; print(json.dumps(app.openapi()))" > openapi.json

  - name: Validate spec (spectral)
    run: npx @stoplight/spectral-cli lint openapi.json --ruleset .spectral.yaml

  - name: Check backward compatibility (oasdiff)
    run: oasdiff breaking openapi-baseline.json openapi.json

  - name: Commit spec as artefact
    run: cp openapi.json docs/api/openapi.json
```

### 5.5 API Versioning Strategy

| Aspect | Decision |
|--------|----------|
| **Versioning scheme** | URL path prefix: `/api/v1/`, `/api/v2/` |
| **Breaking change policy** | New major version; old version supported for minimum 6 months |
| **Non-breaking additions** | New optional fields, new endpoints — no version bump |
| **Deprecation signalling** | `Sunset` HTTP header + `deprecated: true` in OpenAPI spec |
| **Spec diffing** | `oasdiff` in CI pipeline catches unintentional breaking changes |

---

## 6. Containerisation Plan

### 6.1 Container Image Strategy

#### spectre-api / spectre-worker (shared base)

```dockerfile
# --- Stage 1: Build ---
FROM python:3.12-slim AS builder
# Note: Python 3.14 not yet in stable Docker images as of 2026-04;
# use 3.12 now, upgrade when 3.14-slim is GA.
# ⚠ Assumption A5: orekit requires JVM

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gfortran \
    default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY src/ src/

# --- Stage 2: Runtime ---
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r spectre && useradd -r -g spectre spectre

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src /app/src
COPY config/ /app/config/

ENV PATH="/app/.venv/bin:$PATH"
ENV SPECTRE_CONFIG_DIR="/app/config"

USER spectre

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health/live').raise_for_status()"

EXPOSE 8000
CMD ["uvicorn", "spectre.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### spectre-ui (frontend)

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### 6.2 Container Image Sizing Targets

| Image | Target size | Key drivers |
|-------|-------------|-------------|
| spectre-api | < 1.5 GB | JRE (~200 MB), Python scientific stack (~600 MB), astro data files |
| spectre-worker | Same base as api | Shares image, different CMD |
| spectre-ui | < 50 MB | Static SPA + Nginx |
| spectre-db | Use official postgres:16-alpine | ~80 MB |
| redis | Use official redis:7-alpine | ~30 MB |

### 6.3 Cloud-Agnostic Design Principles

| Principle | Implementation |
|-----------|---------------|
| **No cloud-specific SDKs in application code** | All cloud interaction via environment variables and standard protocols (S3-compatible, PostgreSQL wire protocol, HTTP) |
| **Container registry agnostic** | CI pushes to OCI-compliant registry; Helm values parameterise registry URL |
| **Secrets via environment or mounted files** | Never baked into image; compatible with K8s Secrets, Vault, AWS Secrets Manager, Azure Key Vault |
| **Storage via PersistentVolumeClaim** | TLE/EOP data cached on persistent volume; CSI driver is cloud-specific but transparent to the app |
| **Ingress via standard K8s Ingress or Gateway API** | No cloud-specific load balancer annotations in the app; handled in Helm values per environment |
| **Observability via OpenTelemetry** | OTLP export to any backend (Grafana, Datadog, CloudWatch, Azure Monitor) |

### 6.4 Helm Chart Structure

```
spectre-helm/
├── Chart.yaml
├── values.yaml                    # Defaults (dev/local)
├── values-aws.yaml                # AWS-specific overrides
├── values-azure.yaml              # Azure-specific overrides
├── values-gcp.yaml                # GCP-specific overrides
├── templates/
│   ├── _helpers.tpl
│   ├── api-deployment.yaml
│   ├── api-service.yaml
│   ├── api-hpa.yaml               # Horizontal Pod Autoscaler
│   ├── worker-deployment.yaml
│   ├── worker-hpa.yaml
│   ├── ui-deployment.yaml
│   ├── ui-service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml             # Force model configs, feature flags
│   ├── secrets.yaml               # External secret references
│   ├── pvc-data.yaml              # TLE/EOP cache volume
│   ├── postgresql.yaml            # Or subchart reference
│   ├── redis.yaml                 # Or subchart reference
│   └── tests/
│       └── test-api-health.yaml
```

### 6.5 Local Development with Docker Compose

```yaml
# docker-compose.yml — local development parity
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://spectre:dev@db:5432/spectre
      - REDIS_URL=redis://redis:6379/0
      - SPECTRE_LOG_LEVEL=DEBUG
    volumes:
      - ./src:/app/src         # Hot reload
      - tle-cache:/data/tle
    depends_on: [db, redis]

  worker:
    build: .
    command: celery -A spectre.worker worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://spectre:dev@db:5432/spectre
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - tle-cache:/data/tle
    depends_on: [db, redis]

  ui:
    build: ./frontend
    ports: ["3000:80"]

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: spectre
      POSTGRES_USER: spectre
      POSTGRES_PASSWORD: dev
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

volumes:
  pgdata:
  tle-cache:
```

---

## 7. Cross-Cutting Concerns

### 7.1 Observability

| Layer | Tool | Standard |
|-------|------|----------|
| Structured logging | `structlog` → JSON | OpenTelemetry log bridge |
| Distributed tracing | OpenTelemetry SDK (Python) | OTLP export |
| Metrics | Prometheus client (`prometheus_client`) | `/metrics` endpoint |
| Dashboards | Grafana (cloud-agnostic) | Helm subchart or managed |
| Alerting | Grafana Alertmanager or cloud-native | SLO-based burn-rate alerts |

### 7.2 Security

| Concern | Approach |
|---------|----------|
| **API authentication** | OAuth 2.0 / OIDC bearer tokens (compatible with any IdP) |
| **API authorisation** | RBAC middleware in FastAPI; roles: operator, analyst, admin |
| **Container scanning** | Trivy in CI; block critical/high CVEs |
| **Network policy** | K8s NetworkPolicy: API ↔ DB only, Worker ↔ DB + Redis only, UI → API only |
| **Secrets** | External Secrets Operator (K8s) → any backend (Vault, AWS SM, Azure KV) |
| **TLS** | Terminated at Ingress; internal mTLS via service mesh if required |
| **Image signing** | Cosign / Notation for supply chain integrity |

### 7.3 Data Management

| Data | Storage | Lifecycle |
|------|---------|-----------|
| TLE cache | PersistentVolume + Redis hot cache | Daily refresh; TTL warnings per regime (LEO 24h, GEO 72h) |
| EOP data | PersistentVolume | Weekly refresh from IERS; stale warning in API response headers |
| Planetary ephemerides | Baked into image or PV | Pinned version (DE440); checksum validated at startup |
| Scenario data | PostgreSQL | User-managed; soft delete with retention policy |
| Computation results | PostgreSQL + object store for large ephemerides | TTL-based expiry; configurable |
| Gravity models | Baked into image | Versioned; truncation level in config |

---

## 8. Implementation Phases

### Phase 0 — Assessment & Preparation (Week 1–2)

| # | Action | Deliverable | Effort |
|---|--------|-------------|--------|
| 0.1 | Audit current SPECTRE codebase: module structure, entry points, dependencies | Dependency graph + module map | S |
| 0.2 | Identify all I/O boundaries (file reads, network calls, user input, output formats) | I/O boundary register | S |
| 0.3 | Pin all dependencies with `uv lock` or `pip-compile` | `uv.lock` / `requirements.txt` | XS |
| 0.4 | Confirm orekit-python JVM requirement; evaluate replacement feasibility | Go/no-go decision on JVM in container (updates A5) | M |
| 0.5 | Define force model configuration schema (TOML/YAML) | `force_models.toml` template | S |
| 0.6 | Establish golden-value test baseline for core computations | `tests/golden/` directory with known-truth outputs | M |

### Phase 1 — API Layer (Week 3–5)

| # | Action | Deliverable | Effort |
|---|--------|-------------|--------|
| 1.1 | Install FastAPI; create app skeleton with health endpoints | `/health/live`, `/health/ready` responding | XS |
| 1.2 | Define Pydantic models for all domain objects (StateVector, OrbitalElements, Scenario, etc.) | `spectre/api/models/` package | M |
| 1.3 | Wrap core propagation functions as `/objects/{id}/propagate` endpoint | Working propagation via API | M |
| 1.4 | Wrap manoeuvre planning as `/manoeuvres` endpoint | Working Lambert/Hohmann via API | M |
| 1.5 | Add async job infrastructure (Celery/RQ + Redis) for long-running computations | `/jobs/{id}` status polling | M |
| 1.6 | Extract and commit `openapi.json`; add CI validation (Spectral + oasdiff) | Versioned OpenAPI spec in repo | S |
| 1.7 | Add OpenTelemetry instrumentation to API and propagation hot paths | Traces and timing metrics | S |

### Phase 2 — Containerisation (Week 5–7)

| # | Action | Deliverable | Effort |
|---|--------|-------------|--------|
| 2.1 | Write multi-stage Dockerfile for spectre-api/worker | Working container image | M |
| 2.2 | Write Dockerfile for spectre-ui (if frontend exists) | Working UI container | S |
| 2.3 | Create `docker-compose.yml` for local development | Full stack runs locally with `docker compose up` | S |
| 2.4 | Validate all astrodynamics computations produce identical results in container vs bare metal | Container golden-value test pass | M |
| 2.5 | Add Trivy container scanning to CI | No critical/high CVEs in image | XS |
| 2.6 | Measure container startup time and image size; optimise if outside targets | Image size report | S |

### Phase 3 — Kubernetes & Cloud-Agnostic Deployment (Week 7–9)

| # | Action | Deliverable | Effort |
|---|--------|-------------|--------|
| 3.1 | Create Helm chart with templates for all components | `spectre-helm/` chart | M |
| 3.2 | Create `values-{cloud}.yaml` for AWS, Azure, GCP | Cloud-specific overrides | S |
| 3.3 | Deploy to first target cloud; validate end-to-end | Working cloud deployment | L |
| 3.4 | Configure HPA for API and worker pods | Autoscaling tested under load | M |
| 3.5 | Implement NetworkPolicy for pod-to-pod isolation | Security validated | S |
| 3.6 | Set up External Secrets Operator for secrets management | No plaintext secrets in cluster | S |
| 3.7 | Deploy OpenTelemetry Collector + Grafana dashboards | Observability stack operational | M |

### Phase 4 — Hardening & Validation (Week 9–11)

| # | Action | Deliverable | Effort |
|---|--------|-------------|--------|
| 4.1 | Load test API under realistic operator tempo (concurrent scenarios) | Performance baseline | M |
| 4.2 | Validate propagation accuracy in cloud matches local golden values | Accuracy regression report | S |
| 4.3 | DR test: kill pods, verify recovery and data integrity | DR runbook validated | M |
| 4.4 | Penetration test / threat model review of API surface | Security findings report | L |
| 4.5 | Document operational runbook (top 10 alert types, triage steps) | Runbook v1 | M |
| 4.6 | Deploy to second cloud provider to validate portability | Multi-cloud portability confirmed | L |

---

## 9. Risk Register

| # | Risk | Severity | Likelihood | Mitigation |
|---|------|----------|------------|------------|
| R1 | Orekit JVM dependency bloats container image and complicates builds | Medium | High | Evaluate replacing orekit with poliastro/beyond for required functions; if not feasible, accept JVM layer and optimise with JRE-headless |
| R2 | Numerical results differ between Windows bare metal and Linux container | High | Medium | Golden-value regression tests run on both platforms in CI; investigate any delta > machine epsilon × expected growth factor |
| R3 | JAX GPU requirement emerges mid-project | Medium | Low | Design container for CPU-first; GPU support is a node pool + Dockerfile variant, not an architecture change |
| R4 | Python 3.14 not available as stable Docker base image | Low | High | Use Python 3.12 now (stable, well-supported); upgrade when 3.14-slim ships. All code should be 3.12+ compatible. |
| R5 | Large ephemeris files (DE440 ~100 MB) in container image slow pulls | Low | Medium | Store on PersistentVolume, not in image; init container downloads on first deploy |
| R6 | Operator latency expectations not met by containerised deployment | High | Medium | Profile end-to-end in Phase 4; pre-warm containers; use Redis caching for repeated queries; async for long-running computations |
| R7 | OpenAPI spec drift between implementation and published spec | Medium | Medium | CI gate: auto-generate spec on every PR, diff against committed baseline, fail on undocumented changes |
| R8 | Cloud-specific features leak into application code despite design intent | Medium | Medium | Architecture review gate: no cloud SDK imports outside `spectre/infra/` adapter layer; enforce via import linter |

---

## 10. Operational Readiness Checklist (Target State)

- [ ] All SPECTRE containers build reproducibly from a single `git clone && docker compose build`
- [ ] OpenAPI 3.1 spec is auto-generated, validated, and version-controlled
- [ ] Golden-value astrodynamics tests pass in container environment
- [ ] Health endpoints (`/health/live`, `/health/ready`) are wired to Kubernetes probes
- [ ] Structured JSON logging with correlation IDs on all API requests
- [ ] OpenTelemetry traces cover propagation, manoeuvre, and OD code paths
- [ ] No critical/high CVEs in any container image (Trivy scan in CI)
- [ ] Network policies restrict pod-to-pod communication to required paths only
- [ ] Secrets managed via External Secrets Operator (no plaintext in manifests)
- [ ] HPA configured and tested for API and worker deployments
- [ ] DR tested: pod failure, node failure, data persistence across restarts
- [ ] Helm chart deployable to at least two cloud providers without code changes
- [ ] Runbook covers top 10 operational scenarios
- [ ] Force model configuration is externalised (TOML/YAML), not hard-coded
- [ ] TLE/EOP data freshness monitored with alerting on stale data

---

## 11. Next Steps (Prioritised)

1. **Answer Q1–Q5 (Section 3)** — These answers will refine or invalidate assumptions A1–A6 and may reshape the architecture. — Est. effort: **XS** (conversation)
2. **Phase 0.1: Audit current codebase** — Map modules, dependencies, and I/O boundaries to validate the proposed container topology. — Est. effort: **S**
3. **Phase 0.4: Orekit go/no-go** — Determine whether JVM is required in the container; this is the single biggest driver of container complexity. — Est. effort: **M**
4. **Phase 0.6: Establish golden-value baseline** — Before any refactoring, capture known-good outputs so we can detect regressions from containerisation. — Est. effort: **M**
5. **Phase 1.1–1.2: FastAPI skeleton + Pydantic models** — Start building the API contract; this can proceed in parallel with Phase 0 answers. — Est. effort: **M**

---

## Appendix A: Session Artefacts

### A.1 Mission Log

**Overall objective:** Make SPECTRE OpenAPI-compliant and container-deployable on any cloud provider.  
**Last updated:** 2026-04-12

**Constraints:**
- Pure Python astrodynamics stack (no COTS orbital tools)
- Must support rapid operator decision-making tempo
- Unclassified environment
- Cloud-provider agnostic

**Decisions Made:**

| # | Decision | Rationale | Date | Reversible? |
|---|----------|-----------|------|-------------|
| 1 | FastAPI for API framework | Native OpenAPI 3.1, async, Pydantic validation | 2026-04-12 | Yes (early stage) |
| 2 | Kubernetes as orchestration target | Cloud-agnostic; Helm for parameterised deployment | 2026-04-12 | Yes (Docker Compose fallback) |
| 3 | Separate frontend and API containers | Independent scaling and deployment | 2026-04-12 | Yes |
| 4 | OpenTelemetry for observability | Vendor-agnostic; OTLP export to any backend | 2026-04-12 | Yes |

**Open Questions:**
- [ ] Q1–Q5 from Section 3 — all impact architecture materially

### A.2 Architecture Snapshot

**Current state:** Assumed monolithic Python application, no existing API surface, no containerisation.

**Core Dependencies (planned):**

| Library | Version | Used For | Licence |
|---------|---------|----------|---------|
| FastAPI | 0.115+ | API framework + OpenAPI generation | MIT |
| Pydantic | 2.x | Request/response validation | MIT |
| Uvicorn | 0.30+ | ASGI server | BSD |
| Celery / RQ | Latest | Async task queue | BSD / BSD |
| structlog | 24.x+ | Structured logging | MIT / Apache 2.0 |
| opentelemetry-sdk | 1.x | Tracing + metrics | Apache 2.0 |
| astropy | 6.x+ | Coordinates, time, units | BSD |
| sgp4 | 2.x | TLE propagation | MIT |
| poliastro | 0.17+ | Orbit mechanics | MIT |
| orekit-python | TBD | High-fidelity propagation, OD | Apache 2.0 (⚠ JVM) |

### A.3 Change Ledger

| # | What Changed | Why | Session | Risk/Impact |
|---|-------------|-----|---------|-------------|
| 1 | Created initial OpenAPI + containerisation plan | First session — establishing baseline architecture | 2026-04-12 | Plan is assumption-heavy; needs Q1–Q5 answers to firm up |
