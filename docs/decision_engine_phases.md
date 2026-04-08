# Decision Engine — Phase Roadmap

*Last updated: 2026-04-08*

---

## Current State: Phase 1 (Deterministic)

**Status: ✅ Complete and in production**

Phase 1 evaluates a user-defined grid of adversary actions × friendly responses using deterministic analytic estimates and a weighted composite scoring function.

### What Phase 1 does

- Operator enters N adversary actions (type, probability, confidence) and M friendly responses (type, cost, reversibility, time-to-execute)
- Engine computes an N × M outcome matrix; each cell contains:
  - `composite_score` (weighted sum, lower = better for friendly)
  - `custody_maintained` (bool — can friendly satellite keep track?)
  - `closest_approach_km` (minimum separation during horizon — analytic SMA-difference approximation)
  - `time_to_intercept_h`, `delta_v_cost_km_s` (analytic estimates from orbital mechanics rules of thumb)
- Three selector strategies: **Minimax** (minimise worst-case), **Expected Value** (probability-weighted), **Maximin** (maximise best-case)
- Results: robust recommendation banner + full outcome matrix + per-adversary ranked response cards

### Key files

| File | Role |
|------|------|
| `sipc/domain/decision.py` | Core data model + `evaluate_scenario()` |
| `sipc/web/routes/decision.py` | `GET /plan/decision/panel`, `POST /plan/decision/evaluate` |
| `sipc/web/templates/partials/decision_panel.html` | Scenario builder form |
| `sipc/web/templates/partials/decision_results.html` | Outcome matrix + recommendation |

### Known Phase 1 limitations

- Outcome metrics are **analytic estimates**, not SGP4 propagations (closest approach via SMA difference approximation)
- Adversary actions have no manoeuvre hypothesis — all actions are treated as constant-SMA from a propagation standpoint
- No uncertainty — single deterministic outcome per (adversary, response) pair
- ΔV cost is estimated from orbital mechanics rules of thumb, not simulated

---

## Phase 2: Monte Carlo Integration

**Status: Next sprint**

**Dependency:** `sipc/astro/monte_carlo.py` (already built and tested)

### What changes

- `AdversaryAction` gains an optional `hypothesis: ManoeuvreHypothesis` field (from `monte_carlo.py`)
- When a hypothesis is attached, `compute_outcome_metrics()` replaces the analytic estimate with a Monte Carlo run:
  - Samples N realisations of the adversary manoeuvre (perturbed ΔV, timing, pointing)
  - Propagates each sample forward via RK45 + J2 + drag
  - Computes closest approach for each realisation → distribution
  - Returns `closest_approach_km_p5`, `closest_approach_km_p50`, `closest_approach_km_p95`
- `OutcomeMetrics` gains `ca_percentiles: dict[int, float]` and `ca_std_km: float`
- Scoring uses the P95 closest approach (conservative) instead of the point estimate
- `ScenarioResult` gains `monte_carlo_runs: int`, `mc_wall_time_s: float`

### UI additions

- Decision panel: "Adversary Manoeuvre Hypothesis" collapsible section per action row
  - ΔV magnitude (km/s), RIC direction, uncertainty σ, archetype dropdown (from `MANOEUVRE_ARCHETYPES`)
  - n_samples slider (100–2000, default 500)
- Results: outcome matrix cells show P5–P95 band instead of single score; hover tooltip shows full percentile distribution
- New "Uncertainty" column in per-adversary rankings showing σ of composite score across MC runs

### Implementation steps

1. Add `hypothesis: ManoeuvreHypothesis | None = None` to `AdversaryAction`
2. Update `compute_outcome_metrics()` to branch on `hypothesis` presence
3. Add `ca_percentiles` / `ca_std_km` to `OutcomeMetrics`
4. Update `decision_panel.html` with per-row hypothesis accordion
5. Update `decision_results.html` to show P5/P50/P95 bands in cells
6. Add `hypothesis_*` form fields to `decision_evaluate` route

---

## Phase 3: SGP4-Propagated Outcomes

**Status: After Phase 2**

**Dependency:** Phase 2 complete; both red and blue TLEs available in session state

### What changes

- Replace analytic closest-approach estimate with full SGP4 propagation:
  - Start from red TLE at scenario epoch
  - Apply adversary manoeuvre hypothesis (sampled from MC)
  - Propagate both objects to horizon; compute actual minimum separation via `TLEOrbit.propagate()`
  - Apply response ΔV to blue TLE; propagate; recompute separation
- `OutcomeMetrics.custody_maintained` becomes a true SGP4 result (line-of-sight check at each step)
- Enables time-of-closest-approach (TCA) calculation

### UI additions

- TCA timestamp shown in each outcome matrix cell (tooltip)
- "Show Trajectory" button per outcome cell → opens the Hill-frame CW geometry visualiser for that (adversary, response) pair
- Summary: TCA distribution histogram (Chart.js) for the selected best response

### Implementation steps

1. Add `propagate_outcome()` in `decision.py` — wraps `TLEOrbit.propagate()`
2. Require `blue_tle` and `red_tle` in `evaluate_scenario()` for Phase 3 path
3. Add TCA to `OutcomeMetrics`
4. Wire "Show Trajectory" button → `POST /plan/geometry/intercept` with cell parameters

---

## Phase 4: Multi-Turn Adversary Modelling

**Status: After Phase 3**

**Dependency:** Phase 3 complete

### What changes

- Scenarios become sequential: adversary may respond to a friendly response with a second action
- `Scenario` gains a `turns: int` field (default 1; Phase 4 enables 2–3)
- Game tree: depth-first search over adversary → friendly → adversary → friendly chains
- Minimax becomes full recursive minimax tree search
- Expected Value selector uses Bayesian update of adversary probabilities after observing first-turn outcome

### UI additions

- "Turn depth" selector (1–3) in scenario builder
- D3.js collapsible game tree showing branch scores (`decision_gametree.html`)
- Per-turn recommendation sequence: "Turn 1: Collision avoidance → if adversary persists → Turn 2: Repositioning"

### Implementation steps

1. `Scenario.turns` field + recursive `evaluate_turn()` helper
2. `GameNode` dataclass (action, response, children, subtree_score)
3. D3.js tree partial (`decision_gametree.html`)
4. Route: add `turns` form field to `POST /plan/decision/evaluate`

---

## Phase 5: NOTSO-Informed Priors

**Status: Parallel development alongside Phase 3/4**

**Dependency:** `sipc/data/notso_cache.py` (already built); `sipc/astro/notso.py` (already built)

### What changes

- If NOTSO records exist for the adversary satellite (via `notso_cache.py`), prior probabilities on adversary actions are seeded from historical NOTSO type distribution
  - e.g. 8 of last 10 NOTSOs for this object were `MANOEUVRE` → P(manoeuvre) = 0.8 as default
- `OperatorBehaviourProfile` (from `sipc/astro/notso.py`) feeds `AdversaryAction.probability` defaults
- After scenario evaluation, NOTSO-derived confidence intervals shown in results

### UI additions

- "Load from NOTSO" button in adversary action rows → auto-fills probability + confidence from cache
- In results: NOTSO history mini-timeline per adversary action row

---

## Summary Table

| Phase | Core capability | Key new data | Status |
|-------|----------------|--------------|--------|
| **1** | Deterministic analytic scoring | `OutcomeMetrics` (analytic) | ✅ Complete |
| **2** | Monte Carlo uncertainty on adversary manoeuvre | `ManoeuvreHypothesis`, P5/P50/P95 bands | Next sprint |
| **3** | SGP4-propagated outcomes + TCA | `propagate_outcome()`, TCA timestamp | After Phase 2 |
| **4** | Multi-turn game tree | `GameNode`, recursive minimax | After Phase 3 |
| **5** | NOTSO-informed priors | `OperatorBehaviourProfile` integration | Parallel with Phase 3/4 |

---

## Build order

```
Phase 2 (MC) → Phase 3 (SGP4) → Phase 5 (NOTSO priors, parallel with 3)
                              → Phase 4 (multi-turn)
```

Phase 2 is the highest value add: it converts the engine from a calculator into an uncertainty-aware tool. Phase 3 grounds the results in real physics. Phase 4 is the most complex and should only start once Phase 3 validation is complete.
