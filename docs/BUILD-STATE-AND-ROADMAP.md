# Build state and the art of the possible

Where SPECTRE actually is, what is left, and what would make it materially
better than anything currently on the market.

Written from the repository: route surface, coverage report, module inventory
and the data files, not from recollection.

## The one-sentence finding

**The capability is not missing. It is disconnected.**

SPECTRE already computes, in one application, five things that almost nobody
holds together: orbital dynamics, detected manoeuvre history, a behavioural
anomaly score, a propellant budget, and per-object intelligence. Its headline
threat verdict consults one of them.

That gap is the roadmap.

## Where the build stands

Thirteen route modules are wired and serving. Five hero capabilities on the
operator console: threat sweep, manoeuvre engine, pattern of life, decision
support, and orbit catalogue. UDL login, TLE sourcing, state vectors, HRR and
NOTSO ingest all work against the live service.

### What is genuinely complete

● **Orbital mechanics**, now validated. Eight modules checked against published
  answers and physical invariants; six defects found and fixed.
● **Pattern of life.** `pattern_of_life.py` detects manoeuvres between
  successive element sets and classifies them, tracks drift phases, scores
  behavioural anomaly across five components, estimates a propellant budget
  with remaining life, and predicts longitude 30, 60 and 90 days out.
● **NOTSO ingest.** The cache carries real manoeuvre notifications with
  delta-V, period, apogee, perigee and inclination change, pre- and
  post-manoeuvre element sets from multiple providers, and a neighbourhood
  close-approach assessment.
● **Deployment.** Live on the App Store, PostgreSQL-backed, container hardened,
  browser-probed.

### What is thin

| Area | Coverage | Read |
|---|---|---|
| `web/routes/pol.py` | 21% | the richest analysis, the least tested |
| `web/routes/threat.py` | 29% | the headline capability |
| `web/routes/udl.py` | 31% | the live data path |
| `astro/maneuvers.py` | 46% | the intercept methods |
| `web/routes/maneuver.py` | 52% | the manoeuvre engine |

Whole-repository coverage is 74.3% against a house standard of 80.

### Known open work

● Four improvement-plan items outstanding: guard red cases for the template and
  contract checks, the portable change-ledger pattern, the App Store
  failure-signature reference, the calibration requirement.
● Five orbital findings recorded and unfixed: no input validation on the
  transfer functions, a regime-blind CW validity threshold, a GEO radius
  inconsistent with the sidereal day, TEME and ECI conflated across the
  propagator boundary, `propagate_range` swallowing failures.
● Seven astro modules and fourteen `tactical.py` heuristic functions unaudited.
● Six red-team recommendations on the sweep.
● No self-service password reset; usernames match case-sensitively.
● `HRR_List.json` absent from the deployed volume, so threat sweep degrades to
  requiring an interactive UDL login.

## The disconnection, precisely

The application computes **three independent risk verdicts** and shows a
fourth:

1. `AnomalyScore.risk_level` - from observed behaviour, five weighted
   components, CRITICAL through MINIMAL.
2. `IntelAssessment.risk_level` - operator-level, with mission profile and
   behaviour class.
3. `adversary_intel.json` `threat_level` - from published counterspace
   assessments, with operational status.
4. The threat sweep's own verdict - four thresholds on a delta-V number.

`threat.py` does not import `pattern_of_life` at all. So the screen that says
"Adversary capability assessment" is the only one of the four that knows
nothing about the adversary.

`PropellantBudget.remaining_life_years` already answers *can this object
actually fly that intercept?* It is computed, displayed on another page, and
not consulted.

## Phase 1: connect what exists - DELIVERED in 0.5.14, with one item part-done

Nothing here is new science. It is wiring, and it is where the fastest and
largest gain sits.

Status against the four items as written, so the record is not flattering:

| Item | State |
|---|---|
| 1. Composite threat verdict | **Done.** `spectre/domain/threat_assessment.py`, geometry and capability answered separately, weaker side governing, unassessed objects falling back to geometry rather than being scored harmless. |
| 2. Rank on warning time | **Done.** `warning_time_rank` drives both the entry sort and the worst course of action; warning time is now the lead figure on the panel. |
| 3. Real intent from behaviour | **Part done.** The verdict *rationale* is written from real evidence and names the status that produced it. The `_sweep_intents` dictionary mapping solver name to prose is unchanged, because replacing it needs the manoeuvre classifier, which needs an element-set history the sweep does not fetch. |
| 4. Show what was refused | **Done.** Eight silent excepts now record the solver's own message; the panel lists them. |

Capability evidence is currently the assessed record alone. Propellant budget,
anomaly score and observed manoeuvre count all need the same absent history and
are reported as unavailable rather than assumed either way. That fetch is the
first piece of Phase 2 and would complete item 3 with it.

**1. A composite threat verdict.** Combine geometric accessibility with
behavioural anomaly, propellant remaining, and assessed status. An object with
a cheap geometric path, a history of unexplained burns, propellant in hand and
an assessed offensive role is a different proposition from a degraded satellite
that happens to share an orbital plane. Today they score identically.

**2. Rank on warning time.** Delta-V is the feasibility filter; time to closest
approach is the decision. Surface "earliest credible arrival" as the headline.

**3. Real intent, from behaviour.** Replace the static solver-name dictionary
with the manoeuvre classifier and drift-phase history already built. "This
burn is consistent with routine station-keeping for this object" and "this burn
is unlike anything in 200 days of history" are different sentences, and the
data to write both exists.

**4. Show what was refused, and why.** The silent `except Exception: pass`
biases the sweep towards under-reporting the fastest approaches, because
refusals cluster on the aggressive end.

## Phase 2: the manoeuvre trigger

You identified this yourself, and it is the right instinct.

Today the sweep is a thing an analyst runs. The question they actually hold is
*what changed, and does it matter?* The answer should arrive, not be requested.

**The trigger chain:** a manoeuvre is detected, whether from the UDL manoeuvre
endpoint, a NOTSO notification, or SPECTRE's own element-set differencing.
Within seconds the application re-runs the sweep for that object against the
blue asset list, compares the new accessibility envelope with the one from
before the burn, and reports the delta.

**The output is the differential, not the state.** Not "SJ-17 can reach your
asset for 190 m/s" but "SJ-17's burn at 0637Z brought your asset from 14 hours
of warning to 3 hours, and moved three other assets inside its reach". That is
a sentence an analyst can act on, and no product I am aware of produces it.

The NOTSO cache shows the shape of the input is already understood: it carries
delta-V, period change, apogee and perigee change, inclination change, drift
rate and post-manoeuvre element sets. The missing piece is the automatic
re-assessment on arrival.

## Phase 3: capabilities worth building

Ranked by the gap between value and effort, given what is already in the tree.

**Reachability as a field, not a pair.** Instead of asking "can red reach blue",
precompute for each red object the set of all catalogue objects it can reach
within a delta-V and time budget, and keep it warm. The analyst's question
becomes "who is inside whose envelope right now", answerable instantly, and
the answer changes visibly when anyone manoeuvres. The Lambert solver is now
fast and correct enough to support this.

**Custody risk, not conjunction risk.** Conjunction screening asks whether two
objects will collide. The orbital warfare question is whether an object can
reach a position from which it could act, and be there before you could
respond. That is a reachable-set problem against your response timeline, and it
is a different and more useful calculation than a probability of collision.

**Behavioural fingerprinting across the catalogue.** The manoeuvre classifier
runs per object. Run it across the whole GEO belt and cluster: objects whose
station-keeping signature matches a known bus, objects whose signature changed
after a given date, objects behaving unlike their declared mission. Anomaly is
far easier to see against a population than against a single history.

**Propellant-bounded threat horizons.** `PropellantBudget` estimates remaining
delta-V. Combined with reachability, that yields the total set of positions an
object can *ever* occupy for the rest of its life. An analyst could ask "can
this thing ever reach my asset again" and get a defensible no.

**Intent inference from a sequence, not a burn.** A single burn is ambiguous.
A sequence - drift halt, plane match, phasing, closing - is not. The drift-phase
machinery already segments history into phases; recognising the *grammar* of an
approach across phases is the step from detection to warning.

**Counterfactual planning.** Given a detected threat, what are the blue
options, what do they cost, and by when must each be decided? The manoeuvre
library already computes every one of those transfers. It has never been
pointed at the defender.

**The decision clock.** Every assessment carries a "decide by" time derived
from the adversary's fastest credible approach minus your own response latency.
That single number, on every screen, would change how the tool is used more
than any new calculation.

## What I would do in what order

1. Phase 1 wiring. Largest gain, least risk, uses only what is built.
2. Fix the five recorded orbital findings and audit the remaining seven
   modules. The foundation has to be trustworthy before anything is built on
   it, and every module examined so far has contained a defect.
3. Lift coverage on `threat.py`, `pol.py` and `maneuvers.py`. They are the
   three thinnest and three most important.
4. Phase 2, the manoeuvre trigger.
5. Phase 3, chosen by which customer conversation lands first.

## The honest caveat

Phase 3 is the exciting part and it is also the part where I would be least
able to tell you, from inside the repository, which item an orbital warfare
analyst would actually pay for. The ranking above is reasoned from what the
code can already support, not from watching anyone work. Before building any of
it, one afternoon with a practising analyst would reorder this list, and that
is worth more than my ordering of it.

What I can say with confidence is the first finding: the application already
knows more than it says. Closing that gap needs no new research at all.
