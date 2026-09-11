# Red team: is the threat sweep operationally beneficial?

Question asked: when the sweep and intercept analysis completes, is the result
actually useful to an orbital warfare analyst?

Assessed against the code as it stands after the calculation audit, so the
arithmetic underneath is now sound. This is about the analysis, not the maths.

## Verdict

**The sweep answers a question nobody asked, and labels it as the answer to the
question they did ask.**

It computes the cheapest geometric path between two objects and calls the
result an adversary capability assessment. Those are different things. A low
delta-V figure means the orbits happen to be conveniently arranged; it says
nothing about whether the object at the other end can or would fly it.

The underlying machinery is genuinely good and worth keeping: multi-method,
multi-epoch, regime-filtered, fast, and now numerically correct. The defect is
in the interpretation layer, which is thin, and in what the interface asserts
on the strength of it.

Six findings, in order of how much they would change an analyst's decision.

## 1. The threat level measures the geometry, not the adversary

The entire verdict is four thresholds on one number:

```
dv < 0.2 km/s  ->  CRITICAL
dv < 0.5 km/s  ->  HIGH
dv < 1.0 km/s  ->  MEDIUM
otherwise      ->  LOW
```

Nothing else enters. Not the object's propellant, not its mass, not its
demonstrated manoeuvre history, not whether it has ever manoeuvred at all. The
summary line nonetheless reads "Adversary capability assessment - intercept is
critical threat."

**The application already holds the data that would fix this and does not use
it.** `spectre/data/adversary_intel.json` carries 44 per-object records with
`assessed_threat`, `threat_level` and `status`, drawn largely from published
counterspace assessments. `get_intel` is called, but only
to populate a display panel. The verdict ignores it.

So the interface can show two contradictory threat levels side by side. Worked
example from the shipped data: **Kowsar** and **Kowsar-1.5** are assessed
`LOW` / `Degraded`. A degraded satellite in a nearby orbit still has a cheap
geometric path to a co-orbital target, so the sweep will score it `CRITICAL`
while the intelligence panel next to it says `LOW / Degraded`. Nothing
reconciles them and nothing tells the analyst which to believe.

This is the finding to fix first. It is also the cheapest: the data is loaded,
the join exists, only the scoring function needs to consult it.

## 2. Ranking ignores time, which is the currency the analyst actually spends

Everything is sorted on delta-V alone - entries, groups and the headline:

```python
entries.sort(key=lambda e: e.delta_v_km_s)
```

Time of flight is computed, displayed as a label, and never ranked on.

For a defender, warning time is the decision. An intercept costing 0.45 km/s
that arrives in 35 minutes is a far harder problem than one costing 0.12 km/s
that takes 40 hours, because in the second case you have two days to attribute,
consult, manoeuvre or accept. The sweep ranks the second above the first and
calls it the greater threat.

The operational quantity is not "how cheap" but "how little time would I have".
A ranking on time-to-closest-approach, with delta-V as the feasibility filter
it already is, would invert several of these judgements.

## 3. The epoch labels are meaningless in the regime the tool exists for

The sweep burns at five epochs: now, apogee, perigee, ascending node,
descending node, and reports the winner's `burn_location` prominently.

Measured against a representative station-kept GEO object (eccentricity
0.00016, inclination 0.05 degrees): apogee and perigee are **13.3 km apart on a
42,164 km orbit**, and the nodes are defined by a twentieth of a degree of
inclination. The four "locations" resolve to four arbitrary times spread across
a day - 13:07, 17:43, 01:07, 05:41.

Sampling four times across a day is useful. Labelling them apogee and perigee
is not, because it implies an energy-optimal choice that does not exist at
e = 0.0002. An analyst reading "cheapest intercept burns at perigee" will infer
a reasoning that is not there.

What actually varies between those epochs is the **phase angle to the target**,
which is the dominant term in a co-orbital intercept and is never named
anywhere in the output. The tool surfaces the label and hides the cause.

## 4. "Intent" is the solver's name in different words

```python
_sweep_intents = {
    "hohmann": "Orbital Transfer - Energy Change",
    "lambert": "Close-Proximity Operation",
    "phasing": "Phasing Rendezvous",
    ...
}
```

This is a static dictionary from method name to prose. No behaviour is
examined, no history, no comparison against a pattern of life. "Lambert" means
the Lambert solver won the delta-V comparison; it is rendered as "Close-
Proximity Operation", which reads like an inference about what the adversary is
doing.

The application has a real pattern-of-life module and a manoeuvre classifier.
Neither informs this label.

## 5. Every method failure is silent, including the ones that matter most

Each of the eight methods is wrapped:

```python
try:
    sol = phasing_intercept(...)
    ...
except Exception:
    pass
```

An infeasible method dropping out is correct. But the analyst cannot
distinguish "this method was tried and is not viable" from "this method threw".
Nor can they see that a method was attempted at all.

The asymmetry matters because **the cheapest option is the one most likely to
be refused**. A degenerate Lambert geometry, now correctly rejected, is exactly
the near-180-degree GEO phasing case. A near-impossible phasing orbit, now
correctly rejected, is the aggressive short-notice one. The refusals cluster on
the high-threat end of the distribution, so silent dropping biases the sweep
towards under-reporting the fastest approaches.

It also means a genuine bug in any method vanishes without trace, which is how
the Lambert defect survived as long as it did.

## 6. Precision is overstated, modestly

The interface prints delta-V to four decimal places of km/s, a tenth of a metre
per second.

I measured what TLE uncertainty does to that figure, for a co-orbital GEO
intercept over six hours:

| TLE position error | Spread in reported delta-V |
|---|---|
| 0.5 km | 0.11 m/s |
| 2 km | 0.42 m/s |
| 5 km | 1.08 m/s |
| 20 km | 4.60 m/s |

This is less damaging than I expected, and I am recording that rather than
overstating it: at a realistic few-kilometre TLE error the answer is good to
about 1 m/s, so the last one or two decimal places are noise rather than the
last four. The thresholds are 300 m/s apart, so category flipping from this
cause is not a real risk.

Worth fixing as presentation - three decimals, or a figure with a band - but it
is the smallest finding here, not the headline.

## What the sweep does well, and should keep

● It enumerates eight transfer methods across five epochs rather than assuming
  one. That breadth is the right instinct and most tools do not do it.
● `regimes_compatible` filters physically implausible pairings before any
  solving, which is a real piece of judgement encoded correctly.
● It is fast enough to run against 100 targets interactively.
● It already joins to per-object intelligence. The plumbing for finding 1 is
  three-quarters built.

## What an analyst actually needs from this screen

The sweep currently answers: *what is the cheapest way from A to B?*

The question an orbital warfare analyst is holding is closer to: *given what
this object is and what it has done before, how much warning would I get, and
what would I have to decide by when?*

Concretely, and in priority order:

1. **A capability-conditioned score.** Combine the geometric cost with the
   object's assessed status and known manoeuvre history. A cheap intercept by a
   degraded satellite is not a critical threat, and the data to say so is
   already loaded.
2. **Rank on warning time**, with delta-V as the feasibility filter it already
   is. Surface "earliest credible arrival" as the headline number.
3. **Name the phase angle**, since it is what actually drives the answer, and
   drop or qualify the apsis labels in near-circular regimes.
4. **Show what was tried and refused**, with the reason. A method that refuses
   because the geometry is degenerate is informative; silence is not.
5. **Separate the two threat levels explicitly** - "geometric accessibility"
   and "assessed intent" - rather than letting one word carry both and
   contradict itself on screen.
6. **Report delta-V to three decimals or with a band**, derived from TLE age.

## One structural observation

The most valuable thing in this application is not any single calculation. It
is that it already holds, in one place, the orbital dynamics, the object
intelligence, and the pattern of life. Almost nothing on the market joins those
three.

The sweep currently uses one of them and displays a second. The gap between
what the application knows and what its headline verdict consults is where the
capability actually is.
