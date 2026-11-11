# Decision Engine: as built, and the phases that built it

*Rewritten for 0.24.0 (SPC-152) to describe the engine as it stands at the end of that release, and updated for
three owner rulings of 2026-11-05: the 300 s evaluation budget (SPC-178), degraded custody scored between held and
lost (SPC-179) and the record of whether each P was edited (SPC-183); for the score scales of SPC-191, which are
Claude's design choices, not rulings; for the decision record of SPC-192; and for every rule's pick side by side
with a primary rule (SPC-194) and replay from the stored record (SPC-193); for responses the operator marks not
permitted (SPC-195); for the judgement basis, the lookup register and the code version on the results (SPC-196);
and for the element-set acceptance check and the operating envelope (SPC-201, SPC-200); for what P means, a
probability over mutually exclusive actions with the remainder weighed (SPC-203); and for collect first tied to the
engine's own recommendation (SPC-204) and the weight stability beside it (SPC-205); and for element-set error in
every closest approach the engine propagates (SPC-202).
The history of each step is in CHANGELOG.md and docs/CHANGE-LEDGER.md; this page says what the engine does now and
why.*

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
matrix, one cell per pair, ranks the responses for each adversary action, and picks one response under each of the
three rules, never one the operator marked not permitted, the deployment's primary rule's pick heading the result. With a turn depth of 2 or 3 it also builds a game tree in which red may move again after each of our
responses. The result is a modelled recommendation, never an order, and the page says so.

## Every figure states its basis

Each figure carries a `FigureBasis` (SPC-101) of one of four kinds, shown beside it as "(computed)", "(sampled)",
"(lookup)" or "(judgement)" with the rule behind it in words:
● **Computed**: propagated from real element sets, both objects on one propagator, with no randomness.
● **Sampled**: the P5 of many propagated realisations of a hypothesised red burn, with its spread and how well that
  P5 is known.
● **Lookup**: a fixed rule of thumb or table value. It moves the ranking but rests on no orbit. Every one the engine
  reads is in docs/lookup-register.md (SPC-196).
● **Judgement**: a value the operator set or kept on the panel (SPC-196). It is not evidence. The results list each
  one under "Judgement inputs", set out below.

The composite score is a weighted sum of custody, closest approach, our delta-V, time to execute and reversibility,
lower being better. Its weights are uncited (SPC-151), so the score is always a lookup, whatever its inputs are.
Closest approach and our delta-V are each valued in orders of magnitude (SPC-191): closest approach scores its full
penalty at or inside the keep-out distance the operator sets on the panel and none at 50,000 km, and our delta-V
reaches its full penalty at the engine's 1,000 m/s per-burn limit. The next section sets out both scales.

## Score scales (SPC-191)

**Status: built. Each scale is Claude's design choice, not a ruling.** Evaluation finding F-10 (Critical) found the
score nearly blind to closest approach. Closest approach entered it linearly over 0 to 50,000 km at weight 0.25, so
1 m/s of our delta-V weighed the same as 400 km of miss, and our delta-V saturated at 100 m/s, so 100 and 500 m/s
scored the same. A 1 m/s burn that opened a miss from 1 km to 100 km ranked below doing nothing (probe P-17). The
owner said on 2026-11-10 "F-10 first". **The technical authority has not yet signed the scale rationale**, which
F-10's closing evidence requires, so F-10 stays open until it does.

● **Closest approach, in orders of magnitude from a keep-out distance K** (Claude's choice). The term is 1 for a
  miss at or inside K, 0 at or beyond 50,000 km, the far anchor kept from before, and ln(50,000 / miss) /
  ln(50,000 / K) between. It is continuous and falls strictly between the anchors, and each tenfold of miss is worth
  the same: about 0.27 of the term at K 10 km. The operator's question is whether something can reach one of theirs,
  a question of magnitude: 1 km and 100 km differ in kind, 20,000 km and 20,100 km do not.
● **K is the operator's** (Claude's choice). It is a Scenario field, keep_out_km, set on the panel as the labelled
  number field "Keep-out distance (km)", from 0.1 to 10,000 km, below the far anchor so the scale has room. A value
  outside that range, or not a finite number, is refused with a sentence, as every other panel number is. A cleared
  field is refused too, as a cleared horizon is: the form reads a blank as absent, so a default there would score a
  cleared field at 10 km unasked. The result states the distance it used exactly as entered.
● **The default K is 10 km** (Claude's choice, unsourced). A miss of a few kilometres is close for any asset, but
  10 km rests on no source, and the panel, the score's basis note and the result each say so. A scenario opened from
  the sweep, a reference case and a scenario built in code take the default. K enters the scenario's provenance hash
  as every other scenario field does.
● **Our delta-V, in orders of magnitude up to the per-burn limit** (Claude's choice). The term is ln(1 + dv) /
  ln(1,001) for dv in m/s, and 1 at the engine's per-burn limit, MAX_BURN_M_S, 1,000 m/s, and above. 1 m/s scores
  0.10, 10 m/s 0.35, 100 m/s 0.67 and 500 m/s 0.90, where 100 and 500 m/s both scored 1 before.
● **One function each.** `_norm_ca` and `_norm_dv` in `spectre/domain/decision.py` are the only places the score
  reads a miss or our delta-V. The cell score, the sampled score's percentiles and spread, the computed and sampled
  response figures, the burn score note, the sampled caveat's spread and the game tree's path score all go through
  them. The burn score note is now the term before the burn less the term after it, not a linear share of the km,
  and it reports the cell whose score the burn moves most, which on this scale need not be the one where it buys
  most kilometres. The game tree's path score reads our burns along a sequence added up on the same scale, so
  burns adding up to 1,000 m/s or more score the full delta-V term, and its basis note says so.
● **Break-even at the defaults.** Opening a miss from 1 km to 100 km lowers the score by 0.25 x (1 - ln 500 /
  ln 5,000) = 0.0676. Our delta-V adds 0.20 x ln(1 + dv) / ln 1,001, which equals that at about 9.3 m/s. A burn
  under about 9.3 m/s that buys that move now scores better than doing nothing; under the old scales the break-even
  was about 0.25 m/s. P-17's 1 m/s burn to 100 km scores 0.2039 against 0.2514 for doing nothing, and minimax picks it.
  The break-even moves with K: about 38 m/s at K 1 km, and none at K 100 km, where a 1 km and a 100 km miss both
  score the full penalty.
● **The evaluation probe stays as evidence of 0.24.2.** Evaluation probe P-17 is frozen with the evaluation and
  reads a constant SPC-191 removed, so it no longer runs against this code. Its inversion, F-10's closing evidence
  in the code, is `tests/unit/test_decision_score_scales.py`, which recommends the 1 m/s burn to 100 km.
● **What moved.** No reference case's pick changed: in every case at both window starts, Hold is still the pick under
  all three rules. No pinned pick in the test suite changed. Pinned scores were re-derived by hand from the two
  formulas. Scores on far misses fall, so many cells that were amber now read green under the results' colour bands
  (green below 0.25, amber below 0.50). In the 12 cells of the lookup scenario evaluation probe P-17 uses, misses of
  200 to 15,000 km, every score drops by 0.07 to 0.16 and 5 cells change band, four of them amber to green and one
  red to amber. A miss under about 10 km barely moves, and a small burn of ours scores more than before. The bands
  themselves are finding F-18 (SPC-208) and are unchanged.

## Judgement inputs, the lookup register and the code version (SPC-196)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-05 (Critical, gate G5) found every figure tagged computed, sampled or
lookup, but the operator's own values (each response's cost, reversibility and time to execute, each row's P and
Conf, the weights, the keep-out distance) carried no judgement tag, the lookup constants no source, owner or date,
and the code version was never shown. Gate G5 was rated Red; that rating stands until the evaluation is repeated.

● **A fourth basis, judgement.** `Basis.JUDGEMENT` in `spectre/domain/provenance.py` is a value the operator set
  or kept on the panel. It is declared first, the weakest of the four: `weakest()` of a judgement and anything else
  is the judgement, so a judgement never lends a figure more standing than a lookup. A lookup is at least a fixed,
  registered rule, the same for every operator; a judgement is one operator's opinion at one evaluation. The Threat
  Understanding model grades a judgement as it grades a lookup, LOW, and refuses a judgement as evidence.
● **Judgement inputs on the results.** Under the basis lines, the results list every input on the panel that enters
  a score or a pick, each marked in words: the weights, the keep-out distance, the horizon and the number of turns;
  each response's type, cost, reversibility and time to execute, and its burn's target separation, delta-V budget and
  axis when it has one; each row's type, P and Conf, and its custody gap share where the rule of thumb reads it, which
  is on a manoeuvre row whose custody is not read, against a response that neither manoeuvres nor retasks a sensor;
  each manoeuvre hypothesis and its sample count; and, for a tree, the turn-1 observation stated. Each line says what
  reads its inputs. The headline response's type, cost, reversibility and time to execute, and each row's type, P,
  Conf and gap share in the matrix, carry the same mark beside them.
● **Set or kept.** A value on the panel when the operator evaluates is the operator's judgement, whether set or kept
  where the panel started it: the form records no edit of it, so its note names where a new panel starts it, never
  that it was typed. A delta-V budget left blank is the registered default, 50 m/s, which the operator kept by
  leaving it blank, and its note says so. The values a new panel starts at are in the lookup register, and a test
  holds the panel's fields and the route's form to them.
● **What is not a judgement says what it rests on.** A P the form records as never edited is the panel's default
  (SPC-183), marked "(lookup)"; a P and Conf from an applied NOTSO suggestion (SPC-130) carry the suggestion's own
  basis. A manoeuvre hypothesis is marked by where it came from: entered on the panel, a judgement of what red might
  do; an archetype chosen, a judgement, with its typical delta-V a lookup from `MANOEUVRE_ARCHETYPES`; a burn
  detected in the element-set history, what red did, computed from element sets. Its line says its row's closest
  approach is sampled from it only when the row was sampled, and otherwise that nothing was sampled from it.
● **A figure's mark names the evidence and rules it rests on, taking the inputs as given.** The operator's inputs
  are not counted in a figure's basis: every figure rests on the weights alike, so counting them would mark every
  figure a judgement and tell none from another. A lookup that applies a rule of thumb to an input, such as cost x
  0.05 km/s of delta-V, is marked lookup for the rule, and the input is listed as a judgement. The score is marked
  lookup, as before, and no stronger.
● **The lookup register.** `docs/lookup-register.md` lists every numeric constant in the Decision Engine's own
  modules, and the lookups it reads from other modules to set a figure, a score, a pick or its advice (the manoeuvre
  archetypes, the collect-first times, the NOTSO interval, the element-set age limits and others), each with its
  value, where it is in the code, what it does, its source or "none: rule of thumb", its owner ("unassigned" where
  none is recorded, and the owner's rulings where they exist) and the date it was set. The rules of thumb that were
  bare numbers in the lookup model (cost x 5 and cost x 2 on closest approach, cost x 0.05 km/s of delta-V, half a
  sensor retask's time to execute, 0.4 of the horizon) are now named constants, with no change of value, and so are
  the values a new panel starts Conf, cost, reversibility, time to execute and the horizon at.
  `tests/unit/test_lookup_register.py` fails when a constant the register names leaves the code or changes value
  without the register; when one of the engine's own modules gains a numeric module constant the register does not
  list, however it is assigned; when the lookup model's functions hold a bare number other than 0 and 1; and when
  the panel or the route's form starts a field anywhere but its registered value.
● **The code version on the results.** The figure-basis lines end with the code version that computed the result,
  from its provenance, in words: "Code version 0.28.0: the version SPECTRE reports for the code that computed this
  result, from its provenance." It names a release only for a released build. A result with no provenance says its
  code version is not recorded.
● **Stored inputs unchanged.** No Scenario or response field was added, so the stored inputs keep schema version 1,
  and a record written by 0.28.0 reads and replays as before. The reader now refuses a stored NOTSO suggestion whose
  basis is a judgement, which no writer stores.
● **Claude's design choices, awaiting the owner's ruling.** Judgement ranks below lookup rather than beside it. A
  judgement is an input's basis, not a derived figure's, for the reason above. A value kept at the panel's start is
  the operator's judgement, as is a budget left blank, rather than a lookup, since the form records no edit of them
  as it does for P; recording one would change the stored inputs. Conf is listed though it moves no figure, as the
  finding names it. A detected burn is marked computed and listed with the inputs, so its row's line says what it
  rests on. The register's completeness check covers the engine's own modules; the constants of other modules it
  lists are held to their value, not checked for newcomers.

## Phase 1: the matrix, bound to real objects

**Status: built.**

● **Unbound**, every figure is a lookup: closest approach is 200, 3,000, 5,000 or 10,000 km by adversary action
  type, raised by the response's cost, custody follows a rule of thumb set by each row's custody gap share
  (default 0.7), and our delta-V is the response's cost times 50 m/s for a manoeuvre. A bound scenario takes these
  lookups only where nothing is computed or sampled (SPC-125): custody before it is read, our delta-V where no burn is
  sized, and a refused row's closest approach. Each is marked lookup.
● **Bound** (SPC-100): a scenario may be bound to one held red track and one held blue asset. The result names
  them, shows each element set's epoch and age at evaluation against its regime's limit (72 h for GEO and a perigee
  beyond GEO, 24 h otherwise, HEO and Molniya-class included) and puts both element sets in its provenance. The lookup model refuses a bound scenario, so no bound
  figure rests on a lookup constant where a computed or sampled figure exists.
● **P and Conf** are the operator's. P is the chance of the row's action, the rows mutually exclusive, so their P
  sum to at most 1, and the rest is weighed as a row of the engine's own, no adversary action (SPC-203, set out
  below). P weights expected value. Conf records how sure the intelligence behind P is and moves no figure
  (SPC-161). Neither is ever filled in unasked.
● **Three rules pick the response**: minimax (least worst case, the default and the cautious rule), expected value
  (least probability-weighted score) and minimin (least best case, the optimistic rule, not a robust one). Each
  reads the remainder row as it reads the operator's rows.

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
  an orbit not current, a red element set newer than the burn (it may already contain it; for a row of several
  burns, at or after every one of them), a start more than 10 km
  or 100 m/s from the bound red track, or a cost over the cap. While running, a failed sample or a series that does
  not converge refuses the row by name.
● **Converged** means P5, P50 and P95 are each known to within 1 km, or 5 per cent of P5 where that is larger
  (SPC-117): the operator reads P5 to answer "can it reach one of mine", and 8 km at 800 km changes no answer.
  Below 20 km the 1 km floor governs.
● **The cost cap** is 12,000 sample-hours, what the 300 s budget covers at the slowest rate measured (40
  sample-hours a second), with 9 minutes of set-up counted per sample. The owner ruled on 2026-11-05 to raise the
  budget from 120 s, when the cap was 4,800 (SPC-178). An over-cap row is refused naming the longest horizon that
  would fit; the panel says about 23.7 h fits at 500 samples with no burn to size. Nothing else ends a run before
  its budget: the page polls without limit, no reaper ends a job (it stops only when cancelled, replaced, signed out
  of, when the sign-in expires 8 h after it began, or at shutdown), and no server or container timeout applies to it.
● **Off the request** (SPC-113): a scenario that samples runs as a session job the page polls every 2 s, naming the
  hypothesis being sampled, the samples done and the budget used, with a Cancel button. One sampled evaluation runs
  on the server at a time; a second waits and its budget starts when it runs. A stopped evaluation scores nothing and
  says why.
● **On screen** (SPC-115): a sampled cell shows P5 to P95 with the median, the half-width P5 is known to, and the
  score's spread across samples. Since SPC-202 every sample also draws both objects' element-set error along track,
  and the cell says so with each side's error and age; the hover names what is still not in the band: element-set
  error across track and the hypothesis being wrong.

## Phase 3: computed outcomes, custody and our burns

**Status: built (SPC-118 to SPC-125).** Gate passed by `decision_phase3` in
tests/unit/test_decision_reference_cases.py.

● **Computed closest approach** (SPC-120): with both sides bound, a row whose action does not move red (no action,
  a sensor retask, a posture change) gets the pair's closest approach with no burn, propagated by SGP4 from both
  element sets, searched every 60 s with each local minimum refined to 0.01 s. A manoeuvre row with no hypothesis is
  refused, saying to add one: where red goes if it does not move is not the outcome of a manoeuvre. Since SPC-200 the
  search holds the RK45 path's re-entry floor, 100 km: an object below it at any instant searched has decayed, and
  every computed cell is refused, saying so. Since SPC-202 the miss carries a band beside it, the miss less and plus
  both element sets' error at the closest approach in quadrature, and the score reads the band's lower edge.
● **One propagator per figure**: computed is SGP4 on both objects, sampled is RK45 on both. When a matrix holds
  both, the result states the measured gap between the two propagators.
● **The span searched** (SPC-118) runs from the scenario epoch to the earlier of the horizon's end and the moment
  either element set passes its limit, and the page states a trimmed span.
● **The time of closest approach** carries an uncertainty (SPC-118, SPC-124): both element sets' position error over
  the closing speed, erring wide, and the hours after the epoch are printed no finer than that uncertainty. Since
  SPC-202 a sampled TCA's uncertainty holds only the error's growth from the scenario epoch to the TCA, since every
  sample draws the error at the epoch.
● **Custody** (SPC-123) is the operator's definition: timely and actionable information to judge whether a burn is
  normal and how the warning time changed. With a red track bound, the route reads its custody as the sweep does and
  carries it over the horizon on the assumption that no newer element set arrives: it is lost from the earliest of
  the scenario epoch if lost already, the newest element set passing its limit, and a hypothesised burn that set cannot show.
  A row of several burns is read at the earliest burn it applies (SPC-184).
  Degraded custody, which can judge the warning time but not whether a burn is normal, is degraded until one of
  those would lose it. The owner ruled on 2026-11-05 that it scores between held and lost (SPC-179): each hour
  degraded carries 0.25 of the custody penalty an hour lost carries, a ruling and not a sourced figure. The hours it
  is degraded are shown as degraded in the cell, its basis and the result's custody note, never as held or lost, a
  span under 0.1 h as "under 0.1 h" rather than 0.0 h, and the custody gap counts lost hours only. Once one of those
  rules loses it, it is lost, as held custody is. A manoeuvre with no burn time takes the worst case, a burn at the scenario epoch, and says
  so, unless custody is lost at the epoch already. Our response is not applied to custody.
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

**Status: built (SPC-171; any age, SPC-181).** Threat Understanding concept, docs/threat_confidence_concept.md,
section 7.5, and section 9, decision 9.

● The engine reads the Threat range, Understanding, cues and decide-by of the last sweep in the session, when it was
  of the bound red track, at any age, and decide-by only for the blue asset it was set for, so the two never
  disagree. The session holds one picture, so a later sweep of another red track replaces it, as does a sweep whose
  model failed. Threat and Understanding are shown as separate sentences, each with its axis named.
● Every figure and sentence the picture feeds carries its age at evaluation in words beside it: the threat lines,
  the decide-by, the collect-first advice and rows, the expected-value guidance and each row's Understanding, for
  example "from the sweep's picture assessed 3 h 10 min before this evaluation". A picture states when it was
  assessed; one assessed after the evaluation has no age to show, so it is not read.
● The sweep words its decide-by against its own clock. One still ahead at evaluation holds only clock times and is
  shown as the sweep worded it. One that has passed by the evaluation is said again against the evaluation: when it
  was, and when the intercept could arrive, in hours after the evaluation, or that it could have arrived before it.
  So the line never says "Decide by" a past time, and it agrees with the advice below it.
● The sweep's advice is judged against the action line: the Threat band at which the owner may set that a response
  changes, HIGH by default, tuned, not sourced, said in a sentence of its own beside every advice that names it.
  When the Threat range straddles it and a collection that could move the range off it lands before decide-by, the
  sweep would collect first; with no such collection, or decide-by passed, it says act on the ceiling.
● The engine collects first only for a collection whose outcomes give different recommended responses (SPC-204, set
  out below). The outcome matrix reads no Threat band, so none does, and the advice says the collection would narrow
  the Threat range but cannot change the recommended response, and never says to delay the decision for it.
● Collections are listed beside the ranking, never scored, so the recommendation is always one of the operator's own
  rows.
● Under expected value, a bound row whose Understanding is LOW, or any row whose P the form records as never
  edited, carries the guidance that expected value rests on a probability the evidence has not earned, and
  recommends minimax. The selector is never switched for the operator.
● **Whether each P was edited** is recorded by the form (SPC-183), so a deliberate 0.5 is the operator's own. The
  NOTSO region inside the form is asked again on every change, with every row's id and P, and answers with a hidden
  field per edited row, keyed by its id, which the next change and Evaluate send back. A row is edited once its P is
  posted as anything but the text the panel gives every row, and stays edited, through re-renders and row additions
  and removals. Evaluate also reads the P posted beside the record, so an edit to anything but 0.5 just before
  pressing it counts; an edit away from 0.5 and back that the region has not yet answered is not recorded, and the
  row shows the guidance, the cautious side. A row whose P came from an applied NOTSO suggestion counts as edited.
  htmx's HX-Trigger-Name header names the element that asks, the region, not the field that changed, so the record
  compares each P with the panel's text instead. Retyping the same value is no change to the browser and is not
  recorded, so a deliberate 0.5 is made by changing P and setting it back. A row whose P was never edited says its P
  is the panel's default and only its Conf the operator's.

Concept section 9 records the choices this rests on, each Claude's choice when built: decision 9 (where the
engine reads the Threat range and decide-by), decision 10 (collect first with no decide-by), decision 11 (what counts
as an untouched probability, ruled on 2026-11-05: the form tracks whether each P was edited, SPC-183), decision 12
(collect-first rows are listed, not scored) and decision 13 (what a scenario opened from the sweep can carry,
SPC-150; every burn of the transfer, SPC-184).

## Every burn of a transfer

**Status: built (SPC-184).** Owner ruling, 2026-11-05: carry every burn of the transfer (concept section 9,
decision 13).

● A scenario opened from the sweep carries every burn of the entry's transfer on its row, each at its own UTC time
  with its own prograde, normal and radial parts in m/s, read as in-track, cross-track and radial. The departure
  burn's parts are its VNB parts, as before, which match on a near-circular orbit; each later burn's are split in
  red's own RIC frame at its state on the transfer, where the engine applies it, since a Lambert or minimum-time
  solution splits its arrival burn at the target's state. The burns are one adversary action with one P, never
  alternatives. The departure burn fills the row's fields; the panel lists every burn in words before Evaluate and
  carries the later burns beside the first burn's fixed time. A transfer of one burn fills the panel as before.
● A solution whose listed burns do not sum to its delta-V does not list every burn: a V-bar or H-bar hop solution
  lists its entry and final burns of 3 hops. Its row carries the departure burn alone, as before SPC-184, and the
  panel says why.
● Wherever the row is sampled, and wherever our burn is sized against it, red makes every burn the row applies in
  time order, each in the RIC frame of its own state at that burn. A burn due after the span searched ends is handed
  to no sample, so no figure flies it. Our sized burn's line, and the closest approach an after-TCA refusal names,
  say red's nominal transfer and how many of its burns it flies; the row's burn line names the burn its series
  starts from.
● A burn at or before the bound red element set's epoch is never applied, since that set may already include it.
  Exactly those are dropped and the rest kept, and the panel, the result, the session log and the provenance name
  each burn applied and each dropped. The row then starts from its first applied burn, from the bound red track's
  own state there. A row whose every burn is dropped is refused as a single burn that set may include is, and when
  its first burn is exactly at the set's epoch, where a single burn's check would not refuse, by a sentence of its
  own.
● A later burn over 1,000 m/s, the limit on the departure burn's own field, held by the burn's size, is named on the
  panel before Evaluate, and Evaluate refuses the row naming the limit.
● Custody reads the earliest burn the row applies. The cost counts the row's integration from that burn, as for
  one burn there, and the panel fits its sample count to the budget from it.
● Each figure's basis names how many of the row's burns it applies: the sampled closest approach and its time
  name the burns red flies before the span searched ends, custody names the burn it reads, our sized burn names
  the burns it was sized against, and a lookup or the score applies none.
● The game tree refuses a row of several burns (below, D3 and D7), and the one-turn result stands with the reason.

Decisions taken building it, Claude's and not rulings:
● **Each later burn's spread.** A later burn is sampled with the row's pointing, timing and drag spreads, and a
  delta-V spread in proportion to its size (the first burn's spread over the first burn's delta-V). Each burn
  draws from a seed of its own, set by the row's seed and the burn's number, so a burn draws the same spread
  whichever burns before it are dropped. Its timing is drawn on its own, not tied to the first burn's; a later
  burn drawn before the first is made at the first.
● **At or before.** A burn exactly at the red element set's epoch is dropped from a row of several burns, as the
  ruling words it. A single burn at that epoch is still sampled, as before (`decision._after_burn` refuses only a
  burn strictly before it), so the single-burn path is unchanged.
● **Which solutions list every burn.** A solution lists every burn when its burns' sizes sum to its delta-V, to
  1 part in a million. The sweep's own sums agree to about 1e-13 m/s; a hop solution's fall short by a third or
  more. The hop's own burns are not rebuilt here: its final burn is placed on red's unburnt orbit, so it is not a
  flown sequence to carry.
● **The later burns' frame.** The solver's arrival burn is split anew at red's own state on the two-body transfer
  arc (`maneuvers.Burn.own_ric`); the sweep's own figures are unchanged. The engine's RK45 arc, with J2 and drag,
  differs slightly from that two-body arc, as the departure burn's SGP4 start does.
● **The tree refuses every row carrying more than one burn**, even when only one of them is applied, since each
  later turn burns again from the row's first burn as hypothesised.
● **Show trajectory** draws the first burn the row applies, since the view takes one burn, and the cell names the
  later burns it does not draw.
● **The panel's fields set burn 1 only.** The later burns are carried as the sweep gave them; a transfer carries at
  most 8 burns, and a later burn after the horizon is refused beside the form.

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
  show no interval. Since SPC-203 the remainder of P takes up each move, a P is checked only up to where the rows'
  P reach 1, and the joint range is the box of the intervals cut where they would sum above 1; with the rows' P at
  exactly 1 no remainder row is evaluated, so nothing is checked and the line says so.
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
● The tree runs as one evaluation in the one sampled slot, inside the 300 s budget. A run that overruns keeps the
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
  by the operator (SPC-187). Until then a row carrying several burns of one transfer (SPC-184) refuses the tree,
  since equal turns put a row's burn at one time in every turn and cannot give each burn a turn of its own;
  unequal turns are SPC-187.
● **D4. Samples carried as themselves.** Sample k is carried from turn to turn as sample k. Each turn's draws are
  seeded from the row's seed, the turn and the red path, so the same evaluation gives the same tree. A sample whose
  drawn timing puts its burn after its turn ends keeps that burn, and the turn after makes it then. Owner ruling, 2026-11-05: keep.
● **D5. What a figure means.** Each node's closest approach runs from its turn's start to the span's end, as if no
  one moves again. A sequence's closest approach is the smallest along it, P5 of each sample's own minimum where red
  was sampled; its delta-V is our burns added up, a lookup when any turn's is; its custody is the bound red track's
  with the earliest red burn on it; its score is the one-turn weighted sum on those figures, a lookup. Owner ruling, 2026-11-05: keep.
● **D6. The caps.** At most 1,000 branches, the sum over turns k of (rows times responses) to the k, and the same
  cost cap as the matrix, 12,000 sample-hours since the 300 s budget, with 16 sizing trials charged for every sizing.
  So coplanar_leo at 50 samples over three 2 h turns costs about 6,700 sample-hours. It was refused under the 4,800
  cap when the budget was 120 s, though its prototype ran in 33 s idle, and it fits now; at 150 samples it costs
  about 15,400 and is refused. Owner ruling, 2026-11-05: raise the evaluation budget to 300 s (SPC-178, built), then measure trees under
  load and set their own cap from the measurements (SPC-188); until then the tree shares the matrix's cap.
● **D7. Refused before anything runs, the matrix kept.** An unbound or out-of-date side, a row with no orbit to carry
  on, a row of several burns (SPC-184), a burn outside its turn, too many branches or too high a cost refuses the
  tree, in that order, and the one-turn result stands with the reason. Owner ruling, 2026-11-05: keep.
● **D8. Never cut short silently.** A spent budget keeps the deepest turn built in full, naming the run's own budget;
  a failed or unconverged branch keeps the turns built and names the branch, since a pick over a tree missing a
  branch could miss its worst case. Owner ruling, 2026-11-05: keep.
● **D9. Picks over what we could have seen.** A turn's pick may depend only on what the turns before it showed, so
  red moves that show the same thing are one information set and one pick must serve every branch in it. Minimax
  takes the worst sequence over every red move and every branch in the set, minimin the best, and expected value the
  mean weighted by P and by the update. A set with no weight has no pick and says so. The first response wins a tie.
  Owner ruling, 2026-11-05: keep.
● **D10. The likelihood model is the engine's own custody rule.** Custody lost at a burn in the turn shows a burn,
  not which; held through it shows no burn; degraded, lost for another reason, or not read, shows nothing. Each row
  gives one of these for certain. This was chosen over a new detection model with made-up rates. The update is a
  lookup. Owner ruling, 2026-11-05: keep. Degraded custody scores between held and lost since SPC-179, but it is
  neither held through a turn nor lost at a burn from held, so it still shows nothing.
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

## The decision record (SPC-192)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-01 found that a finished evaluation lived only in the sign-in's memory
and one line of the session log, so once the sign-in ended no one could show what the operator was recommended,
chose or rejected. That is the record half of gate G1 ("Advisory, decision recorded", rated Red: "Record: none
(F-01)"). SPC-192 addresses the record half only: the advisory half was not reassessed, and neither was the gate's
Red rating, which stands until the evaluation is repeated. The engine now keeps one record for each finished
evaluation, in the `decision_records` table beside the accounts.

● **What a record holds.** It is written when the evaluation finishes, whether the request answered it or a job ran
  it: when, in UTC; the signed-in operator's username; the scenario's name; the rule used and the response the
  one-turn matrix recommends under it, by id and name; for a game tree, the rule's own pick for turn 1, which can
  differ from the one-turn matrix's, and the tree's recommendation lines as the results showed them, or why it has
  none; the picks of all three rules, minimax, minimin and expected value, each taken with the engine's own
  `find_robust_response` on the same matrix, which reads the figures and changes none; when expected value's
  probability is not earned, the guidance the results give for it, whichever rule ran; the code version, the
  calibration source and every input hash from the result's provenance; the turns; the keep-out distance; and the
  scenario's responses by id and name, so a decision is checked against them. Since 0.28.0 it also holds the
  deployment's primary rule and whether the rule used differed from it (SPC-194), and the evaluation's stored inputs
  with their SHA-256 (SPC-193); both are set out in the next two sections.
● **What 0.27.0 did not hold.** A record written by 0.27.0 holds no element-set text and no raw input, and no primary
  rule: its hashes say which inputs were used but cannot rebuild them, so it cannot be replayed. init_db adds the new
  columns to a 0.27.0 database in place; such a record reads "Primary rule: not recorded" and the replay command says
  it holds no stored inputs.
● **Text both databases take alike.** PostgreSQL's text refuses U+0000, which SQLite stores. A name holding it is kept
  with the replacement character, U+FFFD, in its place, so the record is still written; a rationale holding any
  control character other than tab, line feed and carriage return is refused with a sentence.
● **When none is written.** An evaluation refused before it runs, stopped by Cancel, a sign-out, a newer evaluation
  or shutdown before its sampling finished, or that fails writes no record. Nor does one whose account was deleted
  before the record was written: the write checks, in its own transaction, that the account still exists under the
  same id and name, so a later account handed the freed id by SQLite cannot inherit it. A record the database will
  not take is logged, and the results then say that no decision can be recorded against them.
● **A record whose results were never shown.** Once a job's sampling has finished it writes its record, in a state
  Cancel does not stop, and only then shows the results. A record can therefore describe results the operator never
  saw: the console was reloaded or closed while the job ran, or a newer evaluation or a sign-out came while the
  record was being written, when the job stops with its record kept. The operator can decide it on the Decision
  records page.
● **The operator's decision.** The results end with a form, outside the evaluate form, that asks what the operator
  decided: one of the scenario's own responses, None of these, or Decision deferred, with a rationale of at most
  2,000 characters, required for None of these. The same form sits under each of the operator's own records not yet
  decided on the Decision records page, so a record whose results are gone can still be decided: the operator can
  decide it on the Decision records page. A record takes one decision, once, stored with its own UTC time: a second
  is refused with a sentence, and only the operator who ran the evaluation may decide it. A record that is not the
  operator's is refused with the same sentence as one that does not exist. An admin reads every record but decides
  only their own.
● **Decision records.** A page reached from the Decision Engine panel lists the operator's own records, newest first,
  each with when, the scenario, the rule used and its pick (for a tree, the one-turn matrix's pick and the tree's
  own), the primary rule and its pick, the recommendation shown, and whether the rule used differed, all three
  rules' picks (a record from before 0.28.0 says "Recommended:" for the rule used's pick and that the results showed
  only that rule), when expected value's probability is not earned, and
  the decision, its rationale and its time, or "No decision recorded". An admin sees every record
  and whose it is. Records are kept by account, so they are there after signing out and in again.
● **Retention and access.** No retention is applied: records are kept until the owner decides otherwise. A record
  holds a username, free text (the scenario's name, the response names, the rationale and, since SPC-195, the reason
  a response is not permitted) and, since 0.28.0, the
  evaluation's stored inputs, element-set text included, so retention and access are the owner's decision, as data
  protection lead. The owner's open retention ruling (SPC-228) now covers the stored inputs too.
● **Claude's design choices, awaiting the owner's ruling.** The recommendation stored is the one-turn matrix's pick,
  with a tree's own turn-1 pick beside it. A job's record is written in a RECORDING state that Cancel cannot stop.
  A record is kept when its account is deleted, under the username it was made with, readable by an admin and
  decided by no one; erasing it with the account instead is the data protection lead's call. The Decision records
  page has no pagination and no limit.

## Every rule side by side, and the primary rule (SPC-194)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-03 (Critical, gate G3) found one rule per evaluation, chosen on the panel
and changeable after a result was seen, with no side-by-side result and no flag when the rules disagree. Gate G3
("All rules' results available; disagreement flagged") was rated Red; that rating stands until the evaluation is
repeated.

● **Three picks on every result.** The results show the picks of minimax, minimin and expected value side by side,
  each with its rule's one-line meaning, each the engine's own `find_robust_response` on the result's own matrix: the
  same function, `rule_comparison.matrix_picks`, gives the record its three picks, so the page and the record have one
  source. The picks rest on the composite scores, a lookup, and the results say so.
● **Agreement in words.** When the three picks agree, a line says "All three rules agree: each picks" the response.
  When they do not, a line says "The rules disagree:" and names each pick with the rules that make it, as in
  "minimax and expected value pick Avoid (F1); minimin picks Hold (F0)". Under expected value, when its probability
  is not earned, the existing guidance stays beside its pick, whichever rule ran; it says what minimax picks, not
  what it recommends, since the recommendation is the primary rule's. Since SPC-203 a row at P 0 leaves its weight
  to the remainder of P, so expected value always has weight to pick on. Only a record 0.28.0 or 0.29.0 wrote,
  replayed under the rule it was evaluated by, can hold every row at P 0 with nothing to weigh: expected value then
  has no pick, on the matrix as on the tree, the replay says so, and it is never counted as agreeing with another
  rule. `find_robust_response` itself gives no pick there (SPC-200, evaluation F-31), so nothing is starred
  under expected value either.
● **A tree's turn-1 pick under each rule.** Where a game tree was built, each rule's turn-1 pick is
  `tree_selectors.select` over the tree already built, turns built in full only; nothing is sampled again. A second
  line says whether the rules agree on turn 1, flagged in the same colour as a disagreement on the matrix. It names
  the turns asked and, when the budget stopped the tree sooner, the turns built in full, as in "Over the 2 turns,
  built in full to turn 1 only". Expected value can have no pick when every row has P 0, and the line says so. With
  every response marked not permitted (SPC-195), no rule has a pick and the line says that, not that the rules
  disagree.
● **The deployment's primary rule.** `SPECTRE_PRIMARY_RULE` names it: minimax, minimin or expected_value, read where
  the other settings are read (`spectre/config/settings.py`). Unset, it is minimax, the cautious rule. The panel's
  selector starts on it. The headline recommendation is the primary rule's pick. When the operator chose another
  rule, the result says the primary rule and its pick beside the chosen rule's, so no rule chosen after the fact can
  hide the primary's answer. With the primary rule having no pick, the headline reads "No recommendation" and the
  primary line says why. The evaluation itself still runs under the rule chosen: the matrix's star, the ranking's
  blue highlights, the interval lines of SPC-132 and a tree's lines and update follow it, and a line above the
  matrix says the star marks the rule chosen's pick and, when that is not the primary rule, names the primary's
  beside it. Every line under the headline is set smaller than the headline.
● **The session log** names the recommendation as the results showed it: the primary rule's pick, with the rule
  chosen's beside it when it was another rule.
● **On the record.** Each record keeps the primary rule when it ran and whether the rule used differed from it, in
  two new columns that init_db adds to a 0.27.0 database in place. The record's `recommended_*` columns keep the
  rule used's pick, as in 0.27.0; the records page calls it the rule used's pick, and says the primary rule's pick
  was the recommendation shown, so "recommendation" means one thing on every page. A rule with no pick is held as an
  empty id and name and listed as picking nothing, with the reason: every row had P 0, or, since SPC-195, every
  response was marked not permitted. A record from before says its primary
  rule was not recorded, and keeps its old wording, "Recommended:".
● **Claude's design choices, awaiting the owner's ruling.** Minimax as the default primary rule, being the cautious
  rule. A value of `SPECTRE_PRIMARY_RULE` that names no rule is not refused at boot: it is logged as a warning, once
  per value, and read as minimax, so a typing slip leaves the console running on the cautious rule. A posted rule
  that names none, or none posted, falls back to the primary rule. The primary rule is read when the results are
  shown and when the record is written, so a change to the setting applies to the next evaluation.

## Replay from the stored record (SPC-193)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-02 (Critical, gate G2) found that provenance hashed the inputs and
stored none, so a recommendation could not be reproduced once the sign-in ended; identical inputs already repeated
exactly (probe P-15). Gate G2 was rated Red; that rating stands until the evaluation is repeated.

● **What is stored.** With each record, one canonical JSON document and its SHA-256: the whole Scenario (rows,
  responses with any veto and its reason (SPC-195), weights, horizon, turns, keep-out distance and observation; every hypothesis with its dispersions,
  sample count and seed, and a transfer's later burns; each accepted NOTSO prior with its cover and counted notices;
  the Threat picture with its cues; and the binding, each bound element set's text as read, its epoch, age, limit,
  data mode and custody), the rule the evaluation ran under, the composite score matrix, the code version, and
  whether the evaluation's time budget ran out. The text is canonical: keys sorted, no spaces, ASCII with every other character escaped, no NaN. A name holding U+0000
  is stored exactly, escaped, which both databases take.
● **Written and read strictly.** `spectre/domain/decision_inputs.py` writes every dataclass field by field from its
  own declaration, so a field added later cannot be left out unseen, and reads strictly: it refuses text whose
  SHA-256 does not match, a repeated key, text not in canonical form, a schema or version it does not know, an
  unknown or a missing field at any depth, a value of the wrong kind, a scenario the engine's own checks refuse, and
  scores that do not fit the scenario. Each refusal names where in the document it is.
● **Replay.** `scripts/replay_decision.py RECORD_ID` reads the record from the configured database, rebuilds the
  Scenario from its stored inputs, evaluates it again under the stored rule with `evaluate_tree`, as the console
  does, and reports whether the recommendation (the primary rule's pick), the rule used's pick, each rule's pick, a
  tree's turn-1 pick and every composite score match the record exactly, compared at full precision.
● **Set against the record's own columns.** The SHA-256 sits in the same row as the text it covers, so on its own it
  shows only accidental change: an edit that rehashes the text passes it. The replay therefore also sets the record's
  own columns against the hashed inputs: its rule and code version columns against those inside the document, and
  every input hash the record holds, from the original result's provenance, against the replay's own. An edit to the
  stored inputs that is rehashed, such as a bound element set renamed, cannot match the input hashes held apart, and
  the report names each one that differs.
● **Versions and the time budget, said first.** Before replaying, the command says which code version wrote the
  hashed inputs, read from inside the document, not from the unhashed column; when that is another code version than
  the one running, it says the comparison is across versions, and the verdict says so too. When the evaluation recorded ran out of its
  300 s budget, a sampled row refused, a burn left unsized or a tree built in part, the stored inputs say so; the
  replay runs in full with no budget, so it says before comparing that what the budget left out may differ, and the
  verdict says so again if the replay differs. A record written by 0.28.0 or 0.29.0 is replayed under the rule it was
  evaluated by, and the command says so first too (SPC-203, set out below); so is a record of 0.28.0 to 0.31.0,
  under the miss rule it was evaluated by (SPC-202). A record with no stored inputs is said to hold none, with no version
  line. It exits 0 when the replay matches, 1 when it differs, 2 for a usage error and 3 when there is nothing to
  replay, or no database at the configured SQLite path.
● **It writes nothing.** A SQLite database is opened read-only, and one that is not at the configured path is not
  created: the command says there is none and exits 3. A PostgreSQL database is only read.
● **Element-set text is held.** Storing it reverses 0.27.0's "no element-set text". This is Claude's choice: the
  record is held in the deployment's own database, as the NOTSO cache already is, under the owner's rulings of
  24 and 28 October 2026 that holding cached data is acceptable. docs/SECURITY.md lists it, and the owner's open
  retention ruling (SPC-228) now covers the stored inputs too.
● **Claude's design choices, awaiting the owner's ruling.** One schema version, 1, when built; since SPC-195 the
  document is written as version 2, since SPC-203 as version 3 and since SPC-202 as version 4, every earlier version
  still read (see the sections on each).
  Replay runs with no wall-time budget, so an evaluation the 300 s budget cut short, a sampled row refused or a tree
  built in part, is replayed in full and the comparison may then differ; the stored inputs record whether the budget
  ran out, so the report says why, and names where. The code version is stored in the document, so it is covered by
  the hash, and it is the one the report says first. A record whose inputs could not be encoded is not written, and the
  results say no decision can be recorded, as for any record the database will not take. The replay is a command
  for an administrator with access to the database; no route or page offers it.

## Responses not permitted (SPC-195)

**Status: built. Each choice below is Claude's design choice, not a ruling.** Evaluation finding F-04 (Critical, gate
G4, "Hard constraints enforced as vetoes before aggregation") found that no field could mark a response unacceptable,
so a response that breaks a legal, rules-of-engagement or safety constraint was recommended whenever it scored best
(probe P-06). Gate G4 was rated Red; that rating stands until the evaluation is repeated. Constraint libraries drawn
from doctrine or from rules of engagement are the owner's to supply later: what is built is the operator's own veto,
response by response, with a reason in words.

● **A veto on each response** (Claude's choice). Each friendly response row on the panel carries a labelled "Not
  permitted" checkbox and a labelled reason field. The reason is required when the box is ticked, at most 500
  characters of one line, stored without its surrounding spaces; a reason holding a control character is refused
  with a sentence. A reason typed with the box not ticked is refused rather than dropped unsaid. The box posts its
  row's own id, so a tick that names no row, or two rows sharing an id, is refused and the panel asks to be reloaded;
  so is a tick posted with no reasons at all, which is never read as permitted.
  The veto and its reason are fields of the response, `vetoed` and `veto_reason`, not permitted by default.
● **Removed before aggregation** (Claude's choice). `find_robust_response` ranks only the responses not marked not
  permitted, under every rule, so a vetoed response is never any rule's pick: not the headline, not a pick beside it,
  not a pick in the record. A tie is broken among the permitted responses alone, the first of them winning as
  before, so a tie never brings a vetoed response back. With every row at P 0, expected value still has no pick.
  The NOTSO interval lines read the same permitted responses. On a game tree, a response not permitted is never
  valued in any information set, so no turn picks it and no plan mark falls on its branches; the recommendation per
  turn names each such response as never picked.
● **Still evaluated and shown** (Claude's choice). A vetoed response is evaluated exactly as before, so every figure
  is the same vetoed or not, and the operator sees what was excluded and why. It is greyed in the matrix, with "Not
  permitted:" and its reason in words in its column's heading and a dashed outline on its cells; in the rankings it
  is listed after every permitted response with no rank number, so it is never ranked first, and carries the same
  words; on the tree each branch of it carries them beside its heading, and every later branch below it is greyed
  too, saying it follows that response, since the whole sequence is excluded. A line above the matrix names each
  response marked not permitted with its reason and says that no rule picks it. On the panel the box keeps its own
  width, so its words stay beside it at any width.
● **Every response marked not permitted** (Claude's choice). No rule has a pick, so the headline reads "No
  recommendation", the agreement line says no rule picks a response since every response is marked not permitted,
  and a tree's agreement line says the same of turn 1, not that the rules disagree; both are flagged in the colour a
  disagreement takes, since nothing is recommended. The primary rule's line says why, nothing is starred, nothing is ranked, a tree's turn 1 has no pick and says why,
  and the record stores no pick. Under expected value with a probability not earned, the guidance says minimax picks
  nothing, for the same reason.
● **On the record** (Claude's choice). Each response a record lists carries its reason when it was marked not
  permitted, so the Decision records page lists which responses were vetoed and why. The operator may still record a
  vetoed response as their decision, but only with a rationale; the decision select labels it as marked not
  permitted, and the decision, on the results and on the records page, says it was marked not permitted, with its
  reason.
● **Stored inputs, version 2** (Claude's choice). The stored inputs wrote version 2 of their document, which
  holds each response's veto and reason, and version 3 since SPC-203, which keeps it (set out in the next section).
  A record written by 0.28.0 holds version 1, with no veto: it is still read,
  every response permitted, and replays as before. A version 1 document holding a veto is refused, naming where.
  The scenario's provenance hash leaves out the veto of a response that is permitted, so a scenario with nothing
  vetoed hashes exactly as it did in 0.28.0, and such a record's input hashes still match its replay; a veto changes
  the hash. Where the record's responses or its stored inputs mark any response not permitted, the replay sets the
  one against the other, so a veto dropped from the record's column is caught.
● **Not built.** Scenario-level constraints, a constraint applied across responses or tied to a rule set, wait on
  the constraint libraries above. The veto weighs nothing: it is not a penalty in the score, and no score or weight
  changes with it.

## Element-set integrity and the operating envelope (SPC-201, SPC-200)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed in the
envelope document.** Evaluation finding F-25 (Critical, gate G9), with F-34, found that element sets from UDL reached
the engine with no checksum or range check: probe P-14 changed one digit of an inclination, 97.4 to 98.4 degrees, with
the old checksum, and the computed miss moved from 10.4 to 13.4 km with no flag; the background refresh replaced a
good held set with it; an inclination of 597.4 degrees was accepted. Finding F-09 (Critical, gate G10), with F-30 and
F-31, found no stated operating design domain, and decayed objects passing silently; F-29 found deep-space orbits
evaluated with no regime statement, which this closes in part, by a flag, leaving the limits sourced for them to
SPC-215. Gates G9 and G10 were rated Red; those ratings stand until the evaluation is repeated.

● **The operating envelope is written down** in docs/decision-engine-envelope.md: the regimes, element-set ages,
  horizons, scenario sizes, turns and inputs the engine is fit for, each with where in the code it is enforced and
  what lies outside it. `tests/unit/test_decision_engine_envelope.py` holds every row to the code.
● **One acceptance check for an element set** (`spectre/astro/elset_check.py`): both line numbers, lengths,
  checksums and plain ASCII characters; one readable catalogue number on both lines, and the number asked for when a
  set is fetched for one; an epoch that reads as a day of its year; every field the check reads written in the
  format's own characters, so a corruption the checksum cannot see, such as a 0 changed to e, is refused; the
  inclination, eccentricity, mean motion and the three angles inside their ranges; and an orbit SGP4 can start from.
  B* and the two derivatives of the mean motion are checked as readable, not against a range, since none is
  sourced. Every path an element set enters by runs it, the Pattern of Life history behind custody included, and the
  binder runs it again. A refused set is not stored and never replaces a held one; the refusal is logged without the
  set's text and shown in a sentence naming the object and what failed, on the page or, where the path has none, in
  the run log. The bundled watchlist passes in full.
● **Checked at evaluation entry.** Each bound set on SDP4, SGP4's deep-space branch, is flagged under "Outside the
  operating envelope" on the result, not refused: for a GEO set, its staleness limit and element-set error model are
  the GEO rules of thumb, tuned rather than sourced; for any other orbit on SDP4 they are rules of thumb set for LEO
  and GEO, not validated for it. Limits sourced for them are SPC-215. An object below the re-entry floor at an
  instant the SGP4 search reads, or that SGP4 itself reports decayed, is refused there and said once on the result
  (F-30). All 5 weights at 0 are
  refused beside the form, and expected value with every row at P 0 gives no pick and says so (F-31); since SPC-203 the remainder of P
  carries the weight the rows leave, so that arises only replaying a record 0.28.0 or 0.29.0 wrote.

## What P means: the remainder of P (SPC-203)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-12 (High) found that expected value divided each P by the sum over the
rows entered, with no residual row and no check that P sums to 1, so a single row at P 0.1 was evaluated exactly as
at P 1.0 (probe P-03b): a 1 in 10 manoeuvre was weighed as certain, and the chance that none of the listed actions
happens was never weighed. Gates were not reassessed; their ratings stand until the evaluation is repeated.

● **P is a probability over mutually exclusive actions** (the brief's choice). The rows' P must sum to at most 1,
  with a tolerance of 1e-9 for rounding (`P_SUM_TOLERANCE`, in docs/lookup-register.md). A sum above it is refused
  at the panel, before anything runs, and by the Scenario itself, with the same sentence: "Your rows' P sum to 1.5,
  above 1. P is the chance of each adversary action, and the rows must be mutually exclusive, so their P sum to at
  most 1; the engine weighs the rest as no adversary action. Lower the P of one or more rows." The sum is said to
  the ninth decimal at most, so floating-point noise never reaches the page.
● **The remainder row** (the brief's choice). When the sum is below 1, the engine adds one row of its own, last: "No
  adversary action (remainder of P)", a no-action row at 1 less the sum. It is evaluated as any no-action row, a
  lookup unbound and computed where both sides are bound, and every rule reads it: minimax, minimin and expected
  value, the three picks side by side, the game tree, where it is one of red's moves in every turn, the update after
  turn 1, the NOTSO interval lines and the record. In the matrix and the rankings it is named in full and labelled
  "the engine's remainder, not your row"; its source line gives its P and the sum it rests on; on the tree each of
  its branches says beside its heading "(red's move here is the engine's remainder, not your row)"; and the banner
  counts the operator's actions "and the remainder of P". At a sum of exactly 1, within the tolerance, nothing is
  added.
● **The tree counts the remainder as a red move, and says so** (Claude's choice). A tree weighs the remainder only
  if it branches on it, so it is one of red's moves in the branch count, the cost, the largest depth that fits and
  whether a run is needed. An operator who listed 3 rows at P 0.3 has 4 red moves: against 3 responses that is 1,884
  branches over 3 turns, past the 1,000 cap, where 3 rows summing to 1 make 819 and fit. Every size or cost refusal,
  at the panel and before a run, and the built tree's lines, then add "Red's moves count the remainder of P, the
  engine's no-action row, beside your 3 rows: rows whose P sum to 1 leave no remainder, and one red move fewer."
● **Beside an operator's own no-action row the remainder is still its own row** (the brief's choice, and why). The
  operator's no-action row is one of the actions they listed, at the P they gave it, a judgement about that action;
  the remainder is the chance that none of the listed actions happens, which the operator did not state. Folding it
  into their row would change their P unasked and lose which part is theirs. The two rows' cells are alike, and the
  remainder's source line says why it stands apart.
● **The share beside each P** (the brief's choice). Each row shows "Share=" beside its P: the share of expected value
  it takes, which is its P, marked with its P's basis. The share is written exactly as the P beside it is (Claude's
  choice), so the two always read alike: the operator's P as entered, "P=0.0 · Share=0.0", and the remainder's, 1
  less their sum, to the ninth decimal at most for both, so floating-point noise never reaches the page. The
  remainder's P is marked with the weakest basis of the operator's P it rests on, and it shows "Conf: none".
● **The panel's default stays 0.5** (the brief's choice). It is already marked as the panel's default until edited
  (SPC-183). Three new rows sum to 1.5 and are refused until the operator sets P; the guide says so.
● **NOTSO suggestions** (the brief's choice). A ticked suggestion replaces its row's P, so the route applies the
  suggestions before it builds the scenario and sums the P as they will be evaluated; a sum above 1 they make is
  refused naming the rows that carry them, as in "With the NOTSO suggestion applied to row 1, your rows' P sum to
  1.02, above 1." Typed P that a suggestion replaces are not summed.
● **What moved.** Re-derived from each matrix's own cells, not pasted:
  ■ Probe P-03b inverted: one manoeuvre row against Hold and Avoid (cost 0.1). At P 1.0 expected value picks Avoid;
    at P 0.1 the remainder's 0.9 of no adversary action, against which Hold scores least, takes it to Hold, and
    minimin moves from Avoid to Hold for the same reason. Before, both P gave Avoid under every rule.
  ■ The integration form's single manoeuvre row at P 0.6 against Hold and Avoid (the veto tests' two responses):
    minimin moves from Avoid (F2) to Hold (F1), its best case now the remainder's 0.4 of no adversary action;
    minimax and expected value stay on Avoid. The veto tests now post P 1, so every rule still picks one response.
  ■ Every row at P 0 through the panel: expected value had no pick; it now picks the best response against no
    adversary action, Hold (F1) on the form.
  ■ A record of 0.29.0 at P 0.1 (`tests/unit/_decision_records_0_29_0.json`): expected value picked Avoid then and
    would pick Hold now; the replay reproduces Avoid, as the operator was shown.
  ■ Fixtures whose P summed above 1 were set to each row's old share of the sum, so every pinned expected-value pick
    and score holds. Three fixtures took new P to sum to at most 1, and no test pinned their expected-value pick:
    the judgement fixture (0.6 to 0.4 beside an untouched 0.5) moves from Avoid (R2) to Hold (R1), and the
    understanding fixture at its default P (its other row 0.7 to 0.5) from Watch (F2) to Evade (F1); the stored
    inputs' lookup fixture keeps its picks.
  ■ No reference case's pick changed: its one no-action row at P 0.5 now has the remainder row beside it, with the
    same cells, and Hold is still the pick under all three rules at both window starts.
● **Stored inputs, version 3** (the brief's choice of what, Claude's of how). The remainder row is derived, never
  stored as a row: version 3 adds the scenario's probability rule and, beside the rows, the remainder's id, name and
  P, or null, and its score row after theirs. The reader refuses a remainder that is not the one the rows leave, a
  version 3 document whose P sum above 1, and a version 3 document under any rule but the remainder rule: a result
  under the 0.29.0 rule is only ever a replay of an older record, a replay writes no record, and the writer refuses
  to store one. So only a version 1 or 2 document reads as evaluated before SPC-203, and only its replay says so.
  The reader names a document's schema, then its version, before checking its fields, so a document of a version this
  code does not read is refused for that version, not for a field this version would hold. The scenario's provenance
  hash leaves out the remainder row and each
  row's flag, and leaves out the rule for a record of 0.28.0 or 0.29.0, so those records' input hashes still match.
● **Records of 0.28.0 and 0.29.0 replay as they were evaluated** (the brief's choice of what, Claude's of how).
  Versions 1 and 2 hold no probability rule, and read as the rule those releases evaluated by, `ProbabilityRule.SHARES`:
  each row weighed by its P over the rows' sum, with no remainder, P summing above 1 included. The replay therefore
  reproduces every pick and score exactly, and says first that the record was evaluated under that rule and that
  this code evaluates a new scenario with the remainder.
● **Claude's design choices, awaiting the owner's ruling:**
  ■ A Scenario field, `probability_rule`, carries the rule, so one engine evaluates both, rather than a second code
    path for replay; a scenario built in code or on the panel takes the remainder rule.
  ■ The remainder row is added at evaluation (`with_remainder`), not held by the Scenario the operator built, so the
    record stores the operator's rows and the result shows the rows the engine weighed.
  ■ The tolerance works both ways: a sum within 1e-9 below 1 adds no remainder row, as one within 1e-9 above it is
    read as 1. The sum is added exactly (`math.fsum`), so 0.1, 0.2 and 0.7 sum to 1.
  ■ The remainder row has no Conf, and its P is marked with the weakest basis of the operator's P, since it is 1 less
    their sum; it is not listed among the judgement inputs, since nothing on the panel sets it.
  ■ The NOTSO interval checks hold the other rows at their P with the remainder taking up the move; a P is checked
    no higher than the rows can sum to 1, and rows moved together over the corners of their box cut where the sum
    would pass 1 (the box's corners within the sum and the points on its edges where the sum reaches 1). The update
    after turn 1 reads each share's range over the same corners.
  ■ With the rows' P at exactly 1 no remainder row is evaluated, so no NOTSO interval is checked, alone or together:
    a higher P is refused, and a lower one leaves a remainder of P whose cells this evaluation does not hold. 0.29.0
    checked such an interval by rescaling the rows' shares; this code does not, and the line says why and that with
    the rows' P summing below 1 the remainder row is evaluated and the interval checked. Evaluating a remainder row
    at P 0 for the check alone would add a row the brief rules out at a sum of 1, and its cells to the record. The
    update then reads its shares at the P entered.
  ■ The tree counts the remainder as a red move in its size and cost, and every refusal of size or cost says so,
    rather than leave it out of the count and build a tree that does not weigh it.
  ■ On the tree, the label sits beside a remainder branch's heading, not inside it, so the heading keeps its one
    form, "Turn 1 of 2: red No adversary action (remainder of P), our Hold".
  ■ Version 3 holds the remainder rule alone, so a version 3 record can never replay as one evaluated before
    SPC-203; the rule field is kept so the document says the rule it was evaluated by.
  ■ The sum is checked at Evaluate, not as each field changes, as every other panel number is.

## Collect first tied to the recommendation (SPC-204)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-14 (High) found that the collect-first advice rested on Threat range band
steps against a fixed, unsourced action line, and tied that line to a change in the operator's response, but the
threat picture moves no figure in the matrix, so no collection outcome could change the engine's
recommendation: probe P-10 evaluated one bound scenario under opposite pictures and found the matrix and the pick
identical, while one picture was told to collect first. Gates were not reassessed; their ratings stand until the
evaluation is repeated.

● **Decision relevance, computed from the engine** (the brief's choice of what, Claude's of how). For a scenario
  with a threat picture and a cue, `decision.cue_relevance` takes the recommended response under each of the cue's
  outcomes, the picture's range moved to the cue's benign and to its hostile floor and ceiling, with the rule judged
  by. Each outcome's matrix is the evaluation the engine would run under that picture: `ScenarioResult.matrix_under`
  runs the same cell step the evaluation ran, `_build_matrix`, under the outcome's picture, from the plans the
  evaluation made. Those plans (sampling, the computed approach and burns, custody, the span searched) are made from
  the scenario with no picture in them, so no band can reach one, and a band can reach a figure or a score only in
  the cell step, which is run again. Each picture's matrix is built once per result. A test sets the relevance
  against a whole new evaluation under each outcome's picture, under every rule, on the lookup path, on P-10's bound
  scenario and with a test stand-in that moves figures: they agree. The outcome matrix reads no Threat band, so the
  two picks are always the same, and that is a tested, stated result, not an assumption: should a later release let
  a band move a figure, the advice follows, as the stand-in shows.
● **The advice in the engine** (the brief's choice). Where the sweep would collect first, the engine collects first
  only for a cue whose outcomes give different recommended responses and that lands by decide-by, and then names the
  recommended response under each outcome. With no such cue it names the sweep's cue and says so in words, never
  recommending delay: "Collecting "pull its element-set history" would narrow the Threat range but cannot change
  the recommended response: the outcome matrix reads no Threat band." Where the sweep says act on the ceiling or
  below the action line, its advice stands, and when the picture holds a cue and none of them can change the
  recommended response, a sentence says so: "No collection the picture holds can change the recommended response:
  the outcome matrix reads no Threat band." A collect-first row is listed only for a cue that is collected first.
● **The action line is described as what it is** (the brief's choice). The old wording, which tied the line to a
  change in the operator's response, is gone from every sentence, the operator guide included, and a test finds it
  in any case, spacing or quotation. The advice names "the action line at Threat HIGH" and says in a
  sentence of its own: "The action line is the Threat band at which the owner may set that a response changes:
  Threat HIGH by default, tuned, not sourced." The sweep's own advice keeps its range-narrowing purpose with this
  wording.
● **What moved.** Probe P-10 inverted: the same bound scenario under opposite pictures now gives advice that says
  the collection cannot change the recommendation, and nothing in the engine says collect first
  (`tests/unit/test_decision_relevance.py`). Every engine test of collect first and its rows now runs with a test
  stand-in, `tests/unit/_band_stand_in.py`, that lets the picture move figures, and says so. The sweep's advice to
  act on the ceiling, or that the range is below the line, now carries the sentence above when the picture holds a
  cue. No pick, figure or score changed.
● **Claude's design choices, awaiting the owner's ruling:**
  ■ Relevance is judged by the primary rule's pick on the results page, since that is the recommendation shown; a
    result read on its own judges it by the rule the evaluation ran.
  ■ The sweep's own gates stand beneath it: the range must straddle the action line and the cue must be able to take
    the range off it, as well as change the pick and land by decide-by. Relevance is added, not substituted, so the
    action line stays the owner's knob.
  ■ The matrix under another picture is built again from the evaluation's plans, not by a whole new evaluation,
    which would sample and propagate again for each outcome. To make that the same evaluation, every plan is now
    made from the scenario with its picture taken out, which changes nothing today, since no plan read it. A result
    the engine did not build, which holds no plans, scores each cell again from the figures it was built from.
  ■ The test stand-in moves two figures of the response the band disfavours, custody for the whole horizon and a
    closest approach inside the keep-out distance, rather than one: neither alone moves the picks of every fixture
    that reads it.
  ■ Where an outcome's picture moves a cell but not the pick, the advice says that under either outcome the engine
    recommends the same response. It says the outcome matrix reads no Threat band only when no outcome of any cue the
    picture holds moves any cell, so the reason is earned for the whole picture, not assumed from one cue.
  ■ The advice that cannot change the recommendation names the sweep's cue in quotation marks, since a cue is worded
    as an instruction, and carries no action-line sentence, since it does not judge against the line.
  ■ The sentence beside the sweep's other advice is added only when the picture holds a cue and none can change the
    recommended response. Where a cue could but lands after decide-by, the sweep's advice to act on the ceiling stands
    alone. "Treat it as Threat CRITICAL" is the sweep's wording, kept: the sentence beside it says the matrix reads no
    Threat band.

## The weight stability beside the recommendation (SPC-205)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling; they are listed at the
end of this section.** Evaluation finding F-16 (High) found the default weights uncited direct ratings and no weight
stability computed or shown, though in the bound scenarios of probe P-16 moving our delta-V's weight by 0.089 (0.20
to 0.111), or reversibility's by 0.082, flipped the pick under minimax and expected value. Gates were not reassessed;
their ratings stand until the evaluation is repeated.

● **One function in the domain** (the brief's choice). `spectre/domain/weight_stability.py` `weight_stability`
  takes a rule's pick on the one-turn matrix and, for each of the five weights, finds the smallest change of that
  weight that changes the pick, in each direction, the other four scaled in proportion to keep the sum 1, as the
  panel's normalisation scales them, and what it changes to; or that no change from 0 to 1 does. The results page
  and the decision record both read it.
● **Exact, not sampled** (the brief's choice). For fixed cell figures every composite score is linear in the moved
  weight along that path, its five terms (`decision.score_terms`, from the figures the engine kept unrounded on each
  cell) weighed by the moved weights. The pick can change only where two responses' expected-value lines cross, or
  where the row-wise maxima or minima of two responses meet for minimax and minimin, which is where a line of one
  meets a line of the other. Every such point inside 0 to 1 is found and the pick read at each and between each. A
  response marked not permitted is never a pick it reports.
● **Ties and rounding as the engine has them** (the brief's choice of what, Claude's of how). The engine rounds each
  composite score and picks on the rounded scores, a tie going to the first permitted response, as
  `find_robust_response` decides. At each point read the search scores every cell as the engine would at those
  weights, rounds it to 6 decimal places, as the engine rounds it, and aggregates and picks as
  `find_robust_response` does. So a tie the rounding makes is the
  engine's tie, and only a move that breaks it the engine's way changes the pick; and where two lines meet but the
  rounded scores part them, the rounding decides, as it does in the engine. A change at the point itself reads "at"
  and "at least"; one only beyond it, "past" and "more than".
● **The words never overstate** (Claude's choice). Each change is rounded down to 3 decimal places, so "at least" or
  "more than" is never above the exact change. The weight's value it names is rounded away from the panel's, and the
  engine's pick there is checked to be the one the line names; where 3 places would pass a further change, a place
  more is shown. A change found only where every response scores alike says so, and that the first listed takes it.
● **On the page** (the brief's choice). Beside the recommendation, in words: "The recommendation holds unless a
  weight moves by at least 0.165: our delta-V's weight from 0.200 to 0.034 makes it manoeuvre (F0)." A details
  element lists every weight, lowered and raised, with what the search rests on. A rule chosen other than the
  primary rule has its pick's line beside it. The game tree's picks are not covered, and a line says so, on the
  results and on the records page for a record of more than one turn.
● **On the record** (the brief's choice of what, Claude's of which). A new column, `weight_stability`, holds the
  recommendation's line as the results said it, written with the record; init_db adds it to an older database in
  place, and a record from before reads "Weight stability: not recorded". It is stored, not derived, because the
  stored inputs hold each cell's score but not the figures its terms come from, so deriving it would mean evaluating
  the scenario again, sampled rows included. The stored inputs are unchanged, at version 3, and versions 1 to 3
  still read and replay.
● **What moved.** Probe P-16's bound scenarios, through the real engine (`tests/unit/test_weight_stability.py`):
  under the score scales P-16 measured, those of 0.24.2, restored by a test stand-in, the computed scenario gives
  0.0889 on our delta-V (0.200 to 0.111) and 0.0818 on reversibility under minimax, and 0.0873 and 0.0807 under
  expected value; the sampled scenario gives 0.0889 and 0.0818 under both rules, as P-16 measured; each to the
  manoeuvre (F0), within P-16's 0.001 scan step. Custody 0.65, closest approach 0.75 (0.705 under expected value on
  the computed scenario, where P-16's scan found 0.706) and time to execute 0.9 match P-16 too. Under the scales
  built since SPC-191 the same scenarios hold until our delta-V's weight falls by 0.165, or, on the computed scenario
  under expected value, by more than 0.154. A whole evaluation with the weight moved by 0.154 still picks the sensor
  retask, and at 0.045 the manoeuvre. A brute-force fine scan through the engine's own scoring, done in the test
  only, agrees with the exact search on every weight, direction and rule. No pick, figure or score changed; the
  composite score is the same float as before, its terms now named.
● **Claude's design choices, awaiting the owner's ruling:**
  ■ The chosen rule's pick has its own line whenever the rule chosen is not the primary rule, even when the two
    pick alike, since the weights can move the two picks apart.
  ■ Weights that do not sum to 1, as a scenario built in code may hold, are read over their sum, as the panel scales
    them; a weight that carries the whole weight cannot be moved in proportion, and its line says so. Every weight at
    0 gives no stability, and the line says why.
  ■ A change under 0.001 is said to be under 0.001, and the pick then holds only at the panel's weights; the line
    says which way the weight moves to change it.
  ■ The points are where the unrounded lines meet; the rounded pick turns within a millionth or so of each. Where
    two responses' unrounded aggregates stay within one rounding step of each other over a stretch of the weight,
    the engine's pick there turns on the rounding, and the point is still placed where the lines meet.
  ■ The record stores the recommendation's line alone, not the chosen rule's or every weight's.

## Element-set error in the miss (SPC-202)

**Status: built. Each choice not named in the brief is Claude's design choice, not a ruling, awaiting the owner's
ruling; they are listed at the end of this section.** Evaluation finding F-11 (High) found that the closest-approach
payoff was an SGP4 point miss (computed cells) or a P5 over the burn's dispersions alone (sampled cells): element-set
error, which the code's own model puts at 1 km at epoch plus 2 km a day in LEO and 2 km plus 1 km a day at GEO, never
entered it, so bands read tighter than the inputs allow. Gates were not reassessed; their ratings stand until the
evaluation is repeated.

● **The model.** `spectre/astro/along_track.py`'s `_ERROR_MODEL_KM`, the threat sweep's rule of thumb, tuned, not
  sourced: 1 km at epoch plus 2 km a day of age in LEO and MEO, 2 km plus 1 km a day at GEO and beyond (GEO and DEEP
  as `regime_from_tle` reads the set). It is in docs/lookup-register.md. Each set's age is read from its epoch.
● **Sampled cells.** Every sample also draws each object's element-set error along track, from a normal distribution
  whose 1 sigma is the model's error at that set's age at the scenario epoch, red and blue each their own draw. The
  draws are seeded per sample and side from the hypothesis's seed on a stream of their own (`ELSET_ERROR_STREAM`),
  so an evaluation repeats exactly and the burn draws are untouched. The draw moves the object along its own orbit:
  its RK45 arc is read that many seconds later or earlier, the offset over its speed at the window start, which is
  the same orbit moved along itself, so the shared arcs are still integrated once, run a little past each end. The
  band, P5, its convergence and the score all read the moved objects' misses. The cell names each side's 1 sigma and
  age, and its basis names the model and its source.
● **Computed cells.** The SGP4 miss stays the figure. Beside it, a band: the miss less and plus both sets' error at
  the time of closest approach in quadrature, 1 sigma, the same figure the TCA's uncertainty has used since SPC-118,
  never below 0 km. The score reads the lower edge: the operator reads the closer case to answer "can it reach one of
  mine". Each computed cell shows "Element-set error: low to high km", says the band is 1 sigma, and gives what the
  score reads and each set's age at the TCA. A cell on RK45 because our burn was sized carries the same band; our
  burn is sized on the miss itself.
● **The time of closest approach.** A computed TCA's uncertainty is both sets' whole error at the TCA, as since
  SPC-118. A sampled TCA's is not: every sample has drawn both sets' error at the scenario epoch, so the samples' TCAs
  spread by it already, and adding it again to each sample's TCA would count it twice. Its ± and the TCA histogram's
  bin floor hold only what no sample draws, each set's error at the TCA less its error at the scenario epoch in
  quadrature, both sets in quadrature, and the hover and the histogram's caption say so. In the game tree a sampled
  node's TCA reads the same way.
● **The game tree.** Each sample keeps its draws from turn to turn: red's in the state it carries, blue's as the time
  along its orbit it is read at. A sampled turn after a computed one draws both errors at its start, moving red's one
  state along its orbit for each sample. A computed node shows its miss with the band in its basis, and its sequence
  scores the path's closest approach less the error at that node's closest approach, the latest along the path and so
  no smaller than any before it. The node's basis says the sequence's score reads the path's closest approach less
  that error, which is not always the node's own miss less it.
● **Every sentence that said "element-set error is not in it"** now names the error included, its model with its
  figures, its source and the ages read: the computed and sampled bases, the band's hover, each computed row's
  Uncertainty sentence, from the row's first cell, the computed and sampled caveats, "Converged means" and the tree's
  four notes. Where the error is drawn the ages are at the scenario epoch; where it is beside a computed miss they are
  at that closest approach, and the result's computed caveat gives the ages at the scenario epoch and says each is
  older by the time to the closest approach.
● **The operating envelope.** The deep-space and GEO flags say that the unvalidated or unsourced error model now sets
  every sample's draw, every computed band and the closest approach and score that read them, not only a set's age and
  its TCA's uncertainty. A record of 0.28.0 to 0.31.0 keeps the flags it showed.
● **Records of 0.28.0 to 0.31.0.** They are replayed under the rule they were evaluated by, as SPC-203 did for P:
  stored inputs version 4 adds the scenario's miss rule; versions 1 to 3 read as the rule before it, no element-set
  error, so the replay reproduces what the operator was shown, says so first, and the provenance hashes those records
  as they were. Version 4 holds the new rule alone. No other stored field was needed: each set's text, epoch and age
  were stored already. `tests/unit/_decision_records_0_31_0.json` holds two records 0.31.0 wrote, a sampled and
  computed matrix and a two-turn tree, and each replays exactly.
● **What moved.** Re-derived by evaluating each case under both rules, never pasted. The plane-change computed miss,
  10.40 km, now scores on 8.94 km, inside the 10 km keep-out, so its closest-approach term is the full penalty. The
  orbit raise burned 2 h before its window (convergence C7): P5 855.86 km known to within 11.34 km before, 854.86 km
  within 12.08 km now. The Evasive sampled row: 10.7 to 13.4 km before, 9.7 to 15.1 km now. Our burn sized to 20 km
  against the Evasive burn 0.25 h in: P5 9.45 km before and 19.94 km after, 16 of 100 samples under the target, before;
  7.27 km and 17.87 km, 52 of 100 under it, now, since the burn is sized on the nominal, not the band. The reference
  cases pass unchanged: each computed figure is still the SGP4 miss, and the series with one undispersed sample draws
  nothing.
● **Picks.** The rule can change a pick, and does where our burn is sized. Responses in a row need not share a band: a
  response whose burn is sized has its own miss, TCA and so error, and a fixed subtraction does not move every cell's
  logarithmic closest-approach term alike, nor keep a minimax pick. Checked by evaluating each under both rules: no
  matrix pick and no tree turn-1 pick changed in the 8 record fixtures (0.28.0, 0.29.0 and 0.31.0), nor in C7, the
  Evasive row, test 36 or coplanar_leo computed with Hold against Avoid sized to 20 km, nor the turn-1 picks and the
  path selected in two trees from `tests/unit/_decision_tree_cases.py` under expected value and minimax. One that
  changed, pinned in `tests/unit/test_decision_elset_error.py`: coplanar_leo computed, Hold against Avoid with our
  burn sized to 15 km, the closest-approach weight 0.7 and the other four 0.075 each. Before, every rule picked Avoid,
  0.694479 against Hold's 0.699953; now every rule picks Hold, 0.7 against Avoid's 0.704518. Hold's miss, 10.01 km, is
  just outside the 10 km keep-out and its lower edge inside it, where the term is already the full penalty, so Hold
  moves by under 0.0001. Avoid's burn puts the miss at 15.1 km and is scored at that less its own error, 1.74 km, so
  only Avoid's score rises. The same happens at a 12 km target with the weight at 0.9. A burn sized short of the error
  buys less than its target says; the caveat with a sized burn says so.
● **Claude's design choices, awaiting the owner's ruling:**
  ■ **Along track only.** The model is an along-track error, so no radial or cross-track part is drawn: any figure
    for one would be unsourced, and along track is where element-set error grows fastest. The results say what is
    still not in the band.
  ■ **A normal distribution, 1 sigma the model's figure.** The sweep uses the model as a shift both ways; the TCA's
    uncertainty reads it as 1 sigma, so the draw does too.
  ■ **The age at the scenario epoch, fixed for the span.** The draw is an initial-state error; within the span the
    moved orbit is flown as it is, so the error does not grow at the model's 2 km a day while the span runs, where a
    computed band read at the closest approach does.
  ■ **A time along the orbit.** Moving an object along its own orbit is reading its arc at another time, which keeps
    the cost of a series where it was; our burns on blue keep their time on blue's moved arc, so each is made at the
    same point of blue's orbit.
  ■ **The lower edge for the score of a computed cell.** It is never below 0 km. A crossing at high speed turns
    along-track error mostly into time, so the lower edge can overstate how much closer the pair comes; it errs
    towards the closer case.
  ■ **A 1-sigma edge beside a P5.** The brief sets the band as the miss less and plus the error; the computed cell
    scores on that, 1 sigma closer, while a sampled cell scores on P5, about 1.645 sigma closer where the error
    dominates its spread. Rows of one matrix can so be scored at different confidence levels: the same co-orbital pair
    20 km apart with red two days old scores 14.9 km computed and P5 11.3 km sampled. Both the line and the basis say
    the band is 1 sigma.
  ■ **A sampled TCA holds only the error's growth.** Every sample draws the error at the scenario epoch, so its ± is
    the growth from then to the TCA alone, rather than the whole error counted again.
  ■ **Replay under the rule evaluated by**, not under this code's rule with the difference reported.
  ■ **More samples may be needed.** A wider band converges more slowly, at about the same cost a series: 500 samples
    took 3.5 s with the draws and 3.2 s without at LEO, 2.9 s and 3.0 s at GEO, measured here. A co-orbital GEO pair
    15 km apart over 1 h, both sets 12 h old, 2.5 km each, converges at the default 500 samples, P5 8.42 km known to
    within 0.94 km against 1.00 km. Both 24 h old, 3 km each, well inside GEO's 72 h limit, it does not: P5 7.10 km
    known to within 1.13 km, so the row is refused as unconverged. At 1,000 samples it converges, P5 7.56 km within
    0.64 km. A LEO pair 15 km apart over 0.5 h converges at 500 samples with both sets 19 h old, 2.58 km each, within
    0.97 km, and not at 24 h, its limit, 3 km each, within 1.13 km. The panel takes up to 2,000 samples a row; the
    default stays 500.

## The page's script and the draft threat model (SPC-199)

**Status: the policy is built; the threat model is a draft for the owner's security lead to review and sign. Each
choice not named in the brief is Claude's design choice, not a ruling; they are listed at the end of this section.**
Evaluation finding F-08 (Critical, gate G9) found no engine threat model and a Content Security Policy that allowed
`'unsafe-inline'` and `'unsafe-eval'`, with the results page itself carrying 2 inline scripts. Gate G9 was rated Red;
that rating stands until the security lead has signed the model and the evaluation is repeated.

● **What the browser runs.** `script-src` is `'self'` alone. The Decision Engine panel's row builder, the results'
  trajectory opener and the histogram of sampled times of closest approach are in `spectre/web/static/js/decision.js`,
  with the rest of the console's script in the other files beside it. The rows Add Adversary Action and Add Friendly
  Response build are a `<template>` in the panel, the same markup the script string held, with each row's number
  written where `__ROW__` stands. The histogram's data stays in its `<script type="application/json">` blocks, which
  the browser never runs. An injected inline script, handler attribute or `hx-on` is refused by the browser.
  Injected markup is not: an element carrying `hx-get` or `hx-post` still sends a same-origin request with the CSRF
  token it inherits, so output escaping remains the control against it (T9 in the threat model).
● **What the operator sees.** Nothing changes: every control does what it did, and the browser tests in
  `tests/browser/` drive each one under the policy.
● **The draft threat model.** `docs/threat-model-decision-engine.md`, structured by the 7 ISN 2023/09 principles,
  covers poisoned element sets, tampered weights, priors and vetoes, the integrity and non-repudiation of records and
  stored inputs, the confidentiality of the friendly priorities they reveal, the UDL credential and injection in the
  browser, each with what exists, what remains and its owner. It is unsigned and does not close G9 by itself.
● **Claude's design choices, awaiting the owner's ruling.** Behaviour is reached through `data-action`,
  `data-init` and the other attributes `spectre/web/static/js/core.js` lists, resolved against its own registries
  and never against `window`. A fragment's start-up code runs on htmx's load event, once for each element. htmx runs
  with `allowEval` and `allowScriptTags` off. Inline style is still allowed.

## What remains out of scope

● **The composite weights are uncited** (SPC-151). Until an analyst sources them the score stays a lookup and the
  ranking a weighted heuristic. Since SPC-205 the results show how far one weight can move before the
  recommendation changes; swing-weight elicitation remains SPC-151.
● **A persistent-intent model for red** (D11): the owner ruled on 2026-11-05 to keep P as entered each turn.
● **Element-set error across track** is not drawn, and the along-track model is a rule of thumb, tuned, not sourced
  (SPC-202); sourced error rates per regime are SPC-215.
● **A sensor's line of sight to red is not modelled.** Custody is about information, not geometry, and our response
  is not applied to it.
● **Doctrine wording** (SPC-177): no probability or yardstick word appears. The owner ruled on 2026-11-05 that
  doctrine words stay off screen, and SPC-177 is closed.
● **The verdict switch** stays off: the owner ruled on 2026-11-05 to keep it off (concept section 9, decision 3).
● **Constraint libraries** (SPC-195): rules drawn from doctrine or rules of engagement that would mark responses not
  permitted without the operator ticking each are the owner's to supply; until then each veto is the operator's.
● **A game tree over a transfer of several burns.** The matrix carries every burn of the transfer (SPC-184), but
  the tree's equal turns cannot place them, so such a row refuses the tree. Unequal turns, set by the engine, are
  SPC-187.

## Summary

| Phase | What it gives the operator | Status |
|-------|----------------------------|--------|
| 1 | The matrix, its ranking and three selector rules; bound to real objects | Built |
| 2 | A sampled closest approach from a manoeuvre hypothesis, scored on P5 | Built |
| 3 | Computed closest approach and time, custody, our burns sized, trajectory and histogram | Built |
| 5 | A NOTSO suggestion for P and Conf, its interval, and its timeline | Built |
| 4 | A game tree of up to three turns, its picks, the update after turn 1, and its view | Built |
| SPC-195 | A response marked not permitted, shown with its reason and never picked | Built |
| SPC-200, SPC-201 | The operating envelope written down and checked, and one acceptance check for every element set | Built |
| SPC-203 | P summing to at most 1, the remainder weighed as no adversary action, each row's share shown | Built |
| SPC-204 | Collect first only for a collection that can change the recommended response; the action line described as what it is | Built |
| SPC-205 | The smallest change of one weight that changes the recommendation, beside it and on the record | Built |
| SPC-202 | Element-set error drawn in every sample, and a band beside every computed miss whose lower edge the score reads | Built |
| SPC-199 | The panel's and the results' script in first-party files under a policy with no inline script or eval; a draft threat model for the security lead | Built; threat model a draft |
