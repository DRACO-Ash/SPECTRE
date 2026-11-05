# Decision Engine: as built, and the phases that built it

*Rewritten for 0.24.0 (SPC-152) to describe the engine as it stands at the end of that release. The history of each
step is in CHANGELOG.md and docs/CHANGE-LEDGER.md; this page says what the engine does now and why.*

**Plan status.** The owner ruled on 28 October 2026 to invest in every phase. The build plan is `.board/items.json`,
SPC-100 to SPC-152, summarised in `.board/README.md`. Three points of the original plan were corrected before the
build and stand:
● Phase 2 needs the blue element set: `MonteCarloResult` holds element statistics at the horizon, not trajectories,
  so closest approach needs a separation series.
● Score on the P5 closest approach, not P95: for a miss distance the conservative figure is the smallest one.
● The Phase 4 tree is server-rendered with details and summary elements rather than D3.js, which is not vendored.

Gate for Phase 2 (SPC-110) and Phase 3 (SPC-120): tests/unit/test_decision_reference_cases.py passes with that
phase's path added to PATHS, at both window starts (SPC-102).

## The question it answers

The operator's question is: "Something moved. Can it reach one of mine, how long have I got, does it mean anything,
and what do I need to decide, by when?" The sweep answers the first three. The Decision Engine is output 4, the
recommended response: given what red might do next, which of our responses holds up best, and what each figure
behind that ranking rests on.

The operator enters up to five adversary actions and up to five friendly responses. The engine fills an outcome
matrix, one cell per pair, ranks the responses for each adversary action, and picks one response under the chosen
rule. With a turn depth of 2 or 3 it also builds a game tree in which red may move again after each of our
responses. The result is a modelled recommendation, never an order, and the page says so.

## Every figure states its basis

Each figure carries a `FigureBasis` (SPC-101) of one of three kinds, shown in its cell as "(computed)", "(sampled)"
or "(lookup)" with the rule behind it in words:
● **Computed**: propagated from real element sets, both objects on one propagator, with no randomness.
● **Sampled**: the P5 of many propagated realisations of a hypothesised red burn, with its spread and how well that
  P5 is known.
● **Lookup**: a fixed rule of thumb or table value. It moves the ranking but rests on no orbit.

The composite score is a weighted sum of custody, closest approach, our delta-V, time to execute and reversibility,
lower being better. Its weights are uncited (SPC-151), so the score is always a lookup, whatever its inputs are.
Closest approach is normalised to 50,000 km and delta-V to 100 m/s, so a few kilometres of miss barely move a score
while a burn does; the page tells the operator to read the cell, not the ranking, for what a burn buys.

## Phase 1: the matrix, bound to real objects

**Status: built.**

● **Unbound**, every figure is a lookup: closest approach is 200, 3,000, 5,000 or 10,000 km by adversary action
  type, raised by the response's cost, custody follows a rule of thumb set by each row's custody gap share
  (default 0.7), and our delta-V is the response's cost times 50 m/s for a manoeuvre. A bound scenario takes these
  lookups only where nothing is computed or sampled (SPC-125): custody before it is read, our delta-V where no burn is
  sized, and a refused row's closest approach. Each is marked lookup.
● **Bound** (SPC-100): a scenario may be bound to one held red track and one held blue asset. The result names
  them, shows each element set's epoch and age at evaluation against its regime's limit (72 h for GEO and deep space,
  24 h otherwise) and puts both element sets in its provenance. The lookup model refuses a bound scenario, so no bound
  figure rests on a lookup constant where a computed or sampled figure exists.
● **P and Conf** are the operator's. P weights expected value. Conf records how sure the intelligence behind P is
  and moves no figure (SPC-161). Neither is ever filled in unasked.
● **Three rules pick the response**: minimax (least worst case, the default and the cautious rule), expected value
  (least probability-weighted score) and minimin (least best case, the optimistic rule, not a robust one).

Key files: `spectre/domain/decision.py` (the model and `evaluate_scenario`), `spectre/web/routes/decision.py` (the
panel, binding, evaluation and job routes), `spectre/web/decision_binding.py`, `spectre/web/decision_custody.py`,
`spectre/web/decision_threat.py`, `spectre/web/decision_job.py`, and the panel and results templates under
`spectre/web/templates/partials/`.

## Phase 2: a sampled closest approach

**Status: built (SPC-110 to SPC-117).** Gate passed by `monte_carlo_nominal` in
tests/unit/test_decision_reference_cases.py.

● An adversary row may carry a **manoeuvre hypothesis** (SPC-111, SPC-114): an archetype, a delta-V in m/s, a
  radial, in-track and cross-track direction, a delta-V spread, samples (100 to 2,000, default 500) and a burn time
  in hours from the scenario epoch, the moment Evaluate is pressed (from 72 h before it to the horizon). Blank fields
  take the archetype's; an archetype's direction is assumed in-track and says so. The hypothesis starts from the
  bound red track's own state at the burn time; a burn detected in the element-set history, opened from the sweep,
  starts from the element set before it (SPC-150).
● With both sides bound, that row's closest approach and its time are **sampled** (SPC-112): each sample's burn is
  drawn, propagated by RK45 with J2 and drag beside the blue asset, and its closest approach found. The row scores on
  P5, and its time of closest approach is the earliest at or below P5. One series serves the row, except that a
  response with a sized burn gets its own series after that burn, so its cells differ from the rest of the row.
● Before anything runs, a row is **refused**, keeping its cell a lookup and saying why, for fewer than 50 samples,
  an orbit not current, a red element set newer than the burn (it may already contain it), a start more than 10 km
  or 100 m/s from the bound red track, or a cost over the cap. While running, a failed sample or a series that does
  not converge refuses the row by name.
● **Converged** means P5, P50 and P95 are each known to within 1 km, or 5 per cent of P5 where that is larger
  (SPC-117): the operator reads P5 to answer "can it reach one of mine", and 8 km at 800 km changes no answer.
  Below 20 km the 1 km floor governs.
● **The cost cap** is 4,800 sample-hours, what the 120 s budget covers at the slowest rate measured (40
  sample-hours a second), with 9 minutes of set-up counted per sample. An over-cap row is refused naming the longest
  horizon that would fit; the panel says about 9.4 h fits at 500 samples with no burn to size.
● **Off the request** (SPC-113): a scenario that samples runs as a session job the page polls every 2 s, naming the
  hypothesis being sampled, the samples done and the budget used, with a Cancel button. One sampled evaluation runs
  on the server at a time; a second waits and its budget starts when it runs. A stopped evaluation scores nothing and
  says why.
● **On screen** (SPC-115): a sampled cell shows P5 to P95 with the median, the half-width P5 is known to, and the
  score's spread across samples. The hover names what is not in the band: element-set error and the hypothesis
  being wrong.

## Phase 3: computed outcomes, custody and our burns

**Status: built (SPC-118 to SPC-125).** Gate passed by `decision_phase3` in
tests/unit/test_decision_reference_cases.py.

● **Computed closest approach** (SPC-120): with both sides bound, a row whose action does not move red (no action,
  a sensor retask, a posture change) gets the pair's closest approach with no burn, propagated by SGP4 from both
  element sets, searched every 60 s with each local minimum refined to 0.01 s. A manoeuvre row with no hypothesis is
  refused, saying to add one: where red goes if it does not move is not the outcome of a manoeuvre.
● **One propagator per figure**: computed is SGP4 on both objects, sampled is RK45 on both. When a matrix holds
  both, the result states the measured gap between the two propagators.
● **The span searched** (SPC-118) runs from the scenario epoch to the earlier of the horizon's end and the moment
  either element set passes its limit, and the page states a trimmed span.
● **The time of closest approach** carries an uncertainty (SPC-118, SPC-124): both element sets' position error over
  the closing speed, erring wide, and the hours after the epoch are printed no finer than that uncertainty.
● **Custody** (SPC-123) is the operator's definition: timely and actionable information to judge whether a burn is
  normal and how the warning time changed. With a red track bound, the route reads its custody as the sweep does and
  carries it over the horizon on the assumption that no newer element set arrives: it is lost from the earliest of
  the scenario epoch if lost already, the newest element set passing its limit, and a hypothesised burn that set cannot show.
  Degraded custody counts as lost and is shown as degraded. A manoeuvre with no burn time takes the worst case, a
  burn at the epoch, and says so. Our response is not applied to custody.
● **Our response burns** (SPC-121): a manoeuvre response may carry a target separation, a delta-V budget (50 m/s
  unless given) and an axis. Its burn is sized, not optimised: the manoeuvre library's first guess is doubled
  towards the target and halved back to within 1 per cent, in at most 16 trials, both senses flown. Our burn is
  applied to the blue asset by RK45, so once any response is sized every computed cell is RK45 too, with the SGP4
  figure shown beside it. The cell says what the burn buys. A burn that cannot reach the target within the budget
  flies the whole budget, and the cell says how far short it falls; its delta-V is that burn's. A burn that would
  come after the closest approach or the span searched, or whose arc fails or re-enters, is refused in its cell, and
  its delta-V stays a lookup.
● **Show trajectory** (SPC-124): every propagated cell links to the Hill-frame view of its pair and window, labelled
  as a third model that shows the shape of the approach, not the cell's figures. A sampled cell has a histogram of
  its samples' times of closest approach, with the same figures as a table.

## The sweep's Threat picture and collect first

**Status: built (SPC-171).** Threat Understanding concept, docs/threat_confidence_concept.md, section 7.5.

● The engine reads the sweep's Threat range, Understanding, cues and decide-by for the bound red track while the
  picture is under 30 minutes old, and decide-by only for the blue asset it was set for, so the two never disagree.
  Threat and Understanding are shown as separate sentences, each with its axis named.
● When the Threat range straddles the line where the recommended response changes and a collection that could move
  it off that line lands before decide-by, the guidance says collect first and names the collection; with no such
  collection, or decide-by passed, it says act on the ceiling.
● Collections are listed beside the ranking, never scored, so the recommendation is always one of the operator's own
  rows.
● Under expected value, a bound row whose Understanding is LOW, or whose P is the untouched default, carries the
  guidance that expected value rests on a probability the evidence has not earned, and recommends minimax. The
  selector is never switched for the operator.

Concept section 9 records the choices this rests on, each Claude's choice and not a ruling: decision 9 (where the
engine reads the Threat range and decide-by), decision 10 (collect first with no decide-by), decision 11 (what counts
as an untouched probability), decision 12 (collect-first rows are listed, not scored) and decision 13 (what a
scenario opened from the sweep can carry, SPC-150).

## Phase 5: a probability from NOTSO history

**Status: built (SPC-130 to SPC-132).**

● Each adversary row has a labelled **Load from NOTSO** control. Loading shows a suggested P and Conf from the bound
  red track's NOTSO history, with its basis and an unticked control to apply it. Nothing is written into P or Conf;
  a ticked suggestion is applied at Evaluate only while it is still the one shown.
● P is the chance of at least one reported event of the row's action type within the horizon, at the rate the
  history shows over the periods the cache covers. Gaps in the cache and time before launch are left out, never read
  as quiet. Nothing is offered below 3 events or under 0.01. Conf is capped at 0.3, the most Threat Understanding
  lets any manufacturable item be worth. Both are lookups, rounded down.
● P carries an exact 95 in 100 Poisson interval on the events counted, its edges rounded outward. Under expected
  value the result says whether the pick holds across each row's interval, naming the P where it would change, and
  with two or more such rows across every corner of their joint range. Minimax and minimin read no probability and
  show no interval.
● The results show a NOTSO timeline per applied suggestion: covered periods, gaps and each counted notice, readable
  without colour.

Concept section 9 records these as decision 16 (what Load from NOTSO loads), decision 17 (the interval on a
NOTSO-derived P) and decision 18 (how the interval reaches the pick).

## Phase 4: the game tree and its view

**Status: built (SPC-140, SPC-141, SPC-142).** Code: `spectre/domain/decision_tree.py` (the tree),
`spectre/domain/tree_selectors.py` (the picks), `spectre/domain/turn_update.py` (the update after turn 1) and
`spectre/web/tree_view.py` with `partials/decision_tree.html` (the view).

### What the operator does

● On the panel, choose a **turn depth** of 1, 2 or 3. One turn is the outcome matrix alone. Two or three turns let
  red move again after each of our responses.
● Optionally state what **turn 1 shows** of red: a burn, no burn, or nothing. Only expected value reads it, for the
  update after turn 1. It moves no figure and writes no P. One turn has no later pick for it to update, so an
  observation stated with a depth of 1 is refused beside the form rather than dropped unsaid.
● Press Evaluate. Once the tree has what it needs (below), a depth whose tree cannot fit the branch cap or the cost
  cap is refused at once, beside the form, naming the largest depth that would fit at the same sizes. Nothing runs.

### What the engine does

● A tree needs both sides bound and current, and a propagated orbit from every row: a manoeuvre row needs a
  hypothesis, and no row's cell may be refused. Without these the result is one turn and says why.
● Turn 1 is the matrix. Each later turn starts from where the turn before left both orbits: red sample by sample
  after its hypothesised burn, blue after our sized burn. Every figure in a tree is RK45 with J2 and drag.
● The tree runs as one evaluation in the one sampled slot, inside the 120 s budget. A run that overruns keeps the
  deepest turn built in full and says so.

### What the result shows

● The tree's own lines: its size, how the turns split the span, what each node's and each sequence's figures mean,
  and when each row burns again.
● **The recommendation per turn** for the selector in use: turn 1's pick, then each later turn's pick after each
  thing the turns before may show, following our own picks. A turn-1 pick that differs from the matrix's says so.
● **The update after turn 1**, under expected value: the likelihood model, naming what each row shows, then the
  update for the observation the operator stated, with its basis, or a line saying no observation was stated so
  nothing was updated. An observation no row gives under the model, a tree with no later turn built, or a tree that
  gives no pick updates nothing and says so.
● **What each turn lets us see**, in the same place under minimax or minimin: the same custody rule, naming what
  each row shows in turn 1, since it sets what each later pick may depend on, then that the rule does not use
  probability, so nothing is updated and no P weighs red.
● **The tree itself**, server-rendered as nested collapsible branches. Each branch names its turn, red's move and our
  response, and the path of moves it rests on. Opened, it shows its closest approach from its turn on (with P5, P50,
  P95 and the half-width when sampled), the time of that closest approach with its uncertainty, our burn this turn in
  m/s, and its sequence's closest approach, delta-V, custody and score, each with its kind in words and the rule
  behind it. A branch on the plan the recommendation follows says so in words.
● A tree built in part names the deepest turn built in full and shows nothing below it. A tree refused before it
  runs is headed as asked for and none built, and states why.
● The view reads at phone width, says everything in words as well as colour, and adds no script.

### Design decisions D1 to D11 (SPC-140, SPC-141)

These are the design's choices, recorded for the owner. The owner ruled on each on 2026-11-05 (`.board/README.md`,
owner rulings): keep D1, D2, D4, D5 and D7 to D11; change D3 and D6 (SPC-187, SPC-188).

● **D1. Turn 1 is the matrix.** One root per cell; `evaluate_scenario` is unchanged and one turn has no tree. The
  matrix's own pick is unchanged by the tree. Owner ruling, 2026-11-05: keep.
● **D2. One propagator.** Every figure in a tree is RK45 with J2 and exponential drag for both orbits, from their
  SGP4 states at the scenario epoch, since no element set exists for an orbit after a burn. Turn 1's computed cells
  go on RK45 too, with the SGP4 figure shown beside them, and no node or cell names SGP4. Owner ruling, 2026-11-05: keep.
● **D3. Equal turns, every burn inside its own.** The span searched is split into equal turns. Each row's red burn
  falls at the same offset after each turn starts, and each response executes its time to execute after each turn
  starts, with a target separation sized again against red's nominal burn in that turn. A burn that falls outside
  its turn refuses the tree. Owner ruling, 2026-11-05: accept unequal turns, with their lengths determined by the engine, never set
  by the operator (SPC-187).
● **D4. Samples carried as themselves.** Sample k is carried from turn to turn as sample k. Each turn's draws are
  seeded from the row's seed, the turn and the red path, so the same evaluation gives the same tree. A sample whose
  drawn timing puts its burn after its turn ends keeps that burn, and the turn after makes it then. Owner ruling, 2026-11-05: keep.
● **D5. What a figure means.** Each node's closest approach runs from its turn's start to the span's end, as if no
  one moves again. A sequence's closest approach is the smallest along it, P5 of each sample's own minimum where red
  was sampled; its delta-V is our burns added up, a lookup when any turn's is; its custody is the bound red track's
  with the earliest red burn on it; its score is the one-turn weighted sum on those figures, a lookup. Owner ruling, 2026-11-05: keep.
● **D6. The caps.** At most 1,000 branches, the sum over turns k of (rows times responses) to the k, and the same
  4,800 sample-hour cost cap, with 16 sizing trials charged for every sizing. So coplanar_leo at 50 samples over three
  2 h turns costs about 6,700 sample-hours and is refused, though its prototype ran in 33 s idle. Recalibrating the
  cap for trees is the owner's decision. Owner ruling, 2026-11-05: raise the evaluation budget to 300 s (SPC-178), then measure trees
  under load and set their own cap from the measurements (SPC-188).
● **D7. Refused before anything runs, the matrix kept.** An unbound or out-of-date side, a row with no orbit to carry
  on, a burn outside its turn, too many branches or too high a cost refuses the tree, in that order, and the one-turn
  result stands with the reason. Owner ruling, 2026-11-05: keep.
● **D8. Never cut short silently.** A spent budget keeps the deepest turn built in full, naming the run's own budget;
  a failed or unconverged branch keeps the turns built and names the branch, since a pick over a tree missing a
  branch could miss its worst case. Owner ruling, 2026-11-05: keep.
● **D9. Picks over what we could have seen.** A turn's pick may depend only on what the turns before it showed, so
  red moves that show the same thing are one information set and one pick must serve every branch in it. Minimax
  takes the worst sequence over every red move and every branch in the set, minimin the best, and expected value the
  mean weighted by P and by the update. A set with no weight has no pick and says so. The first response wins a tie.
  Owner ruling, 2026-11-05: keep.
● **D10. The likelihood model is the engine's own custody rule.** Custody lost at a burn in the turn shows a burn,
  not which; held through it shows no burn; lost for another reason, or not read, shows nothing. Each row gives one
  of these for certain. This was chosen over a new detection model with made-up rates. The update is a lookup.
  Owner ruling, 2026-11-05: keep.
● **D11. Red's next move is weighed by P as entered.** Nothing sourced says how red's turn-1 move bears on its next,
  so the update says which turn-1 branch we are on, not what red does next, and the same rule reads turn 2 in a
  3-turn tree. A persistent-intent model needs a stated prior strength, which is the owner's decision. A row's
  applied NOTSO suggestion carries its interval into a range on every share it touches. Owner ruling, 2026-11-05: keep P as entered
  each turn.

### Decisions taken building the view (SPC-142)

The owner ruled on each on 2026-11-05: keep D12 and D13; change D14 and D15 (SPC-189, SPC-190).

● **D12. The operator states the observation.** The update is shown for the one observation the operator states
  for turn 1, held on the scenario and in its provenance, and for none otherwise. Showing every possible update at
  once read as if each had happened. Owner ruling, 2026-11-05: keep.
● **D13. Refused at once only when it cannot fit.** The panel refuses a depth over the branch cap or the cost cap
  before anything runs, naming the largest that would fit, since only a smaller depth or a smaller scenario helps.
  A tree refused for another reason (a side unbound, a row with no orbit, a burn outside its turn) still evaluates,
  and the result states the reason beside the one-turn matrix, since the matrix is still worth having. Owner ruling, 2026-11-05: keep.
● **D14. The plan, marked in words.** A branch is marked when every response on it is the rule's pick for what the
  turns before it showed. The selector picks in every information set, but the recommendation and its marks follow
  our own picks: a branch reached only through a response the rule would not choose carries no mark. Owner ruling, 2026-11-05: mark
  the best branch under each response, including responses the rule would not pick (SPC-189).
● **D15. Plain details and summary.** The tree is server-rendered with no script and no new library, so nothing is
  added to track or scan. Owner ruling, 2026-11-05: an interactive tree diagram (SPC-190).

## What remains out of scope

● **The composite weights are uncited** (SPC-151). Until an analyst sources them the score stays a lookup and the
  ranking a weighted heuristic.
● **A persistent-intent model for red** (D11): the owner ruled on 2026-11-05 to keep P as entered each turn.
● **Element-set error is not sampled.** A sampled band can be narrower than element-set error; a per-cell comparison
  needs the regime on the bound element set and is a follow-up.
● **A sensor's line of sight to red is not modelled.** Custody is about information, not geometry, and our response
  is not applied to it.
● **Doctrine wording** (SPC-177): no probability or yardstick word appears. The owner ruled on 2026-11-05 that
  doctrine words stay off screen, and SPC-177 is closed.
● **The verdict switch** stays off: the owner ruled on 2026-11-05 to keep it off (concept section 9, decision 3).
● **One impulsive burn per adversary row per turn.** A transfer of several burns is carried as its first burn. The
  owner ruled on 2026-11-05 to carry every burn of the transfer (SPC-184).

## Summary

| Phase | What it gives the operator | Status |
|-------|----------------------------|--------|
| 1 | The matrix, its ranking and three selector rules; bound to real objects | Built |
| 2 | A sampled closest approach from a manoeuvre hypothesis, scored on P5 | Built |
| 3 | Computed closest approach and time, custody, our burns sized, trajectory and histogram | Built |
| 5 | A NOTSO suggestion for P and Conf, its interval, and its timeline | Built |
| 4 | A game tree of up to three turns, its picks, the update after turn 1, and its view | Built |
