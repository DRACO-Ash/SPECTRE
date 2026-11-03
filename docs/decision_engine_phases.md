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
   the bound red track, a hypothesis starting more than 100 m/s from the bound red track's velocity (SPC-116), a
   failed sample (naming how many re-entered below 100 km) or an unconverged series. The velocity check is coarse on
   purpose: element-set error alone allows about 11 m/s, so it catches only a velocity in other units (a factor of
   1,000) or from another object (394 m/s apart in the plane-change reference case at its crossing). A frame mix is
   caught first by position, and a burn already folded into the state is left to the element-set epoch check.
   Hypotheses built from the bound red track's own state always pass both start checks; passing them is not
   validation. The cost is capped before anything runs at `MAX_SAMPLE_HOURS`, 4,800 sample-hours: a row costs the
   larger of its samples times the horizon and the hours its series integrates, which counts a burn before the
   window, plus 9 minutes (`SET_UP_S_PER_SAMPLE`) for each sample's solve_ivp set-up and closest-approach search.
   Without that term 20,000 samples over 0.028 h counted 560 and ran for 49 s. A row whose floor (samples times
   horizon and set-up) is already over the cap is refused without drawing its samples, and an over-cap refusal
   names the longest horizon, in tenths of an hour, that would fit: 9.4 h at 500 samples burning at the window
   start, with or without the Evasive archetype's timing spread, 1.7 h for five rows of 500, 2.2 h at 2,000
   samples. The default hypothesis, 500 samples over 48 h, costs about 24,171 and is refused.

   SPC-113 takes a sampled evaluation off the request. `EVALUATION_BUDGET_S` is 120 s, and the cap is what that
   covers at 40 sample-hours a second, about a fifth under the slowest rate measured. The measured rates ran from
   51 to 75 sample-hours a second: plane_change Evasive, 500 samples over 11.7 h (5,951), took 115.7 s with other
   work on the machine (51 a second) and 79.2 s and 80.2 s idle (74 to 75); 500 over 12 h (6,075) took 102.0 s at
   coplanar LEO and 104.3 s for the plane change. A cap at 50 a second would have admitted that 115.7 s case with
   4.3 s of the budget to spare, so a loaded server would have refused it part-way, after holding the only sampling
   slot for 2 minutes; at 40 the largest evaluation the cap admits takes about 94 s at the slowest rate. The budget
   still refuses, by name, whatever overruns anyway. GEO ran about four times faster than the model assumes, so GEO
   is refused conservatively. POST /plan/decision/evaluate answers a scenario that samples nothing
   (`needs_a_run` false: lookups, and rows refused before running) on the request, in milliseconds. Otherwise it
   starts a session job (`spectre/web/decision_job.py`, after the burn watch) and returns a partial that polls
   GET /plan/decision/job every 2 s, naming the hypothesis being sampled, the samples done and the budget used,
   with a Cancel button. One sampled evaluation runs at a time on the server: two series at once on two threads took
   45.6 s against 10.6 s for one, because the equations of motion hold Python's global interpreter lock, and the
   event loop lagged at most 78 ms beside one. A second job waits, queued, and its budget starts when it runs; the
   page says a job is waiting only when another evaluation holds the slot, and otherwise that it is starting. The
   engine ticks after every sample (`run_separation_series(..., tick=)`), and each tick reports progress, stops
   the evaluation when the operator cancels, the sign-in ends, a newer evaluation replaces it or the server shuts
   down, and refuses the row, naming the budget and the samples done within it, once the budget is spent; rows
   after it are refused without starting. A stopped evaluation scores nothing and says why; a failed one says the
   server log has the detail. A Cancel that arrives after the job has finished leaves it alone, and the results
   are shown.

   Sampling converges only where the 1 km absolute convergence tolerance allows. 1,000 samples over 0.44 h and more
   over shorter horizons converged at LEO 300 km, and with the larger cap the plane change converged out to 48 h
   (half-width 0.06 km at 100 samples, 0.04 km at 500) and coplanar LEO Evasive over 6 h (0.51 km). Not every burn in
   or before a window of 1 h or more is refused, as this paragraph said before SPC-113: coplanar LEO Evasive over
   1 h (1.22 km), coplanar LEO Orbit Raise (1.76 km), GEO Intercept (3.94 km) and a burn 2 h before the window
   (1.77 to 8.37 km) were not converged. A burn already made, the operator's "something moved" case, is the one
   that most often fails it; a relative tolerance is an owner decision. The unconverged refusal says to take more
   samples with a shorter horizon.

   Our response is not applied to the blue orbit yet, so blue is one trajectory per scenario: each series
   integrates blue once, about 1/500 of its cost, and every response in a sampled row has the same closest
   approach. "Up to 25 cells of 500 samples" is at most five series, one per sampled row shared by its cells; no
   per-response blue trajectory or pairing is built until a response changes the blue orbit. The 50,000 km
   normalisation lets the sampled spread move a score by at most w_ca x (P95 - P5) / 50,000, which the page
   states.
3. Add `ca_percentiles` / `ca_std_km` to `OutcomeMetrics`. Done in SPC-112, with `ca_samples`, `ca_refusal` and
   `ca_caveat`; an invariant sets the band exactly when the closest approach is sampled and pins it to P5.
4. Update `decision_panel.html` with per-row hypothesis accordion. Done in SPC-114: each adversary row has a
   "Manoeuvre hypothesis (optional)" section with an archetype (None keeps the row a lookup), a delta-V in m/s, a
   RIC direction, a delta-V spread (1 sigma, m/s), samples (100 to 2,000, default 500) and a burn time in hours from
   the scenario epoch, which is the moment Evaluate is pressed (-72 h to the horizon, default 0). Blank fields take
   the archetype's, and an archetype's direction is assumed in-track and says so. Every field sits in its label,
   and the row builder emits the same block, so every row posts all eight fields and the columns stay aligned. The
   panel names the longest horizon the cap admits at 500 samples (`longest_horizon_h`, 9.4 h at 4,800), and the
   horizon field steps in tenths of an hour from 0.1 h so the browser lets the operator submit it; the results
   footer shows the horizon as entered.
5. Update `decision_results.html` to show P5/P50/P95 bands in cells. Done minimally in SPC-112: a sampled cell
   says sampled, prints closest approach to 0.1 km and shows P5 to P95 with the median; a refused cell shows its
   sentence. Finished in SPC-115: each sampled cell also carries the half-width its percentiles are known to and
   the composite score's P5, P50, P95 and 1-sigma spread across samples, each sample's miss scored through the
   same `_score`. The band's hover gives the full distribution and names what is not in it: element-set error, as
   the sweep models it (1 km at epoch plus 2 km a day in LEO, 2 km plus 1 km a day at GEO), and the hypothesis
   being wrong. A lookup cell's hover says it is a fixed figure with no distribution. An Uncertainty column gives
   one sentence per row (sampled, lookup or refused), each ranking card shows the score spread, and a note says
   the spread is small because closest approach is normalised to 50,000 km, not because the outcome is certain,
   and that within a sampled row the ranking is decided by lookup figures. The banner shows the scenario epoch,
   since a job's result arrives after the request. No bar is drawn: cells share no scale. The band can be
   narrower than element-set error (plane_change Evasive at 500 samples spans 0.49 km against the sweep's 1 km
   at epoch); a per-cell comparison needs the regime on the bound element set and is a follow-up.
6. Add `hypothesis_*` form fields to `decision_evaluate` route. Done in SPC-114 as `hyp_*`: each is range-checked
   inline as audit F-164 checks the existing fields (HTTP 200, an error-msg naming the field and its row), only for
   rows whose archetype is not None. A hypothesis starts from the bound red track propagated to the burn time
   (`pre_manoeuvre_state`), so it needs a bound red track; a burn before the red element set's epoch is refused by
   the existing element-set check. The results show the burn on its own line (`AdversaryHypothesis.burn_line`). An
   entered spread (`with_spread`) is recorded in provenance (`spread_entered`), so every hypothesis's provenance
   hash changed with this release.
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
