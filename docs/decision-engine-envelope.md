# Decision Engine: the operating envelope

*Written for SPC-200, evaluation finding F-09 (Critical, gate G10), with SPC-216 (F-30) and SPC-217 (F-31), and for
SPC-201 (F-25 and F-34, gate G9). It closes F-29, deep-space orbits evaluated with no regime statement, in part: such
an orbit is flagged, and the limits sourced for it are SPC-215. It states the conditions the Decision Engine is fit for, where in the code each is
enforced, and what lies outside. It is linked from docs/decision_engine_phases.md, which describes the engine as
built. Gates G9 and G10 were rated Red; those ratings stand until the evaluation is repeated.*

## What the envelope is

The engine answers one question: given what red might do next, which of our responses holds up best, and what each
figure behind that ranking rests on. It gives an honest answer only inside the conditions below. Each condition is
checked where its input enters: an element set when it is stored and again when it is bound, a panel number when the
form is read, a row when it is planned, and the bound element sets once more at evaluation entry. Outside a
condition the engine does one of two things, and says which in a sentence:

● **Refuses**, where it cannot give an honest answer: nothing is stored, nothing runs, or the figure falls back to a
  lookup marked as one, and the sentence names what failed.
● **Flags**, where the answer stands but rests on a rule not validated for the case: the figure is shown, and a
  sentence under "Outside the operating envelope" on the result says why it may be misstated.

`tests/unit/test_decision_engine_envelope.py` holds every row of the tables below to the code: the constant or
function named is at the place named, and a value given is the value the code holds.

## Element sets: what the engine accepts

Every element set passes one acceptance check before anything stores it, on every path it enters by, and again when
a scenario binds it (SPC-201). A set that fails is refused whole: it is not stored, it never replaces a set already
held, the refusal is logged without the set's text, and the operator is shown a sentence naming the object and what
failed. A set fetched for a catalogue number must also be for that number: an answer for another object is refused.

The paths with a page of their own show the sentence on it: the UDL fetch every UDL route shares, the TLE form,
quick-add of a red track or a blue asset, the background refresh at UDL connect, the operator's own pasted sets, the
sweep's manual targets, its manual red set and the screen's manual asset, the sweep's group pre-fetch, target fetch
and actor refresh, and the Pattern of Life panel, whose history also feeds custody, the burn-normality verdict and the
sweep. The paths with no page of their own say it in the operator's run log: the UDL history fetch behind the
clustering, the HRR watchlist fetched from UDL, the history held for the sweep and custody, the training objects, and
the bundled watchlist at start-up, which no operator is signed in to see, so each new session's run log carries it.
The bundled watchlist, `spectre/data/hrr_default.json`, passes in full.

| Dimension | Fit for | Enforced at | Value | Outside it |
|---|---|---|---|---|
| The two element lines | Line 1 then line 2, each beginning with its line number and a space, each 69 characters long, in plain ASCII, each with a good modulo-10 checksum in its last column | `spectre/astro/elset_check.py` `check_elset` | none | Refused: a set with one digit changed in transit, as evaluation probe P-14 sent, fails its checksum; a Unicode digit is refused, not read |
| Line length | Every element line is this many characters | `spectre/astro/propagator.py` `TLE_LINE_LENGTH` | `69` | Refused, naming the line and its length |
| Catalogue number | One number on both lines, 5 digits or an Alpha-5 letter and four digits, and the number asked for when a set is fetched for one | `spectre/astro/catalogue.py` `catalogue_number` | none | Refused: blank, unreadable, differing between the lines, or another object's |
| Epoch | A date: day 1 to the last day of its year, 365, or 366 in a leap year | `spectre/astro/elset_check.py` `tle_epoch` | none | Refused: the epoch cannot be read |
| Fields in the format's own characters | Every field the check reads is written as the format writes it: digits, one decimal point and a sign where the format has one. The checksum counts a letter as 0, so a 0 changed to e or X keeps it good, and float() would read the field as an exponent, inf or nan | `spectre/astro/elset_check.py` `_DECIMAL` | none | Refused, naming the field: it cannot be read |
| Drag fields: B*, and the first and second derivatives of the mean motion | Each readable in its published format; no range is checked, since none is sourced | `spectre/astro/elset_check.py` `_DRAG` | none | Refused when one cannot be read: SGP4 read an unreadable B* as inf or nan, started without an error and propagated every position to NaN |
| Inclination | 0 to 180 degrees | `spectre/astro/elset_check.py` `_ANGLES[0]` | none | Refused: an inclination of 597.4 degrees, accepted before (F-34), is outside it |
| Right ascension of the node, argument of perigee, mean anomaly | 0 to 360 degrees each | `spectre/astro/elset_check.py` `_ANGLES` | none | Refused, naming the field and its value |
| Eccentricity | 0 to under 1: 7 digits after an implied decimal point | `spectre/astro/elset_check.py` `_ECCENTRICITY` | none | Refused: the field cannot be read |
| Mean motion | Above 0 revolutions a day, and finite | `spectre/astro/elset_check.py` `_MEAN_MOTION` | none | Refused: not above 0, or cannot be read |
| Ephemeris type | 0, SGP4, the only type the propagators here read: the UDL record's ephemType when it carries one, else line 1 column 63, a blank read as 0 | `spectre/astro/elset_check.py` `_SGP4_TYPE` | `0` | Refused, naming the type: a type 4 set is SGP4-XP, whose line 1 fields carry other terms, and SGP4 propagates it without an error to a wrong orbit. Every path refuses it, the UDL history included; the log counts what was skipped by type and provider, without the set's text |
| Correlated to the object | A set UDL has correlated to the object it is filed under | `spectre/astro/elset_check.py` `_is_uct` | none | Refused: a record whose uct flag is true is an uncorrelated track. When the newest set a fetch answers with is refused for this or for its type, the page says so and no older set is taken in its place |
| An orbit SGP4 can start from | Once every field is in its range, SGP4 starts from the set with no error of its own | `spectre/astro/propagator.py` `TLEOrbit.init_error` | none | Refused, naming SGP4's error: fields each in range can still describe an orbit inside the Earth, such as 20 revolutions a day |
| A set held before the check, or by any other route | Checked again when a scenario binds it | `spectre/web/decision_binding.py` `bind_scenario` | none | Refused beside the form: nothing is bound |

## Regimes

| Dimension | Fit for | Enforced at | Value | Outside it |
|---|---|---|---|---|
| Near-Earth orbits | A period under about 225 minutes, propagated by SGP4's near-Earth branch; the library makes the switch itself | `spectre/astro/propagator.py` `DEEP_SPACE_PERIOD_MIN` | `225.0` | Flagged, not refused (F-29). A GEO set on SDP4, SGP4's deep-space branch, carries a sentence that its staleness limit and its element-set error model are the GEO rules of thumb, tuned rather than sourced. Any other set on SDP4 (HEO, Molniya-class, GTO, MEO over the switch, or beyond GEO) carries a sentence that they are rules of thumb set for LEO and GEO, not validated for that orbit. Its figures stand. Limits sourced for it are SPC-215 |
| The deep-space flag | One sentence per bound set on SDP4 that is not a GEO set, red first. Since SPC-202 the error model also sets every sample's draw, every computed band and the closest approach and score that read them, and the sentence says so; a record of 0.28.0 to 0.31.0 keeps the sentence it showed | `spectre/domain/decision_envelope.py` `DEEP_SPACE_ELSET` | none | Shown under "Outside the operating envelope" on the result |
| The GEO flag | One sentence per bound GEO set, red first: GEO as `regime_from_tle` reads it, the regime its limit and error model are chosen by. Since SPC-202 it says the error model also sets the draws, the bands, the closest approach and the score; a record of 0.28.0 to 0.31.0 keeps the sentence it showed | `spectre/domain/decision_envelope.py` `DEEP_SPACE_GEO_ELSET` | none | Shown under "Outside the operating envelope" on the result |
| In orbit | Above the re-entry floor at every instant searched, on both propagators | `spectre/astro/monte_carlo.py` `REENTRY_FLOOR_KM` | `100.0` | Refused: a sampled row below it refuses itself (RK45); the computed search refuses the pair, every computed cell says so, and the result says it once (SGP4, F-30). Probe P-14's decayed object, between two of SGP4's perigee errors, gave "Computed: 643.1 km"; it now gives no computed figure |
| SGP4's own decay error | Read as the same re-entry, so the result says the object has decayed whether the search meets this error or the floor first | `spectre/astro/propagator.py` `SGP4_DECAYED` | `6` | Refused as decayed, with the decayed flag; any other SGP4 error is refused as a propagation failure |
| The decayed flag | One sentence, naming the side and the set | `spectre/domain/decision_envelope.py` `DECAYED` | none | Shown under "Outside the operating envelope" on the result |

## Element-set ages

| Dimension | Fit for | Enforced at | Value | Outside it |
|---|---|---|---|---|
| Age, every other regime, h | An element set no older than this at evaluation, in every regime but GEO and DEEP: LEO, MEO, HEO, GTO and Molniya-class, whether on SDP4 or not | `spectre/config/constants.py` `TLE_FILTER["staleness_warn_leo_h"]` | `24` | Refused: nothing is computed or sampled from it, and the span searched ends where it passes the limit |
| Age, regimes GEO and DEEP, h | The same, for the slow regimes as `regime_from_tle` names them: GEO, and DEEP, a perigee beyond GEO. Not every orbit on SDP4 | `spectre/config/constants.py` `TLE_FILTER["staleness_warn_geo_h"]` | `72` | The same |
| A burn before its element set | A hypothesised burn after the bound red set's epoch | `spectre/domain/decision.py` `plan_sampling` | none | Refused: the set may already contain the burn |

## Horizons, budget and cost

| Dimension | Fit for | Enforced at | Value | Outside it |
|---|---|---|---|---|
| Horizon, h | Above 0 and at most this | `spectre/web/routes/decision.py` `_MAX_HORIZON_H` | `720.0` | Refused beside the form |
| Evaluation budget, s | One sampled evaluation's wall time | `spectre/domain/decision.py` `EVALUATION_BUDGET_S` | `300.0` | What the budget leaves out is refused by name, and the result says the budget ran out |
| Cost cap, sample-hours | A sampled row within it | `spectre/domain/decision.py` `MAX_SAMPLE_HOURS` | `12000.0` | Refused before it runs, naming the longest horizon that would fit |

## Scenario sizes and turns

| Dimension | Fit for | Enforced at | Value | Outside it |
|---|---|---|---|---|
| Rows on each side | 1 to this many adversary actions, and 1 to this many friendly responses | `spectre/web/routes/decision.py` `_MAX_ROWS` | `5` | Refused beside the form |
| Samples per hypothesis on the panel | From 100 to 2,000 | `spectre/web/decision_from_sweep.py` `MAX_SAMPLES` | `2000` | Refused beside the form |
| Fewest samples for a sampled row | At least this many | `spectre/astro/monte_carlo.py` `_MIN_CONVERGENCE_SAMPLES` | `50` | The row is refused and its cells are lookups |
| Burns in a transfer | At most this many | `spectre/domain/decision_transfer.py` `MAX_TRANSFER_BURNS` | `8` | Refused |
| One burn, m/s | At most this | `spectre/domain/decision_transfer.py` `MAX_BURN_M_S` | `1000.0` | Refused |
| Turns | 1 to this many | `spectre/domain/decision.py` `MAX_TURNS` | `3` | Refused beside the form |
| Branches in a game tree | At most this many | `spectre/domain/decision_tree.py` `MAX_TREE_BRANCHES` | `1000` | Refused before it runs, naming the largest depth that would fit |

## Inputs

| Dimension | Fit for | Enforced at | Value | Outside it |
|---|---|---|---|---|
| The weights | Each from 0 to 1, and not all 5 at 0 | `spectre/web/routes/decision.py` `_WEIGHTS_ALL_ZERO` | none | Refused beside the form: every score would be 0 and no rule could pick on them (F-31) |
| P under expected value | At least one row above 0 | `spectre/domain/decision.py` `find_robust_response` | none | Expected value has no pick, and the result says so since every row has P 0 (F-31). When expected value is the rule chosen, nothing is starred. The headline reads "No recommendation" only when expected value is the deployment's primary rule; otherwise the headline shows the primary rule's pick and says expected value has none. Minimax and minimin, which read no probability, still pick |
| Keep-out distance, km, least | At least this | `spectre/domain/decision.py` `MIN_KEEP_OUT_KM` | `0.1` | Refused beside the form |
| Keep-out distance, km, greatest | At most this | `spectre/domain/decision.py` `MAX_KEEP_OUT_KM` | `10000.0` | Refused beside the form |
| Hypothesis start, km | Within this of the bound red track | `spectre/domain/decision.py` `START_TOLERANCE_KM` | `10.0` | The row is refused |
| P, Conf, cost, reversibility | Each from 0 to 1 | `spectre/web/routes/decision.py` `_parse` | none | Refused beside the form |

## What lies outside the envelope altogether

The engine is not fit for these, and does not claim to be. None is checked, because none is an input the operator
gives; each is said on the result or in docs/decision_engine_phases.md where it bears on a figure. The limits on
turns and rows above are checked and refused, so they are not repeated here.

● **Element-set error across track is not drawn.** Since SPC-202 every sample draws each object's element-set error
  along track, and a computed miss carries a band of both sets' error in quadrature, from the threat sweep's rule of
  thumb, tuned, not sourced; a radial or cross-track part is not drawn, and the model is not validated for any regime.
● **Third bodies are not modelled.** RK45 carries J2 and drag only, so at GEO it parts from SDP4 by 11 to 18 km
  (probe P-13).
● **A sensor's line of sight is not modelled.** Custody is about information, not geometry.
● **Randomised responses are not considered.** Each rule picks one response, never a mix.
● **An object with no element set.** Nothing is computed or sampled for it; its cells are lookups.

## Design decisions in this envelope

These are Claude's choices, not rulings, and await the owner's:
● **The newest set or none.** When the newest element set UDL holds for an object is refused, the fetch is refused:
  an older set from another source is not taken in its place, since the newest is what UDL holds now.
● **All the failures at once.** A refusal names every failure the check finds, after the line numbers and lengths,
  which stop it, since no field is where it should be once they fail.
● **A readable catalogue number.** The check reads the number as the rest of SPECTRE reads it, 5 digits or
  Alpha-5, so two identical sets always share one and the binder's comparison of the sets' text was removed.
● **Checked again at binding.** A set held before the check existed, or stored by a path not yet known, is refused
  when a scenario binds it.
● **Deep space by the library's own switch.** The flag reads SGP4's own choice of SDP4, not a period the code
  computes, so the two cannot disagree; the period shown is from the set's mean motion and is said as "about", since
  the library switches on a slightly different mean motion.
● **GEO in a sentence of its own.** A GEO set is on SDP4, but its limit and error model are the GEO ones: it is
  flagged as resting on the GEO rules of thumb, tuned rather than sourced, not as resting on rules set for another
  orbit.
● **The fields read as written.** Every field the check reads must match the format's own characters before it is
  read as a number, so a corruption the checksum cannot see is refused. The drag fields are checked as readable, with
  no range, since none is sourced; a B* that reads but is absurd is not refused.
● **The number asked for.** A set fetched for one catalogue number and answered for another is refused, so a sound
  set for the wrong object never replaces a held one.
● **SGP4 sets only.** An SGP4-XP set is well formed and SGP4 starts from it, so no other test catches it; the check
  reads its ephemeris type, and refuses an uncorrelated track by the UDL record's own flag. The newest set is still
  the one fetched: when it is refused for its type, nothing is stored and the operator is told, rather than an older
  set of another provider being taken without a word.
● **The columns stored are the columns checked.** The Pattern of Life parser keeps each line to its 69 columns, so
  it checks those, and text past column 69 is cut, not a reason to refuse.
● **The run log where there is no page.** Paths with no page of their own, and the start-up load, which no operator
  is signed in to see, say each refusal in the run log.
● **All-zero weights refused only at the panel.** A scenario built in code, or replayed from a record, with every
  weight at 0 is not refused by the engine, so a record written before this check replays as it was recorded.
