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
  - `custody_maintained` and `custody_gap_hours` (a rule of thumb, not the held, degraded or lost custody on the sweep,
    unless a red track is bound and its custody read: SPC-123, Phase 3 below)
  - `closest_approach_km` (a fixed 200, 3,000, 5,000 or 10,000 km per adversary action type, raised by response cost;
    no orbit propagated)
  - `time_to_closest_hours` (0.4 of the horizon) and `delta_v_cost_km_s` (response cost x 0.05 km/s for a manoeuvre;
    beside a computed or sampled closest approach, a response that does not burn spends 0 m/s, computed against the
    same no-burn blue orbit, SPC-125)
- Every figure states its own basis (SPC-101): `OutcomeMetrics.figure_bases` holds a `FigureBasis` per figure, of kind
  lookup, sampled or computed, with the rule behind it. In Phase 1 every figure is a lookup. The score's basis is
  derived from the figures its formula uses and is held at lookup by its scoring rule, so the modelled badge stays
  while the ranking is a weighted heuristic. Later releases set a figure's kind through `outcome_bases()` and the page
  marks it in its own cell.
- A scenario may be bound to one held red track and one held blue asset (SPC-100). The binding records which real
  objects the scenario is about, puts their element sets in the result's provenance and shows each orbit's epoch and
  age at evaluation against its regime's limit (72 h for GEO and deep space, 24 h otherwise) in a "Bound to" block.
  `find_robust_response` never reads it, and `compute_outcome_metrics`, the lookup model, refuses a bound scenario
  (SPC-125), so its constants are never read for one; tests pin both. `plan_sampling` reads it
  for a row whose action carries a hypothesis (SPC-112, below), and `plan_computed` reads it for the pair's closest
  approach with no burn, which every row whose action does not move red takes when both sides are bound (SPC-120,
  Phase 3 below). The red track's custody, read by the route as the sweep reads it, replaces the custody rule of
  thumb in every row (SPC-123, Phase 3 below).
- Three selector strategies: **Minimax** (minimise worst-case), **Expected Value** (probability-weighted), **Minimin** (optimistic, best best case; renamed from "Maximin", which named the cautious rule it did not implement)
- Results: modelled-recommendation banner ("Modelled estimate, not a computed solution") with a basis line per figure,
  a "(lookup)" mark on each closest approach and custody in the outcome matrix, and per-adversary ranked response cards

### Key files

| File | Role |
|------|------|
| `spectre/domain/decision.py` | Core data model + `evaluate_scenario()` |
| `spectre/web/routes/decision.py` | `GET /plan/decision/panel`, `GET /plan/decision/bind`, `POST /plan/decision/evaluate` |
| `spectre/web/decision_binding.py` | Binds a scenario to held objects and reads each element set's age (SPC-100) |
| `spectre/web/decision_custody.py` | Reads the bound red track's custody as the sweep does, before evaluation, or as a job's first stage while a UDL history fetch, first or fresh, is awaited (SPC-123, SPC-119) |
| `spectre/web/decision_threat.py` | Holds the sweep's Threat range, Understanding, cues and decide-by for its red track, and gives them to an evaluation bound to it while under 30 min old, with the deadline only for the blue asset it was set for (SPC-171) |
| `spectre/web/templates/partials/decision_panel.html` | Scenario builder form |
| `spectre/web/templates/partials/decision_results.html` | Outcome matrix + recommendation |

### Known Phase 1 limitations

- Unbound, outcome metrics are **lookup estimates** (closest approach is a constant per action type). Bound on
  both sides, closest approach and its time are computed by SGP4 for a row whose action does not move red
  (SPC-120) and sampled for a row with a hypothesis (SPC-112); a manoeuvre with no hypothesis stays a lookup
- An adversary action may carry a manoeuvre hypothesis (SPC-111, Phase 2 step 1). On its own it changes no figure;
  in a scenario bound on both sides its row's closest approach and time to closest approach are sampled (SPC-112),
  and with a red track bound its burn time sets when custody is lost (SPC-123); our delta-V is still a lookup
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

   Until SPC-117, sampling converged only where the 1 km absolute convergence tolerance allowed. 1,000 samples over
   0.44 h and more over shorter horizons converged at LEO 300 km, and with the larger cap the plane change converged
   out to 48 h (half-width 0.06 km at 100 samples, 0.04 km at 500) and coplanar LEO Evasive over 6 h (0.51 km).
   Coplanar LEO Evasive over 1 h (1.22 km), coplanar LEO Orbit Raise (1.76 km), GEO Intercept (3.94 km) and a burn
   2 h before the window (1.77 to 8.37 km) were not converged. A burn already made, the operator's "something
   moved" case, was the one that most often failed it.

   SPC-117 sets the tolerance from what the operator does with the figure: 1 km, or 5 % of P5 where that is larger
   (`miss_tolerance_km`, `MISS_TOLERANCE_FRACTION`), carried on each series as `tolerance_km`. The operator reads P5
   to answer "can it reach one of mine", a question of magnitude: 8.5 km at 843 km changes no answer, and the score
   moves by at most w_ca x half-width / 50,000 (4e-5 at 8.5 km and w_ca 0.25). Below 20 km the 1 km floor governs,
   so every close approach the operator would act on is held exactly as tightly as before. Measured at seed 42, the
   burn 0.25 h into the window unless stated, half-width against P5: plane_change Evasive 0.061 km against 9.45 km
   (100 samples over 1 h) and 0.044 km against 9.37 km (500); coplanar Evasive 1.217 km against 162.65 km (100 over
   1 h), 0.755 km against 161.50 km (500 over 1 h) and 0.375 km against 11.05 km (500 over 6 h, 3.4 %); coplanar
   Orbit Raise 1.758 km against 153.25 km (100 over 1 h) and 0.730 km against 152.12 km (500); GEO Station Keeping
   0.273 km against 306.5 km (100 over 24 h); plane_change with the burn 2 h before a 1 h window, 500 samples,
   Evasive 0.950 km against 41.67 km and Orbit Raise 8.513 km against 842.97 km; at 100 samples, 1.301 km against
   42.97 km and 11.338 km against 855.86 km. These are admitted at 0.5 to 3.4 % of P5; across 12 to 20 seeds the
   worst is about 3 %. GEO Intercept, P5 7.16 km known to 3.939 km at 100 samples over 6 h and 8.14 km to 1.759 km at
   500, is genuinely unknown and stays refused for every seed measured (smallest half-width 2.41 km against 1 km).
   The bootstrap half-width is roughly calibrated against the 95 % spread of P5 across seeds but varies about two
   times between seeds, so a verdict near the tolerance can flip with the seed; 1.77 km for the burn-2-h-before
   Evasive case above was another setup, 0.95 km at seed 42. `run_monte_carlo`'s SMA check keeps 1 km absolute. The
   page says what converged means (`CONVERGED_MEANS`) and leaves whether a move that size matters to the operator,
   since it is not told how close is too close for the asset; each band carries its half-width, the unconverged refusal
   names the tolerance it missed and says to take more samples with a shorter horizon, and a sampled cell names the
   samples already opening at the window start, which is where every sample of a burn 2 h before the window is
   closest.

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

**Status: in progress. Closest approach and its time are computed (SPC-120), custody is computed from the bound
red track's status (SPC-123), the sampled path searches only while both element sets are current and every TCA
carries an uncertainty (SPC-118), and a manoeuvre response given a target separation has its burn sized and
applied to the blue asset (SPC-121), and each cell shows its TCA with its uncertainty, a link to the Hill-frame
view for its pair and window, and, when sampled, a histogram of its samples' TCAs (SPC-124).**

SPC-120, as built. In a scenario bound on both sides each row gets exactly one closest approach. A row whose action
carries a hypothesis is sampled (RK45 on both objects), or refused and kept a lookup: the no-burn figure is not its
outcome. A row whose action does not move red (no action, a sensor retask, a posture change) is computed:
`plan_computed` propagates both bound orbits by SGP4 from their element sets with no burn
(`spectre/astro/elset_approach.py`), searched every 60 s by the shared helper with each local minimum refined to
0.01 s, the access search's step and tolerance (audit F-115). A manoeuvre row with no hypothesis is refused, with
a sentence saying to add a hypothesis: a propagated orbit as it stands only says where red goes if it does not move,
and scoring a manoeuvre on it would understate the threat. The figure belongs to the pair, one search per scenario
shared by every computed row and response, since our response is not applied to the blue orbit yet; the page says
so in `computed_caveat`, as the sampled caveat does. The search runs from the scenario epoch to the earlier of the
horizon's end and the moment either element set passes its limit (a 20 h old LEO set with a 24 h limit earns 4 h),
and the page states a trimmed span. A stale or unknown-age orbit on either side, an element set that does not
parse and a failed SGP4 instant anywhere in the search are refused, naming the side; a failure is never read as
infinite, which could hide the minimum. Each cell carries the miss, TCA and edge flag unrounded (`ca_computed`),
prints the miss to 0.1 km with a TCA line to the minute, and hovers the seconds and the relative speed in m/s; a
minimum at an edge of the search says it is not an encounter.

One figure never mixes propagators: computed is SGP4 on both objects, sampled is RK45 on both, and an invariant on
`OutcomeMetrics` holds a computed figure apart from a sampled band and a refusal. With blue on SGP4 and red on
RK45 the GEO reference TCA was 1,951 s off (0.13.0). Both-SGP4 against both-RK45 agree on every reference case to
within 0.001 km and 1.1 s, because the error is largely common to both objects, but each object alone drifts:
RK45 from its SGP4 state against SGP4 itself, ISS 0.58, 4.49 and 16.97 km at 6, 24 and 48 h; SSO at 500 km with
B* 1e-4 0.74, 5.07 and 11.44 km; the GEO reference red 1.21, 5.39 and 11.31 km. So when a matrix holds both a
computed and a sampled row the result states the measured gap, `rk45_sgp4_gap_km`: red's largest RK45 to SGP4
distance over the grid plus blue's, which by the triangle inequality bounds how far the two separations differ.
Each arc is measured as the sampled row integrates it: blue from its SGP4 state at the window start, red from each
sampled row's pre-manoeuvre state at its burn, at `bstar_post`, taking the largest of the sampled rows. A burn
before the window integrates red for longer, and the gap grows with it: plane_change over 1 h is 0.41 km from the
window start but 0.63, 3.62 and 4.43 km from a burn 2, 24 and 72 h before it; coplanar_leo over 6 h 0.92, 2.81
and 4.65 km. A difference between a computed row and a sampled row smaller than that is the propagators, not the
burn (from the window start: coplanar_leo 0.41 km over 6 h, geo_drift_in 22.62 km over 48 h, plane_change 0.41 km
over 1 h). A refused row is not sampled, so its burn plays no part; a result with no computed cell measures no gap.

Measured with the venv at cd44cb5 (Python 3.13, sgp4 2.27): the computed path gives coplanar_leo 10.0055 km, TCA
4.1 s early; geo_drift_in 29.9991 km, 14.8 s early; plane_change 10.4036 km, 0.9 s late, at both window starts
and at a 60 or 300 s step. On the F-115 counter-rotating 15 km/s pair it gives 299.980 km at 3,599.01 s against
the 0.1 s brute-force 299.981 km at 3,599.00 s. An ISS pair costs 0.07 s over 72 h; the trim to the element sets'
limits keeps every search to 72 h or less.

SPC-123, as built. Custody is the operator's (28 October 2026): timely and actionable information to judge whether a
burn is normal and how the warning time changed. With a red track bound, the evaluate route reads its custody as the
sweep does (`spectre/web/decision_custody.py`): its history through the one held copy (`pol.held_history`), a
bounded 20 s wait for a first fetch, and the sweep's own rule, now `pol.custody_from_history`, so the two cannot
judge one object differently. The status rides on the bound element set (`BoundElset.custody`, red only), so the
evaluation and any job it runs as do no I/O. `custody_over_horizon` (`spectre/domain/custody.py`) carries the
status at the scenario epoch over the horizon on the assumption that no newer element set arrives: custody is lost
from the earliest of the epoch, if it is lost already; the moment the newest element set passes its limit (epoch
plus limit minus age, strictly past, as the sweep's rule is); and a hypothesised burn newer than the newest element
set, which that set cannot show (a burn already made counts from the epoch). `custody_maintained` is never lost
within the horizon and `custody_gap_hours` the hours lost, an upper bound, both computed, and the cell carries the
status at the epoch (`custody_state`). Degraded custody can judge the warning time but not whether a burn is normal,
and the operator's custody needs both, so it counts as lost for the whole horizon, shown as degraded and scored as
lost (review of 3 November 2026: shown and not scored, it carried a green tick the software had not earned). A
manoeuvre row with no hypothesis names no burn time, so it takes the worst case, a burn at the scenario epoch, as a
lookup, and says so, unless custody is lost from the epoch already (lost, degraded, or at its limit), which no burn
time can change, so it is computed. A result whose every row is the worst case says so in its basis line
(`WORST_CASE_BASIS`), not "a rule of thumb", and so does each such cell (`WORST_CASE_CELL_BASIS`).
Custody describes our information about red, so our response is not applied to it: a sensor retask loses its
rule-of-thumb advantage, and the page says so. Unbound, blue only, or with no status read, the rule of thumb stays
and the page says how to earn the computed figure. A refused cell's suffix now speaks for its closest approach only,
since custody may be computed beside it. Offline, custody is degraded (UDL not connected), so it counts as lost for
the whole horizon, which is honest, since nothing offline can judge whether a burn is normal, and will be common; the
custody gap ignores the measured element-set cadence, so it is pessimistic. Owner to confirm that degraded scores as
lost: it follows the operator's definition, and is one branch in `custody_over_horizon` if the owner decides otherwise.

SPC-118, as built. One helper, `_searched_span_s`, sets the span both paths search and the span the propagator gap
is measured over: from the scenario epoch to the earlier of the horizon's end and the moment either bound element
set passes its limit. The sampled path searched the whole horizon before, so 100 samples over 48 h were admitted on
a 24 h LEO limit (4,784 sample-hours over 47 h) and 50 samples 20 h old ran 44 h past it; now they search 24 h and
4 h. An element set at its limit already earns no span and is refused before anything runs, and a hypothesised
burn after the span a row earns is refused, since its figure would be the no-burn one. The span note,
`searched_span_note`, covers a sampled-only result too. Each computed or sampled closest approach carries
`tca_uncertainty`: both element sets' position error at the TCA (`elset_position_error_km`, along_track.py's tuned
model), combined in quadrature, over the closing speed, all of the error taken along the approach, so it errs wide.
A sampled cell uses the closing speed of the sample that sets its TCA, which the separation series now records per
sample. There is none at an edge of the search, at a closing speed of rounding noise, or when it would be wider than
the span, and the page says which. Measured: coplanar_leo 1.888 km over 5.533 m/s, about 341 s (shown "± 6 min",
4.0 h); geo_drift_in 4.662 km over 1.094 m/s, 4,259.5 s ("± 1.2 h", 31 h), which covers the 1,951 s the GEO TCA
moved between propagators; plane_change 1.460 km over 394.0 m/s, 3.7 s ("± 4 s", 0.39 h). The hours after the
scenario epoch print to 0.01 h while the uncertainty is under 3 min, to 0.1 h while it is under 30 min, and to the
hour above, so rounding never moves the time by more than its uncertainty; a TCA too slow to fix within the span
prints to the hour with "± more than the 48.0 h searched".

SPC-121, as built. A manoeuvre response may carry a target separation, a delta-V budget (50 m/s unless given) and
an axis (`ResponseBurnSpec`). SGP4 cannot take an impulsive burn and SPECTRE fits no element set to a burnt orbit,
so a figure that includes our burn is propagated by RK45 with J2 and drag for both orbits from their SGP4 states at
the scenario epoch, and blue burns from its own RK45 arc at the response's time to execute after the epoch
(`spectre/astro/response_burn.py`). Once any response in a scenario is sized, every computed cell in the result is
on RK45, the no-burn ones included, so no row is ranked across two propagators (`_require_one_propagator`); the
SGP4 figure with no burn is shown beside it with the measured difference (`rk45_reference_line`; coplanar_leo
10.005 km against 10.006 km, 0.16 s apart), the propagator gap is no longer measured, and with no target anywhere
0.15.0 behaviour is unchanged. What a burn buys is the RK45 closest approach after it minus the RK45 one before it,
from the same arcs. The size is a search, not an optimiser: the manoeuvre library's Clohessy-Wiltshire size
(`tactical.collision_avoidance`) gives the axis unless the operator names one and a first size; both senses are
flown; the size doubles to the target or the budget and halves back to within 1 %, at most 16 trials. The library
guesses about 0.23 m/s for coplanar_leo to 20 km; 3.08 m/s retrograde in-track is what reaches it, because a
prograde burn closes the miss (1 m/s gives 9.705 km) and every burn moves the encounter. A sampled row sizes the
burn once on the hypothesis's nominal burn and applies it to blue in every sample, paired by sample; the cell scores
on P5 after the burn and says what it buys at P5 (plane_change Evasive 0.25 h in, 100 samples: 5.47 m/s inward,
9.45 km to 19.94 km, half-width 0.04 km), and when P5 after sits under the target it counts the samples that came
closer (16 of 100 in that run); when the whole budget falls short on the nominal, the cell says so rather than
calling the burn sized to the target. A burn after the closest approach or the span, or whose arc fails or
re-enters, is refused in its cell and its delta-V stays a lookup; a burn after the closest approach names the RK45
closest approach it was decided on. A manoeuvre response with no target says how to size it, and a target entered
where the closest approach is a lookup (unbound, a manoeuvre with no hypothesis, a refused row) says it was not
used. The cap counts burns: each adds 0.3 of a sample
per sample (the measured worst, 29 % in LEO over 1 h), 16 samples to size it and blue's burnt arc, and the
computed rows' sizing costs (2 + 16 k) samples over the span; GEO over 72 h with five burning responses is refused
conservatively (5,917 sample-hours), as sampling at GEO already is. Sizing ticks the job's budget; the computed
rows' sizing is not counted as a hypothesis, and the job page names the response being sized, by its id when it has
no name. Measured: coplanar_leo over 6 h with one burn 0.95 s, ten trials, and
with five 3.6 s; the plane_change sampled row above 1.9 s. The score still normalises closest approach to 50,000 km,
so what a burn buys barely moves it while its delta-V does (30.1 km moves a score by 0.0002, 8.85 m/s adds 0.0177);
`burn_score_note` says to read the cell, not the ranking, until SPC-151 settles the weights.

SPC-124, as built. Each computed cell prints its TCA with its uncertainty and its propagator ("± 4 s, 0.39 h after
the scenario epoch; SGP4, no burn"), and each sampled cell the earliest TCA at or below P5 with the TCA's P5 to P95
across samples; the hover says what the uncertainty rests on. Every propagated cell has a Show trajectory button,
whose accessible name starts with that visible label and adds its adversary and response (WCAG 2.5.3, Label in
Name), that posts to the existing geometry route
(`spectre/web/decision_trajectory.py` builds the values, converting km/s to m/s there and only there): a computed
cell with no burn from the scenario epoch over the span searched; a cell with our burn from the later of the epoch
and 24 h before the burn (the route's longest coast), our burn drawn as the opposite change in red's velocity
relative to blue, over the rest of the span; a sampled cell with the hypothesis's nominal burn, from the burn when
it is before the window, saying that our burn is not drawn since the view takes one burn. A lookup or refused
cell has no button. The view is a third model, so the route, given an allowlisted context, says it is a
Clohessy-Wiltshire picture from both SGP4 states that shows the shape of the approach, not the cell's figures, which
stand; and where the element set now held is not the one the evaluation used, it names both epochs. The view and
the intercept result's panel can be open on the operator page together, so the route gives the decision view its
own id prefix and the control that opened it: they share no id and set nothing on `window`, so each draws its own
chart, its close and Escape remove only itself, and focus returns to the cell whose form was submitted (the results
mark it). The route
now binds a form model (`Annotated[_GeometryForm, Form()]`), which keeps the posted names and clears its last bare
`Depends`. A sampled cell whose series records closing speeds carries `tca_histogram`: each sample's TCA, its
uncertainty from its own closing speed, in bins the smallest of 1 s to 12 h that is at least the wider of a
twentieth of the range and the median drawn sample's uncertainty (the plane change's 3.7 s gives 5 s bins). The
median floors the bins, so up to half the drawn samples may be known less well than a bin, and the caption says how
many. Samples at an edge of the search, and samples closing too slowly to fix a time within the span, are counted
in the caption, not drawn. Each bin edge is a whole multiple of a whole-second width, so the table states it
exactly in h:mm, or h:mm:ss for bins under a minute, and the chart labels its bars and axis from the table: no edge
is rounded. The panel offers a labelled select of the sampled cells, a canvas drawn with the vendored Chart.js from
numbers-only JSON, and the same figures as a table; 500 samples cost about 7 ms. The Show trajectory button and the histogram
draw no figure the cell does not already state.

**Dependency:** Phase 2 complete; both red and blue TLEs available in session state

### What changes

- Replace analytic closest-approach estimate with full SGP4 propagation:
  - Start from red TLE at scenario epoch
  - Apply adversary manoeuvre hypothesis (sampled from MC)
  - Propagate both objects to horizon; compute actual minimum separation via `TLEOrbit.propagate()`
  - Apply response ΔV to blue TLE; propagate; recompute separation
- `OutcomeMetrics.custody_maintained` becomes a true SGP4 result (line-of-sight check at each step). SPC-123 took the
  operator's definition instead, which is about information, not geometry: the bound red track's held, degraded or
  lost custody carried over the horizon (above). A sensor's line of sight to red is not modelled.
- Enables time-of-closest-approach (TCA) calculation

### UI additions

- TCA timestamp shown in each outcome matrix cell (tooltip)
- "Show Trajectory" button per outcome cell → opens the Hill-frame CW geometry visualiser for that (adversary, response) pair
- Summary: TCA distribution histogram (Chart.js) for the selected best response

### Implementation steps

1. Add `propagate_outcome()` in `decision.py`, wrapping `TLEOrbit.propagate()`. Done in SPC-120 as
   `plan_computed`, through `elset_closest_approach` in `spectre/astro/elset_approach.py`, so `decision.py` never
   names the propagator.
2. Require `blue_tle` and `red_tle` in `evaluate_scenario()` for Phase 3 path. Done in SPC-120 through the binding:
   the computed path runs only when the scenario is bound on both sides, and a scenario bound on one side says
   "Closest approach not computed: bind a red track and a blue asset to compute it."
3. Add TCA to `OutcomeMetrics`. Done in SPC-120: `ca_computed` carries the TCA in seconds with the edge flag.
4. Wire "Show Trajectory" button → `POST /plan/geometry/intercept` with cell parameters
5. Gate: tests/unit/test_decision_reference_cases.py passes with this phase's path added to PATHS, at both window starts (SPC-102).
   Passed by SPC-120's `decision_phase3`: a scenario at the window start, bound to both element sets aged to it
   against a 24 h limit (72 h at GEO), with one no-action row, run through `evaluate_scenario`.
6. Carry TCA unrounded with the edge flag; decision.py:1156 and :1772 (at cd44cb5) round time_to_closest_hours to
   0.01 h, coarser than the plane-change tolerance, and the results page showed closest approach in whole km
   (decision_results.html:172 at cd44cb5). Done in SPC-120: `ca_computed` holds the miss, TCA and edge flag
   unrounded, a computed cell prints 0.1 km and its TCA to the minute, and the hover gives the seconds.

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

### As built: SPC-140 (the tree)

● `Scenario.turns` (1 to `MAX_TURNS`, 3) and `ScenarioResult.tree`, None for one turn. `spectre/domain/decision_tree.py` builds the tree through `evaluate_tree`; `evaluate_scenario` is unchanged.
● Turn 1 is the outcome matrix, one root per cell. Every computed cell goes on RK45 for both orbits in a tree, even when nothing burns, with the SGP4 figure shown beside it, and no node or cell names SGP4.
● Each later turn starts from the arcs the turn before left: red sample by sample (`run_separation_series(keep_at_s=...)`, then `continue_series`), blue after our burn sized again against red's nominal burn. The span searched is split into equal turns, and every nominal burn must fall inside its own turn. A sample whose drawn timing puts its burn after its turn ends keeps that burn (`Kept.pending`), and the turn after makes it then, so no sample loses a burn at a boundary.
● A node runs from its turn's start to the span's end. A sequence's closest approach is P5 of each sample's own minimum along it, its delta-V our burns added up, its custody the bound red track's with the earliest red burn on it, and its score a lookup. Each carries its basis (`PathFigures.bases`, `custody_bases`): the delta-V is a lookup, naming the turns, when any turn's is, and the closest approach says where no burn was sized.
● Before anything runs, the tree is refused, keeping the one-turn result, when a side is unbound or out of date, a row leaves no orbit, a burn falls outside its turn, the branches pass 1,000, or `tree_cost` passes the cap. A row leaves no orbit when its closest approach is a lookup (add a hypothesis) or refused (its cell says why). Once running, a spent budget keeps the deepest turn built in full, naming the run's own budget; a budget spent before turn 1's row was sampled says so, not that the row is a lookup; and a failed or unconverged branch keeps the turns built and names the branch.
● The cost model charges 16 sizing trials for every sizing, so coplanar_leo at 50 samples over three 2 h turns costs about 6,700 sample-hours and is refused, though its prototype ran in 33 s idle. Recalibrating the cap for trees is the owner's decision (D6).
● The view is SPC-142.

### As built: SPC-141 (selectors over the tree and the update after turn 1)

● `GameTree.selection` holds the result's rule over the turns built in full (`spectre/domain/tree_selectors.py`): turn 1's pick, then each later turn's pick after each thing the turns before may show, following our own picks, with each response's value there; what turn 1 shows under each row; the update after turn 1, under expected value only; and its lines. None when no turn was built. The matrix's own pick is unchanged, and a turn-1 pick that differs from it says so.
● The likelihood model (`spectre/domain/turn_update.py`) is the bound red track's custody, as the sweep judges it, carried over the horizon with the red burns on the path and read at each turn's end: lost at a burn in the turn shows a burn, not which; held through it shows no burn; lost otherwise, or not read, shows nothing. Each row gives one of these for certain, so rows that give the same thing are one information set, and a pick must serve every branch in it.
● Recursive minimax takes the worst sequence over every red move and every branch in the set, minimin the best, and expected value the mean, each red move weighed by its row's share of P and each branch by the product of its moves' shares: Bayes' rule with that likelihood. A set with no weight has no pick and says so. Checked against every policy over three turns.
● The posterior after turn 1 is each row's P restricted to the rows that give what turn 1 shows, renormalised, a lookup. A row's applied NOTSO suggestion carries its interval into a range on every share it touches; shares are shown rounded down and ranges outward; each names its source (your P, the default left untouched, or the NOTSO suggestion); one row alone says the certainty is the model's assumption. Under minimax or minimin it is not shown, and nothing writes a P.
● Decisions taken here, Claude's choice, not a ruling: (a) the observation is the engine's own custody rule rather than a new detection model with made-up rates; (b) red's move in each later turn is weighed by the rows' P as entered, since nothing sourced says how its turn-1 move bears on its next, so the update says which branch we are on, not what red does next; a persistent-intent model needs a stated prior strength, an owner decision; (c) the same rule reads turn 2 in a 3-turn tree.

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
