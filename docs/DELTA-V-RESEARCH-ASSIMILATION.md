# Assimilating the delta-V research into SPECTRE

Source: Bluestaq Limited Space Watch, *Satellite Manoeuvre Delta-v: Feasibility
Above 0.5 km/s and Budgets by Regime*, v1.0, 13 October 2026. Open source.

Assessed against SPECTRE 0.5.19 on branch `claude/app-store-readiness-09re0q`.
Every figure below was measured by running the code, not read off it.

## Bottom line

The research validates the new estimator and condemns the constants around it.

SPECTRE's ΔV physics now reproduces every worked value in the assessment that it
can compute, to within rounding. The numbers the application then *applies* to
those ΔVs do not: the station-keeping classifier uses annual budgets as
per-event limits, the anomaly baseline is four times the cited GEO figure, and
the propellant model reports a quantity that is not the one its label names.

The consequence is specific and it is the wrong way round. Four of the
assessment's own named counterspace events, including both Luch/Olymp-K moves,
are classified by SPECTRE as routine station-keeping.

## Part 1: what the research validates

The assessment publishes worked ΔV values with their basis. SPECTRE's estimator
was built independently of them. They agree:

| Quantity | Assessment | SPECTRE computes | Source |
|---|---|---|---|
| GEO plane change, per degree | about 54 m/s | 53.66 m/s | Table 4, FACT |
| LEO plane change, per degree | about 133 m/s | 132.86 m/s | Table 4 |
| GEO plane change for 0.5 km/s | about 9.3° | 9.33° | Table 4, FACT |
| LEO plane change for 0.5 km/s | about 3.8° | 3.76° | Table 4 |
| GEO graveyard raise, 300 km | about 11 m/s | 10.94 m/s | Table 3 |
| LEO altitude change, 500 to 600 km | about 55 m/s | 54.74 m/s | Table 4 |
| LEO altitude change, 300 to 530 km | about 130 m/s | 129.68 m/s | Table 4 |
| GEO relocation, 10° in 10 days | about 6 m/s | 5.69 m/s | Table 4 |
| GEO relocation, 180° in 30 days | about 34 m/s | 34.16 m/s | Table 4 |
| Rapid GEO relocation, 90° in 3 days | about 170 m/s | 170.81 m/s | Table 4 |
| Semi-major axis offset at 30°/day | about 2,300 km | 2,342 km | Table 4 |

The cross-track channel uses `Δv = 2·v·sin(θ/2)`, which is the assessment's own
stated basis, and the along-track channel uses `Δv = n·Δa/2`, which is
algebraically the `Δv ≈ v·Δa/2a` the assessment quotes for the graveyard raise.
Two independent derivations landing on the same figures is the strongest
external check available short of a published manoeuvre log.

This is worth stating plainly because the previous estimator reproduced none of
them. On the same inputs it returned figures one to three orders of magnitude
larger, and nothing in the application was positioned to notice.

## Part 2: SATNO 62902, refined

The assessment settles what was previously an argument from plausibility.

● **Table 2** puts a LEO electric smallsat's *entire lifetime* budget at 500 to
  2,500 m/s, central 1,500. The reported 36,686.4 m/s was therefore 15 to 73
  times everything the platform could ever hold, and about 24 times the
  assessment's practical ceiling for any chemical spacecraft in Earth orbit.
● **Table 3** puts LEO station-keeping at 500 to 600 km under 5 m/s/yr on
  average and up to about 25 m/s/yr. The reported annual rate of 34,800 m/s/yr
  was 1,400 to 7,000 times the upper bound.
● The corrected figure on a catalogue built to match 62902 is 20.5 m/s over 385
  days, or 19.4 m/s/yr. That sits inside Table 3's envelope for the regime. The
  new estimator does not merely produce smaller numbers; it produces numbers in
  the range the open-source literature says the regime occupies.

## Part 3: where the code and the assessment disagree

Ranked by operational consequence. Each row was produced by running the code.

### 3.1 The station-keeping classifier uses annual budgets as per-event limits

`spectre/astro/pattern_of_life.py:_SK_DV_LIMIT` is applied per manoeuvre in
`_classify_manoeuvre`: `dv <= sk_limit` means `station_keeping`.

| Regime | Code, per event | Assessment, per **year** (Table 3) |
|---|---|---|
| GEO | 50 m/s | 43 to 50 north-south plus 1 to 5 east-west |
| HEO | 50 m/s | 50 to 70 |
| MEO | 30 m/s | about 1 or less |
| LEO | 20 m/s | 5 to 100, solar-cycle dependent |

The GEO and HEO values match the assessment's annual budgets exactly, which is
how the confusion is visible rather than merely suspected. A real single GEO
north-south burn, taking 48 m/s/yr at a fortnightly cadence, is 1.84 m/s.

Running the actual classifier on the assessment's own named events:

| Event | ΔV | SPECTRE calls it |
|---|---|---|
| GEO graveyard raise, 300 km (Table 3) | 11 m/s | **station keeping** |
| Luch/Olymp-K 2, 62° relocation (observed, 2025) | 11 m/s | **station keeping** |
| Luch/Olymp-K 1, raise above GEO (observed, 2025) | 15 m/s | **station keeping** |
| GEO relocation, 180° in 30 days (Table 4) | 34 m/s | **station keeping** |
| SJ-21 tow of Beidou-2 G2 (observed, 2022) | 60 m/s | repositioning |
| SJ-21 tow, round trip (observed) | 120 m/s | unknown |
| Cosmos 2576 inspector campaign (observed) | 28 m/s | unknown |
| Rapid GEO relocation, 90° in 3 days (Table 4) | 170 m/s | repositioning |

Four of the assessment's named real events, including both Russian relocations
it uses as its own calibration cases, are labelled routine. The SJ-21 round trip
and the Cosmos 2576 campaign, both documented counterspace activity, fall into
`unknown`.

### 3.2 The anomaly baseline is four times the cited GEO figure

`_GEO_SK_BASELINE` sets `dv_mean_ms = 8.0` at `interval_days = 14.0`, which
implies **209 m/s/yr**. Table 3 gives GEO as 44 to 55 m/s/yr all in. Every GEO
object is therefore scored against a baseline roughly four times its real
routine budget, so an object spending four times the norm scores as ordinary.

### 3.3 The anomaly score's budget term ignores regime

`_compute_anomaly_score` awards a full budget score at 200 m/s/yr for every
regime. Against the cited routine figures:

| Regime | Routine (cited) | 200 m/s/yr is | Score at **twice** routine |
|---|---|---|---|
| LEO | 25 m/s/yr | 8× routine | 25 of 100 |
| MEO | 1 m/s/yr | 200× routine | 1 of 100 |
| GEO | 48 m/s/yr | 4× routine | 48 of 100 |
| HEO | 60 m/s/yr | 3× routine | 60 of 100 |

A navigation satellite burning twice its regime's entire annual budget scores
one point out of a hundred. `spectre/domain/manoeuvre_calibration.py` already
holds the cited per-regime figures; Pattern of Life does not use them.

### 3.4 The propellant model reports a quantity its label does not name

`_compute_propellant_budget` computes `1 - exp(-Δv/ve)`, which is the fraction
of **total spacecraft mass** that had to be propellant, and labels it
`propellant_used_pct`, the fraction of the **propellant load** consumed. The two
differ by the propellant mass fraction.

For a LEO smallsat that has spent 20 m/s, the function reports 0.9%. Table 2
puts such a platform's propellant at 5 to 15% of mass, so the propellant
actually consumed is about 9.2%, ten times the reported figure.

Three further defects in the same function:

● `assumed_propellant_kg = 900.0` and a 3-tonne platform are applied to every
  object regardless of regime. Table 2 distinguishes six platform classes
  spanning 0.5 to 9 km/s of capacity.
● `dv_remaining` divides by `assumed_prop_kg + assumed_prop_kg`. With nothing
  spent that is 900/1800, so the expression returns `-ve·ln(0.5)` — a constant,
  1,495 m/s for bipropellant, for every object in every regime. It is a fixed
  number dressed as a calculation.
● `budget_class` returned "Very High" for every GEO case tested, from 200 to
  2,000 m/s of cumulative spend.

### 3.5 Correcting the ΔV moved the propellant error rather than removing it

`spectre/domain/threat_assessment.py` grades an object `Band.MINIMAL`, meaning
it cannot act, when `propellant_used_pct >= 95`. That band dominates every other
capability signal.

With the old estimator reporting tens of km/s, **every** analysed object tripped
it. SATNO 62902 would have been graded incapable while actively manoeuvring,
which is the most dangerous single consequence of the original defect.

With correct ΔV the band is now unreachable. Reaching 95% of total mass requires
`-ve·ln(0.05)`, which is 9.40 km/s for bipropellant and 6.46 km/s for
monopropellant. The assessment's practical Earth-orbit ceiling is 1 to 2.5 km/s
chemical and 2 to 5 km/s electric. Measured:

| Cumulative ΔV | Reported used | Incapacity band |
|---|---|---|
| 36,686 m/s (62902, old estimator) | 100.0% | **MINIMAL, cannot act** |
| 2,500 m/s (entire chemical ceiling, Table 2) | 54.9% | not incapacitated |
| 750 m/s (15 years of GEO north-south, Table 2) | 21.3% | not incapacitated |
| 20.5 m/s (62902, new estimator) | 0.7% | not incapacitated |

An object that has genuinely exhausted its tanks will never be reported as such.
The error has flipped from crying wolf on every object to never crying at all.

### 3.6 Two parallel sets of numbers for the same physics

`spectre/domain/manoeuvre_calibration.py` was written in 0.5.15 to assimilate an
earlier edition of this same assessment. It carries per-regime, per-kind posture
bands with cited provenance, the annual station-keeping table, platform classes
with acceleration rates, and the delivery-time model.

`spectre/astro/pattern_of_life.py` imports none of it and carries its own
uncited `_SK_DV_LIMIT`, `_GEO_SK_BASELINE`, `_ISP_MONO`, `_ISP_BI` and the
900 kg assumption. Two definitions of GEO station-keeping that disagree is worse
than one that is wrong, because only one of them will ever be updated.

## Part 4: recommendations for assimilation

Ranked by operational consequence, with the value each should take.

### R1. Point Pattern of Life at `manoeuvre_calibration` (critical)

Delete `_SK_DV_LIMIT` and `_GEO_SK_BASELINE` and classify through the existing
`classify_posture` and `_BANDS`, which are already keyed by (regime,
manoeuvre kind) with cited provenance. `_classify_manoeuvre` already determines
the dominant channel from the measured decomposition, so the manoeuvre kind is
available to key on. This closes 3.1, 3.2 and 3.6 together and removes the
duplication rather than correcting it twice.

Where a per-event station-keeping ceiling is still needed, derive it from the
annual budget and the observed inter-manoeuvre interval the analysis already
computes, rather than asserting one. For GEO that yields roughly 2 m/s at a
fortnightly cadence, against the 50 m/s in force today.

### R2. Rebuild the propellant model on Table 2 (critical)

● Rename the output to what it measures, or convert it to what it claims. If the
  label stays `propellant_used_pct`, divide by a regime-appropriate propellant
  mass fraction: 5 to 15% for a LEO electric smallsat, 15 to 25% xenon for an
  all-electric GEO bus, 30 to 40% for a chemical inspector, about 55% of GTO
  mass for a chemical GEO comsat.
● Replace the single 900 kg assumption with the platform classes Table 2
  already defines, selected by regime and, where known, by the object's intel
  record.
● Delete the `dv_remaining` expression. Report remaining ΔV against the
  platform's *discretionary* budget from Table 2, which is 50 to 200 m/s for a
  chemical GEO comsat and 0.5 to 1.5 km/s for an all-electric bus, not against
  a notional full tank.
● Re-derive the incapacity threshold in `threat_assessment.py` from that
  discretionary budget rather than from 95% of total mass, which no real
  platform can reach.

Until this is done, treat `propellant_used_pct` and `remaining_life_years` as
unreliable in both directions and do not let them drive a capability verdict.

### R3. State the detection floor in operational terms (major)

Table 4 puts collision avoidance at centimetres per second to about 1 m/s per
burn, and Starlink flew 207,152 of them between December 2025 and May 2026,
more than 40 per satellite per year. SPECTRE's measured floor is 0.68 m/s on a
clean single-provider catalogue and 2.8 m/s where two providers contribute.

Routine collision avoidance is therefore below the floor and always will be.
This is a limit of element-set differencing, not a defect, but the panel says
nothing about it, and "no manoeuvres detected" on a Starlink-class object is a
materially misleading statement.

What the capability *does* see, against the assessment's named events:

| Event | ΔV | Above a 2.8 m/s floor? |
|---|---|---|
| Collision avoidance, any regime | up to 1 m/s | no, and never will be |
| GEO north-south station-keeping, per burn | about 1.8 m/s | marginal |
| GEO graveyard raise | 7 to 11 m/s | yes |
| Luch/Olymp-K 2 relocation | 11 m/s | yes |
| Luch/Olymp-K 1 raise above GEO | 15 m/s | yes |
| Cosmos 2576 inspector campaign | 25 to 30 m/s | yes |
| SJ-21 dock and tow | 60 to 120 m/s | yes |
| Rapid GEO relocation | about 170 m/s | yes |

That is the right split for the mission: the capability is blind to routine
traffic management and sees counterspace behaviour. Say so on the panel, with
the measured floor and what it excludes, rather than leaving the operator to
infer that a quiet object is a passive one.

### R4. Act on the assessment's second watchlist recommendation (major)

"Treat inferred on-station ΔV of 0.5 km/s or more as high priority. It indicates
a plane change, cislunar departure, OTV or tug activity, or refuelling-enabled
behaviour."

Nothing in SPECTRE escalates on this today. A single detected manoeuvre above
the platform ceiling for its regime is, by the assessment's own reasoning, not a
large manoeuvre by a normal satellite; it is evidence the object is not what it
was taken to be. Pattern of Life should raise it as such, naming which of the
four explanations the orbit change is consistent with. The decomposition already
distinguishes them: a cross-track-dominated 0.5 km/s is a plane change, an
along-track-dominated one is a transfer.

### R5. Carry the rate constraint into Pattern of Life (major)

"Characterise electric platforms by rate, not reserve. Large ΔV but millinewton
thrust: model time to reach a target, using thrust and power, not total ΔV
alone."

`PLATFORM_CLASSES.minimum_burn_hours` already implements this for the threat
sweep. Pattern of Life does not use it. A detected 170 m/s manoeuvre on an
all-electric GEO bus at 9e-5 m/s² implies about 22 days of continuous thrust,
which is itself a finding: it constrains when the manoeuvre must have started
and rules out any scenario requiring it to be executed on short notice. The
drill-down panel already dates the burn, so it is positioned to say this.

### R6. Represent refuelling (moderate)

"Track refuelling as a capability multiplier. SJ-25 class activity removes the
end-of-life ΔV constraint on Chinese GEO inspectors."

Cumulative ΔV is monotonic in the current model, so a refuelled object reads as
progressively more exhausted exactly as it becomes more capable. Measured on a
GEO object: 200 m/s cumulative gives 9.9 years remaining, 1,200 m/s gives 1.1
years. SJ-21 was refuelled in 2025 and its cumulative spend since 2022 continues
to count against it.

The minimum useful change is an operator-settable "reserve reset" date per
object, after which cumulative ΔV is accumulated afresh, with the earlier total
retained and shown separately. Modelling the transferred quantity is not
possible on open sources: the reported 142 kg hydrazine transfer is secondary
reporting the assessment itself marks unconfirmed.

### R7. Do not act on the first watchlist recommendation as written (no change)

"Set the GEO alert threshold at about 0.1 km/s, not 0.5 km/s."

`DEFAULT_SWEEP_BUDGET_M_S = 500.0` is the nearest thing in the codebase to a
500 m/s threshold, but it is a *sweep budget*, the ΔV an interceptor is assumed
to be able to spend, not an alert threshold on observed behaviour. Lowering it
would shrink the set of intercepts the sweep considers, which is the opposite of
what the recommendation intends. The posture bands in `manoeuvre_calibration`
already place the GEO watch floor at 100 m/s, with that reasoning cited in the
module. This recommendation is already satisfied, in the right place.

Recording it here so it is not "fixed" later by someone matching on the number.

## Part 5: what the assessment says we cannot do

● **Military and Chinese or Russian ΔV figures are lower bounds.** The
  assessment marks its own confidence as low: these are inferred from tracked
  orbit changes using impulsive two-body approximations, which is precisely what
  SPECTRE does. Our figures inherit that limit and should be presented as lower
  bounds, not measurements.
● **Platform ceilings are rocket-equation estimates, not published budgets.**
  The assessment marks them moderate confidence. Any SPECTRE verdict that turns
  on a platform ceiling carries that uncertainty and should say so.
● **LEO drag, SSO and MEO station-keeping figures are secondary reproductions**
  of SMAD-style tables and are indicative. The MEO figure in particular has no
  authoritative source. A capability assessment that leans hard on the 1 m/s/yr
  MEO number is leaning on the weakest row in the assessment.
● **Electric propulsion makes the impulsive assumption wrong, not imprecise.**
  A months-long electric transfer is not a burn with a date. Both SPECTRE's
  estimators assume an impulse. Where the platform is known to be all-electric
  the burn epoch the drill-down reports is the midpoint of a campaign, and the
  panel should not present it as an instant.
