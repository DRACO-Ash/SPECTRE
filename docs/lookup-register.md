# Lookup register

*Built for SPC-196, evaluation finding F-05 (Critical, gate G5). Every numeric constant in the Decision Engine's own
modules, and every lookup and rule of thumb it reads from other modules to set a figure, a score, a pick or its
advice, with its value, where it is in the code, what it does, its source, who may change it and when it was set.*

A figure the results mark "(lookup)" rests on one or more of the constants below. The values a new panel starts the
operator's inputs at are listed here too, in their own section, so their source and date are known. Once the
operator evaluates with one, set or kept, the result marks it "(judgement)" under "Judgement inputs": the form
records no edit of these, so a value kept where the panel started it is the operator's judgement as much as one
typed in, and its note names where a new panel starts it. P is the exception: the form records whether it was edited
(SPC-183), so a P never edited is marked "(lookup)", the panel's default below. A delta-V budget left blank is the
default below, which the operator kept by leaving it blank, and is marked "(judgement)" with that note.

## How to read it

● **Value** is the constant's value exactly as the code holds it, written as a Python literal. A table keyed by an
  enumeration names each key as the enumeration's class and member, as in `"ActionType.MANOEUVRE"`. A record, such
  as an archetype, is written as a table of its numeric fields.
● **Where** names the file and the constant's name in it: a module constant, a class attribute such as
  `Scenario.w_custody` (a field's default), or an entry of a table such as `TLE_FILTER["staleness_warn_geo_h"]`.
● **Source** is the published or measured basis for the value, or "none: rule of thumb" where there is none.
● **Owner** is who may change it. "Unassigned" means no owner is recorded. Where the owner has ruled on a value,
  the ruling is named with its date, from `.board/README.md`. A value that is Claude's choice says so, and is not
  a ruling.
● **Set** is the date the value was set, from `git log`, with the commit, and the release where that is how it
  was introduced. A value carried over from an earlier file keeps its first date. A value first named in SPC-196 was
  a bare number or a panel field before; its date is the number's.

## The rule the register is held to

`tests/unit/test_lookup_register.py` reads every row of the tables below and fails when:
● a constant named here is no longer in the code at the place named;
● its value in the code differs from the value here, so a change to the code without a change to the register
  fails, and so does a change to the register alone;
● one of the Decision Engine's own modules gains a module-level numeric constant this register does not list. They
  are `decision.py`, `decision_tree.py`, `tree_selectors.py`, `turn_update.py`, `rule_comparison.py`,
  `decision_inputs.py`, `decision_replay.py`, `decision_figures.py`, `decision_transfer.py`,
  `decision_judgement.py`, `decide_by.py`, `notso_prior.py` and `decision_envelope.py`, all in `spectre/domain/`. A constant is numeric
  when it is a number (not a truth value), or a non-empty table, tuple, list or set whose every value is numeric in
  turn, so a table of tuples of numbers counts. A name assigned alone, annotated, or unpacked from a tuple is read
  alike. Every such constant is listed, including limits and unit conversions, in the section it belongs to, so none
  can arrive unseen;
● the lookup model's own functions, `_lookup_figures` and `_lookup_cell` in `decision.py`, hold a bare number other
  than 0 and 1, so its rules of thumb stay named constants this register holds;
● a field of the panel, or a weight of the route's form, starts at a value other than the constant listed for it
  below;
● a row leaves its source, owner or date empty.

Constants of other modules are listed where the engine reads them to set a figure, a score, a pick or its advice,
and are held to their value, but a new constant in those modules is not caught by the completeness check. The Threat
Understanding model's own weights, caps and half-lives are not listed: the engine reads its output, a band and an
Understanding with their bases, not those constants, except the ones below that it shows or acts on.

## Lookups and rules of thumb that set a figure, a score, a pick or the advice

| Constant | Value | Where | What it does | Source | Owner | Set |
|---|---|---|---|---|---|---|
| Lookup closest approach per adversary action type, km | `{"ActionType.NO_ACTION": 5000.0, "ActionType.MANOEUVRE": 200.0, "ActionType.SENSOR_RETASK": 10000.0}` | `spectre/domain/decision.py` `_BASE_CA_KM` | The closest approach of an unbound cell, or of a bound cell nothing computed or sampled, by red's action type | none: rule of thumb | unassigned | 2026-04-06 (f73ba47), as a table since 2026-11-03 (45d79c9, 0.13.0) |
| Lookup closest approach of any other action type, km | `3000.0` | `spectre/domain/decision.py` `_OTHER_CA_KM` | The same, for a posture change | none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Closest-approach multiplier for a manoeuvre response | `5.0` | `spectre/domain/decision.py` `_MANOEUVRE_CA_PER_COST` | Raises a lookup closest approach to x(1 + 5 x cost) against our manoeuvre | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Closest-approach multiplier for a posture change | `2.0` | `spectre/domain/decision.py` `_POSTURE_CA_PER_COST` | Raises a lookup closest approach to x(1 + 2 x cost) against our posture change | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Lookup delta-V per unit of cost, km/s | `0.05` | `spectre/domain/decision.py` `_LOOKUP_DV_KM_S_PER_COST` | Our delta-V for a manoeuvre with no sized burn: cost x 0.05 km/s, 0 to 50 m/s | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Sensor-retask custody gap, share of its time to execute | `0.5` | `spectre/domain/decision.py` `_RETASK_GAP_SHARE` | Against a manoeuvre, a sensor retask holds custody with a gap of half its time to execute | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Lookup time to closest approach, share of the horizon | `0.4` | `spectre/domain/decision.py` `_LOOKUP_TCA_SHARE` | The time to closest approach of a lookup cell | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Closest approach scale, far anchor, km | `50_000.0` | `spectre/domain/decision.py` `_CA_NORMALISATION_KM` | A miss at or beyond it scores no closest-approach penalty | none: rule of thumb, kept from before SPC-191 | unassigned | 2026-04-06 (f73ba47) |
| Our delta-V scale, full penalty, m/s | `1000.0` | `spectre/domain/decision_transfer.py` `MAX_BURN_M_S` | Our delta-V scores its full penalty at the engine's per-burn limit, and a later burn above it is refused | none: the limit on burn 1's own field | unassigned | 2026-11-10 (6b87a96, 0.25.0) |
| Degraded custody weight | `0.25` | `spectre/domain/decision.py` `DEGRADED_CUSTODY_WEIGHT` | An hour of degraded custody carries this share of the penalty an hour lost carries | none: a ruling, not a sourced figure | the owner: ruling of 2026-11-05, scored between held and lost (SPC-179) | 2026-11-10 (6b87a96, 0.25.0) |
| Action line | `"Band.HIGH"` | `spectre/domain/threat_understanding.py` `ACTION_LINE` | The Threat band at which the recommended response changes; the collect-first advice is judged against it | none: tuned, not sourced | unassigned; the code calls it the operator's to set, and no control sets it yet | 2026-11-04 (91166bc, 0.19.0) |
| Default response time, h | `12.0` | `spectre/domain/decide_by.py` `DEFAULT_RESPONSE_H` | Decide-by is the soonest credible arrival less this, until the operator sets their own | none: rule of thumb | unassigned (Claude's choice of 2026-11-03, recorded in the owner rulings as not a ruling) | 2026-11-02 (6d33839, 0.10.0) |
| Cap on a manufacturable item, and on a NOTSO Conf | `0.3` | `spectre/domain/threat_understanding.py` `MANUFACTURABLE_CAP` | The most a claim the adversary controls is worth; Conf from NOTSO is capped at it | none: tuned, not sourced | unassigned | 2026-11-03 (9296f9d, 0.16.0) |
| Fewest NOTSO events for a P | `3` | `spectre/domain/notso_prior.py` `MIN_EVENTS` | No P is offered from fewer events | none: tuned, not sourced | unassigned | 2026-11-04 (e325bd8, 0.21.0) |
| Collect-first time, holding conjunctions, h | `0.25` | `spectre/domain/threat_understanding.py` `_CONJUNCTION_HOURS` | How long that collection is taken to need; the engine shows it as a lookup and advises collecting first only when it ends by decide-by | none: tuned, not sourced | unassigned | 2026-11-04 (0166b68, 0.18.0) |
| Collect-first time, a catalogue entry, h | `0.25` | `spectre/domain/threat_understanding.py` `_GCAT_HOURS` | The same, for pulling a catalogue entry | none: tuned, not sourced | unassigned | 2026-11-04 (0166b68, 0.18.0) |
| Collect-first time, an element-set history, h | `0.5` | `spectre/domain/threat_understanding.py` `_HISTORY_HOURS` | The same, for one more history query | none: tuned, not sourced | unassigned | 2026-11-04 (0166b68, 0.18.0) |
| Collect-first time, dating and sourcing a record, h | `4.0` | `spectre/domain/threat_understanding.py` `_RECORD_HOURS` | The same, for an analyst to date and source a record | none: tuned, not sourced | unassigned | 2026-11-04 (0166b68, 0.18.0) |
| Wilson interval z for a NOTSO P | `1.96` | `spectre/domain/notso_prior.py` `_WILSON_Z` | Sets the 95 in 100 interval about a NOTSO P | definition: the normal quantile for 95 in 100 | the owner: ruling of 2026-11-05 to keep the exact 95 in 100 interval (concept decisions 17 and 18) | 2026-11-04 (e325bd8, 0.21.0) |
| Tail share of the exact NOTSO interval | `0.025` | `spectre/domain/notso_prior.py` `_TAIL` | Each tail of the exact Poisson interval that expected value's pick is checked across | definition: 95 in 100 in all | the owner: ruling of 2026-11-05 to keep the exact 95 in 100 interval (concept decisions 17 and 18) | 2026-11-04 (5a702cb, 0.22.0) |
| Archetype Station Keeping: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.002, "delta_v_1sigma_fraction": 0.1, "pointing_1sigma_deg": 1.0, "timing_1sigma_seconds": 10.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["station_keeping"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 3; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Archetype Orbit Raise: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.05, "delta_v_1sigma_fraction": 0.05, "pointing_1sigma_deg": 2.0, "timing_1sigma_seconds": 30.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["orbit_raise"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 4; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Archetype Plane Change: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.1, "delta_v_1sigma_fraction": 0.05, "pointing_1sigma_deg": 3.0, "timing_1sigma_seconds": 60.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["plane_change"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 4; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Archetype Phasing Manoeuvre: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.01, "delta_v_1sigma_fraction": 0.08, "pointing_1sigma_deg": 2.0, "timing_1sigma_seconds": 20.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["phasing"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 4; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Archetype Intercept / Approach: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.2, "delta_v_1sigma_fraction": 0.03, "pointing_1sigma_deg": 1.5, "timing_1sigma_seconds": 15.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["intercept_approach"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 4, its worked example; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Archetype Evasive Manoeuvre: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.002, "delta_v_1sigma_fraction": 0.15, "pointing_1sigma_deg": 5.0, "timing_1sigma_seconds": 120.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["evasive"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 4, above a debris avoidance burn; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47); its delta-V corrected from 30 to 2 m/s on 2026-10-13 (9c5f214, 0.5.15) |
| Archetype Repositioning: typical delta-V, km/s, and its spreads | `{"typical_delta_v_km_s": 0.08, "delta_v_1sigma_fraction": 0.05, "pointing_1sigma_deg": 2.0, "timing_1sigma_seconds": 30.0}` | `spectre/astro/monte_carlo.py` `MANOEUVRE_ARCHETYPES["repositioning"]` | An archetype hypothesis burns its typical delta-V, and a hypothesis that names it is sampled with its delta-V, pointing and timing spreads | typical delta-V: the Space Watch paper of 13 October 2026, Table 4; spreads: none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |

## Where a new panel starts the operator's inputs

Each is a value a new panel, or a new row of it, starts at. Evaluated with, set or kept, it is the operator's
judgement and the results mark it so, except a P never edited, marked "(lookup)" as the panel's default.
`tests/unit/test_lookup_register.py` holds the panel's fields and the route's form to these values.

| Constant | Value | Where | What it does | Source | Owner | Set |
|---|---|---|---|---|---|---|
| Starting horizon, h | `72.0` | `spectre/domain/decision.py` `DEFAULT_HORIZON_H` | The horizon a new panel starts at; a panel opened from a sweep starts at the whole hours to red's arrival and one more, up to the longest horizon | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Horizon a scenario takes unless given, h | `72.0` | `spectre/domain/decision.py` `Scenario.horizon_hours` | The same, as the scenario's own default | none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Default weight, custody | `0.35` | `spectre/domain/decision.py` `Scenario.w_custody` | Weights the custody term of every score on a new panel | none: uncited, to be cited under SPC-151 | unassigned | 2026-04-06 (f73ba47) |
| Default weight, closest approach | `0.25` | `spectre/domain/decision.py` `Scenario.w_closest_approach` | Weights the closest-approach term | none: uncited, to be cited under SPC-151 | unassigned | 2026-04-06 (f73ba47) |
| Default weight, our delta-V | `0.2` | `spectre/domain/decision.py` `Scenario.w_dv_cost` | Weights our delta-V term | none: uncited, to be cited under SPC-151 | unassigned | 2026-04-06 (f73ba47) |
| Default weight, time to execute | `0.1` | `spectre/domain/decision.py` `Scenario.w_time_to_exec` | Weights the time-to-execute term | none: uncited, to be cited under SPC-151 | unassigned | 2026-04-06 (f73ba47) |
| Default weight, reversibility | `0.1` | `spectre/domain/decision.py` `Scenario.w_reversibility` | Weights the reversibility term | none: uncited, to be cited under SPC-151 | unassigned | 2026-04-06 (f73ba47) |
| Default keep-out distance, km | `10.0` | `spectre/domain/decision.py` `DEFAULT_KEEP_OUT_KM` | Where closest approach scores its full penalty on a new panel | none: Claude's choice, unsourced | unassigned (Claude's choice, not a ruling) | 2026-11-10 (a222713, 0.26.0) |
| Default probability | `0.5` | `spectre/domain/decision.py` `DEFAULT_PROBABILITY` | The P every row starts at; a row never edited says its P is this default | none: rule of thumb | unassigned; the owner ruled on 2026-11-05 that a P never edited reads as this default and a deliberate 0.5 as the operator's own (SPC-183) | 2026-11-04 (91166bc, 0.19.0) |
| Starting Conf of a row | `0.7` | `spectre/domain/decision.py` `DEFAULT_CONFIDENCE` | The Conf a new row starts at; Conf moves no figure | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Default custody gap share | `0.7` | `spectre/domain/decision.py` `DEFAULT_CUSTODY_GAP_FRACTION` | The share of the horizon the rule of thumb loses custody for, on a new row | none: the confidence the page posted by default before SPC-161, kept so a page at its defaults scores as before | unassigned | 2026-11-03 (22196c7, 0.17.0) |
| Starting cost of a response | `0.3` | `spectre/domain/decision.py` `DEFAULT_RESPONSE_COST` | The cost a new response starts at | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Starting reversibility of a response | `0.8` | `spectre/domain/decision.py` `DEFAULT_REVERSIBILITY` | The reversibility a new response starts at | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Starting time to execute of a response, h | `6.0` | `spectre/domain/decision.py` `DEFAULT_TIME_TO_EXECUTE_H` | The time to execute a new response starts at | none: rule of thumb | unassigned | 2026-04-06 (f73ba47); named in SPC-196 |
| Default delta-V budget for our burn, km/s | `0.05` | `spectre/domain/decision_figures.py` `DEFAULT_BUDGET_KM_S` | Our burn is sized within 50 m/s when the operator leaves the budget blank, as the field's placeholder shows | none: rule of thumb | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Default delta-V budget for our burn, as the form reads a blank, m/s | `50.0` | `spectre/web/routes/decision.py` `_DEFAULT_BUDGET_M_S` | The budget a blank field is read as; held equal to the constant above | none: rule of thumb | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Starting samples per hypothesis | `500` | `spectre/web/decision_from_sweep.py` `DEFAULT_SAMPLES` | The samples a new hypothesis row starts at, and the most a sweep fill gives | none: rule of thumb | unassigned | 2026-11-04 (1bffba7, 0.20.0) |

## Limits, tolerances and costs that refuse or bound an evaluation

None of these sets a figure that is shown; each decides whether a figure is computed, sampled or refused.

| Constant | Value | Where | What it does | Source | Owner | Set |
|---|---|---|---|---|---|---|
| Longest veto reason, characters | `500` | `spectre/domain/decision.py` `MAX_VETO_REASON` | A reason for marking a response not permitted longer than this is refused | none: rule of thumb | unassigned (Claude's choice) | 2026-11-11 (0.29.0, SPC-195) |
| Least keep-out distance, km | `0.1` | `spectre/domain/decision.py` `MIN_KEEP_OUT_KM` | A keep-out distance below it is refused | none: finer than any element set is known to | unassigned (Claude's choice) | 2026-11-10 (a222713, 0.26.0) |
| Greatest keep-out distance, km | `10_000.0` | `spectre/domain/decision.py` `MAX_KEEP_OUT_KM` | A keep-out distance above it is refused, so the scale below 50,000 km has room | none: rule of thumb | unassigned (Claude's choice) | 2026-11-10 (a222713, 0.26.0) |
| Evaluation budget, s | `300.0` | `spectre/domain/decision.py` `EVALUATION_BUDGET_S` | The wall time one sampled evaluation may take | the owner's ruling | the owner: ruling of 2026-11-05, raised from 120 s (SPC-178) | 2026-11-10 (6b87a96, 0.25.0) |
| Slowest sampling rate assumed, sample-hours a second | `40.0` | `spectre/domain/decision.py` `_SLOWEST_SAMPLE_HOURS_PER_S` | Sets the cost cap from the budget | measured: about a fifth under the slowest rate measured, 51 | unassigned | 2026-11-03 (02a2a27, 0.14.0) |
| Cost cap, sample-hours | `12000.0` | `spectre/domain/decision.py` `MAX_SAMPLE_HOURS` | A scenario over it is refused before anything runs | derived: the budget times the slowest rate | the owner, through the budget ruling of 2026-11-05 (SPC-178) | 2026-11-03 (02a2a27, 0.14.0); 12,000 since 2026-11-10 (0.25.0) |
| Set-up per sample, s of sample time | `540.0` | `spectre/domain/decision.py` `SET_UP_S_PER_SAMPLE` | Each sample's fixed cost in the cap | measured: fitted over 6 evaluations, rounded up to 9 minutes | unassigned | 2026-11-03 (45d79c9, 0.13.0) |
| Search share of a sample's cost for our burn | `0.3` | `spectre/domain/decision.py` `_BURN_SEARCH_FRACTION` | The cost one more search against a burnt blue arc adds | measured: rounded up from the worst, 29 per cent in LEO | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Start position tolerance, km | `10.0` | `spectre/domain/decision.py` `START_TOLERANCE_KM` | A hypothesis starting further from the bound red track is refused | none: set to catch a frame mix, which differs by 46 km in LEO | unassigned | 2026-11-03 (45d79c9, 0.13.0) |
| Start velocity tolerance, km/s | `0.1` | `spectre/domain/decision.py` `START_VELOCITY_TOLERANCE_KM_S` | A hypothesis starting faster or slower than the bound red track by more is refused | none: coarse on purpose, above the element set's own error | unassigned | 2026-11-03 (02a2a27, 0.14.0) |
| Sum of P read as 1 | `1e-09` | `spectre/domain/decision.py` `P_SUM_TOLERANCE` | The rows' P may sum this far above 1 and be read as 1, the rounding of adding fractions; above it the panel and the scenario refuse them. A remainder of P this small or smaller adds no remainder row | definition: floating-point rounding, as the brief for SPC-203 set it | unassigned (set by the SPC-203 brief, not a ruling) | 2026-11-11 (SPC-203, not yet released) |
| Most turns in a game tree | `3` | `spectre/domain/decision.py` `MAX_TURNS` | A depth above it is refused | none: a fourth turn multiplies the branches past one evaluation | unassigned; the owner ruled on 2026-11-05 to keep the tree's design (D1, D2, D4, D5, D7 to D13) | 2026-11-04 (d1aac06, 0.23.0) |
| Most branches in a game tree | `1_000` | `spectre/domain/decision_tree.py` `MAX_TREE_BRANCHES` | A tree with more is refused before it runs | none: rule of thumb | the owner: ruling of 2026-11-05 to measure trees and set their own cap (SPC-188), not yet built | 2026-11-04 (d1aac06, 0.23.0) |
| Most sizing trials for our burn | `16` | `spectre/astro/response_burn.py` `MAX_SIZING_TRIALS` | Bounds the search that sizes our burn | derived: two senses, 6 doublings and 7 halvings | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Sizing tolerance, share of the size | `0.01` | `spectre/astro/response_burn.py` `_SIZE_TOLERANCE` | The search stops once the size is known to 1 per cent | none: rule of thumb | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Convergence tolerance, km | `1.0` | `spectre/astro/monte_carlo.py` `CONVERGENCE_TOLERANCE_KM` | P5, P50 and P95 must each be known to within this, or the relative tolerance where wider | none: the precision the panel shows | unassigned | 2026-10-26 (c74c5ba, 0.6.0) |
| Relative convergence tolerance | `0.05` | `spectre/astro/monte_carlo.py` `MISS_TOLERANCE_FRACTION` | Converged within 5 per cent of P5 where that is wider than 1 km | measured: the cases it admits sit at 0.5 to 3.4 per cent | unassigned | 2026-11-03 (2f66097, 0.15.0) |
| Fewest samples for convergence | `50` | `spectre/astro/monte_carlo.py` `_MIN_CONVERGENCE_SAMPLES` | A row with fewer samples is refused | none: rule of thumb | unassigned | 2026-10-26 (c74c5ba, 0.6.0) |
| Re-entry floor, km | `100.0` | `spectre/astro/monte_carlo.py` `REENTRY_FLOOR_KM` | A sample below it has re-entered and refuses its row; since SPC-200 an object below it at any instant the SGP4 search reads refuses the computed closest approach, and the result says so | none: rule of thumb | unassigned | 2026-11-03 (45d79c9, 0.13.0); read by the SGP4 path since 2026-11-10 (SPC-200) |
| Deep-space period, min | `225.0` | `spectre/astro/propagator.py` `DEEP_SPACE_PERIOD_MIN` | At or over about this SGP4 propagates a set with SDP4, and the result flags the set: for a GEO set, its staleness limit and error model are the GEO rules of thumb, tuned rather than sourced; for any other orbit on SDP4, rules of thumb set for LEO and GEO, not validated for it (F-29). The library decides the switch itself, from a slightly different mean motion; this names it | definition: SGP4's own switch to SDP4 (Spacetrack Report No. 3, 1980; Vallado and others, 2006) | unassigned (Claude's choice to name it, not a ruling) | 2026-11-10 (SPC-200) |
| Most burns in a transfer | `8` | `spectre/domain/decision_transfer.py` `MAX_TRANSFER_BURNS` | A row carrying more is refused | none: the sweep's longest transfer has three burns | unassigned | 2026-11-10 (6b87a96, 0.25.0) |
| Longest response time, h | `168.0` | `spectre/domain/decide_by.py` `MAX_RESPONSE_H` | A longer response time is refused: past a week, decide-by is a planning horizon, not a decision clock | none: rule of thumb | unassigned | 2026-11-02 (6d33839, 0.10.0) |
| Element-set age limit, regimes GEO and DEEP, h | `72` | `spectre/config/constants.py` `TLE_FILTER["staleness_warn_geo_h"]` | An element set older is out of date: nothing computed or sampled rests on it | none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |
| Element-set age limit, every other regime, h | `24` | `spectre/config/constants.py` `TLE_FILTER["staleness_warn_leo_h"]` | The same, outside GEO and DEEP (a perigee beyond GEO): HEO, GTO and Molniya-class orbits on SDP4 get this limit | none: rule of thumb | unassigned | 2026-04-06 (f73ba47) |

## Units, display and internal guards

None of these is a judgement or a rule of thumb about the world. They are listed so that the register holds every
numeric constant in the Decision Engine's own modules.

| Constant | Value | Where | What it does | Source | Owner | Set |
|---|---|---|---|---|---|---|
| Seconds in a minute | `60` | `spectre/domain/decision.py` `_SECONDS_PER_MINUTE` | Words a picture's age | definition | unassigned | 2026-11-10 (ac64ea7, 0.27.0) |
| Minutes in an hour | `60` | `spectre/domain/decision.py` `_MINUTES_PER_HOUR` | Words a picture's age | definition | unassigned | 2026-11-10 (ac64ea7, 0.27.0) |
| Hours in a day | `24` | `spectre/domain/decision.py` `_HOURS_PER_DAY` | Words a picture's age | definition | unassigned | 2026-11-10 (ac64ea7, 0.27.0) |
| Seconds in an hour | `3600.0` | `spectre/domain/decision.py` `_SECONDS_PER_HOUR` | Converts hours | definition | unassigned | 2026-11-03 (45d79c9, 0.13.0) |
| A tenth of an hour, s | `360.0` | `spectre/domain/decision.py` `_TENTH_HOUR_S` | The step the longest horizon that fits the cap is searched in | definition | unassigned | 2026-11-03 (45d79c9, 0.13.0) |
| Radial, in-track and cross-track | `3` | `spectre/domain/decision.py` `_RIC_AXES` | A direction has three parts | definition | unassigned | 2026-11-03 (b12f805, 0.12.0) |
| Least direction a sampler reads | `1e-15` | `spectre/domain/decision.py` `_MIN_DIRECTION_NORM` | Below it a direction is stored at unit length, so the sampler never assumes in-track unseen | the sampler's own limit | unassigned | 2026-11-03 (b12f805, 0.12.0) |
| Percentiles shown | `(5, 50, 95)` | `spectre/domain/decision.py` `_PERCENTILE_KEYS` | P5, P50 and P95 of a sampled closest approach | definition: the operator reads P5 | unassigned | 2026-11-03 (45d79c9, 0.13.0) |
| Smallest spread shown | `0.00005` | `spectre/domain/decision.py` `_SMALLEST_SHOWN_SPREAD` | A smaller score spread is shown as under 0.0001, never as 0.0000 | display | unassigned | 2026-11-03 (02a2a27, 0.14.0) |
| Finest step a P is shown to | `0.01` | `spectre/domain/decision.py` `_HUNDREDTH` | Rounds the P at which expected value's pick changes | display | unassigned | 2026-11-04 (5a702cb, 0.22.0) |
| Seconds in an hour, for the tree | `3600.0` | `spectre/domain/decision_tree.py` `_SECONDS_PER_HOUR` | Converts hours | definition | unassigned | 2026-11-04 (d1aac06, 0.23.0) |
| Seconds in an hour, for the update | `3600.0` | `spectre/domain/turn_update.py` `_SECONDS_PER_HOUR` | Converts hours | definition | unassigned | 2026-11-04 (d1aac06, 0.23.0) |
| On a turn's boundary, h | `2.7777777777777776e-07` | `spectre/domain/turn_update.py` `_ON_THE_BOUNDARY_H` | A moment within a millisecond of a turn's boundary is on it | definition: burn times are kept to the microsecond | unassigned | 2026-11-04 (d1aac06, 0.23.0) |
| Hundredths, for the update | `100` | `spectre/domain/turn_update.py` `_HUNDREDTHS` | Rounds a P down or up to hundredths for display | display | unassigned | 2026-11-04 (d1aac06, 0.23.0) |
| Stored inputs schema version | `3` | `spectre/domain/decision_inputs.py` `VERSION` | The version of the stored inputs this code writes; version 2 adds each response's veto, version 3 the probability rule and the remainder of P | definition | unassigned | 2026-11-10 (73245d9, 0.28.0); version 2 since 2026-11-11 (0.29.0, SPC-195); version 3 since 2026-11-11 (SPC-203, not yet released) |
| Stored inputs versions read | `(1, 2, 3)` | `spectre/domain/decision_inputs.py` `VERSIONS` | The stored-input versions this code reads, so a 0.28.0 or 0.29.0 record still reads and replays under the rule it was evaluated by | definition | unassigned | 2026-11-11 (0.29.0, SPC-195); version 3 added 2026-11-11 (SPC-203, not yet released) |
| First stored inputs version holding the remainder of P | `3` | `spectre/domain/decision_inputs.py` `_REMAINDER_SINCE` | A document of this version or later holds the remainder of P beside the rows, and the reader checks it is the one the rows leave | definition | unassigned (Claude's choice, not a ruling) | 2026-11-11 (SPC-203, not yet released) |
| Seconds in a minute, for figures | `60.0` | `spectre/domain/decision_figures.py` `_SECONDS_PER_MINUTE` | Words a time | definition | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Seconds in an hour, for figures | `3600.0` | `spectre/domain/decision_figures.py` `_SECONDS_PER_HOUR` | Converts hours | definition | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Slowest closing speed, km/s | `1e-09` | `spectre/domain/decision_figures.py` `SLOWEST_CLOSING_KM_S` | Below it a closing speed is rounding noise: the time is not fixed from it and it is never divided by | definition: rounding noise | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Two decimals below, s | `180.0` | `spectre/domain/decision_figures.py` `_TWO_DECIMALS_BELOW_S` | A time whose sigma is below it is shown to 2 decimals of an hour | display: rounding never moves a time by more than its sigma | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| One decimal below, s | `1800.0` | `spectre/domain/decision_figures.py` `_ONE_DECIMAL_BELOW_S` | A time whose sigma is below it is shown to 1 decimal of an hour | display: rounding never moves a time by more than its sigma | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Metres per second in a kilometre per second | `1000.0` | `spectre/domain/decision_figures.py` `_M_S_PER_KM_S` | Converts delta-V for the operator | definition | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Histogram bin widths, s | `(1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1800.0, 3600.0, 7200.0, 10800.0, 21600.0, 43200.0)` | `spectre/domain/decision_figures.py` `_BIN_LADDER_S` | The widths a TCA histogram's bins may take | display | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Bins across a histogram | `20.0` | `spectre/domain/decision_figures.py` `_BINS_ACROSS_RANGE` | A TCA histogram is drawn in about this many bins, unless the TCA's own uncertainty makes them wider | display | unassigned | 2026-11-03 (6b8ef20, 0.16.0) |
| Smallest burn with a size, km/s | `1e-12` | `spectre/domain/decision_transfer.py` `_NO_SIZE_KM_S` | Below it a burn has no size to scale a spread by | definition: rounding noise | unassigned | 2026-11-10 (6b87a96, 0.25.0) |
| Hours in a day, for NOTSO | `24.0` | `spectre/domain/notso_prior.py` `_HOURS_PER_DAY` | Converts days | definition | unassigned | 2026-11-04 (e325bd8, 0.21.0) |
| Seconds in an hour, for NOTSO | `3600.0` | `spectre/domain/notso_prior.py` `_SECONDS_PER_HOUR` | Converts hours | definition | unassigned | 2026-11-04 (e325bd8, 0.21.0) |
| Hundredths, for NOTSO | `100` | `spectre/domain/notso_prior.py` `_HUNDREDTHS` | Rounds a suggested P to hundredths | display | unassigned | 2026-11-04 (e325bd8, 0.21.0) |
| NOTSO timeline width | `1000.0` | `spectre/domain/notso_prior.py` `BAR_UNITS` | The width a NOTSO timeline is drawn on, in its own units | display | unassigned | 2026-11-04 (5a702cb, 0.22.0) |

## The element-set acceptance check

None of these is a judgement or a rule of thumb. They decide which element sets the engine accepts at all (SPC-201,
evaluation F-25 and F-34), on every path a set enters by, so each is listed with the format or the library it comes
from. The days in a year are read from the calendar, not held as a number.

| Constant | Value | Where | What it does | Source | Owner | Set |
|---|---|---|---|---|---|---|
| Element line length, characters | `69` | `spectre/astro/propagator.py` `TLE_LINE_LENGTH` | A line of any other length is refused; the checksum is its last column | definition: the two-line element format (Spacetrack Report No. 3, 1980) | unassigned | 2026-11-10 (SPC-201); held as `_TLE_LINE_LENGTH` for the checksum since audit F-272 |
| Lowest angle, degrees | `0.0` | `spectre/astro/elset_check.py` `_ANGLES[0].low` | The least inclination, node, argument of perigee and mean anomaly accepted | definition: the range of each angle | unassigned | 2026-11-10 (SPC-201) |
| Highest inclination, degrees | `180.0` | `spectre/astro/elset_check.py` `_ANGLES[0].high` | A greater inclination is refused, as 597.4 degrees was not (F-34) | definition: the range of an inclination | unassigned | 2026-11-10 (SPC-201) |
| Highest node, perigee and anomaly angle, degrees | `360.0` | `spectre/astro/elset_check.py` `_ANGLES[1].high` | A greater right ascension of the node, argument of perigee or mean anomaly is refused; the three share it | definition: a full turn | unassigned | 2026-11-10 (SPC-201) |
| First two-digit year of the 1900s | `57` | `spectre/astro/elset_check.py` `_FIRST_YEAR_OF_THE_1900S` | An epoch year from 57 is read as 1957 on, below it as 2000 on | definition: the two-line element format's year convention; the first satellite flew in 1957 | unassigned | 2026-11-10 (SPC-201); the same rule read the epoch in the UDL routes before |
| SGP4's decay error | `6` | `spectre/astro/propagator.py` `SGP4_DECAYED` | The error SGP4 sets when the radius falls under one Earth radius: read as re-entry, so the result says the object has decayed | definition: SGP4's own error code (Vallado and others, 2006) | unassigned | 2026-11-10 (SPC-200) |
| Longest refusal logged, characters | `1000` | `spectre/web/elsets.py` `_REFUSAL_LOG_LIMIT` | A refusal sentence is logged up to this many characters; every failure the check can name fits | display: a flood guard on the log | unassigned (Claude's choice, not a ruling) | 2026-11-10 (SPC-201) |
