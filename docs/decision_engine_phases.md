# Decision Engine — Phase Roadmap

*Last updated: 2026-04-08. Plan status 2026-10-28 below.*

**Plan status, 2026-10-28.** The owner ruled to invest in every phase. The build plan is `.board/items.json`, SPC-100 to
SPC-152, summarised in `.board/README.md`. It corrects three points in the phases below:
● Phase 2 needs the blue element set: `MonteCarloResult` holds element statistics at the horizon, not trajectories, so
  closest approach needs a separation series.
● Score on the P5 closest approach, not P95: for a miss distance the conservative figure is the smallest one.
● The Phase 4 tree is server-rendered rather than D3.js, which is not vendored.
Foundation work comes first: scenarios bound to real element sets, a basis on every figure, and reference cases.
Gate for Phase 2 (SPC-110) and Phase 3 (SPC-120): tests/unit/test_decision_reference_cases.py passes with that phase's
path added to PATHS, at both window starts (SPC-102).

---

## Current State: Phase 1 (Deterministic)

**Status: ✅ Complete and in production**

Phase 1 evaluates a user-defined grid of adversary actions × friendly responses using deterministic analytic estimates and a weighted composite scoring function.

### What Phase 1 does

- Operator enters N adversary actions (type, probability, confidence) and M friendly responses (type, cost, reversibility, time-to-execute)
- Engine computes an N × M outcome matrix; each cell contains:
  - `composite_score` (weighted sum of custody, closest approach and our delta-V with the response's time to execute
    and reversibility; lower = better for friendly)
  - `custody_maintained` and `custody_gap_hours` (a rule of thumb, not the held, degraded or lost custody on the sweep)
  - `closest_approach_km` (a fixed 200, 3,000, 5,000 or 10,000 km per adversary action type, raised by response cost;
    no orbit propagated)
  - `time_to_closest_hours` (0.4 of the horizon) and `delta_v_cost_km_s` (response cost x 0.05 km/s for a manoeuvre)
- Every figure states its own basis (SPC-101): `OutcomeMetrics.figure_bases` holds a `FigureBasis` per figure, of kind
  lookup, sampled or computed, with the rule behind it. In Phase 1 every figure is a lookup. The score's basis is
  derived from the figures its formula uses and is held at lookup by its scoring rule, so the modelled badge stays
  while the ranking is a weighted heuristic. Later releases set a figure's kind through `outcome_bases()` and the page
  marks it in its own cell.
- A scenario may be bound to one held red track and one held blue asset (SPC-100). The binding records which real
  objects the scenario is about, puts their element sets in the result's provenance and shows each orbit's epoch and
  age at evaluation against its regime's limit (72 h for GEO and deep space, 24 h otherwise) in a "Bound to" block.
  On its own it changes no figure: `compute_outcome_metrics` and `find_robust_response` never read it, and a test
  pins that. Only `plan_sampling` reads it, for a row whose action carries a hypothesis (SPC-112, below).
- Three selector strategies: **Minimax** (minimise worst-case), **Expected Value** (probability-weighted), **Minimin** (optimistic, best best case; renamed from "Maximin", which named the cautious rule it did not implement)
- Results: modelled-recommendation banner ("Modelled estimate, not a computed solution") with a basis line per figure,
  a "(lookup)" mark on each closest approach and custody in the outcome matrix, and per-adversary ranked response cards

### Key files

| File | Role |
|------|------|
| `spectre/domain/decision.py` | Core data model + `evaluate_scenario()` |
| `spectre/web/routes/decision.py` | `GET /plan/decision/panel`, `GET /plan/decision/bind`, `POST /plan/decision/evaluate` |
| `spectre/web/decision_binding.py` | Binds a scenario to held objects and reads each element set's age (SPC-100) |
| `spectre/web/templates/partials/decision_panel.html` | Scenario builder form |
| `spectre/web/templates/partials/decision_results.html` | Outcome matrix + recommendation |

### Known Phase 1 limitations

- Outcome metrics are **lookup estimates**, not SGP4 propagations (closest approach is a constant per action type)
- An adversary action may carry a manoeuvre hypothesis (SPC-111, Phase 2 step 1). On its own it changes no figure;
  in a scenario bound on both sides its row's closest approach and time to closest approach are sampled (SPC-112),
  and every other figure, custody included, is still a lookup
- No uncertainty — single deterministic outcome per (adversary, response) pair
- ΔV cost is estimated from orbital mechanics rules of thumb, not simulated

---

## Phase 2: Monte Carlo Integration

**Status: Next sprint**

**Dependency:** `spectre/astro/monte_carlo.py` (already built and tested)

### What changes

- `AdversaryAction` gains an optional `hypothesis: ManoeuvreHypothesis` field (from `monte_carlo.py`)
- When a hypothesis is attached, `compute_outcome_metrics()` replaces the analytic estimate with a Monte Carlo run:
  - Samples N realisations of the adversary manoeuvre (perturbed ΔV, timing, pointing)
  - Propagates each sample forward via RK45 + J2 + drag
  - Computes closest approach for each realisation → distribution
  - Returns `closest_approach_km_p5`, `closest_approach_km_p50`, `closest_approach_km_p95`
- `OutcomeMetrics` gains `ca_percentiles: dict[int, float]` and `ca_std_km: float`
- Scoring uses the P5 closest approach (conservative: the smallest-miss tail) instead of the point estimate
- `ScenarioResult` gains `monte_carlo_runs: int`, `mc_wall_time_s: float`

### UI additions

- Decision panel: "Adversary Manoeuvre Hypothesis" collapsible section per action row
  - ΔV magnitude (km/s), RIC direction, uncertainty σ, archetype dropdown (from `MANOEUVRE_ARCHETYPES`)
  - n_samples slider (100–2000, default 500)
- Results: outcome matrix cells show P5–P95 band instead of single score; hover tooltip shows full percentile distribution
- New "Uncertainty" column in per-adversary rankings showing σ of composite score across MC runs

### Implementation steps

1. Add `hypothesis: ManoeuvreHypothesis | None = None` to `AdversaryAction`. Done in SPC-111 as
   `hypothesis: AdversaryHypothesis | None = None`, a frozen carrier holding the `ManoeuvreHypothesis` with its
   source (archetype, entered or detected), archetype name and direction frame and basis. It is checked when built
   and recorded in the result's provenance; `compute_outcome_metrics` and `find_robust_response` do not read it,
   and a tripwire test pins that the lookup path never does.
2. Update `compute_outcome_metrics()` to branch on `hypothesis` presence. Done in SPC-112 beside it instead:
   `compute_outcome_metrics` stays lookup-only, and `evaluate_scenario` fills a row from `plan_sampling` when its
   action carries a hypothesis and the scenario is bound to a red track and a blue asset. Each such row runs one
   separation series (shared by all its response cells) and scores on its P5, with its time to closest approach the
   earliest TCA at or below P5; both figures say they are sampled, naming samples, horizon and propagator, and the
   score's basis stays lookup. A row is refused, with a sentence in each of its cells ending "This cell's figures are
   lookups.", for fewer than 50 samples, an orbit not current, a red element set newer than the burn (it may already
   include the burn, which would then be applied twice; the start check cannot see this, because an impulsive burn
   leaves position continuous), an element set that cannot be propagated, a hypothesis starting more than 10 km from
   the bound red track, a failed sample or an unconverged series. The cost is capped before anything runs at
   `MAX_SAMPLE_HOURS` (600): a row costs the larger of its samples times the horizon and the hours its series
   integrates, which counts a burn before the window, plus 9 minutes (`SET_UP_S_PER_SAMPLE`) for each sample's
   solve_ivp set-up and closest-approach search. Without that term 20,000 samples over 0.028 h counted 560 and ran
   for 49 s. A row whose floor (samples times horizon and set-up) is already over the cap is refused without drawing
   its samples, and an over-cap refusal names the longest horizon, in tenths of an hour, that would fit. The largest
   allowed evaluation measured 6.3 to 9.0 s on one idle thread, from 50 samples over 11.3 h to 3,500 over 0.02 h
   (the cases are listed in `_cost`). The route runs the evaluation on a worker thread, so other sessions carry on,
   but the operator's own request waits for all of it until SPC-113 adds a time budget. Sampling converges only in a narrow band under the cap: in
   the LEO 300 km measurements, 1,000 samples over 0.44 h and more over shorter horizons converged, while every case
   with the burn in or before a window of 1 h or more (50 to 500 samples) was refused as not converged after the
   full wait, so the unconverged refusal says to take more samples with a shorter horizon. Our response is not
   applied to the blue orbit yet, and the 50,000 km normalisation lets the sampled spread move a score by at most
   w_ca x (P95 - P5) / 50,000, which the page states.
3. Add `ca_percentiles` / `ca_std_km` to `OutcomeMetrics`. Done in SPC-112, with `ca_samples`, `ca_refusal` and
   `ca_caveat`; an invariant sets the band exactly when the closest approach is sampled and pins it to P5.
4. Update `decision_panel.html` with per-row hypothesis accordion
5. Update `decision_results.html` to show P5/P50/P95 bands in cells. Done minimally in SPC-112: a sampled cell
   says sampled, prints closest approach to 0.1 km and shows P5 to P95 with the median; a refused cell shows its
   sentence; the full UI is SPC-115.
6. Add `hypothesis_*` form fields to `decision_evaluate` route
7. Gate: tests/unit/test_decision_reference_cases.py passes with this phase's path added to PATHS, at both window starts (SPC-102).
   Passed by SPC-110's `monte_carlo_nominal`: `run_separation_series` in `spectre/astro/monte_carlo.py` gives each
   sample's closest approach to the blue track through the shared helper, with P5, P50 and P95 of the misses and the
   engine's convergence check. Blue is propagated with the same RK45, J2 and drag model as red, from its SGP4 state at
   the window start; with blue on SGP4 the GEO case missed its TCA by 1,951 s against a 60 s tolerance. Every arc stops
   at `REENTRY_FLOOR_KM` (100 km): a sample that crosses it is counted failed and re-entered, never given a miss from
   inside the Earth. A series costs what it integrates, not its window: `separation_integration_s` counts each
   sample's look-back from its burn, so SPC-112's cap counts integrated hours as well as samples times the horizon.
   SPC-112 scores a bound row with a hypothesis from the series (step 2 above).

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
5. Gate: tests/unit/test_decision_reference_cases.py passes with this phase's path added to PATHS, at both window starts (SPC-102).
6. Carry TCA unrounded with the edge flag; decision.py:462 rounds time_to_closest_hours to 0.01 h, coarser than the
   plane-change tolerance, and the results page shows closest approach in whole km (decision_results.html:121).

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

**Dependency:** `spectre/data/notso_cache.py` (already built); `spectre/astro/notso.py` (already built)

### What changes

- If NOTSO records exist for the adversary satellite (via `notso_cache.py`), prior probabilities on adversary actions are seeded from historical NOTSO type distribution
  - e.g. 8 of last 10 NOTSOs for this object were `MANOEUVRE` → P(manoeuvre) = 0.8 as default
- `OperatorBehaviourProfile` (from `spectre/astro/notso.py`) feeds `AdversaryAction.probability` defaults
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
