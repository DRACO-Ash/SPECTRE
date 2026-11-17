# Training audit, 16 November 2026

The owner could not complete the first training scenario: BLUE-01 did not appear in the console, and could not be
picked in Asset Screening. The owner asked for every instruction in the training system to be checked so that each can
be carried out. Four agents played every tutorial and scenario in Chromium against a throwaway console, following
each instruction literally, and checked every answer and every physics claim with SGP4 (the sgp4 package and the
repo's own GMST). Screenshots and scripts were kept in the session's scratch space and are not part of the repository.

## Result

| | Blocker | Major | Minor |
|---|---|---|---|
| Tutorials and the training page (agent 1) | 4 | 13 | 12 |
| cadet_01, cadet_02, cadet_03, observer_02 (agent 2) | 3 | 7 | 4 |
| planner_03, observer_03, observer_04, observer_05 (agent 3) | 3 | 7 | 9 |
| planner_04, planner_05, theatre defence, gauntlet, timed cycle, levels (agent 4) | 4 | 10 | 7 |
| Found first (F0: the console tab never refreshed) | 1 | | |
| **Total** | **15** | **37** | **32** |

Every scenario had at least one blocker or taught geometry its own element sets contradict.

## Root causes

1. **F0.** The training page shows the console in a frame loaded once, so objects a scenario adds do not appear if
   the console was opened earlier. This is the owner's report.
2. **Stale synthetic data at today's date.** The synthetic element sets date from 2025 and the training never set the
   console's scenario time, so every tool propagated them 13 to 17 months: "STALE", element-set errors of about
   1,500 km, refused Monte Carlo and trajectory views, and geometry unlike the briefings.
3. **Briefings wrong even at their own epoch.** Seven scenarios state ranges, closing rates or times of closest
   approach that SGP4 on their own element sets contradicts (for example observer_03: "TCA T+18h, 1.8 km"; the pair
   never come within 257 km).
4. **Instructions name controls that do not exist** ("Quick-Add Blue", a solver selector, "Hill-frame visualiser",
   "Maximin", "Planning tab"), or tools that need UDL (Pattern of Life, HRR refresh, Monte Carlo in PoL).
5. **The Intercept Engine always plans the red satellite's manoeuvre**, its results view leaves the table, its
   defensive rows report requested rather than achieved distances, and the EVASION summary names the wrong satellite.
6. **The Assets panel shows names only**, so the orbital elements an instruction asks for cannot be read.
7. **Scoring rewards no work.** Self-certified objectives, 150 points for any submission, a challenge that passes on
   two ticks, and a timed challenge that passes when late.

## What follows

The fixes are in `docs/training-game-design.md`, section 10: console and training-mechanics faults in 0.47.0; the old
scenarios and tutorials are rewritten as real-data missions with computed answers and a test that plays every mission
in 0.48.0 and 0.49.0.

## Findings, by agent


### agent-1 findings (6 tutorials + training page)

Summary: 4 BLOCKER, 13 MAJOR, 12 MINOR. Evidence in audit/agent-1/ (t1.py..t8.py, screenshots, intercept_result.txt,
decision_result.txt, decision_panel.txt). F0 not hit (console opened first after start).

## Blockers
1-1 manoeuvre_planning step 3 (tutorials.yaml:139-144): "Hill-frame visualiser" not in Intercept Engine output.
all_intercepts_result.html has no geometry control; "Relative Geometry" exists only in intercept_result.html:227-251,
rendered only by POST /plan/maneuver/apply-intercept which nothing calls. Decision Engine "Show trajectory" never appears
(cells "Not computed: red orbit out of date").
1-2 full_engagement_cycle Detect (tutorials.yaml:189-193, 108-113, 34-38): HRR Refresh "Not connected to UDL"; PoL
"Enter UDL username and password." Works with UDL + real NORAD numbers (INFERENCE).
1-3 Monte Carlo (threat_assessment 4, full_engagement 2; tutorials.yaml:115-119, 195-199): location never named; PoL MC
needs a PoL run (UDL); Decision Engine Manoeuvre hypothesis "Nothing was sampled ... red orbit is out of date".
1-4 full_engagement Act (tutorials.yaml:212-217; training_scenario_active.html:65-189): submit form has no manoeuvre
option selector and no reasoning field; options read-only on detail page (training_scenario_detail.html:86-106).

## Major
1-5 wrong skill axes listed (tutorials.yaml:216-217) vs gamification.yaml:8-36 (Situational Awareness, Manoeuvre
Planning, Decision Quality, Operational Tempo, Efficiency).
1-6 HRR described as "High-Risk Register" threat ranking (tutorials.yaml:32, 102-106, 191); really UDL/JCO "High Rate
Revisit" watchlist (operator.html:235), rank copied from JCO, red/blue by country (udl.py:1323-1360).
1-7 Conf does not feed Expected Value ("moves no figure"); selectors are Minimax, Expected Value, Minimin; tutorial's
"Maximin maximises your best-case" is wrong (tutorials.yaml:164-181; decision_panel.html:236-239, 341-343).
1-9 Intercept Engine workflow wrong (tutorials.yaml:43-44, 129-132): no type selection, one button runs 23 methods;
rows are red's approach; no "CW offset" (CW_DRIFT "Proximity Manoeuvre (CW)"); defensive rows COLA, EVASION, FORMATION.
1-12 "Free-Play has no time pressure" untrue (tutorials.yaml:47-50): observer_02 15 min, planner_03 10 min.
1-13 "all synthetic, no operational systems accessed" overstated (tutorials.yaml:17; training.html:47-48): console offers
UDL connect and Fetch TLE; Threat Sweep lists real HRR objects; hand-added objects stay (INFERENCE).
1-15 "tick each objective"/"self-assess" hide answer scoring (tutorials.yaml:73-75; training_dashboard.html:15-17,28-29;
training.py:448-457, 495-496).
1-16 debrief does not list objectives met; says "Review the objectives above" (training_debrief.html:130-132).
1-18 page not refreshed after completion/level-up (training_tutorial.html:251-258; training.html:50-52, 62-133,
175-177, 221-243): sidebar points, banner level, tutorial list, scenario list stale until reload.
1-19 Recommended Next Step / progress bar hide real level conditions (gamification.py:324-349; training.html:82-84;
training_dashboard.html:79-85, 145-160): advice "weakest axis Efficiency" though only challenges grow it; 3-passes and
3-challenges conditions never shown; sidebar and dashboard give conflicting first steps.
1-20 empty scored submission earns 150 pts and can level up (training.py:503-525): score 0 NOT PASSED "+150", LEVEL UP.
1-21 training objects removed only by the 2 Return to Operations buttons; going to / directly leaves them; time in
training accrues only via buttons.
1-28 synthetic TLE epochs 2025; tools use current time: Decision Engine "524.5 d old STALE", custody lost, CA and sampling
refused; Intercept Engine "element-set error 1487.4 km". Root of 1-1 and 1-3.

## Minor
1-8 decision_evaluation names not in UI: "Electronic interference" (types are Manoeuvre, Sensor Retask, Posture Change,
No Action), "dV cost" (really "Cost", 0-1; dV under "Our burn"), "Hold" (= No Action).
1-10 truncated sentence tutorials.yaml:136-137 "a finite dV budget for Always check".
1-11 orientation tab names (tutorials.yaml:22-26): Assets is a left sidebar tab; PoL labelled "Historical PoL"; Asset
Screening not mentioned. Real top tabs: Threat Sweep, Asset Screening, Intercept Engine, Historical PoL, Decision
Engine, GCAT.
1-14 "levels unlock new capabilities" (tutorials.yaml:55): levels unlock only content (INFERENCE).
1-17 "Submit" vs real "Submit & Score" / "Finish Exploration" (training_scenario_active.html:168).
1-22 sticky banner (training.html:37-45, z-index 100) covers header Return to Operations after 48 px scroll.
1-23 "Training" link inside console frame (operator.html:55-60) loads a nested training page.
1-24 unlock lists show ids/derived names not titles.
1-25 Recent Activity shows scenario ids and US date %m/%d (training_dashboard.html:194, 209).
1-26 locked tutorials readable (GET returns 200 at Level 1).
1-27 NOTSO never spelled out; PoL error says "UDL (credentials)" but option labelled "Direct" (pol.py:531-533).
1-29 (INFERENCE) Level 5 needs 3 challenge passes; at Level 4 only analyst_gauntlet (350/350 needed), repeats count.

## Step verdicts (summary)
orientation: step 1 not accurate; 2 with difficulty; 3 achievable (HRR description wrong); 4 PoL not achievable without
UDL; 5 with difficulty; 6 wrong; 7 achievable. +50; level 2 needs 100 pts, two L1 tutorials give 80.
scenario_loading: achievable; misleading tick; labels; +30, unlocks nothing.
threat_assessment: HRR wrong/not achievable; PoL not achievable; MC not achievable.
manoeuvre_planning: 1 with difficulty; 2 truncated; 3 Hill-frame not achievable.
decision_evaluation: matrix lower=better ok; fields with difficulty; Maximin not achievable.
full_engagement_cycle: Detect, Assess, Act not achievable; Plan with difficulty; Decide achievable via Decision Engine
"Your decision ... Rationale ... Record decision".
Training page: nav ok; points and level-ups work in DB; level display stale until reload; Return to Operations works
and removes objects.

## Real data
Reading-only steps unaffected. HRR and PoL (and PoL MC) need UDL + real NORAD numbers. Decision Engine computed results,
MC and Show trajectory need current TLEs. Intercept Engine works on either but synthetic results propagated 17 months.

## Confusing or tedious
Conflicting first steps; nothing changes after Mark Complete until reload; tutorials prose only with no link into the
console; six terms not in UI ("High-Risk Register", "CW offset", "Maximin", "electronic interference", "dV cost",
Hill-frame visualiser in Intercept Engine); "weakest axis Efficiency" through Levels 2-4; banner says synthetic while
console shows real HRR objects and a live UDL chip.

### agent-2 findings (cadet_01, cadet_02, cadet_03, observer_02)

Summary: 3 BLOCKER, 7 MAJOR, 4 MINOR. Evidence in audit/agent-2/ (run.py, run2.py, physics.py, <tag>_result.json,
<tag>_NN_*.png). sgp4 2.27, 10 s steps.

## Physics (FACT)
cadet_01: "RAAN 45.0 puts BLUE-01 over 128.5 W" correct (128.535 W); drift 0.035-0.040 deg, not 0.08 deg.
cadet_02: no conjunction; formation 0.009-1.38 km for 24 h, closing <= 1.5 m/s; four passes within 20 m, closest 9 m at
T+2.49 h; 1.38 km at T+14 h.
observer_02: 0.7-4.2 m/s closing (not 120), TCA T+7.36 h 1.10 km (not T+4.5 h 2.1 km), RAAN offset 0.05 deg (4.6 km
cross-track, not co-planar).
cadet_03: already 1.27-2.50 km apart for 12 h (Hill at epoch R -0.10, T -1.66, N 1.86 km); nothing to approach.

## Blockers
2-1 RAAN cannot be read anywhere (cadet_01 step 3, Obj 2; scenarios.yaml:61-65; partials/blue_list.html:11-19): list
item is name + remove button; RAAN rendered only in pol_results.html and pol_manoeuvre_detail.html (UDL PoL);
red_orbit_info.html shows Lon, Inc, Period, Alt, Ecc but not RAAN. Answer only in instruction text. Fix: expandable
element card (epoch, a, e, i, RAAN, argp, M, sub-satellite longitude) on blue and red lists.
2-6 no solver selection in Intercept Engine (scenarios.yaml:127, 388-389, 451, obj_select_cw; operator.html:470-546):
single "Calculate All Intercepts"; single-method POST /plan/maneuver/apply-intercept (maneuver.py:838) called by nothing;
no row named CW or Hill-frame (CW rows: CW_DRIFT, RBAR_HOP, VBAR_HOP, HBAR_HOP, NMC). Same wording at
scenarios.yaml:168, 189, 312, 520, 732.
2-7 engine runs at today, not scenario epoch (operator.html:504; maneuver.py:1055-1066 blank = now; preload never sets
scenario start; scenario_epoch_utc never rendered): "element-set error 1485.7 km"; every approach row "No approach";
at epoch pairs are 0.6, 2.5, 14.9 km apart. Fix: set session scenario start (field operator.html:314 reads it) to
scenario_epoch_utc on start; show epoch.

## Major
2-2 fallback load path cannot be followed (scenarios.yaml:60; training_scenario_detail.html:33-58): no "Quick-Add Blue";
no TLE lines shown anywhere. Real path Assets -> Blue -> Name + "TLE lines 1 & 2" -> "Add Blue Asset". Assets panel opens
on Red sub-tab.
2-3 BLUE-01 not selectable in Asset Screening (routes/threat.py:3370-3403 builds from state.hrr_objects only;
operator.html:432). Manual Asset TLE works but ranks 8 actors CRITICAL "0.36 m/s, 11h 57m" in a no-threat scenario;
labels "[99001] [99001]". Real HRR object (SKYNET 5A [30793]) selectable.
2-8 cadet_02 conjunction not in TLEs (scenarios.yaml:360-366): see physics. Fix: regenerate true crossing TCA T+14 h
0.8 km; add a test that checks briefing figures against SGP4.
2-9 cadet_02 engine plans no Blue avoidance; miss distances are its own inputs (maneuvers.py:876-947, 1200-1256;
maneuver.py:628, 1817-1823): COLA burns red, reports desired_miss_km (max(Approach within, 1 km)); FORMATION 5.0 km
default; EVASION burns blue but text "places DEBRIS-07 10.1 km from threat"; TCA taken as start + coast (1 h).
2-10 observer_02 intelligence contradicts TLEs (scenarios.yaml:104-106): see physics; computed TCA 7.4 refused (±0.5).
2-11 cadet_03 engine moves the wrong satellite (scenarios.yaml:449-455; operator.html:480): "R-Bar hop: UNKNOWN-RSO comes
within 1.3 km of BLUE-INS".
2-12 cadet_03 standoff physics misleading (scenarios.yaml:452-453): fixed radial offset drifts along-track at 1.5 n x;
hold points lie on V-bar (INFERENCE on wording).

## Minor
2-4 cadet_01 drift 0.08 vs TLE 0.035-0.040 (scenarios.yaml:42).
2-5 numbered steps run together (training_scenario_active.html:57 pre-line with folded >).
2-13 names: "intercept_range_km" (UI "Miss Dist"/"Achieved Miss"/"Closest approach"); "Blue asset"/"Red track" (UI
"Blue Target"/"Red Satellite"); Blue sub-tab unmentioned; YAML header km/s.
2-14 training objects show "Data Mode: UNVERIFIED" in the engine, not SYNTHETIC.

## Step verdicts
cadet_01: console ok; confirm BLUE-01 with difficulty (Blue sub-tab); fallback not achievable; RAAN not achievable;
2.0 m/s ok; submit 60/60. Owner's Asset Screening try not achievable.
cadet_02: confirm with difficulty; 0.8 from briefing; select ok; run >=2 with difficulty; lowest dV >5 km meaningless
(COLA 0.01/1.0, FORMATION 0.07/5.0, EVASION 0.15/10.1 at epoch); submit 130/130 even without engine.
cadet_03: select CW solver not achievable; relative motion with difficulty (only NMC failure text); >1 km check not
achievable; obj_select_cw ticked anyway; 140/140.
observer_02: Hohmann/Lambert with difficulty (start blank: all "No approach"; at epoch "Already within", LAMBERT
7,996 m/s); T+4.5 h from text (true 7.36 h); posture still correct; 15-min limit easy; 100/100.

## Confusing or tedious
Steps give away every answer; self-cert passes with no work; typed answer not ticked scores 0 and answer box does not
tick its checkbox; cadet_01 four-line RAAN lecture; engine rows buried in provenance prose, expanded one by one; manual
screening "[99001] [99001]" and CRITICAL threats in a no-threat scenario; after passing cadet_01 sidebar "Level 2 100%"
but stays Level 1 (Orientation needed, not said); cadet_03 named cadet but needs Level 2.

### agent-3 findings (planner_03, observer_03, observer_04, observer_05)

Summary: 3 BLOCKER, 7 MAJOR, 9 MINOR. Evidence in audit/agent-3/.
Tested starting from Free-Play with Start Scenario, console opened first time after Start (F0 not hit).

## Physics checks (FACT, sgp4 + repo _gmst_deg)
- planner_03: claim TCA T+4.5h 1.2 km. Computed 7.28 km at T+4.5h; true closest 1.10 km at T+7.36h (15:21:40Z).
- observer_03: claim GEO-COMM at 75.0 E. Computed 116.43 E (75.0 is the TLE RAAN).
- observer_03: claim TCA T+18h 1.8 km. Computed 257.6 km at T+0, 266.7 km at T+18h; no conjunction in 36 h.
- observer_04: objects ~515 km apart steady. observer_05: ~15,366 km apart.

## Findings
3-1 BLOCKER planner_03 (scenarios.yaml:189, :210-232; operator.html:465-556): names solver methods that do not exist
("Hohmann In-Track", "Lambert In-Track/Radial"); one "Calculate All Intercepts" button runs 23 methods; Intercept Engine
computes RED's approach, not BLUE-02's evasion; "OPTIMAL 12 m/s / 6.1 km" never appears; all objectives tick-only so any
pick passes (190/190). Fix: rewrite steps (set Manoeuvre Start to TCA, Max dV 30, Calculate All, Calculator sub-tab,
expand Avoidance rows EVASION/FORMATION/COLA, read Total dV and Miss Dist); replace manoeuvre_options with engine figures
or delete; optionally answer objective on EVASION dV.
3-2 BLOCKER observer_03 avoidance (scenarios.yaml:497-499, :519-522): COLA burns DRIFTER-09 (red) and reports its own
1.0 km target (maneuvers.py:893,912 sv_red_burn); FORMATION reports its own 5.0 km (maneuvers.py:1558-1567); EVASION
257.6 km only because objects are already ~257 km apart; red-approach rows pass both filters. Fix with real conjunction,
direct to EVASION with start at TCA and Max dV 2.5, explain COLA/FORMATION show requested distance.
3-3 BLOCKER observer_03 "Enter T+18h for Objective 2" (scenarios.yaml:517-518; training.py:448-457): answer parsed as
number; "T+18h"/"18h" refused (160 with obj 2 lost); objective also needs tick; passes anyway 160 vs 150. Fix text
"tick Objective 2 and type 18"; optionally strip "T+" and "h".
3-4 MAJOR planner_03 TCA wrong (scenarios.yaml:165-166): see physics.
3-5 MAJOR Intercept results hidden (operator.js:404-412 switchToTradeSpace(); all_intercepts_result.html:86-101): view
jumps to Trade-Space; no Miss Dist column, must expand up to 23 rows; intercept_range_km never shown.
3-6 MAJOR defensive rows mislabelled (maneuver.py:621-630, :1816-1866): EVASION summary "places RED-01 11.0 km from
threat" though burn is BLUE's (maneuvers.py:1210-1220); COLA moves red and shows 1.0 km target; FORMATION 5.0 km target;
summary says "0 m/s" where row shows 0.15 m/s.
3-7 MAJOR scenario_epoch_utc never applied (only scenarios.py:77,:157): Manoeuvre Start blank = now
(maneuver.py:1061); tools propagate 484 days past epoch; RED-01 "484.5 d old STALE". Fix: set state.scenario_start from
scenario epoch in preload, clear on leave.
3-8 MAJOR planner_03 detail page gives the answer away (training_scenario_detail.html:86-106): shows invented options
marked INFEASIBLE/Valid/OPTIMAL before Start.
3-9 MAJOR observer_04 (scenarios.yaml:584-590; decision_panel.html:221-226): no action type for Electronic Interference;
binding objects changes Minimax pick (Sensor Retask -> Posture Change); response cost/reversibility/time unspecified.
3-10 MAJOR observer_03 geometry false (scenarios.yaml:492-494): see physics. GMST at epoch 328.58 deg.
3-11 MINOR Max dV not set by instructions (default 171.8 m/s).
3-12 MINOR timer/steps/objectives on the Free-Play tab, not visible in the console.
3-13 MINOR "Tick Objectives 3, 4 and 5" omits 1 and 2 (scenarios.yaml:522, :661): following it scores 160/210, 135/180.
3-14 MINOR observer_04 names UI that does not exist: "Planning tab", "Evaluate Scenario", "MEDIUM", "Minimax strategy
view" (real: Decision Engine tab, Conf 0.5, Selector Strategy, Evaluate).
3-15 MINOR observer_04 objective 5: Minimax and Expected Value pick the same response in every run.
3-16 MINOR observer_05 says "enter" but UI is a radio.
3-17 MINOR numbered steps run together (folded YAML > rendered pre-line, training_scenario_active.html:50).
3-18 MINOR J2_DRIFT FAILED "date value out of range" at observer_03 epoch; at now arrival 2130.
3-19 MINOR scenarios.yaml header stale (NOTSO panel and Monte Carlo exist, pol.py:1080,1250,1385; Assets panel shows
names only; engine outputs shown in m/s and "Miss Dist").

## Real catalogue objects
planner_03/observer_03: real objects let TCA/range come from Asset Screening/Conjunctions instead of the briefing
(removes 3-4, 3-10); do not fix 3-1, 3-2, 3-5, 3-6. observer_04: binding real red adds NOTSO priors. observer_05: real
NORAD number enables Historical PoL and NOTSO correlation; synthetic 99050 refused by PoL.

## Confusing or tedious
- observer_05 states every answer in text; objects unused.
- Decision Engine results buried under long "Training only" small print.
- Intercept Engine header "No red approach both reaches the target" reads as an alarm.
- Objects from earlier scenarios persist until leaving training; Reset/Abandon/Submit do not remove them
  (training.py:251-255, 287-311).
- Debrief shows "Operational Tempo +30" on scenarios with no tempo objective.
- Synthetic objects show "484.5 d old STALE".

### agent-4 findings (planner_04, planner_05, theatre_defence, analyst_gauntlet, operator_timed_full_cycle, gamification)

Summary: 4 BLOCKER, 10 MAJOR, 7 MINOR. Evidence in audit/agent-4/.

## Cross-cutting (FACT)
X1 "Calculate All Intercepts" runs all 23 methods in one click (0.6-2.3 s); no single method.
X2 view jumps to Trade-Space after each run (operator.js:412 switchToTradeSpace()); table hidden on Calculator.
X3 scenario start does not set console scenario time; blank Manoeuvre Start = now (maneuver.py:1061-1062).
   planner_05: 669.7 km at epoch, 35.3 km now; theatre BLUE-A v CRIMSON-01: 772.8 km epoch, 212.4 km now.
X4 F0 on every scenario after the first; after reload objects from earlier scenarios pile up.
X5 Assets panel shows names only (no elements, RAAN, TLE lines).
X6 each new DE adversary row gets P 0.5; three rows refused ("P sum to 1.5"); P step 0.05 so 0.33 rejected; UI never
   says "robust".
X7 engine's RED satellite manoeuvres; COLA moves red; EVASION moves blue.
X8 objectives not numbered in UI but workflows cite "Objective 2", "Objectives 4 and 5", "Objective 6".

## Blockers
4-3 planner_05 (scenarios.yaml:797-802): engine always moves red, plans TARGET-LEO chasing BLUE-PH; BLUE-PH TLE not
shown so sides cannot be swapped. Fix: swap sides / manoeuvring-side selector / show TLEs.
4-4 analyst_gauntlet chaining not implemented (scenarios.yaml:246-276; challenge_scenarios parsed scenarios.py:85,165,
never used); opening a sub-scenario replaces the panel, orphans the attempt, loses first-try bonus.
4-5 gauntlet passes on two ticks: 350/350 PASSED +500 with no work (scenarios.yaml:263-271).
4-7 operator_timed_full_cycle passes late: at 21 min 400/400 vs pass 400, +400, counts as challenge pass
(scenarios.yaml:333-346; training.py:633). planner_03 also passes late (late max 160, pass 100).

## Major
4-1 planner_04 (scenarios.yaml:706) "~850 km, slowly closing": SGP4 1,140.6 km at epoch opening to 1,148.4 km at
+72 h; SHADOW-01 1.55 deg east with higher mean motion, drifting away.
4-2 planner_05 (scenarios.yaml:775, :799) "1,840 km", "close ~1,810 km": TARGET-LEO 669.7 km behind BLUE-PH, equal mean
motions; 35.3 km at now.
4-6 gauntlet briefing claims rules that do not exist (scenarios.yaml:253-256): time limit no effect (46 min PASSED),
"0.75 decision quality" metric absent, Reset exists despite "No restart", no tool_workflow.
4-8 training runs at now, not scenario epoch (training.py:287-311; maneuver.py:1061).
4-9 results hidden after each engine run (operator.js:412).
4-10 theatre ranking dV ambiguous (scenarios.yaml:886-892): 21 dVs per run; MIN_TIME 37 m/s always; "No approach" rows
tiny dVs. Fix: rank on "Most likely course of action" dV.
4-11 theatre per-asset allocation (scenarios.yaml:893-895): one pick per evaluation; three rows refused at default P.
4-12 operator_timed efficiency "within 20%" tick box with no field (scenarios.yaml:340-343).
G-1 scenario_completed pays 150 pts + decision quality +45 for any scored submission incl. zero ticks and fail
(gamification.yaml:46-53; training.py:512-514); any 7 submissions meet Level 4 DQ gate.
G-2 Level 5 needs 3 challenges but only the gauntlet opens below it; repeats count (gamification.yaml:134-140);
simulation reaches Level 5 at 3,130 pts after 4 gauntlet passes (8 ticks with 4-5).

## Minor
4-13 operator_timed compares RAAN the UI never shows (scenarios.yaml:310); RAAN alone does not fix a GEO slot.
4-14 theatre "All five axes scored" false (scenarios.yaml:841): no manoeuvre_planning objective.
4-15 workflows cite objective numbers the UI does not show (scenarios.yaml:730, 734, 738, 895).
4-16 gauntlet objectives show raw scenario ids (scenarios.yaml:266, 270).
4-17 decision step wording "robust response" vs UI headline pick; P rule not explained (scenarios.yaml:315, 735-737).
G-3 Abandon leaves attempt open and costs first-try bonus (training.py:153-162).
G-4 sidebar stats and banner stale after submit (training.html:114-124).

## Works (FACT)
Point weights and awards match gamification.yaml; unlock entries consistent; theatre 30-min limit enforced (31 min
470 fail); engine runs 0.6-2.3 s; each scenario completable in its limit; no step in the subset needs UDL.

## Confusing or tedious
Re-click Calculator after each run (6 times in theatre); leftover objects clutter dropdowns; challenges under
"Free-Play Scenarios" heading; "+150 pts" vs "+400 training points" and two unrelated per-axis blocks in debrief; timer
reaches 0:00 silently; long "UNVERIFIED" banner and "Training only ... lookup model" small print; "Run >=2 methods" reads
as a choice but the button runs all 23.
