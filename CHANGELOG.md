# Changelog

All notable changes to SPECTRE will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.5.21] - 2026-10-21

What an adversarial review of the two previous releases found.

### Fixed

- **A single large manoeuvre read as MINIMAL risk.** The anomaly score needs
  two manoeuvres, so an object with exactly one fell through to the floor: a
  450.7 m/s AGGRESSIVE relocation reported minimal risk because it happened
  once. The worst observed posture is now a floor under the score, never a
  ceiling.

- **A whole campaign could collapse into one burn.** The duplicate merge
  compared each detection only to the previous cluster member, so clustering
  chained without limit. Ten distinct burns spaced nine-tenths of a window
  apart became a single event, which is the shape of a low-thrust electric
  campaign. Clusters are now bounded at both ends.

- **Four of six platform classes carried a lifetime total in a field named
  discretionary.** Table 2 publishes a discretionary figure for two of them.
  The panel was crediting a LEO smallsat with 2,500 m/s of reserve for
  manoeuvring against another object, when that total is mostly drag make-up,
  collision avoidance and deorbit. Where the figure stands in, the panel says so.

- **The intercept panel's ΔV budget label was 167× out.** The percentage moved
  to the realistic 500 m/s budget in 0.5.15; the template's hardcoded
  "% of 3.0 m/s" did not move with it. The denominator now travels with the
  percentage.

- **A fourth copy of the same Table 3 figure.** `maneuver.py` used an annual
  station-keeping budget as a per-event boundary, so everything from 1 m/s to a
  whole year's budget was labelled "Station-keeping scale" — a band that covers
  both Luch/Olymp-K relocations and a 180° repositioning.

### Notes

One review finding was reported backwards: that the epoch-swept estimator
under-reports a large burn. Measured against the exact two-burn Hohmann cost it
is accurate to 0.4% across the whole range, and the element decomposition is
the one that over-reports, by 10.9% at Δa/a = 0.145. The review was reading a
defect in this project's own test harness, which used the same first-order
relation as the element estimator and so agreed with it precisely where it was
wrong. The harness now computes the exact cost and the overshoot is pinned.

## [0.5.20] - 2026-10-21

The open-source delta-V assessment, assimilated. Pattern of Life now reads the
same cited figures the threat sweep has used since 0.5.15.

### Fixed

- **Four of the assessment's own named counterspace events classified as
  routine station-keeping.** `_SK_DV_LIMIT` applied Table 3's **annual**
  budgets as **per-event** limits; its GEO and HEO values matched the annual
  figures exactly. The GEO graveyard raise, both Luch/Olymp-K relocations and a
  180° repositioning all came back as station-keeping. The ceiling is now
  derived from the annual budget and the object's own observed cadence: 1.84
  m/s for a GEO burn at a fortnightly cycle, against the 50 m/s in force.

- **The propellant figure measured the wrong thing.** It reported the fraction
  of **total spacecraft mass** under a label naming the fraction of the
  **propellant load**. They differ by the propellant mass fraction, so a LEO
  smallsat reading 0.9% had in fact spent about 9.2% of its tank. It also
  applied 900 kg on a 3-tonne platform to every object in every regime, and
  computed remaining ΔV with a `prop + prop` denominator that returned a
  constant 1,495 m/s whatever the object.

- **The incapacity band could not fire.** The threat assessment grades an
  object unable to act at 95% propellant consumed, and that dominates every
  other capability signal. With the old estimator it fired on everything, so
  SATNO 62902 would have read as incapable while actively manoeuvring.
  Correcting the ΔV did not fix it: 95% of total mass needs 9.40 km/s against a
  practical ceiling of 2.5. Reading the tank instead needs 1.57 km/s for a LEO
  smallsat, which is inside Table 2's envelope. A discretionary-reserve signal
  was added alongside, because most of a comsat's remaining tank is committed
  to station-keeping and cannot be spent on manoeuvring against anyone.

- **The anomaly score ignored regime.** A full budget score was awarded at 200
  m/s/yr everywhere: 4 times routine in GEO, 8 in LEO, 200 in MEO. A navigation
  satellite burning twice its regime's entire annual budget scored one point
  out of a hundred.

- **A quiet object was reported as passive.** Collision avoidance is
  centimetres per second to about 1 m/s and Starlink flew 207,152 of them in
  six months, all of it below any element-set detection floor. The panel now
  states the measured floor, lists which named events sit above and below it,
  and says that a quiet result is evidence about what can be seen rather than
  about what the object is doing.

### Added

- **Posture on every manoeuvre**, from the cited per-regime, per-kind bands:
  BENIGN, ANNOYANCE, AGGRESSIVE or BEYOND PLATFORM, with the band's provenance
  and the reasoning shown in the drill-down.
- **Escalation at 500 m/s on station**, the assessment's second watchlist
  recommendation. The measured decomposition distinguishes a plane change from
  a tug, so the panel names which explanation the orbit change supports instead
  of listing all four.
- **How long the burn must have taken.** A 170 m/s relocation on an
  all-electric GEO bus is 21.9 days of continuous thrust, which rules out any
  scenario needing it at short notice. Uses the object's own assumed platform,
  not the fastest one that could afford it.
- **A reserve reset date**, so a refuelled object stops reading as
  progressively more exhausted as it becomes more capable. The earlier total is
  retained and shown separately. The transferred quantity is deliberately not
  modelled; the one reported figure is unconfirmed secondary reporting.
- **Graveyard disposal as a distinct classification.** Disposal and the start of
  a drift are identical in the elements; only the altitude it ends at separates
  them.

### Changed

- Classification, propellant, anomaly scoring and the operator narrative moved
  from `spectre/astro/pattern_of_life.py` to the new
  `spectre/domain/pol_assessment.py`. The astro package measures and stops
  there. This also puts the m/s interpretation on the correct side of the unit
  boundary, since astro works in km/s throughout.
- A mixed-channel manoeuvre is now scored against the proximity band rather
  than the permissive rendezvous one. Cosmos 2576's inspector campaign reads
  BENIGN against rendezvous and ANNOYANCE against proximity.
- `DEFAULT_SWEEP_BUDGET_M_S` stays at 500 m/s, deliberately. It is a sweep
  budget, not an alert threshold; lowering it would shrink the intercept set
  rather than tighten the watch floor. Three tests pin the figure and the
  reasoning so it is not changed later by someone matching on the number.

### Notes

SPECTRE reproduces eleven of the assessment's published worked values to within
rounding, having been built independently of them. Four are now pinned as tests.

## [0.5.19] - 2026-10-21

The Pattern of Life ΔV figures were measuring the gap between element sets, not
the manoeuvre between them. Every number downstream of them was wrong by up to
three orders of magnitude.

### Fixed

- **ΔV was estimated by differencing two propagated velocity vectors.** The
  before-element-set was propagated to the after-epoch and the velocities
  differenced. That measures how far two trajectories have drifted apart, which
  is dominated by along-track phase and carries no ΔV information at all.
  Measured on a 550 km orbit: two fits of the same orbit at the same epoch,
  differing only in mean anomaly by 0.1° (1.6 seconds of along-track timing),
  reported 13.3 m/s; at 30° of phase, 3,936 m/s. True ΔV is zero in both. The
  error compounded with the epoch gap, so a real 6.95 m/s burn read as 395 m/s
  across 0.2 days and 1,971 m/s across one day.

- **Natural node precession was partly read as a plane change.** Secular drift
  rates now come from SGP4's own initialised element set rather than the
  closed-form J2 relation, and are weighted by the measured burn instant
  because the orbit precesses at one rate before a burn and another after it.
  The mismatch had been putting 39 m/s of phantom plane change on a real 7 m/s
  burn across a 15-day gap.

- **One provider's fit was differenced against another's.** Each element set is
  now differenced only against the previous one from the same source.
  Differencing across providers measures the disagreement between two
  organisations' orbit determination, not a manoeuvre: on a catalogue with two
  providers 6.3 km apart in semi-major axis it put a standing 3.5 m/s on every
  provider switch and raised the detection floor from 2.8 to 9.1 m/s, burying
  every real station-keeping burn beneath it.

- **The detection threshold was a fixed 2 m/s.** It is now measured per object,
  from the median and median absolute deviation of every consecutive-pair ΔV in
  that object's own history. Both statistics are robust, so an object's own
  burns cannot inflate the threshold meant to find them.

- **The element set table rendered every record with its full element set
  text.** On a 3,676-set catalogue that was 7.3 MB of HTML into a 340 px scroll
  box. Capped to the newest 400, with the omission stated on the page rather
  than left silent. Measured: 7,321,947 characters before, 905,528 after.

### Added

- **A drill-down behind every ΔV figure.** Both element sets side by side with
  their provenance and fit residuals, all three estimators with their readings,
  every channel with the numbers that produced it and the relation applied, the
  measured detection floor, the dated burn instant, and why the result was or
  was not believed. Mean anomaly is shown and explicitly marked "not used",
  because it is the variable that caused the original defect.

- **Two estimators, neither of which can read phase as ΔV.** The headline is
  epoch-swept propagation: velocity differencing is exact at the instant of the
  burn and only then, so the gap is searched for the epoch at which the two
  trajectories actually coincide. Measured against synthetic burns of known
  magnitude, it is accurate to better than 0.2% at every gap from 0.2 to 15
  days. The second is mean element differencing, which decomposes the figure
  per variable and never reads mean anomaly.

- **Confirmed and candidate tiers.** A detection is confirmed only where both
  estimators agree within 1.5×, it stands ten times above the object's own
  measured fit scatter, and nothing about the element sets' provenance objects.
  Only confirmed events feed the cumulative ΔV, the propellant budget and the
  anomaly score. Candidates are kept, shown and labelled with the reason they
  did not qualify.

- **A detection provenance block.** How many element set pairs were examined,
  the measured floor and the statistics behind it, and how many pairs were
  discarded, for what reason.

### Changed

- `PolAnalysis.manoeuvres` now holds confirmed detections only; the rest are in
  `PolAnalysis.candidate_manoeuvres`. Everything derived from manoeuvres, the
  propellant budget included, follows the confirmed list.
- Manoeuvre classification keys on which measured channel carries the ΔV rather
  than on scaled element deltas with weights that had no physical basis.
- The maximum epoch gap for a detectable manoeuvre rose from 15 to 30 days, now
  that the estimator no longer degrades with the gap.

### Notes

The new figures under-report: across four simulated catalogues the cumulative
ΔV came out at 0.69 to 0.91 of known truth, because burns below the measured
floor genuinely cannot be told apart from the disagreement between successive
fits. The old estimator over-reported by 5,581× on the same data.
Under-claiming expended propellant is recoverable; over-claiming it by three
orders of magnitude into a capability assessment is not.

## [0.5.18] - 2026-10-16

The HRR watchlist, delivered. The threat sweep and the asset screen both run
on a fresh instance with no UDL connection.

### Fixed

- **An unanchored `data/` in `.gitignore`.** Gitignore matches at any depth, so
  the rule meant for the runtime data volume silently swallowed
  `spectre/data/` as well. The package data already there survives only
  because it predates the rule; anything added since has been ignored without
  a word. That is why the watchlist kept going missing, and nothing ever
  errored to say so. Now anchored to `/data/`, with a guard that probes a new
  file under `spectre/data/` and fails if it is ignored.

- **The asset and target selectors refused to render without a UDL session.**
  Both opened with `{% if not has_udl %}`, which hid a perfectly usable
  watchlist behind a login it does not need. The gate is now "do we have
  objects". Measured: 0 assets listed before, 18 after.

- **A UDL fetch would never have replaced a bundled element set.** All three
  fetch sites skipped anything already cached, so connecting to UDL would have
  changed nothing and an operator would have kept reading generated orbits
  believing they were tracked.

### Added

- **A bundled bootstrap watchlist** at `spectre/data/hrr_default.json`, last
  in the candidate path so an operator-supplied file always wins. 38 objects:
  18 blue assets and 20 red candidates, every red one joining to an existing
  assessment in `adversary_intel.json` so the intelligence join is genuinely
  exercised.

  The operator's own `HRR_List.json` stays gitignored and dockerignored, as it
  should: it is operational data and belongs on the data volume.

- **Optional element sets in the HRR parser.** An object list alone populates
  a dropdown that then refuses to run, because both capabilities need an orbit
  per object. A real JCO notification carries no element sets, so the live
  path is unchanged.

- **`scripts/build-hrr-default.py`**, so the bundled list is reproducible
  rather than a blob. It derives each object's regime label by reading it back
  out of the element set it generated, so the label and the orbit cannot
  disagree.

### The element sets are synthetic, and say so everywhere

Catalogue numbers and names are real and public. The orbits are generated to
be physically consistent at a stated epoch, not observed. They are tagged
`SYNTHETIC`, the startup log says so at WARNING, the asset selector carries a
banner, and a UDL fetch replaces them. Four tests assert each of those.

### Known limits

- **The sweep's red interceptor dropdown still needs UDL or a pasted TLE.** It
  reads operator-added Red Tracks, not HRR objects. The sweep's target side
  now works from the bundled list; its interceptor side is unchanged.
- **The classifier calls a Molniya orbit GTO.** It keys on eccentricity above
  0.5 with a low perigee and does not separate a transfer orbit from an
  operational highly elliptical one. Both are trans-belt for compatibility so
  nothing is filtered wrongly, but the label reads oddly. Recorded, not fixed.

## [0.5.17] - 2026-10-15

Blue asset screening. The sweep asks what one object can reach; screening asks
who threatens one asset, which is the question an analyst actually holds.

### Added

- **Asset Screening**, a new console tab. Select a blue HRR object and every
  red object in a regime that could physically reach it is screened, assessed
  and ranked. Three clicks: the tab, the asset, Screen Asset.

  This is the first time the composite verdict from 0.5.14 does any
  discriminating work. In the red-out sweep capability is one constant across
  every entry, because there is one red object. Here it varies per actor and it
  is the field that separates the two objects worth briefing from the eighteen
  that are not.

- **Two headline answers, and the disagreement between them.** The most
  dangerous actor is ranked on composite verdict with warning time as the
  tie-break. The earliest possible arrival is named separately. When they are
  different objects the panel says so in words:

  > These disagree. TJS-3 is assessed CRITICAL and would arrive in 6.2 h, but
  > COSMOS 2535 could be here in 0.7 h and is assessed MINIMAL. If that
  > assessment is wrong, your warning time is 0.7 h, not 6.2 h.

  Ranking on verdict alone would bury the fast approach. Ranking on warning
  time alone would put a derelict on top and undo the verdict entirely.

- **Expandable per-actor profiles.** Each ranked row opens to the epochs and
  methods behind its verdict, soonest first, so the headline can be
  interrogated rather than taken on trust.

- **A manual asset TLE override**, for an asset whose element set is not
  cached. It is also what lets the browser probe drive screening end to end,
  which it cannot do for the sweep.

### Measured, not assumed

Per the plan, cost was measured before any feature code was written: **53.8 ms
per candidate actor**, of which 81 per cent is the 24-hour orbital event scan.
10 actors 0.54 s, 25 actors 1.35 s, 50 actors 2.69 s.

The gate was to build a feasibility pre-screen if 25 actors exceeded about four
seconds. It does not, so **no pre-screen was built**. An optimisation with
nothing to optimise is a place for a defect to hide. Candidates are capped at
60 and truncation is always reported.

### Every empty answer carries a reason

No watchlist, no compatible red object, no transfer inside the budget, and an
asset with no cached element set each produce a different sentence naming what
was checked. The no-candidates panel states how many red objects were screened
and excluded, because "nothing listed" and "nothing can reach you" must not
look the same.

### Changed

- **`_compute_intercept_intel` reduced further**, from 96 statements to 31
  branches, by extracting the method-insight and summary blocks; the twenty-way
  method chain is now a dispatch table. The 47 characterisation tests written
  in 0.5.16 passed unchanged at every step. That suite is the only reason a
  refactor of this size was safe to make alongside a feature.
- **One score band** shared by the detectability, stability and terrain panels,
  which each carried their own copy of the same two thresholds.

## [0.5.16] - 2026-10-13

Closes the double-conversion trap recorded as a known limit in 0.5.15. No
template anywhere in the application performs unit arithmetic.

### Fixed

- **The pattern-of-life conversion trap.** Four templates scaled km/s to m/s
  inline in eighteen places: `pol_results.html` twelve, `intercept_geometry.html`
  three, `notso_results.html` two, `pol_mc_results.html` one. Every one was
  correct. Together they were a trap, because the route layer converts at its
  own boundary: the first person to finish the job by converting
  `PatternOfLifeResult` at the boundary would have left the template scaling an
  already-converted value, putting the charts at 1,000,000x and the table at
  1,000x in the same panel, both rendering without error.

  All eighteen now happen in Python, at a named route boundary, through one
  `to_m_s` helper.

### Added

- **The invariant, enforced.** A template may not scale by a thousand, and the
  four velocity panels may not read a km/s field at all, so a future boundary
  conversion cannot reach them. Three routes to the failure were each watched
  failing: a template that scales, a conversion running twice in Python
  (caught by value, "482000.0, expected 482.0"), and a template going back to
  reading a km/s field.

- **A context contract for every converted figure.** Moving twelve conversions
  out of a template means the route must now supply twelve names, and Jinja's
  default undefined is falsy and silent, so a typo renders a blank panel and
  nothing raises. A test parses each panel for the names it reads and asserts
  the route passes every one. This is the 0.5.14 lesson applied before it bit.

- **47 characterisation tests** for `_compute_intercept_intel`, written before
  touching it, pinning its output across every intercept method, every delta-v
  band, the flight-time labels and the per-burn breakdown.

### Changed

- **`_compute_intercept_intel` split into four pure helpers.** It was 163
  statements across 56 branches at roughly half coverage, past the point where
  a reader can hold it or a reviewer can check it. The same 47 characterisation
  tests pass before and after.

- **One flight-time label, shared.** The threat sweep and the intercept panel
  each carried an identical if/elif chain. Two copies of a format is two places
  to drift, and an operator comparing the two screens would see the same
  duration written two ways with no way to tell which to trust.

- **Dead code removed.** The Monte Carlo route accepted a `dv_km_s` form
  parameter it never read, and the template posted it. Both gone.

### Unchanged, confirmed

- The orbital state vector panel stays in km/s, and the astro package keeps
  km/s internally. Both remain the guard's documented exceptions, each with a
  test that fails if the exception stops applying.

## [0.5.15] - 2026-10-13

Everything the operator reads is now metres per second, and a delta-v figure is
no longer shown bare: it is read against what satellites actually do.

Calibrated from "Satellite Manoeuvre Delta-v: Feasibility Above 0.5 km/s and
Budgets by Regime" (Bluestaq Limited Space Watch, v1.0, 13 October 2026).

### Added

- **A manoeuvre calibration** (`spectre/domain/manoeuvre_calibration.py`).
  Three postures, per manoeuvre kind, per orbital regime, every boundary
  traceable to a named table or observed case:

  ● **BENIGN** - efficient, minimum energy, long timeline. Indistinguishable
    from routine operations.
  ● **ANNOYANCE** - deliberate and noticed, but affordable and repeatable.
    Shadowing, inspection, moderate repositioning.
  ● **AGGRESSIVE** - short timeline, high energy, chosen for effect rather than
    economy. Usually a meaningful fraction of the platform's remaining life.
  ● **BEYOND PLATFORM** - past the reserve of every flown class, so it implies
    a tug, an orbital transfer vehicle, a kick stage or refuelling.

  The nine documented cases land where an analyst would put them: Luch/Olymp-K
  2's 62 degree relocation for 11 m/s is BENIGN, the SJ-21 tow of Beidou-2 G2
  at 60 m/s is ANNOYANCE, its 120 m/s round trip and the 170 m/s rapid
  repositioning are AGGRESSIVE.

- **A burn-rate feasibility check.** Reserve is not the ability to spend it in
  time. An all-electric GEO bus holds up to 1,500 m/s but thrusts at about
  0.27 N, so it needs about 64 days to deliver 500 m/s. A transfer whose time
  of flight is shorter than the fastest possible delivery is now flagged NOT
  FLYABLE with the class and the hours named.

  This matters because the sweep ranks on warning time, so it actively
  preferred short flight times, which is exactly where the impulsive
  approximation breaks. Measured: 450 m/s arriving in 36 minutes was scored
  CRITICAL and cannot be flown by anything in orbit.

- **A guard that no operator-facing figure is in km/s**
  (`tests/unit/test_operator_sees_metres_per_second.py`). Sixteen cases
  covering templates, routes, the domain layer, the training scenarios and the
  operator guide, with one documented allow-list entry and a test that fails if
  that entry stops applying.

### Changed

- **The access band is posture, not four global numbers.** The thresholds were
  200, 500 and 1,000 m/s, and every counterspace manoeuvre on open record sits
  below the lowest of them, so the band returned CRITICAL for a routine
  commercial repositioning and for a hostile closure alike. It is also keyed on
  regime now, because 50 m/s is one routine year at GEO and fifty years of it
  at MEO.

- **The default budget is 500 m/s, not 3,000.** 3,000 m/s exceeded the
  discretionary reserve of every flown platform class, so the sweep accepted
  intercepts nothing could fly. 500 m/s is the assessment's own anomaly
  threshold and sits above every manoeuvre on record.

- **Sweep groups rank on warning time**, matching the headline above them. They
  ranked on cost while the banner ranked on time, so the two disagreed about
  which target mattered most on the same screen.

- **The `evasive` Monte Carlo archetype was 30 m/s**, which matches no
  published figure; a collision avoidance manoeuvre is centimetres per second
  to about 1 m/s. Now 2 m/s. The other six archetypes already matched and now
  cite their source.

### Fixed

- **MIN_TIME took its delta-v budget from the target distance.** An operator
  asking for a 500 m standoff set the solver's budget to 0.5 km/s. Second site
  of the defect recorded in 0.5.13 for `intercept_envelope_intercept`.

- **The Hill-frame burn vector round trip.** The intercept panel posts its burn
  components into the relative-geometry route, which clamped at +/-20 and
  handed them to the Clohessy-Wiltshire propagator as km/s. Once the panel
  emitted m/s a real burn either failed the clamp or arrived a thousand times
  too large.

- **Four display sites that were silently wrong after the rename:** the budget
  bar divided by a hardcoded 3.0 and captioned itself "% of 3 km/s"; the sweep
  row colouring banded at 0.5 and 1.0, shading every row above 1 m/s
  identically; the intercept panel banded CRITICAL at 2.0; and the trade-space
  chart labelled its axis km/s while plotting m/s.

- **A defect introduced during this change and caught before it shipped.** A
  blanket relabel changed three Hill-frame velocities from km/s to m/s without
  scaling them, printing a number a thousand times too small. The string-based
  guard went green precisely because the relabel removed the string it looks
  for. A second guard now pairs known km/s attributes with their labels and
  requires a scaling.

### Known limits

- **The orbital state vector panel stays in km/s**, deliberately. Orbital speed
  is about 7.6 km/s in LEO and 3.07 km/s at GEO, and the source assessment
  writes orbital speed in km/s and manoeuvre cost in m/s throughout.
- **The posture bands describe an object already on station.** They do not
  describe commissioning: electric orbit raising from geostationary transfer
  orbit costs 1,500-2,500 m/s and is entirely routine.
- **`pol_results.html` converts in twelve places inside the template** while
  `pol.py` converts at the route boundary. Both are correct today, but
  finishing the conversion at the boundary would put the chart at 1,000,000x
  and the table at 1,000x in the same panel. Recorded, not fixed.

## [0.5.14] - 2026-09-13

Phase 1 of the roadmap: the sweep's verdict now consults the evidence the
application already holds about the adversary, instead of measuring only the
geometry and calling the result a capability assessment.

### Added

- **A composite threat verdict** (`spectre/domain/threat_assessment.py`). Pure
  functions over plain data, no I/O. Geometric **access** and assessed
  **capability** are answered separately and combined with the weaker side
  governing, because a threat needs both a permissive geometry and an object
  able to exploit it.

  The contradiction this removes was visible on screen. Kowsar and Kowsar-1.5
  ship in `adversary_intel.json` assessed `LOW` / `Degraded`, and a degraded
  satellite in a nearby orbit still has a cheap geometric path, so the sweep
  scored them `CRITICAL` while the intelligence panel beside it said the
  opposite. Same inputs now return verdict `MINIMAL`, access `CRITICAL`,
  capability `MINIMAL`, all three shown.

  An object with **no** capability record is not scored as incapable. The
  verdict falls back to geometry with `LOW` confidence and says in words that
  it may overstate the threat, because the alternative is quietly under-
  reporting every object nobody has assessed yet.

- **A guard that renders the real template** (`tests/unit/test_threat_sweep_template.py`).
  Eight cases under `StrictUndefined`, with the `worst_coa` fixture built by
  calling the real `_compute_worst_coa` so it cannot drift from the route.

  It immediately found a defect in this release: the new refusals panel was
  bound to `assessment.method_refusals` while the route passes
  `method_refusals` at the top level. Jinja's default undefined is falsy and
  silent, so the panel never rendered, the page returned 200, the browser probe
  passed, and all 956 existing tests stayed green. Watched to fail against the
  original binding and to pass against the fix.

### Changed

- **Ranking is on warning time, not cost.** `entries.sort` and the most
  dangerous course of action now use `warning_time_rank`, which sorts on time
  to arrival among intercepts inside the delta-V budget. Delta-V keeps the role
  it already had as the feasibility filter. Previously a 0.05 km/s intercept
  arriving in three hours outranked a 0.40 km/s intercept arriving in thirty
  minutes and was called the greater threat; warning time is what a defender
  actually spends.

- **Refused methods are recorded and shown.** The eight
  `except Exception: pass` blocks now capture the solver's own message, and the
  interface lists them. Refusals are not evenly distributed: a degenerate
  Lambert geometry is the near-180-degree GEO phasing case and an unflyable
  phasing orbit is the short-notice one, so dropping them silently biased the
  sweep towards under-reporting the fastest approaches. It is also how the
  Lambert defect fixed in 0.5.11 survived as long as it did.

- **Delta-V is reported to three decimals, not four.** Measured against TLE
  uncertainty, a co-orbital GEO intercept over six hours is good to about
  1 m/s at a realistic few-kilometre position error. The fourth decimal was
  0.1 m/s of noise presented as precision.

- **The browser probe reaches the sweep panel** and states plainly when it
  cannot drive the sweep end to end, which it cannot without UDL credentials.
  A step that silently does nothing is the failure the probe exists to catch.

- `T_phase` and `T_target` in `astro/tactical.py` renamed to `period_phase` and
  `period_target`, clearing the last naming finding on changed lines.

### Known limits

- **Behavioural capability is not yet connected.** Propellant budget, anomaly
  score and observed manoeuvre count need an element-set history; the sweep
  holds one current TLE per object. Those fields stay unset and the interface
  reports "3 input(s) unavailable" rather than assuming either way.
- **`_sweep_intents` is unchanged.** Roadmap item 3, replacing the static
  solver-name-to-prose dictionary with the manoeuvre classifier, needs the same
  absent history. The verdict *rationale* is now written from real evidence;
  the intent label is not.

## [0.5.13] - 2026-09-12

`tactical.py` audited, 2,129 lines. Three defects fixed: the NMC establishing
burn in `nmc_safety_ellipse` (a safety function certifying a trajectory whose
flown closest approach was zero for a reported 5 km margin), the `phasing_orbit`
closure condition (non-integer revolution count, 5,615 km semi-major axis error
at 180 degrees), and `intercept_envelope_intercept`, which discarded the state
vectors it held for a phase-blind estimate measuring 1.3x to 121x optimistic.
Full detail in `docs/CHANGE-LEDGER.md` and `docs/ORBITAL-CALCULATION-AUDIT.md`.

## [0.5.12] - 2026-09-12

Second half of the orbital calculation audit. Twelve double conversions of
angles already in degrees removed from `maneuvers.py`: a 0.5 degree plane
change at GEO costs 27 m/s and was reported as 1,521 m/s. `state_to_keplerian`
now substitutes the defined element where a classical element is degenerate;
the circular equatorial round trip moved 78,460 km and now returns the same
state.

## [0.5.11] - 2026-09-11

**Critical.** The Lambert solver computed `sqrt(y/mu)` where Curtis algorithm
5.2 requires `sqrt(y/C(z))`. Error against the published worked example was
1,970 m/s; a round trip missed by 6,268 km. Replaced with the correct residual
and a bracketed bisection, and the degeneracy guard rekeyed on transfer angle
rather than on a quantity that stayed at 3.7e-12 at exactly 180 degrees. Every
Lambert-derived delta-V produced before this release was wrong.

## [0.5.10] - 2026-09-10

No application behaviour changes. First batch of the approved improvement plan.

### Added

- **A browser smoke probe** (`scripts/smoke-browser.py`). Boots a throwaway
  instance on a free port against a temporary database, then drives login,
  admin create and delete, the training exit and sign out, failing on any
  uncaught exception, any HTMX swap error, and any same-origin console error.
  External network failures are classified and ignored, and the count is
  reported so the allowance cannot hide a real fault.

  Watched to fail and to pass. With the 0.5.9 fixes reverted it exits 1 naming
  `[admin-create] uncaught exception: e.querySelectorAll is not a function` and
  `[training-leave] leaving training mode was rejected by the CSRF guard`. With
  them restored it exits 0. Both of those defects returned HTTP 200 and were
  invisible to all 850 server-side tests.

  It does not skip itself when its browser is missing; it fails and says why. A
  probe that quietly does nothing is how the defects it exists to catch reached
  production in the first place. `SMOKE_BROWSER_SKIP=1` skips it deliberately.

- **A test harness for the packaging gates**
  (`tests/integration/test_packager_gates.py`). Eleven cases that copy the
  tracked working tree, break exactly one thing, run the real packager and
  assert it refuses with the message naming the problem. The script previously
  had no test at all, despite its five fail-closed branches deciding whether an
  artefact ships.

- **Two new packaging gates, each with a committed red case.** A gate may not
  read a file git does not track, because `docs/` is gitignored and the change
  ledger lives there, so that gate ran on one machine only. And
  non-application material may not reach the archive, because the platform
  ignores `sonar.sources` and grades every file in it as application code.

### Changed

- **Coverage reporting now tells the truth.** `fail_under` was 70 against a
  house standard of 80 while actual coverage was 74.3, so the loop reported
  green from underneath its own bar. The floor is now a ratchet at 74 so
  coverage cannot slip, and `scripts/check-quality.sh` prints the measured
  figure, the floor and the standard on every run, naming the 5.7-point gap.
  **The gap is open and nothing here closes it.**

- `playwright` added to `requirements-dev.txt` with its reason recorded in
  `requirements-dev.in`. Dev-only: neither the image nor the platform Test
  stage installs it, and the scanned and runtime locks are unchanged.

### Known cost

- The packager harness runs the real script eleven times, so the full suite is
  materially slower than it was. That is the price of covering the code that
  decides what ships.

## [0.5.9] - 2026-09-01

### Fixed

- **The user management table never updated after a change.** Creating a user
  appeared to do nothing: the row did not appear and the form did not clear, so
  it looked as though the account had not been created. It had been. The POST
  returned 200 with the new row and the flash message in the body, and the
  failure was entirely client-side:

  ```
  htmx:swapError
  TypeError: e.querySelectorAll is not a function
  ```

  htmx 1.9.12 chooses its parsing path from the first tag of a response. A
  response beginning with `<tr>` is wrapped in `<table><tbody>` before parsing,
  and the HTML parser then foster-parents the trailing out-of-band flash
  `<div>` out of the table. htmx handed a non-element to its out-of-band code,
  which threw and abandoned the entire swap.

  Reproduced in Chromium against a running instance. Measured blast radius:
  create, save-edit and delete all failed; opening and cancelling an edit were
  clean, because those responses carry no flash. The rule was exact - every
  admin response carrying a flash was broken, every one without it worked.

  Fixed by rooting those responses at the whole table region rather than a bare
  run of rows, so the flash stays a legal sibling and the table parsing path is
  never entered. All three paths now swap live with zero console errors.

- **Two plain POST forms submitted without a CSRF token**, and were rejected
  with `{"detail":"CSRF validation failed."}`:

  ● The sidebar **Return to Operations** button in training mode, which
    stranded operators inside the training system. The nav-bar copy of the same
    button did carry the field, which is why it survived review.
  ● **Sign Out** on the user management page, which had not been reported yet
    and was found by auditing every template.

  HTMX requests take the token from `hx-headers` on `<body>`; a plain
  `<form method="post">` does not, so it must carry the hidden field. Both now
  submit cleanly. `/login` is the only remaining plain POST form without one,
  and it is exempt by design.

### Added

- A template-wide guard asserting every plain POST form carries a
  `csrf_token` field unless its action is exempt. Verified in both directions:
  removing the field again fails the test naming the exact file and line.
- Response-shape tests asserting no mutating admin endpoint returns a
  table-scoped root element while carrying a flash. Asserted on the wire, not
  in the template, because the defect is a property of the bytes htmx receives.

## [0.5.8] - 2026-08-28

### Fixed

- **Container Build failed on the `COPY` added in 0.5.7.** `.dockerignore`
  excluded `tle_clustering/` under "Tests, docs and development tooling never
  ship in the runtime image", so the path was filtered out of the build context
  and the `COPY` had nothing to match:

  ```
  Error: building at STEP "COPY tle_clustering/ /app/tle_clustering/":
  no items matching glob ".../spectre/tle_clustering" copied
  (1 filtered out using .../.dockerignore): no such file or directory
  ```

  That exclusion is the true root cause of the clustering defect, one layer
  below where 0.5.7 placed it. The package was not simply missing a `COPY`; it
  was being stripped from the build context, and the absent `COPY` made the
  stripping invisible. Classifying it as tooling was wrong, because the
  application imports it.

  `TestBuildContextContract` now reads both Dockerfiles and asserts that no
  local `COPY` source is excluded by `.dockerignore` or missing from the
  repository. Verified in both directions: restoring the exclusion fails the
  test naming both Dockerfiles, removing it passes.

  Container Scan was skipped and Deploy never ran, so 0.5.6 remained the
  deployed version throughout.

### Changed

- **Test and Code Quality are template-gated. The question is settled.** 0.5.7
  shipped `tests/`, `sonar-project.properties`, `pytest.ini`, `.coveragerc` and
  a real `coverage.xml` to find out whether those stages were absent by
  template or merely starved of input. Neither ran. Dockerfile Lint passed in
  the same pipeline, and both stages precede it on the python template, so they
  were not pending. Code Quality is decisive: it needs no dependency install
  and had every input it reads.

  The four gates docker-only gives up therefore cannot be bought back by
  shipping their inputs. Only restoring a manifest brings them back, and that
  brings Dependency Scanning with it.

- Those five files no longer ship, and the packager machinery that generated
  and validated them is removed. No stage reads them under this template.

## [0.5.7] - 2026-08-28

### Fixed

- **TLE clustering has been silently disabled in every deployed build.**
  `spectre/astro/tle_preprocessing.py:150` imports `tle_clustering` inside a
  `try/except ImportError` that logs a warning and returns an empty result.
  Neither `Dockerfile` nor `Dockerfile.docker-only` ever carried a `COPY` for
  the package, so the import has always failed inside the container and the
  clustering step has always been skipped. Nothing failed, because the guard is
  correct: the feature degrades rather than crashing. That is precisely why no
  pipeline stage could catch it.

  Both Dockerfiles now copy the package, and the docker-only packager no longer
  drops it. Three tests pin it, one of which performs the application's own
  import rather than checking that files exist.

### Changed

- **The docker-only archive now drops only the recognised manifests.**
  `pyproject.toml`, `requirements.txt` and `requirements.in` are the three
  filenames the analyser selects on; those still go. `tests/`,
  `tle_clustering/` and `sonar-project.properties` were dropped in 0.5.6 on the
  assumption that docker-only runs no Test or Code Quality stage. The 0.5.6
  pipeline did show six stages rather than nine, but we shipped neither the
  suite nor the Sonar config, so that observation cannot distinguish a stage
  that does not exist from a stage with no input. Shipping them distinguishes
  the two and costs nothing if the stages stay absent.

- **`pytest.ini` and `.coveragerc` are generated into the docker-only archive.**
  pytest and coverage read their configuration from `pyproject.toml`, which
  cannot ship. Without it the suite loses `asyncio_mode = "auto"` and every
  async test errors on collection. Both files are derived from
  `pyproject.toml` at package time rather than copied, so the shipped
  configuration cannot drift from the one the repository tests under.

- **The packager runs the suite against the staged docker-only tree before
  zipping**, and ships the `coverage.xml` that run produces.
  `sonar-project.properties` points at that report, and the platform's Test
  stage generates it on the python template. A docker-only archive has no Test
  stage, so a Code Quality stage that did run would read a missing file and
  score zero coverage, failing on an absence rather than on the code. The
  report is generated from the exact tree being zipped, in the same build; the
  packager fails if the suite does not pass or the report is not produced.

- **Contract tests detect which template they are running in.** Assertions
  about `requirements.txt` and `pyproject.toml` skip inside the docker-only
  archive, detected from both manifests being absent rather than one, so a
  python package that lost a manifest to a packaging bug still fails instead of
  skipping. `TestDockerOnlyContract` asserts the inverse property there, so the
  skip leaves no gap.

- The Sonar project version is stamped into the staged copy at package time. It
  had been left at `0.4.0`.

## [0.5.6] - 2026-08-28

### Changed

- **Submitted as the docker-only template rather than python.** Twelve
  submissions have failed the Dependency Scanning stage with an identical
  signature: two INFO lines, `exit status 1` in under ten seconds, no
  CycloneDX SBOM, no report and no error text. Eliminated across those
  submissions: vulnerable packages (`gemnasium-db` matched offline, 97
  packages, 148 advisories, zero affected), vendored JavaScript, stray
  subdirectory manifests, lockfile header form, analyser Python version,
  `pyproject.toml` presence, manifest count at the package root (0.5.4 was
  file-for-file identical to an application that clears the gate), network
  access, and a package that no standard Python tool could build (0.5.5).

  The docker-only archive ships no recognised Python manifest at any depth,
  so the analyser has nothing to select. `requirements-runtime.txt` stays for
  the image build and is installed under `--require-hashes`; it is not a
  filename the analyser reads.

  The trade is deliberate and recorded: no `tests/`, no
  `sonar-project.properties` and no `requirements.txt` ship, so the Test and
  Code Quality stages have nothing to run against. Both passed on 0.5.4 and
  0.5.5.

### Result

- **Accepted and deployed.** All stages passed and the app is Active. The
  pipeline ran six stages, not nine: Secret Detection, SAST Scan, Dockerfile
  Lint, Container Build, Container Scan, Deploy. Dependencies, Dependency
  Scanning, Test and Code Quality did not run, which establishes that template
  selection follows manifest detection inside the archive rather than any
  setting above it.

  Four platform gates are therefore no longer exercising this submission. The
  equivalent local checks are `scripts/check-quality.sh` for tests and the six
  quality-gate conditions, and `scripts/audit-dependencies.sh` for `pip-audit`,
  the CycloneDX SBOM and the offline `gemnasium-db` match. They run, but they
  are ours rather than the platform's.

### Unchanged

- The application itself. The docker-only image carries the same `spectre/`
  tree, the same hash-locked runtime lock and the same connection-pool
  resilience fix from 0.5.3 as the python-template build. The python template
  remains buildable from this repository with
  `scripts/package-appstore.sh` for the day the gate is understood.

## [0.5.5] - 2026-08-28

### Fixed

- **The package could not be built by any standard Python tool.**
  `pyproject.toml` declared `[project]` but no `[build-system]`, so PEP 517
  fell back to setuptools, whose flat-layout auto-discovery refuses a project
  with more than one importable top-level directory:

  ```
  error: Multiple top-level packages discovered in a flat-layout:
         ['spectre', 'tle_clustering']
  ```

  It fails in seconds, with the message on stderr. Reproduced with
  `pip install --dry-run --no-deps .` against the package root, and it returns
  the moment the fix is reverted.

  `[build-system]` now names setuptools explicitly and
  `[tool.setuptools.packages.find]` declares the two packages, excluding
  `tests`. Metadata builds cleanly and `pip-compile pyproject.toml` resolves
  with zero errors.

  Whether the App Store analyser calls that build hook is inference, not proof.
  It matches the failure signature exactly and is consistent with PSIRENS
  passing, since a single package under `src/` auto-discovers unambiguously.
  Either way a package no standard tool can build is a defect worth fixing.

### Added

- **`TestBuildBackendContract`.** Asserts the backend is declared rather than
  defaulted, and that packages are declared explicitly whenever more than one
  top-level package exists. Verified by removing the declaration and watching
  two tests fail.

## [0.5.4] - 2026-08-28

The package root is now identical, file for file, to PSIRENS, an application
that clears this gate. First change to Dependency Scanning in ten submissions
with evidence behind it.

### Fixed

- **`requirements.in` and `requirements-runtime.in` no longer ship.**
  `requirements.in` is a recognised Python manifest. Shipping it gave the
  analyser three recognised manifests at the root, against PSIRENS's two, and
  left a single lockfile paired with two candidate requirements sources. The
  `.in` files stay in the repository, because `scripts/lock.sh` compiles from
  them; they simply do not travel in the archive.

### Changed

- **The root is trimmed to the seven files PSIRENS ships**: `Dockerfile`,
  `.dockerignore`, `pyproject.toml`, `requirements.txt`,
  `requirements-runtime.txt`, `sonar-project.properties` and `README.md`. Gone
  are `CHANGELOG.md`, `SECURITY.md`, `READINESS.md`, `CODEOWNERS`,
  `.env.example`, `.gitignore` and `.pre-commit-config.yaml`. Every file in the
  archive is analysed by Code Quality as application code, which already cost
  five findings in 0.5.1.
- **pytest and coverage configuration moved back into `pyproject.toml`**, so
  `pytest.ini` and `.coveragerc` leave the root as well. Verified with the
  platform's own command: 846 passed, coverage 74.36%, `coverage.xml` written.

### Not changed

- **The `src/` layout and the second top-level package.** PSIRENS keeps its
  application under `src/psirens/`; we have `spectre/` and `tle_clustering/` at
  the root. Neither is a recognised manifest location, so neither can change
  which files the analyser reads. If 0.5.4 fails, that is the next diff to run,
  and the ledger records it as the remaining structural difference.

## [0.5.3] - 2026-08-28

### Fixed

- **Login crashed on the deployed app with `connection is closed`.** The async
  engine was created with no pool arguments, so a PostgreSQL backend closed
  server-side, by an idle timeout, a proxy or a failover, stayed in SQLAlchemy's
  pool and was handed to the next caller. The first statement then failed with
  `asyncpg...InterfaceError: connection is closed`. Login is a low-traffic path,
  which is why it surfaced there.

  The engine now sets `pool_pre_ping`, so SQLAlchemy tests a connection on
  checkout and transparently replaces a dead one, and `pool_recycle` (300s,
  `SPECTRE_DB_POOL_RECYCLE`) to discard connections before an intermediary is
  likely to. PostgreSQL also gets bounded sizing: pool 5, overflow 10, a 30
  second checkout timeout so an exhausted pool fails the request rather than
  hanging the worker. SQLite is deliberately given neither, since sizing is a
  queue-pool concept for a networked server.

  Reproduced and verified against a real PostgreSQL 16: the backend is
  terminated server-side, then the app's own engine runs the real login query.
  Before the change that raises the production error; after it, it recovers.
  `scripts/verify-db-resilience.py` is that check, kept runnable.

### Added

- **`tests/unit/test_db_pool_contract.py`.** The pool decision is a pure
  function, `build_pool_kwargs`, so it can be asserted without reloading the
  data layer. An earlier draft of this test did reload it, which handed the rest
  of the suite an engine with no tables; the failures surfaced far from the
  cause. Nine assertions, all running everywhere including inside the package.

## [0.5.2] - 2026-08-28

### Fixed

- **Code Quality.** `scripts/` and `.github/` no longer ship. The job log named
  all five findings in build tooling: a security hotspot at
  `scripts/preflight-gate.py:213` and code smells at `:34`, `:50`, `:234` and
  `scripts/package-appstore.sh:246`. `sonar-project.properties` declares
  `sonar.sources=spectre,tle_clustering`, so the platform is analysing the whole
  archive and ignoring that declaration. Build and verification tooling is not
  application code, is not needed at runtime or by the Test stage, and only
  widens what the gate can object to. This also retrospectively explains the
  shell smells reported against `scripts/bump-version.sh` in 0.4.6, which were
  addressed by changing the script when the real fix was not shipping it.

### Added

- **`docs/CHANGE-LEDGER.md`, enforced by the packager.** Every version must have
  an entry before it can be built, classifying each change as EVIDENCED, PROBE
  or HYGIENE and stating what a failure would rule out. At most one PROBE per
  submission, because two guesses in one upload cannot be told apart. A gate
  with no evidence gets "NO HYPOTHESIS" rather than an invented fix. Verified by
  removing the entry and watching the build refuse.

### Not changed

- **Dependency Scanning.** No hypothesis. Seven failures, the gate contract
  satisfied, and every content hypothesis held so far has been wrong. The ledger
  records that no further change ships for this gate without the analyser's
  error text, the `.pre` resolution job's log, or a file-level diff against a
  package that passes.

## [0.5.1] - 2026-08-27

0.5.0 failed with the contract satisfied. This matches the remaining attribute
that separates SPECTRE from both applications known to clear the gate.

### Changed

- **All three lock files are now generated by `uv pip compile`**, via the
  canonical `scripts/lock.sh`, replacing `pip-compile`. Neither passing
  application uses a pip-compile header; the one known failure does, and so did
  we. The guidance says header form is not the cause, and it may well be right,
  but with every other difference eliminated this is the last one left, and the
  skill's own locker prescribes uv anyway. `--python-version 3.12` is now
  explicit, which pip-compile could not express and which matters because a lock
  compiled for a different interpreter resolves a different set. Package sets
  are byte-identical: 54 scanned, 44 runtime, 55 development, no version moved.

### Fixed

- **Three contract tests were silently skipping** on `requirements.lock`, which
  0.5.0 deleted. A skipping test is a worse outcome than a failing one, because
  it reads as a pass. They now assert what actually matters: that the runtime
  lock is a version-identical subset of the scanned set, that both are
  tool-generated, and that no pin anywhere lacks a hash. The whole suite now
  runs with zero skips.
- **`_repo_only`'s docstring** claimed pyproject.toml was excluded from the
  package. It is required in it. Corrected, with a warning against reaching for
  the helper to silence a failure.

## [0.5.0] - 2026-08-27

Rebuilt the package to the App Store gate contract, from guidance calibrated
against applications that actually clear this gate. Two changes made earlier in
this branch were backwards and are reversed.

### Fixed

- **`pyproject.toml` restored, and now required.** 0.4.7 removed it to reduce
  ambiguity. It is the single highest-value file to keep: the only root file
  present in both known-passing packages and absent from the known failure, and
  a documented resolution trigger. It is back in minimal form, a `[project]`
  table with **no** `[project.dependencies]`, because declaring dependencies in
  two places is what lets them drift.
- **The local analyser is no longer treated as a gate.** Calibrated against
  three control samples it disagreed with the platform on two, including
  calling a passing package a failure. `verify-dependency-scan.sh` keeps the
  calibration table in its header, is diagnostic only, and can no longer fail a
  build.
- **`scripts/package-appstore.sh` mishandled an absolute output directory**,
  concatenating it onto the working directory and failing in `zip`.

### Changed

- **Three-way requirements split**, replacing the single collapsed manifest:
  `requirements.in` and `requirements.txt` (scanned, runtime plus test),
  `requirements-runtime.in` and `requirements-runtime.txt` (what the image
  installs, under a name the analyser does not read), and `requirements-dev.txt`
  for lint and SAST tooling, which never ships. All hash-locked and compiled as
  a constrained set so the runtime file cannot drift from the scanned one. Same
  54 packages at the same versions as 0.4.9; nothing added, removed or upgraded.
- **The image installs the runtime set only**, reverting 0.4.8's install-then-
  uninstall. Collapsing the split would count the test toolchain against the
  Container Scan stage.
- **`requirements.lock` is gone**, replaced by `requirements-runtime.txt`.
- **`scripts/bump-version.sh` rewrites the version in `pyproject.toml`**, which
  is now literal rather than derived by hatch.

### Added

- **`scripts/preflight-gate.py`**, the contract checker, run by the packager
  against the staged package on every build. It blocks the build on a contract
  violation. Currently: 0 blocking, 1 advisory, and that advisory is a false
  positive (it cannot resolve the digest through the `BASE_IMAGE` build
  argument, which a test already asserts).

## [0.4.9] - 2026-08-27

0.4.8 failed identically. The package now carries exactly one manifest-shaped
file and the stage still crashes, so no remaining hypothesis about our content
survives.

### Changed

- **`docs/DEPENDENCY-SCANNING.md` rewritten as an elimination record.** Eight
  hypotheses, each with the evidence that ruled it out, and a three-line ask
  for the platform team. Written to be handed over rather than re-derived.

### Findings

The first failure was on a directory whose only file was `setup.py`, with no
requirements file in it. Every layout since has failed too, including one
carrying a single hash-pinned, correctly headed `requirements.txt` and nothing
else. Six distinct inputs, one outcome, in three to seven seconds with no error
text. That is the signature of a failure independent of our content.

The analyser is a fork: its directory-selection log line appears in no public
GitLab analyser, no public analyser image carries a v6 tag, and its registry
path returns 403 to an anonymous pull that succeeds for public control images.
It cannot be reproduced outside the platform.

Also ruled out this cycle: the analyser does not need network access. Upstream
builds a complete SBOM with all egress blocked.

## [0.4.8] - 2026-08-27

0.4.7 did not fix Dependency Scanning, so pyproject.toml was not the cause.
This removes the last manifest-shaped file from the submission root. Still a
probe: the platform's analyser is not obtainable, so it cannot be verified
against it here.

### Changed

- **`requirements.lock` no longer ships in the python package.** With
  pyproject.toml already gone, it was the only remaining manifest-shaped file
  beside `requirements.txt`, and it has been present at the root in every
  failed run. Upstream does not recognise a `.lock` name, but the platform's
  analyser is demonstrably a fork with detection behaviour upstream does not
  have, so the assumption is not safe to keep making.
- **`requirements.txt` is now hash-pinned** and is the single manifest. Same 54
  packages at the same versions, 1,513 hash lines, pip-compile header intact.
  It gains hash verification in the platform Test stage, which previously
  installed an unhashed file.
- **The image installs from it and then removes the ten test-only packages**,
  so the runtime image carries exactly what it carried before. Verified by
  building that venv for real: hashed install, uninstall, then the app booted
  from a bare package directory and answered 200 on `/`, `/healthz` and
  `/readyz`.
- **`Dockerfile.docker-only` keeps `requirements.lock`.** That template must
  ship no recognised manifest, so it needs a pinned file under a name the
  detector ignores. The lockfile stays in the repository for it, and the drift
  guard keeps the two in step.
- **Continuous integration audits `requirements.txt`**, the file the image now
  installs.

## [0.4.7] - 2026-08-27

Removes the last ambiguity from the submission root. A reasoned probe, not a
proven fix: the platform's analyser is not obtainable, so this cannot be
verified against it here.

### Changed

- **`pyproject.toml` no longer ships in the submission package.** It is a
  recognised dependency manifest, and the analyser processes every manifest in
  the directory it selects. pyproject.toml maps to the poetry and uv package
  managers, both of which expect a lockfile beside it that this project does
  not use. It is the one constant across every failed Dependency Scanning run,
  surviving three different `requirements.txt` formats. The package root now
  presents exactly one recognised manifest: `requirements.txt`, in pip-compile
  format.
- **pytest and coverage configuration moved** to `pytest.ini` and
  `.coveragerc`, which the analyser ignores. They are now the single source, so
  they cannot drift from a pyproject copy. Verified with the platform's own
  command, `pytest --cov --cov-report=xml:coverage.xml`, against a tree with
  pyproject.toml absent: 845 passed, coverage 74.29%, `coverage.xml` written.
- **The image copies the package onto the path instead of pip-installing it**,
  since installing needs pyproject.toml. Nothing is lost: the lockfile was
  already the single source of truth for dependencies and the install ran
  `--no-deps`. `CMD` moves from the generated `spectre-serve` console script to
  the equivalent `python -m spectre.web._entrypoint`, matching
  `Dockerfile.docker-only`. Booted in that exact layout, with no install and no
  pyproject.toml: binds 0.0.0.0:8080, and `/`, `/healthz` and `/readyz` all
  return 200.

### Fixed

- **Three contract tests read `pyproject.toml`** and so failed inside a package
  that no longer carries it. They now route through a shared `_repo_only`
  helper that skips when a repository-only file is absent, the same rule the
  docs test needed. Caught by the packager's in-package suite run before
  shipping, which is what that gate is for.

### Added

- **A guard** asserting the packager ships no recognised manifest beside
  `requirements.txt`. Verified by adding pyproject.toml back and watching it
  name the file.

## [0.4.6] - 2026-08-26

Verifies the 0.4.5 fix by running the App Store's actual analyser, and makes
that check part of every build.

### Added

- **`scripts/verify-dependency-scan.sh`.** Builds the open-source analyser
  behind the platform's `dependency-scan-python` image and runs it against a
  built package. It prints the fatal message the platform swallows. The
  packager now calls it on every build and refuses to ship a package the
  analyser rejects.

### Verified

Against the real analyser, not by inference:

- 0.4.4 shape, with the hand-written banner: exit 1, no SBOM, reporting
  `manifest fallback is disabled and no usable lock or dependency graph file
  was found for: [requirements.txt]`. That is precisely the platform failure.
- 0.4.5 onward: exit 0, `gl-sbom-pypi-pip.cdx.json` with 54 components and a
  22-entry dependency graph.
- docker-only: exit 0 with no manifest to scan, which is correct for that
  template.

## [0.4.5] - 2026-08-26

Fixes the Dependency Scanning failure at its real cause, and the Test stage
failure 0.4.4 introduced.

### Fixed

- **Dependency Scanning.** With both `requirements.txt` and `pyproject.toml` at
  the root, the analyser selects pip-tools and parses `requirements.txt` with
  the pip-compile parser. That parser accepts a file only if line 2 begins with
  `# This file is autogenerated by pip-compile with`. Ours opened with a
  hand-written banner, so line 2 was `#`, the check is positional, the parser
  skipped, no SBOM was produced and the job exited 1 with no message.
  `requirements.txt` is now generated by pip-compile instead of maintained by
  hand. The package set is the same 54 packages at the same versions; nothing
  added, removed or upgraded. Read from the analyser's own source rather than
  inferred.
- **Test stage.** `test_floor_is_documented_for_the_platform`, added in 0.4.4,
  asserted the presence of `docs/DEPENDENCY-SCANNING.md`. The packager
  deliberately strips `docs/`, so the test passed here and failed inside the
  submitted package. It now skips when the directory is absent.

### Added

- **The packager runs the suite from inside the built zip.** The platform tests
  the uploaded tree, not the working copy, and the gap between the two cost a
  submission cycle. Confirmed by reverting the fix above and watching the
  packager refuse to ship.
- **`TestPipCompileLockContract`**, replicating the analyser's `IsPipCompileLock`
  exactly, plus a drift check between the two manifests. Verified by restoring
  the banner and watching the guard name it.

### Corrected

The 0.4.4 diagnosis blamed the analyser's Python version. That was wrong: the
job log shows Python 3.12.14 resolving every wheel, and the scan exits after
three seconds, far too fast to have attempted a download.

## [0.4.4] - 2026-08-25

Root-causes the Dependency Scanning stage failure. No vulnerable package was
ever involved.

### Added

- **`docs/DEPENDENCY-SCANNING.md`.** The analyser runs `pip download` against
  the manifest before it can analyse anything. SPECTRE pins resolve on Python
  3.12 and above and on nothing older, so an analyser on an older interpreter
  fails to resolve, exits non-zero and writes no report. The platform maps a
  non-zero exit to "Vulnerable dependencies found", which is how a crashed
  scan reaches the user as a finding. The document carries the evidence and
  names the remedy: run the analyser on Python 3.12 or newer.
- **`scripts/audit-dependencies.sh`.** Audits `requirements.txt`, emits a
  CycloneDX SBOM, and measures the interpreter floor by attempting resolution
  on 3.9 through 3.14.
- **`TestPythonFloorContract`.** Guards the offline half of the invariant: the
  floor declared in `requires-python` and the Dockerfile base image must
  agree. Verified by drifting one and watching the guard name the mismatch.

### Verified clean

Checked against the scanner's own database rather than only our own tooling.
`gemnasium-db` was cloned and matched offline against every pinned version
with OR-aware range parsing: 54 runtime and test packages (94 advisories
examined) and 43 development-only packages (54 advisories examined), zero
affected. `pip-audit` reports no known vulnerabilities against
`requirements.txt`, `requirements.lock` and full `pyproject.toml` resolution.
The four vendored JavaScript libraries were fingerprinted by hand, since they
ship without a manifest: htmx 1.9.12, Chart.js 4.4.7, chartjs-plugin-zoom
2.0.1 and Hammer.js 2.0.7 are all outside every advisory on file.

## [0.4.3] - 2026-08-25

### Fixed

- **Four shell code smells in `scripts/bump-version.sh`.** It was the only
  script in the repository with a `bash` shebang, so SonarQube applied its
  bash rule and asked for `[[` over `[`. The other four scripts are POSIX
  `sh` and were correctly left alone. Rather than introduce a second shell
  dialect, the script now uses `#!/bin/sh` like its neighbours. Verified
  under dash, which is what `/bin/sh` resolves to on the base image: every
  path exercised, including the documentation rewrite and both rejection
  cases.
- **Self-referencing extra in `pyproject.toml`.** The `dev` group pulled in
  `spectre[test]`, which forces any resolver reading the file without our
  source tree to fetch a distribution named `spectre` from an index. An
  unrelated `spectre` package exists on PyPI at 0.0.1, so that is a
  dependency-confusion path. The test packages are now listed explicitly.
  `pip install -e .[dev]` still resolves to our own tree.

### Added

- **Two guards** in `TestDependencyScannerContract`: one rejecting any
  self-referencing optional-dependency group, alongside the existing stray
  manifest check. Both verified by reintroducing the fault.

## [0.4.2] - 2026-08-25

### Fixed

- **Dependency Scanning stage failure.** `spectre/app_logging/setup.py` was a
  structlog configuration module, not a packaging manifest: no `setup()` call,
  no `install_requires`. The platform scanner detects a dependency directory by
  filename, announced `Detected supported dependency files in
  'spectre/app_logging'`, and per its own rule skipped every other directory,
  so `requirements.lock` was never read. Resolving the decoy produced nothing,
  the stage exited 1, and no `gl-dependency-scanning-report.json` was written -
  a scan failure reported as if it were a vulnerability finding. The module is
  renamed to `spectre/app_logging/config.py`; its two coverage-exclusion
  references follow. No vulnerable dependency was ever involved: `pip-audit`
  over `requirements.lock` reports no known vulnerabilities.

### Added

- **`TestDependencyScannerContract`** in `tests/unit/test_deployment_contract.py`.
  Fails if any file below the repository root is named like a Python dependency
  manifest, since one such file silently redirects the whole scan. Verified by
  reintroducing the decoy and watching the guard name it.

## [0.4.1] - 2026-08-25

Quality-gate clean-up following the first successful App Store analysis. That
run laid down a baseline, so SonarQube now scores changed lines only and the
count fell from 436 issues to three.

### Fixed

- **Three code smells in `tle_clustering`.** `parser.py` collapsed two chained
  `startswith` calls into the tuple form; `clustering.py` lost an empty
  `if TYPE_CHECKING: pass` block along with the import that existed only to
  feed it, and now uses a set comprehension instead of `set()` over a
  generator. No behavioural change.
- **Unused `noqa: F401` directive** in `tests/integration/test_admin_bootstrap.py`,
  flagged by the changed-lines scoper.
- **`scripts/package-appstore.sh` argument parsing.** The mode flag was read
  from `$2` only, so a bare `--docker-only` was taken as the output directory
  and the run died in `mkdir`. Arguments are now parsed in a loop, the flag and
  the optional output directory may appear in either order, and unknown options
  are rejected rather than silently treated as a path.

### Added

- **`scripts/bump-version.sh`.** Every submission from here on carries a
  distinct version, so the platform, the pipeline log and the artefact on disk
  cannot disagree about which build is which. Takes `patch`, `minor`, `major`
  or an explicit version; updates the single source in `spectre/__init__.py`
  and the literal references in the documentation.

## [0.4.0] - 2026-08-21

Bluestaq App Store readiness. SPECTRE is packaged for the docker-only template
and meets the platform runtime contract. See `READINESS.md` for the scored
report and the remaining gaps.

### Fixed

- **37 failing integration tests.** Commit `d88cb69` added a global CSRF
  dependency without updating the suite, so every authenticated POST returned
  403 and `master` CI had been red since 5 May 2026. Tests now mint a real
  token via `csrf_headers()`, exercising the control rather than disabling it.
- **`GET /` returned 302 to anonymous callers.** The App Store router probes the
  root and treats a redirect as a failed deploy. It now serves the login page at
  200 via the new `optional_login` dependency; console state still never renders
  without a valid session.
- **Lint job disagreed with the local loop.** It installed a partial dependency
  set, so mypy failed in CI while passing locally. It now installs `.[dev]`.
- **`HRR_List.json` resolved to a path that cannot exist in a container.** It is
  now read from the data volume first, so a deployed instance can be given fresh
  data without a rebuild.

### Added

- **Health and readiness endpoints** (`spectre/web/health.py`). `/healthz` is
  liveness only. `/readyz` proves storage with a real write, races a hard 2 s
  timeout so a stalled mount cannot become a silent liveness kill, and returns
  the resolved data directory and the exact errno in its 503 body.
- **Fail-closed startup validation.** A missing, placeholder or short
  `SECRET_KEY` stops the boot. So does a data directory that will not accept a
  write, with the `securityContext.fsGroup` remedy named in the message.
- **`requirements.lock`**, 43 dependencies pinned with SHA-256 hashes,
  installed with `--require-hashes --only-binary=:all:`.
- **`scripts/verify-container.sh`**, builds the image and asserts every
  contract property against it. POSIX `sh`, no bashisms. Run before every upload.
- **`tests/unit/test_deployment_contract.py`**, pins the deployment contract as
  tests so it cannot silently regress.
- Test suites for configuration resolution, the health endpoints, the CSRF and
  session controls, the logout flow and the intercept CSV export.
- **Container contract job in CI**, builds the image and verifies non-root, no
  setuid paths, no package manager, 200 at `/` and the health paths, and
  fail-closed boot.

### Changed

- **Dockerfile rewritten** as a three-stage hardened build: no compiler (every
  dependency ships a manylinux wheel), base pinned by digest, package managers
  and toolchain stripped, the setuid/setgid sweep as the last mutation failing
  the build closed, and the runtime flattened to `FROM scratch` with a single
  `COPY --from=prep / /` so the policy scan finds no layer history.
- **Port 8080.** Resolved from `PORT` in code, never baked with `ENV`.
- **`DATABASE_URL` and the data directory resolve at runtime**, explicit
  variable, then the platform-injected value, then a local default. The baked
  `ENV DATABASE_URL` that would have sent writes to the ephemeral layer is gone.
- Container runs as `USER 10001:0`.
- Version single-sourced from `spectre/__init__.py`; `pyproject.toml` reads it
  dynamically and the FastAPI app stamps it. Previously 0.1.0 and 0.4.0 disagreed.
- `pip-audit` in CI now scans `requirements.lock` rather than a hand-maintained
  duplicate list, so CI and the image can never disagree about what was scanned.

### Platform feedback

- **Fixed the failing Dependencies stage.** The package carried no root
  `requirements.txt`, so the platform's dependency install had no manifest it
  recognised and failed before any later stage ran. Added it, which moves the
  app to the python template; the quality gate conditions were already met.
  `requirements.txt` (88 packages, pinned, what the platform installs) and
  `requirements.lock` (43 packages, hash-pinned, what the image installs) are
  generated from one resolution, and a test asserts their runtime pins never
  drift. Verified by installing into a clean interpreter: 800 tests pass.
- **Removed a fail-open from the setuid sweep** (hadolint DL4006). The
  verification piped `find` into `wc -l`; had find errored with stderr
  suppressed, wc would still have exited 0 and printed 0, reporting a clean
  sweep over a dirty image. The pipe is gone and the check runs under `set -eu`,
  so a failing find aborts the build. The suggested `SHELL` remedy was not
  applied because `/bin/sh` on Debian is dash, which has no `pipefail` and would
  have broken the build.
- Pipeline simulation now covers the dependency-install stage.

### Quality gate

Meets all six SonarQube quality gate conditions on new and changed code:
zero bugs, zero vulnerabilities, zero code smells, 100% coverage on the 129
changed lines, 0% duplication, and six of six security hotspots reviewed.
Reproduce with `scripts/check-quality.sh`; enforced per-commit in CI.

- **Fixed a reliability bug this change introduced**, caught by its own test.
  Narrowing `_load_hrr_from_disk` to a specific exception tuple left
  `AttributeError` uncaught, so well-formed JSON of the wrong shape would crash
  the boot. Resolved with shape validation at the boundary rather than a wider
  catch.
- **Session cookie now sets `Secure`** (`python:S2068` hotspot). On by default;
  disabling it requires the explicit `SPECTRE_COOKIE_SECURE=false` opt-out used
  by the test client, which speaks plain HTTP.
- **Removed blind `except Exception` handlers** from the health probe and the
  HRR loader, replaced magic values with named constants, and hoisted a
  function-level typing import to module scope.
- **Duplication cut from 2.33% to 0%** by hoisting copy-pasted integration
  fixtures into `tests/integration/conftest.py`.
- **Corrected a coverage under-measurement.** SQLAlchemy's async bridge switches
  greenlets on every await, and coverage.py lost the trace afterwards, marking
  lines uncovered that demonstrably run. Fixed with
  `concurrency = ["thread", "greenlet"]` rather than by excluding the lines;
  `auth.py` went from 84% to 93% with no test changes.
- Added `sonar-project.properties` scoping sources, tests and the coverage
  report path, with a written rationale for the single coverage exclusion.
- Added `scripts/check-quality.sh` and `scripts/sonar_scope.py`, which filter
  findings to the lines the gate actually scores, so a pre-existing smell in a
  touched file is never mistaken for a new violation.
- The two tests that silently skipped when run as root now inject the failure
  instead, so the suite reports no false passes.

### Removed

- `bluestaq-foundations-server-python-tailored.zip` (456 KB), committed in error.

---

## [Unreleased]

### Added

- **Training Mode** (`spectre/training/`, `spectre/web/routes/training.py`, `spectre/web/templates/training.html`)
  - Full gamification system: 6 proficiency levels (Cadet → Expert), XP/points engine, five skill axes
  - 13 structured training scenarios covering all 6 levels; each defines Blue+Red assets (synthetic TLEs), objectives, tool workflow, and answer specification
  - Timed challenge scenarios that unlock at Level 4+
  - Step-by-step tutorials per skill axis with XP awards on completion
  - Live SPECTRE console embed via iframe (lazy-loaded) — operators use real tools against scenario data inside the training session
  - DB-persisted training sessions and progress (`TrainingSession`, `TrainingProgress`, `TrainingChallengeResult` ORM models)
  - Training mode banner with sticky amber warning strip; persistent "Return to Operations" control
  - Training session metrics: scenarios passed, tutorials completed, challenges passed, time in training, total points
  - Recommended next step widget based on current level and skill-axis gaps
  - All 13 scenarios designed for tool-only use (Assets panel + Intercept Engine + Decision Engine); no UDL dependency in training

- **Decision Engine Phase 1** (`spectre/domain/decision.py`, `spectre/web/routes/decision.py`)
  - Deterministic what-if analysis: define a grid of N adversary actions × M friendly responses
  - Outcome matrix: each cell computes `composite_score`, `custody_maintained`, `custody_gap_h`, `closest_approach_km`, `time_to_intercept_h`, `delta_v_cost_km_s`
  - Three selector strategies: Minimax (minimise worst-case), Expected Value (probability-weighted), Maximin (maximise best-case)
  - Robust recommendation banner + per-adversary ranked response cards
  - `GET /plan/decision/panel` scenario builder; `POST /plan/decision/evaluate` evaluator

- **Pattern of Life — NOTSO Correlation** (`spectre/astro/notso.py`, `spectre/web/routes/pol.py`)
  - `NOTSORecord` parser for USSPACECOM free-text and structured message formats
  - `correlate_notsos_with_manoeuvres()`: temporal matching of NOTSO windows against detected manoeuvre epochs
  - `OperatorBehaviourProfile`: aggregated statistics on notification lead time, ΔV magnitude accuracy, phantom NOTSO rate
  - `/pol/notso-panel` and `/pol/notso-correlate` routes; graceful fallback when UDL has no NOTSO endpoint
  - Results partial: three-column matched/notso-only/manoeuvre-only table + behaviour profile card

- **Pattern of Life — Monte Carlo Simulation** (`spectre/astro/monte_carlo.py`, `spectre/web/routes/pol.py`)
  - `ManoeuvreHypothesis` and `ManoeuvreType` dataclasses; `MANOEUVRE_ARCHETYPES` dict (park, shadow, inspection, rendezvous, evasion)
  - Vectorised NumPy sample generation: Gaussian/uniform ΔV magnitude, Rayleigh pointing cone, Gaussian timing, Gaussian B*
  - RIC→ECI rotation via pre-manoeuvre state unit vectors
  - RK45 integrator (scipy) with J2 + exponential atmosphere drag; `ProcessPoolExecutor` for parallel sample propagation
  - `MonteCarloResult`: P5/P50/P95 SMA/ecc/inc/RAAN distributions, position cloud 3σ radius, regime probability breakdown, convergence diagnostics
  - `/pol/monte-carlo` route; per-manoeuvre `[Monte Carlo ▶]` button in PoL results; regime probability bar chart and percentile table
  - Added `scipy>=1.11` dependency

- **Pattern of Life — Photometry Analysis** (`spectre/astro/photometry.py`, `spectre/web/routes/pol.py`)
  - `PhotometryObservation` dataclass with observer geometry fields (airmass, elevation, range, solar phase, lunar phase)
  - Geometric corrections: range normalisation (reduced magnitude), Rozenberg airmass, lunar quality flagging
  - `fit_baseline()`: quadratic phase function via `scipy.optimize.curve_fit` + iterative sigma-clipping
  - `detect_change()`: Student's t-test on recent residuals vs baseline window; `PhotometryChangeAssessment`
  - Manoeuvre correlation: for each detected brightness change, search for manoeuvres within ±48 h
  - `/pol/photometry-panel` and `/pol/photometry-analyse` routes; "Photometry" tab in PoL results

- **Pattern of Life — TLE Cadence Filtering** (`spectre/astro/tle_filter.py`)
  - `TLECluster` dataclass with `span_seconds` property
  - `cluster_tles()`: groups sorted `TLERecord` list by regime-aware minimum spacing threshold
  - `select_representative()`: best TLE per cluster — lowest RMS residual → latest epoch → highest element set number
  - `quality_flag_sequence()`: staleness, B* discontinuity, and element-jump flags across the representative sequence
  - `filter_tle_history()`: top-level pipeline returning `(representatives, flags)` tuple
  - Cadence-filter checkbox in PoL panel; quality flags summary in PoL results
  - `TLE_FILTER` thresholds added to `spectre/config/constants.py`

- **CW Geometry Module** (`spectre/astro/cw_geometry.py`)
  - Clohessy-Wiltshire equations for Hill-frame relative motion
  - Relative state vector computation; NMC (natural motion circumnavigation) safety ellipse parameters

- **CW Geometry Route** (`spectre/web/routes/geometry.py`)
  - `GET /plan/geometry/panel` — Hill-frame visualiser
  - `POST /plan/geometry/intercept` — compute Hill-frame trajectory for given (blue, red, response) parameters

- **NOTSO Cache** (`spectre/data/notso_cache.py`)
  - Persistent NOTSO record storage keyed by NORAD ID; retrieval interface for Decision Engine Phase 5 priors (planned)

- **Security hardening**
  - `.pre-commit-config.yaml`: `gitleaks` v8.18.4, `ruff`, `bandit[toml]`, `mypy`, standard hooks (large files, YAML/TOML validation, no-commit-to-branch master)
  - `CODEOWNERS`: `@Higgy-843` owns `.github/`, `spectre/web/auth.py`, `spectre/web/routes/login.py`, `spectre/web/database.py`, `spectre/config/`, `docs/SECURITY.md`
  - `.github/dependabot.yml`: weekly pip + GitHub Actions dependency updates; Europe/London schedule; labels: `dependencies`, `security`, `ci`
  - `pyproject.toml`: `[tool.bandit]` configuration section added; `hypothesis>=6.0`, `bandit[toml]>=1.7`, `pip-audit>=2.7` added to dev extras
  - `docs/SECURITY.md`: full UK NCSC / SSCoP aligned security policy (classification, incident response, secure development, supply chain)

- **CI pipeline rewrite** (`.github/workflows/ci.yml`)
  - `permissions: contents: read` at top level (principle of least privilege)
  - `lint` job: ruff + mypy
  - `test` job: full pytest suite with coverage
  - `sast` job: bandit with `pyproject.toml` config
  - `sca` job: pip-audit for CVE scanning of dependencies
  - `secrets` job: gitleaks v8.18.4 secret scan

- **New test modules**
  - `tests/unit/test_monte_carlo.py`
  - `tests/unit/test_notso.py`
  - `tests/unit/test_photometry.py`
  - `tests/unit/test_tle_filter.py`
  - `tests/unit/test_decision.py`
  - `tests/unit/test_training_gamification.py`
  - `tests/unit/test_cw_geometry.py`
  - `tests/unit/test_threat_sweep.py`
  - `tests/unit/test_udl_tle_fetch.py`
  - `tests/unit/test_exceptions.py`

### Changed

- `pyproject.toml`: added `numpy>=2.0`, `python-dotenv>=1.0`, `scipy>=1.11`, `scikit-learn>=1.4` to runtime dependencies (previously undeclared but used); removed `pywin32` (no imports in codebase)
- All 13 training scenarios rebuilt — removed all PoL/NOTSO/Monte Carlo/HRR auto-fetch references; scenarios now require only Assets panel, Intercept Engine, and Decision Engine so they are usable without a live UDL connection
- `spectre/training/config/scenarios.yaml`: added comment block documenting tool capabilities and design rules for future scenario authors
- Training mode `tpanel-console` iframe: lazy-loaded on first tab activation; `training-main` switches to `position:relative` / `overflow:hidden` when console tab is active so the iframe fills the panel correctly

### Fixed

- Training mode leave redirect: `POST /training/leave` now redirects to `/` (operator console), not `/operator`
- Training session `datetime` subtraction: naive/aware mismatch when computing `time_in_training_minutes`; both datetimes now forced to UTC-aware before subtraction
- Training active scenario layout: objectives, descriptions, and answer inputs now render correctly in scenario detail partial

---

## [Unreleased — prior sprint]

### Added

- **GCAT Browser** (`spectre/web/routes/gcat.py`)
  - Fully interactive browser for the General Catalog of Artificial Space Objects (J. McDowell, planet4589.org/space/gcat; CC-BY)
  - 28 TSV datasets across four categories: Derived, Objects, Payloads, Supporting
  - `GET /gcat/panel` returns the panel skeleton instantly (< 50 ms, no network I/O)
  - `GET /gcat/table` fetches the requested dataset on first access then serves from in-memory `_CACHE`; supports column search, single-column sort, and windowed pagination
  - `POST /gcat/refresh` concurrently re-downloads all 28 datasets using `asyncio.gather` + `ThreadPoolExecutor`
  - HTMX out-of-band swaps (`hx-swap-oob`) update nav button row counts after each table load
  - Debounced search input (350 ms); `urlquote` Jinja2 filter registered in `app.py`
  - CSS `position: absolute; inset: 0` layout for the GCAT hero panel
  - Fixed loading overlay always-visible bug: `.gcat-load-overlay` defaulted to `display: flex` — corrected to `display: none` with `.gcat-load-overlay.htmx-request { display: flex }`
  - Added `pandas>=2.0` dependency

- **Pattern of Life panel** (`spectre/astro/pattern_of_life.py`, `spectre/web/routes/pol.py`)
  - Historical TLE sequence analysis: period tracking, manoeuvre detection, activity classification, and behavioural baseline
  - Hero tab lazy-loaded via HTMX; Chart.js zoom/pan via `hammer.min.js` + `chartjs-plugin-zoom.min.js`
  - Dual-fetch strategy: `/elset/current` for latest TLE + `/elset` with epoch for history

- **Threat Sweep redesign** (`spectre/web/routes/threat.py`)
  - HRR group dropdown (Blue/Red HRR by rank 0–5) with TLE pre-fetch on selection
  - Batch Hohmann evaluation across 5 orbital epochs; top 5 auto-refined with Lambert for VNB components
  - TLE clustering via DBSCAN before sweep run; elevated-uncertainty flag (▲) for multi-cluster objects
  - Sentinel pattern: background sweep re-run when asset set changes
  - Collapsible TLE Cadence Filter Flags section in results (collapsed by default)

- **HRR Watchlist sub-tab** in the Assets panel
  - Blue HRR and Red HRR tables with one-click **→ Blue** / **→ Red** buttons
  - Button replaced by OOB confirmation badge on success

- **Intercept engine expansion** (`spectre/web/routes/maneuver.py`, `spectre/astro/tactical.py`)
  - 23 total methods across Classical, Tactical, Advanced Analysis, and Decision Support categories
  - All-intercepts comparison result partial
  - Trade-space ΔV vs transfer-time scatter plot with zoom/pan

### Changed

- Architecture completely migrated from STK-dependent hexagonal adapter pattern to pure-Python astrodynamics; `spectre/stk_adapter/` and `spectre/intercept_engine/` packages removed; `spectre/astro/` package now provides all orbital mechanics
- `docs/architecture.md` rewritten to reflect current pure-Python stack

---

## [0.1.0] — 2026-03-04

### Added

- Initial project scaffold with hexagonal architecture
- `IStkSession` Protocol (stk_adapter/interface.py)
- `FakeStkSession` unit-test double (stk_adapter/fake.py)
- `StkComSession` COM stub (stk_adapter/com_session.py)
- Domain models: `BlueAsset`, `RedTrack`, `InterceptWindow`, `RunConfig`, `AccessInterval`
- `ScenarioPlanner` stub (domain/scenario.py)
- Geometry helpers stub (domain/geometry.py)
- structlog configuration with run_id correlation (app_logging/setup.py)
- Constants and runtime settings (config/)
- pytest unit test stubs
- GitHub Actions CI (lint + unit tests on ubuntu-latest)
- Docker + uvicorn deployment
- Architecture, operator guide, and STK object model notes (docs/)

> **Note:** v0.1.0 used STK COM integration for all orbital mechanics. This was completely replaced in favour of pure-Python astrodynamics in the subsequent sprint. The STK adapter, PySide6 UI, and `intercept_engine/` package have all been removed. No upgrade path from v0.1.0 is provided — start fresh.
